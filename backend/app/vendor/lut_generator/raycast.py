"""Vectorised pixel -> ray -> DEM intersection.

Semantics are identical to core/stage_b.py of the GUI, but whole batches of rays
are marched in lock-step so a full-resolution build takes minutes instead of
half an hour:

  * the march is seeded at the camera itself, so a hit closer than one DEM cell
    is still bracketed (steep near-field pixels);
  * a nodata sample invalidates the bracket, so a crossing is never inferred
    across a data gap (which would fabricate a point inside the gap);
  * the crossing is refined by bisection to ~1 cm.
"""
from __future__ import annotations

import numpy as np

from .dem import DEM


def pixel_rays(u: np.ndarray, v: np.ndarray, R: np.ndarray, K: np.ndarray,
               dist: np.ndarray) -> np.ndarray:
    """Unit ray directions in world coordinates for pixel arrays (N,) -> (N,3)."""
    import cv2

    pix = np.stack([u, v], axis=-1).astype(np.float64).reshape(-1, 1, 2)
    if np.any(np.asarray(dist) != 0):
        und = cv2.undistortPoints(pix, K, np.asarray(dist, float)).reshape(-1, 2)
        cam = np.column_stack([und[:, 0], und[:, 1], np.ones(len(und))])
    else:
        cam = np.column_stack([(pix[:, 0, 0] - K[0, 2]) / K[0, 0],
                               (pix[:, 0, 1] - K[1, 2]) / K[1, 1],
                               np.ones(len(pix))])
    d = cam @ R                       # == (R.T @ cam.T).T
    return d / np.linalg.norm(d, axis=1, keepdims=True)


def raycast_batch(u: np.ndarray, v: np.ndarray, R: np.ndarray, C: np.ndarray,
                  K: np.ndarray, dist: np.ndarray, dem: DEM,
                  height_offset: float = 0.0, max_range: float = 50_000.0,
                  bisection_iters: int = 40) -> np.ndarray:
    """Intersect a batch of pixel rays with the DEM.

    Returns (N, 3) of X, Y, Z; rows that never hit terrain are NaN.
    """
    n = u.size
    out = np.full((n, 3), np.nan, dtype=np.float64)
    if n == 0:
        return out

    d = pixel_rays(u.ravel(), v.ravel(), R, K, dist)
    C = np.asarray(C, dtype=np.float64)
    step = dem.res
    n_steps = int(np.ceil(max_range / step))

    # seed the bracket at the camera position itself
    z_cam = dem.z(C[0], C[1])
    prev = np.full(n, np.nan)
    if np.isfinite(z_cam):
        prev[:] = C[2] - (z_cam + height_offset)

    last = np.repeat(C.reshape(1, 3), n, axis=0)   # last finite sample per ray
    idx = np.arange(n)                              # active ray indices
    lo = np.empty((0, 3))
    hi = np.empty((0, 3))
    hit_idx = np.empty(0, dtype=np.int64)

    for s in range(1, n_steps + 1):
        if idx.size == 0:
            break
        t = s * step
        P = C + t * d[idx]
        z = dem.z_many(P[:, 0], P[:, 1])
        finite = np.isfinite(z)

        diff = np.full(idx.size, np.nan)
        diff[finite] = P[finite, 2] - (z[finite] + height_offset)

        crossing = finite & (prev[idx] > 0) & (diff <= 0)
        if np.any(crossing):
            hit_idx = np.concatenate([hit_idx, idx[crossing]])
            lo = np.vstack([lo, last[idx[crossing]]])
            hi = np.vstack([hi, P[crossing]])

        # a nodata sample breaks the bracket; a finite one refreshes it
        prev[idx[finite]] = diff[finite]
        prev[idx[~finite]] = np.nan
        last[idx[finite]] = P[finite]
        last[idx[~finite]] = P[~finite]

        idx = idx[~crossing]

    if hit_idx.size == 0:
        return out

    # ---- vectorised bisection between lo (above surface) and hi (below) -----
    for _ in range(bisection_iters):
        mid = 0.5 * (lo + hi)
        zm = dem.z_many(mid[:, 0], mid[:, 1])
        above = mid[:, 2] - (zm + height_offset) > 0
        bad = ~np.isfinite(zm)
        lo = np.where(above[:, None] & ~bad[:, None], mid, lo)
        hi = np.where((~above)[:, None] & ~bad[:, None], mid, hi)
        if np.all(np.linalg.norm(hi - lo, axis=1) < 0.01):
            break

    out[hit_idx] = 0.5 * (lo + hi)
    return out


def raycast_single(u: float, v: float, R, C, K, dist, dem: DEM,
                   height_offset: float = 0.0, max_range: float = 50_000.0,
                   bisection_iters: int = 40):
    """Convenience wrapper for one pixel; returns (X, Y, Z) or None."""
    r = raycast_batch(np.array([u], float), np.array([v], float), R, C, K, dist,
                      dem, height_offset, max_range, bisection_iters)[0]
    return None if not np.isfinite(r[0]) else r
