"""``ProviderRegistry`` — config string to a ready provider (§11.4).

★ **``LE_IMAGERY_PROVIDER`` HAS TWO MODES, AND NAMING THEM IS THE FIX.**

===================  ==========================================================
``auto`` (default)   **PREFERENCE.** Walk ``LE_IMAGERY_FALLBACK_CHAIN`` in order
                     and take the first ``is_configured()`` provider.
an explicit name     **THAT provider.** The chain is **error-recovery only**, and
                     only when ``LE_IMAGERY_STRICT=false``.
===================  ==========================================================

> **Why this matters — the defect this design exists to prevent.** The chain's stated
> rationale is *"``local_orthophoto`` FIRST: if the operator mounted orthophotos they are
> definitionally better than any web tile source"*. But if the chain is walked ONLY when the
> NAMED provider is unconfigured, and the named default is keyless Esri, then
> ``is_configured()`` is **always True**, so **the chain is never consulted** — and an
> operator who dropped GeoTIFFs into ``./data/orthophotos`` still gets Esri tiles **and
> never learns why.** The ordering's rationale describes a **preference** mechanism; the
> error-recovery reading implements a different one. Only one could be true.
>
> ``auto`` makes both true: an empty ortho dir self-skips -> Esri (**zero-config preserved,
> L2 intact**), and a populated one wins (**the rationale becomes real**).

**The deliberate asymmetry, stated so nobody "fixes" it:** an explicitly requested
unconfigured **provider** raises (-> ``503 PROVIDER_NOT_CONFIGURED``), but an explicitly
requested missing **model weight** is a ``202`` + fallback. **Imagery changes the answer's
provenance; a matcher changes only its accuracy.** Silently serving 10 m Sentinel when the
operator paid for 0.3 m Mapbox is a worse failure than a 503. Both are reported; only one
is refusable.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Final

from gis.config import GisConfig
from gis.errors import (
    ProviderDisabledError,
    ProviderNotConfiguredError,
    UnknownProviderError,
)
from gis.imagery.base import PROVIDER_NAMES, ImageryProvider
from gis.imagery.providers import OFFLINE_PROVIDERS, PROVIDERS

__all__ = [
    "ProviderListing",
    "ProviderRegistry",
    "default_registry",
    "get_provider",
    "provider_allows_caching",
    "provider_cache_ttl_seconds",
    "provider_negative_cache_ttl_seconds",
]

_log = logging.getLogger("gis.imagery.registry")

_NEVER_IN_A_CHAIN: Final[frozenset[str]] = frozenset({"google_maps_static", "google_map_tiles"})
"""★ Providers that fallback may NEVER reach. Structural enforcement, not documentation.

``google_maps_static``'s terms plausibly forbid this product's core use, so it must not be
reachable by accident — only by an explicit ``LE_IMAGERY_PROVIDER=google_maps_static``, and
only after the double opt-in. Being *absent from every chain* is what makes "never default"
a property of the code rather than a promise in a comment.
"""


@dataclass(frozen=True, slots=True)
class ProviderListing:
    """One provider's registry status, for ``GET /imagery/providers``.

    ★ A ``gis``-side type, deliberately. The wire's ``ProviderInfo`` is a **pydantic**
    schema, and ``gis`` may not import pydantic (§10.2). ``app.services._adapters`` maps
    this plus ``capabilities()`` and ``health()`` into ``ProviderInfo``. The dependency
    points the way it already points.

    Attributes:
        provider: The constructed instance. Construction always succeeds, so this is never
            None — even for a provider with no key.
        configured: What ``is_configured()`` said.
        allowed: Whether ``LE_ALLOWED_PROVIDERS`` and ``LE_IMAGERY_OFFLINE`` permit it.
        reason: Why it is unavailable, as a sentence naming the fix. None when usable.
    """

    provider: ImageryProvider
    configured: bool
    allowed: bool
    reason: str | None = None

    @property
    def name(self) -> str:
        """The provider's registry key."""
        return self.provider.name

    @property
    def usable(self) -> bool:
        """True iff this provider could serve a request right now."""
        return self.configured and self.allowed


class ProviderRegistry:
    """Resolves a config string to a ready ``ImageryProvider``.

    Instances are cached per provider name: a provider holds a connection pool, a metadata
    cache and an orthophoto index, and rebuilding those per request would throw all three
    away. Thread-safe — Celery resolves from a worker pool.

    Args:
        config: The ``gis`` configuration. Defaults to a zero-config ``GisConfig()``, which
            is a fully working keyless system (L2, L10).
    """

    def __init__(self, config: GisConfig | None = None) -> None:
        self._config = config or GisConfig()
        self._instances: dict[str, ImageryProvider] = {}
        self._lock = threading.Lock()

    @property
    def config(self) -> GisConfig:
        """The configuration this registry resolves against."""
        return self._config

    # ---- construction ------------------------------------------------------

    def _build(self, name: str) -> ImageryProvider:
        """Construct (or return the cached) provider by name.

        ★ Construction NEVER raises for missing config — that is the ABC's contract, and it
        is what lets ``available()`` list an unconfigured provider instead of 500ing while
        trying to build one.

        Raises:
            UnknownProviderError: ``name`` is not registered. ★ Fails LOUD: a typo'd config
                must not quietly resolve to something that works, because a silently-wrong
                provider is a silently-wrong provenance on a survey coordinate.
        """
        instance = self._instances.get(name)
        if instance is not None:
            return instance
        provider_cls = PROVIDERS.get(name)
        if provider_cls is None:
            raise UnknownProviderError(
                f"unknown imagery provider {name!r}; registered: "
                f"{', '.join(sorted(PROVIDERS))}",
                provider=name,
            )
        with self._lock:
            instance = self._instances.get(name)
            if instance is None:
                instance = provider_cls(self._config)
                self._instances[name] = instance
        return instance

    # ---- policy ------------------------------------------------------------

    def is_allowed(self, name: str) -> tuple[bool, str | None]:
        """Check the operator's allow-list and offline mode. Never raises.

        Args:
            name: A registry key.

        Returns:
            ``(allowed, reason)``. ``reason`` names the var that would fix it.
        """
        imagery = self._config.imagery
        if imagery.offline and name not in OFFLINE_PROVIDERS:
            return (
                False,
                (
                    f"LE_IMAGERY_OFFLINE=true permits only {', '.join(OFFLINE_PROVIDERS)}; "
                    f"{name} needs the network"
                ),
            )
        allow_list = imagery.allowed_providers
        if allow_list and name not in allow_list:
            return (
                False,
                (
                    f"{name} is not in LE_ALLOWED_PROVIDERS ({', '.join(allow_list)}) - the "
                    "operator's hard allow-list"
                ),
            )
        return (True, None)

    def default_chain(self) -> tuple[str, ...]:
        """Return the ordered fallback chain, filtered to what may legally be reached.

        ★ Providers in ``_NEVER_IN_A_CHAIN`` are stripped even if an operator put them in
        ``LE_IMAGERY_FALLBACK_CHAIN``, and unknown names are dropped with a warning rather
        than taking the process down (L10) — a typo in a chain must not make imagery
        unavailable, it must make imagery fall back.

        Returns:
            The chain, in preference order.
        """
        chain: list[str] = []
        for name in self._config.imagery.fallback_chain:
            if name not in PROVIDERS:
                _log.warning(
                    "LE_IMAGERY_FALLBACK_CHAIN names unknown provider %r; ignoring it. "
                    "Registered: %s",
                    name,
                    ", ".join(sorted(PROVIDERS)),
                )
                continue
            if name in _NEVER_IN_A_CHAIN:
                _log.warning(
                    "LE_IMAGERY_FALLBACK_CHAIN names %r, which may never be reached by "
                    "fallback: its terms plausibly forbid deriving survey coordinates from "
                    "its imagery. Removing it from the chain. Select it explicitly with "
                    "LE_IMAGERY_PROVIDER if your own agreement permits your use.",
                    name,
                )
                continue
            chain.append(name)
        return tuple(chain)

    # ---- resolution --------------------------------------------------------

    def resolve(self, name: str | None = None) -> ImageryProvider:
        """Resolve a provider. ★ THE entry point, and the §11.4 ruling in code.

        Order of operations:

        1. ``name`` (or ``LE_IMAGERY_PROVIDER``) is ``auto`` -> **PREFERENCE WALK**: the
           first configured, allowed provider in ``default_chain()`` wins.
        2. Otherwise the name is explicit:

           a. not registered -> ``UnknownProviderError`` (fail loud: a typo'd config);
           b. not allowed -> ``ProviderDisabledError`` (-> 403 PROVIDER_TOS_FORBIDDEN);
           c. configured -> that provider;
           d. unconfigured and ``LE_IMAGERY_STRICT=true`` -> ``ProviderNotConfiguredError``
              (-> 503). *Dev is forgiving; prod is loud.*
           e. unconfigured and not strict -> **WARN and walk the chain.**

        ★ Whatever is returned, ``chip.provider_name`` is set to what was **actually** used,
        so a downstream report can never misattribute imagery.

        Args:
            name: A registry key, ``"auto"``, or None to read the configuration.

        Returns:
            A configured, allowed ``ImageryProvider``.

        Raises:
            UnknownProviderError: The name is not registered.
            ProviderDisabledError: The operator's allow-list or offline mode forbids it.
            ProviderNotConfiguredError: Under strict mode, or when nothing in the chain is
                configured.
        """
        requested = (name or self._config.imagery.provider or "auto").strip()

        if requested == "auto":
            return self._resolve_auto()

        if requested not in PROVIDERS:
            raise UnknownProviderError(
                f"unknown imagery provider {requested!r}; registered: "
                f"{', '.join(sorted(PROVIDERS))}",
                provider=requested,
            )

        allowed, why = self.is_allowed(requested)
        if not allowed:
            raise ProviderDisabledError(why or f"{requested} is not permitted", provider=requested)

        provider = self._build(requested)
        if provider.is_configured():
            return provider

        reason = provider.configuration_reason() or "not configured"
        if self._config.imagery.strict:
            raise ProviderNotConfiguredError(
                f"{requested} was requested but {reason}. LE_IMAGERY_STRICT=true, so this "
                "does not fall back: silently serving different imagery than the operator "
                "expected would misattribute the provenance of a survey coordinate.",
                provider=requested,
            )

        _log.warning(
            "%s was requested but %s; falling back down LE_IMAGERY_FALLBACK_CHAIN. The "
            "imagery you get will NOT be from %s, and chip.provider_name will say so.",
            requested,
            reason,
            requested,
        )
        return self._resolve_auto(exclude=requested)

    def _resolve_auto(self, *, exclude: str | None = None) -> ImageryProvider:
        """Walk the chain and take the first configured, allowed provider.

        Raises:
            ProviderNotConfiguredError: Nothing in the chain is usable.
        """
        reasons: list[str] = []
        for name in self.default_chain():
            if name == exclude:
                continue
            allowed, why = self.is_allowed(name)
            if not allowed:
                reasons.append(f"{name}: {why}")
                continue
            provider = self._build(name)
            try:
                configured = provider.is_configured()
            except Exception as exc:  # noqa: BLE001 - one bad provider must not break the chain
                reasons.append(f"{name}: is_configured() raised ({exc})")
                continue
            if configured:
                _log.debug("imagery provider resolved to %s", name)
                return provider
            reasons.append(f"{name}: {provider.configuration_reason() or 'not configured'}")

        detail = "; ".join(reasons) if reasons else "the fallback chain is empty"
        raise ProviderNotConfiguredError(
            f"no imagery provider is available. Tried: {detail}. The zero-config default "
            "(esri_world_imagery) is keyless and should always resolve - check "
            "LE_IMAGERY_FALLBACK_CHAIN, LE_ALLOWED_PROVIDERS and LE_IMAGERY_OFFLINE.",
        )

    # ---- listing -----------------------------------------------------------

    def available(self) -> list[ProviderListing]:
        """List every registered provider with its status. ★ NEVER raises.

        Drives the UI picker and ``GET /imagery/providers``. Unconfigured providers ARE
        listed, with ``configured: false`` and a reason — a provider that vanishes because
        its key is missing is a provider nobody can discover they need to configure.

        Returns:
            One ``ProviderListing`` per registered provider, in ``PROVIDER_NAMES`` order.
        """
        listings: list[ProviderListing] = []
        for name in PROVIDER_NAMES:
            try:
                provider = self._build(name)
            except Exception as exc:  # noqa: BLE001 - construction is contractually free
                _log.error(
                    "%s failed to construct (%s). __init__ must never raise - see "
                    "CONTRACT.md §4.16.",
                    name,
                    exc,
                )
                continue
            try:
                configured = provider.is_configured()
                reason = None if configured else provider.configuration_reason()
            except Exception as exc:  # noqa: BLE001 - is_configured() must never raise
                configured, reason = False, f"is_configured() raised: {exc}"
            allowed, why = self.is_allowed(name)
            listings.append(
                ProviderListing(
                    provider=provider,
                    configured=configured,
                    allowed=allowed,
                    reason=reason or (None if allowed else why),
                )
            )
        return listings

    def get(self, name: str) -> ImageryProvider:
        """Return one provider by exact name, ignoring configuration and the allow-list.

        For ``GET /imagery/providers/{provider}``, which must be able to report on a
        provider precisely *because* it is not configured.

        Args:
            name: A registry key.

        Returns:
            The provider instance.

        Raises:
            UnknownProviderError: ``name`` is not registered.
        """
        return self._build(name)

    def clear(self) -> None:
        """Drop every cached instance. For tests and for a config reload."""
        with self._lock:
            self._instances.clear()


_DEFAULT_LOCK: Final[threading.Lock] = threading.Lock()
_default: ProviderRegistry | None = None


def default_registry() -> ProviderRegistry:
    """Return the process-wide registry, built from the environment on first use.

    ★ Lazy, not import-time: reading ``os.environ`` at import would freeze the config
    before a test could set it, and would run ``GisConfig.from_env`` inside anything that
    merely imported ``gis.imagery``.

    Returns:
        The shared ``ProviderRegistry``. Never raises (L10: ``GisConfig.from_env({})``
        cannot fail).
    """
    global _default
    if _default is not None:
        return _default
    with _DEFAULT_LOCK:
        if _default is None:
            _default = ProviderRegistry(GisConfig.from_env())
    return _default


def reset_default_registry() -> None:
    """Drop the process-wide registry so the next call rebuilds it. For tests."""
    global _default
    with _DEFAULT_LOCK:
        _default = None


def get_provider(name: str | None = None, *, config: GisConfig | None = None) -> ImageryProvider:
    """Resolve a provider without holding a registry. The convenience entry point.

    Args:
        name: A registry key, ``"auto"``, or None to read the configuration.
        config: Override the configuration. Uses the process-wide registry when None.

    Returns:
        A configured, allowed ``ImageryProvider``.

    Raises:
        UnknownProviderError | ProviderDisabledError | ProviderNotConfiguredError: As
            ``ProviderRegistry.resolve``.
    """
    registry = ProviderRegistry(config) if config is not None else default_registry()
    return registry.resolve(name)


def provider_allows_caching(name: str) -> bool:
    """Report whether a provider's TERMS permit persistent caching.

    ★ THE CACHE'S LICENCE GATE. ``DiskTileCache`` and ``RedisTileCache`` call this (at call
    time, to avoid an import cycle) before writing a single byte.

    Args:
        name: A registry key.

    Returns:
        The provider's ``allows_caching`` capability.

    Raises:
        UnknownProviderError: ``name`` is not registered. ★ Deliberately NOT swallowed
            here: the callers translate any failure into "do not persist", which is the safe
            default for a licence gate, and they want to log the reason.
    """
    return default_registry().get(name).capabilities().allows_caching


def provider_cache_ttl_seconds(name: str) -> int | None:
    """A provider's own ToS-capped cache TTL, or None for "no provider-specific cap".

    ★ THE PER-PROVIDER TTL GATE, companion to :func:`provider_allows_caching`.
    ``DiskTileCache`` consults it (call-time, memoised) so a duration-capped provider
    (Mapbox) expires on ITS clock even when the operator's global TTL is longer.

    Raises:
        UnknownProviderError: ``name`` is not registered — callers translate any failure
            into "use the global TTL", never into a crash.
    """
    return default_registry().get(name).cache_ttl_seconds


def provider_negative_cache_ttl_seconds(name: str) -> int:
    """How long a provider's "no imagery here" may be remembered, seconds.

    Raises:
        UnknownProviderError: ``name`` is not registered.
    """
    return default_registry().get(name).negative_cache_ttl_seconds
