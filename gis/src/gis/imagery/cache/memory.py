"""``LRUTileCache`` — in-process, always available, zero dependencies.

The default in tests and, crucially, **the terminal fallback for every provider whose
terms forbid persistent caching**: an in-process, request-lifetime LRU is caching that
cannot outlive the process, accumulate on a disk, or be shared — which is precisely what
those terms permit and no more.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass

from gis.imagery.cache.base import (
    NEGATIVE_MARKER,
    CacheStats,
    TileCache,
    TileCacheKey,
    TileCacheKeyPrefix,
)

__all__ = ["LRUTileCache"]


@dataclass(slots=True)
class _Entry:
    """One cached tile plus its expiry."""

    data: bytes
    expires_at: float | None
    """Monotonic deadline; None means no expiry."""

    def expired(self, now: float) -> bool:
        """True iff this entry is past its TTL."""
        return self.expires_at is not None and now >= self.expires_at


class LRUTileCache(TileCache):
    """A bounded in-process tile cache, evicting least-recently-used first.

    Bounded by **both** entry count and total bytes, because either alone is a leak: 20 000
    Sentinel tiles is a very different amount of memory from 20 000 blank ocean tiles, and
    a Celery worker that grows without limit is an OOM kill mid-job.

    Thread-safe: Celery calls this from a worker pool.
    """

    def __init__(
        self,
        *,
        max_entries: int = 4096,
        max_bytes: int = 256 * 1024 * 1024,
        default_ttl_s: int | None = None,
    ) -> None:
        """Build the cache.

        Args:
            max_entries: Hard cap on entry count.
            max_bytes: Hard cap on total stored bytes.
            default_ttl_s: Default expiry. None means entries live until evicted — the
                right default in-process, where the process lifetime is the bound.

        Raises:
            ValueError: If a cap is not positive.
        """
        if max_entries <= 0:
            raise ValueError(f"max_entries must be > 0, got {max_entries}")
        if max_bytes <= 0:
            raise ValueError(f"max_bytes must be > 0, got {max_bytes}")
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._default_ttl_s = default_ttl_s
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._keys: dict[str, TileCacheKey] = {}
        self._bytes = 0
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._negative_hits = 0
        self._writes = 0
        self._evictions = 0

    @property
    def backend(self) -> str:
        return "memory"

    def get(self, key: TileCacheKey) -> bytes | None:
        skey = key.to_str()
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(skey)
            if entry is None:
                self._misses += 1
                return None
            if entry.expired(now):
                self._drop(skey)
                self._misses += 1
                return None
            self._entries.move_to_end(skey)
            if entry.data == NEGATIVE_MARKER:
                self._negative_hits += 1
            else:
                self._hits += 1
            return entry.data

    def put(self, key: TileCacheKey, data: bytes, *, ttl_s: int | None = None) -> None:
        self._store(key, bytes(data), ttl_s if ttl_s is not None else self._default_ttl_s)

    def put_negative(self, key: TileCacheKey, *, ttl_s: int = 86_400) -> None:
        self._store(key, NEGATIVE_MARKER, ttl_s)

    def _store(self, key: TileCacheKey, data: bytes, ttl_s: int | None) -> None:
        """Insert or replace an entry, then evict down to the caps."""
        skey = key.to_str()
        expires_at = None if ttl_s is None else time.monotonic() + ttl_s
        with self._lock:
            if skey in self._entries:
                self._drop(skey)
            if len(data) > self._max_bytes:
                # A single tile larger than the whole cache: caching it would evict
                # everything and then not fit. Refuse rather than thrash.
                return
            self._entries[skey] = _Entry(data=data, expires_at=expires_at)
            self._keys[skey] = key
            self._bytes += len(data)
            self._writes += 1
            self._evict_locked()

    def _drop(self, skey: str) -> None:
        """Remove one entry. Caller holds the lock."""
        entry = self._entries.pop(skey, None)
        if entry is not None:
            self._bytes -= len(entry.data)
            self._keys.pop(skey, None)

    def _evict_locked(self) -> None:
        """Evict LRU entries until both caps are satisfied. Caller holds the lock."""
        while self._entries and (
            len(self._entries) > self._max_entries or self._bytes > self._max_bytes
        ):
            oldest, _ = next(iter(self._entries.items()))
            self._drop(oldest)
            self._evictions += 1

    def get_many(self, keys: Sequence[TileCacheKey]) -> dict[TileCacheKey, bytes]:
        found: dict[TileCacheKey, bytes] = {}
        for key in keys:
            value = self.get(key)
            if value is not None:
                found[key] = value
        return found

    def invalidate(self, prefix: TileCacheKeyPrefix) -> int:
        with self._lock:
            doomed = [
                skey for skey, key in self._keys.items() if prefix.matches(key)
            ]
            for skey in doomed:
                self._drop(skey)
            return len(doomed)

    def stats(self) -> CacheStats:
        with self._lock:
            return CacheStats(
                backend=self.backend,
                hits=self._hits,
                misses=self._misses,
                negative_hits=self._negative_hits,
                writes=self._writes,
                refusals=0,
                evictions=self._evictions,
                entries=len(self._entries),
                bytes_used=self._bytes,
            )

    def clear(self) -> None:
        """Drop everything. For tests."""
        with self._lock:
            self._entries.clear()
            self._keys.clear()
            self._bytes = 0
