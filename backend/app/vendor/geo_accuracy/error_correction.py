r"""Stage E - correct the geolocation error measured by Stage D.

Two layers, applied in order:

  1. POSE REFINEMENT (fixes the cause).  Every tile Stage D locked is a
     pseudo-GCP: we know which pixel views that patch of ground, and the
     satellite tells us where that ground REALLY is (claimed - measured
     error).  ~100 such correspondences, spread over the whole frame, are
     re-solved through the normal Stage A solver -> a refined R, C.  Because
     a pose has only a handful of parameters, this corrects EVERY pixel and
     cannot overfit basemap noise.

  2. RESIDUAL FIELD (mops up what a rigid pose cannot express - locally bad
     DEM cells, basemap distortion).  Whatever error remains at the tiles
     after refinement is interpolated into a smooth (dE, dN) field and
     subtracted from every query that lands inside it.

The result is a CorrectedGeolocator: query(u, v) -> raw and corrected
lat/lon side by side, so the correction is inspectable, and a correction
report with before/after medians per range band.

Everything here is pure computation (no Tk, no matplotlib); the GUI's
page 3 drives it.  Corrections serialise to a small JSON so a LUT rebuild
or an external script can reuse the refined pose.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import numpy as np

from . import stage_a, stage_b


# --------------------------------------------------------------- pseudo-GCPs
def pseudo_gcps(result, dem, R, C, K, dist):
    """Stage D tiles -> (uv, xyz_true) correspondences.

    For each locked tile: its centre is where WE placed that ground, so
    projecting it through the CURRENT pose gives the pixel that views it;
    the satellite says the ground truly sits at claimed - (dE, dN)."""
    import cv2
    p = result.params
    good = result.good
    if len(good) < 8:
        raise RuntimeError("only %d locked tiles - not enough to refine a pose"
                           % len(good))
    claimed = np.array([[t["cE"], t["cN"]] for t in good])
    err = np.array([[t["dE"], t["dN"]] for t in good])
    true_xy = claimed - err
    z_claimed = np.array([dem.Z(x, y) for x, y in claimed])
    z_true = np.array([dem.Z(x, y) for x, y in true_xy])

    rvec = cv2.Rodrigues(np.asarray(R, float))[0]
    tvec = (-np.asarray(R, float) @ np.asarray(C, float)).reshape(3, 1)
    P = np.column_stack([claimed, z_claimed])
    uv, _ = cv2.projectPoints(P.reshape(-1, 1, 3), rvec, tvec,
                              np.asarray(K, float), np.asarray(dist, float))
    uv = uv.reshape(-1, 2)

    keep = np.isfinite(z_true) & np.isfinite(z_claimed) & np.isfinite(uv).all(axis=1)
    xyz_true = np.column_stack([true_xy, z_true])
    tiles = [t for t, k in zip(good, keep) if k]
    return uv[keep], xyz_true[keep], tiles


# --------------------------------------------------------------- refinement
@dataclass
class Correction:
    R: np.ndarray               # refined rotation
    C: np.ndarray               # refined camera position
    K: np.ndarray               # intrinsics the refined pose was solved with
    dist: np.ndarray
    residual_pts: np.ndarray    # (N,2) world E,N of the tile truths
    residual_vec: np.ndarray    # (N,2) leftover (dE, dN) AFTER refinement
    report: dict = field(default_factory=dict)
    _interp = None

    # ---- residual field ----------------------------------------------------
    def _build_interp(self):
        from ._interp import Triangulation, LinearTriInterpolator
        tri = Triangulation(self.residual_pts[:, 0], self.residual_pts[:, 1])
        self._interp = (LinearTriInterpolator(tri, self.residual_vec[:, 0]),
                        LinearTriInterpolator(tri, self.residual_vec[:, 1]))

    def residual_at(self, X, Y):
        """Smooth leftover (dE, dN) at a world point; (0,0) outside the
        measured area - never extrapolate a correction."""
        if len(self.residual_pts) < 4:
            return 0.0, 0.0
        if self._interp is None:
            self._build_interp()
        dE = self._interp[0](X, Y)
        dN = self._interp[1](X, Y)
        if np.ma.is_masked(dE) or np.ma.is_masked(dN):
            return 0.0, 0.0
        return float(dE), float(dN)

    # ---- persistence -------------------------------------------------------
    def save(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(dict(
                format="geolocation-correction", version=1,
                R=self.R.tolist(), C=self.C.tolist(),
                K=self.K.tolist(), dist=self.dist.tolist(),
                residual_pts=self.residual_pts.tolist(),
                residual_vec=self.residual_vec.tolist(),
                report=self.report), f, indent=1)
        return path

    @classmethod
    def load(cls, path):
        d = json.load(open(path, encoding="utf-8"))
        if d.get("format") != "geolocation-correction":
            raise ValueError("not a correction file: %s" % path)
        return cls(R=np.asarray(d["R"]), C=np.asarray(d["C"]),
                   K=np.asarray(d["K"]), dist=np.asarray(d["dist"]),
                   residual_pts=np.asarray(d["residual_pts"]),
                   residual_vec=np.asarray(d["residual_vec"]),
                   report=d.get("report", {}))


def _tile_errors(uv, xyz_true, R, C, K, dist, dem):
    """Predicted ground-error vector per pseudo-GCP under a given pose:
    raycast the pixel, compare landing spot to the satellite truth."""
    out = np.full((len(uv), 2), np.nan)
    for i, ((u, v), t) in enumerate(zip(uv, xyz_true)):
        hit = stage_b.raycast(u, v, R, C, K, dist, dem.Z, dem.res)
        if hit is not None:
            out[i] = (hit[0] - t[0], hit[1] - t[1])
    return out


def build_correction(result, dem, R, C, K, dist, use_residual_field=True,
                     free_focal=False, progress=lambda pct, msg: None):
    """The Stage E pipeline: pseudo-GCPs -> refined pose -> residual field.

    Returns a Correction whose report carries before/after error medians per
    range band, so the improvement is a printed fact, not a hope."""
    p = result.params
    progress(10, "building pseudo-GCPs from %d locked tiles..." % len(result.good))
    uv, xyz_true, tiles = pseudo_gcps(result, dem, R, C, K, dist)

    progress(30, "measuring error at tiles under the CURRENT pose...")
    before = _tile_errors(uv, xyz_true, R, C, K, dist, dem)

    progress(50, "re-solving the pose against the satellite truth...")
    sol = stage_a.solve_pose(xyz_true, uv, K, dist, np.asarray(C, float),
                             free_focal=free_focal)
    R2, C2, K2 = np.asarray(sol["R"]), np.asarray(sol["C"]), np.asarray(sol["K"])

    progress(70, "measuring error at tiles under the REFINED pose...")
    after = _tile_errors(uv, xyz_true, R2, C2, K2, dist, dem)

    ok = np.isfinite(before).all(axis=1) & np.isfinite(after).all(axis=1)
    uv, xyz_true = uv[ok], xyz_true[ok]
    before, after = before[ok], after[ok]
    tiles = [t for t, k in zip(tiles, ok) if k]

    def band_medians(vecs):
        mags = np.hypot(vecs[:, 0], vecs[:, 1])
        out = {}
        for lo, hi, name in p.bands:
            m = np.array([lo <= t["range"] < hi for t in tiles])
            if m.any():
                out[name] = float(np.median(mags[m]))
        out["all"] = float(np.median(mags))
        return out

    residual_vec = after if use_residual_field else np.zeros_like(after)
    corr = Correction(R=R2, C=C2, K=K2, dist=np.asarray(dist, float),
                      residual_pts=xyz_true[:, :2].copy(),
                      residual_vec=residual_vec.copy())

    # residual-field pass: what remains once the field is subtracted too
    final = after - residual_vec if use_residual_field else after

    b_all = band_medians(before)["all"]
    a_all = band_medians(after)["all"]
    corr.report = dict(
        n_pseudo_gcps=int(len(uv)),
        position_shift_m=float(np.linalg.norm(C2 - np.asarray(C, float))),
        azimuth_deg=float(sol["azimuth"]),
        tilt_down_deg=float(sol.get("tilt_down", float("nan"))),
        reproj_median_px=float(np.median(sol["reproj"])),
        before_m=band_medians(before),
        after_pose_m=band_medians(after),
        after_full_m=band_medians(final),
        residual_field=bool(use_residual_field),
        free_focal=bool(free_focal),
        # ACCEPTANCE GATE.  Validated across the 15-case GCP study: gating on
        # the all-band median catches 3/3 regressions with 0 false rejects.
        # Camera-shift and fit-residual thresholds were tested on the same
        # cases and REFUTED (they flag successes and miss failures), so they
        # are reported as diagnostics only - never as gate criteria.
        accepted=bool(a_all <= b_all),
        gate_reason=("pose refinement improves the median error (%.2f -> %.2f m)"
                     % (b_all, a_all) if a_all <= b_all else
                     "pose refinement would make it WORSE (%.2f -> %.2f m). "
                     "Keep the original pose; re-measure (Stage D) before "
                     "trusting any correction here." % (b_all, a_all)),
    )
    progress(100, "correction ready")
    return corr


# --------------------------------------------------------------- geolocator
class CorrectedGeolocator:
    """query(u, v) -> dict with raw, corrected and (if Stage F is attached)
    stagef world/lat-lon, so all of them can be shown side by side and every
    layer stays inspectable."""

    def __init__(self, raw_pose, correction: Correction, dem, stage_f=None):
        self.rawR, self.rawC, self.rawK, self.rawdist = raw_pose
        self.corr = correction
        self.dem = dem
        self.stage_f = stage_f          # core.stage_f.StageF, or None

    def query(self, u, v, target_h=0.0):
        out = {}
        raw = stage_b.raycast(u, v, self.rawR, self.rawC, self.rawK,
                              self.rawdist, self.dem.Z, self.dem.res,
                              height_offset=target_h)
        if raw is not None:
            lat, lon = self.dem.xy_to_latlon(raw[0], raw[1])
            out["raw"] = dict(X=raw[0], Y=raw[1], Z=raw[2], lat=lat, lon=lon)
        hit = stage_b.raycast(u, v, self.corr.R, self.corr.C, self.corr.K,
                              self.corr.dist, self.dem.Z, self.dem.res,
                              height_offset=target_h)
        if hit is not None:
            # the refined pose ALONE, before the residual field - so the two
            # can be compared and pinned separately instead of only as a sum
            lat, lon = self.dem.xy_to_latlon(hit[0], hit[1])
            out["pose"] = dict(X=hit[0], Y=hit[1], Z=hit[2], lat=lat, lon=lon)
            dE, dN = self.corr.residual_at(hit[0], hit[1])
            X, Y = hit[0] - dE, hit[1] - dN
            lat, lon = self.dem.xy_to_latlon(X, Y)
            out["field"] = out["corrected"] = dict(
                X=X, Y=Y, Z=hit[2], lat=lat, lon=lon,
                residual_dE=dE, residual_dN=dN)

        # ---- Stage F: choose the better base, then subtract its leftover
        if self.stage_f is not None:
            base = "corrected" if "corrected" in out else "raw"
            probe = out.get("corrected") or out.get("raw")
            if probe is not None:
                prefer_raw = self.stage_f.prefer_raw(probe["X"], probe["Y"])
                if prefer_raw and "raw" in out:
                    base, src = "raw", out["raw"]
                else:
                    prefer_raw = False
                    src = out.get("corrected") or out["raw"]
                    base = "corrected" if "corrected" in out else "raw"
                sub, _, gain = self.stage_f.correction_at(
                    src["X"], src["Y"], use_raw_base=prefer_raw)
                X, Y = src["X"] - sub[0], src["Y"] - sub[1]
                lat, lon = self.dem.xy_to_latlon(X, Y)
                out["stagef"] = dict(X=X, Y=Y, Z=src["Z"], lat=lat, lon=lon,
                                     base=base, dE=float(sub[0]),
                                     dN=float(sub[1]), gain=float(gain))
        return out or None
