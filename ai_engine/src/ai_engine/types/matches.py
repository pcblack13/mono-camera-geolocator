"""Matches and correspondences — the pipeline's universal currency.

`MatchSet` is the detector-based world's output: pairs of *indices*. `Correspondences`
is what the rest of the pipeline actually consumes: pairs of *points*. Every source
produces the latter — detector-based, detector-free, or landmark patch search — which is
why neither `Matcher` nor `DetectorFreeMatcher` ever appears in a pipeline signature.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np

from ai_engine.types.features import FeatureSet
from ai_engine.types.landmarks import LandmarkWeightField

__all__ = ["Correspondences", "CorrespondenceRequest", "MatchSet"]


@dataclass(frozen=True, slots=True)
class MatchSet:
    """Descriptor matches between two FeatureSets, as index pairs.

    ★ `scores` must be comparable ACROSS matchers, because ``S_f`` averages them:

    * Ratio-test matchers (FLANN/BF):
      ``score = clip((r_thr - r) / (r_thr - r_min), 0, 1)`` with r_thr=0.8, r_min=0.3.
    * Learned matchers (SuperGlue/LightGlue/LoFTR): the network's own match confidence,
      already in [0,1].
    """

    indices: np.ndarray  # (M,2) int32. col 0 -> index into a, col 1 -> index into b
    scores: np.ndarray  # (M,) float32 in [0,1], HIGHER = BETTER, matcher-normalised
    matcher_name: str
    distances: np.ndarray | None = None  # (M,) float32 raw descriptor distance (L2 or Hamming)
    ratios: np.ndarray | None = None  # (M,) float32 Lowe ratio d1/d2; NaN where inapplicable
    mutual: np.ndarray | None = None  # (M,) bool — passed cross-check
    meta: Mapping[str, Any] = field(default_factory=dict)

    @property
    def num_matches(self) -> int:
        """M — the number of index pairs held."""
        return int(self.indices.shape[0])

    def validate(self, n_a: int, n_b: int) -> None:
        """Raise ValueError on out-of-range indices, duplicate (i,j) pairs, or scores
        outside [0,1].

        A duplicate pair is not cosmetic: it double-counts one piece of evidence in the
        inlier ratio and hands RANSAC the same constraint twice.
        """
        m = self.num_matches

        if self.indices.ndim != 2 or self.indices.shape[1] != 2:
            raise ValueError(f"indices must be (M,2); got shape {self.indices.shape}")
        if self.indices.dtype != np.int32:
            raise ValueError(f"indices must be int32; got {self.indices.dtype}")
        if self.scores.ndim != 1 or self.scores.shape[0] != m:
            raise ValueError(f"scores must be (M,) with M={m}; got shape {self.scores.shape}")
        if self.scores.dtype != np.float32:
            raise ValueError(f"scores must be float32; got {self.scores.dtype}")

        if m:
            ia = self.indices[:, 0]
            ib = self.indices[:, 1]
            if int(ia.min()) < 0 or int(ia.max()) >= n_a:
                raise ValueError(
                    f"indices into a must lie in [0,{n_a}); got "
                    f"[{int(ia.min())},{int(ia.max())}]"
                )
            if int(ib.min()) < 0 or int(ib.max()) >= n_b:
                raise ValueError(
                    f"indices into b must lie in [0,{n_b}); got "
                    f"[{int(ib.min())},{int(ib.max())}]"
                )
            if np.unique(self.indices, axis=0).shape[0] != m:
                raise ValueError("indices contain duplicate (i,j) pairs")
            if not np.isfinite(self.scores).all():
                raise ValueError("scores contain non-finite values")
            if float(self.scores.min()) < 0.0 or float(self.scores.max()) > 1.0:
                raise ValueError(
                    f"scores must lie in [0,1]; got "
                    f"[{float(self.scores.min()):.4f}, {float(self.scores.max()):.4f}]"
                )

        for name, arr in (("distances", self.distances), ("ratios", self.ratios)):
            if arr is None:
                continue
            if arr.ndim != 1 or arr.shape[0] != m:
                raise ValueError(f"{name} must be (M,) with M={m}; got shape {arr.shape}")
            if arr.dtype != np.float32:
                raise ValueError(f"{name} must be float32; got {arr.dtype}")
        if self.mutual is not None:
            if self.mutual.ndim != 1 or self.mutual.shape[0] != m:
                raise ValueError(f"mutual must be (M,) with M={m}; got shape {self.mutual.shape}")
            if self.mutual.dtype != np.bool_:
                raise ValueError(f"mutual must be bool; got {self.mutual.dtype}")

    def select(self, idx: np.ndarray) -> MatchSet:
        """Return the subset named by `idx` (an index or boolean array)."""
        idx = np.asarray(idx)
        return replace(
            self,
            indices=self.indices[idx],
            scores=self.scores[idx],
            distances=None if self.distances is None else self.distances[idx],
            ratios=None if self.ratios is None else self.ratios[idx],
            mutual=None if self.mutual is None else self.mutual[idx],
        )

    def to_correspondences(self, a: FeatureSet, b: FeatureSet) -> Correspondences:
        """Materialise indices into points.

        The ONLY bridge from the detector-based world into the pipeline's universal
        currency. Landmark identity is carried across: `a.landmark_ids` follows the
        query-side index, which is how a user's landmark stays identifiable through
        matching, RANSAC weighting and the per-landmark fix loop.
        """
        self.validate(a.num_features, b.num_features)
        ia = self.indices[:, 0]
        ib = self.indices[:, 1]
        return Correspondences(
            pts_a=a.keypoints[ia].astype(np.float32, copy=True),
            pts_b=b.keypoints[ib].astype(np.float32, copy=True),
            scores=self.scores.astype(np.float32, copy=True),
            image_size_a=a.image_size,
            image_size_b=b.image_size,
            source_name=self.matcher_name,
            is_dense=False,
            landmark_ids=None if a.landmark_ids is None else a.landmark_ids[ia].astype(np.int32),
            feature_sets=(a, b),
            match_set=self,
        )


@dataclass(frozen=True, slots=True)
class Correspondences:
    """★ THE PIPELINE'S UNIVERSAL CURRENCY.

    Every source produces this; every consumer reads this.
    """

    pts_a: np.ndarray  # (M,2) float32 — QUERY IMAGE pixels
    pts_b: np.ndarray  # (M,2) float32 — WINDOW pixels
    scores: np.ndarray  # (M,) float32 in [0,1]
    image_size_a: tuple[int, int]
    image_size_b: tuple[int, int]
    source_name: str
    is_dense: bool  # True => produced detector-free; no stable feature indices exist
    weights: np.ndarray | None = None
    # ★ (M,) float32 > 0. Landmark-derived PRIORITY, not confidence. PROSAC sort key.
    landmark_ids: np.ndarray | None = None  # (M,) int32; >=0 => from user landmark k, -1 otherwise
    prior_free: bool = True
    # ★ False => these correspondences were produced with a prior_H gate (the guided pass,
    #   or pass 1 seeded from landmark fixes). LOAD-BEARING FOR HONESTY: a gated set's
    #   inlier ratio and RMS are bounded by the gate itself, so S_f/S_g computed on it
    #   measure GATE EFFICACY, not correctness. Without this flag the scorer cannot tell
    #   the two apart.
    feature_sets: tuple[FeatureSet, FeatureSet] | None = None  # None when is_dense
    match_set: MatchSet | None = None  # None when is_dense
    meta: Mapping[str, Any] = field(default_factory=dict)

    @property
    def num_correspondences(self) -> int:
        """M — the number of point pairs held."""
        return int(self.pts_a.shape[0])

    def validate(self) -> None:
        """Raise ValueError on shape/dtype disagreement or scores outside [0,1]."""
        m = self.num_correspondences
        for name, arr in (("pts_a", self.pts_a), ("pts_b", self.pts_b)):
            if arr.ndim != 2 or arr.shape[1] != 2:
                raise ValueError(f"{name} must be (M,2); got shape {arr.shape}")
            if arr.dtype != np.float32:
                raise ValueError(f"{name} must be float32; got {arr.dtype}")
        if self.pts_b.shape[0] != m:
            raise ValueError(f"pts_a has {m} rows but pts_b has {self.pts_b.shape[0]}")
        if self.scores.shape != (m,):
            raise ValueError(f"scores must be (M,) with M={m}; got shape {self.scores.shape}")
        if m and (float(self.scores.min()) < 0.0 or float(self.scores.max()) > 1.0):
            raise ValueError("scores must lie in [0,1]")
        if self.weights is not None:
            if self.weights.shape != (m,):
                raise ValueError(f"weights must be (M,) with M={m}; got shape {self.weights.shape}")
            if m and float(self.weights.min()) <= 0.0:
                raise ValueError("weights must be strictly positive — they are a PROSAC sort key")
        if self.landmark_ids is not None and self.landmark_ids.shape != (m,):
            raise ValueError(
                f"landmark_ids must be (M,) with M={m}; got shape {self.landmark_ids.shape}"
            )
        if self.is_dense and (self.feature_sets is not None or self.match_set is not None):
            raise ValueError("is_dense correspondences have no feature_sets and no match_set")

    def _sort_key(self) -> np.ndarray:
        """The PROSAC ordering key: `weights` when present, else `scores`."""
        return self.scores if self.weights is None else self.weights

    def select(self, idx: np.ndarray) -> Correspondences:
        """Return the subset named by `idx` (an index or boolean array).

        `feature_sets` and `match_set` are dropped: after an arbitrary selection the
        match_set's indices no longer align to the retained rows, and a stale index array
        is worse than an absent one.
        """
        idx = np.asarray(idx)
        return replace(
            self,
            pts_a=self.pts_a[idx],
            pts_b=self.pts_b[idx],
            scores=self.scores[idx],
            weights=None if self.weights is None else self.weights[idx],
            landmark_ids=None if self.landmark_ids is None else self.landmark_ids[idx],
            match_set=None if self.match_set is None else self.match_set.select(idx),
        )

    def sorted_by_weight(self) -> tuple[Correspondences, np.ndarray]:
        """Return (sorted copy, permutation), descending by weights-or-scores.

        ``sorted.pts_a[i] == self.pts_a[perm[i]]``, so a caller un-permutes with::

            inv = np.empty_like(perm); inv[perm] = np.arange(len(perm))

        PROSAC REQUIRES this ordering: handing unsorted data to `SAMPLING_PROSAC`
        silently degrades it to uniform sampling — no error, just a quietly worse
        estimate. The sort is stable, so equal keys keep their input order and the whole
        pipeline stays deterministic under a fixed seed.
        """
        key = self._sort_key()
        perm = np.argsort(-key, kind="stable").astype(np.int64)
        return self.select(perm), perm

    @staticmethod
    def merge(items: Sequence[Correspondences], *, dedupe_px: float = 2.0) -> Correspondences:
        """Union of several sources.

        Two correspondences are duplicates iff BOTH endpoints are within `dedupe_px`;
        the higher-weight one survives. Requiring both endpoints is deliberate: two
        different matches that happen to share a query point are genuinely different
        hypotheses, and collapsing them would silently discard the ambiguity that
        `dedupe_many_to_one` exists to measure.
        """
        if not items:
            raise ValueError("merge() needs at least one Correspondences to know the image sizes")
        first = items[0]
        for other in items[1:]:
            if other.image_size_a != first.image_size_a or other.image_size_b != first.image_size_b:
                raise ValueError(
                    "cannot merge correspondences from different image frames: "
                    f"{first.image_size_a}/{first.image_size_b} vs "
                    f"{other.image_size_a}/{other.image_size_b}"
                )
        if dedupe_px < 0:
            raise ValueError(f"dedupe_px must be non-negative; got {dedupe_px}")

        pts_a = np.concatenate([c.pts_a for c in items], axis=0)
        pts_b = np.concatenate([c.pts_b for c in items], axis=0)
        scores = np.concatenate([c.scores for c in items], axis=0)

        # `weights` survives the union only if every part can supply one; a part without
        # weights contributes its scores, which is the same quantity sorted_by_weight()
        # would have used for it anyway.
        any_weights = any(c.weights is not None for c in items)
        weights: np.ndarray | None = None
        if any_weights:
            weights = np.concatenate(
                [(c.scores if c.weights is None else c.weights) for c in items], axis=0
            ).astype(np.float32)

        landmark_ids: np.ndarray | None = None
        if any(c.landmark_ids is not None for c in items):
            landmark_ids = np.concatenate(
                [
                    (
                        np.full(c.num_correspondences, -1, dtype=np.int32)
                        if c.landmark_ids is None
                        else c.landmark_ids
                    )
                    for c in items
                ],
                axis=0,
            )

        key = scores if weights is None else weights
        order = np.argsort(-key, kind="stable")

        keep: list[int] = []
        for idx in order:
            if keep:
                kept_a = pts_a[keep]
                kept_b = pts_b[keep]
                close_a = np.linalg.norm(kept_a - pts_a[idx], axis=1) <= dedupe_px
                close_b = np.linalg.norm(kept_b - pts_b[idx], axis=1) <= dedupe_px
                if np.any(close_a & close_b):
                    continue
            keep.append(int(idx))
        survivors = np.asarray(sorted(keep), dtype=np.int64)

        return Correspondences(
            pts_a=pts_a[survivors],
            pts_b=pts_b[survivors],
            scores=scores[survivors],
            image_size_a=first.image_size_a,
            image_size_b=first.image_size_b,
            source_name="merge(" + "+".join(sorted({c.source_name for c in items})) + ")",
            is_dense=any(c.is_dense for c in items),
            weights=None if weights is None else weights[survivors],
            landmark_ids=None if landmark_ids is None else landmark_ids[survivors],
            # ★ A merged set is prior-free only if EVERY part was. One gated part bounds
            #   the union's inlier ratio, so claiming otherwise would let a gated set be
            #   scored as if it were independent evidence.
            prior_free=all(c.prior_free for c in items),
            feature_sets=None,
            match_set=None,
        )


@dataclass(frozen=True, slots=True)
class CorrespondenceRequest:
    """One ask of a CorrespondenceSource: two images, optional precomputed features,
    optional masks, and an optional prior.

    `prior_H` is what switches on the guided path. Anything produced under it MUST come
    back with ``Correspondences.prior_free = False``.
    """

    image_a: np.ndarray
    image_b: np.ndarray
    features_a: FeatureSet | None = None  # precomputed/cached; ignored by detector-free
    features_b: FeatureSet | None = None
    mask_a: np.ndarray | None = None
    mask_b: np.ndarray | None = None
    prior_H: np.ndarray | None = None  # triggers the guided path when not None
    prior_cov: np.ndarray | None = None
    guided_radius_px: float = 32.0
    landmark_weights: LandmarkWeightField | None = None
