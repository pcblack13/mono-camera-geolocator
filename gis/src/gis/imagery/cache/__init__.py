"""The tile cache package.

★ **``redis_cache`` IS IMPORTED LAZILY, VIA A MODULE ``__getattr__`` (PEP 562)** (§11.3, and
§2.3's tree says so in as many words). ``from gis.imagery.cache import RedisTileCache``
works; ``import gis.imagery.cache`` with redis absent **also** works, because nothing here
touches ``redis_cache`` until someone actually names it.

Without this, ``cd gis && pytest`` would die at COLLECTION on every machine without redis
installed — which is this one — before a single test ran.

``get_tile_cache()`` is the factory: it resolves a backend name to an instance and
**degrades rather than fails**. Asking for ``redis`` on a machine with no redis gets a
``DiskTileCache`` and a WARNING, never a traceback (L11).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Final

from gis.imagery.cache.base import (
    NEGATIVE_MARKER,
    CacheStats,
    TileCache,
    TileCacheKey,
    TileCacheKeyPrefix,
)
from gis.imagery.cache.disk import DiskTileCache
from gis.imagery.cache.memory import LRUTileCache

if TYPE_CHECKING:  # pragma: no cover - type-checking only, never at runtime
    from gis.imagery.cache.redis_cache import RedisTileCache

__all__ = [
    "CACHE_BACKENDS",
    "NEGATIVE_MARKER",
    "CacheStats",
    "DiskTileCache",
    "LRUTileCache",
    "RedisTileCache",
    "TileCache",
    "TileCacheKey",
    "TileCacheKeyPrefix",
    "get_tile_cache",
    "redis_cache_available",
]

_log = logging.getLogger("gis.imagery.cache")

CACHE_BACKENDS: Final[tuple[str, ...]] = ("memory", "disk", "redis")
"""Every ``LE_IMAGERY_TILE_CACHE_BACKEND`` value. ``memory`` in tests, ``disk`` in dev,
``redis`` in prod."""


def __getattr__(name: str) -> Any:
    """Resolve ``RedisTileCache`` lazily. ★ THE POINT OF THIS MODULE (PEP 562).

    Importing ``gis.imagery.cache.redis_cache`` at module scope would be harmless on its
    own — that module binds ``redis`` inside its methods — but the belt-and-braces
    laziness here means the cache package has **no** import-time relationship with redis at
    all, and the property cannot be broken by a future edit to ``redis_cache.py``.

    Args:
        name: The attribute being looked up.

    Returns:
        The attribute.

    Raises:
        AttributeError: For any name this package does not define. ★ Note the type: an
            ``ImportError`` here would be a lie, since the module imports fine — it is the
            *dependency* that may be missing, and that is reported by
            ``redis_cache_available()``, not by an exception.
    """
    if name == "RedisTileCache":
        from gis.imagery.cache.redis_cache import RedisTileCache  # noqa: PLC0415

        return RedisTileCache
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """Include the lazily-resolved names in ``dir()`` and in tab completion."""
    return sorted(__all__)


def redis_cache_available() -> tuple[bool, str | None]:
    """Report whether the Redis cache backend can be used. ★ Total; never raises.

    Returns:
        ``(available, reason)``. ``reason`` is None when available, else the sentence
        ``GET /capabilities`` shows the operator.
    """
    from gis.imagery.cache.redis_cache import is_available  # noqa: PLC0415

    return is_available()


def get_tile_cache(
    backend: str = "disk",
    *,
    directory: str = "./data/tile_cache",
    redis_url: str = "redis://localhost:6379/0",
    ttl_s: int = 2_592_000,
    max_bytes: int = 21_474_836_480,
) -> TileCache:
    """Build a tile cache by backend name. ★ NEVER raises; always returns a working cache.

    Degradation ladder, per L11 — every step is a WARNING plus a fallback, never an error:

    * ``redis`` with redis absent or unreachable -> ``DiskTileCache``.
    * ``disk`` with an unusable directory -> ``LRUTileCache``.
    * An unknown backend name -> ``DiskTileCache``.

    ★ There is no failure mode. A cache is an optimisation, and an optimisation that can
    take imagery down has stopped being one.

    Args:
        backend: ``memory`` | ``disk`` | ``redis``. ``LE_IMAGERY_TILE_CACHE_BACKEND``.
        directory: Disk cache root. ``LE_IMAGERY_TILE_CACHE_DIR``.
        redis_url: ``LE_REDIS_URL``.
        ttl_s: Default entry lifetime. ★ Several providers' terms CAP this — see
            ``docs/legal/imagery-terms.md``.
        max_bytes: Advisory size cap for the disk cache.

    Returns:
        A ``TileCache``. Its ``.backend`` reports what was ACTUALLY built, which may differ
        from ``backend`` if something degraded — so a caller reporting provenance reports
        the truth.
    """
    name = (backend or "disk").strip().lower()

    if name not in CACHE_BACKENDS:
        _log.warning(
            "unknown tile cache backend %r; expected one of %s. Using 'disk'.",
            backend,
            ", ".join(CACHE_BACKENDS),
        )
        name = "disk"

    if name == "memory":
        return LRUTileCache(max_bytes=min(max_bytes, 512 * 1024 * 1024))

    if name == "redis":
        available, reason = redis_cache_available()
        if not available:
            _log.warning(
                "tile cache backend 'redis' requested but %s; using the disk cache at %s. "
                "Tiles will not be shared between workers, so each worker re-fetches the "
                "same AOI.",
                reason,
                directory,
            )
        else:
            from gis.imagery.cache.redis_cache import RedisTileCache  # noqa: PLC0415

            return RedisTileCache(redis_url, ttl_s=ttl_s)

    return _disk_or_memory(directory, ttl_s, max_bytes)


def _disk_or_memory(directory: str, ttl_s: int, max_bytes: int) -> TileCache:
    """Build a ``DiskTileCache``, or an LRU when the directory is unusable.

    ★ The directory is probed HERE, once, rather than discovered on the first write inside
    a Celery task. A read-only mount should degrade at construction with one clear log
    line, not silently miss on every tile for the life of the process.
    """
    from pathlib import Path  # noqa: PLC0415

    try:
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".le-write-probe"
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as exc:
        _log.warning(
            "tile cache directory %s is not writable (%s); using an in-process LRU. The "
            "cache will not survive this process.",
            directory,
            exc,
        )
        return LRUTileCache(max_bytes=min(max_bytes, 512 * 1024 * 1024))
    return DiskTileCache(directory, ttl_s=ttl_s, max_bytes=max_bytes)
