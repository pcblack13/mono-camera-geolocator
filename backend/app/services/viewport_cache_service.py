"""Automatic viewport caching — background-fills the tile cache with what the surveyor
is looking at (plus a prefetch ring), so recently-worked areas are offline-available
without a manual download.

★ **NOT A SECOND CACHE.** This module owns exactly three things: viewport→tile
enumeration, a priority queue, and limits. Every actual tile fetch goes through
``ImageryService.get_tile_bytes(source="viewport")`` — the same read-through cache,
config-fingerprint keys, licence gate, per-provider TTLs, negative cache, in-flight
dedup, rate limiter and retry policy as the live map and the manual Offline Area
Manager. A tile cached here is indistinguishable from one the map fetched.

★ **TWO OFFLINE MECHANISMS, ONE CACHE.** This is the *continuous* one (small, follows
the user, strictly capped). The manual Offline Area Manager
(``offline_cache_service``) is the *deliberate* one (large AOI, budgeted, manifested).
When a manual download is live this service YIELDS — predictable AOI preparation beats
background prefetch.

★ **STALE WORK IS DROPPED, NOT FINISHED.** Every viewport report replaces the pending
queue: tiles for an area the user has left are cancelled (already-cached ones cost
nothing to re-skip; genuinely-needed ones re-enter if still in view). Visible tiles are
HIGH priority, the first prefetch ring MEDIUM, outer rings LOW.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime

from gis.errors import (
    GisError,
    ProviderRateLimitError,
    ProviderTransportError,
    TileNotAvailableError,
)
from gis.imagery.cache.base import TileCacheKey
from gis.tiles import bbox_to_tile_range
from gis.types import BBox, BasemapKind, TileRange

from app.core.config import Settings, get_settings
from app.core.exceptions import LandExplorerError
from app.schemas.viewport_cache import AutoCacheSession, AutoCacheStatus, ViewportReport
from app.services.imagery_service import ImageryService
from app.services.offline_cache_service import has_active_operation

__all__ = ["ViewportCacheManager", "get_viewport_cache_manager", "reset_viewport_cache"]

_log = logging.getLogger("app.services.viewport_cache")

# Priorities — lower sorts first.
_PRIO_VISIBLE = 0
_PRIO_NEAR = 1
_PRIO_FAR = 2

_OFFLINE_BACKOFF_SECONDS = 30.0
"""After this many consecutive transport failures the queue pauses this long — the
network is gone; hammering it would burn the retry budget for nothing."""
_OFFLINE_AFTER_FAILURES = 5

_ENUMERATION_HARD_CAP = 20_000
"""Absolute per-report enumeration ceiling (memory guard, far above any sane cap)."""


@dataclass
class _QueuedTile:
    priority: int
    generation: int
    z: int
    x: int
    y: int


@dataclass
class _Session:
    """The automatic-caching session — reset on restart, toggle-off, project switch."""

    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    project_id: str | None = None
    tiles_requested: int = 0
    tiles_downloaded: int = 0
    tiles_skipped_cached: int = 0
    tiles_no_imagery: int = 0
    tiles_failed: int = 0
    bytes_downloaded: int = 0
    limit_reached: str | None = None


def _wrap_lon(lon: float) -> float:
    while lon > 180.0:
        lon -= 360.0
    while lon < -180.0:
        lon += 360.0
    return lon


def _bbox_ranges(west: float, south: float, east: float, north: float, z: int) -> list[TileRange]:
    """Visible bounds → 1–2 tile ranges, handling Leaflet's unwrapped longitudes.

    Leaflet reports longitudes beyond ±180 after panning across the dateline; wrapping
    can produce ``west > east``, which is a genuine antimeridian crossing — split into
    two ranges rather than enumerating the world the wrong way round.
    """
    south = max(-85.05112878, min(85.05112878, south))
    north = max(-85.05112878, min(85.05112878, north))
    if east - west >= 360.0:  # whole-world view
        west, east = -180.0, 180.0
    else:
        west, east = _wrap_lon(west), _wrap_lon(east)
    if west <= east:
        boxes = [(west, east)]
    else:  # dateline crossing
        boxes = [(west, 180.0), (-180.0, east)]
    ranges = []
    for w, e in boxes:
        try:
            ranges.append(bbox_to_tile_range(BBox(west=w, south=south, east=e, north=north), z))
        except ValueError:
            continue
    return ranges


def _expand(rng: TileRange, ring: int, viewports: int) -> TileRange:
    """Grow a range by ``ring`` viewport-widths, clamped to the world at this zoom."""
    n = (1 << rng.z) - 1
    w = rng.max_x - rng.min_x + 1
    h = rng.max_y - rng.min_y + 1
    dx, dy = w * ring, h * ring
    if ring > viewports:
        raise ValueError("ring beyond configured prefetch")
    return TileRange(
        z=rng.z,
        min_x=max(0, rng.min_x - dx),
        min_y=max(0, rng.min_y - dy),
        max_x=min(n, rng.max_x + dx),
        max_y=min(n, rng.max_y + dy),
    )


class ViewportCacheManager:
    """Process-wide coordinator: queue, workers, session, limits. Thread-safe."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        self._queue: deque[_QueuedTile] = deque()
        self._queued_keys: set[tuple[int, int, int]] = set()
        self._generation = 0
        self._session = _Session()
        self._enabled_override: bool | None = None
        self._workers_started = False
        self._stop = threading.Event()
        self._imagery: ImageryService | None = None
        self._consecutive_failures = 0
        self._paused_until = 0.0
        self._last_report: ViewportReport | None = None
        self._last_status: AutoCacheStatus | None = None

    # ── enable/disable ───────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        if self._enabled_override is not None:
            return self._enabled_override
        return bool(self._settings.imagery_auto_cache_enabled)

    def set_enabled(self, enabled: bool) -> None:
        """Runtime toggle. OFF clears the queue and resets the session — cached tiles
        stay (they are the shared cache's, not this feature's)."""
        with self._lock:
            self._enabled_override = enabled
            if not enabled:
                self._queue.clear()
                self._queued_keys.clear()
                self._session = _Session()
        _log.info("auto_cache.%s", "enabled" if enabled else "disabled")

    # ── the report entry point ───────────────────────────────────────────────

    def report_viewport(self, imagery: ImageryService, report: ViewportReport) -> AutoCacheStatus:
        """A settled viewport: compute coverage, replace the queue with what is missing.

        Never blocks on downloads — enumeration + cheap ``contains()`` stats only; the
        fetching happens on the worker threads.
        """
        self._imagery_ref(imagery)
        settings = self._settings
        note: str | None = None

        provider = imagery.get_provider(report.provider)
        kind = BasemapKind(report.kind)
        variant = provider.cache_variant(kind)
        cache = imagery.tile_cache

        # Project switch resets the session (shared cache; per-project accounting).
        with self._lock:
            if report.project_id != self._session.project_id and (
                report.project_id or self._session.project_id
            ):
                self._session = _Session()
                self._session.project_id = report.project_id
                _log.info("auto_cache.session_reset", extra={"project": report.project_id})

        zooms = self._zooms_for(report.zoom, provider)

        # ── STREAMING enumeration: current zoom (visible + rings), then deeper zooms
        #   shallow→deep, contains-checking as we go and STOPPING once a chunk's worth
        #   of missing tiles is found. Full-detail areas can be 100k+ tiles; the point
        #   of the chunked walk is to never materialise (or stat) more than one chunk
        #   past coverage — the frontend re-reports on drain and the next chunk starts
        #   where this one's cached prefix ends.
        viewport_tiles = cached_tiles = 0
        missing: list[tuple[int, int, int, int]] = []  # (prio, z, x, y)
        seen: set[tuple[int, int, int]] = set()
        truncated = False
        rings = settings.imagery_auto_cache_prefetch_viewports
        chunk_cap = settings.imagery_auto_cache_max_tiles_per_viewport or _ENUMERATION_HARD_CAP

        def visit(prio: int, z: int, x: int, y: int, *, in_view: bool) -> None:
            nonlocal viewport_tiles, cached_tiles
            t = (z, x, y)
            if t in seen:
                return
            seen.add(t)
            contained = False
            if cache is not None:
                try:
                    contained = cache.contains(
                        TileCacheKey(provider=provider.name, z=z, x=x, y=y, variant=variant)
                    )
                except Exception:  # noqa: BLE001
                    contained = False
            if in_view:
                viewport_tiles += 1
                if contained:
                    cached_tiles += 1
            if not contained:
                missing.append((prio, z, x, y))

        def full() -> bool:
            return len(missing) >= chunk_cap or len(seen) >= _ENUMERATION_HARD_CAP

        for z in zooms:
            # ★ The CURRENT zoom is always walked fully (coverage must be exact and the
            #   visible area must always be queued first); deeper zooms stop at the chunk.
            is_current = z == report.zoom
            if not is_current and full():
                truncated = True
                break
            depth_prio = _PRIO_FAR + max(0, z - report.zoom)
            base_ranges = _bbox_ranges(report.west, report.south, report.east, report.north, z)
            prefetch_rings = rings if is_current else 0  # rings only at the live zoom
            for base in base_ranges:
                for ring in range(0, prefetch_rings + 1):
                    prio = (
                        (_PRIO_VISIBLE if ring == 0 else (_PRIO_NEAR if ring == 1 else _PRIO_FAR))
                        if is_current
                        else depth_prio
                    )
                    grown = _expand(base, ring, rings)
                    for x in range(grown.min_x, grown.max_x + 1):
                        for y in range(grown.min_y, grown.max_y + 1):
                            if not is_current and full():
                                break
                            visit(prio, z, x, y, in_view=is_current and ring == 0)
                        if not is_current and full():
                            break
                    if not is_current and full():
                        break
            if not is_current and full():
                truncated = True
                break

        # ── decide whether to queue at all ───────────────────────────────────
        # ★ The report must be visible to the workers BEFORE the first tile is queued —
        #   they read provider/kind off it, and an early pop against a stale (or absent)
        #   report would silently discard work.
        with self._lock:
            self._last_report = report
        if len(missing) > chunk_cap:
            truncated = True  # the queue will cut the current-zoom overflow too
        queued = 0
        offline = bool(settings.imagery_offline)
        manual_active = has_active_operation(report.provider)
        if not self.enabled:
            note = "automatic caching is off"
            truncated = False
        elif offline:
            note = "offline — automatic caching paused; serving cached imagery"
            truncated = False
            _log.info("auto_cache.offline_mode")
        elif manual_active:
            note = "manual offline download active — automatic caching yields"
            truncated = False
            _log.info("auto_cache.yield_to_manual", extra={"provider": report.provider})
        else:
            queued, note = self._replace_queue(report, missing)
            if queued == 0:
                # ★ No progress is possible (session limit, or nothing missing) — the
                #   frontend's continue-on-drain loop must stop here, not spin.
                truncated = False

        session = self._session_snapshot()
        status = AutoCacheStatus(
            enabled=self.enabled,
            online=not offline and not self._network_paused(),
            active=queued > 0 or self._pending() > 0,
            provider=report.provider,
            kind=report.kind,
            zoom=report.zoom,
            viewport_tiles=viewport_tiles,
            cached_tiles=cached_tiles,
            missing_tiles=viewport_tiles - cached_tiles,
            coverage_percent=round(100.0 * cached_tiles / viewport_tiles, 1)
            if viewport_tiles
            else 100.0,
            queued_tiles=self._pending(),
            truncated=truncated,
            note=note,
            session=session,
        )
        with self._lock:
            self._last_report = report
            self._last_status = status
        return status

    def _replace_queue(
        self, report: ViewportReport, missing: list[tuple[int, int, int, int]]
    ) -> tuple[int, str | None]:
        """★ STALE-JOB CANCELLATION: the new viewport's needs REPLACE the queue.
        Limits are applied here, preferring visible tiles over prefetch."""
        settings = self._settings
        note: str | None = None
        missing.sort(key=lambda t: t[0])  # visible first, then near, then far

        per_viewport = settings.imagery_auto_cache_max_tiles_per_viewport
        if per_viewport and len(missing) > per_viewport:
            missing = missing[:per_viewport]
            note = f"limited to {per_viewport} tiles this viewport (AUTO_CACHE_MAX_TILES_PER_VIEWPORT)"
            _log.info("auto_cache.limit_reached", extra={"limit": "per_viewport"})

        with self._lock:
            cap = settings.imagery_auto_cache_max_tiles_per_session
            if cap:
                budget = cap - self._session.tiles_requested
                if budget <= 0:
                    self._session.limit_reached = "session tile limit"
                    _log.warning("auto_cache.limit_reached", extra={"limit": "per_session"})
                    return 0, (
                        f"session limit of {cap} automatic tiles reached — "
                        "toggle automatic caching or use a manual offline area"
                    )
                if len(missing) > budget:
                    missing = missing[:budget]
            byte_cap = settings.imagery_auto_cache_max_session_bytes
            if byte_cap and self._session.bytes_downloaded >= byte_cap:
                self._session.limit_reached = "session storage limit"
                _log.warning("auto_cache.limit_reached", extra={"limit": "session_bytes"})
                return 0, "session storage limit reached — use a manual offline area"

            dropped = len(self._queue)
            self._queue.clear()
            self._queued_keys.clear()
            self._generation += 1
            gen = self._generation
            for prio, z, x, y in missing:
                self._queue.append(_QueuedTile(prio, gen, z, x, y))
                self._queued_keys.add((z, x, y))
            self._session.tiles_requested += len(missing)
            self._wake.notify_all()
        if dropped:
            _log.info("auto_cache.stale_jobs_cancelled", extra={"dropped": dropped})
        if missing:
            _log.info(
                "auto_cache.started",
                extra={"queued": len(missing), "zoom": report.zoom, "provider": report.provider},
            )
        self._ensure_workers()
        return len(missing), note

    # ── status without a new report ──────────────────────────────────────────

    def status(self) -> AutoCacheStatus:
        with self._lock:
            last = self._last_status
        if last is not None:
            return last.model_copy(
                update={
                    "enabled": self.enabled,
                    "online": not self._settings.imagery_offline and not self._network_paused(),
                    "queued_tiles": self._pending(),
                    "active": self._pending() > 0,
                    "session": self._session_snapshot(),
                }
            )
        return AutoCacheStatus(
            enabled=self.enabled,
            online=not self._settings.imagery_offline and not self._network_paused(),
            active=False,
            provider=None,
            kind="satellite",
            zoom=None,
            viewport_tiles=0,
            cached_tiles=0,
            missing_tiles=0,
            coverage_percent=None,
            queued_tiles=0,
            truncated=False,
            note=None,
            session=self._session_snapshot(),
        )

    # ── internals ────────────────────────────────────────────────────────────

    def _zooms_for(self, zoom: int, provider) -> list[int]:
        """The zoom levels a report enumerates, current zoom FIRST (it takes priority).

        ★ ``full_detail`` adds every deeper zoom of the visible area up to
        ``AUTO_CACHE_MAX_ZOOM`` — but only once the user is at
        ``FULL_DETAIL_MIN_ZOOM`` or deeper: a wide (z<15) viewport times every zoom is
        millions of tiles, so below the gate it degrades to current-only.
        """
        settings = self._settings
        mode = (settings.imagery_auto_cache_zoom_range or "current_only").strip().lower()
        lo, hi = provider.min_zoom, provider.max_zoom
        zooms = [zoom]
        if mode == "current_plus_one":
            zooms.append(zoom + 1)
        elif mode == "current_plus_minus_one":
            zooms.extend([zoom - 1, zoom + 1])
        elif mode == "full_detail" and zoom >= settings.imagery_auto_cache_full_detail_min_zoom:
            ceiling = min(hi, settings.imagery_auto_cache_max_zoom)
            zooms.extend(range(zoom + 1, ceiling + 1))
        return [z for z in dict.fromkeys(zooms) if lo <= z <= hi]

    def _imagery_ref(self, imagery: ImageryService) -> None:
        # Keep ONE long-lived service for the workers (its registry caches provider
        # instances; per-request instances would rebuild connection pools).
        if self._imagery is None:
            self._imagery = imagery

    def _pending(self) -> int:
        return len(self._queue)

    def _network_paused(self) -> bool:
        return time.monotonic() < self._paused_until

    def _session_snapshot(self) -> AutoCacheSession:
        s = self._session
        return AutoCacheSession(
            started_at=s.started_at,
            project_id=s.project_id,
            tiles_requested=s.tiles_requested,
            tiles_downloaded=s.tiles_downloaded,
            tiles_skipped_cached=s.tiles_skipped_cached,
            tiles_no_imagery=s.tiles_no_imagery,
            tiles_failed=s.tiles_failed,
            bytes_downloaded=s.bytes_downloaded,
            limit_reached=s.limit_reached,
        )

    # ── workers ──────────────────────────────────────────────────────────────

    def _ensure_workers(self) -> None:
        with self._lock:
            if self._workers_started:
                return
            self._workers_started = True
        count = int(self._settings.imagery_auto_cache_concurrency)
        for i in range(count):
            threading.Thread(
                target=self._worker, name=f"auto-cache-{i}", daemon=True
            ).start()
        _log.info("auto_cache.workers_started", extra={"count": count})

    def _pop(self) -> _QueuedTile | None:
        """Highest-priority pending tile, or None after a short wait. Holds the lock."""
        with self._wake:
            if not self._queue:
                self._wake.wait(timeout=1.0)
                if not self._queue:
                    return None
            best_i = min(range(len(self._queue)), key=lambda i: self._queue[i].priority)
            item = self._queue[best_i]
            del self._queue[best_i]
            self._queued_keys.discard((item.z, item.x, item.y))
            return item

    def _worker(self) -> None:
        while not self._stop.is_set():
            if self._network_paused() or not self.enabled:
                time.sleep(0.5)
                continue
            if has_active_operation():
                time.sleep(1.0)  # manual AOI download owns the budget right now
                continue
            item = self._pop()
            if item is None:
                continue
            with self._lock:
                stale = item.generation != self._generation
                report = self._last_report
            if stale or report is None:
                continue  # a viewport the user already left
            self._fetch(report, item)

    def _fetch(self, report: ViewportReport, item: _QueuedTile) -> None:
        imagery = self._imagery
        if imagery is None:
            return
        byte_cap = self._settings.imagery_auto_cache_max_session_bytes
        # ★ The tile is tallied into the session it was FETCHED FOR (2026-09-02).
        #   A project switch swaps `self._session` while workers are mid-download;
        #   crediting the swap-time session gave the NEW project's fresh tallies a
        #   head start of the old project's stragglers (seen as a full-suite-only
        #   test failure: 79 alpha tiles counted into beta's "fresh" session).
        #   A straggler now counts into its own — by then discarded — session.
        with self._lock:
            session = self._session
        try:
            data, _mime = imagery.get_tile_bytes(
                report.provider,
                item.z,
                item.x,
                item.y,
                kind=BasemapKind(report.kind),
                source="viewport",
            )
            with self._lock:
                session.tiles_downloaded += 1
                session.bytes_downloaded += len(data)
                if (
                    byte_cap
                    and session is self._session
                    and session.bytes_downloaded >= byte_cap
                ):
                    session.limit_reached = "session storage limit"
                    self._queue.clear()
                    self._queued_keys.clear()
                    _log.warning("auto_cache.limit_reached", extra={"limit": "session_bytes"})
            self._consecutive_failures = 0
        except TileNotAvailableError:
            with self._lock:
                session.tiles_no_imagery += 1  # ocean/gap — an answer, not a failure
            self._consecutive_failures = 0
        except ProviderRateLimitError as exc:
            # The HTTP layer already honoured Retry-After through its retry budget;
            # here we just slow the queue instead of failing tiles.
            with self._lock:
                session.tiles_failed += 1
            retry = float(getattr(exc, "retry_after", None) or 2.0)
            time.sleep(min(retry, 10.0))
        except (ProviderTransportError, GisError, LandExplorerError) as exc:
            with self._lock:
                session.tiles_failed += 1
            self._consecutive_failures += 1
            _log.info(
                "auto_cache.tile_failed",
                extra={"tile": f"{item.z}/{item.x}/{item.y}", "error": str(exc)},
            )
            if self._consecutive_failures >= _OFFLINE_AFTER_FAILURES:
                # ★ The network is gone: pause rather than hammer. Resumes by itself;
                #   the next viewport report re-queues whatever is still relevant.
                self._paused_until = time.monotonic() + _OFFLINE_BACKOFF_SECONDS
                self._consecutive_failures = 0
                _log.warning("auto_cache.offline_backoff", extra={"seconds": _OFFLINE_BACKOFF_SECONDS})


_MANAGER: ViewportCacheManager | None = None
_MANAGER_LOCK = threading.Lock()


def get_viewport_cache_manager(settings: Settings | None = None) -> ViewportCacheManager:
    """The process-wide manager (workers + queue + session must outlive requests)."""
    global _MANAGER
    if _MANAGER is None:
        with _MANAGER_LOCK:
            if _MANAGER is None:
                _MANAGER = ViewportCacheManager(settings)
    return _MANAGER


def reset_viewport_cache() -> None:
    """Drop the manager (stops feeding its workers). For tests."""
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is not None:
            _MANAGER._stop.set()  # noqa: SLF001
            with _MANAGER._lock:  # noqa: SLF001
                _MANAGER._queue.clear()  # noqa: SLF001
                _MANAGER._queued_keys.clear()  # noqa: SLF001
        _MANAGER = None
