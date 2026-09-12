"""User landmarks — the points a human marked, and the evidence we gathered about them.

A landmark is not a detection. Nothing proposed it; a surveyor pointed at it. That is
why it enters the descriptor space through `extract_at()` rather than through a
detector, why it carries a human click precision (`sigma_px`) rather than a detector
response, and why its identity (`landmark_ids`) is threaded all the way into RANSAC
weighting.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from ai_engine.types.enums import Device

__all__ = [
    "Landmark",
    "LandmarkEvidence",
    "LandmarkFix",
    "LandmarkProposal",
    "LandmarkSet",
    "LandmarkType",
    "LandmarkWeightField",
    "SuggesterCapabilities",
    "SuggestionStrategy",
]


class LandmarkType(StrEnum):
    """What kind of thing the surveyor marked. Advisory: it steers patch search and
    semantic agreement, and it never gates a solve.
    """

    UNSPECIFIED = "unspecified"
    FIELD_CORNER = "field_corner"
    ROAD_INTERSECTION = "road_intersection"
    BUILDING_CORNER = "building_corner"
    TREE = "tree"
    POLE_OR_PYLON = "pole_or_pylon"
    FENCE_POST = "fence_post"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class Landmark:
    """One marked point in the query photograph."""

    id: int  # dense 0..K-1 index within the job
    xy: tuple[float, float]  # QUERY IMAGE pixels, y-down, top-left origin
    type: LandmarkType = LandmarkType.UNSPECIFIED
    label: str | None = None
    radius_px: float = 32.0
    user_weight: float = 1.0  # from annotations.confidence (0-1), scaled
    sigma_px: float = 3.0  # ★ human click precision — the DOMINANT query-side error


@dataclass(frozen=True, slots=True)
class LandmarkSet:
    """The job's landmarks, in a fixed order that `Landmark.id` indexes."""

    items: tuple[Landmark, ...]
    external_ids: tuple[str, ...] = ()
    # opaque; the backend puts annotations.id UUIDs here. ai_engine NEVER parses these.

    @property
    def points(self) -> np.ndarray:
        """(K,2) float32 — the marked positions, in query-image pixels."""
        if not self.items:
            return np.zeros((0, 2), dtype=np.float32)
        return np.asarray([lm.xy for lm in self.items], dtype=np.float32)

    @property
    def weights(self) -> np.ndarray:
        """(K,) float32 — the per-landmark user weights."""
        if not self.items:
            return np.zeros((0,), dtype=np.float32)
        return np.asarray([lm.user_weight for lm in self.items], dtype=np.float32)

    def __len__(self) -> int:
        return len(self.items)


@dataclass(frozen=True, slots=True)
class LandmarkFix:
    """A direct correspondence for landmark k, found by patch search in the window."""

    landmark_id: int
    window_xy: tuple[float, float]
    score: float  # [0,1]
    method: str  # "patch_ncc" | "descriptor" | "guided"
    used_in_solve: bool = False
    # ★ True => this fix fed the solve: it seeded H_seed, was merged in as a
    #   correspondence, or received PROSAC sampling priority. Such a fix is INELIGIBLE
    #   for transfer_k, because measuring the residual of a fit against the very points
    #   that produced the fit is a FITTING RESIDUAL SOLD AS A SECOND OPINION.


@dataclass(frozen=True, slots=True)
class LandmarkEvidence:
    """Everything we learned about one landmark in one window."""

    landmark_id: int
    has_direct_fix: bool
    fix: LandmarkFix | None
    support_count: int  # inliers within radius_px of the landmark
    patch_score: float | None  # [0,1] NCC of the warped patch
    transfer_error_px: float | None
    transfer_is_holdout: bool = False
    # ★ True <=> transfer_error_px was measured against a fix with used_in_solve=False.
    #   When False, transfer_k MUST be None — an independence claim we can actually keep.
    semantic_agreement: float | None = None  # [0,1]
    score: float = 0.0  # [0,1] combined — see the S_l formula


@dataclass(frozen=True, slots=True)
class LandmarkWeightField:
    """Per-correspondence sampling PRIORITY derived from proximity to user landmarks.

    Evaluates::

        g(p) = ( sum_k w_k * exp(-d_k(p)**2 / (2 * R_L**2)) ) / max(sum_k w_k, eps)
        priority(p) = base_score(p) * (1 + lam*g(p)) * (1 + mu*on_landmark(p))

    ★ THE NORMALISATION IS LOAD-BEARING. Without the division by ``sum_k w_k``, g is a
      bare sum over K landmarks: with 12 landmarks clustered inside R_L at w_k=4,
      ``g ~= 48`` and the priority factor is ``(1+2*48)*(1+3) = 388x`` — two orders of
      magnitude against a base_score spanning only one. PROSAC's ordering would collapse
      into a pure landmark-DENSITY map, discarding descriptor quality entirely, and it
      would degrade WORST in exactly the case the design targets: a surveyor who marked
      many landmarks on one structure. Dividing puts ``g in [0,1]`` and makes the stated
      12x bound the real bound.

    This is a PRIORITY, not a confidence. It orders PROSAC's sampling; it never enters a
    score.
    """

    points: np.ndarray  # (K,2) float32 — landmark positions, QUERY px
    weights: np.ndarray  # (K,) float32 — Landmark.user_weight
    radius_px: float = 96.0  # R_L
    lam: float = 2.0  # lambda — density boost
    mu: float = 3.0  # mu — exact-landmark boost

    def evaluate(self, pts: np.ndarray) -> np.ndarray:
        """(M,2) -> (M,) float32 in [0,1]. This is g(p), NOT the final priority."""
        query = np.asarray(pts, dtype=np.float64)
        if query.ndim != 2 or query.shape[1] != 2:
            raise ValueError(f"pts must be (M,2); got shape {query.shape}")

        m = query.shape[0]
        if self.points.size == 0 or m == 0:
            return np.zeros((m,), dtype=np.float32)

        anchors = np.asarray(self.points, dtype=np.float64)
        if anchors.ndim != 2 or anchors.shape[1] != 2:
            raise ValueError(f"points must be (K,2); got shape {anchors.shape}")
        w = np.asarray(self.weights, dtype=np.float64)
        if w.shape != (anchors.shape[0],):
            raise ValueError(
                f"weights must be (K,) with K={anchors.shape[0]}; got shape {w.shape}"
            )
        if self.radius_px <= 0:
            raise ValueError(f"radius_px must be positive; got {self.radius_px}")

        # (M,K) squared distances, then the normalised Gaussian mixture.
        d2 = np.sum((query[:, None, :] - anchors[None, :, :]) ** 2, axis=2)
        kernel = np.exp(-d2 / (2.0 * self.radius_px**2))
        total = max(float(np.sum(w)), np.finfo(np.float64).eps)
        g = (kernel @ w) / total
        return np.clip(g, 0.0, 1.0).astype(np.float32)


@dataclass(frozen=True, slots=True)
class LandmarkProposal:
    """★ The output of a LandmarkSuggester. Maps 1:1 onto a `landmark_suggestions` row.

    ai_engine proposes; a human accepts; only then is it an annotation (ADR-014).
    """

    xy: tuple[float, float]  # QUERY IMAGE pixels
    kind: LandmarkType
    score: float  # [0,1] the detector's own
    rank: int  # 1 = best
    rationale: str  # human-readable "why" -> landmark_suggestions.rationale


class SuggestionStrategy(StrEnum):
    """How a suggester looks for candidate landmarks. Wire-only — deliberately NOT in
    enum parity scope (no PG type).
    """

    CORNERS = "corners"
    SALIENCY = "saliency"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"


@dataclass(frozen=True, slots=True)
class SuggesterCapabilities:
    """What a LandmarkSuggester can actually offer.

    ★ Declared HERE for the same reason as `SemanticCapabilities`: `landmarks/suggest.py`
      does ``from ai_engine.types import SuggesterCapabilities`` and annotates
      ``capabilities()`` with it. A type named in a signature and defined nowhere is an
      ImportError on the implementing unit's first line.

    `strategies` is what makes the fallback honest: the classical path does not offer
    `SALIENCY`, says so here, and a request for it resolves through the normal chain and
    reports ``effective: "hybrid"`` in a WarningItem rather than silently returning
    corners and calling them saliency.
    """

    strategies: frozenset[SuggestionStrategy]  # what this suggester can actually run
    requires_weights: bool
    supports_semantics: bool  # can consume a prior SemanticMap
    is_deterministic: bool
    device: Device
