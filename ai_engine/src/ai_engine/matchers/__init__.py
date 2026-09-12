"""Matching: descriptors or images → correspondences.

★ EVERY MATCHER IN THIS PACKAGE IS DEFERRED (``docs/architecture/SCOPE.md``). The two ABCs,
the `CorrespondenceSource` seam, the registry entries and the fallback chains are real; the
bodies raise `NotImplementedDeferred`.

The chains:

    superglue → flann → bf → ⊥       lightglue → flann → bf → ⊥
    loftr → ⊥ (via source swap in `pipeline.compose`, NOT via a registry fallback)

The pipeline depends on `CorrespondenceSource`, never on `Matcher` — see `sources.py`.
"""

from __future__ import annotations

from ai_engine.matchers.base import DetectorFreeMatcher, Matcher
from ai_engine.matchers.bruteforce import BruteForceMatcher
from ai_engine.matchers.flann import FlannMatcher
from ai_engine.matchers.lightglue import LightGlueMatcher
from ai_engine.matchers.loftr import LoFTRAsMatcher, LoFTRMatcher
from ai_engine.matchers.sources import (
    CorrespondenceSource,
    DetectBasedSource,
    DetectorFreeSource,
    EnsembleSource,
)
from ai_engine.matchers.superglue import SuperGlueMatcher

__all__ = [
    "BruteForceMatcher",
    "CorrespondenceSource",
    "DetectBasedSource",
    "DetectorFreeMatcher",
    "DetectorFreeSource",
    "EnsembleSource",
    "FlannMatcher",
    "LightGlueMatcher",
    "LoFTRAsMatcher",
    "LoFTRMatcher",
    "Matcher",
    "SuperGlueMatcher",
]
