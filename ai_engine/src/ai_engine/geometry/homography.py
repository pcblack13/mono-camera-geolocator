"""`OpenCvHomographyEstimator` — ★ the ONLY registered ESTIMATOR. **DEFERRED.**

Terminal: no weights, no fallback, no optional packages. `AiEngineConfig.estimator_backend`
(default ``"opencv"``) is the only thing that selects it.

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``). RANSAC homography estimation is
named explicitly in SCOPE §4 as "ABC only". SCOPE §2 gives the reason and it is a design
judgement rather than a schedule slip: a planar homography is strictly valid only for a
planar scene or a pure rotation, and a ground-level oblique photograph of farmland
violates both. The automatic path would have been least reliable exactly where this
product is most used, and a confidently wrong coordinate handed to a surveyor is this
system's worst failure mode (L12).

When implemented:

* `cv2.findHomography` with `cv2.USAC_MAGSAC` by default. `UsacParams.randomGeneratorState`
  is verified settable on OpenCV 4.13, and `RansacConfig.seed` must be routed into it —
  determinism is a test obligation, not a nicety.
* `condition_number` and `determinant` are computed on the **Hartley-normalised** `H̃`,
  never on `H`. That is what makes them invariant to an input rescale, which is the whole
  point of reporting them.
* `LMEDS` stays selectable and is DISQUALIFIED by default: its 50% breakdown point cannot
  survive this product's ~80%-outlier regime. It warns; it does not raise.
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from ai_engine.geometry.base import GeometryEstimator
from ai_engine.models import ComponentKind, DeferredImplementation, register
from ai_engine.types import Device, HomographyResult, RansacConfig

__all__ = ["OpenCvHomographyEstimator"]


@register(ComponentKind.ESTIMATOR, fallback=None, is_terminal=True, device_preference=Device.CPU)
class OpenCvHomographyEstimator(DeferredImplementation, GeometryEstimator):
    """Robust homography estimation via OpenCV's USAC family.

    ★ TERMINAL, and the only member of `ComponentKind.ESTIMATOR`.
    """

    name: ClassVar[str] = "opencv"

    deferred_module: ClassVar[str] = __name__
    deferred_feature: ClassVar[str] = "RANSAC homography estimation"

    def estimate_homography(
        self,
        pts_a: np.ndarray,
        pts_b: np.ndarray,
        config: RansacConfig,
        *,
        weights: np.ndarray | None = None,
    ) -> HomographyResult:
        """Deferred. See the module docstring."""
        self._deferred()

    def refine_homography(
        self,
        H0: np.ndarray,
        pts_a: np.ndarray,
        pts_b: np.ndarray,
        *,
        weights: np.ndarray | None = None,
    ) -> tuple[np.ndarray, np.ndarray | None]:
        """Deferred. See the module docstring."""
        self._deferred()
