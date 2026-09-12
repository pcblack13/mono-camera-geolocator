"""``geolocate`` — the field tool's estimation core, ported: pose from 4+ GCPs, then
pixel → world by ray/DEM intersection.

★ **A faithful port of the teammate tool's ``stage_a.py`` / ``stage_b.py``** (the
desktop geolocation GUI), kept numerically identical where it matters:

- Stage A (:func:`solve_pose`): ``cv2.solvePnP`` with **SQPNP** then a Levenberg–
  Marquardt refine, world points **recentred on the entered camera** for numerical
  conditioning, camera centre recovered as ``C + (−Rᵀt)``.
- Stage B (:func:`raycast`): undistort → back-project → rotate into world, then march
  the ray in DEM-resolution steps until it crosses below the terrain and bisect the
  crossing (60 halvings, 1 cm stop).

★ **Everything runs in the DEM's own projected CRS** (metres). Callers transform
lat/lon in and out via ``gis.crs``; this module never sees a geographic coordinate —
mixing degrees into the march step was the field tool's known silent-breakage mode,
and keeping this module CRS-blind makes it unrepresentable here.

★ **Module-level ``import cv2`` is lawful in this layer** — the precedent is
``services/frame_extraction.py``; L5 bars cv2 from ``app.api`` files, not services.

★ **An estimate is an INFERENCE.** Nothing here fabricates on failure: an unsolvable
pose raises, a ray that never meets the terrain returns ``None``, and the caller says
so to the surveyor (L12).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

__all__ = [
    "DemGrid",
    "PoseSolveError",
    "SolvedPose",
    "project_point",
    "raycast",
    "solve_pose",
]


class PoseSolveError(Exception):
    """The PnP solve failed — degenerate geometry (collinear/clustered points)."""


# ─────────────────────────────────────────────────────────────────────────────
# The DEM, opened once and sampled in RAM (the field tool's ``geo_io.DEM``)
# ─────────────────────────────────────────────────────────────────────────────


class DemGrid:
    """A project DEM held in memory: bilinear ``z(x, y)`` in the raster's own CRS.

    ★ Read WHOLE into RAM on open, exactly like the field tool: the raycast samples
    thousands of points along a ray, and a windowed read per sample would turn a
    millisecond march into a disk workload. Project DEMs are pre-cropped (tens of MB).
    """

    def __init__(self, path: Path | str) -> None:
        import rasterio  # lazy, mirroring gis.dem.sample — rasterio is an extra

        with rasterio.open(path) as ds:
            if ds.crs is None:
                raise ValueError(f"{Path(path).name} carries no CRS.")
            self.crs: str = str(ds.crs)
            self._inv = ~ds.transform
            #: March step for the raycast — one cell, assuming square pixels (metres).
            self.res: float = float(ds.res[0])
            nodata = ds.nodata
            arr = ds.read(1).astype(float)
        if nodata is not None:
            arr = np.where(arr == nodata, np.nan, arr)
        self._arr = arr
        self._rows, self._cols = arr.shape

    def z(self, x: float, y: float) -> float:
        """Bilinear elevation at projected ``(x, y)``; NaN outside the raster."""
        col, row = self._inv * (x, y)
        c0, r0 = math.floor(col), math.floor(row)
        if c0 < 0 or r0 < 0 or c0 >= self._cols - 1 or r0 >= self._rows - 1:
            return float("nan")
        fc, fr = col - c0, row - r0
        window = self._arr[r0 : r0 + 2, c0 : c0 + 2]
        if np.any(np.isnan(window)):
            return float("nan")
        top = window[0, 0] * (1 - fc) + window[0, 1] * fc
        bottom = window[1, 0] * (1 - fc) + window[1, 1] * fc
        return float(top * (1 - fr) + bottom * fr)


# ─────────────────────────────────────────────────────────────────────────────
# Stage A — pose from correspondences
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SolvedPose:
    """The solve's outputs, in the field tool's vocabulary (tilt: + = aimed down)."""

    rotation: np.ndarray  # 3×3, world→camera
    camera_xyz: np.ndarray  # solved centre, DEM CRS metres
    reproj_px: np.ndarray  # per-point reprojection error
    azimuth_deg: float  # from grid north, clockwise, [0, 360)
    tilt_deg: float  # below horizontal, + = down
    position_shift_m: float  # |solved − entered|


def solve_pose(
    obj_xyz: np.ndarray,
    img_uv: np.ndarray,
    k_matrix: np.ndarray,
    dist: np.ndarray,
    cam_xyz: np.ndarray,
) -> SolvedPose:
    """PnP over ≥4 GCP correspondences — the field tool's Stage A, verbatim in effect.

    Args:
        obj_xyz: (N,3) world points, DEM CRS metres.
        img_uv: (N,2) full-resolution image pixels, y-down.
        k_matrix: 3×3 OpenCV pinhole K.
        dist: Brown–Conrady ``[k1, k2, p1, p2, k3]``.
        cam_xyz: The ENTERED camera centre — the recentring origin and the reference
            the position-shift diagnostic is measured against; not a hard constraint.

    Raises:
        PoseSolveError: fewer than 4 points, or a degenerate configuration.
    """
    obj = np.ascontiguousarray(np.asarray(obj_xyz, dtype=float))
    uv = np.ascontiguousarray(np.asarray(img_uv, dtype=float))
    if obj.shape[0] < 4:
        raise PoseSolveError(f"need at least 4 correspondences, got {obj.shape[0]}")
    cam = np.asarray(cam_xyz, dtype=float)

    # ★ Recentre on the entered camera: UTM-scale coordinates (~10⁶) wreck the
    #   solver's conditioning; metre-scale offsets from the station do not.
    obj_local = obj - cam

    ok, rvec, tvec = cv2.solvePnP(
        obj_local, uv, k_matrix, dist, flags=cv2.SOLVEPNP_SQPNP
    )
    if not ok:
        raise PoseSolveError("cv2.solvePnP found no pose for these points.")
    rvec, tvec = cv2.solvePnPRefineLM(obj_local, uv, k_matrix, dist, rvec, tvec)

    rotation, _ = cv2.Rodrigues(rvec)
    camera_xyz = cam + (-rotation.T @ tvec).ravel()

    projected, _ = cv2.projectPoints(obj_local, rvec, tvec, k_matrix, dist)
    reproj = np.linalg.norm(projected.reshape(-1, 2) - uv, axis=1)

    # Optical axis in world frame → azimuth from grid +Y (north), tilt below horizon.
    axis = rotation.T @ np.array([0.0, 0.0, 1.0])
    azimuth = math.degrees(math.atan2(axis[0], axis[1])) % 360.0
    elevation = math.degrees(math.asin(float(np.clip(axis[2], -1.0, 1.0))))

    return SolvedPose(
        rotation=rotation,
        camera_xyz=camera_xyz,
        reproj_px=reproj,
        azimuth_deg=azimuth,
        tilt_deg=-elevation,
        position_shift_m=float(np.linalg.norm(camera_xyz - cam)),
    )


def project_point(
    world_xyz: np.ndarray,
    rotation: np.ndarray,
    camera_xyz: np.ndarray,
    k_matrix: np.ndarray,
    dist: np.ndarray,
) -> tuple[float, float] | None:
    """Stage A run BACKWARDS: one world point → its full-resolution pixel.

    The exact inverse of :func:`raycast`'s geometry, using the same recentring
    discipline as :func:`solve_pose`: the point is expressed relative to the SOLVED
    camera centre (so ``tvec`` is zero and UTM-scale magnitudes never reach OpenCV),
    then pushed through ``cv2.projectPoints`` with the same K and Brown–Conrady
    coefficients the solve used.

    Returns:
        ``(u, v)`` in full-resolution image pixels, y-down — or ``None`` when the
        point sits at/behind the camera plane (cheirality fail: the camera cannot
        see it, and projecting it anyway would produce a plausible-looking lie).

    ★ ``None`` is an honest answer here for the same reason it is in the raycast:
      a moved map point can legitimately leave the camera's half-space, and the
      caller must SAY so rather than mark a fabricated pixel.
    """
    p = np.asarray(world_xyz, dtype=float).reshape(3) - np.asarray(
        camera_xyz, dtype=float
    ).reshape(3)
    cam_frame = np.asarray(rotation, dtype=float) @ p
    if cam_frame[2] <= 0:
        return None  # at/behind the image plane — not visible
    rvec, _ = cv2.Rodrigues(np.asarray(rotation, dtype=float))
    projected, _ = cv2.projectPoints(
        p.reshape(1, 1, 3), rvec, np.zeros(3), k_matrix, dist
    )
    u, v = projected.ravel()
    return float(u), float(v)


# ─────────────────────────────────────────────────────────────────────────────
# Stage B — pixel → world by ray/terrain intersection
# ─────────────────────────────────────────────────────────────────────────────


def _pixel_to_ray(
    u: float, v: float, rotation: np.ndarray, k_matrix: np.ndarray, dist: np.ndarray
) -> np.ndarray:
    """The unit world-frame direction through pixel ``(u, v)``."""
    pt = np.array([[[float(u), float(v)]]], dtype=float)
    coeffs = dist if np.any(np.asarray(dist) != 0) else None
    xn, yn = cv2.undistortPoints(pt, k_matrix, coeffs).ravel()
    direction = rotation.T @ np.array([xn, yn, 1.0])
    return direction / np.linalg.norm(direction)


def raycast(
    u: float,
    v: float,
    rotation: np.ndarray,
    camera_xyz: np.ndarray,
    k_matrix: np.ndarray,
    dist: np.ndarray,
    dem_z: Callable[[float, float], float],
    step_m: float,
    *,
    height_offset_m: float = 0.0,
    max_steps: int = 6000,
    max_range_m: float = 50000.0,
) -> tuple[float, float, float] | None:
    """March the pixel's ray until it crosses below ``terrain + offset``; bisect there.

    Returns:
        ``(x, y, z)`` in the DEM's CRS — or ``None`` for sky, off-DEM, or beyond
        ``max_range_m``. ``None`` is an honest answer and is never papered over.
    """
    direction = _pixel_to_ray(u, v, rotation, k_matrix, dist)
    cam = np.asarray(camera_xyz, dtype=float)

    was_above = False
    prev_t = 0.0
    t = 0.0
    for _ in range(max_steps):
        t += step_m
        if t > max_range_m:
            return None
        point = cam + direction * t
        z = dem_z(float(point[0]), float(point[1]))
        if math.isnan(z):
            # Not over the raster yet → keep marching; left it after being over → gone.
            if was_above:
                return None
            continue
        above = point[2] > z + height_offset_m
        if not was_above:
            if not above:
                return None  # started at/below the terrain — no forward intersection
            was_above = True
            prev_t = t
            continue
        if above:
            prev_t = t
            continue

        # Crossed between prev_t and t — bisect to centimetre precision.
        lo, hi = prev_t, t
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            pm = cam + direction * mid
            zm = dem_z(float(pm[0]), float(pm[1]))
            if math.isnan(zm):
                break
            if pm[2] > zm + height_offset_m:
                lo = mid
            else:
                hi = mid
            if hi - lo < 0.01:
                break
        hit = cam + direction * (0.5 * (lo + hi))
        return float(hit[0]), float(hit[1]), float(hit[2])
    return None
