"""`DegeneracyValidator` — the gate that decides whether a fit may be believed. **DEFERRED.**

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``).

★ THIS CLASS IS L12 MADE MECHANICAL. Estimation reports; **this** judges. Its job is to
find the fits that are arithmetically fine and physically absurd — the ones reprojection
error cannot see, because the surviving inliers all agree with each other. A homography
fitted to collinear points, or to a hull covering 2% of the frame, or one that mirrors the
scene, will have a beautiful RMS and a meaningless answer. Without this gate the product's
worst output is not an error: it is a confident, plausible, wrong coordinate handed to
someone who may dig against it.

**Hard checks zero the gate** (`gate := 0.0`, `status := "rejected"`). **Soft checks
multiply it** — they never zero it, so no single soft signal can veto a fit on its own.

The hard list, H1–H13 (§4.9), each with a purpose-built fixture that trips it:

* H1  too few inliers                       * H8  extreme anisotropy
* H2  ``det(H̃) <= 0`` — a mirrored scene    * H9  scale outside the plausible range
* H3  non-invertible / rank-deficient       * H10 too many landmarks out of bounds
* H4  the vanishing line crosses the ROI    * H11 (DEAD — proven redundant; see below)
* H5  collinear inliers                     * H12 non-finite entries in `H`
* H6  the inlier hull is too small          * H13 too much placeholder imagery
* H7  reprojection error too large

★ H4 is the one that justifies the whole class. The vanishing line crossing the region of
interest means the homography folds the plane through infinity inside the image — and
**reprojection error cannot see it**, because the surviving inliers all sit on the good
side of the line. `scene_horizon_crossing` is the only thing that catches it. H4(b) is the
gauge-free tangency test: an `H` whose vanishing line merely GRAZES the ROI must trip too,
which a threshold expressed as ``1e-6 * |h33|`` could never do.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from ai_engine.config import DegeneracyConfig
from ai_engine.errors import NotImplementedDeferred
from ai_engine.types import (
    DegeneracyReport,
    HomographyResult,
    LandmarkSet,
    ViewRegime,
)

__all__ = ["DegeneracyValidator"]


class DegeneracyValidator:
    """Runs the hard and soft degeneracy checks over a fit and reports the gate.

    Not a registry component: there is no `ComponentKind.VALIDATOR`, and there should not
    be. Degeneracy policy is not swappable — a deployment that could configure its way out
    of the H4 check is a deployment that can emit a confident wrong coordinate, which is
    the one thing this system must not do. `pipeline.compose` constructs it directly from
    `AiEngineConfig.degeneracy`.
    """

    def __init__(self, config: DegeneracyConfig | None = None) -> None:
        """Bind the thresholds.

        Args:
            config: The check thresholds. None uses the defaults, which are the supported
                configuration.

        Raises:
            NotImplementedDeferred: Always, in this build.
        """
        raise NotImplementedDeferred(
            __name__, feature="degeneracy validation of a homography fit"
        )

    def validate(
        self,
        homography: HomographyResult,
        *,
        pts_a: np.ndarray,
        pts_b: np.ndarray,
        query_image_size: tuple[int, int],
        window_image_size: tuple[int, int],
        landmarks: LandmarkSet | None = None,
        regime: ViewRegime = ViewRegime.UNKNOWN,
        placeholder_fraction: float = 0.0,
        extra: Sequence[Any] = (),
    ) -> DegeneracyReport:
        """Run every check and return the report.

        Args:
            homography: The fit under judgement.
            pts_a: `(M,2)` query-frame correspondence points.
            pts_b: `(M,2)` window-frame correspondence points.
            query_image_size: `(width, height)` of the query image.
            window_image_size: `(width, height)` of the window.
            landmarks: The user's landmarks, for H10.
            regime: How the photograph sees the ground — the strongest single predictor of
                whether a homography is even the right model.
            placeholder_fraction: `[0,1]` fraction of blank source imagery, for H13.
            extra: Additional checks to run, for callers that have evidence this class
                cannot see.

        Returns:
            A `DegeneracyReport` with the gate in `[0,1]` and the hard failures named.

        Raises:
            NotImplementedDeferred: Always, in this build.
        """
        raise NotImplementedDeferred(
            __name__, feature="degeneracy validation of a homography fit"
        )
