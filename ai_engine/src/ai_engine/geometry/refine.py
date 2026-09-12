"""``refine_symmetric_transfer()`` — LM refinement plus covariance. **DEFERRED.**

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``).

The symmetric transfer error — the residual measured in BOTH frames rather than only the
forward one — is the right objective here because the two frames have genuinely different
noise: a hand-clicked landmark in the photograph and a satellite pixel are not equally
certain, and a one-directional error quietly assumes they are.

★ THE COVARIANCE'S CONVENTIONS ARE NORMATIVE (§4.24), because a covariance is a matrix of
plausible numbers whose meaning cannot be recovered by inspection. It is **row-major
`vec(H)`** in the **`h33 = 1` gauge**. Get either wrong and nothing fails: the error ellipse
a surveyor reads simply becomes a different, wrong ellipse.
"""

from __future__ import annotations

from typing import NoReturn

import numpy as np

from ai_engine.errors import NotImplementedDeferred

__all__ = ["refine_symmetric_transfer"]


def refine_symmetric_transfer(
    H0: np.ndarray,
    pts_a: np.ndarray,
    pts_b: np.ndarray,
    *,
    weights: np.ndarray | None = None,
    max_iters: int = 100,
) -> tuple[np.ndarray, np.ndarray | None]:
    """Refine `H0` by minimising the symmetric transfer error, via SciPy's LM.

    Args:
        H0: `(3,3)` the initial estimate.
        pts_a: `(M,2)` inlier points in the query frame.
        pts_b: `(M,2)` the corresponding window-frame points.
        weights: `(M,)` float32 > 0, optional per-point weights.
        max_iters: LM iteration cap.

    Returns:
        `(H_refined (3,3) float64, covariance (9,9) float64 | None)`. The covariance is
        row-major `vec(H)` in the `h33=1` gauge — §4.24, normatively. None when the fit
        cannot support one.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    raise NotImplementedDeferred(
        __name__, feature="symmetric-transfer homography refinement"
    )
