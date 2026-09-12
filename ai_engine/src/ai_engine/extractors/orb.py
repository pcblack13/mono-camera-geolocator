"""`OrbExtractor` — ★ a TERMINAL fallback, binary descriptors. **DEFERRED.**

The end of the binary chain (`akaze → orb`, `brisk → orb`). Terminal for the same reason
SIFT is: main-module OpenCV, no weights, no optional packages, so it provably constructs.

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``).

When implemented: `cv2.ORB_create(nfeatures=max_features)`. Descriptors are 256 bits stored
bit-packed as `(N,32)` uint8, LSB-first per byte, and the Hamming metric is the only
meaningful one — which is exactly why `DescriptorKind` exists. FLANN-KDTree over packed ORB
bytes returns plausible-looking garbage instead of failing, so `Matcher.validate_pair`
compares `descriptor_kind` before anything else.
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from ai_engine.extractors.base import FeatureExtractor
from ai_engine.models import ComponentKind, DeferredImplementation, register
from ai_engine.types import DescriptorKind, Device, ExtractorCapabilities, FeatureSet
from ai_engine.version import EXTRACTOR_VERSION

__all__ = ["OrbExtractor"]


@register(ComponentKind.EXTRACTOR, fallback=None, is_terminal=True, device_preference=Device.CPU)
class OrbExtractor(DeferredImplementation, FeatureExtractor):
    """Oriented FAST + rotated BRIEF. BINARY descriptors, D=256 bits (32 bytes).

    ★ TERMINAL. The binary chain ends here.
    """

    name: ClassVar[str] = "orb"
    descriptor_kind: ClassVar[DescriptorKind] = DescriptorKind.BINARY
    descriptor_dim: ClassVar[int] = 256
    version: ClassVar[str] = EXTRACTOR_VERSION

    deferred_module: ClassVar[str] = __name__
    deferred_feature: ClassVar[str] = "ORB feature extraction"

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
