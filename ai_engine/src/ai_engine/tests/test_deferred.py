"""★ EVERY DEFERRED ENTRY POINT RAISES `NotImplementedDeferred` — never junk.

This suite exists because the deferred surface's failure mode is **silence**, and silence
passes every test that only checks for the absence of an exception. A stub that returned
`None`, or `()`, or `0.0`, or an empty `MatchSet` would look exactly like a working
component that found nothing — and the caller could not tell the difference, which is the
entire problem (``docs/architecture/SCOPE.md`` §4 rule 2).

So this file asserts the positive property: **calling a deferred thing raises, and the
exception names what is missing and where the ruling is written down.**

The three specific failures it forbids:

* ``pass`` / a bare ``None`` — indistinguishable from success;
* an empty-but-plausible result — ``no_viable_candidate`` means *the engine looked and found
  nothing*, which is a false claim about the surveyor's imagery when the engine never looked;
* a fabricated keypoint, score, homography or confidence — a confidently wrong coordinate
  handed to a surveyor is this system's worst failure mode (L12).
"""

from __future__ import annotations

import inspect

import numpy as np

from ai_engine.errors import AiEngineError, NotImplementedDeferred
from ai_engine.models import REGISTRY, ComponentKind

# --------------------------------------------------------------------------------------
# the exception itself
# --------------------------------------------------------------------------------------


def test_not_implemented_deferred_is_distinct_from_builtin() -> None:
    """★ It must NOT subclass the builtin `NotImplementedError`.

    The distinctness is the whole point. `backend.app.api` catches exactly this class to
    answer 501 with a `feature: "deferred"` marker, and a generic
    `except NotImplementedError` — meant to catch an unimplemented ABC method somewhere
    unrelated — must not be able to swallow it by accident.
    """
    assert issubclass(NotImplementedDeferred, AiEngineError)
    assert not issubclass(NotImplementedDeferred, NotImplementedError)


def test_not_implemented_deferred_carries_module_and_doc() -> None:
    """It names the module and points at the ruling, in the message and in fields."""
    exc = NotImplementedDeferred("ai_engine.extractors.sift", feature="SIFT extraction")
    assert exc.module == "ai_engine.extractors.sift"
    assert exc.feature == "SIFT extraction"
    assert exc.doc_ref == "docs/architecture/SCOPE.md"
    text = str(exc)
    assert "SIFT extraction" in text
    assert "docs/architecture/SCOPE.md" in text
    assert "manual" in text.lower()


# --------------------------------------------------------------------------------------
# every registered component
# --------------------------------------------------------------------------------------


def test_every_registered_factory_raises_deferred() -> None:
    """★ THE SWEEP. Constructing ANY registered component raises `NotImplementedDeferred`.

    Parametrised over the live registry rather than a hand-written list, so a component
    added later without a deferred body fails here instead of shipping a stub that silently
    returns something.
    """
    specs = REGISTRY.specs()
    assert specs, "empty registry: this test would vacuously pass"

    for spec in specs:
        try:
            instance = spec.factory({})
        except NotImplementedDeferred as exc:
            assert exc.module.startswith("ai_engine."), f"{spec.name}: bad module {exc.module!r}"
            assert exc.doc_ref == "docs/architecture/SCOPE.md", f"{spec.name}: bad doc_ref"
            assert exc.feature, f"{spec.name}: no human-readable feature name"
        except Exception as exc:  # noqa: BLE001
            raise AssertionError(
                f"{spec.kind} {spec.name!r} raised {type(exc).__name__} instead of "
                f"NotImplementedDeferred: {exc}"
            ) from exc
        else:
            raise AssertionError(
                f"{spec.kind} {spec.name!r} CONSTRUCTED and returned {instance!r}. A "
                f"deferred component must raise — an object that silently does nothing is "
                f"indistinguishable from one that works."
            )


def test_every_registered_class_implements_its_abstract_methods() -> None:
    """★ No stub may rely on ABCMeta to do its refusing.

    If a deferred class left an abstract method unimplemented, instantiating it would raise
    `TypeError: Can't instantiate abstract class ...` — an error about Python, not about
    this product, carrying no module, no feature and no pointer to the ruling, and NOT
    catchable by the 501 handler. The signatures also have to be written out for the seam to
    mean anything.
    """
    for spec in REGISTRY.specs():
        cls = spec.factory
        assert inspect.isclass(cls), f"{spec.name}: factory is not a class"
        remaining = getattr(cls, "__abstractmethods__", frozenset())
        assert not remaining, (
            f"{spec.kind} {spec.name!r} leaves {sorted(remaining)} abstract, so it raises "
            f"TypeError instead of NotImplementedDeferred"
        )


def test_deferred_components_never_return_a_falsy_placeholder() -> None:
    """No factory returns None, (), 0 or an empty container instead of raising."""
    for spec in REGISTRY.specs():
        try:
            result = spec.factory({})
        except NotImplementedDeferred:
            continue
        except Exception:  # noqa: BLE001 - covered by the sweep above
            continue
        raise AssertionError(
            f"{spec.name!r} returned {result!r} rather than raising. Never `pass`, never a "
            f"silent None, never a fabricated value."
        )


# --------------------------------------------------------------------------------------
# the public entry points
# --------------------------------------------------------------------------------------


def test_run_match_job_raises_immediately() -> None:
    """★ THE PRIMARY ENTRY POINT REFUSES — it does not return an empty result.

    `run_match_job`'s own contract says it never raises for a business outcome, and returns
    `status="no_viable_candidate"` when nothing matches. That makes returning the empty
    result a very tempting way to defer it — and it would be the worst possible choice.
    "No viable candidate" asserts that the engine LOOKED and found nothing: a factual claim
    about the surveyor's photograph. Saying that when the engine never looked would send
    them back to re-shoot a site over a lie, with an honest-looking empty state in the UI and
    every metric agreeing.
    """
    from ai_engine.pipeline.orchestrator import run_match_job

    try:
        run_match_job(None)  # type: ignore[arg-type]
    except NotImplementedDeferred as exc:
        assert exc.module == "ai_engine.pipeline.orchestrator"
        assert "docs/architecture/SCOPE.md" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("run_match_job did not raise — it must never fake a result")


def test_suggest_landmarks_raises_immediately() -> None:
    """The second public entry point refuses too."""
    from ai_engine.config import AiEngineConfig
    from ai_engine.landmarks.suggest import suggest_landmarks

    try:
        suggest_landmarks(np.zeros((4, 4, 3), dtype=np.uint8), cfg=AiEngineConfig())
    except NotImplementedDeferred as exc:
        assert exc.module == "ai_engine.landmarks.suggest"
    else:  # pragma: no cover
        raise AssertionError("suggest_landmarks did not raise")


def test_build_context_raises() -> None:
    """The composition root refuses: there are no components to compose."""
    from ai_engine.config import AiEngineConfig
    from ai_engine.pipeline.compose import build_context

    try:
        build_context(
            AiEngineConfig(),
            registry=REGISTRY,
            job_id="j",
            query_image=np.zeros((4, 4, 3), dtype=np.uint8),
            query_image_ref=None,  # type: ignore[arg-type]
            landmarks=None,  # type: ignore[arg-type]
            windows=None,  # type: ignore[arg-type]
        )
    except NotImplementedDeferred as exc:
        assert exc.module == "ai_engine.pipeline.compose"
    else:  # pragma: no cover
        raise AssertionError("build_context did not raise")


def test_lazy_root_reexports_resolve() -> None:
    """`ai_engine.run_match_job` and friends bind through the PEP 562 root.

    The 501 path in the API goes through these names; if the lazy table drifted, the API
    would get an `AttributeError` rather than a deferred refusal.
    """
    import ai_engine

    assert callable(ai_engine.run_match_job)
    assert callable(ai_engine.suggest_landmarks)
    assert ai_engine.AiEngineConfig is not None
    assert ai_engine.Registry is not None
    assert ai_engine.version()


# --------------------------------------------------------------------------------------
# the module-level deferred functions
# --------------------------------------------------------------------------------------


def test_module_level_deferred_functions_raise() -> None:
    """Every free function on the deferred surface raises with its own module name."""
    from ai_engine.extractors import preprocess
    from ai_engine.geometry import normalize, refine, uncertainty
    from ai_engine.landmarks import consistency, priors, topology
    from ai_engine.matchers import filters
    from ai_engine.pipeline import ranking, steps
    from ai_engine.semantics import compare, croprows, indices, ridges, structures

    zeros = np.zeros((4, 4, 3), dtype=np.uint8)
    eye = np.eye(3)

    cases: list[tuple[str, object]] = [
        ("ai_engine.extractors.preprocess", lambda: preprocess.to_grayscale(zeros)),
        ("ai_engine.extractors.preprocess", lambda: preprocess.apply_clahe(zeros)),
        ("ai_engine.extractors.preprocess", lambda: preprocess.resize_max_side(zeros, 2)),
        ("ai_engine.extractors.preprocess", lambda: preprocess.gamma_correct(zeros, 2.2)),
        ("ai_engine.matchers.filters", lambda: filters.lowe_ratio(None)),  # type: ignore[arg-type]
        ("ai_engine.matchers.filters", lambda: filters.mutual_nn(None, n_a=1, n_b=1)),  # type: ignore[arg-type]
        ("ai_engine.matchers.filters", lambda: filters.dedupe_many_to_one(None)),  # type: ignore[arg-type]
        ("ai_engine.geometry.normalize", lambda: normalize.hartley_normalize(np.zeros((4, 2)))),
        ("ai_engine.geometry.normalize", lambda: normalize.denormalize_h(eye, eye, eye)),
        ("ai_engine.geometry.normalize", lambda: normalize.normalize_h(eye, eye, eye)),
        (
            "ai_engine.geometry.refine",
            lambda: refine.refine_symmetric_transfer(eye, np.zeros((4, 2)), np.zeros((4, 2))),
        ),
        (
            "ai_engine.geometry.uncertainty",
            lambda: uncertainty.propagate_point_cov(eye, np.zeros(2), np.zeros((9, 9))),
        ),
        ("ai_engine.semantics.indices", lambda: indices.exg(zeros)),
        ("ai_engine.semantics.indices", lambda: indices.gli(zeros)),
        ("ai_engine.semantics.indices", lambda: indices.ndwi(np.zeros((4, 4)), np.zeros((4, 4)))),
        ("ai_engine.semantics.indices", lambda: indices.mndwi(np.zeros((4, 4)), np.zeros((4, 4)))),
        ("ai_engine.semantics.croprows", lambda: croprows.estimate_crop_rows(zeros)),
        ("ai_engine.semantics.croprows", lambda: croprows.estimate_tree_lattice(zeros)),
        ("ai_engine.semantics.ridges", lambda: ridges.detect_ridges(zeros)),
        ("ai_engine.semantics.structures", lambda: structures.detect_greenhouses(zeros)),
        ("ai_engine.semantics.structures", lambda: structures.detect_buildings(zeros)),
        ("ai_engine.semantics.structures", lambda: structures.detect_water_bodies(zeros)),
        ("ai_engine.semantics.compare", lambda: compare.semantic_similarity(None, None, H=eye)),  # type: ignore[arg-type]
        ("ai_engine.landmarks.priors", lambda: priors.landmark_sampling_prior(None, (4, 4))),  # type: ignore[arg-type]
        ("ai_engine.landmarks.priors", lambda: priors.weight_field_from_landmarks(None)),  # type: ignore[arg-type]
        ("ai_engine.landmarks.topology", lambda: topology.cross_ratio_signature(np.zeros((5, 2)))),
        ("ai_engine.landmarks.consistency", lambda: consistency.landmark_consistency(None, ())),  # type: ignore[arg-type]
        ("ai_engine.pipeline.steps", lambda: steps.step1_extract_query_features(None)),  # type: ignore[arg-type]
        ("ai_engine.pipeline.steps", lambda: list(steps.step3_iter_windows(None))),  # type: ignore[arg-type]
        ("ai_engine.pipeline.steps", lambda: steps.step4_extract_window_features(None, None)),  # type: ignore[arg-type]
        ("ai_engine.pipeline.steps", lambda: steps.step5_correspond(None, None, None, None)),  # type: ignore[arg-type]
        ("ai_engine.pipeline.steps", lambda: steps.step6_estimate_homography(None, None)),  # type: ignore[arg-type]
        ("ai_engine.pipeline.steps", lambda: steps.step7_score(None, None)),  # type: ignore[arg-type]
        ("ai_engine.pipeline.steps", lambda: steps.step8_rank(None, ())),  # type: ignore[arg-type]
        ("ai_engine.pipeline.steps", lambda: steps.step9_finalize(None, ())),  # type: ignore[arg-type]
        ("ai_engine.pipeline.ranking", lambda: ranking.rank_windows(())),
        ("ai_engine.pipeline.ranking", lambda: ranking.ambiguity_margin(())),
    ]

    for expected_module, call in cases:
        try:
            call()  # type: ignore[operator]
        except NotImplementedDeferred as exc:
            assert exc.module == expected_module, (
                f"expected module {expected_module!r}, got {exc.module!r}"
            )
        else:  # pragma: no cover
            raise AssertionError(f"{expected_module} returned instead of raising")


def test_deferred_classes_raise_on_construction() -> None:
    """The non-registered deferred classes refuse too."""
    from ai_engine.geometry.degeneracy import DegeneracyValidator
    from ai_engine.geometry.intrinsics import AgriVanishingPointCalibrator
    from ai_engine.geometry.pose import PoseEstimator
    from ai_engine.heatmap.posterior import CameraPosterior
    from ai_engine.landmarks.patches import LandmarkPatchBank
    from ai_engine.matchers.loftr import LoFTRAsMatcher
    from ai_engine.scoring.calibration import IsotonicCalibrator, PlattCalibrator

    cases = [
        ("ai_engine.geometry.degeneracy", lambda: DegeneracyValidator()),
        ("ai_engine.geometry.pose", lambda: PoseEstimator()),
        ("ai_engine.geometry.intrinsics", lambda: AgriVanishingPointCalibrator((10, 10))),
        ("ai_engine.heatmap.posterior", lambda: CameraPosterior()),
        ("ai_engine.landmarks.patches", lambda: LandmarkPatchBank(None, None)),  # type: ignore[arg-type]
        ("ai_engine.matchers.loftr", lambda: LoFTRAsMatcher({})),
        ("ai_engine.scoring.calibration", lambda: PlattCalibrator(1.0, 0.0)),
        (
            "ai_engine.scoring.calibration",
            lambda: IsotonicCalibrator(np.zeros(2), np.zeros(2)),
        ),
    ]
    for expected_module, call in cases:
        try:
            call()
        except NotImplementedDeferred as exc:
            assert exc.module == expected_module
        else:  # pragma: no cover
            raise AssertionError(f"{expected_module} constructed instead of raising")


def test_deferred_source_constructors_are_real_but_correspond_is_deferred() -> None:
    """`DetectBasedSource`'s guard is REAL; its `correspond` is deferred.

    ★ The constructor assertion is the one piece of `sources.py` that must work today,
    because it is the only thing stopping a LOSSY detector-free shim from being wired into
    the detector-based path — a mistake that raises nothing, logs nothing, and silently
    degrades every match.
    """
    from ai_engine.matchers.sources import DetectBasedSource, EnsembleSource

    class _FakeLossyMatcher:
        name = "fake"
        requires_images = True

    try:
        DetectBasedSource(extractor=None, matcher=_FakeLossyMatcher())  # type: ignore[arg-type]
    except TypeError as exc:
        assert "requires_images" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("DetectBasedSource accepted a detector-free shim")

    try:
        EnsembleSource([])
    except ValueError as exc:
        assert "at least one source" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("EnsembleSource accepted an empty source list")


def test_matcher_guided_defaults_are_deferred_not_notimplementederror() -> None:
    """The ABC's guided defaults raise `NotImplementedDeferred`, not `NotImplementedError`.

    The contract specifies a real default for `match_guided`, so "a subclass must supply
    this" would be false. What is true is that the default is part of the deferred surface —
    and only `NotImplementedDeferred` reaches the 501 handler.
    """
    from ai_engine.matchers.base import DetectorFreeMatcher, Matcher

    class _M(Matcher):
        name = "m"
        supported_kinds = frozenset()
        version = "1"

        def match(self, a, b):  # type: ignore[no-untyped-def]
            raise AssertionError("not reached")

    class _D(DetectorFreeMatcher):
        name = "d"
        version = "1"

        def match_images(self, image_a, image_b, mask_a=None, mask_b=None):  # type: ignore[no-untyped-def]
            raise AssertionError("not reached")

    try:
        _M().match_guided(None, None, prior_H=np.eye(3), radius_px=1.0)  # type: ignore[arg-type]
    except NotImplementedDeferred as exc:
        assert exc.module == "ai_engine.matchers.base"
    else:  # pragma: no cover
        raise AssertionError("Matcher.match_guided did not raise NotImplementedDeferred")

    try:
        _D().match_images_guided(None, None, prior_H=np.eye(3), radius_px=1.0)  # type: ignore[arg-type]
    except NotImplementedDeferred as exc:
        assert exc.module == "ai_engine.matchers.base"
    else:  # pragma: no cover
        raise AssertionError("match_images_guided did not raise NotImplementedDeferred")


def test_deferred_surface_covers_every_scope_item() -> None:
    """★ Every capability SCOPE §4 defers has a registered entry or a named module.

    A structural check against the deferral quietly losing a feature: SCOPE promises each of
    these keeps "its interface, its registry entry, and its tests-for-the-seam".
    """
    names = {spec.name for spec in REGISTRY.specs()}
    for required in (
        "sift",
        "orb",
        "superpoint",  # feature extraction
        "flann",
        "bf",
        "superglue",
        "lightglue",
        "loftr",  # matching
        "opencv",  # RANSAC homography
        "classical",
        "sam",
        "dinov2_seg",  # semantics
        "composite",  # composite score
        "dinov2",  # registry entry only
        "classical_suggester",
        "sam_suggester",  # suggestion
    ):
        assert required in names, f"SCOPE §4 defers {required!r} but it is not registered"

    # ABC-only items: no registry entry, but the module and class must exist.
    import ai_engine.geometry.pose  # noqa: F401  — camera pose
    import ai_engine.heatmap.posterior  # noqa: F401  — confidence heatmap
    import ai_engine.pipeline.orchestrator  # noqa: F401  — automatic pipeline
