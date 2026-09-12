"""High-level entry points for embedding the generator in another application.

The geolocation GUI uses `build_from_live_pose` so the LUT is built from exactly
the pose that is on screen - no temporary project file, and no second solve that
could differ from what the operator just validated.
"""
from __future__ import annotations

import logging
import os
from typing import Callable, Optional, Tuple

import numpy as np

from .builder import build_lut
from .bundle import archive_bundle, write_bundle
from .config import BuildConfig
from .dem import DEM
from .pose import CameraPose, roll_from_R

log = logging.getLogger(__name__)

_UP = np.array([0.0, 0.0, 1.0])


def pose_from_arrays(R, C, K, dist, width: int, height: int,
                     reproj_mean_px: float = float("nan"),
                     reproj_max_px: float = float("nan"),
                     n_gcps_used: int = 0,
                     position_shift_m: float = float("nan")) -> CameraPose:
    """Wrap an already-solved pose (e.g. held in a GUI) as a CameraPose."""
    R = np.asarray(R, dtype=float)
    C = np.asarray(C, dtype=float)
    axis = R.T @ _UP
    az = float(np.degrees(np.arctan2(axis[0], axis[1])) % 360.0)
    el = float(np.degrees(np.arcsin(np.clip(axis[2], -1.0, 1.0))))
    return CameraPose(
        R=R, C=C, K=np.asarray(K, dtype=float), dist=np.asarray(dist, dtype=float),
        width=int(width), height=int(height),
        azimuth_deg=az, tilt_down_deg=-el, roll_deg=roll_from_R(R),
        reproj_mean_px=float(reproj_mean_px), reproj_max_px=float(reproj_max_px),
        n_gcps_used=int(n_gcps_used), position_shift_m=float(position_shift_m),
    )


def build_from_live_pose(site_name: str,
                         dem_path: str,
                         output_dir: str,
                         R, C, K, dist,
                         width: int,
                         height: int,
                         target_height_m: float = 0.0,
                         coord_dtype: str = "float64",
                         validation_samples: int = 2000,
                         make_zip: bool = True,
                         progress_cb: Optional[Callable[[int, int], None]] = None,
                         **pose_stats) -> Tuple[str, dict]:
    """Build, validate and package a LUT from a pose held in memory.

    Returns (bundle_dir, validation_report). The report's "passed" flag tells
    the caller whether the bundle met its tolerance; the bundle is written
    either way so a failed run can still be inspected.
    """
    from .validator import validate_lut          # local import keeps cli light

    cfg = BuildConfig(
        site_name=site_name,
        dem_path=os.path.abspath(dem_path),
        project_json=None,
        image_width=int(width),
        image_height=int(height),
        target_height_m=float(target_height_m),
        output_dir=os.path.abspath(output_dir),
        coord_dtype=coord_dtype,
        validation_samples=int(validation_samples),
    )
    cfg.validate()

    dem = DEM(cfg.dem_path)
    pose = pose_from_arrays(R, C, K, dist, width, height, **pose_stats)
    log.info("live build | %s", pose.summary())

    lut = build_lut(cfg, pose, dem, progress_cb=progress_cb)
    report = validate_lut(lut, cfg, pose, dem)
    bundle_dir = write_bundle(lut, cfg, pose, dem, report)
    if make_zip:
        archive_bundle(bundle_dir)
    dem.close()
    return bundle_dir, report
