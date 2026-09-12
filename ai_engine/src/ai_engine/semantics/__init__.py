"""Semantics: optional masks that gate and weight features.

★ EVERYTHING IN THIS PACKAGE IS DEFERRED (``docs/architecture/SCOPE.md``). The
`SemanticSegmenter` ABC and the three registry entries are real; the bodies are not.

The chain: ``sam → classical`` · ``dinov2_seg → classical`` · ``classical → ⊥``.

Two rules run through the whole package and survive the deferral, because they are what
the interfaces are shaped around:

* **Provenance is per class and mandatory.** An HSV guess and a spectral measurement must
  never arrive indistinguishable.
* **Decline rather than fabricate.** Curved rows have no orientation; RGB has no NDWI;
  absent semantics are `None` and not `0.5`.
"""

from __future__ import annotations

from ai_engine.semantics.base import SemanticSegmenter
from ai_engine.semantics.classical import ClassicalSemantics
from ai_engine.semantics.dinov2_seg import Dinov2Semantics
from ai_engine.semantics.sam import SamSegmenter

__all__ = [
    "ClassicalSemantics",
    "Dinov2Semantics",
    "SamSegmenter",
    "SemanticSegmenter",
]
