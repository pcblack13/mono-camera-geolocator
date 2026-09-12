"""The engine's deliverables.

★ Note what `GcpPixelFix` does NOT have: no lat, no lon, no elevation. `ai_engine` ends
at `window_xy` and a covariance in window pixels. Turning that into a coordinate is
`gis`'s job. That single absence is the boundary (L3), and it is why this package can be
tested with no network, no weights and no GPU.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np

from ai_engine.types.degeneracy import DegeneracyReport
from ai_engine.types.enums import ViewRegime
from ai_engine.types.geometry import HomographyResult, PoseResult
from ai_engine.types.heatmap import PixelHeatmap
from ai_engine.types.landmarks import LandmarkEvidence
from ai_engine.types.matches import Correspondences
from ai_engine.types.provenance import ResolutionReport  # ★ types -> types. NEVER types -> models.
from ai_engine.types.scoring import ScoreResult
from ai_engine.types.windows import CandidateWindow

__all__ = [
    "GcpPixelFix",
    "MatchJobResult",
    "PixelAccuracy",
    "WindowResult",
]


@dataclass(frozen=True, slots=True)
class PixelAccuracy:
    """★ PIXELS ONLY. This type carries our fit's uncertainty IN THE WINDOW FRAME and
    stops there.

    Metres are `gis.accuracy`'s job — it is the SINGLE PRODUCER of the four survey
    numbers (relative_m, georef_ce90_m, total_ce90_m, dominant_term). Computing
    `relative_px * window.gsd_m` here would look harmless and would be the exact
    metre-versus-projected-metre conflation that `gis.accuracy` exists to prevent; it
    would happen to be right only because `gsd_m` is corrected, an invariant this module
    cannot see or enforce. Three producers of one number is three chances to disagree.
    There is one.
    """

    relative_px: float  # our fit to the provider's pixels, 1-sigma, WINDOW PIXELS
    cov_px: np.ndarray
    # (2,2) float64 covariance in WINDOW PIXELS. The full anisotropy — gis.accuracy needs
    # it to build the error ellipse, and collapsing it to one scalar here would throw away
    # the most actionable part of the estimate.


@dataclass(frozen=True, slots=True)
class GcpPixelFix:
    """★ ai_engine's DELIVERABLE: one landmark, located in one window's pixels."""

    landmark_id: int
    external_id: str | None  # opaque echo of LandmarkSet.external_ids[k]
    image_xy: tuple[float, float]
    window_xy: tuple[float, float]
    cov_px: np.ndarray  # (2,2) float64 covariance in WINDOW pixels
    residual_px: float | None  # ||H*image_xy - direct_fix|| when a direct fix exists
    confidence: float  # 0..100
    accuracy: PixelAccuracy
    has_direct_fix: bool


@dataclass(frozen=True, slots=True)
class WindowResult:
    """Everything one candidate window produced."""

    window: CandidateWindow
    correspondences: Correspondences
    homography: HomographyResult | None  # None when estimation was not attempted
    degeneracy: DegeneracyReport
    score: ScoreResult
    landmark_evidence: tuple[LandmarkEvidence, ...]
    regime: ViewRegime
    pose: PoseResult | None = None
    timings_ms: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MatchJobResult:
    """★ The ONLY thing run_match_job returns — including when it finds nothing.

    "No match found" is a RESULT, not a failure: it comes back as
    ``status="no_viable_candidate"`` with ``best=None`` and no fixes. An empty `ranked`
    is a legitimate outcome and callers must render it as an answer rather than an error.
    """

    job_id: str
    ranked: tuple[WindowResult, ...]  # rank 1 first. EMPTY is a legitimate result.
    best: WindowResult | None  # None <=> no window passed the gates
    gcp_fixes: tuple[GcpPixelFix, ...]  # from `best`; empty when best is None
    provenance: ResolutionReport  # ★ WHICH components actually produced this
    ambiguity_margin: float | None  # ★ computed on ScoreResult.RAW, never on the clamped confidence
    status: str  # "matched" | "no_viable_candidate" | "ambiguous"
    warnings: tuple[str, ...]
    timings_ms: Mapping[str, float]
    engine_version: str
    seed: int
    heatmaps: tuple[PixelHeatmap, ...] = ()
    # ★ PLURAL, and each carries its own WindowRef. Each lives in ITS OWN window's pixel
    #   frame; fusing them into one true-metre grid is gis.heatmap.fuse_pixel_heatmaps().
