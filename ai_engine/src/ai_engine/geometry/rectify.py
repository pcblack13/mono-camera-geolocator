"""Oblique rectification helpers. **DEFERRED.**

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``).

Rectifying an oblique photograph towards a synthetic nadir view before matching is what
turns `ViewRegime.OBLIQUE_RECTIFIABLE` from a diagnosis into a strategy: it moves the
viewpoint gap between a ground-level photo and a satellite raster back inside what a
descriptor can bridge. It works exactly when the horizon can be located and the scene is
close enough to planar — which is why the regime, not a flag, decides whether it runs.
"""

from __future__ import annotations

from typing import NoReturn

import numpy as np

from ai_engine.errors import NotImplementedDeferred
from ai_engine.types import CameraIntrinsics, CropRowField

__all__ = ["horizon_to_rectifier", "vanishing_points_from_croprows"]


def _deferred(feature: str) -> NoReturn:
    """Raise `NotImplementedDeferred` naming this module and `feature`."""
    raise NotImplementedDeferred(__name__, feature=feature)


def horizon_to_rectifier(
    horizon: np.ndarray,
    intrinsics: CameraIntrinsics,
    image_size: tuple[int, int],
) -> np.ndarray:
    """Build the homography that maps an oblique view towards a synthetic nadir one.

    Args:
        horizon: `(3,)` the horizon line in homogeneous image coordinates.
        intrinsics: The camera intrinsics.
        image_size: `(width, height)` of the source image.

    Returns:
        `(3,3)` float64, the rectifying homography.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    _deferred("horizon-based oblique rectification")


def vanishing_points_from_croprows(
    crop_rows: CropRowField,
    image_size: tuple[int, int],
) -> tuple[np.ndarray, np.ndarray] | None:
    """Recover the two vanishing points implied by a planted row lattice.

    Args:
        crop_rows: The detected row field.
        image_size: `(width, height)`.

    Returns:
        `(v1 (3,), v2 (3,))` in homogeneous image coordinates, or **None** when the rows do
        not support them — curved rows have no single vanishing point, and inventing one
        would put a fiction into every angle downstream.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    _deferred("vanishing points from crop rows")
