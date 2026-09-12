"""``DiskTileCache`` — content on disk, the default in dev.

★ **THIS CACHE ENFORCES A LICENCE CONDITION.** Before writing a single byte it asks whether
the provider's terms permit caching (``ProviderCapabilities.allows_caching``). When they do
not, **the write is refused**, the tile goes to an in-process LRU instead, and a WARNING is
logged. That is what stops a provider with restrictive terms from accidentally
accumulating a permanent on-disk copy of its imagery via a background job. Compliance is
enforced by the cache, not by developer memory — violating it requires editing this file,
not merely forgetting a rule.

★ **Every storage failure degrades to a cache miss, never to an error.** A full disk, a
read-only mount, a permissions change: all of them make imagery slower, none of them make
it fail. A cache that can fail a request is a liability, not an optimisation.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from gis.imagery.cache.base import (
    NEGATIVE_MARKER,
    CacheStats,
    TileCache,
    TileCacheKey,
    TileCacheKeyPrefix,
)
from gis.imagery.cache.memory import LRUTileCache

__all__ = ["DiskTileCache"]

_log = logging.getLogger("gis.imagery.cache.disk")

_DATA_SUFFIX: Final[str] = ".tile"
_NEGATIVE_SUFFIX: Final[str] = ".negative"
"""★ A fixed suffix rather than the source format's extension.

``40-imagery.md`` sketches ``{y}.{ext}``, but the extension is not knowable from a
``TileCacheKey`` — so a reader would have to glob a directory per lookup, and a provider
that switched from JPEG to WebP would silently orphan its own cache. The bytes are opaque
to this layer; the provider decodes them. A fixed suffix makes the path a pure function of
the key, which is what makes ``get`` one stat call and ``invalidate`` one subtree removal.
"""


def _provider_allows_caching(provider: str) -> bool:
    """Ask the registry whether this provider's terms permit persistent caching.

    ★ CALL-TIME import of the registry. At module scope it would be a cycle
    (registry -> providers -> ... -> cache), and it would drag every provider class into
    any module that merely wanted an LRU.

    Args:
        provider: Registry key.

    Returns:
        The provider's ``allows_caching`` capability. ★ **False on any doubt** — an unknown
        provider, an unconstructable one, a raising ``capabilities()``. The safe default for
        a licence gate is "do not persist": the cost of being wrong is a slower cache one
        way and a terms violation the other, and those are not comparable.
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


def _unlink_quiet(path: Path) -> bool:
    """Delete ``path``; report success. Never raises — maintenance must not fail requests."""
    try:
        path.unlink()
        return True
    except OSError as exc:
        _log.warning("cannot remove %s during sweep: %s", path, exc)
        return False


def _looks_like_image(data: bytes) -> bool:
    """True iff ``data`` starts like a JPEG, PNG or WebP — the formats providers serve.

    ★ A magic-byte check, not a decode: the hot path cannot afford a full decode per hit,
    and a wrong-but-well-formed image is the provider's problem, not the cache's. What
    this catches is truncation-to-empty and non-image garbage.
    """
    if len(data) < 12:
        return False
    return (
        data[:3] == b"\xff\xd8\xff"
        or data[:8] == b"\x89PNG\r\n\x1a\n"
        or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")
    )


def _provider_ttls(provider: str) -> tuple[int | None, int | None]:
    """Ask the registry for a provider's own ``(ttl, negative_ttl)``, seconds.

    ★ CALL-TIME import, like :func:`_provider_allows_caching`, and ``(None, None)`` on any
    doubt — an unknown provider must degrade to the global policy, never to a crash.
    """
    try:
        from gis.imagery.registry import (  # noqa: PLC0415
            provider_cache_ttl_seconds,
            provider_negative_cache_ttl_seconds,
        )

        return (
            provider_cache_ttl_seconds(provider),
            provider_negative_cache_ttl_seconds(provider),
        )
    except Exception:  # noqa: BLE001 - a cache must never take a request down
        return (None, None)


def _count_tiles(base: Path) -> int:
    """Count cache files under ``base``. Never raises."""
    try:
        return sum(
            1
            for p in base.rglob("*")
            if p.is_file() and p.suffix in (_DATA_SUFFIX, _NEGATIVE_SUFFIX)
        )
    except OSError:  # pragma: no cover - permissions/races
        return 0


class DiskTileCache(TileCache):
    """A filesystem tile cache: ``{root}/{provider}/{variant}/{z}/{x}/{y}.tile``.

    Safe across restarts and across processes on the same host. **Not** shared across
    replicas — that is what ``RedisTileCache`` is for, and why Redis is the prod default.

    Args:
        directory: Cache root. Created on demand.
        ttl_s: Default entry lifetime, swept by mtime.
        max_bytes: Advisory size cap, reported in ``stats()``. ★ Enforcement is
            ``tasks.maintenance``'s job, not this class's: walking a 20 GB tree to find an
            LRU victim on the tile hot path would cost far more than the eviction saves.
        allows_caching: Predicate over a provider name. Defaults to consulting the
            provider's own ``ProviderCapabilities.allows_caching``. ★ Override only in
            tests.
        fallback: Where refused tiles go. Defaults to a private ``LRUTileCache``.
    """

    def __init__(
        self,
        directory: str | Path = "./data/tile_cache",
        *,
        ttl_s: int = 2_592_000,
        max_bytes: int = 21_474_836_480,
        allows_caching: "object | None" = None,
        fallback: TileCache | None = None,
    ) -> None:
        self._root = Path(directory)
        self._ttl_s = int(ttl_s)
        self._max_bytes = int(max_bytes)
        self._allows_caching = allows_caching or _provider_allows_caching
        self._fallback = fallback if fallback is not None else LRUTileCache()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._negative_hits = 0
        self._writes = 0
        self._refusals = 0
        self._evictions_swept = 0
        self._refused_providers: set[str] = set()
        self._policy_cache: dict[str, bool] = {}
        self._ttl_cache: dict[str, tuple[int, int]] = {}

    @property
    def backend(self) -> str:
        return "disk"

    @property
    def fallback(self) -> TileCache:
        """The cache that refused tiles go to. ★ Exposed so a test can prove the refusal
        landed somewhere rather than vanishing."""
        return self._fallback

    def _permitted(self, provider: str) -> bool:
        """Memoised licence check. Never raises."""
        cached = self._policy_cache.get(provider)
        if cached is not None:
            return cached
        allowed = bool(self._allows_caching(provider))  # type: ignore[operator]
        self._policy_cache[provider] = allowed
        return allowed

    def _ttls_for(self, provider: str) -> tuple[int, int]:
        """Memoised effective ``(ttl, negative_ttl)`` for a provider, seconds.

        ★ The STRICTER of the operator's global TTL and the provider's own ToS cap wins:
        a Mapbox tile expires on Mapbox's clock even when the global TTL is longer, and
        an operator who set a SHORTER global TTL is likewise honoured. ``0`` (no global
        expiry) defers entirely to the provider's cap.
        """
        cached = self._ttl_cache.get(provider)
        if cached is not None:
            return cached
        p_ttl, p_neg = _provider_ttls(provider)
        if p_ttl is None or p_ttl <= 0:
            ttl = self._ttl_s
        elif self._ttl_s <= 0:
            ttl = p_ttl
        else:
            ttl = min(self._ttl_s, p_ttl)
        neg = p_neg if p_neg is not None and p_neg > 0 else 86_400
        result = (ttl, neg)
        self._ttl_cache[provider] = result
        return result

    def _path(self, key: TileCacheKey, *, negative: bool = False) -> Path:
        """Return the on-disk path for a key.

        ``safe_variant()`` is what stops a hostile or careless ``variant`` (``../../etc``)
        from escaping the cache root.
        """
        suffix = _NEGATIVE_SUFFIX if negative else _DATA_SUFFIX
        return (
            self._root
            / key.provider
            / key.safe_variant()
            / str(key.z)
            / str(key.x)
            / f"{key.y}{suffix}"
        )

    def _fresh(self, path: Path, ttl_s: int) -> bool:
        """True iff ``path`` exists and is within its TTL. Never raises."""
        try:
            age = time.time() - path.stat().st_mtime
        except OSError:
            return False
        if ttl_s <= 0:
            return True
        if age > ttl_s:
            # Expired: drop it now, so a cold AOI does not keep stale bytes forever.
            try:
                path.unlink()
            except OSError:
                pass
            return False
        return True

    def get(self, key: TileCacheKey) -> bytes | None:
        if not self._permitted(key.provider):
            return self._fallback.get(key)

        ttl_s, negative_ttl_s = self._ttls_for(key.provider)
        negative_path = self._path(key, negative=True)
        if self._fresh(negative_path, negative_ttl_s):
            with self._lock:
                self._negative_hits += 1
            return NEGATIVE_MARKER

        path = self._path(key)
        if not self._fresh(path, ttl_s):
            with self._lock:
                self._misses += 1
            return None
        try:
            data = path.read_bytes()
        except OSError as exc:
            _log.debug("disk cache read failed for %s: %s", key.to_str(), exc)
            with self._lock:
                self._misses += 1
            return None
        if not _looks_like_image(data):
            # ★ CORRUPTION IS A CACHE MISS, NEVER AN ERROR. A truncated or garbage file
            #   (power loss mid-write on a non-atomic filesystem, bit rot, a stray tool)
            #   must not decode to garbage pixels a surveyor then clicks on. Drop it and
            #   let the read-through path fetch a fresh copy.
            _log.warning(
                "disk cache entry %s is not a decodable image (%d bytes); dropping it",
                key.to_str(),
                len(data),
            )
            try:
                path.unlink()
            except OSError:
                pass
            with self._lock:
                self._misses += 1
            return None
        with self._lock:
            self._hits += 1
        return data

    def contains(self, key: TileCacheKey) -> bool:
        """One ``stat`` — no read, no counter churn. Coverage sweeps call this a lot."""
        if not self._permitted(key.provider):
            return self._fallback.contains(key)
        ttl_s, _neg = self._ttls_for(key.provider)
        return self._fresh(self._path(key), ttl_s)

    def put(self, key: TileCacheKey, data: bytes, *, ttl_s: int | None = None) -> None:
        if not self._permitted(key.provider):
            self._refuse(key)
            self._fallback.put(key, data, ttl_s=ttl_s)
            return
        self._write(self._path(key), bytes(data))

    def put_negative(self, key: TileCacheKey, *, ttl_s: int = 86_400) -> None:
        if not self._permitted(key.provider):
            self._refuse(key)
            self._fallback.put_negative(key, ttl_s=ttl_s)
            return
        self._write(self._path(key, negative=True), NEGATIVE_MARKER)

    def _refuse(self, key: TileCacheKey) -> None:
        """Record and log a licence-driven refusal.

        ★ Logged ONCE per provider, at WARNING. Per-tile it would emit thousands of lines
        for one chip and get filtered out — which would turn a compliance signal into
        noise, and then into silence.
        """
        with self._lock:
            self._refusals += 1
            first = key.provider not in self._refused_providers
            self._refused_providers.add(key.provider)
        if first:
            _log.warning(
                "%s: terms forbid persistent caching (allows_caching=False); tiles will "
                "NOT be written to %s and are held in an in-process LRU for this process's "
                "lifetime only. This is the licence gate working as designed.",
                key.provider,
                self._root,
            )

    def _write(self, path: Path, data: bytes) -> None:
        """Write atomically. NEVER raises — a storage failure is a cache miss."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # ★ Write to a temp file in the SAME directory, then rename. A half-written
            #   tile that a concurrent reader picks up decodes to garbage or, worse, to a
            #   plausible partial image. os.replace is atomic within a filesystem.
            fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".part")
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                os.replace(tmp_name, path)
            except BaseException:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
            with self._lock:
                self._writes += 1
        except OSError as exc:
            _log.warning(
                "disk cache write failed for %s (%s); continuing without caching this tile",
                path,
                exc,
            )

    def get_many(self, keys: Sequence[TileCacheKey]) -> dict[TileCacheKey, bytes]:
        found: dict[TileCacheKey, bytes] = {}
        for key in keys:
            value = self.get(key)
            if value is not None:
                found[key] = value
        return found

    def invalidate(self, prefix: TileCacheKeyPrefix) -> int:
        """Drop every entry under ``prefix``.

        Args:
            prefix: What to drop. A None field matches every value at that level.

        Returns:
            How many entries were removed, across this cache AND its refusal fallback.
            ★ Never raises: an un-deletable file is logged and skipped, because a failed
            invalidation must not become a failed request.
        """
        removed = self._fallback.invalidate(prefix)

        # Layout: {root}/{provider}/{variant}/{z}/{x}/{y}.tile
        base = self._root / prefix.provider
        if prefix.variant is not None:
            base = base / TileCacheKey(prefix.provider, 0, 0, 0, prefix.variant).safe_variant()
            if prefix.z is not None:
                base = base / str(prefix.z)
        if not base.exists():
            return removed

        # ★ A whole-subtree removal only when the prefix names a contiguous subtree. With
        #   variant=None and z set, the z levels are scattered under every variant, so the
        #   files must be selected individually rather than by dropping a directory.
        if prefix.variant is not None or prefix.z is None:
            removed += _count_tiles(base)
            shutil.rmtree(base, ignore_errors=True)
            return removed

        for path in base.glob(f"*/{prefix.z}/*/*"):
            if path.is_file() and path.suffix in (_DATA_SUFFIX, _NEGATIVE_SUFFIX):
                try:
                    path.unlink()
                    removed += 1
                except OSError as exc:
                    _log.warning("cannot invalidate %s: %s", path, exc)
        return removed

    def sweep(
        self,
        *,
        negative_ttl_s: int = 86_400,
        part_ttl_s: int = 3_600,
        max_bytes: int | None = None,
    ) -> dict[str, int]:
        """One full maintenance pass: expiry, negatives, temp files, corruption, size cap.

        ★ NOT the hot path. ``get``/``put`` never walk the tree; this does, once, when a
        maintenance moment arrives (startup, hourly, after a pre-cache run). Desktop-safe:
        no Celery, no Redis, just the filesystem. Never raises — an un-deletable file is
        skipped, because failed maintenance must not become failed imagery.

        Args:
            negative_ttl_s: Max age for ``.negative`` markers.
            part_ttl_s: Max age for orphaned ``.part`` temp files (a crash mid-write).
            max_bytes: Byte cap to enforce, oldest-mtime-first. None means the cache's
                own ``max_bytes``.

        Returns:
            Counters: ``expired``, ``expired_negative``, ``removed_corrupt``,
            ``removed_temp``, ``evicted``, ``remaining_bytes``, ``remaining_entries``.
        """
        cap = self._max_bytes if max_bytes is None else int(max_bytes)
        now = time.time()
        expired = expired_negative = removed_corrupt = removed_temp = 0
        survivors: list[tuple[Path, int, float]] = []

        try:
            walker = list(self._root.rglob("*"))
        except OSError:
            walker = []
        for path in walker:
            try:
                if not path.is_file():
                    continue
                st = path.stat()
            except OSError:
                continue
            age = now - st.st_mtime
            if path.suffix == ".part":
                if age > part_ttl_s and _unlink_quiet(path):
                    removed_temp += 1
                continue
            # Per-provider TTLs: the provider is the first path component under the root.
            try:
                tile_provider = path.relative_to(self._root).parts[0]
                ttl_s, neg_ttl_s = self._ttls_for(tile_provider)
            except (ValueError, IndexError):
                ttl_s, neg_ttl_s = self._ttl_s, negative_ttl_s
            if path.suffix == _NEGATIVE_SUFFIX:
                effective_neg = min(neg_ttl_s, negative_ttl_s) if negative_ttl_s > 0 else neg_ttl_s
                if effective_neg > 0 and age > effective_neg and _unlink_quiet(path):
                    expired_negative += 1
                continue
            if path.suffix != _DATA_SUFFIX:
                continue
            if ttl_s > 0 and age > ttl_s:
                if _unlink_quiet(path):
                    expired += 1
                continue
            if st.st_size == 0:
                # A zero-byte .tile can only be a failed write that dodged the atomic
                # rename; a legal negative lives under _NEGATIVE_SUFFIX.
                if _unlink_quiet(path):
                    removed_corrupt += 1
                continue
            survivors.append((path, st.st_size, st.st_mtime))

        evicted = 0
        total = sum(size for _p, size, _m in survivors)
        if cap > 0 and total > cap:
            survivors.sort(key=lambda e: e[2])  # oldest first — LRU by mtime
            kept: list[tuple[Path, int, float]] = []
            for path, size, mtime in survivors:
                if total > cap and _unlink_quiet(path):
                    total -= size
                    evicted += 1
                else:
                    kept.append((path, size, mtime))
            survivors = kept

        with self._lock:
            self._evictions_swept = getattr(self, "_evictions_swept", 0) + evicted
        return {
            "expired": expired,
            "expired_negative": expired_negative,
            "removed_corrupt": removed_corrupt,
            "removed_temp": removed_temp,
            "evicted": evicted,
            "remaining_bytes": int(total),
            "remaining_entries": len(survivors),
        }

    def sample_average_tile_size(self, provider: str, *, limit: int = 256) -> int | None:
        """Mean size of up to ``limit`` cached tiles for ``provider``, bytes.

        ★ For STORAGE ESTIMATION before a pre-cache run: real bytes from this operator's
        own AOI beat any constant. None when nothing is cached yet — the caller falls
        back to a stated default rather than a fabricated measurement.
        """
        base = self._root / provider
        sizes: list[int] = []
        try:
            for path in base.rglob(f"*{_DATA_SUFFIX}"):
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                if size > 0:
                    sizes.append(size)
                if len(sizes) >= limit:
                    break
        except OSError:
            return None
        if not sizes:
            return None
        return sum(sizes) // len(sizes)

    def stats(self) -> CacheStats:
        with self._lock:
            hits, misses = self._hits, self._misses
            negative_hits, writes, refusals = self._negative_hits, self._writes, self._refusals
        return CacheStats(
            backend=self.backend,
            hits=hits,
            misses=misses,
            negative_hits=negative_hits,
            writes=writes,
            refusals=refusals,
            evictions=self._evictions_swept,
            entries=None,
            bytes_used=None,
        )
