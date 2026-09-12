"""The shared vocabulary of the CV domain — value objects only.

★ THIS PACKAGE IMPORTS ONLY numpy AND THE STDLIB, AND THAT IS A LOAD-BEARING PROPERTY,
NOT A STYLE PREFERENCE.

`gis.candidates` is permitted exactly one cross-package import — `ai_engine.types` — and
the justification for permitting it is precisely that this package is cheap and stable
and cannot drag in `cv2`, `torch` or a model registry. Two rules follow, and
`tests/test_types_import_cheap.py` enforces both on a fresh interpreter:

1. **`ai_engine.types` MUST NOT import `ai_engine.models`.** That is why
   `provenance.py` lives here rather than in `models/spec.py`: `types/results.py` needs
   `ResolutionReport`, and the dependency may only ever point this way. `models/spec.py`
   re-exports FROM here.
2. **`ai_engine/__init__.py` MUST NOT import the pipeline at module scope.** If the
   package root imported the pipeline, `from ai_engine.types import CandidateWindow`
   would execute it and drag in cv2, scipy and every extractor — destroying the exact
   property that permits the cross-import at all. The root is `__getattr__`-lazy.

This module is the ONLY import site downstream code should use:
``from ai_engine.types import FeatureSet`` — not ``from ai_engine.types.features import``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from ai_engine.types.cache import CacheBackend, ImageStore
from ai_engine.types.degeneracy import DegeneracyCheck, DegeneracyReport
from ai_engine.types.enums import (
    DescriptorKind,
    Device,
    HomographyMethod,
    PoseMethod,
    SemanticClass,
    Severity,
    ViewRegime,
)
from ai_engine.types.features import ExtractorCapabilities, FeatureSet, ImageRef
from ai_engine.types.geometry import (
    CameraIntrinsics,
    HomographyResult,
    PoseResult,
    RansacConfig,
)
from ai_engine.types.heatmap import HeatmapComponent, PixelHeatmap
from ai_engine.types.landmarks import (
    Landmark,
    LandmarkEvidence,
    LandmarkFix,
    LandmarkProposal,
    LandmarkSet,
    LandmarkType,
    LandmarkWeightField,
    SuggesterCapabilities,
    SuggestionStrategy,
)
from ai_engine.types.matches import Correspondences, CorrespondenceRequest, MatchSet
from ai_engine.types.provenance import (
    ComponentKind,
    ComponentSpec,
    PreflightReport,
    Resolution,
    ResolutionReport,
)
from ai_engine.types.results import (
    GcpPixelFix,
    MatchJobResult,
    PixelAccuracy,
    WindowResult,
)
from ai_engine.types.scoring import ScoreEvidence, ScoreResult, ScoreTerms
from ai_engine.types.semantics import (
    CropRowField,
    RidgeSet,
    SemanticCapabilities,
    SemanticMap,
    TreeLattice,
)
from ai_engine.types.windows import CandidateWindow, WindowRef, WindowSource

#: ★ A CLOSED literal set, and it is IDENTICAL to the `match` JobStage values.
#:
#: A free-form `stage: str` would leave nothing mapping whatever the pipeline chose
#: (`step1_extract_query_features`? `extract_query`?) onto the closed enum the UI
#: switches on — and the two are written by disjoint units that will not agree by luck.
#: Making the emitted set literally the JobStage values means `tasks/progress.py` needs
#: no translation table at all.
MatchStage = Literal[
    "resolving_models",
    "fetching_tiles",
    "extracting_query",
    "extracting_train",
    "matching",
    "estimating_homography",
    "scoring",
    "deriving_gcps",
]

#: Called at every stage boundary as ``(stage, fraction_complete, message)``.
#: `ai_engine` knows nothing about Redis, Celery or Postgres — this callback is the
#: entire coupling.
ProgressCallback = Callable[[MatchStage, float, str], None]

__all__ = [
    # aliases
    "MatchStage",
    "ProgressCallback",
    # cache
    "CacheBackend",
    "ImageStore",
    # degeneracy
    "DegeneracyCheck",
    "DegeneracyReport",
    # enums
    "DescriptorKind",
    "Device",
    "HomographyMethod",
    "PoseMethod",
    "SemanticClass",
    "Severity",
    "ViewRegime",
    # features
    "ExtractorCapabilities",
    "FeatureSet",
    "ImageRef",
    # geometry
    "CameraIntrinsics",
    "HomographyResult",
    "PoseResult",
    "RansacConfig",
    # heatmap
    "HeatmapComponent",
    "PixelHeatmap",
    # landmarks
    "Landmark",
    "LandmarkEvidence",
    "LandmarkFix",
    "LandmarkProposal",
    "LandmarkSet",
    "LandmarkType",
    "LandmarkWeightField",
    "SuggesterCapabilities",
    "SuggestionStrategy",
    # matches
    "Correspondences",
    "CorrespondenceRequest",
    "MatchSet",
    # provenance
    "ComponentKind",
    "ComponentSpec",
    "PreflightReport",
    "Resolution",
    "ResolutionReport",
    # results
    "GcpPixelFix",
    "MatchJobResult",
    "PixelAccuracy",
    "WindowResult",
    # scoring
    "ScoreEvidence",
    "ScoreResult",
    "ScoreTerms",
    # semantics
    "CropRowField",
    "RidgeSet",
    "SemanticCapabilities",
    "SemanticMap",
    "TreeLattice",
    # windows
    "CandidateWindow",
    "WindowRef",
    "WindowSource",
]
