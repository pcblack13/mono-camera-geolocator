"""Match filters — the ratio test and its friends. **DEFERRED.**

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``). Every caller is a deferred
matcher.

These are the classical outlier suppressors that run *before* RANSAC ever sees a
correspondence, and in this product's regime — ground-level oblique against nadir raster,
roughly 80% outliers in the putative set — they matter more than usual. Repeated field
texture is the specific adversary: a ploughed field is a thousand near-identical patches,
so the second-nearest neighbour is routinely as good a match as the first, and the ratio
test is what notices.
"""

from __future__ import annotations

from typing import NoReturn

import numpy as np

from ai_engine.errors import NotImplementedDeferred
from ai_engine.types import FeatureSet, MatchSet

__all__ = ["dedupe_many_to_one", "lowe_ratio", "mutual_nn", "spatial_gate"]


def _deferred(feature: str) -> NoReturn:
    """Raise `NotImplementedDeferred` naming this module and `feature`."""
    raise NotImplementedDeferred(__name__, feature=feature)


def lowe_ratio(matches: MatchSet, *, ratio: float = 0.75) -> MatchSet:
    """Keep matches whose ``d1/d2`` is below `ratio`.

    Args:
        matches: The candidate matches; `MatchSet.ratios` must be populated.
        ratio: The Lowe threshold. The default of 0.75 is `LE_AI_RATIO_TEST`.

    Returns:
        The surviving subset, with `scores` renormalised per the score contract in
        `matchers/base.py`.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    _deferred("Lowe ratio test")


def mutual_nn(matches: MatchSet, *, n_a: int, n_b: int) -> MatchSet:
    """Keep only mutual nearest neighbours (the cross-check).

    Args:
        matches: The candidate matches.
        n_a: Number of features in the query set.
        n_b: Number of features in the train set.

    Returns:
        The subset that is each other's nearest neighbour, with `mutual` set True.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    _deferred("mutual nearest-neighbour cross-check")


def spatial_gate(
    matches: MatchSet,
    a: FeatureSet,
    b: FeatureSet,
    *,
    prior_H: np.ndarray,
    radius_px: float,
    prior_cov: np.ndarray | None = None,
) -> MatchSet:
    """Reject matches inconsistent with a prior homography.

    Args:
        matches: The candidate matches.
        a: Query features (for the keypoint positions).
        b: Train features.
        prior_H: `(3,3)` float64 mapping the a-frame to the b-frame.
        radius_px: Base search radius in the b frame.
        prior_cov: `(9,9)` covariance of `vec(prior_H)`; widens the radius per point by
            ``2.0 * sqrt(trace(J Sigma_H J^T))``.

    Returns:
        The surviving subset. ★ The caller MUST mark the resulting `Correspondences` with
        ``prior_free=False`` — a gated set's inlier ratio measures the gate, not the fit.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    _deferred("prior-homography spatial gating")


def dedupe_many_to_one(matches: MatchSet) -> MatchSet:
    """Collapse many-to-one matches, keeping the best-scoring pair per train feature.

    Several query features claiming the same train feature is the signature of repeated
    texture — a crop row matching every other crop row. Left in place, those duplicates
    inflate the inlier count of any homography that happens to align the rows, which is
    the failure mode that produces a confident answer one row off.

    Args:
        matches: The candidate matches.

    Returns:
        A subset in which each index into `b` appears at most once.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    _deferred("many-to-one match deduplication")
