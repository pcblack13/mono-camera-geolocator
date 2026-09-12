"""Crop-row and orchard-lattice estimation. **DEFERRED.**

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``).

★ IT MUST DECLINE ON CURVED ROWS RATHER THAN RETURN A FICTIONAL ORIENTATION. Contour
ploughing and centre-pivot irrigation produce rows with no single dominant direction. An
FFT peak still exists for such a field, and reporting it yields a plausible `theta_rad`
that is simply not a property of the scene — which then feeds the vanishing-point
calibrator, the rectifier, and eventually a bearing. `CropRowField.curvature` is the
mechanism: above ~0.3, there is nothing to report, and the honest answer is None.

Rows are **undirected**: `theta_rad` folds to `[0, pi)`. A row field at 10° and one at 190°
are the same field, and any comparison that thinks otherwise is 180° wrong half the time.
"""

from __future__ import annotations

from typing import NoReturn

import numpy as np

from ai_engine.errors import NotImplementedDeferred
from ai_engine.types import CropRowField, TreeLattice

__all__ = ["estimate_crop_rows", "estimate_tree_lattice"]


def _deferred(feature: str) -> NoReturn:
    """Raise `NotImplementedDeferred` naming this module and `feature`."""
    raise NotImplementedDeferred(__name__, feature=feature)


def estimate_crop_rows(
    image: np.ndarray,
    *,
    mask: np.ndarray | None = None,
) -> CropRowField | None:
    """Estimate the dominant row orientation and spacing via structure tensor + FFT.

    Args:
        image: `(H,W,3)` uint8 RGB or `(H,W)` uint8 gray.
        mask: `(H,W)` uint8; nonzero marks the region to analyse.

    Returns:
        A `CropRowField` with `theta_rad` folded to `[0, pi)`, or **None** when no coherent
        row structure exists. See the module docstring on why None beats a number.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    _deferred("crop-row orientation and spacing estimation")


def estimate_tree_lattice(
    image: np.ndarray,
    *,
    mask: np.ndarray | None = None,
) -> TreeLattice | None:
    """Estimate a planted orchard's two-axis lattice and its individual trees.

    Orchard trees are among the best landmarks farmland offers: locally unique, stable
    across seasons, and visible from both a ground-level photograph and a nadir view —
    which is precisely the pair this product has to reconcile.

    Args:
        image: `(H,W,3)` uint8 RGB or `(H,W)` uint8 gray.
        mask: `(H,W)` uint8; nonzero marks the region to analyse.

    Returns:
        A `TreeLattice`, or None when no lattice is present.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    _deferred("orchard lattice estimation")
