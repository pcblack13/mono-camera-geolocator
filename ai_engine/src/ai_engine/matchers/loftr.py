"""`LoFTRMatcher` (detector-free) and `LoFTRAsMatcher` (a LOSSY shim). **DEFERRED.**

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``).

★ NOTE WHAT THE `loftr` SPEC DOES *NOT* HAVE: a `fallback`, and `is_terminal`. Both
absences are deliberate and neither is an oversight:

* **No fallback.** §11.1's chain table reads ``loftr → flann (via source swap)``, and
  `flann` is a `MATCHER`, not a `DETECTOR_FREE`. A `fallback="flann"` here would be looked
  up in the DETECTOR_FREE namespace, find nothing, exhaust the chain and raise
  `ComponentUnavailable` — a crash dressed up as a fallback. The swap is a *composition*
  decision: `pipeline.compose` drops the `DetectorFreeSource` and uses the
  `DetectBasedSource` alone. The registry cannot express "fall back to a different kind of
  thing", and should not try.
* **Not terminal.** `ComponentKind.DETECTOR_FREE` has **no terminal member at all**, because
  there is no classical detector-free matcher — that is the entire point of the family.
  Which is why `AiEngineConfig.detector_free` defaults to None: the default configuration
  does not ask for a component that cannot always be provided.

`LoFTRAsMatcher` exists **only** for `Matcher`-typed external plugin sockets. It is LOSSY —
it invents feature indices for a model that has none — sets ``requires_images = True`` so
that `DetectBasedSource`'s constructor assertion rejects it, and is **not registered**. The
pipeline never uses it.
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from ai_engine.matchers.base import DetectorFreeMatcher, Matcher
from ai_engine.models import ComponentKind, DeferredImplementation, register
from ai_engine.models.torch_guard import TORCH_MODULE_NAME
from ai_engine.types import Correspondences, DescriptorKind, Device, FeatureSet, MatchSet
from ai_engine.version import MATCHER_VERSION

__all__ = ["LoFTRAsMatcher", "LoFTRMatcher"]


@register(
    ComponentKind.DETECTOR_FREE,
    fallback=None,
    requires_packages=(TORCH_MODULE_NAME,),
    requires_weights=("loftr_outdoor_v1",),
    device_preference=Device.AUTO,
)
class LoFTRMatcher(DeferredImplementation, DetectorFreeMatcher):
    """LoFTR: transformer-based detector-free matching.

    Its value in this product is specific and complementary: it finds correspondence in
    the low-texture field interiors where SIFT finds nothing at all, while SIFT nails the
    high-frequency corners LoFTR's 1/8-resolution coarse stage misses. Failing in
    different places is the only good reason to ensemble two matchers — see
    `EnsembleSource`.
    """

    name: ClassVar[str] = "loftr"
    version: ClassVar[str] = MATCHER_VERSION

    deferred_module: ClassVar[str] = __name__
    deferred_feature: ClassVar[str] = "LoFTR detector-free matching"

    def match_images(
        self,
        image_a: np.ndarray,
        image_b: np.ndarray,
        mask_a: np.ndarray | None = None,
        mask_b: np.ndarray | None = None,
    ) -> Correspondences:
        """Deferred. See the module docstring."""
        self._deferred()


class LoFTRAsMatcher(DeferredImplementation, Matcher):
    """★ A LOSSY `Matcher`-shaped adapter over `LoFTRMatcher`. NOT registered. **DEFERRED.**

    It exists so that a `Matcher`-typed external plugin socket can be handed something
    detector-free. It is lossy by construction: LoFTR has no stable feature indices, so
    the `MatchSet.indices` this returns are synthesised, and any consumer that treats them
    as indices into the input `FeatureSet`s is wrong.

    ``requires_images = True`` is the guard. `DetectBasedSource.__init__` asserts
    ``not matcher.requires_images``, so this class can never be silently wired into the
    normal path — a mistake that would otherwise degrade the pipeline's accuracy with no
    error and no log line.

    When implemented, `match()` resolves `FeatureSet.image_ref` back to pixels through the
    `ImageStore` and raises `DetectorFreeRequiresImages` when it cannot: a detector-free
    model with no images has nothing to work on, and saying so is better than returning an
    empty `MatchSet` that reads as "no matches found".
    """

    name: ClassVar[str] = "loftr_as_matcher"
    supported_kinds: ClassVar[frozenset[DescriptorKind]] = frozenset(
        {DescriptorKind.FLOAT, DescriptorKind.BINARY}
    )
    #: ★ THE GUARD. `DetectBasedSource` asserts this is False.
    requires_images: ClassVar[bool] = True
    version: ClassVar[str] = MATCHER_VERSION

    deferred_module: ClassVar[str] = __name__
    deferred_feature: ClassVar[str] = "LoFTR-as-Matcher (lossy) adaptation"

    def match(self, a: FeatureSet, b: FeatureSet) -> MatchSet:
        """Deferred. See the class docstring."""
        self._deferred()
