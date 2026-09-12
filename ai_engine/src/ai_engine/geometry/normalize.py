"""Hartley pre-conditioning — ``hartley_normalize()`` and ``denormalize_h()``. **DEFERRED.**

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``).

Normalising points to zero mean and RMS distance ``sqrt(2)`` from the origin before the DLT
is not an optimisation. Without it the design matrix's condition number is dominated by the
image's pixel scale, and the "homography" that comes back is a well-conditioned fit to
badly-conditioned arithmetic. It is also why `HomographyResult.condition_number` and
`.determinant` are defined on the normalised `H̃` rather than on `H`: those diagnostics are
only meaningful when they are invariant to an input rescale.
"""

from __future__ import annotations

from typing import NoReturn

import numpy as np

from ai_engine.errors import NotImplementedDeferred

__all__ = ["denormalize_h", "hartley_normalize", "normalize_h"]


def _deferred(feature: str) -> NoReturn:
    """Raise `NotImplementedDeferred` naming this module and `feature`."""
    raise NotImplementedDeferred(__name__, feature=feature)


def hartley_normalize(pts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return `(pts_normalised, T)` with zero mean and RMS distance `sqrt(2)`.

    Args:
        pts: `(M,2)` float64 points.

    Returns:
        `(pts_n (M,2), T (3,3))` where ``pts_n = T @ pts`` in homogeneous coordinates.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    _deferred("Hartley point normalisation")


def denormalize_h(H_tilde: np.ndarray, T_a: np.ndarray, T_b: np.ndarray) -> np.ndarray:
    """Lift a normalised homography back into pixel space: ``H = inv(T_b) @ H̃ @ T_a``.

    Args:
        H_tilde: `(3,3)` the homography in normalised coordinates.
        T_a: `(3,3)` the query-frame normalising transform.
        T_b: `(3,3)` the window-frame normalising transform.

    Returns:
        `(3,3)` the homography in pixel coordinates.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    _deferred("homography denormalisation")


def normalize_h(H: np.ndarray, T_a: np.ndarray, T_b: np.ndarray) -> np.ndarray:
    """The inverse of :func:`denormalize_h`: ``H̃ = T_b @ H @ inv(T_a)``.

    Needed because `condition_number` and `determinant` are reported on `H̃` (§4.24), and a
    caller holding only `H` must be able to recover it.

    Args:
        H: `(3,3)` the homography in pixel coordinates.
        T_a: `(3,3)` the query-frame normalising transform.
        T_b: `(3,3)` the window-frame normalising transform.

    Returns:
        `(3,3)` the homography in normalised coordinates.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    _deferred("homography normalisation")
