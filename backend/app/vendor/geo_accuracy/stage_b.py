"""
Stage B - pixel -> world (X,Y,Z) by ray / DEM intersection.

Given the solved pose (R, C) and intrinsics, a pixel is converted to a ray in
world space, then marched forward until it drops below the DEM surface (plus an
optional height_offset for targets that sit above bare earth). A bisection step
refines the crossing to ~centimetre precision.
"""
import numpy as np
import cv2


def pixel_to_ray(u, v, R, K, dist):
    """Return a unit ray direction in world coordinates for pixel (u,v)."""
    dist = np.asarray(dist, float)
    if np.any(dist != 0):
        und = cv2.undistortPoints(np.array([[[u, v]]], float), K, dist).reshape(2)
        p = np.array([und[0], und[1], 1.0])
    else:
        p = np.array([(u - K[0, 2]) / K[0, 0], (v - K[1, 2]) / K[1, 1], 1.0])
    d = R.T @ p
    return d / np.linalg.norm(d)


def raycast(u, v, R, C, K, dist, demZ, dem_res,
            height_offset=0.0, max_steps=None, max_range=50000.0):
    """pixel -> (X,Y,Z) world intersection, or None if the ray misses the terrain.

    demZ(x, y) : callable returning bare-earth elevation (NaN outside coverage)
    dem_res    : DEM pixel size in metres (march step)
    height_offset : metres the target sits above bare earth (0 for feet/ground)
    max_steps  : None derives it from max_range/step, so the reach is range-bound
                 (a fixed count would silently shrink the reach on fine DEMs)
    """
    C = np.asarray(C, float)
    d = pixel_to_ray(u, v, R, K, dist)
    step = float(dem_res)
    if max_steps is None:
        max_steps = int(np.ceil(max_range / step))
    t = 0.0
    # seed with the camera itself, otherwise a hit closer than one step (steep
    # near-field pixels) is never bracketed and the ray reports "no hit"
    z0 = demZ(C[0], C[1])
    prev = (C[2] - (z0 + height_offset)) if np.isfinite(z0) else None
    last = C.copy()
    for _ in range(max_steps):
        t += step
        P = C + t * d
        z = demZ(P[0], P[1])
        if not np.isfinite(z):
            # nodata breaks the crossing bracket: never pair samples from
            # opposite sides of a gap (a bracket spanning the gap would let the
            # bisection return a fabricated point far from any real surface)
            prev = None
            last = P
            if t > max_range:
                break
            continue
        diff = P[2] - (z + height_offset)
        if prev is not None and prev > 0 and diff <= 0:
            lo, hi = last, P
            for _ in range(60):
                m = (lo + hi) / 2
                zm = demZ(m[0], m[1])
                if not np.isfinite(zm):
                    return hi        # nodata inside a one-step bracket: hi was
                                     # sampled finite and at/below the surface
                if m[2] - (zm + height_offset) > 0:
                    lo = m
                else:
                    hi = m
                if np.linalg.norm(hi - lo) < 0.01:
                    break
            return (lo + hi) / 2
        prev = diff
        last = P
        if t > max_range:
            break
    return None
