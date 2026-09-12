"""Scoring — the number the product reports, and everything it was computed from.

The design commitment here is that a score is never a bare float. `ScoreEvidence` is what
went in, `ScoreTerms` is how it decomposed, and `feature_vector` is persisted so a
calibration can be refit offline without re-running any CV. A confidence nobody can
reconstruct is a confidence nobody should act on.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np

from ai_engine.types.degeneracy import DegeneracyReport
from ai_engine.types.enums import ViewRegime
from ai_engine.types.geometry import HomographyResult
from ai_engine.types.landmarks import LandmarkEvidence, LandmarkSet
from ai_engine.types.matches import Correspondences
from ai_engine.types.semantics import SemanticMap
from ai_engine.types.windows import CandidateWindow

__all__ = ["ScoreEvidence", "ScoreResult", "ScoreTerms"]


@dataclass(frozen=True, slots=True)
class ScoreTerms:
    """The four signals and the gate, kept separable.

    `s_semantic` is None — not 0.5, and not 0.0 — when semantics are unavailable. A None
    term drops out of BOTH the numerator and the denominator, so the remaining weights
    renormalise. Substituting a neutral value instead would silently pull every score
    toward it and make the weight table mean something other than what it says.
    """

    s_feature: float  # [0,1]
    s_geometry: float  # [0,1]
    s_landmark: float  # [0,1]
    s_semantic: float | None  # [0,1] or None if semantics unavailable -> weights renormalise
    gate: float  # [0,1] degeneracy gate, multiplicative
    weights: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class ScoreEvidence:
    """Everything the scorer is allowed to look at, for one window.

    Passing the whole bundle rather than pre-reduced numbers is deliberate: it keeps the
    scoring model a pure function of stated inputs, which is what makes it swappable and
    what makes the persisted `feature_vector` reproducible.
    """

    correspondences: Correspondences
    homography: HomographyResult
    degeneracy: DegeneracyReport
    landmarks: LandmarkSet
    landmark_evidence: Sequence[LandmarkEvidence]
    query_semantics: SemanticMap | None
    window_semantics: SemanticMap | None
    regime: ViewRegime
    query_image_size: tuple[int, int]
    window: CandidateWindow


@dataclass(frozen=True, slots=True)
class ScoreResult:
    """★ `confidence` is THE number the product reports, and it is 0..100.

    `calibrated` ships FALSE and `calibration_id` ships "identity". This is not a gap to
    be filled in with a plausible curve: a fabricated calibration is a lie with a
    probability attached to it. Until a curve is fitted against real ground truth — which
    is exactly what the manual GCP mode produces — `confidence` is an ORDINAL score, and
    every consumer that renders it must treat it as one.
    """

    confidence: float  # ★ 0..100 — THE number the product reports
    raw: float  # [0,1] pre-calibration, pre-clamp weighted sum * gate
    terms: ScoreTerms
    calibrated: bool  # ★ ships FALSE
    calibration_id: str  # "identity" | "default-v1" | ...
    clamp_reason: str | None  # e.g. "regime=oblique_raw ceiling 60"
    status: Literal["accepted", "advisory", "rejected"]
    feature_vector: np.ndarray
    # (F,) float32 — raw terms, PERSISTED so calibration can be refit offline without
    # re-running any CV. Column names come from ScoringModel.feature_names() and must be
    # stable across versions, or the persisted training data becomes unreadable.
