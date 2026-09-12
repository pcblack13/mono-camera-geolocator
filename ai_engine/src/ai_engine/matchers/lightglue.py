"""`LightGlueMatcher` — SuperGlue's faster successor. Weights, lazy. **DEFERRED.**

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``). Falls back to `flann`.

When implemented, its adaptive depth/width pruning is what makes it viable on a CPU box at
all — but note that even so, on this hardware the classical path is the *faster*
configuration (§4.15), not merely the fallback.
"""

from __future__ import annotations

from typing import ClassVar

from ai_engine.matchers.base import Matcher
from ai_engine.models import ComponentKind, DeferredImplementation, register
from ai_engine.models.torch_guard import TORCH_MODULE_NAME
from ai_engine.types import DescriptorKind, Device, FeatureSet, MatchSet
from ai_engine.version import MATCHER_VERSION

__all__ = ["LightGlueMatcher"]


@register(
    ComponentKind.MATCHER,
    fallback="flann",
    requires_packages=(TORCH_MODULE_NAME,),
    requires_weights=("lightglue_v1",),
    device_preference=Device.AUTO,
)
class LightGlueMatcher(DeferredImplementation, Matcher):
    """LightGlue: adaptive-depth learned matching over FLOAT descriptors."""

    name: ClassVar[str] = "lightglue"
    supported_kinds: ClassVar[frozenset[DescriptorKind]] = frozenset({DescriptorKind.FLOAT})
    version: ClassVar[str] = MATCHER_VERSION

    deferred_module: ClassVar[str] = __name__
    deferred_feature: ClassVar[str] = "LightGlue learned descriptor matching"

    def match(self, a: FeatureSet, b: FeatureSet) -> MatchSet:
        """Deferred. See the module docstring."""
        self._deferred()
