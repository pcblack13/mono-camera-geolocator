"""IU-01 — the value types enforce their own invariants.

Every assertion here pins a rule that fails SILENTLY if it is not enforced: a
non-unit-norm descriptor still matches (just worse), a duplicate landmark_id still
solves (just with the wrong weights), an unsorted PROSAC input still estimates (just
uniformly). None of it crashes. That is exactly why it is tested at the boundary.
"""

from __future__ import annotations

import numpy as np
import pytest

from ai_engine.errors import IncompatibleDescriptors
from ai_engine.types import (
    CandidateWindow,
    Correspondences,
    DescriptorKind,
    FeatureSet,
    HomographyMethod,
    LandmarkWeightField,
    MatchSet,
    PoseMethod,
    SemanticClass,
    WindowRef,
)

# --------------------------------------------------------------------------------------
# builders — a valid object per type, so each test perturbs exactly one thing
# --------------------------------------------------------------------------------------


def make_float_features(n: int = 5, d: int = 8, size: tuple[int, int] = (64, 48)) -> FeatureSet:
    """A validate()-clean FLOAT FeatureSet with unit-norm descriptors."""
    rng = np.random.default_rng(0)
    kps = rng.uniform(1.0, 40.0, size=(n, 2)).astype(np.float32)
    desc = rng.normal(size=(n, d)).astype(np.float32)
    desc /= np.linalg.norm(desc, axis=1, keepdims=True)
    scores = np.linspace(1.0, 0.1, n, dtype=np.float32)
    return FeatureSet(
        keypoints=kps,
        descriptors=desc.astype(np.float32),
        scores=scores,
        image_size=size,
        extractor_name="sift",
        descriptor_kind=DescriptorKind.FLOAT,
    )


def make_binary_features(n: int = 5, n_bytes: int = 61) -> FeatureSet:
    """A validate()-clean BINARY FeatureSet, shaped like AKAZE's 61-byte MLDB."""
    rng = np.random.default_rng(1)
    return FeatureSet(
        keypoints=rng.uniform(1.0, 40.0, size=(n, 2)).astype(np.float32),
        descriptors=rng.integers(0, 256, size=(n, n_bytes), dtype=np.uint8),
        scores=np.linspace(1.0, 0.1, n, dtype=np.float32),
        image_size=(64, 48),
        extractor_name="akaze",
        descriptor_kind=DescriptorKind.BINARY,
    )


def make_correspondences(
    pts_a: np.ndarray,
    pts_b: np.ndarray,
    scores: np.ndarray,
    weights: np.ndarray | None = None,
    *,
    source_name: str = "flann",
    prior_free: bool = True,
) -> Correspondences:
    return Correspondences(
        pts_a=np.asarray(pts_a, dtype=np.float32),
        pts_b=np.asarray(pts_b, dtype=np.float32),
        scores=np.asarray(scores, dtype=np.float32),
        image_size_a=(64, 48),
        image_size_b=(64, 48),
        source_name=source_name,
        is_dense=False,
        weights=None if weights is None else np.asarray(weights, dtype=np.float32),
        prior_free=prior_free,
    )


# --------------------------------------------------------------------------------------
# FeatureSet.validate
# --------------------------------------------------------------------------------------


def test_valid_feature_sets_pass() -> None:
    make_float_features().validate()
    make_binary_features().validate()


def test_empty_feature_set_is_valid() -> None:
    """An extractor that finds nothing returns an EMPTY set rather than raising, so the
    empty set must itself be clean — otherwise every blank-image path throws."""
    empty = FeatureSet(
        keypoints=np.zeros((0, 2), dtype=np.float32),
        descriptors=np.zeros((0, 8), dtype=np.float32),
        scores=np.zeros((0,), dtype=np.float32),
        image_size=(64, 48),
        extractor_name="sift",
        descriptor_kind=DescriptorKind.FLOAT,
    )
    empty.validate()
    assert empty.num_features == 0


def test_validate_rejects_shape_mismatch() -> None:
    fs = make_float_features(n=5)
    bad = FeatureSet(**{**_fields(fs), "descriptors": fs.descriptors[:3]})
    with pytest.raises(ValueError, match="rows"):
        bad.validate()

    bad_scores = FeatureSet(**{**_fields(fs), "scores": fs.scores[:2]})
    with pytest.raises(ValueError, match="scores"):
        bad_scores.validate()

    bad_kps = FeatureSet(**{**_fields(fs), "keypoints": fs.keypoints[:, :1]})
    with pytest.raises(ValueError, match=r"\(N,2\)"):
        bad_kps.validate()


def test_validate_rejects_non_finite_keypoints() -> None:
    fs = make_float_features()
    kps = fs.keypoints.copy()
    kps[2, 0] = np.nan
    with pytest.raises(ValueError, match="non-finite"):
        FeatureSet(**{**_fields(fs), "keypoints": kps}).validate()

    kps[2, 0] = np.inf
    with pytest.raises(ValueError, match="non-finite"):
        FeatureSet(**{**_fields(fs), "keypoints": kps}).validate()


def test_validate_rejects_keypoints_outside_image_size() -> None:
    fs = make_float_features(size=(64, 48))
    kps = fs.keypoints.copy()
    kps[1] = (64.0 + 10.0, 5.0)  # past the right edge
    with pytest.raises(ValueError, match="outside image_size"):
        FeatureSet(**{**_fields(fs), "keypoints": kps}).validate()

    kps[1] = (5.0, -3.0)  # above the top edge
    with pytest.raises(ValueError, match="outside image_size"):
        FeatureSet(**{**_fields(fs), "keypoints": kps}).validate()


def test_validate_accepts_subpixel_keypoints_at_the_border() -> None:
    """Integer coordinates are pixel CENTRES, so the image spans [-0.5, W-0.5]. A
    subpixel refinement that nudges a border keypoint to -0.4 is inside the image, and
    rejecting it would make every edge feature a spurious error."""
    fs = make_float_features(size=(64, 48))
    kps = fs.keypoints.copy()
    kps[0] = (-0.4, 47.4)
    FeatureSet(**{**_fields(fs), "keypoints": kps}).validate()


def test_validate_rejects_non_unit_norm_float_descriptors() -> None:
    """DescriptorKind.FLOAT means exactly one thing everywhere: L2-normalised. A matcher
    computing L2 distance on unnormalised rows returns plausible garbage."""
    fs = make_float_features()
    desc = fs.descriptors.copy()
    desc[3] *= 1.5
    with pytest.raises(ValueError, match="L2-normalised"):
        FeatureSet(**{**_fields(fs), "descriptors": desc}).validate()


def test_validate_unit_norm_tolerance_is_1e_3() -> None:
    """The tolerance is normative: 1e-3 passes, 1e-2 does not."""
    fs = make_float_features()

    within = fs.descriptors.copy()
    within[0] *= 1.0 + 5e-4
    FeatureSet(**{**_fields(fs), "descriptors": within}).validate()

    outside = fs.descriptors.copy()
    outside[0] *= 1.0 + 1e-2
    with pytest.raises(ValueError, match="L2-normalised"):
        FeatureSet(**{**_fields(fs), "descriptors": outside}).validate()


def test_validate_rejects_scores_outside_unit_interval() -> None:
    fs = make_float_features()
    for bad_value in (-0.01, 1.01):
        scores = fs.scores.copy()
        scores[0] = bad_value
        with pytest.raises(ValueError, match=r"scores must lie in \[0,1\]"):
            FeatureSet(**{**_fields(fs), "scores": scores}).validate()


def test_validate_rejects_dtype_mismatch() -> None:
    fs = make_float_features()
    with pytest.raises(ValueError, match="keypoints must be float32"):
        FeatureSet(**{**_fields(fs), "keypoints": fs.keypoints.astype(np.float64)}).validate()
    with pytest.raises(ValueError, match="FLOAT descriptors must be float32"):
        FeatureSet(**{**_fields(fs), "descriptors": fs.descriptors.astype(np.float64)}).validate()
    with pytest.raises(ValueError, match="scores must be float32"):
        FeatureSet(**{**_fields(fs), "scores": fs.scores.astype(np.float64)}).validate()


def test_binary_descriptors_must_be_packed_uint8() -> None:
    """★ The constructible form of "descriptor_dim is not a whole number of bytes":
    unpacked bits stored as float32 and declared BINARY. AKAZE's 486 significant bits are
    the classic case — they are returned as 61 BYTES, and storing them any other way makes
    descriptor_dim disagree with the extractor's ClassVar, which raises
    IncompatibleDescriptors at every matcher."""
    bad = FeatureSet(
        keypoints=np.zeros((2, 2), dtype=np.float32),
        descriptors=np.zeros((2, 486), dtype=np.float32),
        scores=np.zeros((2,), dtype=np.float32),
        image_size=(64, 48),
        extractor_name="akaze",
        descriptor_kind=DescriptorKind.BINARY,
    )
    with pytest.raises(ValueError, match="bit-packed uint8"):
        bad.validate()


def test_binary_descriptor_dim_is_always_a_whole_number_of_bytes() -> None:
    """★ D = 488 for AKAZE, NOT 486.

    486 significant bits arrive as 61 bytes. `486 // 8 == 60 != 61` and `61 * 8 == 488`,
    so a ClassVar of 486 could never equal the computed property, `validate_pair`
    compares exactly that field, and EVERY AKAZE FeatureSet would raise
    IncompatibleDescriptors at composition time. descriptor_dim declares the STORAGE
    width; the final 2 bits are zero pad and Hamming is unaffected.
    """
    fs = make_binary_features(n_bytes=61)
    fs.validate()
    assert fs.descriptor_dim == 488
    assert fs.descriptor_dim % 8 == 0

    for n_bytes in (16, 32, 61, 64):
        assert make_binary_features(n_bytes=n_bytes).descriptor_dim % 8 == 0


def test_validate_rejects_duplicate_landmark_ids() -> None:
    """★ THE MULTI-ORIENTATION TRAP. `cv2.SIFT.compute()` emits one keypoint PER dominant
    orientation, so a K=8 extract_at can return N=14 with landmark_ids many-to-one. Nothing
    crashes: the duplicated landmark silently gets 2-3x its assigned PROSAC priority and
    S_l's sum over k is quietly reweighted. This is the boundary that catches it."""
    fs = make_float_features(n=5)
    ids = np.array([0, 1, 1, -1, -1], dtype=np.int32)
    with pytest.raises(ValueError, match="1:1"):
        FeatureSet(**{**_fields(fs), "landmark_ids": ids}).validate()


def test_validate_allows_repeated_detected_sentinel() -> None:
    """-1 means "detected, not a landmark" and repeats freely — only assigned ids are 1:1."""
    fs = make_float_features(n=5)
    ids = np.array([-1, -1, -1, 0, 1], dtype=np.int32)
    FeatureSet(**{**_fields(fs), "landmark_ids": ids}).validate()


def test_validate_rejects_wrong_landmark_id_dtype() -> None:
    fs = make_float_features(n=5)
    ids = np.array([-1, -1, -1, 0, 1], dtype=np.int64)
    with pytest.raises(ValueError, match="landmark_ids must be int32"):
        FeatureSet(**{**_fields(fs), "landmark_ids": ids}).validate()


# --------------------------------------------------------------------------------------
# FeatureSet.concat / select / transform
# --------------------------------------------------------------------------------------


def test_concat_raises_on_kind_dim_or_name_mismatch() -> None:
    a = make_float_features(n=4, d=8)

    with pytest.raises(IncompatibleDescriptors, match="binary"):
        a.concat(make_binary_features(n=4))

    other_dim = make_float_features(n=4, d=16)
    with pytest.raises(IncompatibleDescriptors, match="dim"):
        a.concat(other_dim)

    other_name = FeatureSet(**{**_fields(make_float_features(n=4, d=8)), "extractor_name": "orb"})
    with pytest.raises(IncompatibleDescriptors, match="orb"):
        a.concat(other_name)


def test_concat_of_compatible_sets_validates() -> None:
    a = make_float_features(n=4, d=8)
    b = make_float_features(n=3, d=8)
    merged = a.concat(b)
    merged.validate()
    assert merged.num_features == 7


def test_select_preserves_parallel_arrays() -> None:
    fs = make_float_features(n=6)
    ids = np.array([-1, 0, 1, 2, -1, 3], dtype=np.int32)
    fs = FeatureSet(**{**_fields(fs), "landmark_ids": ids})
    picked = fs.select(np.array([1, 3, 5]))
    picked.validate()
    assert picked.num_features == 3
    assert picked.landmark_ids is not None
    assert picked.landmark_ids.tolist() == [0, 2, 3]


def test_transform_maps_keypoints_and_is_invertible() -> None:
    """A round trip through T and T^-1 must return the original keypoints."""
    fs = make_float_features(n=6, size=(64, 48))
    T = np.array([[1.0, 0.0, 5.0], [0.0, 1.0, -3.0], [0.0, 0.0, 1.0]])
    moved = fs.transform(T)
    assert np.allclose(moved.keypoints, fs.keypoints + np.array([5.0, -3.0], dtype=np.float32))
    back = moved.transform(np.linalg.inv(T))
    assert np.allclose(back.keypoints, fs.keypoints, atol=1e-4)


def test_transform_pushes_affine_frames_through_the_jacobian() -> None:
    """For an affine T the Jacobian is constant and equals T's linear block, so the
    pushed-forward frame is exactly T[:2,:2] @ affine."""
    fs = make_float_features(n=3, size=(64, 48))
    affine = np.tile(np.eye(2, dtype=np.float32), (3, 1, 1))
    fs = FeatureSet(**{**_fields(fs), "affine": affine})
    T = np.array([[2.0, 0.0, 0.0], [0.0, 3.0, 0.0], [0.0, 0.0, 1.0]])
    out = fs.transform(T, image_size=(256, 256))
    assert out.affine is not None
    assert np.allclose(out.affine, np.tile(np.diag([2.0, 3.0]), (3, 1, 1)), atol=1e-5)
    assert out.image_size == (256, 256)


# --------------------------------------------------------------------------------------
# MatchSet.validate
# --------------------------------------------------------------------------------------


def make_match_set(indices: list[list[int]], scores: list[float]) -> MatchSet:
    return MatchSet(
        indices=np.asarray(indices, dtype=np.int32).reshape(-1, 2),
        scores=np.asarray(scores, dtype=np.float32),
        matcher_name="flann",
    )


def test_match_set_validate_accepts_a_clean_set() -> None:
    make_match_set([[0, 1], [1, 2], [2, 0]], [0.9, 0.5, 0.2]).validate(n_a=3, n_b=3)


def test_match_set_validate_rejects_out_of_range_indices() -> None:
    ms = make_match_set([[0, 1], [5, 2]], [0.9, 0.5])
    with pytest.raises(ValueError, match=r"indices into a must lie in \[0,3\)"):
        ms.validate(n_a=3, n_b=3)

    ms_b = make_match_set([[0, 1], [1, 7]], [0.9, 0.5])
    with pytest.raises(ValueError, match=r"indices into b must lie in \[0,3\)"):
        ms_b.validate(n_a=3, n_b=3)

    ms_neg = make_match_set([[0, 1], [-1, 2]], [0.9, 0.5])
    with pytest.raises(ValueError, match="indices into a"):
        ms_neg.validate(n_a=3, n_b=3)


def test_match_set_validate_rejects_duplicate_pairs() -> None:
    """A duplicate pair double-counts one piece of evidence in the inlier ratio and hands
    RANSAC the same constraint twice."""
    ms = make_match_set([[0, 1], [1, 2], [0, 1]], [0.9, 0.5, 0.4])
    with pytest.raises(ValueError, match="duplicate"):
        ms.validate(n_a=3, n_b=3)


def test_match_set_validate_allows_many_to_one_across_different_pairs() -> None:
    """(0,1) and (2,1) share a b-index but are different pairs — that is ambiguity for
    dedupe_many_to_one to measure, not a malformed set."""
    make_match_set([[0, 1], [2, 1]], [0.9, 0.5]).validate(n_a=3, n_b=3)


def test_match_set_validate_rejects_scores_outside_unit_interval() -> None:
    ms = make_match_set([[0, 1], [1, 2]], [0.9, 1.7])
    with pytest.raises(ValueError, match=r"scores must lie in \[0,1\]"):
        ms.validate(n_a=3, n_b=3)


def test_to_correspondences_carries_landmark_identity() -> None:
    a = make_float_features(n=4, d=8)
    a = FeatureSet(**{**_fields(a), "landmark_ids": np.array([-1, 7, -1, 9], dtype=np.int32)})
    b = make_float_features(n=4, d=8)
    ms = make_match_set([[1, 0], [3, 2]], [0.8, 0.6])

    corr = ms.to_correspondences(a, b)
    corr.validate()
    assert corr.landmark_ids is not None
    assert corr.landmark_ids.tolist() == [7, 9]
    assert np.allclose(corr.pts_a, a.keypoints[[1, 3]])
    assert np.allclose(corr.pts_b, b.keypoints[[0, 2]])
    assert corr.is_dense is False


# --------------------------------------------------------------------------------------
# Correspondences.sorted_by_weight / merge
# --------------------------------------------------------------------------------------


def test_sorted_by_weight_returns_a_permutation_that_actually_sorts() -> None:
    """★ PROSAC REQUIRES descending order; handing it unsorted data silently degrades it
    to uniform sampling. And the permutation must be USABLE to un-permute, because the
    inlier mask has to come back aligned to the caller's original object."""
    pts_a = np.array([[1, 1], [2, 2], [3, 3], [4, 4]], dtype=np.float32)
    pts_b = pts_a + 10
    scores = np.array([0.1, 0.9, 0.4, 0.7], dtype=np.float32)
    weights = np.array([0.5, 0.2, 0.9, 0.1], dtype=np.float32)
    corr = make_correspondences(pts_a, pts_b, scores, weights)

    ordered, perm = corr.sorted_by_weight()

    assert ordered.weights is not None
    assert np.all(np.diff(ordered.weights) <= 0), "not descending"
    assert sorted(perm.tolist()) == [0, 1, 2, 3], "not a permutation"
    assert np.allclose(ordered.pts_a, corr.pts_a[perm])

    inv = np.empty_like(perm)
    inv[perm] = np.arange(len(perm))
    assert np.allclose(ordered.pts_a[inv], corr.pts_a)


def test_sorted_by_weight_falls_back_to_scores() -> None:
    pts_a = np.array([[1, 1], [2, 2], [3, 3]], dtype=np.float32)
    corr = make_correspondences(pts_a, pts_a + 5, np.array([0.2, 0.8, 0.5], dtype=np.float32))
    ordered, perm = corr.sorted_by_weight()
    assert np.all(np.diff(ordered.scores) <= 0)
    assert perm.tolist() == [1, 2, 0]


def test_sorted_by_weight_is_stable_on_ties() -> None:
    """Determinism under a fixed seed depends on this: equal keys keep input order."""
    pts_a = np.array([[1, 1], [2, 2], [3, 3]], dtype=np.float32)
    corr = make_correspondences(pts_a, pts_a + 5, np.array([0.5, 0.5, 0.5], dtype=np.float32))
    _, perm = corr.sorted_by_weight()
    assert perm.tolist() == [0, 1, 2]


def test_merge_dedupes_only_when_both_endpoints_are_close() -> None:
    """★ BOTH endpoints, not either. Two matches sharing only a query point are different
    hypotheses about where that point went; collapsing them would discard the ambiguity."""
    a1 = np.array([[10.0, 10.0]], dtype=np.float32)
    b1 = np.array([[20.0, 20.0]], dtype=np.float32)

    # Same a, far b -> NOT a duplicate.
    left = make_correspondences(a1, b1, np.array([0.9], dtype=np.float32), source_name="s1")
    right = make_correspondences(
        a1, np.array([[40.0, 40.0]], dtype=np.float32), np.array([0.5], dtype=np.float32),
        source_name="s2",
    )
    assert Correspondences.merge([left, right], dedupe_px=2.0).num_correspondences == 2

    # Far a, same b -> NOT a duplicate.
    right_b = make_correspondences(
        np.array([[80.0, 80.0]], dtype=np.float32), b1, np.array([0.5], dtype=np.float32),
        source_name="s2",
    )
    assert Correspondences.merge([left, right_b], dedupe_px=2.0).num_correspondences == 2

    # Both endpoints within dedupe_px -> ONE survivor.
    near = make_correspondences(
        a1 + 1.0, b1 + 1.0, np.array([0.5], dtype=np.float32), source_name="s2"
    )
    assert Correspondences.merge([left, near], dedupe_px=2.0).num_correspondences == 1

    # Both endpoints just outside -> both survive.
    far = make_correspondences(
        a1 + 3.0, b1 + 3.0, np.array([0.5], dtype=np.float32), source_name="s2"
    )
    assert Correspondences.merge([left, far], dedupe_px=2.0).num_correspondences == 2


def test_merge_keeps_the_higher_weight_duplicate() -> None:
    a = np.array([[10.0, 10.0]], dtype=np.float32)
    b = np.array([[20.0, 20.0]], dtype=np.float32)
    weak = make_correspondences(
        a, b, np.array([0.3], dtype=np.float32), np.array([0.3], dtype=np.float32), source_name="w"
    )
    strong = make_correspondences(
        a + 0.5,
        b + 0.5,
        np.array([0.4], dtype=np.float32),
        np.array([2.5], dtype=np.float32),
        source_name="s",
    )

    merged = Correspondences.merge([weak, strong], dedupe_px=2.0)
    assert merged.num_correspondences == 1
    assert merged.weights is not None
    assert merged.weights[0] == pytest.approx(2.5)
    assert np.allclose(merged.pts_a[0], strong.pts_a[0])

    # Order of the inputs must not change the survivor.
    flipped = Correspondences.merge([strong, weak], dedupe_px=2.0)
    assert flipped.weights is not None
    assert flipped.weights[0] == pytest.approx(2.5)


def test_merge_is_prior_free_only_if_every_part_is() -> None:
    """A gated part bounds the union's inlier ratio, so the union may not be scored as
    independent evidence."""
    a = np.array([[10.0, 10.0]], dtype=np.float32)
    s = np.array([0.5], dtype=np.float32)
    free = make_correspondences(a, a + 5, s, source_name="f", prior_free=True)
    gated = make_correspondences(a + 40, a + 45, s, source_name="g", prior_free=False)

    assert Correspondences.merge([free, free]).prior_free is True
    assert Correspondences.merge([free, gated]).prior_free is False


def test_merge_rejects_mismatched_frames() -> None:
    a = np.array([[1.0, 1.0]], dtype=np.float32)
    s = np.array([0.5], dtype=np.float32)
    one = make_correspondences(a, a, s)
    two = Correspondences(
        pts_a=a, pts_b=a, scores=s, image_size_a=(999, 999), image_size_b=(64, 48),
        source_name="x", is_dense=False,
    )
    with pytest.raises(ValueError, match="different image frames"):
        Correspondences.merge([one, two])


def test_merge_rejects_an_empty_sequence() -> None:
    with pytest.raises(ValueError, match="at least one"):
        Correspondences.merge([])


# --------------------------------------------------------------------------------------
# CandidateWindow — the seam
# --------------------------------------------------------------------------------------


def test_candidate_window_round_trips_its_opaque_payload_unchanged() -> None:
    """★ `geotransform` and `crs` are CARRIED, NEVER READ. This test is the executable
    statement of L3: the engine must hand back exactly the six floats and the authority
    string it was given, bit for bit, having formed no opinion about them."""
    gt = (-1.9558e07, 0.5971, 0.0, 7.3577e06, 0.0, -0.5971)
    window = CandidateWindow(
        ref=WindowRef(key="opaque-key-1", provider="esri_world_imagery"),
        rgb=np.zeros((8, 12, 3), dtype=np.uint8),
        geotransform=gt,
        crs="AUTHORITY:9999",
        gsd_m=0.34,
        georef_ce90_m=5.0,
        attribution="Esri, Maxar, Earthstar Geographics",
        terms_url="https://example.invalid/terms",
    )

    assert window.geotransform == gt
    assert window.geotransform is gt or tuple(window.geotransform) == gt
    assert window.crs == "AUTHORITY:9999"
    assert window.size == (12, 8)

    for produced, original in zip(window.geotransform, gt, strict=True):
        assert produced == original


def test_candidate_window_defaults_are_honest() -> None:
    """The optional payload defaults must never imply a capability the provider lacks."""
    window = CandidateWindow(
        ref=WindowRef(key="k", provider="fixture"),
        rgb=np.zeros((4, 4, 3), dtype=np.uint8),
        geotransform=(0.0, 1.0, 0.0, 0.0, 0.0, -1.0),
        crs="AUTHORITY:1",
        gsd_m=1.0,
        georef_ce90_m=1.0,
        attribution="fixture",
        terms_url="https://example.invalid/",
    )
    assert window.supports_multispectral is False
    assert window.extra_bands is None
    assert window.is_authoritative is False
    assert window.placeholder_fraction == 0.0
    assert window.captured_at is None


# --------------------------------------------------------------------------------------
# LandmarkWeightField — the normalisation that bounds PROSAC's priority
# --------------------------------------------------------------------------------------


def test_landmark_weight_field_is_bounded_by_one_and_priority_by_twelve() -> None:
    """★ THE BOUND, PINNED. With 12 landmarks at w_k=4 all clustered inside R_L, an
    UNNORMALISED g would reach ~48 and the priority factor (1+lam*g)(1+mu) would reach
    ~388x — two orders of magnitude against a base_score spanning one, collapsing PROSAC's
    ordering into a pure landmark-DENSITY map and discarding descriptor quality exactly
    when a surveyor marks many landmarks on one structure. Normalised, max(g) <= 1 and the
    stated 12x bound is the real bound."""
    k = 12
    centre = np.array([100.0, 100.0])
    rng = np.random.default_rng(7)
    points = (centre + rng.uniform(-5.0, 5.0, size=(k, 2))).astype(np.float32)
    field = LandmarkWeightField(
        points=points,
        weights=np.full(k, 4.0, dtype=np.float32),
        radius_px=96.0,
        lam=2.0,
        mu=3.0,
    )

    probe = np.concatenate([points, centre[None, :].astype(np.float32)], axis=0)
    g = field.evaluate(probe)

    assert g.shape == (k + 1,)
    assert float(g.max()) <= 1.0
    assert float(g.min()) >= 0.0
    assert float(g.max()) > 0.9, "landmarks inside R_L should saturate g"

    # priority = base * (1 + lam*g) * (1 + mu*on_landmark); bounded by (1+2*1)*(1+3*1) = 12.
    max_priority_factor = (1.0 + field.lam * float(g.max())) * (1.0 + field.mu * 1.0)
    assert max_priority_factor <= 12.0 + 1e-6


def test_landmark_weight_field_decays_with_distance() -> None:
    field = LandmarkWeightField(
        points=np.array([[0.0, 0.0]], dtype=np.float32),
        weights=np.array([1.0], dtype=np.float32),
        radius_px=10.0,
    )
    g = field.evaluate(np.array([[0.0, 0.0], [10.0, 0.0], [1000.0, 0.0]], dtype=np.float32))
    assert g[0] == pytest.approx(1.0, abs=1e-6)
    assert 0.0 < g[1] < 1.0
    assert g[2] == pytest.approx(0.0, abs=1e-9)
    assert g[0] > g[1] > g[2]


def test_landmark_weight_field_with_no_landmarks_is_zero() -> None:
    field = LandmarkWeightField(
        points=np.zeros((0, 2), dtype=np.float32), weights=np.zeros((0,), dtype=np.float32)
    )
    g = field.evaluate(np.array([[1.0, 2.0]], dtype=np.float32))
    assert g.shape == (1,)
    assert float(g[0]) == 0.0


# --------------------------------------------------------------------------------------
# ★ ENUM PARITY — LEG 3
# --------------------------------------------------------------------------------------
#
# `ai_engine` may not import sqlalchemy or app.schemas, so this leg pins the values
# against the normative PG type literals from CONTRACT §5.3. The backend's
# test_enum_parity.py closes the triangle from the other side over the same PARITY_MAP.
# Together the two assert what neither can alone: that all three legs agree.

PG_SEMANTIC_CLASS = (
    "field_border", "road", "irrigation_canal", "tree", "tree_line", "greenhouse",
    "building", "water_body", "crop_row", "bare_soil", "vegetation", "shadow", "unknown",
)
PG_ROBUST_ESTIMATOR = ("ransac", "usac_magsac", "lmeds", "prosac", "usac_accurate", "lsq")
PG_POSE_METHOD = (
    "zhang_plane", "homography_decomposition", "pnp", "exif_gps_only", "manual",
    "heatmap_argmax",
)


def test_semantic_class_matches_the_pg_enum() -> None:
    """★ Without this leg, ai_engine could emit a mask class the DB cannot store, or drop
    one the enum promised, and nothing would fail."""
    assert {c.value for c in SemanticClass} == set(PG_SEMANTIC_CLASS)


def test_homography_method_matches_the_robust_estimator_pg_enum() -> None:
    """Every method must be recordable, or a job cannot say what actually ran."""
    assert {m.value for m in HomographyMethod} == set(PG_ROBUST_ESTIMATOR)


def test_pose_method_matches_the_pg_enum() -> None:
    """`camera_poses.method` is NOT NULL — a method without a label is a pose that cannot
    be written at all. `zhang_plane` is the PRIMARY method and must be present."""
    assert {m.value for m in PoseMethod} == set(PG_POSE_METHOD)
    assert PoseMethod.ZHANG_PLANE.value == "zhang_plane"


def test_enum_values_are_plain_strings_on_the_wire() -> None:
    """L9: snake_case, one name per field, everywhere. StrEnum members ARE their values,
    so no serialisation layer needs a mapping table."""
    assert SemanticClass.WATER_BODY == "water_body"
    assert HomographyMethod.USAC_MAGSAC == "usac_magsac"
    assert PoseMethod.ZHANG_PLANE == "zhang_plane"


# --------------------------------------------------------------------------------------


def _fields(fs: FeatureSet) -> dict[str, object]:
    """Shallow field dict for a FeatureSet, so a test can perturb exactly one entry.

    `dataclasses.asdict` recurses into numpy arrays and is both slow and lossy here.
    """
    return {
        "keypoints": fs.keypoints,
        "descriptors": fs.descriptors,
        "scores": fs.scores,
        "image_size": fs.image_size,
        "extractor_name": fs.extractor_name,
        "descriptor_kind": fs.descriptor_kind,
        "sizes": fs.sizes,
        "angles": fs.angles,
        "affine": fs.affine,
        "image_ref": fs.image_ref,
        "extractor_version": fs.extractor_version,
        "params_hash": fs.params_hash,
        "landmark_ids": fs.landmark_ids,
        "meta": fs.meta,
    }
