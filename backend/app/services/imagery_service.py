"""``imagery_service`` — wraps ``gis.imagery.registry`` and injects config from Settings.

★ **L2: the default imagery provider is KEYLESS.** ``docker compose up`` with an empty
``.env`` yields a working satellite search via ``esri_world_imagery`` — this service does
nothing to change that; it merely resolves the registry the same way ``gis`` does, with a
``GisConfig`` built from the backend ``Settings`` instead of read straight from the
environment (per-provider secrets are still read from the environment by each provider —
see ``_adapters.gis_config_from_settings``).

★ **L5: this service performs NO CV.** It resolves providers, lists them, proxies tile
bytes and health, and hands the raw ``ImageryProvider`` back for a caller that needs a
chip. The heavy stitch of ``get_static_bbox`` lives in ``gis``; this service only calls
it, and the request-scale budget (``LE_MAX_STATIC_*``) is enforced there.

The registry caches provider instances (a provider holds a connection pool and a metadata
cache), so it should be built **once** at the composition root and injected. When none is
injected this service builds one from Settings, which is correct but throws that cache away
per request — fine for a script, wrong for a hot path.
"""

from __future__ import annotations

import logging
import threading
import time
from functools import lru_cache
from typing import Final

from gis.errors import (
    ProviderDisabledError,
    ProviderNotConfiguredError as GisProviderNotConfigured,
    ProviderRateLimitError,
    ProviderTransportError,
    TileNotAvailableError,
    UnknownProviderError as GisUnknownProvider,
)
from gis.imagery.base import ProviderCapabilities, ProviderHealth
from gis.imagery.cache.base import NEGATIVE_MARKER, TileCache, TileCacheKey
from gis.imagery.registry import ProviderListing, ProviderRegistry
from gis.types import BBox as GisBBox, BasemapKind, SatelliteChip

from app.core.config import Settings
from app.core.exceptions import (
    ProviderNotConfigured,
    ProviderToSForbidden,
    UnknownProvider,
)
from app.schemas.imagery import ProviderInfo
from app.services._adapters import gis_config_from_settings, to_provider_info
from app.services.imagery_usage import get_usage

__all__ = ["ImageryService", "build_registry"]

_log = logging.getLogger("app.services.imagery")

# ── in-flight tile registry ──────────────────────────────────────────────────
#
# ★ Process-wide, because ``ImageryService`` is per-request: an instance-level registry
#   would dedupe nothing. Keyed on the full ``TileCacheKey`` string (provider + variant
#   + z/x/y), so distinct configurations never share a fetch. Entries are removed when
#   the last holder releases; the dict is bounded by the number of CONCURRENT misses.

_INFLIGHT: dict[str, threading.Lock] = {}
_INFLIGHT_GUARD = threading.Lock()


def _inflight_lock(key_str: str) -> threading.Lock:
    """The shared per-tile lock — created once per in-flight tile."""
    with _INFLIGHT_GUARD:
        lock = _INFLIGHT.get(key_str)
        if lock is None:
            lock = threading.Lock()
            _INFLIGHT[key_str] = lock
        return lock


def _inflight_release(key_str: str, lock: threading.Lock) -> None:
    """Drop the registry entry once nobody holds the lock. Best-effort cleanup —
    a lingering unlocked entry is re-used harmlessly, never leaked unboundedly."""
    with _INFLIGHT_GUARD:
        if _INFLIGHT.get(key_str) is lock and not lock.locked():
            _INFLIGHT.pop(key_str, None)


#: How long a ``ProviderHealth`` probe result is trusted before a re-probe (§7.1). The
#: gis providers' ``health()`` is already cheap and offline for keyless sources, but the
#: cache keeps endpoint 51 from turning into a per-request round trip for keyed ones.
_HEALTH_TTL_SECONDS: Final[float] = 30.0


@lru_cache(maxsize=4)
def _tile_cache_for(
    backend: str, directory: str, ttl_s: int, max_bytes: int
) -> TileCache | None:
    """Build the shared tile cache once per distinct configuration.

    ★ Cached because ``ImageryService`` is constructed PER REQUEST (see the endpoint in
    ``api/v1/imagery.py``); building a fresh cache object on every tile would throw away the
    LRU bookkeeping and, for the memory backend, the cache itself.

    A cache that cannot be built is not fatal — imagery still works, just uncached.
    """
    try:
        if backend == "disk":
            from gis.imagery.cache.disk import DiskTileCache

            return DiskTileCache(directory, ttl_s=ttl_s, max_bytes=max_bytes)
        if backend == "memory":
            from gis.imagery.cache.memory import LRUTileCache

            return LRUTileCache(max_bytes=max_bytes, default_ttl_s=ttl_s)
        if backend == "redis":
            from gis.imagery.cache import RedisTileCache  # lazily bound (§11.3)

            return RedisTileCache(ttl_s=ttl_s)
    except Exception as exc:  # noqa: BLE001 — never let caching break imagery
        _log.warning("tile_cache.unavailable", extra={"backend": backend, "error": str(exc)})
    return None


def _build_tile_cache(settings: Settings) -> TileCache | None:
    return _tile_cache_for(
        str(settings.imagery_tile_cache_backend),
        str(settings.imagery_tile_cache_dir),
        int(settings.imagery_tile_cache_ttl_seconds),
        int(settings.imagery_tile_cache_max_bytes),
    )


def _media_type_of(data: bytes) -> str:
    """Recover a cached tile's MIME from its magic bytes.

    ``TileCache`` stores raw bytes only, so the media type is derived rather than stored —
    which keeps the cache format unchanged and cannot drift from the payload.
    """
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def build_registry(settings: Settings) -> ProviderRegistry:
    """Build a ``ProviderRegistry`` from the backend ``Settings``.

    ★ Call this ONCE at the composition root and inject the result. The registry caches
    provider instances; a new one per request rebuilds every connection pool.
    """
    return ProviderRegistry(gis_config_from_settings(settings))


class ImageryService:
    """Resolve, list and proxy satellite imagery providers.

    Args:
        settings: The backend settings — the source of the tile-proxy URL template, the
            default provider, and the ``GisConfig`` when no registry is injected.
        registry: A shared ``ProviderRegistry``. When None, one is built from
            ``settings`` (see the module docstring for why injecting is preferable).
    """

    def __init__(self, settings: Settings, *, registry: ProviderRegistry | None = None) -> None:
        self._settings = settings
        self._registry = registry if registry is not None else build_registry(settings)
        self._health_cache: dict[str, tuple[float, ProviderHealth]] = {}
        self._tiles: TileCache | None = _build_tile_cache(settings)
        if str(settings.imagery_tile_cache_backend) == "disk":
            get_usage().configure_ledger(settings.imagery_tile_cache_dir)

    @property
    def tile_cache(self) -> TileCache | None:
        """The shared tile cache — ``OfflineCacheService`` reads coverage through it."""
        return self._tiles

    # ── resolution ────────────────────────────────────────────────────────────

    def resolve(self, name: str | None = None):
        """Resolve a provider, translating gis errors into the domain hierarchy.

        Args:
            name: A provider name, ``"auto"``, or None for the configured default (L2).

        Returns:
            A configured, allowed ``gis.imagery.base.ImageryProvider``.

        Raises:
            UnknownProvider: The name is not registered (404).
            ProviderToSForbidden: The operator's allow-list / offline mode forbids it
                (403).
            ProviderNotConfigured: The provider is registered but has no credential, and
                strict mode (or an exhausted chain) refuses to fall back (503).
        """
        try:
            return self._registry.resolve(name)
        except GisUnknownProvider as exc:
            raise UnknownProvider(str(exc)) from exc
        except ProviderDisabledError as exc:
            raise ProviderToSForbidden(str(exc)) from exc
        except GisProviderNotConfigured as exc:
            raise ProviderNotConfigured(str(exc)) from exc

    def get_provider(self, name: str):
        """Return one provider by exact name, ignoring config and the allow-list.

        For ``GET /imagery/providers/{provider}``, which must report on a provider
        precisely *because* it is not configured.

        Raises:
            UnknownProvider: The name is not registered.
        """
        try:
            return self._registry.get(name)
        except GisUnknownProvider as exc:
            raise UnknownProvider(str(exc)) from exc

    # ── listing (→ wire) ──────────────────────────────────────────────────────

    def list_provider_info(self) -> list[ProviderInfo]:
        """Every registered provider as a wire ``ProviderInfo`` — endpoint 50.

        Never raises: an unconfigured or even un-buildable provider is reported, not
        hidden, so a surveyor can discover which key to set.
        """
        default_name = self._default_provider_name()
        return [
            to_provider_info(
                listing,
                is_default=listing.name == default_name,
                tile_url_template=self.tile_url_template(listing.name),
            )
            for listing in self._registry.available()
        ]

    def get_provider_info(self, name: str) -> ProviderInfo:
        """One provider as a wire ``ProviderInfo`` — endpoints 50/51.

        Raises:
            UnknownProvider: The name is not registered.
        """
        provider = self.get_provider(name)
        configured, reason = self._configured_state(provider)
        allowed, why = self._registry.is_allowed(name)
        listing = ProviderListing(
            provider=provider,
            configured=configured,
            allowed=allowed,
            reason=reason or (None if allowed else why),
        )
        return to_provider_info(
            listing,
            is_default=name == self._default_provider_name(),
            tile_url_template=self.tile_url_template(name),
        )

    # ── imagery access (no CV here — gis does the work) ───────────────────────

    def get_tile_bytes(
        self,
        provider_name: str,
        z: int,
        x: int,
        y: int,
        *,
        kind: BasemapKind = BasemapKind.SATELLITE,
        source: str = "map",
    ) -> tuple[bytes, str]:
        """Fetch a single tile's raw bytes + MIME for the proxy — endpoint 52.

        The provider decodes/encodes; this service never touches pixels.

        ``source`` is accounting only (``map`` | ``precache`` | ``viewport`` — see
        ``imagery_usage``); behaviour is identical for every source.

        Raises:
            UnknownProvider | ProviderToSForbidden | ProviderNotConfigured: As
                :meth:`resolve`.
            Any ``gis.errors.ProviderError`` subclass for a transport/range failure — the
                API layer maps those to the right status.
        """
        provider, cache_only = self._resolve_for_tiles(provider_name)
        usage = get_usage()

        # ★ READ-THROUGH TILE CACHE. Without this the settings (LE_IMAGERY_TILE_CACHE_*),
        #   the cache classes in gis.imagery.cache and the tile_cache_gc maintenance task
        #   were all dead code: nothing ever CONSTRUCTED a cache, so every tile went to the
        #   provider and nothing was ever persisted. That made "warm the cache, then work
        #   offline" (docs/guides/offline-mode.md) impossible — the documented offline
        #   workflow simply did not function.
        #
        # ★ DiskTileCache.put consults the provider's `allows_caching` capability and
        #   REFUSES to persist tiles from providers whose terms forbid it (google_maps_static
        #   is allows_caching=False). Caching is therefore opt-out by licence, not by luck.
        #
        # ★ The key's variant is the provider's OWN config fingerprint (style, @2x,
        #   format, kind — `cache_variant`), so changing the imagery configuration can
        #   never return incompatible cached tiles.
        key = TileCacheKey(
            provider=provider.name, z=z, x=x, y=y, variant=provider.cache_variant(kind)
        )
        if self._tiles is not None:
            try:
                hit = self._tiles.get(key)
            except Exception:  # noqa: BLE001 — a cache fault must never fail a tile
                hit = None
            if hit is not None:
                if hit == NEGATIVE_MARKER:
                    # ★ NEGATIVE HIT: we asked before and the provider has nothing here.
                    #   Answering from the marker is what stops re-fetch storms over
                    #   ocean and coverage gaps — the 204 costs zero upstream requests.
                    usage.record_negative_hit(provider.name)
                    raise TileNotAvailableError(
                        f"{provider.name} has no imagery at {z}/{x}/{y} (cached negative)",
                        provider=provider.name,
                    )
                usage.record_cache_hit(provider.name)
                return hit, _media_type_of(hit)

        if cache_only:
            # ★ OFFLINE MODE, uncached tile: a controlled miss (→ 204), NEVER a network
            #   attempt. The map keeps working over cached ground; blank tiles mark the
            #   edge of the prepared area.
            usage.record_offline_miss(provider.name)
            raise TileNotAvailableError(
                f"{provider.name} tile {z}/{x}/{y} is not in the offline cache "
                "(LE_IMAGERY_OFFLINE=true serves cached imagery only)",
                provider=provider.name,
            )

        usage.record_miss(provider.name)

        # ★ IN-FLIGHT DEDUP. One lock per tile identity: whoever holds it fetches;
        #   everyone else queues on it and then reads the answer from the cache. However
        #   many callers ask for the same missing tile at once — the map pane, a manual
        #   pre-cache run, the automatic viewport cacher — exactly ONE upstream request
        #   is sent and ONE disk write happens.
        key_str = key.to_str()
        lock = _inflight_lock(key_str)
        try:
            with lock:
                if self._tiles is not None:
                    try:
                        hit = self._tiles.get(key)
                    except Exception:  # noqa: BLE001
                        hit = None
                    if hit is not None:
                        # Someone else fetched it while we waited on the lock.
                        if hit == NEGATIVE_MARKER:
                            usage.record_negative_hit(provider.name)
                            raise TileNotAvailableError(
                                f"{provider.name} has no imagery at {z}/{x}/{y} "
                                "(cached negative)",
                                provider=provider.name,
                            )
                        usage.record_cache_hit(provider.name)
                        return hit, _media_type_of(hit)

                usage.record_upstream(provider.name, source=source)
                try:
                    data, media_type = provider.get_tile_bytes(z, x, y, kind=kind)
                except TileNotAvailableError:
                    # ★ A GENUINE "no imagery here" — negative-cache it, for the
                    #   provider's own negative TTL. Auth failures, 429s, 5xx and
                    #   transport errors deliberately do NOT land here: they raise their
                    #   own types below and are never negative-cached, because a
                    #   temporary failure is not an answer.
                    if self._tiles is not None:
                        try:
                            self._tiles.put_negative(
                                key, ttl_s=provider.negative_cache_ttl_seconds
                            )
                        except Exception:  # noqa: BLE001 — cache faults never fail a tile
                            pass
                    raise
                except ProviderRateLimitError:
                    usage.record_429(provider.name)
                    raise
                except ProviderTransportError:
                    usage.record_failure(provider.name)
                    raise

                if self._tiles is not None:
                    try:
                        # ★ PER-PROVIDER TTL. The provider's ToS-capped TTL (Mapbox:
                        #   LE_MAPBOX_CACHE_TTL_SECONDS) rides along on the write for
                        #   backends with native expiry (redis/memory); DiskTileCache
                        #   additionally enforces it at read/sweep time. None = global.
                        self._tiles.put(key, data, ttl_s=provider.cache_ttl_seconds)
                    except Exception:  # noqa: BLE001 — a full disk degrades to no-cache
                        _log.warning("tile_cache.put_failed", extra={"key": key.to_str()})
                return data, media_type
        finally:
            _inflight_release(key_str, lock)

    def _resolve_for_tiles(self, provider_name: str | None):
        """Resolve for the tile path, honouring offline mode as CACHE-ONLY.

        ★ ``LE_IMAGERY_OFFLINE=true`` forbids the *network*, not the *cache*: imagery a
        surveyor deliberately pre-cached is exactly what offline mode exists to serve.
        An explicitly named network provider therefore resolves to ``(provider, True)``
        — serve cached tiles, never fetch. The operator's hard allow-list
        (``LE_ALLOWED_PROVIDERS``) still refuses outright; offline never widens it.

        Returns:
            ``(provider, cache_only)``.
        """
        try:
            return self.resolve(provider_name), False
        except ProviderToSForbidden:
            name = (provider_name or "").strip()
            if not self._settings.imagery_offline or not name or name == "auto":
                raise
            allow = list(self._settings.allowed_providers)
            if allow and name not in allow:
                raise
            try:
                provider = self._registry.get(name)
            except GisUnknownProvider as exc:
                raise UnknownProvider(str(exc)) from exc
            return provider, True

    def get_static_chip(
        self,
        bbox: GisBBox,
        zoom: int,
        *,
        provider_name: str | None = None,
        kind: BasemapKind = BasemapKind.SATELLITE,
    ) -> SatelliteChip:
        """Fetch contiguous imagery covering ``bbox`` as one chip — endpoint 53.

        The request-scale budget (``LE_MAX_STATIC_*``) is enforced inside ``gis`` and
        surfaces as ``AreaTooLargeError``; the API maps that to ``422
        STATIC_IMAGE_TOO_LARGE``.
        """
        provider = self.resolve(provider_name)
        return provider.get_static_bbox(bbox, zoom, kind=kind)

    def capabilities(self, provider_name: str | None = None) -> ProviderCapabilities:
        """A provider's raw gis capabilities — the accuracy inputs a manual GCP needs.

        ``gcp_service`` reads ``tile_size_px`` and ``georef_ce90_m`` off this to compute a
        manual GCP's positional accuracy (SCOPE.md §5).
        """
        return self.resolve(provider_name).capabilities()

    # ── health (30 s cache) ───────────────────────────────────────────────────

    def health(self, provider_name: str) -> ProviderHealth:
        """A provider's liveness, served from a 30 s cache (§7.1) — endpoint 51.

        Never raises: ``ImageryProvider.health`` returns a status rather than throwing.
        """
        now = time.monotonic()
        cached = self._health_cache.get(provider_name)
        if cached is not None and now - cached[0] < _HEALTH_TTL_SECONDS:
            return cached[1]
        provider = self.get_provider(provider_name)
        health = provider.health()
        self._health_cache[provider_name] = (now, health)
        return health

    # ── usage & cache statistics ──────────────────────────────────────────────

    def usage_snapshot(self) -> dict[str, object]:
        """Application-level imagery usage — ``GET /imagery/usage``.

        ★ THIS APP's ledger (upstream requests, hit ratios, 429s), explicitly NOT the
        provider's billing dashboard, which remains the billing truth.
        """
        snapshot = get_usage().snapshot()
        if self._tiles is not None:
            try:
                s = self._tiles.stats()
                snapshot["cache"] = {
                    "backend": s.backend,
                    "hits": s.hits,
                    "misses": s.misses,
                    "negative_hits": s.negative_hits,
                    "writes": s.writes,
                    "refusals": s.refusals,
                    "evictions": s.evictions,
                    "entries": s.entries,
                    "bytes_used": s.bytes_used,
                    "hit_rate": round(s.hit_rate, 4),
                }
            except Exception:  # noqa: BLE001 — stats must never fail the endpoint
                snapshot["cache"] = None
        else:
            snapshot["cache"] = None
        return snapshot

    # ── url templates ─────────────────────────────────────────────────────────

    def tile_url_template(self, provider_name: str) -> str:
        """The tile URL template the client should use for a provider.

        ★ By default the proxy path for EVERY provider, keyed or keyless — that is what
        keeps the ToS chokepoint, the shared rate-limit bucket and worker/browser cache
        identity intact (§7.2). ``LE_IMAGERY_DIRECT_TILE_URLS=true`` is an opt-in bandwidth
        trade for keyless providers; even then this service returns the proxy template
        unless the provider exposes a safe upstream template, because an invented upstream
        URL would put a broken tile layer in the browser (``tile_url`` raises for providers
        that have none).
        """
        prefix = self._settings.api_prefix.rstrip("/")
        return f"{prefix}/imagery/tiles/{provider_name}/{{z}}/{{x}}/{{y}}"

    # ── default provider (public — readiness reads this) ──────────────────────

    def default_provider_name(self) -> str:
        """The name default resolution lands on — the honest readiness/``is_default`` label.

        Public so the readiness probe (``GET /health/ready``) does not reach into a
        private method: readiness reporting which provider it would serve is a legitimate
        read of configured state, not internal detail.
        """
        return self._default_provider_name()

    # ── internals ─────────────────────────────────────────────────────────────

    def _default_provider_name(self) -> str:
        """The name the default resolution actually lands on, for ``is_default``."""
        try:
            return self.resolve("auto").name
        except (ProviderNotConfigured, ProviderToSForbidden, UnknownProvider):
            # Nothing resolves (a locked-down allow-list with no configured member). The
            # keyless Esri default is still the *intended* default, so name it.
            return "esri_world_imagery"

    @staticmethod
    def _configured_state(provider) -> tuple[bool, str | None]:
        """``(configured, reason)`` without ever raising — the ABC's contract."""
        try:
            configured = provider.is_configured()
            return configured, (None if configured else provider.configuration_reason())
        except Exception as exc:  # noqa: BLE001 - is_configured() must never break a listing
            return False, f"is_configured() raised: {exc}"
