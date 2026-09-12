"""★ THE L1 REGRESSION TEST (IU-02).

L1 says the classical path runs the whole product and deep models are optional accelerants:
*"If every weight file vanished, the only observable change is accuracy and a set of log
lines."* This file is what keeps that true.

★ NOTE WHAT THIS SUITE STILL PROVES IN A BUILD WHERE EVERY COMPONENT IS DEFERRED
(``docs/architecture/SCOPE.md``). The fallback POLICY is fully exercised: `superpoint` still
fails on its missing weights, the chain still walks to `sift`, `chain == ("superpoint",
"sift")` and `degraded is True` exactly as the contract specifies. The only difference is
that the surviving candidate reports *deferred* at construction instead of returning an
instance. That is the seam being load-bearing rather than decorative — the day the engine is
re-enabled, this suite does not change, and neither does any caller.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import tempfile
from pathlib import Path

from ai_engine.errors import ComponentUnavailable, NotImplementedDeferred
from ai_engine.models import BASE_INSTALL_PACKAGES, REGISTRY, ComponentKind, Registry
from ai_engine.models.policy import DeferredComponent, is_deferred, resolve_with_fallback
from ai_engine.models.registration import REGISTRATION_MODULES
from ai_engine.models.weights import WeightManifest, WeightSpec, weight_status
from ai_engine.types import ComponentSpec, Device

# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------


def _empty_dir() -> tempfile.TemporaryDirectory:
    """A directory guaranteed to contain no weight files."""
    return tempfile.TemporaryDirectory(prefix="le-weights-empty-")


# --------------------------------------------------------------------------------------
# ★ registration — the twelve-parallel-agent failure mode
# --------------------------------------------------------------------------------------


def test_registry_is_not_empty() -> None:
    """`Registry.specs()` is non-empty after `_ensure_registered()`.

    The failure this pins: a `@register` decorator only fires when its module is imported.
    With nothing designated to import them, `specs()` would be EMPTY at composition time and
    every resolve would fall through to `ComponentUnavailable` — on a machine where
    everything is installed and nothing is wrong.
    """
    assert REGISTRY.specs(), "the registry is empty: nothing imported the @register sites"
    for kind in ComponentKind:
        assert REGISTRY.specs(kind), f"no components registered for {kind}"


def test_every_registration_module_registers_something() -> None:
    """Each module in `REGISTRATION_MODULES` contributes at least one spec.

    An import that silently stopped registering anything looks exactly like a working one.
    """
    modules = {spec.factory.__module__ for spec in REGISTRY.specs()}
    for name in REGISTRATION_MODULES:
        assert name in modules, f"{name} is imported for registration but registers nothing"


def test_terminal_specs_have_no_requirements() -> None:
    """★ Every terminal spec has no weights and no non-base packages — asserted at registration.

    This is what makes every fallback chain PROVABLY terminate at something that always
    constructs. Without it, "the chain ends somewhere safe" is a hope.
    """
    terminal = [s for s in REGISTRY.specs() if s.is_terminal]
    assert terminal, "no terminal specs at all: no chain could provably terminate"
    for spec in terminal:
        assert spec.fallback is None, f"terminal {spec.name!r} declares a fallback"
        assert not spec.requires_weights, f"terminal {spec.name!r} requires weights"
        assert not set(spec.requires_packages) - BASE_INSTALL_PACKAGES, (
            f"terminal {spec.name!r} requires non-base packages"
        )


def test_registration_rejects_a_bad_terminal_spec() -> None:
    """Registering a terminal spec that needs weights raises at registration time."""
    registry = Registry()
    bad = ComponentSpec(
        name="liar",
        kind=ComponentKind.EXTRACTOR,
        factory=lambda cfg: object(),
        requires_weights=("superpoint_v1",),
        is_terminal=True,
    )
    try:
        registry.register(bad)
    except ValueError as exc:
        assert "terminal" in str(exc)
    else:  # pragma: no cover - the assertion below is the point
        raise AssertionError("a terminal spec requiring weights was accepted")


def test_every_chain_terminates() -> None:
    """Following `fallback` from any spec reaches a terminal one, or a deliberate dead end.

    `ComponentKind.DETECTOR_FREE` is the deliberate exception: it has NO terminal member,
    because there is no classical detector-free matcher. `pipeline.compose` swaps the
    correspondence source instead of walking a chain (§11.1's "loftr → flann (via source
    swap)"), so `loftr` legitimately ends nowhere.
    """
    for spec in REGISTRY.specs():
        seen: list[str] = []
        cur: ComponentSpec | None = spec
        while cur is not None:
            assert cur.name not in seen, f"fallback cycle from {spec.name!r}: {seen}"
            seen.append(cur.name)
            if cur.is_terminal:
                break
            if cur.fallback is None:
                assert cur.kind is ComponentKind.DETECTOR_FREE, (
                    f"{cur.kind} {cur.name!r} has no fallback and is not terminal; only "
                    f"DETECTOR_FREE may do that (it has no classical member)"
                )
                break
            cur = REGISTRY.get(cur.fallback, cur.kind)
            assert cur is not None, f"{spec.name!r} falls back to a name that is not registered"


# --------------------------------------------------------------------------------------
# ★ THE L1 REGRESSION TEST
# --------------------------------------------------------------------------------------


def test_missing_weights_fall_back_to_sift(caplog: object = None) -> None:
    """★ Empty weights dir ⇒ superpoint resolves to sift, chain and all, degraded=True."""
    with _empty_dir() as empty:
        res = REGISTRY.resolve("superpoint", ComponentKind.EXTRACTOR, {"weights_dir": empty})

    assert res.requested == "superpoint"
    assert res.resolved == "sift"
    assert res.chain == ("superpoint", "sift")
    assert res.degraded is True
    # ★ Environment-dependent honest reason: on the authoring box torch imports and the
    #   empty dir yields "weights missing"; in a plain venv torch itself is invisible and
    #   the (earlier) probe honestly says "missing package". Same policy, same fallback,
    #   same loudness — the cause string is not the contract.
    assert res.reason and ("weights missing" in res.reason or "missing package" in res.reason)
    # In this build the terminal candidate is deferred rather than constructed. The POLICY
    # is unchanged and fully exercised above; only construction differs.
    assert is_deferred(res)


def test_fallback_emits_a_warning_event() -> None:
    """★ A fallback is NEVER SILENT — it emits ComponentFallback at WARNING.

    A user who configured SuperPoint and got SIFT has exactly one channel through which to
    discover it. This is that channel.
    """
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Capture()
    logger = logging.getLogger("ai_engine.models.policy")
    logger.addHandler(handler)
    previous = logger.level
    logger.setLevel(logging.WARNING)
    try:
        with _empty_dir() as empty:
            REGISTRY.resolve("superpoint", ComponentKind.EXTRACTOR, {"weights_dir": empty})
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)

    events = [r for r in records if getattr(r, "event", None) == "ComponentFallback"]
    assert events, "no ComponentFallback event was emitted"
    event = events[0]
    assert event.levelno == logging.WARNING
    assert event.requested == "superpoint"  # type: ignore[attr-defined]
    assert event.candidate == "superpoint"  # type: ignore[attr-defined]
    reason: str = event.reason  # type: ignore[attr-defined]
    # Same environment-dependent pair as test_missing_weights_fall_back_to_sift above.
    assert "weights missing" in reason or "missing package" in reason


def test_truncated_weight_resolves_exactly_like_a_missing_one() -> None:
    """★ A file with the right name and the wrong sha256 is treated as MISSING.

    A half-downloaded checkpoint that loads and then emits garbage is far worse than one
    that is simply absent: the absent one degrades loudly, the corrupt one produces
    confident nonsense.
    """
    manifest = WeightManifest(
        {
            "superpoint_v1": WeightSpec(
                key="superpoint_v1",
                filename="superpoint_v1.pth",
                sha256="00" * 32,  # deliberately not the digest of anything we write
            )
        }
    )

    with tempfile.TemporaryDirectory(prefix="le-weights-trunc-") as tmp:
        path = Path(tmp) / "superpoint_v1.pth"
        path.write_bytes(b"truncated garbage, right name, wrong content")

        status = weight_status("superpoint_v1", weights_dir=tmp, manifest=manifest)
        assert status.ok is False
        assert status.reason and "corrupt" in status.reason
        assert status.path == path  # it WAS found; it is simply not usable

        corrupt = resolve_with_fallback(
            REGISTRY,
            "superpoint",
            ComponentKind.EXTRACTOR,
            {"weights_dir": tmp},
            manifest=manifest,
        )

    with _empty_dir() as empty:
        missing = resolve_with_fallback(
            REGISTRY,
            "superpoint",
            ComponentKind.EXTRACTOR,
            {"weights_dir": empty},
            manifest=manifest,
        )

    assert corrupt.resolved == missing.resolved == "sift"
    assert corrupt.chain == missing.chain == ("superpoint", "sift")
    assert corrupt.degraded == missing.degraded is True


def test_valid_weight_passes_verification() -> None:
    """The positive control: a file whose digest matches is accepted and marked verified.

    Without this, `test_truncated_...` would pass just as happily against a checker that
    rejected everything.
    """
    import hashlib

    payload = b"pretend this is a checkpoint"
    digest = hashlib.sha256(payload).hexdigest()
    manifest = WeightManifest(
        {"k": WeightSpec(key="k", filename="k.pth", sha256=digest, size_bytes=len(payload))}
    )
    with tempfile.TemporaryDirectory(prefix="le-weights-ok-") as tmp:
        (Path(tmp) / "k.pth").write_bytes(payload)
        status = weight_status("k", weights_dir=tmp, manifest=manifest)
    assert status.ok is True
    assert status.verified is True
    assert status.reason is None


def test_find_spec_is_used_not_import() -> None:
    """★ Resolution probes with `find_spec` and never imports torch.

    Run in a FRESH interpreter, because any earlier test that touched torch would make a
    `sys.modules` probe in this process meaningless — and the assertion would then pass for
    the wrong reason, forever.
    """
    script = (
        "import sys, tempfile\n"
        "from ai_engine.models import REGISTRY, ComponentKind\n"
        "with tempfile.TemporaryDirectory() as d:\n"
        "    r = REGISTRY.resolve('superpoint', ComponentKind.EXTRACTOR, {'weights_dir': d})\n"
        "assert r.resolved == 'sift', r.resolved\n"
        "assert 'torch' not in sys.modules, 'torch was IMPORTED during resolution'\n"
        "print('ok')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    assert proc.returncode == 0, f"probe failed:\n{proc.stdout}\n{proc.stderr}"


def test_cuda_request_routes_through_the_same_fallback_branch() -> None:
    """★ `Device.CUDA` + no GPU falls back exactly like a missing weight does.

    Device unavailability is the SAME failure class as a missing weight (§11.2) and must not
    grow its own private code path.
    """
    registry = Registry()
    registry.register(
        ComponentSpec(
            name="gpu_only",
            kind=ComponentKind.EXTRACTOR,
            factory=lambda cfg: object(),
            device_preference=Device.CUDA,
            fallback="cpu_ok",
        )
    )
    registry.register(
        ComponentSpec(
            name="cpu_ok",
            kind=ComponentKind.EXTRACTOR,
            factory=lambda cfg: "constructed",
            device_preference=Device.CPU,
            is_terminal=True,
        )
    )

    from ai_engine.models.device import cuda_available

    res = resolve_with_fallback(registry, "gpu_only", ComponentKind.EXTRACTOR, {})
    if cuda_available():  # pragma: no cover - not the verified box
        assert res.resolved == "gpu_only"
        return
    assert res.resolved == "cpu_ok"
    assert res.chain == ("gpu_only", "cpu_ok")
    assert res.degraded is True
    assert res.reason and "device unavailable" in res.reason
    assert res.device is Device.CPU
    assert res.instance == "constructed"


def test_cycle_detection_terminates() -> None:
    """A fallback cycle raises `ComponentUnavailable` rather than looping forever."""
    registry = Registry()
    registry.register(
        ComponentSpec(
            name="a",
            kind=ComponentKind.EXTRACTOR,
            factory=_always_fails,
            fallback="b",
        )
    )
    registry.register(
        ComponentSpec(
            name="b",
            kind=ComponentKind.EXTRACTOR,
            factory=_always_fails,
            fallback="a",
        )
    )
    try:
        resolve_with_fallback(registry, "a", ComponentKind.EXTRACTOR, {})
    except ComponentUnavailable as exc:
        assert "cycle" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("a fallback cycle did not raise")


def test_chain_limit_caps_depth() -> None:
    """`chain_limit` bounds the walk even without a cycle."""
    registry = Registry()
    for i in range(8):
        registry.register(
            ComponentSpec(
                name=f"n{i}",
                kind=ComponentKind.EXTRACTOR,
                factory=_always_fails,
                fallback=f"n{i + 1}",
            )
        )
    try:
        resolve_with_fallback(registry, "n0", ComponentKind.EXTRACTOR, {}, chain_limit=3)
    except ComponentUnavailable as exc:
        assert "chain limit" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("chain_limit did not bound the walk")


def test_unknown_name_raises_component_unavailable() -> None:
    """An unregistered name exhausts immediately — there is no fallback to follow."""
    try:
        REGISTRY.resolve("does_not_exist", ComponentKind.EXTRACTOR, {})
    except ComponentUnavailable as exc:
        assert "does_not_exist" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("an unknown component name did not raise")


def test_strict_mode_raises_instead_of_falling_back() -> None:
    """★ `strict=True` refuses to degrade. True in production violates L1."""
    with _empty_dir() as empty:
        try:
            REGISTRY.resolve(
                "superpoint",
                ComponentKind.EXTRACTOR,
                {"weights_dir": empty},
                strict=True,
            )
        except ComponentUnavailable as exc:
            assert "strict" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("strict mode fell back instead of raising")


def test_strict_mode_surfaces_deferral_as_deferral() -> None:
    """Under strict mode a deferred component raises `NotImplementedDeferred`, not a vague error.

    The distinction is the point: "the chain ran out" and "this is not built yet" are
    different facts, and strict mode is precisely the mode that asked to be told the truth
    loudly.
    """
    try:
        REGISTRY.resolve("sift", ComponentKind.EXTRACTOR, {}, strict=True)
    except NotImplementedDeferred as exc:
        assert exc.module == "ai_engine.extractors.sift"
        assert exc.doc_ref == "docs/architecture/SCOPE.md"
    else:  # pragma: no cover
        raise AssertionError("strict mode did not surface the deferral")


def test_deferred_resolution_reports_honestly() -> None:
    """A deferred resolution names the module and hands back a raising sentinel, never None."""
    res = REGISTRY.resolve("sift", ComponentKind.EXTRACTOR, {})
    assert is_deferred(res)
    assert res.instance is not None, "a deferred instance must never be a silent None"
    assert isinstance(res.instance, DeferredComponent)
    assert res.instance.module == "ai_engine.extractors.sift"
    assert res.degraded is True
    assert res.reason and "deferred" in res.reason

    try:
        res.instance.extract(None)
    except NotImplementedDeferred as exc:
        assert "SCOPE.md" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("the deferred sentinel did not raise on use")


def _always_fails(config: object) -> object:
    """A factory that always raises — for the cycle and chain-limit fixtures."""
    raise RuntimeError("this factory always fails")
