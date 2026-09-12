"""``TileCache`` — the tile cache interface (§1.5 of ``40-imagery.md``).

★ **CACHING IS LICENCE-GATED, NOT MERELY A PERFORMANCE CHOICE.** ``DiskTileCache`` and
``RedisTileCache`` consult ``ProviderCapabilities.allows_caching`` and **refuse to persist**
tiles from providers whose terms prohibit it, falling back to in-process LRU with a
WARNING. Encoding this in the cache layer means a provider with restrictive terms cannot
accidentally accumulate a permanent on-disk copy via a background job — compliance is
enforced by the cache, not by developer memory.
"""

from __future__ import annotations

import abc
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

__all__ = [
    "NEGATIVE_MARKER",
    "CacheStats",
    "TileCache",
    "TileCacheKey",
    "TileCacheKeyPrefix",
]

NEGATIVE_MARKER: Final[bytes] = b""
"""What a cached "the provider has no tile here" looks like on the wire.

★ An empty body is not a legal tile in any format, so it cannot collide with real data.
``get()`` returning ``b""`` therefore means *"asked and answered: nothing here"*, which is
**distinct from None** (*"never asked"*). Collapsing the two produces re-fetch storms over
ocean and void.
"""

_VARIANT_SAFE: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9._@+-]")


@dataclass(frozen=True, slots=True)
class TileCacheKey:
    """A tile's cache identity.

    ★ ``variant`` prevents the single nastiest cache bug in this domain: a Sentinel L2A
    June composite and an October composite are the same ``(z, x, y)`` and utterly
    different pixels. Without ``variant`` in the key, a re-run silently matches against the
    wrong season's imagery and produces **confidently wrong coordinates**. The same applies
    to ``@2x`` retina tiles, Mapbox style ids, basemap kind, and an orthophoto file's hash.
    """

    provider: str
    z: int
    x: int
    y: int
    variant: str = "default"
    """``"@2x"``, ``"l2a-2024-06"``, a style id, a basemap kind, an ortho file hash."""

    def to_str(self) -> str:
        """Return the canonical string key.

        Returns:
            ``tile:{provider}:{variant}:{z}:{x}:{y}``.
        """
        return f"tile:{self.provider}:{self.variant}:{self.z}:{self.x}:{self.y}"

    def safe_variant(self) -> str:
        """Return ``variant`` reduced to one safe path component.

        ★ ``variant`` reaches a filesystem path in ``DiskTileCache``, and it is not always
        an internal constant — a Mapbox style id or a Sentinel mosaic window can arrive from
        configuration. Two distinct hazards, both closed here:

        1. **Separators and exotica** -> ``_``. A ``/`` would silently create a directory
           level that ``invalidate()`` could then never find; a NUL or a newline would break
           the Redis key.
        2. **Pure-dot components** -> ``default``. ★ This is the subtle one. ``.`` and
           ``..`` survive rule 1 untouched (a dot is a legal filename character, and
           ``mapbox.satellite`` needs it), but as a **path component** ``..`` is traversal:
           ``{root}/{provider}/../{z}/{x}/{y}`` escapes the cache root by a level. Only a
           component that is *nothing but* dots is dangerous — ``..foo`` is an ordinary
           filename — so that is exactly what is rejected.
        """
        cleaned = _VARIANT_SAFE.sub("_", self.variant)
        if not cleaned or not cleaned.strip("."):
            return "default"
        return cleaned


@dataclass(frozen=True, slots=True)
class TileCacheKeyPrefix:
    """A partial key, for bulk invalidation.

    Fields left None match everything at that level. ``TileCacheKeyPrefix("mapbox_satellite")``
    matches every Mapbox tile; adding ``z=18`` narrows it to that zoom.
    """

    provider: str
    variant: str | None = None
    z: int | None = None

    def matches(self, key: TileCacheKey) -> bool:
        """True iff ``key`` falls under this prefix."""
        if key.provider != self.provider:
            return False
        if self.variant is not None and key.variant != self.variant:
            return False
        return not (self.z is not None and key.z != self.z)


@dataclass(frozen=True, slots=True)
class CacheStats:
    """A cache's counters. ★ Diagnostic only: never control flow."""

    backend: str
    hits: int = 0
    misses: int = 0
    negative_hits: int = 0
    writes: int = 0
    refusals: int = 0
    """★ Writes REFUSED because the provider's terms forbid caching. A non-zero value here
    is the licence gate working, not an error."""
    evictions: int = 0
    entries: int | None = None
    bytes_used: int | None = None

    @property
    def hit_rate(self) -> float:
        """Hits over total lookups, or 0.0 when nothing has been asked."""
        total = self.hits + self.negative_hits + self.misses
        return (self.hits + self.negative_hits) / total if total else 0.0


class TileCache(abc.ABC):
    """Encoded tile bytes, keyed by ``TileCacheKey``.

    Implementations store **encoded bytes**, never decoded arrays: a decoded 256x256 RGB
    tile is 196 KB, while its JPEG is ~15 KB, and the cache's whole point is to hold a lot
    of them.
    """

    @property
    @abc.abstractmethod
    def backend(self) -> str:
        """``"memory"`` | ``"disk"`` | ``"redis"``."""

    @abc.abstractmethod
    def get(self, key: TileCacheKey) -> bytes | None:
        """Look a tile up.

        Args:
            key: The tile's identity.

        Returns:
            The encoded bytes; ``NEGATIVE_MARKER`` (``b""``) when the provider is known to
            have nothing here; None when we have never asked. ★ The three-way answer is the
            point — see ``NEGATIVE_MARKER``.
        """

    @abc.abstractmethod
    def put(self, key: TileCacheKey, data: bytes, *, ttl_s: int | None = None) -> None:
        """Store a tile.

        ★ Silently a no-op when the provider's terms forbid caching — see
        ``allows_caching`` on the cache's construction. NEVER raises on a storage failure:
        a full disk degrades to a cache miss, not to a failed tile request.

        Args:
            key: The tile's identity.
            data: Encoded bytes.
            ttl_s: Override the cache's default TTL.
        """

    @abc.abstractmethod
    def get_many(self, keys: Sequence[TileCacheKey]) -> dict[TileCacheKey, bytes]:
        """Batch-read.

        ★ Stitching asks for 30-200 tiles at once; N round trips to Redis for one chip is
        the difference between 40 ms and 2 s.

        Args:
            keys: The tiles to look up.

        Returns:
            Only the keys that were present. Negatives are included, with a ``b""`` value.
        """

    @abc.abstractmethod
    def put_negative(self, key: TileCacheKey, *, ttl_s: int = 86_400) -> None:
        """Record "the provider has no tile here".

        Prevents re-fetch storms over ocean and void. Distinct from absent.

        ★ The default TTL is a day rather than the tile TTL: coverage gaps do get filled,
        and a permanent negative would hide new imagery forever.

        Args:
            key: The tile's identity.
            ttl_s: How long to remember.
        """

    def contains(self, key: TileCacheKey) -> bool:
        """Report whether a POSITIVE entry exists, without necessarily reading it.

        ★ For coverage/estimation sweeps over thousands of keys, where ``get()``'s
        byte-read would be pure waste. A cached negative is NOT "contained" — the caller
        is asking "do I hold imagery here", and the answer for a negative is no.
        Implementations should override with a cheaper check where one exists (a disk
        ``stat``); the default reads.
        """
        value = self.get(key)
        return value is not None and value != NEGATIVE_MARKER

    @abc.abstractmethod
    def invalidate(self, prefix: TileCacheKeyPrefix) -> int:
        """Drop every entry under ``prefix``.

        Args:
            prefix: What to drop.

        Returns:
            How many entries were removed.
        """

    @abc.abstractmethod
    def stats(self) -> CacheStats:
        """Return this cache's counters. Never raises."""

    def close(self) -> None:
        """Release any resources. Idempotent. Default: nothing to do."""
        return None
