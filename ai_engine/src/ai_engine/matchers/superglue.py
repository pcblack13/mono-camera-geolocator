"""`SuperGlueMatcher` — learned attentional matching. Weights, lazy. **DEFERRED.**

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``).

★ A REQUESTED-BUT-MISSING WEIGHT IS A `202`, NOT A `503`, AND THE ASYMMETRY IS DELIBERATE
(§11.0). `POST /images/{id}/match` with ``matcher: "superglue"`` on a weightless box is
**accepted**: the job runs, falls back to `flann`, and reports
``WarningItem{code:"MODEL_WEIGHTS_MISSING", requested:"superglue", effective:"flann"}`` at
stage `resolving_models` — the instant it is known. Contrast an explicitly requested,
unconfigured *imagery provider*, which is a `503`. **Imagery changes the answer's
provenance; a matcher changes only its accuracy.** Both are reported; only one is
refusable.

Requires SuperPoint's D=256 FLOAT descriptors — it is trained on them, and matching any
other descriptor space through it is not a degradation but a category error.
"""

from __future__ import annotations

from typing import ClassVar

from ai_engine.matchers.base import Matcher
from ai_engine.models import ComponentKind, DeferredImplementation, register
from ai_engine.models.torch_guard import TORCH_MODULE_NAME
from ai_engine.types import DescriptorKind, Device, FeatureSet, MatchSet
from ai_engine.version import MATCHER_VERSION

__all__ = ["SuperGlueMatcher"]


@register(
    ComponentKind.MATCHER,
    fallback="flann",
    requires_packages=(TORCH_MODULE_NAME,),
    requires_weights=("superglue_outdoor_v1",),
    device_preference=Device.AUTO,
)
class SuperGlueMatcher(DeferredImplementation, Matcher):
    """SuperGlue: graph-neural-network matching over SuperPoint features. FLOAT, D=256."""

    name: ClassVar[str] = "superglue"
    supported_kinds: ClassVar[frozenset[DescriptorKind]] = frozenset({DescriptorKind.FLOAT})
    version: ClassVar[str] = MATCHER_VERSION

    deferred_module: ClassVar[str] = __name__
    deferred_feature: ClassVar[str] = "SuperGlue learned descriptor matching"

    def match(self, a: FeatureSet, b: FeatureSet) -> MatchSet:
        """Deferred. See the module docstring."""
        self._deferred()
