"""`BriskExtractor` — binary, main-module OpenCV, falls back to `orb`. **DEFERRED.**

★ NOT opencv-contrib. BRISK is main-module and present on the verified box.

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``).

When implemented: `cv2.BRISK_create()`. 512-bit descriptors stored bit-packed as `(N,64)`
uint8.
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from ai_engine.extractors.base import FeatureExtractor
from ai_engine.models import ComponentKind, DeferredImplementation, register
from ai_engine.types import DescriptorKind, Device, ExtractorCapabilities, FeatureSet
from ai_engine.version import EXTRACTOR_VERSION

__all__ = ["BriskExtractor"]


@register(ComponentKind.EXTRACTOR, fallback="orb", device_preference=Device.CPU)
class BriskExtractor(DeferredImplementation, FeatureExtractor):
    """Binary robust invariant scalable keypoints. BINARY, D=512 bits (64 bytes)."""

    name: ClassVar[str] = "brisk"
    descriptor_kind: ClassVar[DescriptorKind] = DescriptorKind.BINARY
    descriptor_dim: ClassVar[int] = 512
    version: ClassVar[str] = EXTRACTOR_VERSION

    deferred_module: ClassVar[str] = __name__
    deferred_feature: ClassVar[str] = "BRISK feature extraction"

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
