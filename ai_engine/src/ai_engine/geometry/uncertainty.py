"""``propagate_point_cov()`` — **PIXEL** covariance propagation. **DEFERRED.**

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``).

★ PIXELS IN, PIXELS OUT. Metres are `gis.accuracy`'s job, and the split is not
bureaucratic. This module knows the fit's uncertainty in the window's pixel frame and
nothing else; `gis.accuracy` is the single producer of the four survey numbers
(`relative_m`, `georef_ce90_m`, `total_ce90_m`, `dominant_term`) because it is the only
module that knows what a window pixel is worth on the ground **at that window's position**.

Multiplying a pixel covariance by a scale factor here would look right and be wrong: it is
the exact conflation `gis.accuracy` exists to prevent, and it happens to survive only
because `CandidateWindow.gsd_m` is already position-corrected — an invariant that is
load-bearing precisely because nothing about the arithmetic reveals it.

The conventions are §4.24's, normatively: `Σ_H` is over **row-major `vec(H)`** in the
**`h33 = 1` gauge**, and `A_h` is the Jacobian of the warped point with respect to that
`vec`. A permutation error between the two produces a covariance that is symmetric,
positive-definite, plausible and wrong — which is why IU-05's test is Monte-Carlo against
`A_h Σ_H A_hᵀ` rather than a Frobenius check on `H` alone, which cannot see a permutation.
"""

from __future__ import annotations

import numpy as np

from ai_engine.errors import NotImplementedDeferred

__all__ = ["propagate_point_cov"]


def propagate_point_cov(
    H: np.ndarray,
    pt: np.ndarray,
    cov_H: np.ndarray,
    *,
    cov_pt: np.ndarray | None = None,
) -> np.ndarray:
    """Propagate homography and point uncertainty into the warped point's covariance.

    Computes ``Σ_out = A_h Σ_H A_hᵀ + A_p Σ_p A_pᵀ`` where `A_h` is the Jacobian of the
    warped point with respect to row-major `vec(H)` in the `h33=1` gauge, and `A_p` is its
    Jacobian with respect to the input point.

    Args:
        H: `(3,3)` float64, the homography.
        pt: `(2,)` float64, the point in the query frame.
        cov_H: `(9,9)` float64, the covariance of row-major `vec(H)` in the `h33=1` gauge.
        cov_pt: `(2,2)` float64, the input point's own covariance — for a hand-clicked
            landmark this is the surveyor's click precision, and it is frequently the
            dominant term. None means the point is treated as exact.

    Returns:
        `(2,2)` float64 covariance of the warped point, **in WINDOW PIXELS**.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    raise NotImplementedDeferred(__name__, feature="pixel covariance propagation")
