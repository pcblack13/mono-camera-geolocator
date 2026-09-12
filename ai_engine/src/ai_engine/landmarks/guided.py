"""``guided_rematch()`` — a prior-H constrained second pass. **DEFERRED.**

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``).

The second pass is where the accuracy is, and the reason is the ratio test rather than the
speed: once a prior homography exists, each query point's competitors are only the
*spatially plausible* ones, so the second-nearest neighbour stops being a random repeat of
the same crop row two hundred metres away. The ratio test suddenly means what it was
designed to mean.

★ AND ITS OUTPUT MUST CARRY `prior_free=False`. This is not bookkeeping. A gated
correspondence set's inlier ratio and RMS are bounded **by the gate itself** — feed them to
`S_f`/`S_g` and you are measuring how tight the gate was, not how right the fit is. §4.12
requires those two terms be computed on the prior-free pass, and `prior_free` is the only
thing that lets the scorer tell the two sets apart. Without it the guided pass would
reliably improve the score and not the answer.
"""

from __future__ import annotations

import numpy as np

from ai_engine.errors import NotImplementedDeferred
from ai_engine.types import Correspondences, LandmarkSet

__all__ = ["guided_rematch"]


def guided_rematch(
    source: object,
    image_a: np.ndarray,
    image_b: np.ndarray,
    *,
    prior_H: np.ndarray,
    prior_cov: np.ndarray | None = None,
    landmarks: LandmarkSet | None = None,
    radius_px: float = 32.0,
) -> Correspondences:
    """Re-match under a prior homography, gated to the plausible band.

    Args:
        source: The `CorrespondenceSource` to re-run. Typed `object` to keep this module
            free of a `matchers` import — §10.2 confines `ai_engine.landmarks` to
            `ai_engine.{types,extractors}`, and the source is structural anyway.
        image_a: `(H,W,3)` uint8 RGB — the query photograph.
        image_b: `(H,W,3)` uint8 RGB — the window.
        prior_H: `(3,3)` float64 mapping the a-frame to the b-frame.
        prior_cov: `(9,9)` covariance of `vec(prior_H)`, widening the gate per point.
        landmarks: The surveyor's landmarks, to weight the re-match toward them.
        radius_px: The base gate radius in the b frame.

    Returns:
        `Correspondences` with ``prior_free=False`` — see the module docstring.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    raise NotImplementedDeferred(
        __name__, feature="prior-constrained landmark re-matching"
    )
