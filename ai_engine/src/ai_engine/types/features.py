"""Keypoints and descriptors — what an extractor produces.

`FeatureSet` is the first place a numeric convention can silently go wrong, so
`validate()` is strict and is called at every producer boundary. The alternative is a
plausible-looking wrong answer, which is the failure mode this whole engine is built to
avoid (L12).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np

from ai_engine.errors import IncompatibleDescriptors
from ai_engine.types.cache import ImageStore
from ai_engine.types.enums import DescriptorKind, Device

__all__ = ["ExtractorCapabilities", "FeatureSet", "ImageRef"]

#: Tolerance for the FLOAT unit-norm invariant. Normative (§13.1 IU-01).
_UNIT_NORM_ATOL = 1e-3

#: Keypoints are (x, y) with the origin at the top-left CORNER and integer coordinates
#: at pixel CENTRES. The image therefore physically spans [-0.5, W-0.5] x [-0.5, H-0.5],
#: and a subpixel keypoint refined slightly past a centre at the border is still inside
#: the image. Bounds checking uses the true extent, not [0, W-1].
_EDGE_MARGIN = 0.5


@dataclass(frozen=True, slots=True)
class ImageRef:
    """Content-addressed handle. Lets a FeatureSet point back at its image without
    pinning the array in memory.

    `sha256` is the digest of the decoded pixel buffer, not of the encoded file: two
    uploads of the same scene as JPEG and PNG are the same image to the engine.
    """

    sha256: str
    width: int
    height: int

    def resolve(self, store: ImageStore) -> np.ndarray | None:
        """Fetch the pixels this ref names, or None if `store` does not hold them.

        ★ The `store` Protocol is `ai_engine.types.cache.ImageStore` — a REAL import,
        not a forward reference. Declaring the Protocol in `types/` and implementing it
        in `runtime/` is the same pattern `WindowSource` uses, and it is what keeps this
        annotation resolvable under `mypy --strict` and `typing.get_type_hints()`.

        Returns None rather than raising: a miss is an ordinary outcome, and the caller
        (a detector-free shim needing live pixels) has a typed error of its own
        (`DetectorFreeRequiresImages`) for the case where the miss actually matters.
        """
        return store.get(self.sha256)


@dataclass(frozen=True, slots=True)
class FeatureSet:
    """Detected (or described-at) features for exactly one image.

    Storage conventions, normative:

    * ``keypoints``  — (N,2) float32 (x,y) in PIXELS, subpixel expected.
    * ``descriptors`` — FLOAT: (N,D) float32, each row L2-normalised (``||d|| == 1``).
                        BINARY: (N,D//8) uint8, bit-packed, LSB-first per byte.
    * ``scores``     — (N,) float32 in [0,1], RANK-normalised: ``score_i = 1 - rank_i/N``.
                       NEVER a raw detector response — raw scales are not comparable
                       across extractors, and ``S_f`` averages these.
    """

    # --- required ---
    keypoints: np.ndarray
    descriptors: np.ndarray
    scores: np.ndarray
    image_size: tuple[int, int]  # (width, height) of the image the keypoints live in
    extractor_name: str  # matches FeatureExtractor.name; used for compat checks
    descriptor_kind: DescriptorKind

    # --- optional geometry ---
    sizes: np.ndarray | None = None  # (N,) float32 keypoint diameter, px
    angles: np.ndarray | None = None  # (N,) float32 radians CCW from +x. NaN = undefined
    affine: np.ndarray | None = None  # (N,2,2) float32 local affine frame (ASIFT/AffNet)

    # --- provenance / caching ---
    image_ref: ImageRef | None = None  # REQUIRED by detector-free shims
    extractor_version: str = "1"  # bump => cache invalidation
    params_hash: str = ""  # sha256 of the extractor's param dict
    landmark_ids: np.ndarray | None = None
    # (N,) int32. >=0 => this keypoint IS user landmark k (from extract_at). -1 => detected.
    # This is how landmark identity survives all the way into RANSAC weighting.
    meta: Mapping[str, Any] = field(default_factory=dict)

    @property
    def num_features(self) -> int:
        """N — the number of keypoints held."""
        return int(self.keypoints.shape[0])

    @property
    def descriptor_dim(self) -> int:
        """Logical dim D. For BINARY returns ``descriptors.shape[1] * 8``.

        ★ This is the STORAGE width, and it is what `Matcher.validate_pair` compares.
          AKAZE's MLDB carries 486 significant bits, which cv2 returns as 61 bytes, so
          its declared D is **488** — the final 2 bits are zero pad. Hamming distance is
          unaffected (pad bits are zero in both operands). A `ClassVar` that cannot
          equal this property is an extractor that raises `IncompatibleDescriptors` at
          composition time, on every call.
        """
        if self.descriptors.ndim != 2:
            raise ValueError(
                f"descriptors must be 2-D to have a dimension; got shape {self.descriptors.shape}"
            )
        width = int(self.descriptors.shape[1])
        return width * 8 if self.descriptor_kind is DescriptorKind.BINARY else width

    def validate(self) -> None:
        """Raise ValueError unless every storage invariant holds.

        Checks: shape agreement across N, non-finite keypoints, keypoints outside
        `image_size`, FLOAT rows not unit-norm (atol 1e-3), scores outside [0,1], dtype
        mismatch, ``descriptor_dim % 8 != 0`` for BINARY, and duplicate values among
        ``landmark_ids[landmark_ids >= 0]``.

        ★ The landmark_ids uniqueness rule is load-bearing, not hygiene.
          ``cv2.SIFT.compute()`` can return MORE keypoints than it was given: a patch
          with two dominant gradient orientations emits one keypoint PER ORIENTATION —
          same (x,y), different angle. So a K=8 landmark set can come back as N=14 with
          landmark_ids many-to-one, and EVERYTHING downstream assumes 1:1: the
          per-landmark fix loop, the PROSAC landmark weight (a duplicated landmark
          silently gets 2-3x the sampling priority it was assigned), and S_l's sum over
          k. None of it crashes; it quietly reweights the product's differentiator.
          A loud ValueError at the boundary is the whole point of having a validate().
        """
        n = self.num_features

        # --- image_size ---
        if len(self.image_size) != 2:
            raise ValueError(f"image_size must be (width, height); got {self.image_size!r}")
        width, height = self.image_size
        if width <= 0 or height <= 0:
            raise ValueError(f"image_size must be positive; got {self.image_size!r}")

        # --- keypoints ---
        if self.keypoints.ndim != 2 or self.keypoints.shape[1] != 2:
            raise ValueError(f"keypoints must be (N,2); got shape {self.keypoints.shape}")
        if self.keypoints.dtype != np.float32:
            raise ValueError(f"keypoints must be float32; got {self.keypoints.dtype}")
        if n and not np.isfinite(self.keypoints).all():
            raise ValueError("keypoints contain non-finite values")
        if n:
            x = self.keypoints[:, 0]
            y = self.keypoints[:, 1]
            outside = (
                (x < -_EDGE_MARGIN)
                | (x > width - 1 + _EDGE_MARGIN)
                | (y < -_EDGE_MARGIN)
                | (y > height - 1 + _EDGE_MARGIN)
            )
            if outside.any():
                bad = int(np.argmax(outside))
                raise ValueError(
                    f"{int(outside.sum())} keypoint(s) lie outside image_size {self.image_size}; "
                    f"first at index {bad} = {tuple(self.keypoints[bad].tolist())}"
                )

        # --- descriptors ---
        if self.descriptors.ndim != 2:
            raise ValueError(f"descriptors must be (N,D); got shape {self.descriptors.shape}")
        if self.descriptors.shape[0] != n:
            raise ValueError(
                f"descriptors has {self.descriptors.shape[0]} rows but there are {n} keypoints"
            )
        if self.descriptor_kind is DescriptorKind.BINARY:
            if self.descriptors.dtype != np.uint8:
                raise ValueError(
                    f"BINARY descriptors must be bit-packed uint8; got {self.descriptors.dtype}"
                )
            if self.descriptor_dim % 8 != 0:
                raise ValueError(
                    f"BINARY descriptor_dim must be a whole number of bytes; "
                    f"got {self.descriptor_dim} ({self.descriptors.shape[1]} bytes)"
                )
        else:
            if self.descriptors.dtype != np.float32:
                raise ValueError(f"FLOAT descriptors must be float32; got {self.descriptors.dtype}")
            if n:
                if not np.isfinite(self.descriptors).all():
                    raise ValueError("descriptors contain non-finite values")
                norms = np.linalg.norm(self.descriptors, axis=1)
                if not np.allclose(norms, 1.0, atol=_UNIT_NORM_ATOL):
                    worst = int(np.argmax(np.abs(norms - 1.0)))
                    raise ValueError(
                        f"FLOAT descriptor rows must be L2-normalised to within "
                        f"{_UNIT_NORM_ATOL}; row {worst} has norm {norms[worst]:.6f}"
                    )

        # --- scores ---
        if self.scores.ndim != 1 or self.scores.shape[0] != n:
            raise ValueError(f"scores must be (N,) with N={n}; got shape {self.scores.shape}")
        if self.scores.dtype != np.float32:
            raise ValueError(f"scores must be float32; got {self.scores.dtype}")
        if n:
            if not np.isfinite(self.scores).all():
                raise ValueError("scores contain non-finite values")
            if float(self.scores.min()) < 0.0 or float(self.scores.max()) > 1.0:
                raise ValueError(
                    f"scores must lie in [0,1]; got "
                    f"[{float(self.scores.min()):.4f}, {float(self.scores.max()):.4f}]"
                )

        # --- optional geometry ---
        self._validate_optional_1d("sizes", self.sizes, n)
        self._validate_optional_1d("angles", self.angles, n, allow_nan=True)
        if self.affine is not None:
            if self.affine.shape != (n, 2, 2):
                raise ValueError(f"affine must be (N,2,2) with N={n}; got shape {self.affine.shape}")
            if self.affine.dtype != np.float32:
                raise ValueError(f"affine must be float32; got {self.affine.dtype}")

        # --- landmark_ids ---
        if self.landmark_ids is not None:
            if self.landmark_ids.ndim != 1 or self.landmark_ids.shape[0] != n:
                raise ValueError(
                    f"landmark_ids must be (N,) with N={n}; got shape {self.landmark_ids.shape}"
                )
            if self.landmark_ids.dtype != np.int32:
                raise ValueError(f"landmark_ids must be int32; got {self.landmark_ids.dtype}")
            assigned = self.landmark_ids[self.landmark_ids >= 0]
            if assigned.size:
                uniq, counts = np.unique(assigned, return_counts=True)
                if uniq.size != assigned.size:
                    dupes = uniq[counts > 1].tolist()
                    raise ValueError(
                        f"landmark_ids must be 1:1 with the landmarks they describe; "
                        f"id(s) {dupes} appear more than once. An extractor whose backend "
                        f"emits multiple orientations per point MUST collapse to the "
                        f"highest-response orientation or pass explicit angles."
                    )

    @staticmethod
    def _validate_optional_1d(
        name: str, arr: np.ndarray | None, n: int, *, allow_nan: bool = False
    ) -> None:
        """Shared shape/dtype check for the optional (N,) float32 fields."""
        if arr is None:
            return
        if arr.ndim != 1 or arr.shape[0] != n:
            raise ValueError(f"{name} must be (N,) with N={n}; got shape {arr.shape}")
        if arr.dtype != np.float32:
            raise ValueError(f"{name} must be float32; got {arr.dtype}")
        if not allow_nan and n and not np.isfinite(arr).all():
            raise ValueError(f"{name} contains non-finite values")

    def select(self, idx: np.ndarray) -> FeatureSet:
        """Return the subset named by `idx` (an index or boolean array).

        Every parallel array is carried through, so the result is validate()-clean
        whenever `self` was.
        """
        idx = np.asarray(idx)
        return replace(
            self,
            keypoints=self.keypoints[idx],
            descriptors=self.descriptors[idx],
            scores=self.scores[idx],
            sizes=None if self.sizes is None else self.sizes[idx],
            angles=None if self.angles is None else self.angles[idx],
            affine=None if self.affine is None else self.affine[idx],
            landmark_ids=None if self.landmark_ids is None else self.landmark_ids[idx],
        )

    def concat(self, other: FeatureSet) -> FeatureSet:
        """Append `other`'s features to this set.

        Raises IncompatibleDescriptors if kind/dim/extractor_name differ — concatenating
        two descriptor spaces produces a block of numbers that matches against nothing
        and fails silently.

        An optional field is carried only when BOTH sides have it: a half-populated
        `angles` array is worse than none, because its absence is checkable and its
        zeros are not.
        """
        if self.descriptor_kind is not other.descriptor_kind:
            raise IncompatibleDescriptors(
                f"cannot concat {self.descriptor_kind} with {other.descriptor_kind}"
            )
        if self.descriptor_dim != other.descriptor_dim:
            raise IncompatibleDescriptors(
                f"cannot concat descriptors of dim {self.descriptor_dim} and {other.descriptor_dim}"
            )
        if self.extractor_name != other.extractor_name:
            raise IncompatibleDescriptors(
                f"cannot concat features from {self.extractor_name!r} and {other.extractor_name!r}"
            )

        def _both(a: np.ndarray | None, b: np.ndarray | None) -> np.ndarray | None:
            return None if a is None or b is None else np.concatenate([a, b], axis=0)

        return replace(
            self,
            keypoints=np.concatenate([self.keypoints, other.keypoints], axis=0),
            descriptors=np.concatenate([self.descriptors, other.descriptors], axis=0),
            scores=np.concatenate([self.scores, other.scores], axis=0),
            sizes=_both(self.sizes, other.sizes),
            angles=_both(self.angles, other.angles),
            affine=_both(self.affine, other.affine),
            landmark_ids=_both(self.landmark_ids, other.landmark_ids),
        )

    def transform(self, T: np.ndarray, *, image_size: tuple[int, int] | None = None) -> FeatureSet:
        """Map keypoints through a 3x3 homography.

        This is how ASIFT lifts tilt-simulated keypoints back into the original frame.
        Descriptors are unchanged — they were computed in the simulated view and remain
        valid there. The local geometry is pushed forward by the transform's Jacobian at
        each point:

            J(p) = (1/w) * [[a - x'*g, b - x'*h],
                            [d - y'*g, e - y'*h]]           for T = [[a,b,c],[d,e,f],[g,h,i]]

        * `affine` frames are premultiplied by J.
        * `sizes` scale by ``sqrt(|det J|)`` — the local area change.
        * `angles` are carried through J as a direction and re-derived with atan2, so a
          non-conformal T rotates them correctly rather than by a global constant.

        Args:
            T: (3,3) homography mapping this set's frame to the target frame.
            image_size: The target frame's (width, height). Defaults to `self.image_size`,
                which is correct only when T maps the frame onto itself. ASIFT lifts
                between frames of different sizes and MUST pass this, or the result will
                not validate().
        """
        T = np.asarray(T, dtype=np.float64)
        if T.shape != (3, 3):
            raise ValueError(f"T must be (3,3); got shape {T.shape}")

        n = self.num_features
        if n == 0:
            return replace(self, image_size=image_size or self.image_size)

        pts = self.keypoints.astype(np.float64)
        homogeneous = np.column_stack([pts, np.ones(n, dtype=np.float64)])
        mapped = homogeneous @ T.T
        w = mapped[:, 2]
        if not np.all(np.abs(w) > 1e-12):
            raise ValueError("T maps at least one keypoint onto the line at infinity")
        warped = mapped[:, :2] / w[:, None]

        # Per-point Jacobian of the projective map.
        jac = np.empty((n, 2, 2), dtype=np.float64)
        jac[:, 0, 0] = T[0, 0] - warped[:, 0] * T[2, 0]
        jac[:, 0, 1] = T[0, 1] - warped[:, 0] * T[2, 1]
        jac[:, 1, 0] = T[1, 0] - warped[:, 1] * T[2, 0]
        jac[:, 1, 1] = T[1, 1] - warped[:, 1] * T[2, 1]
        jac /= w[:, None, None]

        new_affine: np.ndarray | None = None
        if self.affine is not None:
            new_affine = (jac @ self.affine.astype(np.float64)).astype(np.float32)

        new_sizes: np.ndarray | None = None
        if self.sizes is not None:
            det = np.abs(np.linalg.det(jac))
            new_sizes = (self.sizes.astype(np.float64) * np.sqrt(det)).astype(np.float32)

        new_angles: np.ndarray | None = None
        if self.angles is not None:
            a = self.angles.astype(np.float64)
            direction = np.stack([np.cos(a), np.sin(a)], axis=1)
            pushed = np.einsum("nij,nj->ni", jac, direction)
            new_angles = np.arctan2(pushed[:, 1], pushed[:, 0]).astype(np.float32)
            new_angles[~np.isfinite(a)] = np.float32(np.nan)

        return replace(
            self,
            keypoints=warped.astype(np.float32),
            image_size=image_size or self.image_size,
            sizes=new_sizes,
            angles=new_angles,
            affine=new_affine,
        )


@dataclass(frozen=True, slots=True)
class ExtractorCapabilities:
    """What an extractor can actually do — asked, never assumed.

    `supports_extract_at` is the one that matters: an extractor that cannot describe at
    caller-supplied points cannot see the user's landmarks at all, and the landmark path
    is the product's differentiator.
    """

    supports_mask: bool
    supports_extract_at: bool
    supports_batch: bool
    is_affine_covariant: bool
    requires_grayscale: bool
    device: Device
    max_features: int
