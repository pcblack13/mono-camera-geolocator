"""`MatchContext` and `SearchSeed` — the immutable per-job bundle.

★ THESE TYPES ARE REAL AND COMPLETE. They are the shape of a job, and they are what makes
the engine testable with no network, no GPU, no weights and no database: **every dependency
is injected**. The engine constructs nothing it could be given. `windows` is a `WindowSource`
that `gis` implements and the composition root injects; `cache` is a `CacheBackend` a test
can satisfy with `NullCache`; `on_progress` is a plain callable, and it is the *entire*
coupling to Celery, Redis and Postgres — none of which `ai_engine` has ever heard of.

The components it holds are all deferred in this build (``docs/architecture/SCOPE.md``), so
a `MatchContext` cannot currently be constructed with live ones. The dataclass is real
anyway: it is the contract `pipeline.compose` will fill in, and its field list is what makes
re-enabling the engine a zero-caller-change operation.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ai_engine.config import AiEngineConfig
from ai_engine.extractors.base import FeatureExtractor
from ai_engine.geometry.base import GeometryEstimator
from ai_engine.geometry.degeneracy import DegeneracyValidator
from ai_engine.matchers.sources import CorrespondenceSource
from ai_engine.scoring.base import ScoringModel
from ai_engine.semantics.base import SemanticSegmenter
from ai_engine.types import (
    CacheBackend,
    CameraIntrinsics,
    ImageRef,
    LandmarkSet,
    ProgressCallback,
    WindowSource,
)

__all__ = ["MatchContext", "SearchSeed"]


@dataclass(frozen=True, slots=True)
class SearchSeed:
    """★ A prior that narrows the search before it starts.

    A seed is what a job knows *before* any window is fetched. It exists because the two
    things that most reduce this problem's difficulty are both known up front: a previously
    solved homography for a re-run, and the surveyor's own confirmed correspondences.

    ★ THE CONTRACT DOES NOT SPECIFY THIS TYPE'S FIELDS — §2.2 names `SearchSeed` beside
    `MatchContext` and §4.13 defines only `MatchContext`. The shape below is this unit's
    choice, kept deliberately minimal and pinned to things the contract DOES define:
    `prior_H`/`prior_cov` mirror `CorrespondenceRequest`'s fields exactly, and
    `landmark_fixes` is the existing `LandmarkFix` vocabulary. Flagged as an open decision
    in the unit report rather than buried here.

    Attributes:
        prior_H: `(3,3)` float64 mapping the query frame to a window frame, from a previous
            solve. Triggers the guided path when present. ★ Correspondences produced under
            it MUST carry `prior_free=False` — a gated set's inlier ratio measures the gate,
            not the fit (§4.12).
        prior_cov: `(9,9)` float64 covariance of row-major `vec(prior_H)` in the `h33=1`
            gauge (§4.24). Widens the guided search radius per point instead of trusting the
            prior uniformly.
        guided_radius_px: The base search radius in the window frame.
        landmark_fixes: Confirmed landmark → window-pixel correspondences. In this build
            these are exactly what the manual GCP flow produces, which is why they are the
            most valuable seed the engine will ever get: they are direct observations, not
            inferences.
        window_key_hint: An opaque `WindowRef.key` to try first. Carried, never parsed.
    """

    prior_H: np.ndarray | None = None
    prior_cov: np.ndarray | None = None
    guided_radius_px: float = 32.0
    landmark_fixes: tuple[object, ...] = ()
    window_key_hint: str | None = None


@dataclass(frozen=True, slots=True)
class MatchContext:
    """One job's immutable bundle. Every dependency is injected.

    Attributes:
        job_id: The job's identifier. Opaque to the engine; used for logging and echoed
            into `MatchJobResult.job_id`.
        config: The engine configuration for this job.
        query_image: `(H,W,3)` uint8 RGB — the surveyor's photograph.
        query_image_ref: The content-addressed handle for `query_image`, so a `FeatureSet`
            can point back at its image without pinning the array in memory.
        landmarks: The surveyor's landmarks, in ORIGINAL image pixel space.
        windows: ★ THE SEAM. A `WindowSource` implemented by `gis` and injected by the
            composition root. The engine iterates it and never asks where the pixels came
            from — which is what makes L3 mechanical.
        extractor: Resolved via the registry.
        source: The correspondence source — detector-based, detector-free, or an ensemble.
            The pipeline depends on this, never on a `Matcher`.
        estimator: The homography estimator.
        segmenter: The semantic segmenter.
        scorer: The scoring model.
        validator: The degeneracy validator. ★ Not a registry component and deliberately
            not swappable — a deployment that could configure its way out of the degeneracy
            gate is one that can emit a confident wrong coordinate.
        cache: Typed on the `CacheBackend` Protocol rather than on `DiskCache`, which is
            what lets a test inject `NullCache` with nothing installed and no disk touched.
        intrinsics_hint: Camera intrinsics from EXIF, resolved by the backend.
        on_progress: Called at every stage boundary. ★ The entire coupling to the outside
            world. Its stage is a closed literal set identical to the `match` job stages, so
            the worker needs no translation table.
    """

    job_id: str
    config: AiEngineConfig
    query_image: np.ndarray
    query_image_ref: ImageRef
    landmarks: LandmarkSet
    windows: WindowSource
    extractor: FeatureExtractor
    source: CorrespondenceSource
    estimator: GeometryEstimator
    segmenter: SemanticSegmenter
    scorer: ScoringModel
    validator: DegeneracyValidator
    cache: CacheBackend
    intrinsics_hint: CameraIntrinsics | None = None
    on_progress: ProgressCallback | None = None
    seed: SearchSeed | None = None
