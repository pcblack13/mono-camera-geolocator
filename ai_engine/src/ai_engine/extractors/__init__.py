"""Feature extraction: image → keypoints + descriptors.

★ EVERY EXTRACTOR IN THIS PACKAGE IS DEFERRED (``docs/architecture/SCOPE.md``). The ABC,
the registry entries, the fallback chains and the descriptor metadata are real and
complete; the bodies raise `NotImplementedDeferred`. LandExplorer ships as a manual GCP
surveying tool, where the coordinate is a direct observation rather than an inference.

The chains, all of which end at a terminal extractor that needs no weights:

    superpoint → sift        dinov2 → sift        asift → sift
    akaze → orb              brisk → orb
    sift → ⊥                 orb → ⊥

★ Import a concrete class from here only if you mean to name it. Everything in the engine
resolves through the registry instead — `REGISTRY.resolve("sift", ComponentKind.EXTRACTOR,
cfg)` — because that is what makes the fallback policy exist in one place (L1, L11).
"""

from __future__ import annotations

from ai_engine.extractors.akaze import AkazeExtractor
from ai_engine.extractors.asift import AffineSimulatedExtractor
from ai_engine.extractors.base import FeatureExtractor
from ai_engine.extractors.brisk import BriskExtractor
from ai_engine.extractors.dinov2 import Dinov2DenseExtractor
from ai_engine.extractors.orb import OrbExtractor
from ai_engine.extractors.sift import SiftExtractor
from ai_engine.extractors.superpoint import SuperPointExtractor

__all__ = [
    "AffineSimulatedExtractor",
    "AkazeExtractor",
    "BriskExtractor",
    "Dinov2DenseExtractor",
    "FeatureExtractor",
    "OrbExtractor",
    "SiftExtractor",
    "SuperPointExtractor",
]
