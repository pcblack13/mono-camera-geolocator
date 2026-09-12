"""`ClassicalSemantics` — ★ the DEFAULT segmenter and a TERMINAL fallback. **DEFERRED.**

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``).

Terminal: no weights, no packages beyond the base install. Every deep segmenter falls back
here (`sam → classical`, `dinov2_seg → classical`), which is only a real guarantee because
this class needs nothing to construct.

★ WHEN IMPLEMENTED, IT MUST GATE ON `supports_multispectral` AND SAY WHAT IT DID. The true
water indices need NIR/SWIR bands, which an RGB-only window does not have. On such a window
this class uses an HSV heuristic instead and records ``provenance="hsv_heuristic"`` for the
affected classes — it does **not** substitute the green band into an index that expects NIR
and report the result as a measurement. `semantics/indices.py`'s `ndwi`/`mndwi` raise
`ValueError` when the bands are absent for exactly this reason: the decision to fall back
to a heuristic belongs to the caller, who can label it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

import numpy as np

from ai_engine.models import ComponentKind, DeferredImplementation, register
from ai_engine.semantics.base import SemanticSegmenter
from ai_engine.types import Device, SemanticCapabilities, SemanticMap
from ai_engine.version import SEMANTICS_VERSION

__all__ = ["ClassicalSemantics"]


@register(ComponentKind.SEGMENTER, fallback=None, is_terminal=True, device_preference=Device.CPU)
class ClassicalSemantics(DeferredImplementation, SemanticSegmenter):
    """Colour indices, structure tensors, Hessian ridges and contour analysis.

    ★ TERMINAL and DEFAULT. The segmenter chain ends here.
    """

    name: ClassVar[str] = "classical"
    version: ClassVar[str] = SEMANTICS_VERSION

    deferred_module: ClassVar[str] = __name__
    deferred_feature: ClassVar[str] = "classical semantic segmentation"

    def segment(
        self,
        image: np.ndarray,
        *,
        bands: Mapping[str, np.ndarray] | None = None,
    ) -> SemanticMap:
        """Deferred. See the module docstring."""
        self._deferred()

    def capabilities(self) -> SemanticCapabilities:
        """Deferred. See the module docstring."""
        self._deferred()
