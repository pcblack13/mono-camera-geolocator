"""The component registry — the graceful-degradation engine.

`ai_engine` never constructs a backend by name at a call site. It asks the registry, and
the registry consults `models.policy` (the single home of fallback policy), which walks a
chain until something works and reports honestly what it found. That indirection is what
makes L1 and L11 mechanical rather than aspirational: "SIFT still works when every weight
file is missing" is not a promise in a document, it is a `ComponentSpec.fallback` field
and an assertion at registration time.

★ IN THIS BUILD EVERY COMPONENT RESOLVES TO *DEFERRED* (``docs/architecture/SCOPE.md``).
The registry, the specs, the chains and the policy are all real and all exercised; the
implementations behind them are not built. `models/policy.py` explains at length how that
is expressed without special-casing any caller, and why the seam has to be load-bearing
now rather than the day the engine is re-enabled.

Usage — the registration side (every concrete backend module)::

    @register(ComponentKind.EXTRACTOR, fallback="sift", requires_weights=("superpoint_v1",))
    class SuperPointExtractor(FeatureExtractor):
        name = "superpoint"
        ...

Usage — the resolution side (`pipeline.compose`, `models.preflight`)::

    resolution = REGISTRY.resolve("superpoint", ComponentKind.EXTRACTOR, cfg_mapping)
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from ai_engine.logging import get_logger
from ai_engine.models.hashing import params_hash
from ai_engine.models.policy import (
    DeferredComponent,
    DeferredImplementation,
    is_deferred,
    resolve_with_fallback,
)
from ai_engine.models.spec import (
    ComponentKind,
    ComponentSpec,
    PreflightReport,
    Resolution,
    ResolutionReport,
)
from ai_engine.models.weights import WeightManifest

__all__ = [
    "BASE_INSTALL_PACKAGES",
    "REGISTRY",
    "ComponentKind",
    "ComponentSpec",
    "DeferredComponent",
    "DeferredImplementation",
    "PreflightReport",
    "Registry",
    "Resolution",
    "ResolutionReport",
    "WeightManifest",
    "get_registry",
    "is_deferred",
    "params_hash",
    "register",
]

_log = get_logger(__name__)

#: Packages every `ai_engine` install already has (§2.2: "pure CV. numpy + cv2 + scipy
#: only"). A terminal spec may not declare a `requires_packages` outside this set — that
#: is what "provably terminates at something that always constructs" means, and it is
#: asserted rather than trusted.
BASE_INSTALL_PACKAGES: frozenset[str] = frozenset({"numpy", "cv2", "scipy"})


class Registry:
    """Name + kind → :class:`ComponentSpec`, and name + kind → a live component.

    One namespace **per kind**: ``("sift", EXTRACTOR)`` and ``("sift", SEGMENTER)`` are
    different slots and would not collide. In practice names are unique anyway, but keying
    on the pair is what makes `resolve` unable to hand a matcher to something expecting an
    extractor.
    """

    def __init__(self) -> None:
        self._specs: dict[tuple[ComponentKind, str], ComponentSpec] = {}

    # -- registration ---------------------------------------------------------------

    def register(self, spec: ComponentSpec) -> None:
        """Add `spec` to the registry, validating the invariants the policy relies on.

        ★ THE TERMINAL ASSERTION IS THE POINT OF THIS METHOD. `resolve_with_fallback`
        promises that every chain provably terminates at something that always
        constructs. That promise is only worth anything if "terminal" means what it says,
        so it is checked here, at registration, where the failure is a loud import-time
        error naming the offending spec — rather than at 3 a.m., as a
        `ComponentUnavailable` from a chain that ran off the end of the world.

        A terminal spec must have: no `fallback`, no `requires_weights`, and no
        `requires_packages` beyond :data:`BASE_INSTALL_PACKAGES`.

        Note the one-directional check. ``is_terminal`` implies ``fallback is None``, but
        **not** the reverse: `ComponentKind.DETECTOR_FREE` has no classical member, so
        `loftr` legitimately has `fallback=None` while requiring weights. It is not
        terminal, and an unresolvable detector-free matcher is handled by swapping the
        correspondence source in `pipeline.compose`, not by a chain step (§11.1).

        Args:
            spec: The component spec to register.

        Raises:
            ValueError: The spec violates a terminal invariant, or the (kind, name) pair
                is already registered with a different spec.
        """
        key = (spec.kind, spec.name)

        if spec.is_terminal:
            problems: list[str] = []
            if spec.fallback is not None:
                problems.append(f"declares fallback={spec.fallback!r}")
            if spec.requires_weights:
                problems.append(f"requires weights {list(spec.requires_weights)}")
            extra_packages = set(spec.requires_packages) - BASE_INSTALL_PACKAGES
            if extra_packages:
                problems.append(f"requires non-base packages {sorted(extra_packages)}")
            if problems:
                raise ValueError(
                    f"{spec.kind} {spec.name!r} is registered as terminal but "
                    f"{'; '.join(problems)}. A terminal spec is the end of a fallback "
                    f"chain and MUST always construct — that is what makes every chain "
                    f"provably terminating. Either give it a fallback or drop its "
                    f"requirements."
                )

        existing = self._specs.get(key)
        if existing is not None and existing is not spec:
            raise ValueError(
                f"{spec.kind} {spec.name!r} is already registered. Two specs for one "
                f"slot means the winner depends on import order, which is not a "
                f"decision anyone should make by accident."
            )

        self._specs[key] = spec
        _log.debug("registered %s %r (fallback=%r)", spec.kind, spec.name, spec.fallback)

    # -- lookup ---------------------------------------------------------------------

    def get(self, name: str, kind: ComponentKind) -> ComponentSpec | None:
        """Return the spec for `(name, kind)`, or None. Calls `_ensure_registered()` first."""
        _ensure_registered()
        return self._specs.get((kind, name))

    def specs(self, kind: ComponentKind | None = None) -> tuple[ComponentSpec, ...]:
        """Every registered spec, optionally filtered by `kind`.

        Calls `_ensure_registered()` first, so this is never empty by accident — the
        twelve-parallel-agent failure mode where nothing imported the decorators and every
        resolution fell through to `ComponentUnavailable`.

        Returns:
            Specs sorted by (kind, name), so `GET /capabilities` and the logs enumerate
            components in a stable order rather than in dict-insertion order.
        """
        _ensure_registered()
        found = [
            spec
            for (spec_kind, _name), spec in self._specs.items()
            if kind is None or spec_kind == kind
        ]
        return tuple(sorted(found, key=lambda s: (str(s.kind), s.name)))

    def names(self, kind: ComponentKind) -> tuple[str, ...]:
        """The registered names for `kind`, sorted."""
        return tuple(spec.name for spec in self.specs(kind))

    # -- resolution -----------------------------------------------------------------

    def resolve(
        self,
        name: str,
        kind: ComponentKind,
        config: Mapping[str, Any],
        *,
        strict: bool = False,
        manifest: WeightManifest | None = None,
    ) -> Resolution:
        """Resolve `(name, kind)` to a component, falling back as policy dictates.

        Calls `_ensure_registered()` first, then delegates every decision to
        `resolve_with_fallback`. This method deliberately contains no policy of its own:
        there is exactly one place fallback policy lives, and it is not here.

        Args:
            name: The requested component name.
            kind: The slot to fill.
            config: The component config mapping — see
                `pipeline.compose.component_config`, whose key sets are normative.
            strict: `LE_AI_STRICT_BACKEND`. Refuse to degrade; raise instead.
            manifest: The weight table to verify against. Defaults to the shipped one.
                Kept out of `config` because `config` is hashed into cache keys.

        Returns:
            A `Resolution`. In this build its `instance` is a `DeferredComponent` and its
            `reason` says so — see `models/policy.py`.

        Raises:
            ComponentUnavailable: The chain was exhausted, or `strict=True` and a
                candidate was rejected.
            NotImplementedDeferred: `strict=True` and the resolved component is deferred.
        """
        _ensure_registered()
        return resolve_with_fallback(
            self, name, kind, config, strict=strict, manifest=manifest
        )


def register(kind: ComponentKind, **kw: Any) -> Callable[[type], type]:
    """Class decorator: register the decorated class as a component of `kind`.

    The decorated class is both the spec's identity and its factory — it is called with
    the component config mapping, so every concrete backend's ``__init__`` takes exactly
    one positional argument, a ``Mapping[str, Any]``.

    ::

        @register(ComponentKind.EXTRACTOR, fallback="sift", requires_weights=("superpoint_v1",))
        class SuperPointExtractor(FeatureExtractor):
            name = "superpoint"

    Args:
        kind: The slot the class fills.
        **kw: Any `ComponentSpec` field except `kind` and `factory`. `name` defaults to
            the class's `name` ClassVar — the class already has to declare it for the
            ABC, and repeating it in the decorator is a second source of truth that will
            eventually disagree with the first.

    Returns:
        The decorator, which registers the class and returns it unchanged.

    Raises:
        ValueError: `name` was neither passed nor declared on the class, or a terminal
            invariant is violated (checked in `Registry.register`).
    """

    def decorate(cls: type) -> type:
        name = kw.pop("name", None) or getattr(cls, "name", None)
        if not name or not isinstance(name, str):
            raise ValueError(
                f"{cls.__qualname__} cannot be registered: it declares no `name` "
                f"ClassVar and none was passed to register(). The registry key has to "
                f"come from somewhere."
            )
        REGISTRY.register(ComponentSpec(name=name, kind=kind, factory=cls, **kw))
        return cls

    return decorate


#: ★ THE singleton. `pipeline.compose` and `models.preflight` resolve against it, and
#: `ai_engine.Registry` re-exports the CLASS so an embedder can build their own isolated
#: one (a test, a notebook, a benchmark harness) without disturbing this table.
REGISTRY = Registry()


def get_registry() -> Registry:
    """Return the process-wide registry singleton.

    Prefer this to importing `REGISTRY` directly at module scope in long-lived code: it
    is one indirection away from being swappable, and it reads as a decision rather than
    as a global.
    """
    return REGISTRY


_REGISTERED = False


def _ensure_registered() -> None:
    """★ THE REGISTRATION SITE. Idempotent, lazy, called at the top of every lookup.

    A `@register` class decorator fires only when its module is **imported**, so some
    module has to import them all. This is that trigger, and its placement is the only
    one that is neither cyclic nor eager:

    * **`models/__init__.py` importing `ai_engine.extractors` at module scope** is a hard
      cycle — the extractors import `models` for the decorator — and §10.2 confines
      `models` to stdlib + `ai_engine.{types,errors}` besides.
    * **`ai_engine/__init__.py` importing them** would make `gis`'s sanctioned
      `from ai_engine.types import CandidateWindow` execute the package `__init__` and
      drag in cv2, scipy and every extractor — destroying the exact cheapness property
      that §10.3 uses to justify permitting that cross-package import at all, and
      breaking `cd gis && pytest`.

    Calling it lazily, at first lookup, costs nothing new: by the time anyone resolves a
    component they are already in the pipeline. It mirrors
    `gis/imagery/providers/__init__.py`'s explicit-registration pattern.
    """
    global _REGISTERED
    if _REGISTERED:
        return
    # ★ Set BEFORE the import, not after. `registration` imports modules that import this
    #   package, and one of them calling a lookup during its own import would re-enter
    #   here and recurse forever. The flag is the re-entrancy guard as well as the
    #   idempotence guard.
    _REGISTERED = True
    from ai_engine.models import registration  # noqa: F401, PLC0415 — the whole point

    _log.debug("component registration complete: %d specs", len(REGISTRY.specs()))
