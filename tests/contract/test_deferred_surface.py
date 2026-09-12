"""★ THE DEFERRED SEAM, seen across the whole repo (SCOPE.md §4).

IU-08's `ai_engine/tests/test_deferred.py` proves each deferred *component* raises. This
file is the **cross-package** view IU-08 cannot take from inside `ai_engine`: that the seam
is real and honest end to end — the exception is distinct, the registries are populated (so
`resolve` never falls off an empty list into a fabricated default), and the whole automatic
surface is present-but-refusing rather than absent-and-404, or worse, absent-and-faking.

SCOPE.md §4, rule 2::

    Deferred bodies raise `NotImplementedDeferred` … Never `pass`, never a silent `None`,
    never fabricated values.

The failure this guards is **silence**. A stub returning `None`, `()`, `0.0` or an empty
`MatchSet` looks exactly like a working component that found nothing, and a surveyor cannot
tell "the engine looked and found nothing" from "the engine was never built" — the first is
a fact about their imagery, the second a fact about this build, and only one of them should
send them to place GCPs by hand.

★ Runs today: it imports `ai_engine` (numpy/cv2/scipy only) and parses `backend` source
with `ast` (no fastapi/pydantic needed for the parts checked here).
"""

from __future__ import annotations

from typing import Any

import pytest

from _astsupport import REPO_ROOT

pytest.importorskip("numpy", reason="the registry sweep constructs real ai_engine specs")


# =============================================================================
# The exception's cross-package contract
# =============================================================================


def test_not_implemented_deferred_is_not_the_builtin() -> None:
    """★ It must NOT subclass builtin `NotImplementedError`.

    `backend.app.api` catches *exactly* this class to answer 501 with `feature: "deferred"`.
    If it subclassed the builtin, a generic `except NotImplementedError` anywhere in the
    stack — the idiom for an unfinished ABC method — would swallow a deferred-feature signal
    and turn an honest 501 into something else. The distinctness is the whole design.
    """
    from ai_engine.errors import AiEngineError, NotImplementedDeferred

    assert issubclass(NotImplementedDeferred, AiEngineError)
    assert not issubclass(NotImplementedDeferred, NotImplementedError)


def test_deferred_exception_points_every_caller_at_the_scope_document() -> None:
    """★ The exception names WHAT is missing and WHERE the ruling is written down.

    A deferred body's job is not only to refuse but to explain — the module that would hold
    the implementation, and the document that says why it does not yet. That is what lets a
    501 be actionable ("place GCPs manually") instead of merely a wall.
    """
    from ai_engine.errors import NotImplementedDeferred

    exc = NotImplementedDeferred("ai_engine.extractors.sift", feature="SIFT extraction")
    assert exc.module == "ai_engine.extractors.sift"
    assert exc.feature == "SIFT extraction"
    assert exc.doc_ref == "docs/architecture/SCOPE.md"
    assert "manual" in str(exc).lower(), "the message must point the surveyor at manual mode"


# =============================================================================
# The registry is populated — so resolution never fabricates
# =============================================================================


def test_the_ai_registry_is_not_empty() -> None:
    """★ An empty registry is the 12-parallel-agent failure mode.

    If `_ensure_registered()` silently registered nothing, every `resolve()` would fall off
    the end of an empty list — and the danger is that some caller then treats "nothing
    resolved" as "use the default", fabricating a component. The seam is only honest while
    the registry actually knows about the things it is deferring.
    """
    from ai_engine.models import REGISTRY

    specs = REGISTRY.specs()
    assert specs, "the ai_engine registry is empty; _ensure_registered() did not run"
    assert len(specs) >= 15, f"only {len(specs)} specs; the deferred surface is under-populated"


def test_every_registered_component_refuses_by_construction() -> None:
    """★★ THE SWEEP, from outside the package. Building ANY spec raises deferred, never junk.

    Parametrised over the *live* registry rather than a hand-written list, so a component
    added later without a deferred body fails here instead of shipping a stub that silently
    returns something. This is the cross-package mirror of IU-08's in-package sweep; both
    must agree, and a divergence means one of them stopped seeing the real registry.

    ★ Even `sift`, `bf` and `opencv` — the classical default path, `L1`'s "tested path" —
    refuse here. SCOPE.md §6 is explicit: in THIS build every deep-model path resolves to
    *deferred*, and so does the classical one, because the classical path is deferred too.
    That is not a bug in `L1`; it is the scope ruling overriding it for this build.
    """
    from ai_engine.errors import NotImplementedDeferred
    from ai_engine.models import REGISTRY

    specs = REGISTRY.specs()
    survivors: list[str] = []
    wrong: list[str] = []

    for spec in specs:
        try:
            instance = spec.factory({})
        except NotImplementedDeferred as exc:
            if not exc.module.startswith("ai_engine."):
                wrong.append(f"{spec.name}: module {exc.module!r} is not under ai_engine")
            if exc.doc_ref != "docs/architecture/SCOPE.md":
                wrong.append(f"{spec.name}: doc_ref {exc.doc_ref!r} is not SCOPE.md")
            if not exc.feature:
                wrong.append(f"{spec.name}: no human-readable feature name")
        except Exception as exc:  # noqa: BLE001 - any other type is itself the finding
            wrong.append(f"{spec.name}: raised {type(exc).__name__} not NotImplementedDeferred")
        else:
            survivors.append(f"{spec.kind} {spec.name!r} -> {instance!r}")

    assert not survivors, (
        "a deferred component CONSTRUCTED instead of refusing — a silent stub is "
        "indistinguishable from a working component that found nothing:\n  "
        + "\n  ".join(survivors)
    )
    assert not wrong, "a deferred refusal was malformed:\n  " + "\n  ".join(wrong)


def test_run_match_job_refuses_without_touching_the_network() -> None:
    """★ `run_match_job` — the one thing a match task calls — refuses immediately.

    It is the outermost deferred surface: a Celery worker calls exactly this. It must raise
    before doing anything, not after a partial run that could leave a half-written result
    behind. `_no_network` (conftest) makes "without touching the network" enforced rather
    than merely intended — a refusal that first dialled a tile server is not a clean refusal.
    """
    from ai_engine.errors import NotImplementedDeferred

    import ai_engine

    with pytest.raises(NotImplementedDeferred) as caught:
        ai_engine.run_match_job(object())  # any argument: it must refuse before inspecting it
    assert caught.value.doc_ref == "docs/architecture/SCOPE.md"
    assert "manual" in str(caught.value).lower()


def test_suggest_landmarks_refuses_once_its_signature_is_satisfied() -> None:
    """★ `suggest_landmarks` refuses too — the automatic-suggestion surface (SCOPE.md §4).

    Unlike `run_match_job` it has a required keyword-only `cfg`, so it validates its
    signature *before* it can reach the deferred body — a `TypeError` for a missing argument
    is Python, not a fabricated result. Once the signature is satisfied it must refuse, and
    with a real config the refusal is what proves the algorithm itself is the thing deferred.
    """
    from ai_engine.config import AiEngineConfig
    from ai_engine.errors import NotImplementedDeferred

    import ai_engine
    import numpy as np

    image = np.zeros((16, 16, 3), dtype=np.uint8)
    with pytest.raises(NotImplementedDeferred) as caught:
        ai_engine.suggest_landmarks(image, cfg=AiEngineConfig())
    assert caught.value.doc_ref == "docs/architecture/SCOPE.md"


# =============================================================================
# The API surface stays present, not 404 (SCOPE.md §4 rule 3)
# =============================================================================


def test_backend_declares_a_501_feature_deferred_error() -> None:
    """★ SCOPE.md §4 rule 3: deferred endpoints return **501**, `feature: "deferred"` — NOT 404.

    404 says "this feature does not exist"; the feature is planned, not absent. The
    difference is the whole re-enabling story (SCOPE.md §7): flipping 501 -> live must be the
    only server change. Asserted by parsing `core/exceptions.py`, since importing it needs
    the backend stack.
    """
    exceptions = REPO_ROOT / "backend" / "app" / "core" / "exceptions.py"
    if not exceptions.is_file():
        pytest.skip("backend/app/core/exceptions.py is not present yet")

    source = exceptions.read_text(encoding="utf-8")
    assert "FEATURE_DEFERRED" in source, "no FEATURE_DEFERRED error code"
    assert "501" in source, "the deferred error must carry status 501, not 404"
    assert '"deferred"' in source, 'the marker value feature: "deferred" is missing'
    assert "SCOPE.md" in source, "the deferred error must point at the scope document"


def test_scope_and_contract_both_exist_and_scope_wins() -> None:
    """★ The two governing documents are present, and SCOPE states its own precedence.

    Every deferred refusal points at SCOPE.md; a dangling pointer would make each 501
    unactionable. And SCOPE.md must actually claim to override the contract — that claim is
    the load-bearing sentence the entire deferred build rests on.
    """
    scope = REPO_ROOT / "docs" / "architecture" / "SCOPE.md"
    contract = REPO_ROOT / "docs" / "architecture" / "CONTRACT.md"
    assert scope.is_file() and contract.is_file()

    scope_text = scope.read_text(encoding="utf-8").lower()
    assert "overrides" in scope_text and "contract.md" in scope_text, (
        "SCOPE.md no longer states that it overrides CONTRACT.md — the precedence every "
        "deferred stub depends on"
    )
    assert "deferred" in scope_text


# =============================================================================
# gis has NO deferred surface — the manual product is fully built
# =============================================================================


def test_gis_never_raises_notimplementeddeferred() -> None:
    """★ The other half of the ruling: everything `gis` owns is BUILT, in full.

    SCOPE.md defers the *matching engine*, which lives entirely in `ai_engine`. `gis` —
    imagery, tiles, CRS, accuracy, exports — is the manual product and is built to first-
    class quality. A `NotImplementedDeferred` anywhere in `gis` would mean a piece of the
    *shipping* product was quietly stubbed under cover of the deferral.

    (`gis` cannot even import the symbol without importing `ai_engine`, which L4 forbids — so
    the string appearing in `gis` source is the whole signal.)
    """
    from _astsupport import scan

    gis_src = REPO_ROOT / "gis" / "src" / "gis"
    hits = scan(gis_src, r"NotImplementedDeferred", flags=0)
    assert not hits, (
        "gis references NotImplementedDeferred, but gis is the fully-built manual product:\n  "
        + "\n  ".join(hits)
    )
