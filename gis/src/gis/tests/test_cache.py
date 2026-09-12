"""IU-11 · the tile cache.

★ The obligations this suite discharges (§13.1 IU-11):

* **A provider with ``allows_caching=False`` causes ``DiskTileCache`` to REFUSE the write**
  and fall back to LRU with a warning. *This is a licence control, not a performance
  choice — it is asserted by checking that nothing reaches the disk.*
* **``TileCacheKey.variant`` distinguishes two seasons of the same ``(z, x, y)``.**

Plus the invariants that keep a cache from becoming a liability: the three-way get, bounded
memory, path-traversal containment, and degradation-never-failure.

NO NETWORK. NO REDIS. ``redis`` is blocked in ``sys.modules`` for the Redis tests, which is
how they assert the degradation path on a machine that has no Redis to talk to.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from gis.imagery.cache import (
    NEGATIVE_MARKER,
    DiskTileCache,
    LRUTileCache,
    TileCache,
    TileCacheKey,
    TileCacheKeyPrefix,
    get_tile_cache,
    redis_cache_available,
)

_ESRI = "esri_world_imagery"  # allows_caching=True
_GOOGLE = "google_maps_static"  # ★ allows_caching=False — the licence-gated one
_SENTINEL = "sentinel_copernicus"


@pytest.fixture
def disk_cache(tmp_path: Path) -> DiskTileCache:
    """A disk cache rooted in a temp dir, using the REAL provider capability gate.

    ★ Deliberately not a stubbed predicate: the point of these tests is that the gate
    consults the actual providers' declared terms, so a capability flag flipped in a
    provider is caught here.
    """
    return DiskTileCache(tmp_path / "tiles")


def _tiles_on_disk(root: Path) -> list[Path]:
    """Every cache file physically present under ``root``."""
    return [p for p in root.rglob("*") if p.is_file() and p.suffix in (".tile", ".negative")]


def _px(tag: bytes) -> bytes:
    """A distinct payload that passes the disk cache's read-time magic-byte gate.

    ★ ``DiskTileCache.get`` drops anything that does not sniff as JPEG/PNG/WebP of
    ≥ 12 bytes (corruption-as-a-miss), so bare tag bytes like ``b"PIXELS"`` would be
    silently discarded on read-back. JPEG SOI + the tag keeps payloads distinct AND
    readable.
    """
    return (b"\xff\xd8\xff\xe0" + tag).ljust(12, b"\x00")


# =============================================================================
# ★★ THE LICENCE GATE
# =============================================================================


def test_disk_cache_refuses_to_persist_a_provider_that_forbids_caching(
    disk_cache: DiskTileCache, tmp_path: Path
) -> None:
    """★★ THE COMPLIANCE TEST. Google's tiles must never touch the disk.

    ``capabilities().allows_caching = False`` makes the persistent caches **refuse the
    write** and hard-fall to an in-process, request-lifetime LRU. That is what stops a
    provider with restrictive terms from accidentally accumulating a permanent on-disk copy
    of its imagery via a background job.

    **Compliance is enforced by the cache, not by developer memory** — violating it requires
    editing capability code, not merely forgetting a rule. The assertion is physical: zero
    files on disk.
    """
    key = TileCacheKey(_GOOGLE, 18, 137452, 89234)

    disk_cache.put(key, b"GOOGLE-TILE-BYTES")

    assert _tiles_on_disk(tmp_path / "tiles") == [], (
        "tiles from a provider whose terms forbid caching reached the disk"
    )
    assert disk_cache.stats().refusals >= 1


def test_a_refused_tile_still_serves_from_the_lru_fallback(
    disk_cache: DiskTileCache,
) -> None:
    """★ Refusal is not loss. The tile is cached — in-process, for this process only.

    That is precisely what the restrictive terms permit and no more: caching that cannot
    outlive the process, accumulate on a disk, or be shared between workers.
    """
    key = TileCacheKey(_GOOGLE, 18, 1, 2)

    disk_cache.put(key, b"GOOGLE-TILE-BYTES")

    assert disk_cache.get(key) == b"GOOGLE-TILE-BYTES"
    assert disk_cache.fallback.get(key) == b"GOOGLE-TILE-BYTES"


def test_the_refusal_is_warned_once_per_provider(
    disk_cache: DiskTileCache, caplog: pytest.LogCaptureFixture
) -> None:
    """★ WARNING, and exactly once.

    Never silent — an operator must be able to see the gate acting. But per-tile it would
    emit thousands of lines for one chip, get filtered, and turn a compliance signal into
    noise and then into silence.
    """
    with caplog.at_level("WARNING", logger="gis.imagery.cache.disk"):
        for x in range(10):
            disk_cache.put(TileCacheKey(_GOOGLE, 18, x, 2), b"BYTES")

    warnings = [r for r in caplog.records if _GOOGLE in r.getMessage()]
    assert len(warnings) == 1, f"expected one warning per provider, got {len(warnings)}"
    assert "allows_caching=False" in warnings[0].getMessage()


def test_a_permitted_provider_is_written_to_disk(
    disk_cache: DiskTileCache, tmp_path: Path
) -> None:
    """The gate is not a blanket refusal — a permitted provider persists normally."""
    key = TileCacheKey(_ESRI, 18, 137452, 89234)

    disk_cache.put(key, _px(b"ESRI-TILE"))

    assert len(_tiles_on_disk(tmp_path / "tiles")) == 1
    assert disk_cache.get(key) == _px(b"ESRI-TILE")
    assert disk_cache.stats().refusals == 0


def test_negative_entries_are_licence_gated_too(
    disk_cache: DiskTileCache, tmp_path: Path
) -> None:
    """★ A negative is a record ABOUT the provider's imagery; the same gate applies."""
    disk_cache.put_negative(TileCacheKey(_GOOGLE, 18, 1, 2))

    assert _tiles_on_disk(tmp_path / "tiles") == []
    assert disk_cache.stats().refusals >= 1


def test_the_gate_defaults_to_refusing_on_any_doubt(tmp_path: Path) -> None:
    """★ An unknown provider is NOT persisted.

    The safe default for a licence gate is "do not persist": the cost of being wrong is a
    slower cache one way and a **terms violation** the other. Those are not comparable, so
    the tie goes to refusal.
    """
    cache = DiskTileCache(tmp_path / "tiles")

    cache.put(TileCacheKey("some_unregistered_provider", 1, 0, 0), b"BYTES")

    assert _tiles_on_disk(tmp_path / "tiles") == []


# =============================================================================
# ★★ THE VARIANT — the nastiest cache bug in this domain
# =============================================================================


def test_variant_distinguishes_two_seasons_of_the_same_tile(
    disk_cache: DiskTileCache,
) -> None:
    """★★ THE SEASONAL-COLLISION TEST.

    A Sentinel L2A **June** composite and an **October** composite are the same
    ``(z, x, y)`` and **utterly different pixels**. Without ``variant`` in the key, a re-run
    silently matches against the wrong season's imagery and produces **confidently wrong
    coordinates** — the system's worst failure mode, arrived at through a cache.
    """
    june = TileCacheKey(_SENTINEL, 14, 8, 5, variant="l2a-2024-06")
    october = TileCacheKey(_SENTINEL, 14, 8, 5, variant="l2a-2024-10")

    disk_cache.put(june, _px(b"JUNE"))
    disk_cache.put(october, _px(b"OCTOBER"))

    assert disk_cache.get(june) == _px(b"JUNE")
    assert disk_cache.get(october) == _px(b"OCTOBER")
    assert june.to_str() != october.to_str()


def test_variant_distinguishes_retina_and_style_variants() -> None:
    """The same collision applies to ``@2x`` tiles and Mapbox style ids."""
    plain = TileCacheKey("mapbox_satellite", 18, 1, 2)
    retina = TileCacheKey("mapbox_satellite", 18, 1, 2, variant="@2x")

    assert plain.to_str() != retina.to_str()


def test_key_string_is_the_documented_format() -> None:
    """The key format is a wire contract with Redis; pin it."""
    key = TileCacheKey("esri_world_imagery", 18, 137452, 89234, "default")
    assert key.to_str() == "tile:esri_world_imagery:default:18:137452:89234"


def test_variant_cannot_escape_the_cache_root(disk_cache: DiskTileCache, tmp_path: Path) -> None:
    """★ ``variant`` reaches a filesystem path and is not always an internal constant.

    A Mapbox style id or a Sentinel mosaic window arrives from configuration, so the
    sanitiser is a real control.
    """
    root = tmp_path / "tiles"
    for hostile in ("../../../../etc/passwd", "..", ".", "a/b/c", "x\x00y"):
        key = TileCacheKey(_ESRI, 1, 0, 0, variant=hostile)
        disk_cache.put(key, b"X")

        assert "/" not in key.safe_variant()
        assert key.safe_variant().strip("."), f"{hostile!r} produced a pure-dot component"

    for path in _tiles_on_disk(root):
        assert root.resolve() in path.resolve().parents, f"{path} escaped the cache root"


def test_pure_dot_variants_become_default() -> None:
    """★ ``..`` survives character sanitisation but IS traversal as a path component.

    ``..foo`` is an ordinary filename and must be preserved; only a component that is
    *nothing but* dots is dangerous.
    """
    assert TileCacheKey(_ESRI, 1, 0, 0, "..").safe_variant() == "default"
    assert TileCacheKey(_ESRI, 1, 0, 0, ".").safe_variant() == "default"
    assert TileCacheKey(_ESRI, 1, 0, 0, "").safe_variant() == "default"
    assert TileCacheKey(_ESRI, 1, 0, 0, "..foo").safe_variant() == "..foo"
    assert TileCacheKey(_ESRI, 1, 0, 0, "mapbox.satellite").safe_variant() == "mapbox.satellite"


# =============================================================================
# The three-way get: hit / negative / never-asked
# =============================================================================


@pytest.fixture(params=["memory", "disk"])
def cache(request: pytest.FixtureRequest, tmp_path: Path) -> TileCache:
    """Parametrised over the two always-available backends."""
    if request.param == "memory":
        return LRUTileCache()
    return DiskTileCache(tmp_path / "tiles")


def test_a_miss_is_none(cache: TileCache) -> None:
    """Never asked -> None."""
    assert cache.get(TileCacheKey(_ESRI, 18, 1, 2)) is None


def test_a_negative_is_distinct_from_a_miss(cache: TileCache) -> None:
    """★★ ``b""`` (asked, nothing there) is NOT ``None`` (never asked).

    Collapsing the two produces re-fetch storms over ocean and void: the caller cannot tell
    "the provider told us there is nothing here" from "we have not looked", so it looks
    again, forever.
    """
    key = TileCacheKey(_ESRI, 18, 1, 2)
    assert cache.get(key) is None

    cache.put_negative(key)

    assert cache.get(key) == NEGATIVE_MARKER
    assert cache.get(key) is not None, "a negative is a real answer"


def test_a_hit_returns_the_exact_bytes(cache: TileCache) -> None:
    """The cache stores ENCODED bytes and returns them unchanged."""
    key = TileCacheKey(_ESRI, 18, 137452, 89234)
    payload = b"\xff\xd8\xff\xe0JFIF-ish bytes\x00\x01"

    cache.put(key, payload)

    assert cache.get(key) == payload


def test_get_many_returns_only_what_is_present(cache: TileCache) -> None:
    """★ Batch reads exist because stitching asks for 30-200 tiles at once."""
    present = TileCacheKey(_ESRI, 18, 1, 1)
    negative = TileCacheKey(_ESRI, 18, 2, 2)
    absent = TileCacheKey(_ESRI, 18, 3, 3)
    cache.put(present, _px(b"PIXELS"))
    cache.put_negative(negative)

    found = cache.get_many([present, negative, absent])

    assert found[present] == _px(b"PIXELS")
    assert found[negative] == NEGATIVE_MARKER
    assert absent not in found


def test_get_many_of_nothing_is_empty(cache: TileCache) -> None:
    """A degenerate batch is not an error."""
    assert cache.get_many([]) == {}


def test_put_overwrites(cache: TileCache) -> None:
    """A re-put replaces rather than duplicating."""
    key = TileCacheKey(_ESRI, 18, 1, 2)
    cache.put(key, _px(b"OLD"))
    cache.put(key, _px(b"NEW"))

    assert cache.get(key) == _px(b"NEW")


def test_invalidate_by_provider(cache: TileCache) -> None:
    """Dropping one provider's tiles leaves the others alone."""
    esri = TileCacheKey(_ESRI, 18, 1, 2)
    sentinel = TileCacheKey(_SENTINEL, 14, 1, 2)
    cache.put(esri, _px(b"E"))
    cache.put(sentinel, _px(b"S"))

    removed = cache.invalidate(TileCacheKeyPrefix(_ESRI))

    assert removed >= 1
    assert cache.get(esri) is None
    assert cache.get(sentinel) == _px(b"S")


def test_invalidate_by_provider_and_variant(cache: TileCache) -> None:
    """★ The seasonal case again: drop June, keep October."""
    june = TileCacheKey(_SENTINEL, 14, 1, 2, "l2a-2024-06")
    october = TileCacheKey(_SENTINEL, 14, 1, 2, "l2a-2024-10")
    cache.put(june, _px(b"J"))
    cache.put(october, _px(b"O"))

    cache.invalidate(TileCacheKeyPrefix(_SENTINEL, variant="l2a-2024-06"))

    assert cache.get(june) is None
    assert cache.get(october) == _px(b"O")


def test_invalidate_by_provider_and_zoom(cache: TileCache) -> None:
    """A zoom-scoped invalidation spans every variant at that zoom."""
    z14 = TileCacheKey(_SENTINEL, 14, 1, 2, "l2a-2024-06")
    z13 = TileCacheKey(_SENTINEL, 13, 1, 2, "l2a-2024-06")
    cache.put(z14, _px(b"A"))
    cache.put(z13, _px(b"B"))

    cache.invalidate(TileCacheKeyPrefix(_SENTINEL, z=14))

    assert cache.get(z14) is None
    assert cache.get(z13) == _px(b"B")


def test_invalidating_nothing_is_not_an_error(cache: TileCache) -> None:
    """A prefix matching no entries removes zero and raises nothing."""
    assert cache.invalidate(TileCacheKeyPrefix("mapbox_satellite")) == 0


def test_stats_are_coherent(cache: TileCache) -> None:
    """★ Counters are DIAGNOSTIC ONLY — never control flow — but they must not lie."""
    key = TileCacheKey(_ESRI, 18, 1, 2)
    cache.get(key)  # miss
    cache.put(key, _px(b"STATS"))
    cache.get(key)  # hit

    stats = cache.stats()

    assert stats.backend == cache.backend
    assert stats.hits >= 1
    assert stats.misses >= 1
    assert stats.writes >= 1
    assert 0.0 <= stats.hit_rate <= 1.0


def test_hit_rate_of_an_untouched_cache_is_zero(cache: TileCache) -> None:
    """No division by zero on a cold cache."""
    assert cache.stats().hit_rate == 0.0


# =============================================================================
# LRU bounds
# =============================================================================


def test_lru_is_bounded_by_entry_count() -> None:
    """An unbounded cache in a Celery worker is an OOM kill mid-job."""
    cache = LRUTileCache(max_entries=3, max_bytes=10**9)

    for x in range(5):
        cache.put(TileCacheKey("fixture", 1, x, 0), b"x" * 100)

    assert cache.stats().entries == 3
    assert cache.stats().evictions == 2


def test_lru_is_bounded_by_bytes_too() -> None:
    """★ Entry count alone is a leak.

    20 000 Sentinel tiles and 20 000 blank ocean tiles are wildly different amounts of
    memory; only a byte bound catches the first.
    """
    cache = LRUTileCache(max_entries=1000, max_bytes=500)

    for x in range(10):
        cache.put(TileCacheKey("fixture", 1, x, 0), b"x" * 100)

    assert (cache.stats().bytes_used or 0) <= 500
    assert cache.stats().evictions > 0


def test_lru_evicts_least_recently_used_first() -> None:
    """The 'LRU' in the name is load-bearing: a recent read protects an entry."""
    cache = LRUTileCache(max_entries=2, max_bytes=10**9)
    first = TileCacheKey("fixture", 1, 0, 0)
    second = TileCacheKey("fixture", 1, 1, 0)
    third = TileCacheKey("fixture", 1, 2, 0)

    cache.put(first, b"A")
    cache.put(second, b"B")
    cache.get(first)  # first is now the most recently used
    cache.put(third, b"C")

    assert cache.get(first) == b"A"
    assert cache.get(second) is None, "the least recently used entry was evicted"
    assert cache.get(third) == b"C"


def test_lru_refuses_an_entry_larger_than_itself() -> None:
    """Caching it would evict everything and then not fit. Refuse rather than thrash."""
    cache = LRUTileCache(max_entries=10, max_bytes=100)

    cache.put(TileCacheKey("fixture", 1, 0, 0), b"x" * 500)

    assert cache.get(TileCacheKey("fixture", 1, 0, 0)) is None
    assert cache.stats().entries == 0


def test_lru_rejects_nonsense_bounds() -> None:
    """A zero-size cache is a configuration error, not a silent no-op cache."""
    with pytest.raises(ValueError, match="max_entries"):
        LRUTileCache(max_entries=0)
    with pytest.raises(ValueError, match="max_bytes"):
        LRUTileCache(max_bytes=0)


def test_lru_ttl_expires_entries() -> None:
    """A TTL'd entry disappears when asked for after its deadline."""
    cache = LRUTileCache(default_ttl_s=0)
    key = TileCacheKey(_ESRI, 18, 1, 2)

    cache.put(key, b"X", ttl_s=-1)  # already expired

    assert cache.get(key) is None


# =============================================================================
# Degradation — a cache must never fail a request
# =============================================================================


def test_disk_cache_write_failure_degrades_to_a_miss(tmp_path: Path) -> None:
    """★ A full disk, a read-only mount, a permissions change: all become a cache MISS.

    A cache that can fail a tile request is a liability, not an optimisation.

    ★ The unwritable directory is the one the tile's own path is created under — not the
    cache root. Chmod'ing only the root proves nothing: the write path is
    ``{root}/{provider}/{variant}/{z}/{x}/{y}.tile``, so once those intermediate directories
    exist, a write never touches the root again and would succeed regardless.
    """
    root = tmp_path / "tiles"
    cache = DiskTileCache(root)
    cache.put(TileCacheKey(_ESRI, 18, 1, 2), _px(b"X"))

    zoom_dir = root / _ESRI / "default" / "18"
    assert zoom_dir.is_dir(), "the first write must have created the tile's directory chain"

    zoom_dir.chmod(0o500)  # read + execute, no write: a new x/ dir cannot be created
    try:
        cache.put(TileCacheKey(_ESRI, 18, 9, 9), _px(b"Y"))  # ★ must NOT raise

        assert cache.get(TileCacheKey(_ESRI, 18, 9, 9)) is None, "degraded to a miss"
        assert cache.get(TileCacheKey(_ESRI, 18, 1, 2)) == _px(b"X"), "reads still work"
    finally:
        zoom_dir.chmod(0o700)


def test_disk_cache_put_never_raises_on_an_unwritable_root(tmp_path: Path) -> None:
    """★ A cache rooted somewhere impossible still cannot fail a request."""
    cache = DiskTileCache("/proc/definitely/not/writable")

    cache.put(TileCacheKey(_ESRI, 18, 1, 2), b"X")  # must not raise

    assert cache.get(TileCacheKey(_ESRI, 18, 1, 2)) is None


def test_get_tile_cache_returns_a_working_cache_for_any_input(tmp_path: Path) -> None:
    """★ There is NO failure mode. Every path yields a usable cache.

    ``.backend`` reports what was ACTUALLY built, which may differ from what was asked for —
    so a caller reporting provenance reports the truth.
    """
    assert get_tile_cache("memory").backend == "memory"
    assert get_tile_cache("disk", directory=str(tmp_path / "a")).backend == "disk"
    assert get_tile_cache("nonsense", directory=str(tmp_path / "b")).backend == "disk"
    assert get_tile_cache("", directory=str(tmp_path / "c")).backend == "disk"


def test_get_tile_cache_falls_back_to_memory_on_an_unwritable_directory() -> None:
    """★ Probed at construction, once — not discovered on the first write inside a task.

    A read-only mount should degrade with one clear log line at startup, not silently miss
    on every tile for the life of the process.
    """
    built = get_tile_cache("disk", directory="/proc/definitely/not/writable")

    assert built.backend == "memory"


def test_get_tile_cache_redis_degrades_when_redis_is_absent(tmp_path: Path) -> None:
    """★ Asking for the prod backend on a box without redis yields disk + a WARNING."""
    available, _reason = redis_cache_available()
    if available:
        pytest.skip("redis is installed; the degradation path is covered by the blocked test")

    assert get_tile_cache("redis", directory=str(tmp_path)).backend == "disk"


# =============================================================================
# RedisTileCache — with redis blocked
# =============================================================================


@pytest.fixture
def redis_blocked() -> Iterator[None]:
    """Block ``redis`` at the import system level. See ``test_import_without_deps``."""
    saved = sys.modules.get("redis", ...)
    sys.modules["redis"] = None  # type: ignore[assignment]
    try:
        yield
    finally:
        if saved is ...:
            sys.modules.pop("redis", None)
        else:
            sys.modules["redis"] = saved  # type: ignore[assignment]


def test_redis_cache_is_importable_and_usable_without_redis(redis_blocked: None) -> None:
    """★★ ``cache/__init__`` resolves ``RedisTileCache`` LAZILY (PEP 562 ``__getattr__``).

    Naming the class works with redis absent; the class then degrades to its LRU on use. A
    module-scope ``from .redis_cache import RedisTileCache`` would have made
    ``import gis.imagery.cache`` — and therefore the entire gis suite — die at collection.
    """
    from gis.imagery.cache import RedisTileCache

    cache = RedisTileCache("redis://localhost:6379/0")
    key = TileCacheKey(_ESRI, 18, 1, 2)
    cache.put(key, b"PIXELS")

    assert cache.degraded is True
    assert cache.get(key) == b"PIXELS"
    assert cache.stats().backend == "redis", "it reports what it IS, not what it fell back to"


def test_redis_cache_licence_gate_applies_before_any_connection(
    redis_blocked: None,
) -> None:
    """★ The gate is checked before the backend is even consulted.

    A provider that forbids caching is refused whether or not Redis is reachable — the
    licence does not depend on our infrastructure.
    """
    from gis.imagery.cache import RedisTileCache

    cache = RedisTileCache("redis://localhost:6379/0")
    cache.put(TileCacheKey(_GOOGLE, 18, 1, 2), b"GOOGLE")

    assert cache.stats().refusals >= 1


def test_redis_cache_get_many_is_total_when_degraded(redis_blocked: None) -> None:
    """Batch reads work on the fallback path too."""
    from gis.imagery.cache import RedisTileCache

    cache = RedisTileCache("redis://localhost:6379/0")
    present = TileCacheKey(_ESRI, 18, 1, 1)
    absent = TileCacheKey(_ESRI, 18, 2, 2)
    cache.put(present, b"P")

    found = cache.get_many([present, absent])

    assert found[present] == b"P"
    assert absent not in found


def test_redis_cache_close_is_idempotent(redis_blocked: None) -> None:
    """Shutdown must never raise."""
    from gis.imagery.cache import RedisTileCache

    cache = RedisTileCache("redis://localhost:6379/0")
    cache.close()
    cache.close()


def test_cache_package_getattr_rejects_unknown_names() -> None:
    """★ ``AttributeError``, not ``ImportError``.

    The module imports fine; it is a *dependency* that may be missing, and that is reported
    by ``redis_cache_available()`` rather than by an exception.
    """
    import gis.imagery.cache as cache_pkg

    with pytest.raises(AttributeError, match="no attribute"):
        _ = cache_pkg.NoSuchCache  # type: ignore[attr-defined]


def test_redis_cache_available_is_total() -> None:
    """It reports; it never raises."""
    available, reason = redis_cache_available()

    assert isinstance(available, bool)
    assert (reason is None) == available
