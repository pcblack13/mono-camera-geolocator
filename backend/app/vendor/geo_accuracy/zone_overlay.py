r"""Range-zone error overlay - the engine, with no GUI attached.

Takes a Stage D result and a camera pose, and produces the nine-zone picture:
three range bands x three image columns, each filled by the error measured
inside it, drawn as an RGBA layer you can composite over the photograph.

It is deliberately free of Tk, of this app's classes, and of any file layout,
so another program can use it with four things it already has:

    photo   HxWx3 array (or a PIL image)
    pose    R, C, K, dist                       - to project ground -> pixel
    dem     anything with .Z(x, y) and .res     - to trace the range contours
    tiles   [{cE, cN, err, range}, ...]         - the Stage D measurements

    from core import zone_overlay as ZO

    curves = ZO.iso_range_curves(bands, range_at, W, H)     # once per pose
    stats, rng = ZO.zone_stats(tiles, bands, uv, W)
    layer = ZO.overlay_image(curves, bands, stats, rng, W, H, scale, alpha=45)
    out   = ZO.render_on_photo(photo, curves, bands, stats, rng, alpha=45)

`range_at(u, v)` and the projection are passed IN rather than computed here, so
the caller keeps its own ray-caster and its own camera model; this module never
guesses how your software raycasts.

★ VENDORED, BYTE-IDENTICAL BELOW THIS NOTE (heatmap_kit, 2026-09-10)
----------------------------------------------------------------------
Nothing in this file is ours. `accuracy_service._photo_zones` is the caller:
it supplies our own `stage_b.raycast` as `range_at`, projects the locked tiles
with `project_uv`, and stores the curves and the nine cell statistics with the
measurement — the client draws them itself, so `overlay_image` and
`render_on_photo` (PIL) are kept only for a saved report figure. The `_main`
below refers to upstream's `core` package and is not runnable here; it stays
so the next port is a diff.

Command line, for a quick look without any host program:

    python -m core.zone_overlay --proj projects\hajez_136.geoproj --alpha 55
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFont

__all__ = ["DEFAULT_ALPHA", "MIN_TILES", "HEAT", "heat_rgb", "iso_range_curves",
           "zone_stats", "overlay_image", "render_on_photo", "project_uv"]

DEFAULT_ALPHA = 45          # per cent
MIN_TILES = 5               # under this a zone is "no data", never a colour
COLS = ("L", "M", "R")

# Sequential and one-directional, because the quantity is: more error is worse.
# Not red-green - about 8 % of men cannot separate those - and not blue-to-red,
# which loses its ordering once it is translucent over a photograph.
HEAT = ((255, 233, 138), (255, 196, 87), (247, 144, 61),
        (231, 87, 60), (176, 40, 48), (109, 17, 41))


def heat_rgb(v, lo, hi, stops=HEAT):
    """Continuous colour for one value, interpolated between the stops."""
    if not np.isfinite(v) or hi <= lo:
        return stops[0]
    t = min(1.0, max(0.0, (v - lo) / (hi - lo))) * (len(stops) - 1)
    i = min(int(t), len(stops) - 2)
    f = t - i
    a, b = stops[i], stops[i + 1]
    return tuple(int(round(a[k] + (b[k] - a[k]) * f)) for k in range(3))


def _font(size, bold=False):
    for nm in (("arialbd.ttf", "segoeuib.ttf") if bold else ("arial.ttf", "segoeui.ttf")):
        try:
            return ImageFont.truetype(nm, size)
        except Exception:                                   # noqa: BLE001
            continue
    return ImageFont.load_default()


# --------------------------------------------------------------- geometry
def iso_range_curves(bands, range_at, W, H, n_cols=34, v_step=None, bisect=7):
    """{band: [(u, v), ...]} - where the ground is exactly `band` metres away.

    Traced by scanning each sampled column from the BOTTOM up: the near ground
    is at the bottom of the frame and the sky at the top, so scanning upward
    finds the crossing before running out of terrain. A straight horizontal row
    would be wrong by hundreds of metres - the contour bends with the terrain.

    range_at(u, v) -> horizontal camera-to-ground range in metres, or None
    where the ray misses the terrain (sky, or off the DEM).
    """
    bands = sorted(float(b) for b in bands)
    if not bands:
        return {}
    curves = {b: [] for b in bands}
    v_step = v_step or max(6.0, H / 60.0)
    for u in np.linspace(2.0, W - 3.0, n_cols):
        prev_v = prev_r = None
        misses = 0
        v = H - 1.0
        while v >= 0:
            r = range_at(u, v)
            if r is None:
                misses += 1
                if prev_r is not None or misses > 12:
                    break                                   # into the sky
            else:
                if prev_r is not None:
                    for b in bands:
                        if prev_r < b <= r:
                            lo, hi = float(prev_v), float(v)
                            ok = True
                            for _ in range(bisect):
                                mid = 0.5 * (lo + hi)
                                rm = range_at(u, mid)
                                if rm is None:
                                    ok = False
                                    break
                                if rm < b:
                                    lo = mid
                                else:
                                    hi = mid
                            if ok:
                                curves[b].append((float(u), 0.5 * (lo + hi)))
                if r > bands[-1]:
                    break
                prev_v, prev_r = v, r
            v -= v_step
    return {b: pts for b, pts in curves.items() if len(pts) >= 2}


def curve_v(curves, b, u):
    """Row of the band-b contour at column u."""
    pts = sorted(curves[b])
    return float(np.interp(u, [p[0] for p in pts], [p[1] for p in pts]))


def project_uv(points_xyz, R, C, K, dist=None):
    """Ground points -> pixels. Uses OpenCV when it is there (so distortion is
    handled exactly as the pose was fitted), otherwise a plain pinhole."""
    P = np.asarray(points_xyz, float).reshape(-1, 3) - np.asarray(C, float)
    try:
        import cv2
        uv, _ = cv2.projectPoints(P.reshape(-1, 1, 3), cv2.Rodrigues(np.asarray(R, float))[0],
                                  np.zeros((3, 1)), np.asarray(K, float),
                                  np.zeros(5) if dist is None else np.asarray(dist, float))
        return uv.reshape(-1, 2)
    except ImportError:
        q = (np.asarray(R, float) @ P.T).T
        K = np.asarray(K, float)
        return np.stack([K[0, 0] * q[:, 0] / q[:, 2] + K[0, 2],
                         K[1, 1] * q[:, 1] / q[:, 2] + K[1, 2]], axis=1)


# ------------------------------------------------------------------ stats
def zone_stats(tiles, bands, uv, W, min_tiles=MIN_TILES, stat=np.median):
    """({(band index, column index): (n, value)}, (lo, hi) over zones with data).

    `tiles` carry their own ground range, so the band is a lookup; `uv` is the
    matching array of pixel positions, so the column is a comparison. No ray
    marching - this has to be cheap enough to run on every redraw.
    """
    bands = sorted(float(b) for b in bands)
    cells = {}
    for t, p in zip(tiles, np.asarray(uv, float).reshape(-1, 2)):
        r = t.get("range", t.get("rng"))
        bi = next((i for i, b in enumerate(bands) if r < b), None)
        if bi is None:
            continue                                        # beyond the last band
        ci = 0 if p[0] < W / 3.0 else (1 if p[0] < 2 * W / 3.0 else 2)
        cells.setdefault((bi, ci), []).append(float(t["err"]))
    stats = {k: (len(v), float(stat(v))) for k, v in cells.items()}
    vals = [m for n, m in stats.values() if n >= min_tiles]
    return stats, ((min(vals), max(vals)) if vals else None)


# ----------------------------------------------------------------- drawing
def overlay_image(curves, bands, stats, rng, W, H, scale=1.0, alpha=DEFAULT_ALPHA,
                  min_tiles=MIN_TILES, labels=True, legend=True, unit="m",
                  caption="median error vs satellite"):
    """The nine fills, their labels and a legend, as one RGBA image.

    Drawn at DISPLAY resolution (W*scale x H*scale) so the text stays crisp at
    any zoom, and returned with a real alpha channel - a host with no alpha
    compositing (Tk's canvas, for one) can only offer a coarse stipple, which
    is visibly dithered and cannot be adjusted continuously.
    """
    bands = sorted(float(b) for b in bands)
    dw, dh = int(W * scale), int(H * scale)
    if dw < 8 or dh < 8 or not curves:
        return None
    a = int(round(255 * max(0, min(100, alpha)) / 100.0))
    lo, hi = rng if rng else (0.0, 1.0)
    img = Image.new("RGBA", (dw, dh), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img, "RGBA")
    for ci in range(3):
        x0, x1 = ci * W / 3.0, (ci + 1) * W / 3.0
        xs = np.linspace(x0, x1, 26)
        for bi, b in enumerate(bands):
            if b not in curves:
                continue
            n, med = stats.get((bi, ci), (0, float("nan")))
            top = [(x, curve_v(curves, b, x)) for x in xs]
            if bi == 0:
                bot = [(x, float(H)) for x in xs]
            elif bands[bi - 1] in curves:
                bot = [(x, curve_v(curves, bands[bi - 1], x)) for x in xs]
            else:
                continue
            poly = [(x * scale, y * scale) for (x, y) in top + bot[::-1]]
            if n >= min_tiles:
                dr.polygon(poly, fill=heat_rgb(med, lo, hi) + (a,),
                           outline=(255, 255, 255, min(255, a + 90)))
            else:
                # nothing measured here: a wash, never a colour that reads as
                # a number
                dr.polygon(poly, fill=(120, 120, 120, max(20, a // 3)),
                           outline=(255, 255, 255, 90))
    if labels:
        f_big = _font(max(11, int(dh / 46)), bold=True)
        f_small = _font(max(9, int(dh / 62)))
        for ci, cname in enumerate(COLS):
            u = W * (ci + 0.5) / 3.0
            for bi, b in enumerate(bands):
                if b not in curves:
                    continue
                v_far = curve_v(curves, b, u)
                v_near = H if bi == 0 else (curve_v(curves, bands[bi - 1], u)
                                            if bands[bi - 1] in curves else H)
                vmid = 0.5 * (v_near + v_far)
                if not (0 <= vmid <= H):
                    continue
                n, med = stats.get((bi, ci), (0, float("nan")))
                head = "%s%d" % (cname, bi + 1)
                main = ("%.1f %s" % (med, unit)) if n >= min_tiles else "no data"
                sub = "%s-%.0f m   %d tiles" % ("0" if bi == 0 else "%.0f" % bands[bi - 1], b, n)
                wmain = max(dr.textlength(head + "  " + main, font=f_big),
                            dr.textlength(sub, font=f_small))
                pad, lh = 7, f_big.size + f_small.size + 9
                cx, cy = u * scale, vmid * scale
                dr.rounded_rectangle((cx - wmain / 2 - pad, cy - lh / 2 - pad,
                                      cx + wmain / 2 + pad, cy + lh / 2 + pad),
                                     radius=7, fill=(15, 20, 28, 165),
                                     outline=(255, 255, 255, 70))
                dr.text((cx, cy - lh / 2 + 1), head + "  " + main, font=f_big,
                        fill=(255, 255, 255, 255), anchor="ma")
                dr.text((cx, cy - lh / 2 + f_big.size + 5), sub, font=f_small,
                        fill=(206, 216, 230, 255), anchor="ma")
    if legend and rng:
        f_small = _font(max(9, int(dh / 62)))
        lw, lh_ = min(230, dw // 4), 12
        x0, y0 = 14, dh - 46
        for i in range(lw):
            dr.line([(x0 + i, y0), (x0 + i, y0 + lh_)],
                    fill=heat_rgb(lo + (hi - lo) * i / float(lw - 1), lo, hi) + (235,))
        dr.rectangle((x0, y0, x0 + lw, y0 + lh_), outline=(255, 255, 255, 150))
        dr.text((x0, y0 - 15), caption, font=f_small, fill=(255, 255, 255, 230))
        dr.text((x0, y0 + lh_ + 3), "%.1f %s" % (lo, unit), font=f_small,
                fill=(255, 255, 255, 230))
        dr.text((x0 + lw, y0 + lh_ + 3), "%.1f %s" % (hi, unit), font=f_small,
                fill=(255, 255, 255, 230), anchor="ra")
    return img


def render_on_photo(photo, curves, bands, stats, rng, alpha=DEFAULT_ALPHA, scale=1.0,
                    **kw):
    """The overlay composited onto the photo - one RGB image, for a host that
    cannot layer (or for saving a report figure)."""
    base = photo if isinstance(photo, Image.Image) else Image.fromarray(np.asarray(photo))
    base = base.convert("RGBA")
    W, H = base.size
    if scale != 1.0:
        base = base.resize((int(W * scale), int(H * scale)), Image.LANCZOS)
    layer = overlay_image(curves, bands, stats, rng, W, H, scale=scale, alpha=alpha, **kw)
    if layer is None:
        return base.convert("RGB")
    return Image.alpha_composite(base, layer).convert("RGB")


# -------------------------------------------------------------- as a script
def _main():
    import argparse
    import csv
    import json
    import os
    import sys

    ap = argparse.ArgumentParser(description="nine-zone error overlay on the photo")
    ap.add_argument("--proj", required=True)
    ap.add_argument("--tiles", default=None)
    ap.add_argument("--bands", default=None, help="two edges, e.g. 1200,2400")
    ap.add_argument("--alpha", type=int, default=DEFAULT_ALPHA)
    ap.add_argument("--scale", type=float, default=0.35)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, here)
    from core import geo_io, stage_b
    proj = os.path.abspath(a.proj)
    d = json.load(open(os.path.join(proj, "project.json"), encoding="utf-8"))
    R = np.array(d["pose"]["R"], float)
    C = np.array(d["pose"]["C"], float)
    K = np.array(d["pose"]["K"], float)
    dist = np.array(d["pose"]["dist"], float)
    dem = geo_io.DEM(os.path.join(proj, *d["dem"]["file"].split("/")))
    photo = Image.open(os.path.join(proj, *d["image"]["file"].split("/")))
    W, H = photo.size
    name = os.path.splitext(os.path.basename(proj))[0]
    src = a.tiles or os.path.join(here, "tools", "analysis", "outputs", name, "tiles.csv")
    tiles = [dict(cE=float(t["cE"]), cN=float(t["cN"]), err=float(t["err"]),
                  range=float(t["range"]))
             for t in csv.DictReader(open(src)) if t.get("ok") == "True"]
    if not tiles:
        raise SystemExit("no locked tiles in %s" % src)
    rmax = max(t["range"] for t in tiles)
    bands = ([float(x) for x in a.bands.split(",")] + [rmax]) if a.bands else \
            [rmax / 3.0, 2 * rmax / 3.0, rmax]

    def range_at(u, v):
        q = stage_b.raycast(float(u), float(v), R, C, K, dist, dem.Z, dem.res,
                            max_range=1.2 * rmax)
        return None if q is None else float(np.hypot(q[0] - C[0], q[1] - C[1]))

    print("tracing contours at %s m ..." % ", ".join("%.0f" % b for b in bands))
    curves = iso_range_curves(bands, range_at, W, H)
    xyz = np.array([[t["cE"], t["cN"], float(dem.Z(t["cE"], t["cN"]))] for t in tiles])
    ok = np.isfinite(xyz[:, 2])
    tiles = [t for t, k in zip(tiles, ok) if k]
    stats, rng = zone_stats(tiles, bands, project_uv(xyz[ok], R, C, K, dist), W)
    out = a.out or os.path.join(proj, "outputs", "zone_overlay.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    render_on_photo(photo, curves, bands, stats, rng, alpha=a.alpha,
                    scale=a.scale).save(out)
    print("wrote %s" % out)
    for bi in range(len(bands)):
        print("  " + "   ".join(
            "%s%d %s" % (COLS[ci], bi + 1,
                         ("%5.1f m (%d)" % (stats[(bi, ci)][1], stats[(bi, ci)][0]))
                         if stats.get((bi, ci), (0,))[0] >= MIN_TILES else "   -  (%d)"
                         % stats.get((bi, ci), (0, 0))[0])
            for ci in range(3)))


if __name__ == "__main__":
    _main()
