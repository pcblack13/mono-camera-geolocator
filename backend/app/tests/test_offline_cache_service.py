"""``OfflineCacheService`` — AOI enumeration, estimates, budgets, download lifecycle,
manifests and coverage. All against a FAKE imagery service: zero network, zero Celery.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from gis.imagery.cache.base import TileCacheKey
from gis.imagery.cache.memory import LRUTileCache
from gis.types import BasemapKind

from app.core.config import Settings
from app.core.exceptions import PrecacheBudgetExceeded, PrecacheConflict
from app.schemas.offline import OfflineAreaRequest
from app.services.imagery_usage import get_usage
from app.services.offline_cache_service import OfflineCacheService, reset_operations

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 40

#: A small AOI near Beirut — enumerates a handful of tiles at z13–14.
POLYGON = [[35.50, 33.90], [35.52, 33.90], [35.52, 33.92], [35.50, 33.92]]


class FakeCaps:
    tile_size_px = 512


class FakeProvider:
    """Just enough provider for the service: name, variant, caps, TTL."""

    name = "mapbox_satellite"
    cache_ttl_seconds = 3_600

    def capabilities(self) -> FakeCaps:
        return FakeCaps()

    def cache_variant(self, kind: BasemapKind = BasemapKind.SATELLITE) -> str:
        return f"{kind.value}.test"


class FakeImagery:
    """Read-through like the real one: fetch → cache; a barrier event can slow it."""

    def __init__(self) -> None:
        self.tile_cache = LRUTileCache()
        self.provider = FakeProvider()
        self.fetch_calls = 0
        self.gate: threading.Event | None = None  # set → fetches block until released
        self.fail_tiles: set[tuple[int, int, int]] = set()

    def get_provider(self, _name: str) -> FakeProvider:
        return self.provider

    def get_tile_bytes(
        self, _name: str, z: int, x: int, y: int, *, kind=BasemapKind.SATELLITE, source="map"
    ):
        if self.gate is not None:
            self.gate.wait(5.0)
        self.fetch_calls += 1
        if (z, x, y) in self.fail_tiles:
            from gis.errors import ProviderTransportError

            raise ProviderTransportError("boom", provider=self.provider.name)
        key = TileCacheKey(
            provider=self.provider.name, z=z, x=x, y=y, variant=self.provider.cache_variant(kind)
        )
        self.tile_cache.put(key, JPEG)
        return JPEG, "image/jpeg"


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    reset_operations()
    get_usage().reset()
    yield
    reset_operations()
    get_usage().reset()


def make_service(tmp_path: Path, **overrides) -> tuple[OfflineCacheService, FakeImagery]:
    settings = Settings(
        imagery_tile_cache_backend="memory",  # the FAKE holds the cache; no sweeps
        imagery_tile_cache_dir=tmp_path / "tile_cache",
        **overrides,
    )
    fake = FakeImagery()
    return OfflineCacheService(settings, imagery=fake), fake


def request(**overrides) -> OfflineAreaRequest:
    base = dict(
        provider="mapbox_satellite",
        kind="satellite",
        polygon=POLYGON,
        zoom_min=13,
        zoom_max=14,
    )
    base.update(overrides)
    return OfflineAreaRequest(**base)


def wait_for(service: OfflineCacheService, op_id: str, states: set[str], timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = service.get_operation(op_id)
        if status.state in states:
            return status
        time.sleep(0.02)
    raise AssertionError(f"operation never reached {states}; last: {status.state}")


# ── estimation ────────────────────────────────────────────────────────────────


def test_estimate_counts_real_intersecting_tiles(tmp_path: Path) -> None:
    service, _fake = make_service(tmp_path)
    est = service.estimate(request())
    assert est.total_tiles > 0
    assert est.total_tiles == est.missing_tiles  # nothing cached yet
    assert est.cached_tiles == 0
    assert est.estimated_upstream_requests == est.missing_tiles
    assert est.average_tile_size_source == "default"
    assert est.estimated_storage_bytes == est.missing_tiles * est.average_tile_size_bytes
    assert est.budget.within_budget


def test_estimate_sees_already_cached_tiles(tmp_path: Path) -> None:
    service, fake = make_service(tmp_path)
    est = service.estimate(request())
    # Pre-cache everything, then re-estimate: all cached, nothing missing.
    op = service.start(request())
    wait_for(service, op.id, {"completed"})
    est2 = service.estimate(request())
    assert est2.cached_tiles == est.total_tiles
    assert est2.missing_tiles == 0


def test_budget_per_operation_refuses_before_downloading(tmp_path: Path) -> None:
    service, fake = make_service(tmp_path, mapbox_max_tile_requests_per_operation=1)
    est = service.estimate(request())
    assert not est.budget.within_budget
    assert "PER_OPERATION" in (est.budget.reason or "")
    with pytest.raises(PrecacheBudgetExceeded):
        service.start(request())
    assert fake.fetch_calls == 0  # ★ refused BEFORE the first request


def test_budget_prefetch_cap(tmp_path: Path) -> None:
    service, _fake = make_service(tmp_path, mapbox_max_prefetch_tiles=1)
    est = service.estimate(request())
    assert not est.budget.within_budget
    assert "PREFETCH" in (est.budget.reason or "")


# ── download lifecycle ────────────────────────────────────────────────────────


def test_download_completes_and_writes_manifest(tmp_path: Path) -> None:
    service, fake = make_service(tmp_path)
    est = service.estimate(request())
    op = service.start(request())
    done = wait_for(service, op.id, {"completed"})

    assert done.completed_tiles == est.total_tiles
    assert done.failed_tiles == 0
    assert done.percent == 100.0
    assert fake.fetch_calls == est.total_tiles
    assert done.manifest_id == op.id

    manifests = service.list_manifests()
    assert len(manifests) == 1
    m = manifests[0]
    assert m.provider == "mapbox_satellite"
    assert m.cache_variant == "satellite.test"
    assert m.tile_count == est.total_tiles
    assert m.completed_tiles == est.total_tiles
    assert m.missing_tiles == 0
    assert m.tile_size_px == 512
    assert m.zoom_min == 13 and m.zoom_max == 14
    assert m.expires_at is not None  # provider TTL 3600 s → a real expiry


def test_second_run_skips_cached_tiles(tmp_path: Path) -> None:
    service, fake = make_service(tmp_path)
    op1 = service.start(request())
    wait_for(service, op1.id, {"completed"})
    first_fetches = fake.fetch_calls

    op2 = service.start(request())
    done = wait_for(service, op2.id, {"completed"})
    assert fake.fetch_calls == first_fetches  # ★ zero new upstream requests
    assert done.skipped_cached == done.total_tiles


def test_concurrent_run_for_same_provider_is_refused(tmp_path: Path) -> None:
    service, fake = make_service(tmp_path)
    fake.gate = threading.Event()  # block fetches so the first run stays live
    op = service.start(request())
    try:
        with pytest.raises(PrecacheConflict):
            service.start(request())
    finally:
        fake.gate.set()
    wait_for(service, op.id, {"completed"})


def test_pause_resume_cancel(tmp_path: Path) -> None:
    service, fake = make_service(tmp_path)
    fake.gate = threading.Event()
    op = service.start(request())

    paused = service.pause(op.id)
    assert paused.state == "paused"
    with pytest.raises(PrecacheConflict):
        service.pause(op.id)  # already paused

    resumed = service.resume(op.id)
    assert resumed.state == "running"

    cancelled = service.cancel(op.id)
    assert cancelled.state == "cancelled"
    fake.gate.set()
    final = wait_for(service, op.id, {"cancelled"})
    assert final.completed_tiles < final.total_tiles
    with pytest.raises(PrecacheConflict):
        service.cancel(op.id)  # already terminal


def test_failed_tiles_are_counted_and_retryable(tmp_path: Path) -> None:
    service, fake = make_service(tmp_path)
    # Fail one specific tile on the first pass.
    est = service.estimate(request())
    assert est.total_tiles >= 2
    from gis.tiles import tiles_for_polygon

    ring = [(p[0], p[1]) for p in POLYGON]
    tiles, _ = tiles_for_polygon(ring, 13, 14)
    victim = tiles[0]
    fake.fail_tiles = {(victim.z, victim.x, victim.y)}

    op = service.start(request())
    done = wait_for(service, op.id, {"completed"})
    assert done.failed_tiles == 1
    assert done.note is not None  # the last error is legible

    fake.fail_tiles = set()  # the outage passes
    retried = service.retry_failed(op.id)
    final = wait_for(service, retried.id, {"completed"})
    assert final.failed_tiles == 0


# ── coverage ──────────────────────────────────────────────────────────────────


def test_coverage_before_and_after(tmp_path: Path) -> None:
    service, _fake = make_service(tmp_path)
    before = service.coverage(request())
    assert before.coverage_ratio == 0.0
    op = service.start(request())
    wait_for(service, op.id, {"completed"})
    after = service.coverage(request())
    assert after.coverage_ratio == 1.0
    assert set(after.by_zoom) == {"13", "14"}
    for bucket in after.by_zoom.values():
        assert bucket["cached"] == bucket["total"]


def test_delete_manifest_leaves_tiles(tmp_path: Path) -> None:
    service, fake = make_service(tmp_path)
    op = service.start(request())
    wait_for(service, op.id, {"completed"})
    assert len(service.list_manifests()) == 1
    service.delete_manifest(op.id)
    assert service.list_manifests() == []
    # ★ Tiles survive — they are shared with the live map.
    assert service.coverage(request()).coverage_ratio == 1.0
