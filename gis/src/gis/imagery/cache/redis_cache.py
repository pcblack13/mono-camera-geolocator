"""``RedisTileCache`` — shared by every worker. The default in prod.

★ **``redis`` IS BOUND AT CALL TIME, INSIDE THE METHODS — NEVER AT MODULE SCOPE** (§11.3).
``cache/__init__.py`` exposes this module via a module ``__getattr__``, so importing the
cache package with redis absent succeeds. ``is_available()`` then reports
``(False, "requires redis")`` and the registry falls back to ``DiskTileCache``.

**Why Redis in prod, specifically.** Tile fetching happens **inside Celery workers**, and a
disk cache in a container is per-replica. Four workers searching the same AOI would fetch
every tile four times — quadrupling both latency and our rate-limit consumption against the
provider. The shared cache is the point; the persistence is incidental.

★ Like every cache here, this one is **licence-gated** (``allows_caching``) and **fails
soft**: an unreachable Redis is a cache miss and a WARNING, never a failed tile request.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence
from typing import Any, Final

from gis.imagery.cache.base import (
    NEGATIVE_MARKER,
    CacheStats,
    TileCache,
    TileCacheKey,
    TileCacheKeyPrefix,
)
from gis.imagery.cache.memory import LRUTileCache

__all__ = ["RedisTileCache"]

_log = logging.getLogger("gis.imagery.cache.redis")

_NEGATIVE_VALUE: Final[bytes] = b"\x00LE_NEGATIVE"
"""On-the-wire marker for a cached negative.

★ Redis cannot distinguish "key holds an empty string" from "key absent" through every
client path, so the negative gets an explicit sentinel rather than relying on ``b""``. It
is translated back to ``NEGATIVE_MARKER`` at this class's boundary, so callers only ever
see the interface's three-way answer.
"""


def is_available() -> tuple[bool, str | None]:
    """Report whether ``redis`` can be bound. ★ Total; callable with redis absent.

    Returns:
        ``(available, reason)``. ``reason`` is None when available, else the sentence that
        ``GET /capabilities`` shows the operator.
    """
    import importlib.util  # noqa: PLC0415

    if importlib.util.find_spec("redis") is None:
        return (False, "requires redis (pip install 'landexplorer-gis[redis]')")
    return (True, None)


def _provider_allows_caching(provider: str) -> bool:
    """Ask the registry whether this provider's terms permit persistent caching.

    ★ CALL-TIME import: at module scope it would cycle through the provider registry.

    Returns:
        The capability, and **False on any doubt** — the safe default for a licence gate.
    """
    try:
        from gis.imagery.registry import provider_allows_caching  # noqa: PLC0415

        return provider_allows_caching(provider)
    except Exception as exc:  # noqa: BLE001 - a cache must never take a request down
        _log.warning(
            "cannot determine whether %r permits caching (%s); refusing to persist",
            provider,
            exc,
        )
        return False


class RedisTileCache(TileCache):
    """Tile bytes in Redis, shared across every worker.

    Args:
        url: Redis URL. ``LE_REDIS_URL``.
        ttl_s: Default entry lifetime. ★ Several providers' terms CAP caching duration —
            see ``docs/legal/imagery-terms.md``. The default is 30 days; a provider with a
            shorter cap must be given a shorter TTL by the composition root.
        namespace: Key prefix, so a shared Redis can host more than this cache.
        allows_caching: Predicate over a provider name. Defaults to the provider's own
            ``ProviderCapabilities.allows_caching``. ★ Override only in tests.
        fallback: Where refused and un-storable tiles go. Defaults to a private
            ``LRUTileCache``.
    """

    def __init__(
        self,
        url: str = "redis://localhost:6379/0",
        *,
        ttl_s: int = 2_592_000,
        namespace: str = "le",
        allows_caching: "object | None" = None,
        fallback: TileCache | None = None,
    ) -> None:
        self._url = url
        self._ttl_s = int(ttl_s)
        self._namespace = namespace
        self._allows_caching = allows_caching or _provider_allows_caching
        self._fallback = fallback if fallback is not None else LRUTileCache()
        self._client: Any | None = None
        self._degraded = False
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._negative_hits = 0
        self._writes = 0
        self._refusals = 0
        self._refused_providers: set[str] = set()
        self._policy_cache: dict[str, bool] = {}

    @property
    def backend(self) -> str:
        return "redis"

    @property
    def fallback(self) -> TileCache:
        """The cache that refused and un-storable tiles go to."""
        return self._fallback

    @property
    def degraded(self) -> bool:
        """True once Redis has failed and this cache has fallen back to its LRU."""
        return self._degraded

    def _redis(self) -> Any | None:
        """Bind a Redis client at CALL time, or None. NEVER raises.

        ★ THE call-time binding this module exists to demonstrate: ``import redis`` lives
        here, inside a method, so that importing ``gis.imagery.cache`` with redis absent
        succeeds and the whole gis suite collects.
        """
        if self._degraded:
            return None
        if self._client is not None:
            return self._client
        with self._lock:
            if self._client is not None:
                return self._client
            try:
                import redis  # noqa: PLC0415 - ★ CALL-TIME BINDING, §11.3.

                self._client = redis.Redis.from_url(self._url)
                return self._client
            except Exception as exc:  # noqa: BLE001 - ImportError, bad URL, anything
                self._degrade(f"cannot bind redis ({exc})")
                return None

    def _degrade(self, why: str) -> None:
        """Fall back to the in-process LRU, once, loudly. NEVER raises."""
        if self._degraded:
            return
        self._degraded = True
        self._client = None
        _log.warning(
            "tile cache: %s; falling back to an in-process LRU. Tiles are no longer shared "
            "between workers, so each worker will re-fetch the same AOI and the effective "
            "request rate against the provider is multiplied by the worker count.",
            why,
        )

    def _permitted(self, provider: str) -> bool:
        """Memoised licence check. Never raises."""
        cached = self._policy_cache.get(provider)
        if cached is not None:
            return cached
        allowed = bool(self._allows_caching(provider))  # type: ignore[operator]
        self._policy_cache[provider] = allowed
        return allowed

    def _key(self, key: TileCacheKey) -> str:
        """Return the namespaced Redis key."""
        return f"{self._namespace}:{key.to_str()}"

    def get(self, key: TileCacheKey) -> bytes | None:
        if not self._permitted(key.provider):
            return self._fallback.get(key)
        client = self._redis()
        if client is None:
            return self._fallback.get(key)
        try:
            value = client.get(self._key(key))
        except Exception as exc:  # noqa: BLE001 - a cache read must never raise
            self._degrade(f"redis GET failed ({exc})")
            return self._fallback.get(key)
        if value is None:
            with self._lock:
                self._misses += 1
            return None
        if value == _NEGATIVE_VALUE:
            with self._lock:
                self._negative_hits += 1
            return NEGATIVE_MARKER
        with self._lock:
            self._hits += 1
        return bytes(value)

    def put(self, key: TileCacheKey, data: bytes, *, ttl_s: int | None = None) -> None:
        if not self._permitted(key.provider):
            self._refuse(key)
            self._fallback.put(key, data, ttl_s=ttl_s)
            return
        self._set(key, bytes(data), ttl_s if ttl_s is not None else self._ttl_s)

    def put_negative(self, key: TileCacheKey, *, ttl_s: int = 86_400) -> None:
        if not self._permitted(key.provider):
            self._refuse(key)
            self._fallback.put_negative(key, ttl_s=ttl_s)
            return
        self._set(key, _NEGATIVE_VALUE, ttl_s)

    def _set(self, key: TileCacheKey, value: bytes, ttl_s: int) -> None:
        """SETEX one key. NEVER raises — a write failure is a cache miss."""
        client = self._redis()
        if client is None:
            self._fallback.put(key, value, ttl_s=ttl_s)
            return
        try:
            client.set(self._key(key), value, ex=max(1, int(ttl_s)))
            with self._lock:
                self._writes += 1
        except Exception as exc:  # noqa: BLE001 - a cache write must never raise
            self._degrade(f"redis SET failed ({exc})")
            self._fallback.put(key, value, ttl_s=ttl_s)

    def _refuse(self, key: TileCacheKey) -> None:
        """Record and log a licence-driven refusal. Logged ONCE per provider."""
        with self._lock:
            self._refusals += 1
            first = key.provider not in self._refused_providers
            self._refused_providers.add(key.provider)
        if first:
            _log.warning(
                "%s: terms forbid persistent caching (allows_caching=False); tiles will "
                "NOT be written to Redis and are held in an in-process LRU for this "
                "process's lifetime only. This is the licence gate working as designed.",
                key.provider,
            )

    def get_many(self, keys: Sequence[TileCacheKey]) -> dict[TileCacheKey, bytes]:
        """Batch-read via MGET.

        ★ The reason this method exists at all: stitching asks for 30-200 tiles at once,
        and N round trips to Redis for one chip is the difference between 40 ms and 2 s.
        """
        keys = list(keys)
        if not keys:
            return {}

        permitted = [k for k in keys if self._permitted(k.provider)]
        refused = [k for k in keys if not self._permitted(k.provider)]
        found: dict[TileCacheKey, bytes] = {}
        if refused:
            found.update(self._fallback.get_many(refused))
        if not permitted:
            return found

        client = self._redis()
        if client is None:
            found.update(self._fallback.get_many(permitted))
            return found
        try:
            values = client.mget([self._key(k) for k in permitted])
        except Exception as exc:  # noqa: BLE001
            self._degrade(f"redis MGET failed ({exc})")
            found.update(self._fallback.get_many(permitted))
            return found

        hits = negatives = misses = 0
        for key, value in zip(permitted, values, strict=True):
            if value is None:
                misses += 1
            elif value == _NEGATIVE_VALUE:
                found[key] = NEGATIVE_MARKER
                negatives += 1
            else:
                found[key] = bytes(value)
                hits += 1
        with self._lock:
            self._hits += hits
            self._negative_hits += negatives
            self._misses += misses
        return found

    def invalidate(self, prefix: TileCacheKeyPrefix) -> int:
        """Drop every entry under ``prefix``.

        ★ Uses SCAN, never KEYS. ``KEYS`` is O(N) over the whole keyspace and blocks the
        single-threaded Redis for the duration — on a production instance holding millions
        of tiles, that is an outage triggered by a cache-clear button.

        Returns:
            How many keys were removed. Never raises.
        """
        removed = self._fallback.invalidate(prefix)
        client = self._redis()
        if client is None:
            return removed

        variant = prefix.variant if prefix.variant is not None else "*"
        z = str(prefix.z) if prefix.z is not None else "*"
        pattern = f"{self._namespace}:tile:{prefix.provider}:{variant}:{z}:*"
        try:
            batch: list[bytes] = []
            for raw_key in client.scan_iter(match=pattern, count=500):
                batch.append(raw_key)
                if len(batch) >= 500:
                    removed += int(client.delete(*batch))
                    batch = []
            if batch:
                removed += int(client.delete(*batch))
        except Exception as exc:  # noqa: BLE001
            self._degrade(f"redis SCAN/DEL failed ({exc})")
        return removed

    def stats(self) -> CacheStats:
        with self._lock:
            return CacheStats(
                backend=self.backend,
                hits=self._hits,
                misses=self._misses,
                negative_hits=self._negative_hits,
                writes=self._writes,
                refusals=self._refusals,
                evictions=0,
                entries=None,
                bytes_used=None,
            )

    def close(self) -> None:
        """Close the Redis connection. Idempotent. Never raises."""
        client, self._client = self._client, None
        if client is not None:
            try:
                client.close()
            except Exception as exc:  # noqa: BLE001 - shutdown must not raise
                _log.debug("error closing redis client: %s", exc)
