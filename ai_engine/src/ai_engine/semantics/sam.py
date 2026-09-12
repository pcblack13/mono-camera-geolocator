"""`SamSegmenter` — Segment Anything. Weights, lazy. **DEFERRED.**

★ SCOPE lists SAM as **"registry entry only"**. It gets exactly that: a spec, a chain to
`classical`, truthful metadata, and no body.

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``).

Two facts about SAM shape everything around it. Its ViT-H checkpoint is ~2.4 GB — which is
why `GET /capabilities` reads a cached `PreflightReport` and never re-hashes weights per
request, since doing so would be seconds of blocking disk I/O inside a route. And it takes
2–8 s per 1024² image **on a CPU**, which is what this box has, which is why
`LE_AI_SEMANTICS_ENABLED` defaults to `false` and `deep.max_candidates` is code-enforced
at 8.
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

__all__ = ["SamSegmenter"]


@register(
    ComponentKind.SEGMENTER,
    fallback="classical",
    requires_packages=(TORCH_MODULE_NAME,),
    requires_weights=("sam_vit_h_v1",),
    device_preference=Device.AUTO,
)
class SamSegmenter(DeferredImplementation, SemanticSegmenter):
    """Segment Anything: promptable class-agnostic segmentation.

    Class-agnostic is the catch: SAM returns *regions*, not `SemanticClass` labels, so an
    implementation must assign classes itself — from colour indices, shape and context —
    and record honest per-class `provenance` for the assignment it made.
    """

    name: ClassVar[str] = "sam"
    version: ClassVar[str] = SEMANTICS_VERSION

    deferred_module: ClassVar[str] = __name__
    deferred_feature: ClassVar[str] = "Segment Anything semantic segmentation"

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
