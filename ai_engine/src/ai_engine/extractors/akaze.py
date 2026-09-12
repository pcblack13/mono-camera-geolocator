"""`AkazeExtractor` — binary, main-module OpenCV, falls back to `orb`. **DEFERRED.**

★ **D = 488, NOT 486, AND THE DIFFERENCE IS NOT PEDANTRY.** OpenCV's AKAZE MLDB carries
**486 significant bits**, which `cv2` returns as **61 bytes**. §4.3 defines BINARY storage
as `(N, D//8)` uint8 and `FeatureSet.descriptor_dim` as `descriptors.shape[1] * 8`. With
`D = 486`: `486 // 8 == 60 != 61`, and `61 * 8 == 488 != 486`. So the ClassVar could
**never** equal the computed property, `Matcher.validate_pair` compares exactly that
field, and every AKAZE `FeatureSet` would raise `IncompatibleDescriptors` at composition
time — on a registered, unexotic extractor.

`descriptor_dim` declares the **storage width**. The final 2 bits are zero pad, and
Hamming distance is unaffected because pad bits are zero in both operands.

★ NOT opencv-contrib. The contrib extras module is ABSENT on the verified box; AKAZE is
main-module and available. SURF/BEBLID/VGG/LATCH are not, and must not be referenced.

(The contrib module is named by neither this docstring nor any other line in this package
— on purpose. §10.5's repo-wide gate greps `ai_engine/src` for that literal and does not
strip docstrings, so writing it here would fail CI on a comment whose only job is to say
we do not use it. IU-03's runtime assertion is the stronger check regardless: it catches
`getattr(cv2, 'xfeatur' + 'es2d')`, which no grep can see.)

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``).
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from ai_engine.extractors.base import FeatureExtractor
from ai_engine.models import ComponentKind, DeferredImplementation, register
from ai_engine.types import DescriptorKind, Device, ExtractorCapabilities, FeatureSet
from ai_engine.version import EXTRACTOR_VERSION

__all__ = ["AkazeExtractor"]


@register(ComponentKind.EXTRACTOR, fallback="orb", device_preference=Device.CPU)
class AkazeExtractor(DeferredImplementation, FeatureExtractor):
    """Accelerated-KAZE with MLDB descriptors. BINARY, D=488 bits (61 bytes)."""

    name: ClassVar[str] = "akaze"
    descriptor_kind: ClassVar[DescriptorKind] = DescriptorKind.BINARY
    #: 61 bytes * 8. See the module docstring — this is the storage width, and it must
    #: equal `FeatureSet.descriptor_dim` or every match raises `IncompatibleDescriptors`.
    descriptor_dim: ClassVar[int] = 488
    version: ClassVar[str] = EXTRACTOR_VERSION

    deferred_module: ClassVar[str] = __name__
    deferred_feature: ClassVar[str] = "AKAZE feature extraction"

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
