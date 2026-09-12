"""``ViewportCacheManager`` — enumeration, prefetch, limits, priorities, offline,
manual-download yielding, stale-queue replacement. All against a fake imagery service:
zero network.
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
from app.schemas.viewport_cache import ViewportReport
from app.services import viewport_cache_service as vcs
from app.services.viewport_cache_service import ViewportCacheManager

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 40

# A small viewport near Beirut, ~2x2 tiles at z15.
VIEW = dict(west=35.500, south=33.900, east=35.520, north=33.915, zoom=15)


class FakeCaps:
    tile_size_px = 512


class FakeProvider:
    name = "mapbox_satellite"
    min_zoom = 0
    max_zoom = 22
    cache_ttl_seconds = None
    negative_cache_ttl_seconds = 86_400

    def capabilities(self):
        return FakeCaps()

    def cache_variant(self, kind: BasemapKind = BasemapKind.SATELLITE) -> str:
        return f"{kind.value}.test"


class FakeImagery:
    def __init__(self) -> None:
        self.tile_cache = LRUTileCache()
        self.provider = FakeProvider()
        self.fetched: list[tuple[int, int, int]] = []
        self.gate: threading.Event | None = None
        self.fail_all = False
        self._lock = threading.Lock()

    def get_provider(self, _name: str) -> FakeProvider:
        return self.provider

    def get_tile_bytes(self, _name, z, x, y, *, kind=BasemapKind.SATELLITE, source="map"):
        if self.gate is not None:
            self.gate.wait(5.0)
        if self.fail_all:
            from gis.errors import ProviderTransportError

            raise ProviderTransportError("no network", provider=self.provider.name)
        with self._lock:
            self.fetched.append((z, x, y))
        key = TileCacheKey(
            provider=self.provider.name, z=z, x=x, y=y, variant=self.provider.cache_variant(kind)
        )
        self.tile_cache.put(key, JPEG)
        return JPEG, "image/jpeg"


@pytest.fixture
def managers() -> Iterator[list[ViewportCacheManager]]:
    created: list[ViewportCacheManager] = []
    yield created
    for m in created:
        m._stop.set()  # noqa: SLF001
        with m._lock:  # noqa: SLF001
            m._queue.clear()  # noqa: SLF001


def make(tmp_path: Path, managers, **overrides) -> tuple[ViewportCacheManager, FakeImagery]:
    settings = Settings(
        imagery_tile_cache_backend="memory",
        imagery_tile_cache_dir=tmp_path / "tc",
        **overrides,
    )
    manager = ViewportCacheManager(settings)
    managers.append(manager)
    return manager, FakeImagery()


def report(**overrides) -> ViewportReport:
    base = dict(provider="mapbox_satellite", kind="satellite", **VIEW)
    base.update(overrides)
    return ViewportReport(**base)


def drain(manager: ViewportCacheManager, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with manager._lock:  # noqa: SLF001
            if not manager._queue:  # noqa: SLF001
                time.sleep(0.1)  # let in-flight worker fetches finish
                return
        time.sleep(0.02)
    raise AssertionError("queue never drained")


# ── enumeration, coverage, cache-first ────────────────────────────────────────


def test_viewport_is_cached_and_second_report_is_full_coverage(tmp_path, managers) -> None:
    manager, fake = make(tmp_path, managers, imagery_auto_cache_zoom_range="current_only", imagery_auto_cache_prefetch_viewports=0)
    st = manager.report_viewport(fake, report())
    assert st.enabled and st.viewport_tiles > 0
    assert st.cached_tiles == 0 and st.coverage_percent == 0.0
    drain(manager)
    assert len(fake.fetched) == st.viewport_tiles  # exactly the visible tiles

    st2 = manager.report_viewport(fake, report())
    assert st2.coverage_percent == 100.0
    assert st2.missing_tiles == 0
    drain(manager)
    assert len(fake.fetched) == st.viewport_tiles  # ★ cache-first: zero re-downloads

    session = st2.session
    assert session.tiles_downloaded == st.viewport_tiles
    assert session.tiles_failed == 0


def test_current_zoom_only_by_default(tmp_path, managers) -> None:
    manager, fake = make(tmp_path, managers, imagery_auto_cache_zoom_range="current_only", imagery_auto_cache_prefetch_viewports=0)
    manager.report_viewport(fake, report())
    drain(manager)
    assert {z for z, _x, _y in fake.fetched} == {VIEW["zoom"]}


def test_zoom_range_current_plus_minus_one(tmp_path, managers) -> None:
    manager, fake = make(
        tmp_path,
        managers,
        imagery_auto_cache_prefetch_viewports=0,
        imagery_auto_cache_zoom_range="current_plus_minus_one",
    )
    manager.report_viewport(fake, report())
    drain(manager)
    assert {z for z, _x, _y in fake.fetched} == {14, 15, 16}


def test_prefetch_buffer_queues_a_ring_beyond_the_viewport(tmp_path, managers) -> None:
    m0, f0 = make(tmp_path / "a", managers, imagery_auto_cache_zoom_range="current_only", imagery_auto_cache_prefetch_viewports=0)
    m1, f1 = make(tmp_path / "b", managers, imagery_auto_cache_zoom_range="current_only", imagery_auto_cache_prefetch_viewports=1)
    s0 = m0.report_viewport(f0, report())
    s1 = m1.report_viewport(f1, report())
    drain(m0)
    drain(m1)
    assert s0.viewport_tiles == s1.viewport_tiles  # visible coverage identical
    assert len(f1.fetched) > len(f0.fetched)  # ring tiles fetched too
    # The ring is roughly (3w x 3h) − (w x h); at least double the visible count.
    assert len(f1.fetched) >= 2 * len(f0.fetched)


def test_dateline_crossing_splits_not_world_wraps(tmp_path, managers) -> None:
    manager, fake = make(tmp_path, managers, imagery_auto_cache_prefetch_viewports=0)
    st = manager.report_viewport(
        fake, report(west=179.98, east=180.02, south=0.0, north=0.02, zoom=12)
    )
    drain(manager)
    # A ~0.04° box at z12 is a handful of tiles, not half the world.
    assert 0 < st.viewport_tiles <= 8
    xs = {x for _z, x, _y in fake.fetched}
    n = 1 << 12
    assert xs <= {0, 1, n - 2, n - 1}  # both edges of the world, nothing between


# ── limits ────────────────────────────────────────────────────────────────────


def test_per_viewport_limit_truncates_and_says_so(tmp_path, managers) -> None:
    manager, fake = make(
        tmp_path,
        managers,
        imagery_auto_cache_prefetch_viewports=2,
        imagery_auto_cache_max_tiles_per_viewport=3,
    )
    st = manager.report_viewport(fake, report())
    assert "viewport" in (st.note or "").lower() or "limited" in (st.note or "").lower()
    drain(manager)
    assert len(fake.fetched) <= 3


def test_session_tile_limit_stops_queueing(tmp_path, managers) -> None:
    manager, fake = make(
        tmp_path,
        managers,
        imagery_auto_cache_prefetch_viewports=0,
        imagery_auto_cache_max_tiles_per_session=2,
    )
    manager.report_viewport(fake, report())
    drain(manager)
    assert len(fake.fetched) <= 2
    st = manager.report_viewport(fake, report(west=36.0, east=36.02, south=34.0, north=34.015))
    assert st.session.limit_reached == "session tile limit"
    assert "session limit" in (st.note or "")
    drain(manager)
    assert len(fake.fetched) <= 2  # nothing new


def test_session_byte_limit_clears_queue(tmp_path, managers) -> None:
    manager, fake = make(
        tmp_path,
        managers,
        imagery_auto_cache_prefetch_viewports=0,
        imagery_auto_cache_max_session_bytes=1,  # first tile trips it
    )
    manager.report_viewport(fake, report())
    drain(manager)
    assert len(fake.fetched) < 6
    assert manager.status().session.limit_reached == "session storage limit"


# ── enable/disable, offline, manual priority ─────────────────────────────────


def test_disabled_reports_coverage_but_queues_nothing(tmp_path, managers) -> None:
    manager, fake = make(tmp_path, managers, imagery_auto_cache_enabled=False)
    st = manager.report_viewport(fake, report())
    assert not st.enabled
    assert st.viewport_tiles > 0  # coverage still computed
    assert st.queued_tiles == 0
    time.sleep(0.2)
    assert fake.fetched == []


def test_runtime_toggle_overrides_settings(tmp_path, managers) -> None:
    manager, fake = make(tmp_path, managers, imagery_auto_cache_enabled=True)
    manager.set_enabled(False)
    st = manager.report_viewport(fake, report())
    assert not st.enabled and st.queued_tiles == 0
    manager.set_enabled(True)
    st = manager.report_viewport(fake, report())
    assert st.enabled
    drain(manager)
    assert fake.fetched  # now it caches


def test_offline_mode_pauses_and_never_fetches(tmp_path, managers) -> None:
    manager, fake = make(tmp_path, managers, imagery_offline=True)
    st = manager.report_viewport(fake, report())
    assert not st.online
    assert "offline" in (st.note or "").lower()
    time.sleep(0.2)
    assert fake.fetched == []


def test_yields_to_manual_offline_download(tmp_path, managers, monkeypatch) -> None:
    manager, fake = make(tmp_path, managers)
    monkeypatch.setattr(vcs, "has_active_operation", lambda _p=None: True)
    st = manager.report_viewport(fake, report())
    assert "manual" in (st.note or "").lower()
    assert st.queued_tiles == 0
    time.sleep(0.2)
    assert fake.fetched == []


def test_network_loss_backs_off_instead_of_hammering(tmp_path, managers) -> None:
    manager, fake = make(tmp_path, managers, imagery_auto_cache_prefetch_viewports=0)
    fake.fail_all = True
    manager.report_viewport(fake, report())
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and not manager._network_paused():  # noqa: SLF001
        time.sleep(0.05)
    assert manager._network_paused()  # noqa: SLF001 — backed off after N failures
    st = manager.status()
    assert not st.online
    assert st.session.tiles_failed >= 5


# ── stale-queue replacement & session/project semantics ──────────────────────


def test_new_viewport_replaces_stale_queue(tmp_path, managers) -> None:
    manager, fake = make(tmp_path, managers, imagery_auto_cache_zoom_range="current_only", imagery_auto_cache_prefetch_viewports=0)
    fake.gate = threading.Event()  # freeze the workers mid-area-A
    manager.report_viewport(fake, report())
    with manager._lock:  # noqa: SLF001
        assert manager._queue  # noqa: SLF001
    # The user pans far away before anything downloads:
    st_b = manager.report_viewport(
        fake, report(west=36.500, south=34.500, east=36.520, north=34.515)
    )
    fake.gate.set()
    drain(manager)
    # ★ All of area B was fetched; area A's QUEUED tiles were cancelled. Workers that
    #   had already popped an A tile before the pan finish it (in-flight work completes;
    #   only queued work is dropped) — at most `concurrency` stragglers.
    from gis.tiles import bbox_to_tile_range
    from gis.types import BBox

    rng_b = bbox_to_tile_range(BBox(west=36.500, south=34.500, east=36.520, north=34.515), 15)

    def in_b(x: int, y: int) -> bool:
        return rng_b.min_x <= x <= rng_b.max_x and rng_b.min_y <= y <= rng_b.max_y

    b_fetched = [t for t in fake.fetched if in_b(t[1], t[2])]
    stragglers = [t for t in fake.fetched if not in_b(t[1], t[2])]
    assert len(b_fetched) == st_b.viewport_tiles  # area B fully cached
    assert len(stragglers) <= 4  # ≤ concurrency in-flight A tiles, never the whole area


def test_project_switch_resets_session(tmp_path, managers) -> None:
    manager, fake = make(tmp_path, managers, imagery_auto_cache_prefetch_viewports=0)
    manager.report_viewport(fake, report(project_id="alpha"))
    drain(manager)
    assert manager.status().session.tiles_downloaded > 0
    # ★ HOLD THE WORKERS AT THE FENCE (2026-09-02). The snapshot below must prove
    #   the SWITCH reset the tallies — but beta's own report enumerates deeper
    #   full-detail chunks alpha never reached, and with the instant fake a worker
    #   can legitimately land hundreds of beta downloads before report_viewport
    #   even returns. That race only ever lost after test_accuracy_service's
    #   ~8 minutes of BLAS threads reshaped scheduling — a full-suite-only
    #   failure (406 == 0) that no subset could reproduce. The gate makes the
    #   assertion about the reset, not about who wins a thread race.
    fake.gate = threading.Event()  # closed: every fetch waits at the fence
    st = manager.report_viewport(fake, report(project_id="beta"))
    assert st.session.project_id == "beta"
    assert st.session.tiles_downloaded == 0  # fresh tallies; the CACHE is untouched
    assert st.coverage_percent == 100.0  # shared cache: project beta sees alpha's tiles
    fake.gate.set()  # release the workers for teardown


# ── full-detail mode ──────────────────────────────────────────────────────────


def test_full_detail_below_the_gate_is_current_only(tmp_path, managers) -> None:
    """A wide (z13) viewport × every zoom is millions of tiles — below the gate the
    mode degrades to current-only."""
    manager, fake = make(
        tmp_path,
        managers,
        imagery_auto_cache_prefetch_viewports=0,
        imagery_auto_cache_zoom_range="full_detail",
        imagery_auto_cache_full_detail_min_zoom=15,
    )
    manager.report_viewport(fake, report(zoom=13))
    drain(manager)
    assert {z for z, _x, _y in fake.fetched} == {13}


def test_full_detail_caches_every_deeper_zoom_progressively(tmp_path, managers) -> None:
    """★ THE ASK: zoomed at/past the gate, the visible area fills at EVERY deeper zoom
    up to the ceiling — in chunks, continued by re-reports, until truncated=False."""
    manager, fake = make(
        tmp_path,
        managers,
        imagery_auto_cache_prefetch_viewports=0,
        imagery_auto_cache_zoom_range="full_detail",
        imagery_auto_cache_full_detail_min_zoom=15,
        imagery_auto_cache_max_zoom=18,  # a small ceiling keeps the test fast
        imagery_auto_cache_max_tiles_per_viewport=10,  # force several chunks
    )
    # A tiny viewport (~1 tile at z15 → ~64 at z18).
    view = report(west=35.500, south=33.900, east=35.505, north=33.904, zoom=15)

    rounds = 0
    while True:
        st = manager.report_viewport(fake, view)
        drain(manager)
        rounds += 1
        if not st.truncated:
            break
        assert rounds < 20, "progressive fill never converged"

    zooms = {z for z, _x, _y in fake.fetched}
    assert zooms == {15, 16, 17, 18}  # ★ full detail: current AND every deeper zoom
    assert rounds > 1  # it genuinely filled in chunks, not one blast
    # Complete: a fresh report finds nothing missing and does not claim more remains.
    st = manager.report_viewport(fake, view)
    assert st.coverage_percent == 100.0
    assert not st.truncated
    assert st.queued_tiles == 0


def test_full_detail_visible_zoom_downloads_before_deep_zooms(tmp_path, managers) -> None:
    manager, fake = make(
        tmp_path,
        managers,
        imagery_auto_cache_prefetch_viewports=0,
        imagery_auto_cache_zoom_range="full_detail",
        imagery_auto_cache_full_detail_min_zoom=15,
        imagery_auto_cache_max_zoom=17,
        imagery_auto_cache_concurrency=4,
    )
    view = report(west=35.500, south=33.900, east=35.505, north=33.904, zoom=15)
    st = manager.report_viewport(fake, view)
    drain(manager)
    # The current-zoom (visible) tiles must be fetched first — within the first
    # (visible + concurrency) positions of the fetch order.
    z15_positions = [i for i, (z, _x, _y) in enumerate(fake.fetched) if z == 15]
    assert z15_positions, "visible zoom was fetched"
    assert max(z15_positions) < st.viewport_tiles + 4


def test_full_detail_respects_the_session_cap_and_stops_the_loop(tmp_path, managers) -> None:
    manager, fake = make(
        tmp_path,
        managers,
        imagery_auto_cache_prefetch_viewports=0,
        imagery_auto_cache_zoom_range="full_detail",
        imagery_auto_cache_full_detail_min_zoom=15,
        imagery_auto_cache_max_zoom=20,
        imagery_auto_cache_max_tiles_per_viewport=30,
        imagery_auto_cache_max_tiles_per_session=45,
    )
    view = report(west=35.500, south=33.900, east=35.505, north=33.904, zoom=15)
    manager.report_viewport(fake, view)
    drain(manager)
    st = manager.report_viewport(fake, view)  # second chunk hits the session cap
    drain(manager)
    st = manager.report_viewport(fake, view)  # third: budget exhausted
    assert st.queued_tiles == 0
    assert not st.truncated  # ★ the continue-loop STOPS — no progress is possible
    assert st.session.limit_reached == "session tile limit"
    assert len(fake.fetched) <= 45
