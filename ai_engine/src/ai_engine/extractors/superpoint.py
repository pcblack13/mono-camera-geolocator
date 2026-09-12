"""`SuperPointExtractor` — learned detector + descriptor. Weights, lazy. **DEFERRED.**

★ THIS IS THE CLASS THE L1 REGRESSION TEST DRIVES. Point `weights_dir` at an empty
directory and `resolve("superpoint", EXTRACTOR)` must return
`Resolution(requested="superpoint", resolved="sift", chain=("superpoint","sift"),
degraded=True)` with a `ComponentFallback` event at WARNING. That test passes in this
build, unchanged: the fallback policy is real and fully exercised even though both ends of
the chain are deferred — only the construction at the end reports "deferred". See
`models/policy.py`.

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``).

The spec declares `requires_packages=("torch",)` and `requires_weights=("superpoint_v1",)`,
and the policy probes them **in that order, with `find_spec` and a checksum** — never with
an import. A missing weight file is the default state of this repository and is a WARNING
plus a fallback, never an error (L11, §11.1).
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from ai_engine.extractors.base import FeatureExtractor
from ai_engine.models import ComponentKind, DeferredImplementation, register
from ai_engine.models.torch_guard import TORCH_MODULE_NAME
from ai_engine.types import DescriptorKind, Device, ExtractorCapabilities, FeatureSet
from ai_engine.version import EXTRACTOR_VERSION

__all__ = ["SuperPointExtractor"]


@register(
    ComponentKind.EXTRACTOR,
    fallback="sift",
    requires_packages=(TORCH_MODULE_NAME,),
    requires_weights=("superpoint_v1",),
    device_preference=Device.AUTO,
)
class SuperPointExtractor(DeferredImplementation, FeatureExtractor):
    """SuperPoint. FLOAT descriptors, D=256, L2-normalised by the network's own head.

    `extract_at` is a bilinear `grid_sample` of the dense descriptor map at the supplied
    points — which is why this extractor can see the user's landmarks at all, and is the
    reason `supports_extract_at` is a capability worth asking about.
    """

    name: ClassVar[str] = "superpoint"
    descriptor_kind: ClassVar[DescriptorKind] = DescriptorKind.FLOAT
    descriptor_dim: ClassVar[int] = 256
    version: ClassVar[str] = EXTRACTOR_VERSION

    deferred_module: ClassVar[str] = __name__
    deferred_feature: ClassVar[str] = "SuperPoint feature extraction"

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
