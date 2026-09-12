"""The `FeatureExtractor` ABC — image in, keypoints and descriptors out.

★ THIS ABC IS REAL AND COMPLETE even though every implementation behind it is deferred
(``docs/architecture/SCOPE.md``). It is the seam, and the seam is the deliverable: callers
depend on this interface and never on a concrete class, so implementing the extractors
later is a change inside `ai_engine/extractors/` and nowhere else (SCOPE §7).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

import numpy as np

from ai_engine.models import params_hash as _params_hash
from ai_engine.types import DescriptorKind, ExtractorCapabilities, FeatureSet

__all__ = ["FeatureExtractor"]


class FeatureExtractor(ABC):
    """Detects and describes local features in one image.

    Every implementation MUST honour the storage conventions `FeatureSet` documents and
    `FeatureSet.validate()` enforces — keypoints `(N,2)` float32 in pixels, FLOAT
    descriptors L2-normalised, BINARY descriptors bit-packed to `D//8` bytes, scores
    rank-normalised into `[0,1]`. Those are not suggestions: `S_f` averages `scores`
    across extractors, and a raw detector response would make that average meaningless.

    Attributes:
        name: The registry key, e.g. ``"sift"``. Also written into
            `FeatureSet.extractor_name` and compared by `Matcher.validate_pair`.
        descriptor_kind: FLOAT or BINARY. Decides which metric is meaningful, and stops
            FLANN-KDTree from being handed packed ORB bytes — which returns
            plausible-looking garbage rather than failing.
        descriptor_dim: The **storage** width in bits. For BINARY this is
            ``descriptors.shape[1] * 8``, so AKAZE's 486 significant bits declare
            ``D = 488`` (61 bytes) with two zero pad bits. A ClassVar that cannot equal
            `FeatureSet.descriptor_dim` is an extractor that raises
            `IncompatibleDescriptors` on every call.
        version: Bumped whenever what this extractor produces changes. A cache-key input:
            stale descriptors matched against fresh ones fail as a slightly worse answer
            rather than as an error, which is the kind of bug that survives review.
    """

    name: ClassVar[str]
    descriptor_kind: ClassVar[DescriptorKind]
    descriptor_dim: ClassVar[int]
    version: ClassVar[str]

    @abstractmethod
    def extract(
        self,
        image: np.ndarray,
        mask: np.ndarray | None = None,
    ) -> FeatureSet:
        """Detect and describe features across `image`.

        Args:
            image: `(H,W,3)` uint8 RGB, or `(H,W)` uint8 grayscale.
            mask: `(H,W)` uint8; nonzero marks the allowed region. None means the whole
                image. An extractor whose `capabilities().supports_mask` is False must
                say so rather than ignore this silently.

        Returns:
            A `validate()`-clean `FeatureSet`.

        ★ MUST return an EMPTY (0-length) `FeatureSet` rather than raise when it finds
        nothing. A featureless window — an overcast field, a blank tile — is an ordinary
        outcome in this product, not an error, and the orchestrator must be able to score
        it as "no evidence" and move on.
        """

    @abstractmethod
    def extract_at(
        self,
        image: np.ndarray,
        points: np.ndarray,
        *,
        sizes: np.ndarray | None = None,
        angles: np.ndarray | None = None,
        landmark_ids: np.ndarray | None = None,
    ) -> FeatureSet:
        """★ Describe at CALLER-SUPPLIED points — the user's landmarks.

        THIS METHOD IS THE HINGE THE ENTIRE LANDMARK ALGORITHM TURNS ON. The surveyor's
        landmarks were never proposed by any detector, so this is the only way they enter
        the descriptor space at all.

        Args:
            image: `(H,W,3)` uint8 RGB or `(H,W)` uint8 gray.
            points: `(K,2)` float32 `(x,y)` — the landmarks, in this image's pixels.
            sizes: `(K,)` float32 patch diameter in px. None ⇒ the config default.
            angles: `(K,)` float32 radians. None ⇒ the extractor estimates an orientation
                (or uses 0 if it has no notion of one).
            landmark_ids: `(K,)` int32 written through to `FeatureSet.landmark_ids`, so
                landmark identity survives into RANSAC weighting and `S_l`.

        Returns:
            A `validate()`-clean `FeatureSet`.

        ★ THE CARDINALITY CONTRACT, BOTH DIRECTIONS:

        * The result MAY be SHORTER than K — points inside the patch margin are dropped,
          and `landmark_ids` tells the caller which survived.
        * The result MUST NOT be LONGER than K, and `landmark_ids` MUST contain no
          duplicates. `cv2.SIFT.compute()` returns one keypoint PER DOMINANT ORIENTATION,
          so a bi-modal gradient patch turns K=8 into N=14 with `landmark_ids` many-to-one
          — and everything downstream assumes 1:1. Nothing crashes: the per-landmark fix
          loop, PROSAC's landmark weight and `S_l`'s sum over k all quietly reweight the
          product's differentiator. Implementations MUST collapse to the highest-response
          orientation per input point, or pass explicit `angles` to suppress the search.
          Multiplicity belongs in `LandmarkPatchBank`, a structure designed for it.
        """

    def extract_batch(
        self,
        images: Sequence[np.ndarray],
        masks: Sequence[np.ndarray | None] | None = None,
    ) -> list[FeatureSet]:
        """Describe several images. Default: a serial loop over :meth:`extract`.

        Deep extractors override this with real tensor batching, which is where their
        throughput actually comes from. The default exists so that a classical extractor
        needs no batching code to satisfy the interface.

        Args:
            images: The images to process.
            masks: Per-image masks, or None for no masks at all. When given it MUST be
                the same length as `images` — a short mask list would silently
                mask-and-not-mask alternating images.

        Returns:
            One `FeatureSet` per input image, in order.

        Raises:
            ValueError: `masks` is given and its length differs from `images`.
        """
        if masks is not None and len(masks) != len(images):
            raise ValueError(
                f"masks has length {len(masks)} but there are {len(images)} images; "
                f"pass one mask per image (None is allowed per entry) or pass masks=None"
            )
        if masks is None:
            return [self.extract(image) for image in images]
        return [self.extract(image, mask) for image, mask in zip(images, masks, strict=True)]

    @abstractmethod
    def capabilities(self) -> ExtractorCapabilities:
        """What this extractor can actually do — asked, never assumed.

        ★ Abstract on purpose. There is no honest default: `supports_extract_at` is the
        one that decides whether the user's landmarks can be seen at all, and an
        extractor that inherited a guess for it would be lying about the product's
        differentiator. Answering is cheap; guessing is not.
        """

    def warmup(self) -> None:
        """Force any lazy weight load plus one dummy forward pass.

        Called by `preflight()` at boot, **never per request** — the point is to move the
        cost and the failure to a place where an operator is watching. The default is a
        no-op, which is correct for a classical extractor: there is nothing lazy to load,
        and pretending otherwise would burn a frame of CPU to prove it.
        """
        return None

    def params_hash(self) -> str:
        """A stable digest of this extractor's parameters — a cache-key input.

        The default hashes the config mapping the component was constructed with, using
        the normative `params_hash` (§4.14.1), so every extractor produces the same digest
        for the same configuration. Override only if the effective parameters differ from
        the mapping handed in, and if you do, bump `version` in the same commit.

        Returns:
            A 64-character hex digest. Empty-mapping-safe.
        """
        config: Mapping[str, Any] = getattr(self, "_config", {})
        return _params_hash(config)
