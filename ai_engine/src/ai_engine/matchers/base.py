"""The `Matcher` and `DetectorFreeMatcher` ABCs.

Two ABCs rather than one, because detection and matching are inseparable in LoFTR and its
successors and the interface should admit that instead of pretending otherwise. A
detector-free model has no stable feature indices to return, so forcing it through
`Matcher.match(a: FeatureSet, b: FeatureSet)` would mean inventing them — which is what
`LoFTRAsMatcher` does, why it is documented as LOSSY, and why the pipeline never uses it.

★ BOTH ABCs ARE REAL AND COMPLETE even though every implementation is deferred
(``docs/architecture/SCOPE.md``).

**Score normalisation is part of this contract, not a detail.** `MatchSet.scores` must be
comparable ACROSS matchers, because `S_f` averages them:

* ratio-test matchers (FLANN, BF): ``score = clip((r_thr - r) / (r_thr - r_min), 0, 1)``
  with ``r_thr = 0.8``, ``r_min = 0.3``;
* learned matchers (SuperGlue, LightGlue, LoFTR): the network's own match confidence,
  which is already in `[0,1]`.

A matcher that emitted a raw distance here would not fail — it would quietly skew every
composite score that ever averaged it against another matcher's.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

import numpy as np

from ai_engine.errors import IncompatibleDescriptors, NotImplementedDeferred
from ai_engine.logging import get_logger
from ai_engine.models import params_hash as _params_hash
from ai_engine.types import Correspondences, DescriptorKind, FeatureSet, MatchSet

__all__ = ["DetectorFreeMatcher", "Matcher"]

_log = get_logger(__name__)


class Matcher(ABC):
    """Matches two descriptor sets into a `MatchSet`.

    Attributes:
        name: The registry key, e.g. ``"flann"``.
        supported_kinds: The `DescriptorKind`s this matcher can handle. Checked by
            :meth:`validate_pair` before anything else — this is the single guard against
            the bug class `DescriptorKind` exists for.
        requires_images: True ONLY for detector-free shims. `DetectBasedSource` asserts
            this is False, so a lossy shim can never be silently wired into the normal
            path.
        version: Cache-key input. Bump when the matcher's output changes.
    """

    name: ClassVar[str]
    supported_kinds: ClassVar[frozenset[DescriptorKind]]
    requires_images: ClassVar[bool] = False
    version: ClassVar[str]

    @abstractmethod
    def match(self, a: FeatureSet, b: FeatureSet) -> MatchSet:
        """Match `a`'s descriptors against `b`'s, with this matcher's own filtering.

        Filtering means the ratio test, cross-check, or a learned assignment — whatever
        this matcher considers part of producing a match rather than a downstream policy.

        Args:
            a: Query features.
            b: Train features.

        Returns:
            A `MatchSet` whose `scores` obey the normalisation contract above.

        ★ MUST call `self.validate_pair(a, b)` first, and MUST return an EMPTY `MatchSet`
        rather than raise when nothing matches. "No matches" is an ordinary outcome; an
        incompatible descriptor pair is not.
        """

    def match_guided(
        self,
        a: FeatureSet,
        b: FeatureSet,
        *,
        prior_H: np.ndarray,
        radius_px: float,
        prior_cov: np.ndarray | None = None,
    ) -> MatchSet:
        """Spatially-constrained matching under a prior homography.

        The default implementation runs a full :meth:`match` and then rejects any pair
        whose ``||p_b - prior_H(p_a)||`` exceeds the effective radius. Efficient
        implementations override this to build the candidate list per point BEFORE
        comparing descriptors (a KD-tree over `b`'s keypoints) — and that is where the
        real accuracy comes from, not the speed: the ratio test is then computed against
        only the **spatially plausible** competitors, so the second-nearest neighbour
        stops being a random repeat of the field texture two hundred metres away.

        Args:
            a: Query features.
            b: Train features.
            prior_H: `(3,3)` float64 mapping the a-frame to the b-frame.
            radius_px: Search disk radius in the b frame.
            prior_cov: `(9,9)` covariance of `vec(prior_H)`. When given, the radius widens
                per point: ``radius_eff(p_a) = radius_px + k*sqrt(trace(J Sigma_H J^T))``
                with ``k = 2.0``.

        Returns:
            A `MatchSet` restricted to the prior-consistent pairs.

        ★ Correspondences produced this way MUST carry `prior_free=False`. A gated set's
        inlier ratio and RMS are bounded by the gate itself, so `S_f`/`S_g` computed on it
        measure gate efficacy rather than correctness (§4.12).

        Raises:
            NotImplementedDeferred: Always, in this build. ★ `NotImplementedDeferred`
                rather than `NotImplementedError`, and the distinction matters: the
                contract specifies a real default here, so "a subclass must supply this"
                would be false. What is true is that this default is part of the deferred
                matching surface. The API layer catches exactly this class to answer 501.
        """
        raise NotImplementedDeferred(
            __name__, feature="prior-constrained (guided) descriptor matching"
        )

    def supports(self, a: FeatureSet, b: FeatureSet) -> bool:
        """True when this matcher can handle the pair, without raising.

        The non-raising sibling of :meth:`validate_pair`, for callers choosing between
        matchers rather than committing to one.
        """
        try:
            self.validate_pair(a, b)
        except IncompatibleDescriptors:
            return False
        return True

    def validate_pair(self, a: FeatureSet, b: FeatureSet) -> None:
        """Raise `IncompatibleDescriptors` unless this matcher can match `a` against `b`.

        ★ THIS IS REAL, AND IT IS REAL ON PURPOSE. It is the one guard that stands between
        this engine and the failure `DescriptorKind` was invented to prevent: FLANN's
        KD-tree index, handed bit-packed ORB bytes, does not fail — it returns
        plausible-looking garbage, which becomes plausible-looking correspondences, a
        plausible-looking homography, and a confidently wrong coordinate handed to a
        surveyor (L12). It is checked here, in the base class, so that no matcher can
        forget it.

        Checks:

        * `a.descriptor_kind != b.descriptor_kind` → raise;
        * `a.descriptor_kind not in self.supported_kinds` → raise;
        * `a.descriptor_dim != b.descriptor_dim` → raise;
        * `a.extractor_name != b.extractor_name` → **WARN only**. Crossing ASIFT with SIFT
          is legitimate: same descriptor space, different detector.

        Args:
            a: Query features.
            b: Train features.

        Raises:
            IncompatibleDescriptors: The pair cannot be matched meaningfully.
        """
        if a.descriptor_kind is not b.descriptor_kind:
            raise IncompatibleDescriptors(
                f"{self.name}: cannot match {a.descriptor_kind} descriptors against "
                f"{b.descriptor_kind} ones — the metrics are not comparable."
            )
        if a.descriptor_kind not in self.supported_kinds:
            raise IncompatibleDescriptors(
                f"{self.name}: does not support {a.descriptor_kind} descriptors "
                f"(supports {sorted(self.supported_kinds)}). This check exists because "
                f"the alternative is silent garbage, not an error."
            )
        if a.descriptor_dim != b.descriptor_dim:
            raise IncompatibleDescriptors(
                f"{self.name}: descriptor dimensions differ — {a.descriptor_dim} "
                f"({a.extractor_name}) versus {b.descriptor_dim} ({b.extractor_name})."
            )
        if a.extractor_name != b.extractor_name:
            _log.warning(
                "%s: matching features from different extractors (%r vs %r). This is "
                "legitimate when the descriptor space is shared (asift/sift), and wrong "
                "otherwise.",
                self.name,
                a.extractor_name,
                b.extractor_name,
            )

    def params_hash(self) -> str:
        """A stable digest of this matcher's parameters — a cache-key input (§4.14.1)."""
        config: Mapping[str, Any] = getattr(self, "_config", {})
        return _params_hash(config)


class DetectorFreeMatcher(ABC):
    """For LoFTR and its successors: detection and matching are one operation.

    Emits `Correspondences` directly rather than a `MatchSet`, because there are no stable
    feature indices for a `MatchSet` to index into. That is not a limitation of the model;
    it is what detector-free means.

    Attributes:
        name: The registry key, e.g. ``"loftr"``.
        version: Cache-key input.
    """

    name: ClassVar[str]
    version: ClassVar[str]

    @abstractmethod
    def match_images(
        self,
        image_a: np.ndarray,
        image_b: np.ndarray,
        mask_a: np.ndarray | None = None,
        mask_b: np.ndarray | None = None,
    ) -> Correspondences:
        """Match two images directly.

        Args:
            image_a: `(H,W,3)` uint8 RGB — the query image.
            image_b: `(H,W,3)` uint8 RGB — the window.
            mask_a: `(H,W)` uint8; nonzero marks the allowed region in `image_a`.
            mask_b: The same for `image_b`.

        Returns:
            `Correspondences` with ``is_dense=True``, ``feature_sets=None`` and
            ``match_set=None`` — the three fields that record that no detector ran.
        """

    def match_images_guided(
        self,
        image_a: np.ndarray,
        image_b: np.ndarray,
        *,
        prior_H: np.ndarray,
        radius_px: float,
        mask_a: np.ndarray | None = None,
        mask_b: np.ndarray | None = None,
    ) -> Correspondences:
        """Match under a prior homography.

        Real implementations mask the coarse-level attention to the prior-consistent band,
        which is both faster and more accurate than gating afterwards.

        Args:
            image_a: `(H,W,3)` uint8 RGB — the query image.
            image_b: `(H,W,3)` uint8 RGB — the window.
            prior_H: `(3,3)` float64 mapping the a-frame to the b-frame.
            radius_px: Search band half-width in the b frame.
            mask_a: Optional region mask for `image_a`.
            mask_b: Optional region mask for `image_b`.

        Returns:
            `Correspondences` with ``prior_free=False``.

        Raises:
            NotImplementedDeferred: Always, in this build.
        """
        raise NotImplementedDeferred(
            __name__, feature="prior-constrained (guided) detector-free matching"
        )

    def match_images_batch(
        self,
        pairs: Sequence[tuple[np.ndarray, np.ndarray]],
    ) -> list[Correspondences]:
        """Match several image pairs. Default: a serial loop over :meth:`match_images`.

        Args:
            pairs: `(image_a, image_b)` tuples.

        Returns:
            One `Correspondences` per pair, in order.
        """
        return [self.match_images(a, b) for a, b in pairs]
