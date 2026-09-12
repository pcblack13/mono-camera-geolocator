"""Boot-time capability reporting — ``preflight(config) -> PreflightReport``.

★ RUNS EXACTLY ONCE, in `main.py`'s lifespan; the report is cached on `app.state` (§11.1).
`GET /api/v1/capabilities` **reads that cache and never re-resolves**: re-running sha256
over a 2.4 GB checkpoint on every request is not a health check, it is an outage.

★ THIS FUNCTION NEVER RAISES. Not "should not" — does not, and it is tested
(`test_registry_zero_env.py`). It is a **report**, and a report that raises has failed at
the one job it has. The rules it exists to keep:

* **L10** — `Settings()` on an empty environment never raises, and the app it configures
  boots. `uvicorn app.main:app` with no env must return 200, and preflight runs in that
  path.
* **L11** — a missing weight, a missing key, an absent GPU or an unavailable dependency is
  a WARNING and a fallback, never a traceback.

So every failure mode a component can have becomes a line in `messages` and a False in a
field, including the ones `resolve_with_fallback` raises for (`ComponentUnavailable` on an
exhausted chain, and `NotImplementedDeferred` under `strict_models`). That is not
swallowing errors: the errors are the *content* of the report. Something that could not be
resolved is reported as unresolved, by name, with the reason — which is strictly more
information than a traceback, and it arrives somewhere an operator can read it.

★ WHAT THIS BUILD REPORTS. Every component is deferred (``docs/architecture/SCOPE.md``),
so `any_degraded` is True and every resolution says so. Note what is deliberately NOT
emitted: §11.1's message *"Classical CV pipeline (SIFT/ORB + FLANN/BF + RANSAC) is fully
operational."* That sentence is false here — the classical path is deferred too — and a
capabilities endpoint that says a pipeline is operational when it is not is the exact
failure mode SCOPE §4 rule 3 forbids. The truthful message is emitted instead.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from ai_engine.errors import AiEngineError
from ai_engine.logging import get_logger
from ai_engine.models import REGISTRY, Registry
from ai_engine.models.device import cuda_available, describe_device, select_device
from ai_engine.models.policy import is_deferred
from ai_engine.models.weights import DEFAULT_MANIFEST, WeightManifest, weight_status
from ai_engine.types.provenance import (
    ComponentKind,
    PreflightReport,
    Resolution,
    ResolutionReport,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    # ★ TYPE_CHECKING, not a runtime import: `ai_engine.config` reaches back into this
    #   package to validate `estimator_backend`, and keeping the annotation static means
    #   the two modules can never race each other at import time.
    from ai_engine.config import AiEngineConfig

__all__ = ["ComponentConfigBuilder", "preflight"]

_log = get_logger(__name__)

#: Builds the per-kind component config mapping. `pipeline.compose.component_config`
#: satisfies it, and §4.14.1 makes its key sets normative.
ComponentConfigBuilder = Callable[["AiEngineConfig", ComponentKind], Mapping[str, Any]]

#: The document that explains what is built in this release, and why.
_SCOPE_DOC = "docs/architecture/SCOPE.md"


def _minimal_component_config(
    config: AiEngineConfig, kind: ComponentKind
) -> Mapping[str, Any]:
    """The fallback config builder used when the caller injects none.

    ★ WHY A MINIMAL MAPPING IS ENOUGH FOR A *REPORT*, AND WHY IT IS NOT ENOUGH FOR A JOB.

    `resolve_with_fallback`'s availability decision is steps 1–4 — spec exists, packages
    importable, weights present and intact, device satisfiable — and **none of those reads
    the component config except `weights_dir`**. Only step 5, actually constructing the
    thing, needs the full normative key set from §4.14.1. So a preflight run with this
    mapping reports availability faithfully.

    The full builder lives at `pipeline.compose.component_config` (IU-08) because it is a
    composition concern, and §10.2 forbids `ai_engine.models` from importing
    `ai_engine.pipeline` — the layer points the other way, and inverting it here would be
    a cycle and an import-linter failure. So the caller injects it: `main.py`'s lifespan
    passes `component_config=compose.component_config` and gets a preflight whose step 5
    is exactly what a real job will do. Without it, this mapping keeps preflight honest
    about availability and merely approximate about construction.
    """
    return {
        "weights_dir": config.weights_dir,
        "device": config.device,
    }


def _components_to_resolve(config: AiEngineConfig) -> tuple[tuple[ComponentKind, str], ...]:
    """The (kind, requested-name) pairs this configuration actually needs.

    `matcher` and `detector_free` are skipped when None — that is not a missing component,
    it is a configuration with one correspondence source instead of two, and the default
    (`detector_free=None`) is exactly that. Reporting an unconfigured slot as unavailable
    would make the default configuration look broken.
    """
    pairs: list[tuple[ComponentKind, str]] = [
        (ComponentKind.EXTRACTOR, config.extractor),
    ]
    if config.matcher is not None:
        pairs.append((ComponentKind.MATCHER, config.matcher))
    if config.detector_free is not None:
        pairs.append((ComponentKind.DETECTOR_FREE, config.detector_free))
    pairs.extend(
        [
            (ComponentKind.ESTIMATOR, config.estimator_backend),
            (ComponentKind.SEGMENTER, config.segmenter),
            (ComponentKind.SCORER, config.scorer),
            (ComponentKind.SUGGESTER, config.suggester),
        ]
    )
    return tuple(pairs)


def _missing_weights(
    registry: Registry,
    config: AiEngineConfig,
    manifest: WeightManifest,
) -> tuple[str, ...]:
    """Every weight key any registered spec wants that is not usable here.

    Computed over the whole registry rather than only over the configured components, on
    purpose: `GET /capabilities` answers "what could this deployment do if you asked?",
    and "you have no SuperGlue weights" is useful before someone requests SuperGlue, not
    after. Corrupt counts as missing, per `weights.py`.
    """
    wanted: set[str] = set()
    for spec in registry.specs():
        wanted.update(spec.requires_weights)

    missing = [
        key
        for key in sorted(wanted)
        if not weight_status(key, weights_dir=config.weights_dir, manifest=manifest).ok
    ]
    return tuple(missing)


def _effective_weights_dir(
    config: AiEngineConfig, manifest: WeightManifest
) -> str | None:
    """The first directory in the search order that actually exists, or None.

    None is a truthful and expected answer: `LE_AI_MODEL_WEIGHTS_DIR` is empty by default
    and no weights directory need exist (§9.8). Reporting the *existing* directory rather
    than merely the *configured* one is what makes the value actionable — an operator who
    mounted a volume at the wrong path sees None here and knows immediately.
    """
    for directory in manifest.search_dirs(config.weights_dir):
        try:
            if directory.is_dir():
                return str(directory)
        except OSError:
            continue
    return None


def preflight(
    config: AiEngineConfig,
    *,
    registry: Registry | None = None,
    component_config: ComponentConfigBuilder | None = None,
    manifest: WeightManifest | None = None,
) -> PreflightReport:
    """Resolve every configured component once and report what this box can actually do.

    ★ NEVER RAISES. See the module docstring: it is a report, and every failure is
    content rather than an exception.

    Args:
        config: The engine configuration to preflight. On a zero-env boot this is
            `AiEngineConfig()` — every field defaulted — and that must work.
        registry: The registry to resolve against. Defaults to the process singleton.
        component_config: Builds the per-kind config mapping passed to each factory.
            Defaults to a minimal mapping; `main.py` should pass
            `ai_engine.pipeline.compose.component_config` so that step 5 of the
            resolution is exactly what a real job performs. See
            :func:`_minimal_component_config` for why the default is sufficient for
            availability reporting and insufficient for construction.
        manifest: The weight manifest to verify against. Defaults to the shipped one.

    Returns:
        A `PreflightReport`. `any_degraded` is INFORMATIONAL and must never gate
        readiness — a box with no weight files is the *supported* configuration, not a
        sick one (§11.1).
    """
    started = time.time()
    reg = registry if registry is not None else REGISTRY
    table = manifest if manifest is not None else DEFAULT_MANIFEST
    build_config = component_config if component_config is not None else _minimal_component_config

    resolutions: dict[ComponentKind, Resolution] = {}
    messages: list[str] = []
    deferred_names: list[str] = []
    unresolved: list[str] = []

    for kind, requested in _components_to_resolve(config):
        try:
            mapping = dict(build_config(config, kind))
        except Exception as exc:  # noqa: BLE001 — a broken builder must not break boot
            messages.append(
                f"{kind} {requested!r}: could not build its component config "
                f"({type(exc).__name__}: {exc}); resolution skipped."
            )
            unresolved.append(f"{kind}:{requested}")
            _log.warning("preflight: component_config failed for %s", kind, exc_info=exc)
            continue

        mapping.setdefault("weights_dir", config.weights_dir)

        try:
            # The manifest is threaded through as a PARAMETER so that policy step 3
            # verifies against the same table `missing_weights` reports on. If it rode in
            # the mapping instead it would be hashed into every cache key — see
            # `models/hashing.py`.
            resolution = reg.resolve(
                requested,
                kind,
                mapping,
                strict=config.strict_models,
                manifest=table,
            )
        except AiEngineError as exc:
            # ComponentUnavailable (chain exhausted, or strict mode refusing to degrade),
            # and NotImplementedDeferred under strict mode. Both are FACTS ABOUT THIS BOX,
            # and the report's job is to state them, not to re-raise them into a lifespan
            # that would then fail to boot on an empty environment.
            messages.append(f"{kind} {requested!r}: unavailable — {exc}")
            unresolved.append(f"{kind}:{requested}")
            _log.warning(
                "preflight: %s %r could not be resolved: %s", kind, requested, exc
            )
            continue
        except Exception as exc:  # noqa: BLE001 — nothing gets to break the boot report
            messages.append(
                f"{kind} {requested!r}: resolution raised an unexpected "
                f"{type(exc).__name__}: {exc}"
            )
            unresolved.append(f"{kind}:{requested}")
            _log.warning(
                "preflight: unexpected error resolving %s %r", kind, requested, exc_info=exc
            )
            continue

        resolutions[kind] = resolution

        if is_deferred(resolution):
            deferred_names.append(f"{kind}:{resolution.resolved}")
            messages.append(
                f"{kind} {requested!r}: resolved to {resolution.resolved!r}, which is "
                f"DEFERRED in this build and has no implementation."
            )
        elif resolution.degraded:
            messages.append(
                f"{kind} {requested!r}: degraded to {resolution.resolved!r} — "
                f"{resolution.reason}"
            )
        else:
            messages.append(f"{kind} {requested!r}: available on {resolution.device}.")

    missing = _missing_weights(reg, config, table)
    weights_dir = _effective_weights_dir(config, table)
    device_selected = select_device(config.device)
    cuda = cuda_available()

    any_degraded = bool(unresolved) or any(r.degraded for r in resolutions.values())

    messages.append(describe_device(config.device))
    if missing:
        messages.append(
            f"{len(missing)} model weight file(s) are absent or unverifiable: "
            f"{list(missing)}. Weights are never downloaded automatically; "
            f"scripts/download_models.py is the only downloader. This is the default, "
            f"supported state of this repository and does not affect readiness."
        )
    else:
        messages.append("Every registered model weight was located and checked.")

    if deferred_names:
        messages.append(
            "The automatic matching engine is DEFERRED in this build: feature "
            "extraction, matching, homography estimation, camera pose, semantics, "
            "scoring, heatmaps and landmark suggestion are registered and typed but not "
            f"implemented ({len(deferred_names)} component(s): {deferred_names}). "
            "LandExplorer ships as a MANUAL GCP surveying tool — the surveyor marks a "
            "landmark in the photograph and clicks the same point on the map, and the "
            "coordinate is recorded as a DIRECT OBSERVATION rather than an inference. "
            f"See {_SCOPE_DOC} for the ruling and the rationale."
        )
    if unresolved:
        messages.append(
            f"{len(unresolved)} configured component(s) could not be resolved at all: "
            f"{unresolved}. They will fail if a job requests them."
        )

    report = PreflightReport(
        resolutions=ResolutionReport(
            resolutions=dict(resolutions),
            any_degraded=any_degraded,
        ),
        weights_dir=weights_dir,
        device_selected=device_selected,
        cuda_available=cuda,
        missing_weights=missing,
        any_degraded=any_degraded,
        checked_at=started,
        messages=tuple(messages),
    )

    _log.info(
        "preflight complete in %.3fs: %d component(s) resolved, %d deferred, "
        "%d unresolved, device=%s, cuda=%s",
        time.time() - started,
        len(resolutions),
        len(deferred_names),
        len(unresolved),
        device_selected,
        cuda,
    )
    return report
