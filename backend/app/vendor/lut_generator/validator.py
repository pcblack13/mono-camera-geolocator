"""Independent verification of a built LUT.

The builder marches whole batches of rays at once. This module re-computes a
random sample of pixels one at a time and compares, so a vectorisation bug
cannot slip into a shipped bundle unnoticed.
"""
from __future__ import annotations

import logging

import numpy as np

from .config import BuildConfig
from .dem import DEM
from .pose import CameraPose
from .raycast import raycast_batch

log = logging.getLogger(__name__)


def validate_lut(lut, cfg: BuildConfig, pose: CameraPose, dem: DEM,
                 seed: int = 12345) -> dict:
    """Compare `validation_samples` random pixels against a single-ray recompute."""
    rng = np.random.default_rng(seed)
    W, H = pose.width, pose.height
    n = min(cfg.validation_samples, W * H)

    uu = rng.integers(0, W, n)
    vv = rng.integers(0, H, n)

    # reference: one ray at a time (batch of size 1 -> no cross-ray state)
    ref = np.full((n, 3), np.nan)
    for i in range(n):
        ref[i] = raycast_batch(np.array([uu[i]], float), np.array([vv[i]], float),
                               pose.R, pose.C, pose.K, pose.dist, dem,
                               cfg.target_height_m, cfg.max_range_m,
                               cfg.bisection_iters)[0]

    lat_lut = lut.lat[vv, uu].astype(np.float64)
    lon_lut = lut.lon[vv, uu].astype(np.float64)

    ref_hit = np.isfinite(ref[:, 0])
    lut_hit = np.isfinite(lat_lut)
    disagree = int(np.sum(ref_hit != lut_hit))

    both = ref_hit & lut_hit
    errors_m = np.array([])
    if np.any(both):
        lon_ref, lat_ref = dem.xy_to_lonlat(ref[both, 0], ref[both, 1])
        # metric error via a local equirectangular approximation
        lat0 = np.radians(np.mean(lat_ref))
        dlat_m = (lat_lut[both] - lat_ref) * 111_320.0
        dlon_m = (lon_lut[both] - lon_ref) * 111_320.0 * np.cos(lat0)
        errors_m = np.hypot(dlat_m, dlon_m)

    report = {
        "samples": int(n),
        "validity_mismatches": disagree,
        "compared": int(both.sum()),
        "mean_error_m": float(np.mean(errors_m)) if errors_m.size else 0.0,
        "p95_error_m": float(np.percentile(errors_m, 95)) if errors_m.size else 0.0,
        "max_error_m": float(np.max(errors_m)) if errors_m.size else 0.0,
        "tolerance_m": cfg.max_error_tolerance_m,
    }
    report["passed"] = bool(disagree == 0
                            and report["max_error_m"] <= cfg.max_error_tolerance_m)

    lvl = logging.INFO if report["passed"] else logging.ERROR
    log.log(lvl, "validation %s: %d samples, max %.4f m (tol %.3f m), "
                 "mean %.4f m, %d validity mismatches",
            "PASSED" if report["passed"] else "FAILED", report["samples"],
            report["max_error_m"], report["tolerance_m"],
            report["mean_error_m"], disagree)
    return report
