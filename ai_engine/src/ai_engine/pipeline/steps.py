"""The nine pipeline steps, each a pure typed function. **DEFERRED.**

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``). The signatures are real; the
bodies raise.

Two structural notes that survive the deferral, because they are the reason the step list
looks the way it does:

★ **Steps 1 and 2 are ONE interface, not two.** Detection and description are a single call
in every real extractor, and splitting them forces a wasteful second traversal of the image.
Step 2 is realised as the descriptor path that genuinely *is* separate: `extract_at()` —
describing at **externally supplied** points, i.e. the surveyor's landmarks, which no
detector proposed. That is why there is no `step2_`.

★ **Step 6 must sort, estimate, then UN-PERMUTE.** PROSAC requires descending-by-weight
ordering — hand `SAMPLING_PROSAC` unsorted data and it silently degrades to uniform
sampling. But after the sort, `inlier_mask` and `residuals` align to the SORTED order, not
to `WindowResult.correspondences`, which is the original. Nothing else in the pipeline knows
a permutation happened, so if it escapes this step, every landmark support count, every
`LandmarkEvidence.support_count` and every `gcps.residual_px` silently indexes the WRONG
correspondence — no crash, entirely plausible numbers. Un-permuting inside step 6 is what
keeps the permutation from ever escaping::

    c_sorted, perm = c.sorted_by_weight()
    res = ctx.estimator.estimate_homography(c_sorted.pts_a, c_sorted.pts_b, cfg, weights=...)
    inv = np.empty_like(perm); inv[perm] = np.arange(len(perm))
    res = replace(res, inlier_mask=res.inlier_mask[inv], residuals=res.residuals[inv])
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import NoReturn

from ai_engine.errors import NotImplementedDeferred
from ai_engine.pipeline.context import MatchContext
from ai_engine.types import (
    CandidateWindow,
    Correspondences,
    FeatureSet,
    HomographyResult,
    MatchJobResult,
    ScoreEvidence,
    ScoreResult,
    WindowResult,
)

__all__ = [
    "step1_extract_query_features",
    "step3_iter_windows",
    "step4_extract_window_features",
    "step5_correspond",
    "step6_estimate_homography",
    "step7_score",
    "step8_rank",
    "step9_finalize",
]


def _deferred(feature: str) -> NoReturn:
    """Raise `NotImplementedDeferred` naming this module and `feature`."""
    raise NotImplementedDeferred(__name__, feature=feature)


def step1_extract_query_features(ctx: MatchContext) -> FeatureSet:
    """Step 1+2: detect and describe the query photograph, including at the landmarks.

    Args:
        ctx: The job bundle.

    Returns:
        A `validate()`-clean `FeatureSet` whose `landmark_ids` identify which keypoints are
        the surveyor's landmarks (>= 0) and which were detected (-1).

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    _deferred("query feature extraction (pipeline step 1)")


def step3_iter_windows(ctx: MatchContext) -> Iterator[CandidateWindow]:
    """Step 3: iterate the candidate windows.

    Args:
        ctx: The job bundle. `ctx.windows` is the injected `WindowSource`.

    Returns:
        A lazy iterator over candidate windows.

    ★ A `WindowFetchError` on an INDIVIDUAL window is logged, counted, and skipped — the
    job continues. That is why the seam's exception type lives in `ai_engine.errors`: the
    orchestrator must be able to name what it catches, and `ai_engine.pipeline` may not
    import `gis`. Its only alternative would be `except Exception`, which is a defect.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    _deferred("candidate window iteration (pipeline step 3)")


def step4_extract_window_features(ctx: MatchContext, w: CandidateWindow) -> FeatureSet:
    """Step 4: detect and describe one candidate window.

    Args:
        ctx: The job bundle.
        w: The window.

    Returns:
        A `validate()`-clean `FeatureSet`. Empty for a featureless window — not an error.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    _deferred("window feature extraction (pipeline step 4)")


def step5_correspond(
    ctx: MatchContext,
    q: FeatureSet,
    t: FeatureSet,
    w: CandidateWindow,
) -> Correspondences:
    """Step 5: match the query against one window.

    Args:
        ctx: The job bundle.
        q: The query features.
        t: The window ("train") features.
        w: The window itself, for its metadata.

    Returns:
        `Correspondences` — the pipeline's universal currency.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    _deferred("correspondence generation (pipeline step 5)")


def step6_estimate_homography(ctx: MatchContext, c: Correspondences) -> HomographyResult:
    """Step 6: fit the homography. **Sorts for PROSAC, estimates, then UN-PERMUTES.**

    Args:
        ctx: The job bundle.
        c: The correspondences.

    Returns:
        A `HomographyResult` whose `inlier_mask` and `residuals` are aligned to `c` — the
        object handed in, NOT the sorted copy. See the module docstring: this is the step
        that keeps the permutation from escaping, and it is the only place that can.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    _deferred("homography estimation (pipeline step 6)")


def step7_score(ctx: MatchContext, ev: ScoreEvidence) -> ScoreResult:
    """Step 7: score one candidate window.

    Args:
        ctx: The job bundle.
        ev: Everything known about this window's fit.

    Returns:
        A `ScoreResult` with `confidence` in `[0,100]` and an honest `calibrated` flag.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    _deferred("candidate scoring (pipeline step 7)")


def step8_rank(ctx: MatchContext, results: Sequence[WindowResult]) -> list[WindowResult]:
    """Step 8: rank the candidates, best first.

    Args:
        ctx: The job bundle.
        results: The scored windows.

    Returns:
        The windows sorted by confidence, best first, with sub-`min_confidence` candidates
        dropped. **Refusing to answer beats a confident wrong coordinate (L12).**

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    _deferred("candidate ranking (pipeline step 8)")


def step9_finalize(ctx: MatchContext, ranked: Sequence[WindowResult]) -> MatchJobResult:
    """Step 9: turn the best window into GCP pixel fixes.

    Args:
        ctx: The job bundle.
        ranked: The ranked windows from step 8.

    Returns:
        The `MatchJobResult`. ★ An empty `ranked` returns
        ``status="no_viable_candidate"`` — it does **not** raise. `NoViableCandidate` is
        retained only as an internal marker inside this step and never crosses the package
        boundary: "no match found" is a result, not a failure (§11.6), and returning it is
        also the internally consistent choice, since `estimate_homography` already returns a
        sub-threshold result rather than raising. Estimation reports; policy judges; a
        status is data.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    _deferred("result finalisation (pipeline step 9)")
