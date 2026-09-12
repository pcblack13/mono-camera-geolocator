"""`BruteForceMatcher` — ★ a TERMINAL fallback. **DEFERRED.**

The end of the matcher chain (`superglue → flann → bf`), and terminal for the reason every
terminal spec is: no weights, no optional packages, so it provably constructs. Exhaustive
search is slow and always correct, which is exactly what you want at the bottom of a
fallback chain.

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``).

When implemented: `cv2.BFMatcher(cv2.NORM_L2)` for FLOAT and `cv2.NORM_HAMMING` for
BINARY, `knnMatch(k=2)`, then the Lowe ratio test and the cross-check from
`matchers/filters.py`. Scores normalised per `matchers/base.py`'s ratio-test rule.
"""

from __future__ import annotations

from typing import ClassVar

from ai_engine.matchers.base import Matcher
from ai_engine.models import ComponentKind, DeferredImplementation, register
from ai_engine.types import DescriptorKind, Device, FeatureSet, MatchSet
from ai_engine.version import MATCHER_VERSION

__all__ = ["BruteForceMatcher"]


@register(ComponentKind.MATCHER, fallback=None, is_terminal=True, device_preference=Device.CPU)
class BruteForceMatcher(DeferredImplementation, Matcher):
    """Exhaustive descriptor search. Handles both descriptor kinds.

    ★ TERMINAL. The matcher chain ends here.
    """

    name: ClassVar[str] = "bf"
    supported_kinds: ClassVar[frozenset[DescriptorKind]] = frozenset(
        {DescriptorKind.FLOAT, DescriptorKind.BINARY}
    )
    version: ClassVar[str] = MATCHER_VERSION

    deferred_module: ClassVar[str] = __name__
    deferred_feature: ClassVar[str] = "brute-force descriptor matching"

    def match(self, a: FeatureSet, b: FeatureSet) -> MatchSet:
        """Deferred. See the module docstring."""
        self._deferred()
