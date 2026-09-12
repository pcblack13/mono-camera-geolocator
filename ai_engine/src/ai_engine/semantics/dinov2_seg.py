"""`Dinov2Semantics` — segmentation from DINOv2 dense features. Weights. **DEFERRED.**

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``). Registry entry only; falls back
to `classical`.

When implemented: cluster the patch-token grid and assign `SemanticClass` labels to the
clusters, recording per-class `provenance` for the assignment.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

import numpy as np

from ai_engine.models import ComponentKind, DeferredImplementation, register
from ai_engine.models.torch_guard import TORCH_MODULE_NAME
from ai_engine.semantics.base import SemanticSegmenter
from ai_engine.types import Device, SemanticCapabilities, SemanticMap
from ai_engine.version import SEMANTICS_VERSION

__all__ = ["Dinov2Semantics"]


@register(
    ComponentKind.SEGMENTER,
    fallback="classical",
    requires_packages=(TORCH_MODULE_NAME,),
    requires_weights=("dinov2_v1",),
    device_preference=Device.AUTO,
)
class Dinov2Semantics(DeferredImplementation, SemanticSegmenter):
    """Semantic segmentation by clustering DINOv2 patch tokens."""

    name: ClassVar[str] = "dinov2_seg"
    version: ClassVar[str] = SEMANTICS_VERSION

    deferred_module: ClassVar[str] = __name__
    deferred_feature: ClassVar[str] = "DINOv2 semantic segmentation"

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
