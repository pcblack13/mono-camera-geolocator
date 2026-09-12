"""Camera intrinsics — from EXIF, from a field of view, or from vanishing points. **DEFERRED.**

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``).

★ `AgriVanishingPointCalibrator` DECLINES RATHER THAN GUESSES, and that is the whole design.
Crop rows give a vanishing point; the horizon gives another; assuming they are orthogonal
gives a focal length via ``f² = -(v1 · v2)`` in normalised image coordinates. When the
assumed orthogonality is wrong — contour ploughing, a centre-pivot field, a rutted track
mistaken for a row — that expression goes **negative**, and there is no real focal length.

Clamping `f²` to a small positive number at that point would produce a number. It would
also produce a fictional camera, and every angle derived from it would inherit the fiction
silently, all the way to a bearing on a map. So it declines. `CameraIntrinsics.confidence`
and `.source` exist so a caller can tell an EXIF-derived focal length from a guessed one.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, NoReturn

import numpy as np

from ai_engine.errors import NotImplementedDeferred
from ai_engine.types import CameraIntrinsics, CropRowField

__all__ = [
    "AgriVanishingPointCalibrator",
    "assumed_intrinsics",
    "intrinsics_from_exif",
    "intrinsics_from_fov",
]


def _deferred(feature: str) -> NoReturn:
    """Raise `NotImplementedDeferred` naming this module and `feature`."""
    raise NotImplementedDeferred(__name__, feature=feature)


def intrinsics_from_exif(
    exif: Mapping[str, Any],
    image_size: tuple[int, int],
) -> CameraIntrinsics | None:
    """Derive intrinsics from EXIF focal length and sensor metadata.

    Args:
        exif: The parsed EXIF mapping. Parsing is the backend's job; this reads it.
        image_size: `(width, height)` of the image **after** any orientation normalisation.
            Passing the pre-rotation size silently transposes the principal point.

    Returns:
        `CameraIntrinsics` with ``source="exif"``, or None when EXIF does not carry enough
        to derive one. ★ None, not a guess — `assumed_intrinsics` is the explicit way to
        guess, and it labels itself.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    _deferred("intrinsics from EXIF")


def intrinsics_from_fov(
    fov_deg: float,
    image_size: tuple[int, int],
) -> CameraIntrinsics:
    """Derive intrinsics from a horizontal field of view.

    Args:
        fov_deg: Horizontal field of view in degrees.
        image_size: `(width, height)`.

    Returns:
        `CameraIntrinsics` with ``source="fov"``.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    _deferred("intrinsics from field of view")


def assumed_intrinsics(image_size: tuple[int, int]) -> CameraIntrinsics:
    """The last-resort guess: a typical phone-camera field of view.

    Args:
        image_size: `(width, height)`.

    Returns:
        `CameraIntrinsics` with ``source="assumed"`` and a LOW `confidence`. ★ The labels
        are the point: this is a guess, it says so in two fields, and everything downstream
        can see that it is one.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    _deferred("assumed intrinsics")


class AgriVanishingPointCalibrator:
    """Estimates focal length from crop-row and horizon vanishing points.

    ★ It DECLINES when the orthogonality assumption fails. See the module docstring: a
    negative `f²` is the calibrator discovering that its assumption was wrong, and the
    correct response to that is None, not a clamp.
    """

    def __init__(self, image_size: tuple[int, int]) -> None:
        """Bind the image geometry.

        Args:
            image_size: `(width, height)` of the query photograph.

        Raises:
            NotImplementedDeferred: Always, in this build.
        """
        raise NotImplementedDeferred(
            __name__, feature="vanishing-point camera calibration"
        )

    def calibrate(
        self,
        crop_rows: CropRowField,
        horizon: np.ndarray | None = None,
    ) -> CameraIntrinsics | None:
        """Estimate intrinsics from row geometry.

        Args:
            crop_rows: The detected row field. ★ Its `curvature` gates this: above ~0.3 the
                rows are contour-ploughed or centre-pivot and have no single vanishing
                point, so there is nothing to calibrate from.
            horizon: `(3,)` the horizon line in homogeneous image coordinates, when known.

        Returns:
            `CameraIntrinsics` with ``source="vanishing_points"``, or **None** when the
            geometry does not support a real solution.

        Raises:
            NotImplementedDeferred: Always, in this build.
        """
        raise NotImplementedDeferred(
            __name__, feature="vanishing-point camera calibration"
        )
