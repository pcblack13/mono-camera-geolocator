r"""Automatic geolocation-error measurement engine (Stage D).

Compares the solved view of the world against satellite imagery and returns
the ACTUAL geolocation error as a field of vectors - no field work, no manual
point picking:

  1. ortho      redraw the oblique photo as a north-up map using pose + DEM
                ("where WE think everything is")
  2. satellite  Mapbox mosaic of the same ground, on the same metre grid
                ("where everything really is", to within the basemap's own
                few-metre georeferencing)
  3. compare    overlapping tiles; per tile, phase correlation measures how
                far our content sits from the satellite's -> (dE, dN) metres
  4. filter     featureless tiles skipped, weak peaks dropped, and a
                neighbour-consistency pass removes false locks
  5. diagnose   each vector split into radial (along the sightline = DEM
                height channel) and tangential (across = pose channel)

This module is pure computation - no matplotlib, no Tk.  The GUI's Stage D
page and tools\analysis\error_map.py (CLI + figures) both drive it.

★ VENDORED, AND KEPT CLOSE TO UPSTREAM ON PURPOSE
--------------------------------------------------
Two deliberate departures from the upstream file, and nothing else:

  * `mosaic_writer` is threaded through `run()` into `fetch_satellite()`, so
    the satellite reference comes from THIS application's imagery service
    (rate limits, tile cache, offline mode, licence gate) rather than a direct
    provider call.  Upstream calls `mapbox_api` there; we have no such module.
  * the imports are relative, because this is a package inside the backend.
  * `cloud_mask` (2026-09-10): upstream §10 documents the basemap-cloud gap and
    the mask that works on it, but never built it.  It is built here as the
    `Params` switch upstream prescribes — OFF by default, because white roofs
    can trigger it — and it removes cloud from the content mask before any
    tile is matched.  `Result.cloud` carries the mask for reporting.

Everything else is upstream's, byte for byte, so the next port is a diff and
not a merge.  That is also why the code below does not match this repo's house
style and is not reformatted.

Last port: 2026-09-10, from `heatmap_kit/reference/error_map.py`
(`docs/HEATMAP_ALGORITHM_UPDATES.md` §1-§6).  It brought the affine ECC
rescue, per-tile reliability, tile-size-from-geometry, and the widened catch
in the zoom step-down.  EVERY ONE OF THOSE IS OFF AT ITS DEFAULT: a run that
sets no new `Params` field produces the same tiles it did before the port,
which `app/tests/test_error_map_updates.py` pins.
"""
from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass, field

import cv2
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling

from . import stage_b


@dataclass
class Params:
    gsd: float = 1.0            # ortho ground sample distance, m/cell
    max_range: float = 1100.0   # how far out to rectify, m
    tile: int = 128             # correlation tile size, m
    stride: int = 64            # tile step, m
    min_valid: float = 0.75     # tile must be at least this covered
    min_texture: float = 3.0    # high-pass std below this = featureless
    min_response: float = 0.06  # phase peak below this = no lock
    max_shift: float = 25.0     # larger 'match' = false lock
    sat_zoom: int = 17
    bands: tuple = ((0, 300, "near 0-300"), (300, 500, "mid 300-500"),
                    (500, 1100, "far 500-1000"))
    # mutual-information second chance for tiles phase correlation rejected
    # (appearance mismatch, e.g. different season in the basemap)
    mi_rescue: bool = True
    mi_half: int = 8            # search +/- this many metres around the seed
    mi_sharp_min: float = 2.0   # peak must stand this many sigmas above the surface
    mi_seed_radius: float = 300.0
    mi_consistent_m: float = 4.0
    # coarse-to-fine: after a tile locks, re-match its four half-size
    # sub-tiles with the satellite pre-shifted by the coarse answer, so each
    # sub-tile only needs to find a small residual.  Recovers the ~1-2 m of
    # real local structure a full-size tile averages away.
    fine_pass: bool = True
    fine_residual_max: float = 8.0   # a sub-tile 'refinement' larger than this is noise
    # ── the three additions of 2026-09-10, EVERY ONE OFF AT ITS DEFAULT ──────────
    # The rule that governs all of them: a run that changes no field below produces
    # bit-identical output to the engine before they existed. That is what lets an
    # existing measurement stay comparable with a new one.
    #
    # Affine second chance for tiles still rejected after the MI pass. At grazing
    # incidence a tile is not merely SHIFTED against the satellite, it is internally
    # SHEARED: the DTM's own height error displaces the ray intersection by
    # (amplification x dz), and the amplification varies across the tile. Measured
    # upstream, the spread inside one 128 m tile is 1.96 on a grazing ground scene
    # against 0.84 on a nadir flight — ~5.9 m of internal warp at 3 m of height error
    # against ~2.5 m. Phase correlation solves for a pure translation and finds no
    # peak; an affine ECC fit does. Rescue only: it never touches a tile that already
    # locked, so existing results cannot regress.
    # OFF by default on purpose — it changes WHICH ground gets measured, so a scene
    # that already locks most of its tiles reports a different (slightly larger)
    # median as previously unmeasurable hard tiles join. Turn it on for the oblique,
    # grazing scenes this product actually watches.
    ecc_rescue: bool = False
    ecc_iters: int = 60
    ecc_eps: float = 1e-4
    ecc_shear_max: float = 0.35      # |affine linear part - I| beyond this = nonsense
    # Per-tile reliability. A height error of sigma_dtm metres moves the intersection
    # by (amplification x sigma_dtm) along the sight line, so the same DTM makes a
    # near-nadir tile trustworthy and a grazing one useless. Computed ALWAYS (it is
    # two columns on every tile); it only GATES when reliability_max > 0.
    sigma_dtm: float = 3.0           # 1-sigma DTM height error, metres
    reliability_max: float = 0.0     # >0: drop tiles whose expected sigma exceeds this
    # Tile size from the scene's geometry. A large tile holds more texture (good at
    # nadir) but spans more amplification change (bad at grazing incidence), so the
    # right size follows the geometry. The decider is the AREA-weighted median
    # amplification over the ortho footprint — stated once so the thresholds mean one
    # thing. Off by default so no existing run changes its tile size.
    tile_auto: bool = False
    tile_auto_sizes: tuple = (128, 96, 64)       # chosen when amp is below ...
    tile_auto_thresholds: tuple = (2.5, 3.5)     # ... these; else the last size
    # ★ VENDOR EDIT — basemap cloud (upstream §10, the known gap). The content
    # mask treats cloud in the basemap as content, the texture gate passes at
    # cloud EDGES, and the consistency filter cannot reject cloud-edge false locks
    # because an edge is a continuous line — neighbouring false locks agree with
    # each other. Off by default: white roofs can trigger it.
    cloud_mask: bool = False
    cloud_min_brightness: int = 165      # darkest channel above this ...
    cloud_max_saturation: float = 0.18   # ... and (max-min)/max below this = cloud
    cloud_close_px: int = 9              # morphological close, to fill thin gaps


@dataclass
class Result:
    ortho: np.ndarray           # HxWx3 rectified photo
    sat: np.ndarray             # HxWx3 satellite on the same grid
    inside: np.ndarray          # HxW bool: ortho has content here
    rng_g: np.ndarray           # HxW range from camera (NaN outside)
    origin: tuple               # (E of col 0, N of row 0), cell centres
    tiles: list = field(default_factory=list)   # per-tile dicts
    params: Params = None
    cloud: np.ndarray = None    # ★ VENDOR EDIT: HxW bool, basemap cloud, when masked

    @property
    def good(self):
        return [t for t in self.tiles if t["ok"]]

    def zone_summary(self):
        """[(band name, n, median err, dE, dN, radial, tangential), ...]"""
        out = []
        for lo, hi, name in self.params.bands:
            g = [t for t in self.good if lo <= t["range"] < hi]
            if not g:
                continue
            med = lambda k: float(np.median([t[k] for t in g]))
            out.append((name, len(g), med("err"), med("dE"), med("dN"),
                        med("radial"), med("tangential")))
        return out


def dem_grid(dem, E, N):
    """Vectorised bilinear DEM height at meshgrids E (cols) / N (rows)."""
    inv = ~dem.ds.transform
    col = inv.a * E + inv.b * N + inv.c - 0.5
    row = inv.d * E + inv.e * N + inv.f - 0.5
    c0 = np.floor(col).astype(int); r0 = np.floor(row).astype(int)
    fc = col - c0; fr = row - r0
    h, w = dem.arr.shape
    ok = (c0 >= 0) & (r0 >= 0) & (c0 < w - 1) & (r0 < h - 1)
    c0c = np.clip(c0, 0, w - 2); r0c = np.clip(r0, 0, h - 2)
    a = dem.arr
    z = (a[r0c, c0c] * (1 - fr) * (1 - fc) + a[r0c, c0c + 1] * (1 - fr) * fc +
         a[r0c + 1, c0c] * fr * (1 - fc) + a[r0c + 1, c0c + 1] * fr * fc)
    z[~ok] = np.nan
    return z


def ground_bounds(R, C, K, dist, dem, w, h, p: Params):
    """Rough ground footprint: raycast a coarse pixel grid, keep hits in range."""
    pts = []
    for v in range(h - 1, 0, -max(1, h // 18)):
        for u in range(0, w, max(1, w // 24)):
            hit = stage_b.raycast(u, v, R, C, K, dist, dem.Z, dem.res)
            if hit is None:
                continue
            r = float(np.hypot(hit[0] - C[0], hit[1] - C[1]))
            if r <= p.max_range:
                pts.append((hit[0], hit[1]))
    if len(pts) < 8:
        raise RuntimeError("could not establish a ground footprint - is the "
                           "DEM loaded and does it cover the scene?")
    q = np.array(pts)
    lo = q.min(axis=0) - 60; hi = q.max(axis=0) + 60
    return lo[0], lo[1], hi[0], hi[1]


def build_ortho(R, C, K, dist, photo, dem, bounds, p: Params):
    """North-up rectification + per-cell range and source-pixel u."""
    e0, n0, e1, n1 = bounds
    E = np.arange(e0, e1, p.gsd)
    N = np.arange(n1, n0, -p.gsd)                  # row 0 = north
    EE, NN = np.meshgrid(E, N)
    ZZ = dem_grid(dem, EE, NN)

    P = np.stack([EE.ravel(), NN.ravel(), ZZ.ravel()], axis=1)
    valid = np.isfinite(P[:, 2])
    rng = np.hypot(P[:, 0] - C[0], P[:, 1] - C[1])
    valid &= rng <= p.max_range

    rvec = cv2.Rodrigues(R)[0]
    tvec = (-R @ C).reshape(3, 1)
    cam_z = (P[valid] - C) @ R[2]
    vin = np.where(valid)[0][cam_z > 1.0]

    uv = np.full((len(P), 2), -1e9, np.float64)
    for s in range(0, len(vin), 500_000):
        idx = vin[s:s + 500_000]
        prj, _ = cv2.projectPoints(P[idx].reshape(-1, 1, 3), rvec, tvec, K, dist)
        uv[idx] = prj.reshape(-1, 2)

    h, w = photo.shape[:2]
    mapx = uv[:, 0].reshape(EE.shape).astype(np.float32)
    mapy = uv[:, 1].reshape(EE.shape).astype(np.float32)
    inside = (mapx >= 0) & (mapy >= 0) & (mapx < w) & (mapy < h)
    ortho = cv2.remap(photo, mapx, mapy, cv2.INTER_LINEAR,
                      borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    ortho[~inside] = 0
    rng_g = rng.reshape(EE.shape); rng_g[~inside] = np.nan
    u_g = mapx.copy(); u_g[~inside] = np.nan
    return ortho, inside, rng_g, u_g, (E[0], N[0])


def _covers(tif, bounds, dem_epsg):
    """Does a cached mosaic actually span the ground we are about to match?"""
    e0, n0, e1, n1 = bounds
    try:
        with rasterio.open(tif) as src:
            if src.crs is None or src.crs.to_epsg() != dem_epsg:
                return False
            b = src.bounds
    except Exception:                                     # noqa: BLE001
        return False
    return b.left <= e0 and b.right >= e1 and b.bottom <= n0 and b.top >= n1


def fetch_satellite(cam_ll, bounds, origin, shape, dem_epsg, cache_dir, p: Params,
                    log=lambda s: None, mosaic_writer=None):
    """Mosaic on the ortho grid; the GeoTIFF is cached per flight in cache_dir.

    ★ LANDEXPLORER VENDOR EDIT (the only behavioural change in this file). The
    standalone tool calls its own ``mapbox_api.satellite_geotiff`` here. In the
    app the imagery must come through ``ImageryService`` instead, so the writer
    is INJECTED:

        mosaic_writer(lat, lon, radius_m=..., zoom=..., out_path=..., epsg=...)

    It must write a north-up GeoTIFF in EPSG:``epsg`` covering ``radius_m``
    around the camera, and may raise ``RuntimeError`` mentioning "cap" to ask
    for a coarser zoom — the same protocol the original used, so the
    step-down loop below is untouched. Routing it through the service is what
    keeps the provider allow-list, the disk tile cache, the usage ledger and
    offline mode in force for this stage too.
    """
    if mosaic_writer is None:
        raise RuntimeError(
            "no satellite source supplied — Stage D needs a mosaic_writer that "
            "fetches imagery through the application's imagery service."
        )
    e0, n0, e1, n1 = bounds
    corners = np.array([[e0, n0], [e0, n1], [e1, n0], [e1, n1]])
    lat, lon = cam_ll
    tif = os.path.join(cache_dir, "satellite_utm.tif")
    import pyproj
    to_xy = pyproj.Transformer.from_crs(4326, dem_epsg, always_xy=True)
    camE, camN = to_xy.transform(lon, lat)
    radius = float(np.max(np.hypot(corners[:, 0] - camE, corners[:, 1] - camN))) + 120
    if os.path.isfile(tif) and not _covers(tif, bounds, dem_epsg):
        # the cache is keyed only by folder name, so a mosaic fetched for a
        # different scene can be sitting there. Reusing it does not fail
        # loudly: the uncovered tiles come back black, lose their lock, and
        # the run just reports a poor match rate.
        log("cached mosaic does not cover this scene - refetching")
        try:
            os.remove(tif)
        except OSError:
            pass
    if not os.path.isfile(tif):
        os.makedirs(cache_dir, exist_ok=True)
        for zoom in range(p.sat_zoom, 14, -1):    # step down if the area is too big
            try:
                log("fetching satellite mosaic (radius %.0f m, z%d)..." % (radius, zoom))
                mosaic_writer(lat, lon, radius_m=radius, zoom=zoom,
                              out_path=tif, epsg=dem_epsg)
                break
            except (RuntimeError, ValueError) as ex:
                # ★ WIDENED FOR THE WRITER WE DO NOT OWN (upstream §1, 2026-09-10).
                #   THIS build's writer (`accuracy_service.make_mosaic_writer`) raises
                #   RuntimeError with "cap" in the message, so the step-down has always
                #   worked here — upstream's own writer raises ValueError for the cap and
                #   its loop was dead code. Catching both keeps the protocol working
                #   whichever a future provider path chooses; anything without "cap" in
                #   the message still propagates untouched.
                if "cap" not in str(ex) or zoom == 15:
                    raise
                log("area too large at z%d - trying z%d" % (zoom, zoom - 1))
    else:
        log("reusing cached satellite mosaic")
    dst = np.zeros((3,) + tuple(shape), np.uint8)
    with rasterio.open(tif) as src:
        dst_transform = rasterio.transform.from_origin(
            origin[0] - p.gsd / 2, origin[1] + p.gsd / 2, p.gsd, p.gsd)
        for b in range(3):
            reproject(rasterio.band(src, b + 1), dst[b],
                      dst_transform=dst_transform, dst_crs="EPSG:%d" % dem_epsg,
                      resampling=Resampling.bilinear)
    return np.moveaxis(dst, 0, 2)


def _highpass(rgb):
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    return g - cv2.GaussianBlur(g, (0, 0), 12)


def phase_sign():
    """Runtime self-test of cv2.phaseCorrelate's sign convention.
    Returns s so that  s * phaseCorrelate(A, B) = pos(A) - pos(B)."""
    rs = np.random.RandomState(1)
    a = cv2.GaussianBlur(rs.rand(256, 256).astype(np.float32), (0, 0), 3)
    b = np.roll(a, (7, 13), axis=(0, 1))
    (sx, sy), _ = cv2.phaseCorrelate(a, b)
    s = -1.0 if abs(sx - 13) < 2 and abs(sy - 7) < 2 else 1.0
    got = (s * sx, s * sy)
    assert abs(got[0] + 13) < 2 and abs(got[1] + 7) < 2, \
        "phaseCorrelate sign self-test failed: %s" % [sx, sy]
    return s


def cloud_mask(sat, content, p: Params):
    """★ VENDOR EDIT — upstream §10's recipe, verbatim, as a function.

    Cloud in this basemap is bright in EVERY channel and nearly grey: the darkest
    channel above `cloud_min_brightness` and (max-min)/max under
    `cloud_max_saturation`. Bright saturated ground (yellow stubble, red roofs)
    fails the second test; a white roof passes both, which is why the switch is
    off by default. Closed with a square kernel so a thin gap in a cloud does
    not survive as a sliver of "content" between two masked halves."""
    img = np.asarray(sat, dtype=np.float32)
    mn, mx = img.min(axis=2), img.max(axis=2)
    sat_ = (mx - mn) / np.maximum(mx, 1)
    cloud = np.asarray(content, bool) & (mn > p.cloud_min_brightness) & (sat_ < p.cloud_max_saturation)
    k = np.ones((int(p.cloud_close_px), int(p.cloud_close_px)), np.uint8)
    return cv2.morphologyEx(cloud.astype(np.uint8), cv2.MORPH_CLOSE, k) > 0


def match_tiles(ortho, sat, inside, rng_g, u_g, img_w, p: Params):
    s = phase_sign()
    oh = _highpass(ortho); sh = _highpass(sat)
    tile, stride = int(p.tile / p.gsd), int(p.stride / p.gsd)
    win = cv2.createHanningWindow((tile, tile), cv2.CV_32F)
    H, W = oh.shape
    rows = []
    for y0 in range(0, H - tile, stride):
        for x0 in range(0, W - tile, stride):
            sl = np.s_[y0:y0 + tile, x0:x0 + tile]
            if inside[sl].mean() < p.min_valid:
                continue
            po, ps = oh[sl], sh[sl]
            if po.std() < p.min_texture or ps.std() < p.min_texture:
                continue
            (dx, dy), resp = cv2.phaseCorrelate(po * win, ps * win)
            dE = s * dx * p.gsd
            dN = -s * dy * p.gsd                   # row grows south
            err = float(np.hypot(dE, dN))
            r = float(np.nanmean(rng_g[sl]))
            u = float(np.nanmean(u_g[sl]))
            ok = resp >= p.min_response and err <= p.max_shift
            rows.append(dict(x0=x0, y0=y0, tile=tile, dE=dE, dN=dN, err=err,
                             resp=float(resp), range=r, u=u, method="phase",
                             sector=int(min(2, u // (img_w / 3))), ok=ok))
    return rows


# ------------------------------------------------------- MI second chance
def _mi(Aq, Bq, mask, bins=32):
    """Mutual information of two quantised tiles over the valid mask.
    High when one image's values reliably PREDICT the other's - no
    assumption that they are equal, which is what survives a season
    mismatch (green crop maps consistently to brown soil)."""
    h = np.histogram2d(Aq[mask], Bq[mask], bins=bins, range=((0, bins), (0, bins)))[0]
    s = h.sum()
    if s == 0:
        return 0.0
    pxy = h / s
    px = pxy.sum(1, keepdims=True)
    py = pxy.sum(0, keepdims=True)
    nz = pxy > 0
    return float((pxy[nz] * np.log(pxy[nz] / (px @ py)[nz])).sum())


def mi_rescue(rows, ortho, sat, inside, p: Params, log=lambda s: None):
    """Second chance for tiles phase correlation rejected: a small
    mutual-information search seeded by the neighbours' median shift.
    A rescue must have a sharp MI peak AND agree with its neighbours."""
    good = [t for t in rows if t["ok"]]
    bad = [t for t in rows if not t["ok"]]
    if not bad or len(good) < 5:
        return rows
    BINS = 32
    g_o = (cv2.cvtColor(ortho, cv2.COLOR_RGB2GRAY) / (256 / BINS)).astype(np.int32)
    g_s = (cv2.cvtColor(sat, cv2.COLOR_RGB2GRAY) / (256 / BINS)).astype(np.int32)
    pos = np.array([[t["x0"], t["y0"]] for t in good], float) * p.gsd
    vec = np.array([[t["dE"], t["dN"]] for t in good])
    T = int(p.tile / p.gsd)
    rescued = 0
    for t in bad:
        d = np.hypot(*(pos - np.array([t["x0"], t["y0"]], float) * p.gsd).T)
        nb = d <= p.mi_seed_radius
        if nb.sum() < 3:
            continue
        seed = np.median(vec[nb], axis=0)
        y0, x0 = t["y0"], t["x0"]
        Aq = g_o[y0:y0 + T, x0:x0 + T]
        mask = inside[y0:y0 + T, x0:x0 + T]
        best, surface = None, []
        for de in range(int(seed[0]) - p.mi_half, int(seed[0]) + p.mi_half + 1):
            for dn in range(int(seed[1]) - p.mi_half, int(seed[1]) + p.mi_half + 1):
                sx, sy = x0 - int(de / p.gsd), y0 + int(dn / p.gsd)
                if sx < 0 or sy < 0 or sx + T > g_s.shape[1] or sy + T > g_s.shape[0]:
                    continue
                v = _mi(Aq, g_s[sy:sy + T, sx:sx + T], mask, BINS)
                surface.append(v)
                if best is None or v > best[2]:
                    best = (de, dn, v)
        if best is None or len(surface) < 9:
            continue
        vals = np.array(surface)
        sharp = (best[2] - np.median(vals)) / (vals.std() + 1e-9)
        consistent = np.hypot(best[0] - seed[0], best[1] - seed[1]) <= p.mi_consistent_m
        if sharp >= p.mi_sharp_min and consistent:
            t.update(dE=float(best[0]), dN=float(best[1]),
                     err=float(np.hypot(best[0], best[1])),
                     resp=float(sharp), method="mi", ok=True)
            rescued += 1
    if rescued:
        log("MI second chance rescued %d tile(s)" % rescued)
    return rows


def fine_pass(rows, ortho, sat, inside, rng_g, u_g, img_w, p: Params,
              log=lambda s: None):
    """Coarse-to-fine: each locked tile's answer pre-aligns the satellite,
    then its four half-size sub-tiles measure only the small residual left.
    Small tiles fail at large shifts (nothing to lock onto) but succeed at
    tiny ones - so this recovers local detail the big tile blurred."""
    parents = [t for t in rows if t["ok"]]
    if not parents:
        return rows
    g_o = _highpass(ortho)
    g_s = _highpass(sat)
    T = int(p.tile / p.gsd)
    T2 = T // 2
    win = cv2.createHanningWindow((T2, T2), cv2.CV_32F)
    s = phase_sign()
    H, W = g_o.shape
    added = 0
    for t in parents:
        de0 = int(round(t["dE"] / p.gsd))
        dn0 = int(round(t["dN"] / p.gsd))
        for oy in (0, T2):
            for ox in (0, T2):
                y0, x0 = t["y0"] + oy, t["x0"] + ox
                sx, sy = x0 - de0, y0 + dn0
                if sx < 0 or sy < 0 or sx + T2 > W or sy + T2 > H:
                    continue
                sl = np.s_[y0:y0 + T2, x0:x0 + T2]
                if inside[sl].mean() < p.min_valid:
                    continue
                A = g_o[sl]
                B = g_s[sy:sy + T2, sx:sx + T2]
                if A.std() < p.min_texture or B.std() < p.min_texture:
                    continue
                (dx, dy), resp = cv2.phaseCorrelate(A * win, B * win)
                if resp < p.min_response:
                    continue
                rE = s * dx * p.gsd
                rN = -s * dy * p.gsd
                if np.hypot(rE, rN) > p.fine_residual_max:
                    continue
                dE = de0 * p.gsd + rE
                dN = dn0 * p.gsd + rN
                u = float(np.nanmean(u_g[sl]))
                rows.append(dict(
                    x0=x0, y0=y0, tile=T2, dE=float(dE), dN=float(dN),
                    err=float(np.hypot(dE, dN)), resp=float(resp),
                    range=float(np.nanmean(rng_g[sl])), u=u, method="fine",
                    sector=int(min(2, u // (img_w / 3))), ok=True))
                added += 1
    if added:
        log("fine pass added %d half-size sub-tiles" % added)
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Ported verbatim from the upstream engine, 2026-09-10 (heatmap_kit §3-§5).
# Kept byte-for-byte with the reference so the next port is a diff, not a merge.
# All three are inert until a Params switch turns them on; `tile_reliability`
# runs always but only ADDS two columns unless `reliability_max > 0`.
# ─────────────────────────────────────────────────────────────────────────────
# ------------------------------------------------- affine (ECC) third chance
def _ecc_raw(A, B, seed=(0.0, 0.0), iters=60, eps=1e-4):
    """Affine ECC fit of B onto A.  Returns (dx, dy, shear, cc): the raw
    displacement of the tile CENTRE, how far the linear part sits from the
    identity, and the correlation.  None if ECC will not converge."""
    warp = np.array([[1, 0, seed[0]], [0, 1, seed[1]]], np.float32)
    crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, int(iters), float(eps))
    A = np.ascontiguousarray(A, np.float32)
    B = np.ascontiguousarray(B, np.float32)
    try:
        try:
            cc, W = cv2.findTransformECC(A, B, warp, cv2.MOTION_AFFINE, crit, None, 5)
        except TypeError:                    # older signature, no gaussFiltSize
            cc, W = cv2.findTransformECC(A, B, warp, cv2.MOTION_AFFINE, crit)
    except cv2.error:
        return None
    W = np.asarray(W, float)
    if not np.all(np.isfinite(W)):
        return None
    h, w = A.shape
    c = np.array([w / 2.0, h / 2.0, 1.0])
    disp = W @ c - c[:2]
    shear = float(np.linalg.norm(W[:, :2] - np.eye(2)))
    return float(disp[0]), float(disp[1]), shear, float(cc)


def ecc_sign():
    """Runtime self-test, same idea as phase_sign(): returns es such that
    es * _ecc_raw(A, B) is pos(A) - pos(B), matching the phase convention.
    Returns 0.0 when ECC cannot be trusted here, which disables the rescue
    rather than risking a sign-flipped answer."""
    rs = np.random.RandomState(1)
    a = cv2.GaussianBlur(rs.rand(256, 256).astype(np.float32), (0, 0), 3)
    # a SMALL shift: ECC has a narrow convergence basin and is not pyramided
    # here, so a large offset would not converge from an identity seed.  That
    # is also why the rescue seeds every tile from its neighbours.
    b = np.roll(a, (3, 5), axis=(0, 1))          # pos(a) - pos(b) = (-5, -3)
    r = _ecc_raw(a, b)
    if r is None:
        return 0.0
    dx, dy = r[0], r[1]
    es = -1.0 if abs(dx - 5) < 1.5 and abs(dy - 3) < 1.5 else 1.0
    if not (abs(es * dx + 5) < 1.5 and abs(es * dy + 3) < 1.5):
        return 0.0
    return es


def ecc_rescue(rows, ortho, sat, inside, p: Params, log=lambda s: None):
    """Third chance for tiles both phase correlation and MI rejected: an
    AFFINE fit seeded by the neighbours' median shift.  A tile whose content is
    sheared by DTM error has no translation that fits it but does have an
    affine one.  Accepted only if the linear part stays near the identity and
    the answer agrees with the neighbourhood, so a shear cannot buy a lock that
    the surrounding field contradicts."""
    good = [t for t in rows if t["ok"]]
    bad = [t for t in rows if not t["ok"]]
    if not bad or len(good) < 5:
        return rows
    es = ecc_sign()
    if es == 0.0:
        log("affine rescue skipped: ECC self-test failed on this OpenCV build")
        return rows
    oh = _highpass(ortho)
    sh = _highpass(sat)
    pos = np.array([[t["x0"], t["y0"]] for t in good], float) * p.gsd
    vec = np.array([[t["dE"], t["dN"]] for t in good])
    added = 0
    for t in bad:
        c = np.array([t["x0"], t["y0"]], float) * p.gsd
        nb = np.hypot(*(pos - c).T) <= p.mi_seed_radius
        if nb.sum() < 4:
            continue
        seed = np.median(vec[nb], axis=0)               # dE, dN in metres
        T = t["tile"]
        sl = np.s_[t["y0"]:t["y0"] + T, t["x0"]:t["x0"] + T]
        if inside[sl].mean() < p.min_valid:
            continue
        A, B = oh[sl], sh[sl]
        if A.std() < p.min_texture or B.std() < p.min_texture:
            continue
        r = _ecc_raw(A, B, seed=(es * seed[0] / p.gsd, -es * seed[1] / p.gsd),
                     iters=p.ecc_iters, eps=p.ecc_eps)
        if r is None:
            continue
        dx, dy, shear, cc = r
        dE = es * dx * p.gsd
        dN = -es * dy * p.gsd
        err = float(np.hypot(dE, dN))
        if err > p.max_shift or shear > p.ecc_shear_max:
            continue
        if np.hypot(dE - seed[0], dN - seed[1]) > 2.0 * p.mi_consistent_m:
            continue
        t.update(dE=dE, dN=dN, err=err, resp=float(cc), method="ecc",
                 shear=float(shear), ok=True)
        added += 1
    if added:
        log("affine rescue recovered %d sheared tile(s)" % added)
    return rows


def tile_reliability(rows, camC, dem, p: Params, log=lambda s: None):
    """Per-tile amplification and expected sigma.

    A height error dz on the DTM moves the ray/terrain intersection along the
    sight line by  |d_xy| / |d_z - grad(h) . d_xy|  times dz, where d is the
    unit view direction.  Over flat ground that is 1/tan(depression).  It is
    the single biggest reason a grazing scene measures worse than a nadir one,
    so it is recorded per tile and the aggregate can be gated on it instead of
    treating a 2x tile and a 5x tile as equal evidence."""
    res = float(dem.res)
    for t in rows:
        t.setdefault("amplification", None)
        t.setdefault("sigma_m", None)
        cE, cN = t.get("cE"), t.get("cN")
        if cE is None:
            continue
        z = dem.Z(cE, cN)
        if not np.isfinite(z):
            continue
        d = np.array([cE - camC[0], cN - camC[1], z - camC[2]], float)
        n = np.linalg.norm(d)
        if n < 1.0:
            continue
        d /= n
        zx = (dem.Z(cE + res, cN) - dem.Z(cE - res, cN)) / (2 * res)
        zy = (dem.Z(cE, cN + res) - dem.Z(cE, cN - res)) / (2 * res)
        if not (np.isfinite(zx) and np.isfinite(zy)):
            zx = zy = 0.0
        den = abs(d[2] - (zx * d[0] + zy * d[1]))
        amp = float(np.hypot(d[0], d[1]) / max(den, 1e-6))
        t["amplification"] = amp
        t["sigma_m"] = amp * p.sigma_dtm
    if p.reliability_max > 0:
        n = 0
        for t in rows:
            if t["ok"] and t["sigma_m"] is not None and t["sigma_m"] > p.reliability_max:
                t["ok"] = False
                n += 1
        if n:
            log("reliability gate dropped %d tile(s) over %.1f m expected sigma"
                % (n, p.reliability_max))
    a = [t["amplification"] for t in rows if t["ok"] and t["amplification"] is not None]
    if a:
        log("amplification over locked tiles: median %.1fx -> expected sigma %.1f m "
            "at sigma_dtm = %.1f m"
            % (float(np.median(a)), float(np.median(a)) * p.sigma_dtm, p.sigma_dtm))
    return rows


def footprint_amplification(inside, origin, camC, dem, p: Params, step=8):
    """Area-weighted median amplification over the ortho footprint, computed
    BEFORE matching from pose + DTM alone.  `step` subsamples the cell grid."""
    H, W = inside.shape
    ys, xs = np.nonzero(inside[::step, ::step])
    if xs.size == 0:
        return float("nan")
    rows = [dict(cE=origin[0] + (x * step + 0.5) * p.gsd,
                 cN=origin[1] - (y * step + 0.5) * p.gsd, ok=True)
            for y, x in zip(ys, xs)]
    tile_reliability(rows, camC, dem, p)
    a = [r["amplification"] for r in rows if r["amplification"] is not None]
    return float(np.median(a)) if a else float("nan")


def resolve_tile_auto(p: Params, inside, origin, camC, dem, log=lambda s: None):
    """Return a Params with tile/stride set from the scene, or p unchanged."""
    if not p.tile_auto:
        return p
    amp = footprint_amplification(inside, origin, camC, dem, p)
    sizes, thr = p.tile_auto_sizes, p.tile_auto_thresholds
    size = sizes[-1]
    for s, t in zip(sizes, thr):
        if amp < t:
            size = s
            break
    q = dataclasses.replace(p, tile=size, stride=max(1, size // 2))
    log("tile auto: footprint median amplification %.1fx -> %d m tiles, %d m stride"
        % (amp, q.tile, q.stride))
    return q


def consistency_filter(rows, p: Params, radius=220.0, floor=4.0, log=lambda s: None):
    """Error fields are smooth; a lone tile pointing 20 m against its
    neighbours is a false lock.  Rejects any locked tile deviating from the
    median of its neighbours by more than max(floor, 3 x MAD); iterates so
    mutually-supporting false locks fall together."""
    dropped = 0
    for _ in range(4):
        good = [t for t in rows if t["ok"]]
        if len(good) < 5:
            break
        pos = np.array([[t["x0"], t["y0"]] for t in good], float) * p.gsd
        vec = np.array([[t["dE"], t["dN"]] for t in good])
        hit = False
        for i, t in enumerate(good):
            d = np.hypot(*(pos - pos[i]).T)
            nb = (d > 0) & (d <= radius)
            if nb.sum() < 4:
                continue
            med = np.median(vec[nb], axis=0)
            mad = np.median(np.hypot(*(vec[nb] - med).T))
            if np.hypot(*(vec[i] - med)) > max(floor, 3.0 * mad):
                t["ok"] = False
                dropped += 1
                hit = True
        if not hit:
            break
    if dropped:
        log("consistency filter dropped %d false lock(s)" % dropped)
    return rows


def decompose(rows, camEN, origin, p: Params):
    for t in rows:
        cE = origin[0] + (t["x0"] + t["tile"] / 2) * p.gsd
        cN = origin[1] - (t["y0"] + t["tile"] / 2) * p.gsd
        ur = np.array([cE - camEN[0], cN - camEN[1]])
        ur /= np.linalg.norm(ur)
        ut = np.array([-ur[1], ur[0]])
        t["cE"], t["cN"] = cE, cN
        t["radial"] = t["dE"] * ur[0] + t["dN"] * ur[1]
        t["tangential"] = t["dE"] * ut[0] + t["dN"] * ut[1]
    return rows


def heat_grid(result: Result, step=4, reach=1.6):
    """Error magnitude interpolated between locked tiles onto a coarse grid.
    Returns (Z, step) with NaN where there is no content or no tile nearby."""
    good = result.good
    if len(good) < 4:
        return None, step
    return heat_from_points(
        result,
        np.array([t["x0"] + t["tile"] / 2 for t in good], float),
        np.array([t["y0"] + t["tile"] / 2 for t in good], float),
        np.array([t["err"] for t in good], float),
        tile=max(t["tile"] for t in good), step=step, reach=reach)


def heat_from_points(result: Result, X, Y, E, tile=None, step=4, reach=1.6):
    """The same grid for ANY per-tile quantity, not just the raw error.

    Split out so every correction stage can be drawn on one identical grid
    with one shared colour scale - comparing two heat maps that were built
    differently tells you about the builders, not about the error."""
    from ._interp import Triangulation, LinearTriInterpolator
    X = np.asarray(X, float)
    Y = np.asarray(Y, float)
    E = np.asarray(E, float)
    if len(X) < 4:
        return None, step
    if tile is None:
        tile = max(t["tile"] for t in result.good)
    H, W = result.sat.shape[:2]
    gy, gx = np.mgrid[0:H:step, 0:W:step]
    try:
        interp = LinearTriInterpolator(Triangulation(X, Y), E)
    except Exception:
        return None, step
    Z = np.asarray(interp(gx.astype(float), gy.astype(float)))
    cover = result.inside[::step, ::step]
    d2 = np.full(gx.shape, np.inf)
    for x, y in zip(X, Y):
        d2 = np.minimum(d2, (gx - x) ** 2 + (gy - y) ** 2)
    Z[~cover | (d2 > (reach * tile) ** 2)] = np.nan
    return Z, step


def run(R, C, K, dist, photo, dem, cam_ll, cache_dir, params: Params = None,
        progress=lambda pct, msg: None, mosaic_writer=None):
    """The whole pipeline.  `progress(pct, msg)` is called from the worker
    thread - marshal to the UI thread yourself if you display it.

    ★ VENDOR EDIT: `mosaic_writer` is threaded through to `fetch_satellite`
    (see its docstring) so the satellite reference comes from the application's
    imagery service rather than a direct provider call."""
    p = params or Params()
    progress(5, "finding ground footprint...")
    bounds = ground_bounds(R, C, K, dist, dem, photo.shape[1], photo.shape[0], p)
    progress(15, "rectifying photo to a north-up map...")
    ortho, inside, rng_g, u_g, origin = build_ortho(R, C, K, dist, photo, dem, bounds, p)
    # ★ (a) tile size from the geometry, BEFORE the mosaic is fetched — the tile
    #   size decides the stride and therefore how much satellite is worth having.
    #   Returns a NEW Params (dataclasses.replace); everything downstream must use
    #   the rebound `p`, which is why this rebinds rather than mutating.
    p = resolve_tile_auto(p, inside, origin, C, dem, log=lambda s: progress(40, s))
    progress(45, "loading satellite reference...")
    sat = fetch_satellite(cam_ll, bounds, origin, ortho.shape[:2], dem.epsg,
                          cache_dir, p, log=lambda s: progress(50, s),
                          mosaic_writer=mosaic_writer)
    # ★ VENDOR EDIT: cloud leaves the content mask BEFORE anything is matched, so
    #   a tile mostly on cloud fails `min_valid` like a tile mostly off the photo,
    #   and a cloud edge is never a texture a matcher can lock onto.
    cloud = None
    if p.cloud_mask:
        cloud = cloud_mask(sat, inside, p)
        masked = float(cloud.sum()) / max(float(inside.sum()), 1.0)
        inside = inside & ~cloud
        progress(69, "cloud mask: %.1f%% of the content is basemap cloud" % (100.0 * masked))
    progress(70, "matching %d m tiles..." % p.tile)
    rows = match_tiles(ortho, sat, inside, rng_g, u_g, photo.shape[1], p)
    rows = consistency_filter(rows, p, log=lambda s: progress(82, s))
    if p.mi_rescue:
        progress(86, "mutual-information second chance on rejected tiles...")
        rows = mi_rescue(rows, ortho, sat, inside, p, log=lambda s: progress(88, s))
        rows = consistency_filter(rows, p, log=lambda s: progress(90, s))
    if p.ecc_rescue:
        # ★ (b) the affine third chance, then the SAME consistency filter the other
        #   rescues answer to — a sheared lock earns its place on the same terms.
        progress(91, "affine second chance on sheared tiles...")
        rows = ecc_rescue(rows, ortho, sat, inside, p, log=lambda s: progress(91, s))
        rows = consistency_filter(rows, p, log=lambda s: progress(92, s))
    if p.fine_pass:
        progress(92, "coarse-to-fine sub-tiles...")
        rows = fine_pass(rows, ortho, sat, inside, rng_g, u_g, photo.shape[1], p,
                         log=lambda s: progress(93, s))
        rows = consistency_filter(rows, p, log=lambda s: progress(94, s))
    rows = decompose(rows, (C[0], C[1]), origin, p)
    # ★ (c) AFTER decompose, which is what puts cE/cN on every row — the
    #   amplification is computed at the tile's ground centre.
    rows = tile_reliability(rows, C, dem, p, log=lambda s: progress(94, s))
    progress(95, "summarising...")
    res = Result(cloud=cloud, ortho=ortho, sat=sat, inside=inside, rng_g=rng_g,
                 origin=origin, tiles=rows, params=p)
    progress(100, "done: %d/%d tiles locked" % (len(res.good), len(rows)))
    return res
