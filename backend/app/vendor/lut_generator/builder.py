"""Full-resolution LUT construction: every pixel gets its own ray-cast."""
from __future__ import annotations

import logging
import time

import numpy as np

from .config import BuildConfig
from .dem import DEM
from .pose import CameraPose
from .raycast import raycast_batch

log = logging.getLogger(__name__)


class LUTArrays:
    """The built product: latitude / longitude per pixel (NaN = no terrain hit)."""

    def __init__(self, lat: np.ndarray, lon: np.ndarray, stats: dict) -> None:
        self.lat = lat
        self.lon = lon
        self.stats = stats

    @property
    def shape(self):
        return self.lat.shape

    @property
    def nbytes(self) -> int:
        return self.lat.nbytes + self.lon.nbytes


def build_lut(cfg: BuildConfig, pose: CameraPose, dem: DEM,
              progress_cb=None) -> LUTArrays:
    """Ray-cast the full image grid and convert every hit to lat/lon.

    progress_cb(done_pixels, total_pixels) is called after each row chunk so a
    GUI can drive a progress bar; it must be cheap and thread-safe.
    """
    W, H = pose.width, pose.height
    total = W * H
    dtype = np.dtype(cfg.coord_dtype)

    log.info("building full-resolution LUT %d x %d = %.2f M pixels", W, H, total / 1e6)
    log.info("output dtype %s -> %.1f MB payload", dtype.name, total * dtype.itemsize * 2 / 1e6)

    lat = np.full((H, W), np.nan, dtype=dtype)
    lon = np.full((H, W), np.nan, dtype=dtype)

    rows_per_chunk = max(1, cfg.chunk_pixels // W)
    n_hit = 0
    t_start = time.perf_counter()
    last_report = t_start

    for r0 in range(0, H, rows_per_chunk):
        r1 = min(r0 + rows_per_chunk, H)
        vv, uu = np.meshgrid(np.arange(r0, r1, dtype=np.float64),
                             np.arange(W, dtype=np.float64), indexing="ij")
        hits = raycast_batch(uu.ravel(), vv.ravel(), pose.R, pose.C, pose.K,
                             pose.dist, dem, cfg.target_height_m,
                             cfg.max_range_m, cfg.bisection_iters)

        ok = np.isfinite(hits[:, 0])
        n_hit += int(ok.sum())
        if np.any(ok):
            lon_v, lat_v = dem.xy_to_lonlat(hits[ok, 0], hits[ok, 1])
            block_lat = np.full(hits.shape[0], np.nan)
            block_lon = np.full(hits.shape[0], np.nan)
            block_lat[ok] = lat_v
            block_lon[ok] = lon_v
            lat[r0:r1] = block_lat.reshape(r1 - r0, W).astype(dtype)
            lon[r0:r1] = block_lon.reshape(r1 - r0, W).astype(dtype)

        if progress_cb is not None:
            progress_cb(r1 * W, total)

        now = time.perf_counter()
        if now - last_report > 5.0 or r1 == H:
            done = r1 * W
            rate = done / (now - t_start)
            eta = (total - done) / rate if rate > 0 else 0
            log.info("  rows %5d/%d  %5.1f%%  %.0f kpx/s  ETA %4.1f min",
                     r1, H, 100.0 * done / total, rate / 1e3, eta / 60)
            last_report = now

    elapsed = time.perf_counter() - t_start
    stats = {
        "pixels_total": int(total),
        "pixels_with_hit": int(n_hit),
        "coverage_percent": round(100.0 * n_hit / total, 3),
        "build_seconds": round(elapsed, 1),
        "pixels_per_second": int(total / elapsed) if elapsed > 0 else 0,
    }
    log.info("build done in %.1f s (%.0f kpx/s); %.2f%% of pixels hit terrain",
             elapsed, total / elapsed / 1e3, stats["coverage_percent"])
    return LUTArrays(lat, lon, stats)
