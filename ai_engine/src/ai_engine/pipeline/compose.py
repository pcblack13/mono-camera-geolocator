"""★ THE COMPOSITION ROOT INSIDE `ai_engine`.

This is the one module allowed to see every subpackage at once — `models` + `extractors` +
`matchers` + `geometry` + `semantics` + `scoring` — and that is precisely why the Registry
cannot do this job itself:

1. `ComponentKind` has EXTRACTOR/MATCHER/DETECTOR_FREE/SEGMENTER/ESTIMATOR/SCORER/SUGGESTER.
   There is **no** "source" kind, no "validator" kind, no "cache" kind. A registry method
   could not produce `MatchContext.source`, `.validator` or `.cache` at all.
2. §10.2 **forbids** `ai_engine.models` from importing `ai_engine.matchers`, so the registry
   could not wrap a resolved matcher in a `DetectBasedSource` even in principle.

Composition needs to see everything; the registry must see almost nothing. Those are
different jobs, and merging them is what makes a registry into a god object.

★ `component_config` AND `params_hash` ARE REAL AND NORMATIVE (§4.14.1) EVEN THOUGH
`build_context` IS DEFERRED. They are not CV — they are a dict and a digest — and they are
**cache-key inputs**, which is exactly why they are normative: three units inventing three
key sets for one configuration is cache poisoning across a package boundary, arriving as a
slightly wrong answer rather than as an error.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from ai_engine.config import AiEngineConfig
from ai_engine.errors import NotImplementedDeferred
from ai_engine.models import ComponentKind, Registry
from ai_engine.models.hashing import params_hash
from ai_engine.pipeline.context import MatchContext
from ai_engine.types import (
    CacheBackend,
    CameraIntrinsics,
    ImageRef,
    LandmarkSet,
    ProgressCallback,
    ResolutionReport,
    WindowSource,
)

__all__ = ["build_context", "component_config", "params_hash"]


def component_config(cfg: AiEngineConfig, kind: ComponentKind) -> Mapping[str, Any]:
    """Build the config mapping for one `ComponentKind`. ★ The key sets are NORMATIVE.

    §4.14.1's table, exhaustively:

    ======================  ==================================================================
    `ComponentKind`         keys
    ======================  ==================================================================
    ``EXTRACTOR``           `max_features` · `clahe_enabled` · `weights_dir` · `device` · `asift`
    ``MATCHER``             `ratio_test` · `cross_check` · `min_matches` · `weights_dir` · `device`
    ``DETECTOR_FREE``       `weights_dir` · `device` · `deep`
    ``SEGMENTER``           `weights_dir` · `device` · `semantics_enabled`
    ``ESTIMATOR``           `ransac`
    ``SCORER``              `scoring` · `calibration_id`
    ``SUGGESTER``           `weights_dir` · `device` · `max_results`
    ======================  ==================================================================

    ★ EXHAUSTIVE MEANS EXHAUSTIVE. This mapping is hashed by :func:`params_hash` into a
    cache key. Adding a key changes every cache key for that kind; omitting one a component
    actually reads means two different configurations collide on one key and the second job
    silently serves the first job's descriptors. Change this table and bump the relevant
    `*_VERSION` in the same commit.

    ★ NOTE WHAT IS ABSENT: a `WeightManifest`. `resolve_with_fallback` takes it as a
    parameter instead, because a manifest object has no stable `str()` and folding one in
    would salt every key with an object address — see `models/hashing.py`.

    Args:
        cfg: The engine configuration.
        kind: The component slot being configured.

    Returns:
        The mapping, containing exactly the keys above and nothing else. Sub-configs are
        expanded to plain dicts so the mapping serialises stably.

    Raises:
        ValueError: `kind` is not one of the seven. A new `ComponentKind` with no row here
            would otherwise silently receive an empty config and hash identically for every
            configuration — one cache key for every possible setting of it.
    """
    if kind is ComponentKind.EXTRACTOR:
        return {
            "max_features": cfg.max_features,
            "clahe_enabled": cfg.clahe_enabled,
            "weights_dir": cfg.weights_dir,
            "device": cfg.device,
            "asift": _as_dict(cfg.asift),
        }
    if kind is ComponentKind.MATCHER:
        return {
            "ratio_test": cfg.ratio_test,
            "cross_check": cfg.cross_check,
            "min_matches": cfg.min_matches,
            "weights_dir": cfg.weights_dir,
            "device": cfg.device,
        }
    if kind is ComponentKind.DETECTOR_FREE:
        return {
            "weights_dir": cfg.weights_dir,
            "device": cfg.device,
            "deep": _as_dict(cfg.deep),
        }
    if kind is ComponentKind.SEGMENTER:
        return {
            "weights_dir": cfg.weights_dir,
            "device": cfg.device,
            "semantics_enabled": cfg.semantics_enabled,
        }
    if kind is ComponentKind.ESTIMATOR:
        return {"ransac": _as_dict(cfg.ransac)}
    if kind is ComponentKind.SCORER:
        return {
            "scoring": _as_dict(cfg.scoring),
            "calibration_id": cfg.calibration_id,
        }
    if kind is ComponentKind.SUGGESTER:
        return {
            "weights_dir": cfg.weights_dir,
            "device": cfg.device,
            "max_results": cfg.max_results,
        }
    raise ValueError(
        f"no normative component-config key set for {kind!r}. Every ComponentKind must "
        f"have a row in §4.14.1's table: a kind that falls through here would receive an "
        f"empty mapping and hash to one cache key for every possible configuration."
    )


def _as_dict(sub_config: Any) -> dict[str, Any]:
    """Flatten one of `AiEngineConfig`'s frozen sub-configs into a plain dict.

    ★ Field order is not relied on: `params_hash` sorts keys. `dataclasses.asdict` is
    avoided deliberately — it deep-copies numpy arrays and recurses into nested dataclasses,
    both of which are cost and neither of which is wanted for a shallow, scalar-only config.
    """
    fields = getattr(sub_config, "__dataclass_fields__", None)
    if fields is None:
        raise TypeError(
            f"expected a config dataclass; got {type(sub_config).__name__}. The §4.14.1 "
            f"key sets name specific sub-configs, and substituting another type here would "
            f"change every cache key for that kind."
        )
    return {name: getattr(sub_config, name) for name in fields}


def build_context(
    cfg: AiEngineConfig,
    *,
    registry: Registry,
    job_id: str,
    query_image: np.ndarray,
    query_image_ref: ImageRef,
    landmarks: LandmarkSet,
    windows: WindowSource,
    cache: CacheBackend | None = None,
    intrinsics_hint: CameraIntrinsics | None = None,
    on_progress: ProgressCallback | None = None,
) -> tuple[MatchContext, ResolutionReport]:
    """Resolve every component, assemble the source, and return a ready `MatchContext`.

    ★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``). It raises immediately: every
    component it would resolve is deferred, so there is no `MatchContext` to return. Walking
    the registry first to arrive at the same exception would only make a categorical failure
    look conditional. `preflight()` is where resolution is *reported* — honestly, per
    component, without raising; this is where the refusal happens.

    When re-enabled, the design below is what it must implement.

    **The source-selection table (§4.14.2, normative):**

    ==================  ===========  ================================================
    `cfg.detector_free` `cfg.matcher` `MatchContext.source`
    ==================  ===========  ================================================
    None                set          ``DetectBasedSource(extractor, matcher)``
    set                 set          ``EnsembleSource([DetectBased…, DetectorFree…])``
    set                 None         ``DetectorFreeSource(detector_free)``
    None                None         ``ConfigurationError``
    ==================  ===========  ================================================

    **Resolution order:** EXTRACTOR → MATCHER/DETECTOR_FREE → ESTIMATOR → SEGMENTER →
    SCORER. The `ResolutionReport` is emitted BEFORE any window is fetched, which is what
    lets the worker report degradation at stage `resolving_models` — the instant it is
    known, rather than at the end of a job the user is still waiting for (§11.1).

    **The detector-free source swap.** `loftr` has no registry `fallback`, because §11.1's
    ``loftr → flann`` is a *source* swap and not a chain step — `flann` is a `MATCHER` and
    would not be found in the `DETECTOR_FREE` namespace. So an unresolvable detector-free
    matcher raises `ComponentUnavailable` from the registry, and THIS function catches it,
    warns, and composes a `DetectBasedSource` alone. That is the one fallback the registry
    structurally cannot express, which is why it lives here.

    Args:
        cfg: The engine configuration.
        registry: The registry to resolve against.
        job_id: The job identifier, echoed into the result.
        query_image: `(H,W,3)` uint8 RGB — the surveyor's photograph.
        query_image_ref: The content-addressed handle for `query_image`.
        landmarks: The surveyor's landmarks, in original image pixel space.
        windows: The injected `WindowSource`.
        cache: The feature cache. None composes a `NullCache`.
        intrinsics_hint: Camera intrinsics from EXIF.
        on_progress: The progress callback.

    Returns:
        `(MatchContext, ResolutionReport)` — the ready context and the provenance of every
        component in it.

    Raises:
        NotImplementedDeferred: Always, in this build.
        ConfigurationError: When re-enabled — `matcher` and `detector_free` both None.
        ComponentUnavailable: When re-enabled — a chain exhausted at composition time.
    """
    raise NotImplementedDeferred(
        __name__,
        feature="automatic match pipeline composition (build_context)",
    )
