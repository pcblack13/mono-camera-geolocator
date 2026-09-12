"""★ THE ONLY PLACE FALLBACK POLICY EXISTS.

Every "what do we do when X is unavailable?" decision in `ai_engine` is made by
:func:`resolve_with_fallback` and nowhere else. That centralisation *is* L1 and L11: if
the policy lived at each call site, "a missing weight is a warning and a fallback" would
be nine slightly different opinions, and the one that mattered would be the one nobody
tested.

★ WHAT THIS BUILD RESOLVES TO, AND WHY THE CODE BELOW LOOKS LIKE IT DOES
------------------------------------------------------------------------
The automatic matching engine is DEFERRED (``docs/architecture/SCOPE.md``). So in this
build **every** component path — deep *and* classical — resolves to *deferred*: there is
no classical fallback, because the classical path is deferred too. The scope ruling
requires that this be expressed **without special-casing callers**, and this module does
it with one idea:

    **Resolution REPORTS. Construction RAISES.**

The walk below is the real, complete fallback policy, unchanged from what a fully
implemented engine needs. It probes packages, verifies checksums and checks devices
exactly as specified, and falls back exactly as specified. The *only* thing that differs
today is what happens at step 5: `spec.factory(config)` raises
:class:`~ai_engine.errors.NotImplementedDeferred`, and this module recognises that
exception as a **terminal, honest outcome** rather than as one more reason to fall back.

That distinction is the whole design, so it is worth stating why the two obvious
alternatives are wrong:

* **Catching it as a generic construction failure** (`except Exception` at step 5) would
  make every chain fall through to exhaustion and raise `ComponentUnavailable` at
  preflight — a traceback on an empty environment, violating L10 and L11, and reporting
  "fallback chain exhausted" when the truth is "not built yet". A wrong diagnosis is
  worse than no diagnosis.
* **Special-casing deferred names in the registry** (a "skip these" list) would mean the
  fallback policy is not exercised at all in this build, so the day the engine is
  re-enabled would be the day the policy first runs. The seam has to be load-bearing now
  or it is decoration (SCOPE §4 rule 1).

Instead, the chain walks for real — ``superpoint`` still fails on its missing weights and
still falls back to ``sift``, and `test_registry_fallback.py` still asserts exactly that,
including `chain=("superpoint","sift")` and `degraded=True`. It is only at the end, when
the surviving candidate is asked to *construct*, that this build says "deferred". Re-enabling
the engine means deleting a `raise` from a factory. Nothing here changes, and no caller
changes (SCOPE §7).

`Resolution.instance` then holds a :class:`DeferredComponent` rather than ``None``, for a
reason that is not cosmetic: a caller who ignores the report and uses the instance gets
`NotImplementedDeferred` naming the module it needs, instead of
``AttributeError: 'NoneType' object has no attribute 'extract'``. Never a silent ``None``
(SCOPE §4 rule 2).
"""

from __future__ import annotations

from collections.abc import Mapping
from importlib.util import find_spec
from typing import TYPE_CHECKING, Any, NoReturn

from ai_engine.errors import ComponentUnavailable, NotImplementedDeferred
from ai_engine.logging import get_logger
from ai_engine.models.device import device_is_satisfiable, select_device
from ai_engine.models.weights import WeightManifest, weight_status
from ai_engine.types.provenance import ComponentKind, ComponentSpec, Resolution

if TYPE_CHECKING:  # pragma: no cover - typing only
    # ★ Import-cycle avoidance, and it is real rather than defensive: `ai_engine.models`
    #   imports this module at package-init time, so a runtime import of `Registry` here
    #   would be a hard cycle. The contract's own signature writes `registry: "Registry"`
    #   as a string for exactly this reason.
    from ai_engine.models import Registry

__all__ = [
    "DeferredComponent",
    "DeferredImplementation",
    "is_deferred",
    "resolve_with_fallback",
]

_log = get_logger(__name__)


class DeferredImplementation:
    """Mixin for a concrete backend that is **registered and typed but not built**.

    Every deferred class in `ai_engine` mixes this in, ahead of its ABC, and gets one
    behaviour: constructing it raises :class:`~ai_engine.errors.NotImplementedDeferred`
    naming the module and the feature. Its abstract methods are still written out in full,
    with their real signatures — see the note below on why that is not redundant.

    ::

        class SiftExtractor(DeferredImplementation, FeatureExtractor):
            deferred_module = __name__
            deferred_feature = "SIFT feature extraction"

    ★ THE ABSTRACT METHODS MUST STILL BE DEFINED ON EACH SUBCLASS, and the reason is
    mechanical rather than stylistic: `ABCMeta` refuses to instantiate a class with
    unimplemented abstract methods, and it refuses **before** `__init__` runs. A stub that
    left them out would raise ``TypeError: Can't instantiate abstract class
    SiftExtractor`` — an error about Python, not about this product — instead of the
    `NotImplementedDeferred` that carries the module, the feature and a pointer to
    `docs/architecture/SCOPE.md`, and that the API layer turns into a `501` with a
    ``feature: "deferred"`` marker. Writing them out also keeps the signatures honest and
    reviewable: they are the contract that makes re-enabling the engine a zero-caller-change
    operation, and a signature nobody wrote down is a signature that will not match.

    Attributes:
        deferred_module: The dotted module path of the deferred implementation. Set it to
            `__name__` at the class body.
        deferred_feature: A human-readable name for the capability, e.g. ``"SIFT feature
            extraction"``. It reaches the operator in a log line and the surveyor in a
            501 envelope, so write it for them.
    """

    #: The dotted path of the module that will hold the implementation.
    deferred_module: str = __name__
    #: What the thing does, in words a surveyor would recognise.
    deferred_feature: str = "this component"

    def __init__(self, config: Mapping[str, Any]) -> None:
        """Raise. A deferred component cannot be constructed.

        ★ Construction is the failure point ON PURPOSE. `resolve_with_fallback` runs its
        entire chain — packages, checksums, devices, fallbacks — and only discovers the
        deferral at step 5. That is what keeps the policy exercised and the report honest:
        the registry can truthfully say *"you asked for superpoint, its weights are
        missing, policy fell back to sift, and sift is not implemented in this build"*,
        which is three true facts rather than one vague one.

        Args:
            config: The component config mapping. Accepted and ignored — the signature is
                part of the seam (`ComponentSpec.factory` is
                ``Callable[[Mapping[str, Any]], Any]``), and it must stay right so that
                the implementation can drop in without touching the registry.

        Raises:
            NotImplementedDeferred: Always.
        """
        self._deferred()

    def _deferred(self) -> NoReturn:
        """Raise `NotImplementedDeferred` for this class. The only body a stub may have.

        Never `pass`, never a bare `None`, never a fabricated keypoint, score, homography
        or confidence. A silent no-op is indistinguishable from success, and a plausible
        wrong coordinate handed to a surveyor is this system's worst failure mode (L12).
        """
        raise NotImplementedDeferred(self.deferred_module, feature=self.deferred_feature)


class DeferredComponent:
    """A stand-in for a component whose implementation is deferred in this build.

    ★ THIS IS NOT A MOCK AND NOT A NULL OBJECT. It implements nothing and pretends
    nothing. Its single behaviour is to raise
    :class:`~ai_engine.errors.NotImplementedDeferred` — naming the module that would have
    implemented it — on **any** attempt to use it.

    It exists because the alternative is `Resolution.instance = None`, and a `None` there
    is a trap: the caller who fails to read `Resolution.reason` learns about it as
    ``AttributeError: 'NoneType' object has no attribute 'extract'`` — an error that
    names neither the component nor the reason nor the document explaining the ruling.
    This object turns that same mistake into the exact exception the API layer already
    translates into `501 {feature: "deferred"}`.

    It is also what keeps `Resolution` honest for `GET /capabilities`: the component
    genuinely was *resolved* — the registry knows its name, its kind, its weights and its
    fallback chain — it simply cannot be *constructed*. Reporting that as "resolved to
    sift, deferred" is true. Reporting it as "unavailable" would not be.

    Attributes:
        module: The dotted path of the deferred implementation, e.g.
            ``"ai_engine.extractors.sift"``. Carried into every exception it raises.
        feature: A human-readable name for what is missing, e.g. ``"SIFT feature
            extraction"``.
        name: The registry name that resolved to this, e.g. ``"sift"``.
        kind: The `ComponentKind` slot it was resolving for.
    """

    __slots__ = ("_feature", "_kind", "_module", "_name")

    def __init__(
        self,
        *,
        module: str,
        feature: str,
        name: str,
        kind: ComponentKind,
    ) -> None:
        object.__setattr__(self, "_module", module)
        object.__setattr__(self, "_feature", feature)
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_kind", kind)

    @property
    def module(self) -> str:
        """The dotted module path of the deferred implementation."""
        return self._module

    @property
    def feature(self) -> str:
        """A human-readable name for the deferred capability."""
        return self._feature

    @property
    def name(self) -> str:
        """The registry name this stands in for."""
        return self._name

    @property
    def kind(self) -> ComponentKind:
        """The component slot this stands in for."""
        return self._kind

    def _raise(self) -> NoReturn:
        raise NotImplementedDeferred(self._module, feature=self._feature)

    def __getattr__(self, item: str) -> NoReturn:
        """Any attribute access raises `NotImplementedDeferred`.

        Dunder lookups are excluded and raise `AttributeError` instead: Python probes for
        `__deepcopy__`, `__getstate__`, `__iter__` and friends speculatively, and a
        `NotImplementedDeferred` escaping from `copy.copy()` or a `repr()` would be an
        error about the wrong thing entirely.

        Note that `__slots__` means the real attributes resolve through the normal
        descriptor path and never reach here, so there is no recursion.
        """
        if item.startswith("__") and item.endswith("__"):
            raise AttributeError(item)
        self._raise()

    def __call__(self, *args: object, **kwargs: object) -> NoReturn:
        """Calling it raises, for the caller who treats it as a factory."""
        self._raise()

    def __repr__(self) -> str:
        return (
            f"<DeferredComponent {self._kind}:{self._name} "
            f"module={self._module!r} — not implemented in this build; "
            f"see docs/architecture/SCOPE.md>"
        )


def is_deferred(resolution: Resolution) -> bool:
    """True when `resolution` resolved to a component that is deferred in this build.

    ★ Ask with THIS, never by string-matching `Resolution.reason`. The reason is prose
    written for a human in a log line; this is the structural fact. `preflight()` and
    `GET /capabilities` both branch on it.
    """
    return isinstance(resolution.instance, DeferredComponent)


def _describe(kind: ComponentKind, name: str) -> str:
    """A short label for logs and reasons, e.g. ``extractor 'superpoint'``."""
    return f"{kind} {name!r}"


def _emit_fallback_event(
    *,
    requested: str,
    candidate: str,
    kind: ComponentKind,
    reason: str,
    exc_type: str | None,
) -> None:
    """Emit the `ComponentFallback` event at WARNING. **Never silent** (§4.14, §11.8).

    ★ This is a WARNING and it must stay one. A user who configured SuperPoint and
    silently got SIFT has exactly one channel through which to discover it, and this is
    it. Do not lower it to DEBUG "to clean up the logs".

    ★ WHY A LOG RECORD RATHER THAN THE `runtime.events.ComponentFallback` DATACLASS:
      §10.2 confines `ai_engine.models` to stdlib + `ai_engine.{types,errors}`, and
      `ai_engine.runtime` sits above it — importing the dataclass here would invert the
      layer and cycle the build order. The four fields §4.14 names (`requested`,
      `candidate`, `reason`, `exc_type`) are carried structurally in `extra` for any
      structured-logging handler that wants them, and the pipeline re-emits the typed
      event from the `ResolutionReport` where it also has the `job_id` and `stage` that
      §11.8's table requires and that this layer cannot know.
    """
    _log.warning(
        "ComponentFallback: %s was requested; candidate %r is unavailable (%s). "
        "Falling back.",
        _describe(kind, requested),
        candidate,
        reason,
        extra={
            "event": "ComponentFallback",
            "component_kind": str(kind),
            "requested": requested,
            "candidate": candidate,
            "reason": reason,
            "exc_type": exc_type,
        },
    )


def _check_packages(spec: ComponentSpec) -> str | None:
    """Step 2: are `spec.requires_packages` importable? Returns a reason, or None if ok.

    ★ `find_spec`, NOT `import`. Probing must have no module side effects, must not
    initialise CUDA, and must not pay a multi-second torch import just to discover that
    the weights are missing anyway and we will not be using it.
    `test_registry_fallback.py` pins this with a `sys.modules` probe.
    """
    for package in spec.requires_packages:
        try:
            found = find_spec(package) is not None
        except (ImportError, ValueError):
            # ValueError: present in sys.modules with no __spec__ — what a test sentinel
            # looks like. ImportError: a parent package that will not import. Both mean
            # "cannot be relied on", which is the same answer as absent.
            found = False
        if not found:
            return f"missing package: {package!r} is not importable"
    return None


def _check_weights(
    spec: ComponentSpec,
    weights_dir: Any,
    manifest: WeightManifest | None,
) -> str | None:
    """Step 3: are `spec.requires_weights` present and intact? Reason, or None if ok.

    A corrupt or truncated file is reported exactly like an absent one — see
    `weights.py`, where that collapse is argued.
    """
    for key in spec.requires_weights:
        status = weight_status(key, weights_dir=weights_dir, manifest=manifest)
        if not status.ok:
            return status.reason or f"weights unavailable: {key!r}"
    return None


def _check_device(spec: ComponentSpec) -> str | None:
    """Step 4: can `spec.device_preference` be honoured? Reason, or None if ok.

    ★ Device unavailability is the SAME failure class as a missing weight and routes
    through this same walk (§11.2). On the verified box this is the branch that fires.
    `AUTO` and `CPU` never probe torch, which is what keeps the classical chain free of a
    torch import.
    """
    ok, reason = device_is_satisfiable(spec.device_preference)
    return None if ok else reason


def resolve_with_fallback(
    registry: Registry,
    name: str,
    kind: ComponentKind,
    config: Mapping[str, Any],
    *,
    strict: bool = False,
    chain_limit: int = 4,
    manifest: WeightManifest | None = None,
) -> Resolution:
    """Walk ``name -> spec.fallback -> ...`` until something constructs, and report it.

    For each candidate, **in order — cheapest and least side-effecting first**:

    1. a spec exists in the registry for ``(candidate, kind)``      → else next
    2. every ``requires_packages`` is importable via `find_spec`    → else next
    3. every ``requires_weights`` resolves AND its checksum matches → else next
    4. ``device_preference`` is satisfiable                         → else next
    5. ``spec.factory(config)`` constructs                          → else next

    Every fall-through emits a `ComponentFallback` event at WARNING (§4.14). It is never
    silent: a user who configured SuperPoint and got SIFT must be able to find out.

    Termination is structural, not hopeful. A `visited` set breaks cycles, `chain_limit`
    caps depth, and terminal specs (`is_terminal=True`) are asserted at registration to
    have no weights, no extra packages and no fallback — so a chain that reaches one
    provably ends at something that always constructs. `ComponentKind.DETECTOR_FREE` has
    no terminal member **on purpose**: there is no classical detector-free matcher, so an
    unresolvable one raises and `pipeline.compose` swaps the correspondence source
    instead (§11.1's "loftr → flann (via source swap)").

    ★ STEP 5 AND THE DEFERRED BUILD. When the factory raises
    :class:`~ai_engine.errors.NotImplementedDeferred`, that is **not** a construction
    failure to fall back from — it is a terminal, honest answer: the component exists, is
    registered, and is not built yet (``docs/architecture/SCOPE.md``). The walk stops and
    returns a `Resolution` whose `instance` is a :class:`DeferredComponent`, whose
    `reason` says so, and whose `degraded` is True. Falling back here would be a lie: it
    would report "superpoint fell back to sift" as though sift were about to do the work.
    See this module's docstring for the full argument.

    Args:
        registry: The registry to resolve against.
        name: The requested component name, e.g. ``"superpoint"``.
        kind: The slot being filled.
        config: The component config mapping (`pipeline.compose.component_config`).
            Passed verbatim to the factory; also read for `weights_dir`.
        strict: `LE_AI_STRICT_BACKEND`. When True, refuse to degrade — raise instead.
            **True in production violates L1.** It exists for CI accuracy suites on a GPU
            box, where a silent degradation would leave the deep path untested while the
            suite went green.
        chain_limit: Maximum chain depth. A guard, not a tuning knob.
        manifest: The weight table step 3 verifies against. Defaults to the shipped one.
            ★ It is a PARAMETER rather than a key in `config`, and that is not a
            preference: `config` is hashed by `params_hash()` to produce a **cache key**
            (§4.14.1), and a `WeightManifest` object has no stable string form — folding
            one in would salt every cache key with an object address, so identical
            configurations would miss the cache forever and, worse, two workers would
            disagree about the key for identical work.

    Returns:
        A `Resolution` recording what was asked for, what was actually produced, the
        chain walked, why it degraded, and on which device.

    Raises:
        ComponentUnavailable: The chain was exhausted without anything constructing —
            raised at COMPOSITION time (preflight), never mid-request. Also raised for
            every fall-through when `strict=True`.
        NotImplementedDeferred: `strict=True` and the resolved component is deferred.
            Deliberately more specific than `ComponentUnavailable`: under strict mode the
            caller asked to be told the truth loudly, and "not built in this build" is a
            different fact from "the chain ran out".
    """
    weights_dir = config.get("weights_dir")

    visited: set[str] = set()
    chain: list[str] = []
    reasons: list[str] = []
    first_reason: str | None = None

    candidate: str | None = name
    while candidate is not None:
        if candidate in visited:
            reason = (
                f"fallback cycle: {candidate!r} is already in the chain "
                f"{tuple(chain)!r}. Refusing to loop."
            )
            reasons.append(reason)
            break
        visited.add(candidate)
        chain.append(candidate)

        if len(chain) > chain_limit:
            reasons.append(
                f"chain limit of {chain_limit} exceeded at {candidate!r}; chain so far "
                f"{tuple(chain)!r}"
            )
            break

        spec = registry.get(candidate, kind)
        if spec is None:
            known = sorted(s.name for s in registry.specs(kind))
            reason = (
                f"no {kind} is registered under {candidate!r}; registered: {known}"
            )
            _reject(
                requested=name,
                candidate=candidate,
                kind=kind,
                reason=reason,
                exc_type=None,
                strict=strict,
                reasons=reasons,
            )
            first_reason = first_reason or reason
            # Without a spec there is no `fallback` to follow. The chain ends here.
            break

        reason = (
            _check_packages(spec)
            or _check_weights(spec, weights_dir, manifest)
            or _check_device(spec)
        )
        if reason is not None:
            _reject(
                requested=name,
                candidate=candidate,
                kind=kind,
                reason=reason,
                exc_type=None,
                strict=strict,
                reasons=reasons,
            )
            first_reason = first_reason or reason
            candidate = spec.fallback
            continue

        device = select_device(spec.device_preference)

        try:
            instance = spec.factory(config)
        except NotImplementedDeferred as exc:
            # ★ NOT a fallback trigger. A terminal, honest outcome — see the docstring.
            if strict:
                raise
            deferred_reason = (
                f"deferred: {_describe(kind, candidate)} is registered but not "
                f"implemented in this build ({exc.module}); see {exc.doc_ref}"
            )
            if first_reason is not None:
                deferred_reason = f"{first_reason}; then {deferred_reason}"
            _log.warning(
                "%s resolved to %r, which is DEFERRED in this build: %s. The automatic "
                "matching engine is not enabled — GCPs are placed manually.",
                _describe(kind, name),
                candidate,
                exc.module,
                extra={
                    # ★ NOT "module": `logging.LogRecord` already has one, and passing it
                    #   via `extra` raises KeyError("Attempt to overwrite 'module' in
                    #   LogRecord") from inside the logging call — which would have made
                    #   EVERY deferred resolution explode, i.e. every resolution in this
                    #   build. The reserved names are the LogRecord attributes: `module`,
                    #   `name`, `filename`, `lineno`, `args`, `msg`, `levelname`, ...
                    "event": "ComponentDeferred",
                    "component_kind": str(kind),
                    "requested": name,
                    "resolved": candidate,
                    "deferred_module": exc.module,
                    "doc_ref": exc.doc_ref,
                },
            )
            return Resolution(
                requested=name,
                resolved=candidate,
                instance=DeferredComponent(
                    module=exc.module,
                    feature=exc.feature or f"{kind} {candidate!r}",
                    name=candidate,
                    kind=kind,
                ),
                chain=tuple(chain),
                reason=deferred_reason,
                degraded=True,
                device=device,
            )
        except Exception as exc:  # noqa: BLE001 — any construction failure is a fallback
            reason = f"construction failed: {type(exc).__name__}: {exc}"
            _reject(
                requested=name,
                candidate=candidate,
                kind=kind,
                reason=reason,
                exc_type=type(exc).__name__,
                strict=strict,
                reasons=reasons,
                exc=exc,
            )
            first_reason = first_reason or reason
            candidate = spec.fallback
            continue

        degraded = candidate != name
        return Resolution(
            requested=name,
            resolved=candidate,
            instance=instance,
            chain=tuple(chain),
            reason=first_reason if degraded else None,
            degraded=degraded,
            device=device,
        )

    detail = "; ".join(reasons) if reasons else "no candidates were tried"
    raise ComponentUnavailable(
        f"could not resolve {_describe(kind, name)}: every candidate in the chain "
        f"{tuple(chain)!r} was rejected. Reasons: {detail}"
    )


def _reject(
    *,
    requested: str,
    candidate: str,
    kind: ComponentKind,
    reason: str,
    exc_type: str | None,
    strict: bool,
    reasons: list[str],
    exc: BaseException | None = None,
) -> None:
    """Record and report one rejected candidate; raise instead when `strict`.

    Factored out so that the five rejection branches cannot drift apart: a fall-through
    that forgot to emit its event would be a silent degradation, which is the one thing
    L11 forbids outright.
    """
    reasons.append(f"{candidate}: {reason}")
    if strict:
        raise ComponentUnavailable(
            f"{_describe(kind, requested)} is unavailable and strict mode is on "
            f"(LE_AI_STRICT_BACKEND): {reason}. Strict mode refuses to degrade; it is "
            f"for CI accuracy suites, and enabling it in production violates L1."
        ) from exc
    _emit_fallback_event(
        requested=requested,
        candidate=candidate,
        kind=kind,
        reason=reason,
        exc_type=exc_type,
    )
