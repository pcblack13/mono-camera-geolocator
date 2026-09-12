"""``DiskTileCache`` policy behaviour — per-provider TTLs, negatives, corruption, sweep.

★ These pin the cache semantics the offline workflow depends on: a Mapbox tile must
expire on MAPBOX's ToS clock even when the global TTL is longer; a cached negative must
answer without an upstream request and then expire; a corrupted file must read as a MISS
and be removed, never decoded; a sweep must reclaim expiry/negatives/temp/corruption and
enforce the byte cap — all without any test touching the network.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from gis.imagery.cache.base import NEGATIVE_MARKER, TileCacheKey
from gis.imagery.cache.disk import DiskTileCache

# A minimal, valid-enough JPEG head — what `_looks_like_image` requires of real bytes.
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def make_cache(tmp_path: Path, **kwargs) -> DiskTileCache:
    """A cache whose licence gate always permits — policy is not under test here."""
    kwargs.setdefault("allows_caching", lambda _p: True)
    return DiskTileCache(tmp_path / "cache", **kwargs)


def key(provider: str = "mapbox_satellite", z: int = 15, x: int = 100, y: int = 200,
        variant: str = "satellite.mapbox.satellite.@2x.jpg90") -> TileCacheKey:
    return TileCacheKey(provider=provider, z=z, x=x, y=y, variant=variant)


def backdate(path: Path, seconds: int) -> None:
    st = path.stat()
    os.utime(path, (st.st_atime - seconds, st.st_mtime - seconds))


def stored_path(cache: DiskTileCache, k: TileCacheKey, *, negative: bool = False) -> Path:
    return cache._path(k, negative=negative)  # noqa: SLF001 — white-box on purpose


# ── round trip, atomicity, contains ───────────────────────────────────────────


def test_put_get_round_trip(tmp_path: Path) -> None:
    cache = make_cache(tmp_path)
    cache.put(key(), JPEG)
    assert cache.get(key()) == JPEG
    assert cache.contains(key())


def test_atomic_writes_leave_no_part_files(tmp_path: Path) -> None:
    cache = make_cache(tmp_path)
    for i in range(20):
        cache.put(key(x=i), JPEG)
    parts = list((tmp_path / "cache").rglob("*.part"))
    assert parts == []


def test_contains_is_false_for_absent_and_true_for_present(tmp_path: Path) -> None:
    cache = make_cache(tmp_path)
    assert not cache.contains(key())
    cache.put(key(), JPEG)
    assert cache.contains(key())


def test_variant_isolates_configurations(tmp_path: Path) -> None:
    """★ CACHE-KEY ISOLATION: same (z, x, y), different config fingerprint → different
    entries. A style/@2x/format change must never return the old configuration's bytes."""
    cache = make_cache(tmp_path)
    old = key(variant="satellite.mapbox.satellite.@2x.jpg90")
    new = key(variant="satellite.custom.style.@1x.jpg90")
    cache.put(old, JPEG)
    assert cache.get(new) is None
    cache.put(new, PNG)
    assert cache.get(old) == JPEG
    assert cache.get(new) == PNG


# ── per-provider TTL ──────────────────────────────────────────────────────────


def test_provider_ttl_caps_the_global_ttl(tmp_path: Path, monkeypatch) -> None:
    """A provider ToS cap (100 s) beats a 30-day global TTL: the stricter clock wins."""
    monkeypatch.setattr(
        "gis.imagery.cache.disk._provider_ttls", lambda _p: (100, 86_400)
    )
    cache = make_cache(tmp_path, ttl_s=2_592_000)
    cache.put(key(), JPEG)
    backdate(stored_path(cache, key()), 200)
    assert cache.get(key()) is None  # expired on the provider's clock
    assert not stored_path(cache, key()).exists()  # and dropped


def test_shorter_global_ttl_still_wins(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "gis.imagery.cache.disk._provider_ttls", lambda _p: (2_592_000, 86_400)
    )
    cache = make_cache(tmp_path, ttl_s=50)
    cache.put(key(), JPEG)
    backdate(stored_path(cache, key()), 100)
    assert cache.get(key()) is None


def test_unknown_provider_degrades_to_global_ttl(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "gis.imagery.cache.disk._provider_ttls", lambda _p: (None, None)
    )
    cache = make_cache(tmp_path, ttl_s=2_592_000)
    cache.put(key(provider="whoknows"), JPEG)
    assert cache.get(key(provider="whoknows")) == JPEG


# ── negative cache ────────────────────────────────────────────────────────────


def test_negative_round_trip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "gis.imagery.cache.disk._provider_ttls", lambda _p: (None, 86_400)
    )
    cache = make_cache(tmp_path)
    assert cache.get(key()) is None  # never asked
    cache.put_negative(key())
    assert cache.get(key()) == NEGATIVE_MARKER  # asked and answered: nothing here
    assert not cache.contains(key())  # a negative is NOT held imagery


def test_negative_expires_on_its_own_shorter_clock(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "gis.imagery.cache.disk._provider_ttls", lambda _p: (None, 60)
    )
    cache = make_cache(tmp_path)
    cache.put_negative(key())
    backdate(stored_path(cache, key(), negative=True), 120)
    assert cache.get(key()) is None  # gap may have been filled — ask again


# ── corruption ────────────────────────────────────────────────────────────────


def test_corrupted_entry_reads_as_miss_and_is_removed(tmp_path: Path) -> None:
    cache = make_cache(tmp_path)
    cache.put(key(), JPEG)
    stored_path(cache, key()).write_bytes(b"this is not an image at all")
    assert cache.get(key()) is None
    assert not stored_path(cache, key()).exists()


def test_truncated_entry_reads_as_miss(tmp_path: Path) -> None:
    cache = make_cache(tmp_path)
    cache.put(key(), JPEG)
    stored_path(cache, key()).write_bytes(JPEG[:4])  # power loss mid-anything
    assert cache.get(key()) is None


# ── storage failure ───────────────────────────────────────────────────────────


def test_write_failure_degrades_to_no_cache(tmp_path: Path) -> None:
    root = tmp_path / "cache"
    root.mkdir()
    os.chmod(root, 0o500)  # read/execute only — writes must fail
    try:
        cache = DiskTileCache(root, allows_caching=lambda _p: True)
        cache.put(key(), JPEG)  # must NOT raise
        assert cache.get(key()) is None  # simply uncached
    finally:
        os.chmod(root, 0o700)


# ── sweep ─────────────────────────────────────────────────────────────────────


def test_sweep_reclaims_expired_negatives_temp_and_corrupt(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "gis.imagery.cache.disk._provider_ttls", lambda _p: (100, 60)
    )
    cache = make_cache(tmp_path, ttl_s=2_592_000)
    fresh, stale = key(x=1), key(x=2)
    cache.put(fresh, JPEG)
    cache.put(stale, JPEG)
    backdate(stored_path(cache, stale), 200)  # past the provider's 100 s cap
    cache.put_negative(key(x=3))
    backdate(stored_path(cache, key(x=3), negative=True), 120)  # past the 60 s negative
    # An orphaned temp file from a crash mid-write:
    part = stored_path(cache, key(x=4)).parent
    part.mkdir(parents=True, exist_ok=True)
    orphan = part / "orphan.part"
    orphan.write_bytes(b"half")
    backdate(orphan, 7_200)
    # A zero-byte data file that dodged the atomic rename:
    empty = stored_path(cache, key(x=5))
    empty.parent.mkdir(parents=True, exist_ok=True)
    empty.write_bytes(b"")

    result = cache.sweep(negative_ttl_s=86_400)

    assert result["expired"] == 1
    assert result["expired_negative"] == 1
    assert result["removed_temp"] == 1
    assert result["removed_corrupt"] == 1
    assert cache.get(fresh) == JPEG  # the survivor survives


def test_sweep_enforces_the_byte_cap_lru(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "gis.imagery.cache.disk._provider_ttls", lambda _p: (None, None)
    )
    cache = make_cache(tmp_path, ttl_s=0)
    tile = JPEG + b"\x00" * 1_000
    for i in range(10):
        cache.put(key(x=i), tile)
    # Make eviction order deterministic: older x = older mtime.
    for i in range(10):
        backdate(stored_path(cache, key(x=i)), (10 - i) * 100)

    result = cache.sweep(max_bytes=len(tile) * 4)

    assert result["evicted"] == 6
    assert result["remaining_bytes"] <= len(tile) * 4
    assert cache.get(key(x=9)) is not None  # newest kept
    assert cache.get(key(x=0)) is None  # oldest evicted


def test_sample_average_tile_size(tmp_path: Path) -> None:
    cache = make_cache(tmp_path)
    assert cache.sample_average_tile_size("mapbox_satellite") is None  # nothing yet
    for i in range(4):
        cache.put(key(x=i), JPEG + b"\x00" * (100 * i))
    avg = cache.sample_average_tile_size("mapbox_satellite")
    assert avg is not None
    assert len(JPEG) <= avg <= len(JPEG) + 300


# ── refusal fallback still honoured with the new paths ────────────────────────


def test_licence_refusal_goes_to_memory_fallback(tmp_path: Path) -> None:
    cache = DiskTileCache(tmp_path / "cache", allows_caching=lambda _p: False)
    cache.put(key(provider="google_maps_static"), JPEG)
    assert list((tmp_path / "cache").rglob("*.tile")) == []  # nothing persisted
    assert cache.get(key(provider="google_maps_static")) == JPEG  # served from LRU
    assert cache.contains(key(provider="google_maps_static"))
    assert cache.stats().refusals >= 1
