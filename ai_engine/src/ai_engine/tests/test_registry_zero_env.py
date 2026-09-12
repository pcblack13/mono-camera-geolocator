"""★ `preflight()` on an EMPTY ENVIRONMENT returns a report and raises NOTHING (IU-02).

This pins the `LE_AI_ESTIMATOR` boot crash, which is worth restating because the shape of it
recurs: a component registry key and a robust-fit method were given the same name. The env
var defaulted to `usac_magsac` and was routed into `AiEngineConfig.estimator` — but
`usac_magsac` is a `HomographyMethod`, not a registry key, and the only registered estimator
is `opencv`. So with **zero env vars set**, resolving the default against
`ComponentKind.ESTIMATOR` found no spec, found no fallback, exhausted the chain and raised
`ComponentUnavailable` **at preflight**: a boot-time traceback on a fresh clone, violating
L10 (`Settings()` with an empty environment never raises), L11 (never a traceback), and
§9.13's *"`uvicorn app.main:app` with no env → 200"*.

The fix was two names for two concepts (`estimator_backend` vs `ransac.method`). This file
is what stops the class of bug rather than that instance of it: **whatever is wrong with the
environment, preflight returns a report.**

★ IU-02's obligation names `Settings()` with `env={}`. `Settings` is `backend.app.core`
(IU-15) and `ai_engine` may not import it — L10 is a property of `Settings`, and `IU-15`
tests it directly. What `ai_engine` can and must pin is the other half: `AiEngineConfig()`
with every field defaulted is precisely what a zero-env `Settings` produces, and preflight
must survive it. That is what runs here.
"""

from __future__ import annotations

import os
import tempfile

from ai_engine.config import AiEngineConfig
from ai_engine.models import REGISTRY, ComponentKind, Registry
from ai_engine.models.policy import is_deferred
from ai_engine.models.preflight import preflight
from ai_engine.types import ComponentSpec, Device, PreflightReport


def _clear_le_ai_env() -> dict[str, str]:
    """Remove every `LE_AI_*` variable, returning what was removed."""
    removed = {k: v for k, v in os.environ.items() if k.startswith("LE_AI_")}
    for key in removed:
        del os.environ[key]
    return removed


def test_zero_env_preflight_returns_a_report_and_raises_nothing() -> None:
    """★ THE TEST. Default config, no env, no weights dir ⇒ a `PreflightReport`."""
    saved = _clear_le_ai_env()
    try:
        report = preflight(AiEngineConfig())
    finally:
        os.environ.update(saved)

    assert isinstance(report, PreflightReport)
    assert report.checked_at > 0
    assert report.messages, "a preflight report with no messages explains nothing"
    assert isinstance(report.missing_weights, tuple)
    assert report.device_selected in (Device.CPU, Device.CUDA)
    assert report.device_selected is not Device.AUTO, "AUTO must be resolved, not reported"


def test_zero_env_preflight_resolves_every_configured_component() -> None:
    """Every slot the default config names appears in the report."""
    cfg = AiEngineConfig()
    report = preflight(cfg)
    resolved = report.resolutions.resolutions

    for kind in (
        ComponentKind.EXTRACTOR,
        ComponentKind.MATCHER,
        ComponentKind.ESTIMATOR,
        ComponentKind.SEGMENTER,
        ComponentKind.SCORER,
        ComponentKind.SUGGESTER,
    ):
        assert kind in resolved, f"{kind} is configured but absent from the report"

    # detector_free defaults to None: an unconfigured slot, not a missing component.
    assert cfg.detector_free is None
    assert ComponentKind.DETECTOR_FREE not in resolved


def test_zero_env_preflight_reports_the_deferral_truthfully() -> None:
    """★ Every component reports DEFERRED, and the report says so in words.

    And note what it must NOT say. §11.1 specifies the message *"Classical CV pipeline
    (SIFT/ORB + FLANN/BF + RANSAC) is fully operational."* — which is FALSE in this build,
    because the classical path is deferred too. A capabilities report that claims a pipeline
    is operational when it is not is exactly the dishonesty SCOPE §4 rule 3 forbids.
    """
    report = preflight(AiEngineConfig())

    assert report.any_degraded is True
    assert report.resolutions.any_degraded is True
    for kind, res in report.resolutions.resolutions.items():
        assert is_deferred(res), f"{kind} did not report as deferred"

    blob = " ".join(report.messages)
    assert "DEFERRED" in blob or "deferred" in blob
    assert "SCOPE.md" in blob
    assert "manual" in blob.lower()
    assert "fully operational" not in blob.lower(), (
        "the report claims the classical pipeline is operational; it is deferred"
    )


def test_preflight_report_serialises_for_capabilities() -> None:
    """`ResolutionReport.to_dict()` produces wire-ready data with no live objects in it."""
    report = preflight(AiEngineConfig())
    payload = report.resolutions.to_dict()

    assert payload["any_degraded"] is True
    for entry in payload["resolutions"].values():
        assert set(entry) == {"requested", "resolved", "chain", "reason", "degraded", "device"}
        assert "instance" not in entry, "a live object must never reach the wire"


def test_preflight_never_raises_on_an_unresolvable_component() -> None:
    """★ A misconfigured component name is REPORTED, not raised.

    This is the `LE_AI_ESTIMATOR` crash reproduced deliberately: point `estimator_backend` at
    a robust-fit method name, exactly as the deleted env var did. It must produce a report
    naming the problem — not a traceback at boot.
    """
    from dataclasses import replace

    cfg = replace(AiEngineConfig(), estimator_backend="usac_magsac")
    report = preflight(cfg)

    assert isinstance(report, PreflightReport)
    assert report.any_degraded is True
    assert ComponentKind.ESTIMATOR not in report.resolutions.resolutions
    blob = " ".join(report.messages)
    assert "usac_magsac" in blob
    assert "unavailable" in blob or "could not be resolved" in blob


def test_preflight_never_raises_under_strict_models() -> None:
    """Even `strict_models=True` — which raises inside `resolve` — yields a report.

    Strict mode is for CI accuracy suites, and its raise belongs to `resolve`. Preflight's
    contract is to return a report; a boot that dies because a report was strict is a boot
    that lost its own diagnostics.
    """
    from dataclasses import replace

    report = preflight(replace(AiEngineConfig(), strict_models=True))
    assert isinstance(report, PreflightReport)
    assert report.any_degraded is True


def test_preflight_never_raises_on_a_broken_config_builder() -> None:
    """A `component_config` builder that explodes degrades to a report, not a boot failure."""

    def _boom(cfg: AiEngineConfig, kind: ComponentKind) -> dict[str, object]:
        raise RuntimeError("builder is broken")

    report = preflight(AiEngineConfig(), component_config=_boom)
    assert isinstance(report, PreflightReport)
    assert report.any_degraded is True
    assert not report.resolutions.resolutions
    assert any("could not build its component config" in m for m in report.messages)


def test_preflight_reports_a_missing_weights_dir_as_none() -> None:
    """`weights_dir` is None when no directory in the search order exists — the default state."""
    with tempfile.TemporaryDirectory() as tmp:
        from dataclasses import replace
        from pathlib import Path

        ghost = Path(tmp) / "definitely-not-here"
        saved = _clear_le_ai_env()
        try:
            report = preflight(replace(AiEngineConfig(), weights_dir=ghost))
        finally:
            os.environ.update(saved)

    assert report.weights_dir != str(ghost), "a non-existent directory was reported as the home of weights"


def test_preflight_finds_the_weights_dir_when_it_exists() -> None:
    """The positive control for the above: an existing configured dir IS reported."""
    from dataclasses import replace
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        saved = _clear_le_ai_env()
        try:
            report = preflight(replace(AiEngineConfig(), weights_dir=Path(tmp)))
        finally:
            os.environ.update(saved)
        assert report.weights_dir == tmp


def test_preflight_accepts_an_injected_registry() -> None:
    """Preflight resolves against whatever registry it is handed.

    Which is what lets a caller preflight a non-deferred registry — the day the engine is
    re-enabled, and any test that wants to prove the report is not hard-coded.
    """
    registry = Registry()
    for kind, name in (
        (ComponentKind.EXTRACTOR, "sift"),
        (ComponentKind.MATCHER, "flann"),
        (ComponentKind.ESTIMATOR, "opencv"),
        (ComponentKind.SEGMENTER, "classical"),
        (ComponentKind.SCORER, "composite"),
        (ComponentKind.SUGGESTER, "classical_suggester"),
    ):
        registry.register(
            ComponentSpec(
                name=name,
                kind=kind,
                factory=lambda cfg: "live",
                device_preference=Device.CPU,
                is_terminal=True,
            )
        )

    report = preflight(AiEngineConfig(), registry=registry)
    assert report.any_degraded is False, "a fully live registry must not report degraded"
    for res in report.resolutions.resolutions.values():
        assert res.instance == "live"
        assert not is_deferred(res)
    assert not any("DEFERRED" in m for m in report.messages)


def test_the_process_registry_is_untouched_by_the_injected_one() -> None:
    """The injected-registry test above must not have polluted the singleton."""
    assert REGISTRY.get("sift", ComponentKind.EXTRACTOR) is not None
    spec = REGISTRY.get("sift", ComponentKind.EXTRACTOR)
    assert spec is not None
    assert spec.factory.__module__ == "ai_engine.extractors.sift"
