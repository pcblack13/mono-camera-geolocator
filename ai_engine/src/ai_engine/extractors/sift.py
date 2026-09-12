"""`SiftExtractor` — ★ the DEFAULT extractor and a TERMINAL fallback. **DEFERRED.**

Every other extractor's chain ends here, which is why the spec is terminal: no weights, no
packages beyond the base install, no fallback of its own. That is L1 expressed as a data
structure rather than as a hope — `Registry.register` asserts it.

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``). The registry entry, the chain
and the metadata are real; the body is not. `GET /capabilities` can therefore say
truthfully that this engine KNOWS about SIFT and cannot RUN it — which is the distinction
the scope ruling exists to preserve.

When implemented: `cv2.SIFT_create(nfeatures=max_features)`, `.detectAndCompute()` for
:meth:`extract` and `.compute()` for :meth:`extract_at`, with **RootSIFT** applied by
default (L1-normalise → element-wise sqrt → L2-normalise) and the result L2-normalised at
the boundary, so that `DescriptorKind.FLOAT` means exactly one thing everywhere.
:meth:`extract_at` must collapse `cv2.SIFT.compute`'s multi-orientation output to the
highest-response orientation per input point — see `FeatureExtractor.extract_at`.
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from ai_engine.extractors.base import FeatureExtractor
from ai_engine.models import ComponentKind, DeferredImplementation, register
from ai_engine.types import DescriptorKind, Device, ExtractorCapabilities, FeatureSet
from ai_engine.version import EXTRACTOR_VERSION

__all__ = ["SiftExtractor"]


@register(ComponentKind.EXTRACTOR, fallback=None, is_terminal=True, device_preference=Device.CPU)
class SiftExtractor(DeferredImplementation, FeatureExtractor):
    """Scale-invariant feature transform. FLOAT descriptors, D=128, RootSIFT-normalised.

    ★ TERMINAL. Nothing falls back from here, so in a fully implemented engine this class
    is the one that must always construct.
    """

    name: ClassVar[str] = "sift"
    descriptor_kind: ClassVar[DescriptorKind] = DescriptorKind.FLOAT
    descriptor_dim: ClassVar[int] = 128
    version: ClassVar[str] = EXTRACTOR_VERSION

    deferred_module: ClassVar[str] = __name__
    deferred_feature: ClassVar[str] = "SIFT feature extraction"

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
