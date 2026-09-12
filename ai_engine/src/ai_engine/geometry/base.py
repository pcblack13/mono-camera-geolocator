"""The `GeometryEstimator` ABC — correspondences to a homography, **in pixels**.

★ PIXEL SPACE ONLY. NO REFERENCE SYSTEM. EVER. (L3) This package begins at pixels and ends
at pixels. Turning a pixel into a coordinate is `gis`'s job, and the fact that nothing in
here *can* do it is what keeps the boundary real rather than aspirational.

★ THE ABC IS REAL AND COMPLETE; the estimator behind it is deferred
(``docs/architecture/SCOPE.md``). Note that homography estimation is not merely deferred
for scheduling reasons — SCOPE §2 records that a planar homography is strictly valid only
for a planar scene or a pure rotation, and a ground-level oblique photograph violates
both. That is *why* the automatic path is deferred and the manual path is the product: a
manually placed GCP has no homography behind it, so it has no degenerate solve, no
viewpoint assumption, and no estimated confidence to calibrate. It is a direct observation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

import numpy as np

from ai_engine.types import HomographyResult, RansacConfig

__all__ = ["GeometryEstimator"]


class GeometryEstimator(ABC):
    """Robustly fits a planar homography to a set of point correspondences.

    Attributes:
        name: The registry key. ``"opencv"`` is the only registered ESTIMATOR, and
            `AiEngineConfig.estimator_backend` is the only thing that selects it.

            ★ Do not confuse this with `RansacConfig.method`. That is a robust-fit METHOD
            (`usac_magsac`, `prosac`, …); this is a component REGISTRY KEY. Conflating the
            two was a boot crash on an empty environment: resolving ``"usac_magsac"``
            against `ComponentKind.ESTIMATOR` finds no spec, finds no fallback, exhausts
            the chain and raises `ComponentUnavailable` at preflight — with zero env vars
            set, violating L10 and L11 at once. Two names, two concepts, no overlap.
    """

    name: ClassVar[str]

    @abstractmethod
    def estimate_homography(
        self,
        pts_a: np.ndarray,
        pts_b: np.ndarray,
        config: RansacConfig,
        *,
        weights: np.ndarray | None = None,
    ) -> HomographyResult:
        """Fit `H` mapping `pts_a` onto `pts_b`.

        Args:
            pts_a: `(M,2)` float32/float64 — points in the query frame.
            pts_b: `(M,2)` — the corresponding points in the window frame.
            config: The robust-fit configuration, including `method`, `threshold_px` and
                `seed`.
            weights: `(M,)` float32 > 0 — the PROSAC ordering key, a landmark-derived
                *priority* rather than a confidence. The caller MUST pass points already
                sorted descending by weight (use `Correspondences.sorted_by_weight()`);
                handing unsorted data to `SAMPLING_PROSAC` silently degrades it to uniform
                sampling, which is a slower algorithm producing a worse answer with no
                error anywhere.

        Returns:
            A `HomographyResult`.

        ★ IT RETURNS A SUB-THRESHOLD RESULT RATHER THAN RAISING. A fit with
        ``num_inliers < config.min_inliers`` comes back as data. **Estimation reports;
        policy judges** — the `DegeneracyValidator` decides what is acceptable, and it can
        only do that if it is given the thing to judge.

        ★ SORT-ORDER-IN, SORT-ORDER-OUT. `inlier_mask` and `residuals` are aligned to the
        `pts_a`/`pts_b` **handed to this method**. Sorting for PROSAC is the caller's job,
        so un-permuting is the caller's job too — `step6_estimate_homography` is
        normatively required to do both, and the permutation never escapes it. If it did,
        every landmark support count, every `LandmarkEvidence.support_count` and every
        `gcps.residual_px` would silently index the wrong correspondence: no crash, and
        entirely plausible numbers.

        Raises:
            InsufficientCorrespondences: `M < 4`. A homography is not defined by fewer
                than four point pairs — that is arithmetic, not policy, so it raises.
        """

    @abstractmethod
    def refine_homography(
        self,
        H0: np.ndarray,
        pts_a: np.ndarray,
        pts_b: np.ndarray,
        *,
        weights: np.ndarray | None = None,
    ) -> tuple[np.ndarray, np.ndarray | None]:
        """Levenberg-Marquardt refinement of the symmetric transfer error on an inlier set.

        Args:
            H0: `(3,3)` the initial estimate, typically from :meth:`estimate_homography`.
            pts_a: `(M,2)` inlier points in the query frame.
            pts_b: `(M,2)` the corresponding window-frame points.
            weights: `(M,)` float32 > 0, optional per-point weights.

        Returns:
            `(H_refined (3,3), covariance (9,9) | None)`. The covariance is **ROW-MAJOR
            `vec(H)` in the `h33=1` gauge** — normatively, per §4.24. A covariance whose
            vec convention or gauge is undocumented is a matrix of plausible numbers that
            cannot be checked and will be propagated into an error ellipse a surveyor
            trusts. It is None only when the fit is too degenerate to support one.
        """
