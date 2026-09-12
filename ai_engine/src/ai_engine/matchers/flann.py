"""`FlannMatcher` — ★ the DEFAULT matcher. Falls back to `bf`. **DEFERRED.**

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``).

When implemented, the index MUST be selected from `descriptor_kind`, automatically:

* FLOAT  → ``KDTreeIndexParams(trees=4)``
* BINARY → ``LshIndexParams(table_number=12, key_size=20, multi_probe_level=2)``

and a mixed pair MUST raise `IncompatibleDescriptors` — which `Matcher.validate_pair`
already does, and which this class must call first.

★ THIS IS THE CLASS THAT MAKES `DescriptorKind` WORTH HAVING. A FLANN KD-tree handed
bit-packed ORB bytes does not fail. It treats the packed bytes as a 32-dimensional float
vector, finds nearest neighbours in a space with no meaning, and returns matches that look
entirely reasonable — right count, plausible score distribution, no warning. Those become
correspondences, a homography, a confidence, and a coordinate a surveyor may dig against.
The type check is the only thing standing there, which is why it lives in the base class
and is not optional.
"""

from __future__ import annotations

from typing import ClassVar

from ai_engine.matchers.base import Matcher
from ai_engine.models import ComponentKind, DeferredImplementation, register
from ai_engine.types import DescriptorKind, Device, FeatureSet, MatchSet
from ai_engine.version import MATCHER_VERSION

__all__ = ["FlannMatcher"]


@register(ComponentKind.MATCHER, fallback="bf", device_preference=Device.CPU)
class FlannMatcher(DeferredImplementation, Matcher):
    """Approximate nearest-neighbour matching, index chosen from the descriptor kind."""

    name: ClassVar[str] = "flann"
    supported_kinds: ClassVar[frozenset[DescriptorKind]] = frozenset(
        {DescriptorKind.FLOAT, DescriptorKind.BINARY}
    )
    version: ClassVar[str] = MATCHER_VERSION

    deferred_module: ClassVar[str] = __name__
    deferred_feature: ClassVar[str] = "FLANN approximate descriptor matching"

    def match(self, a: FeatureSet, b: FeatureSet) -> MatchSet:
        """Deferred. See the module docstring."""
        self._deferred()
