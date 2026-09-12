"""`Dinov2DenseExtractor` — dense self-supervised features. Weights, lazy. **DEFERRED.**

★ SCOPE lists DINOv2 as **"registry entry only"**. It gets exactly that: a spec, a chain,
metadata truthful enough for `GET /capabilities` to enumerate it, and no body.

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``).

When implemented: patch-token grid from a ViT-S/14 backbone; `extract_at` bilinearly
samples that grid. Falls back to `sift`.
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from ai_engine.extractors.base import FeatureExtractor
from ai_engine.models import ComponentKind, DeferredImplementation, register
from ai_engine.models.torch_guard import TORCH_MODULE_NAME
from ai_engine.types import DescriptorKind, Device, ExtractorCapabilities, FeatureSet
from ai_engine.version import EXTRACTOR_VERSION

__all__ = ["Dinov2DenseExtractor"]


@register(
    ComponentKind.EXTRACTOR,
    fallback="sift",
    requires_packages=(TORCH_MODULE_NAME,),
    requires_weights=("dinov2_v1",),
    device_preference=Device.AUTO,
)
class Dinov2DenseExtractor(DeferredImplementation, FeatureExtractor):
    """DINOv2 dense patch-token features. FLOAT, D=384 (ViT-S/14)."""

    name: ClassVar[str] = "dinov2"
    descriptor_kind: ClassVar[DescriptorKind] = DescriptorKind.FLOAT
    descriptor_dim: ClassVar[int] = 384
    version: ClassVar[str] = EXTRACTOR_VERSION

    deferred_module: ClassVar[str] = __name__
    deferred_feature: ClassVar[str] = "DINOv2 dense feature extraction"

    def extract(self, image: np.ndarray, mask: np.ndarray | None = None) -> FeatureSet:
        """Deferred. See the module docstring."""
        self._deferred()

    def extract_at(
        self,
        image: np.ndarray,
        points: np.ndarray,
        *,
        sizes: np.ndarray | None = None,
        angles: np.ndarray | None = None,
        landmark_ids: np.ndarray | None = None,
    ) -> FeatureSet:
        """Deferred. See the module docstring."""
        self._deferred()

    def capabilities(self) -> ExtractorCapabilities:
        """Deferred. See the module docstring."""
        self._deferred()
