"""``OfflineCacheService`` — AOI pre-caching for offline field work (Offline Area Manager).

★ **NO SECOND TILE PATH.** The download worker pulls every tile through
``ImageryService.get_tile_bytes`` — the same read-through cache, licence gate, rate
limiter, retry policy and usage ledger as the live map. "Prepare this area for offline"
is *requesting* its tiles, nothing more; the only new machinery is enumeration,
budgeting, progress and the manifest.

★ **DESKTOP-FIRST.** Runs are plain daemon threads with bounded concurrency — no Celery,
no Redis required. State lives in a process-wide registry (operations do not survive a
restart; re-running the same AOI is cheap because cached tiles are skipped) and the
manifest is a JSON file next to the tile cache.

★ **BUDGETS ARE REFUSALS, NOT SURPRISES.** Per-operation and prefetch caps are enforced
BEFORE the first request; the per-day cap is checked against the persisted daily ledger
as the run proceeds, pausing the run (resumable tomorrow) rather than blowing through it.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from gis.errors import GisError, TileNotAvailableError
from gis.imagery.cache.base import TileCacheKey
from gis.tiles import tiles_for_polygon
from gis.types import BasemapKind, TileRef

from app.core.config import Settings
from app.core.exceptions import (
    LandExplorerError,
    OfflineManifestNotFound,
    PrecacheBudgetExceeded,
    PrecacheConflict,
    PrecacheOperationNotFound,
)
from app.schemas.offline import (
    OfflineAreaRequest,
    OfflineCoverage,
    OfflineEstimate,
    OfflineManifest,
    PrecacheBudget,
    PrecacheOperation,
)
from app.services.imagery_service import ImageryService
from app.services.imagery_usage import get_usage

__all__ = ["OfflineCacheService", "reset_operations"]

_log = logging.getLogger("app.services.offline_cache")

_HARD_ENUMERATION_CAP = 200_000
"""Absolute ceiling on enumerated tiles per request — a memory guard above any budget."""

_DEFAULT_TILE_SIZE_BYTES = 30_000
"""Stated default for storage estimates when nothing is cached yet to measure.
~30 KB is a typical 512 px jpg90 satellite tile; the estimate says it used a default."""

_DOWNLOAD_CONCURRENCY = 4
"""Bounded worker threads per run. The provider's token bucket is the true rate guard;
this only bounds in-flight sockets and thread count on a desktop machine."""


# ── in-process operation registry ─────────────────────────────────────────────


@dataclass
class _Op:
    """One pre-cache run's mutable state. Guarded by ``lock`` for counters."""

    id: str
    provider: str
    kind: str
    ring: list[tuple[float, float]]
    zoom_min: int
    zoom_max: int
    project_id: str | None
    tiles: list[TileRef]
    total: int
    state: str = "pending"
    completed: int = 0
    skipped_cached: int = 0
    no_imagery: int = 0
    failed: int = 0
    downloaded_bytes: int = 0
    note: str | None = None
    manifest_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    failed_tiles: list[TileRef] = field(default_factory=list)
    pause_evt: threading.Event = field(default_factory=threading.Event)
    cancel_evt: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def remaining(self) -> int:
        return max(0, self.total - self.completed - self.skipped_cached - self.no_imagery - self.failed)


_OPS: dict[str, _Op] = {}
_OPS_LOCK = threading.Lock()


def reset_operations() -> None:
    """Cancel and drop every operation. For tests."""
    with _OPS_LOCK:
        for op in _OPS.values():
            op.cancel_evt.set()
        _OPS.clear()


def has_active_operation(provider: str | None = None) -> bool:
    """Is a manual Offline Area download live (pending/running/paused-resumable)?

    ★ Read by the automatic viewport cacher, which YIELDS to manual downloads: a
    surveyor deliberately preparing an AOI must get a predictable run, not one that
    competes with background prefetch for the same rate-limit bucket.
    """
    with _OPS_LOCK:
        return any(
            (provider is None or op.provider == provider)
            and op.state in ("pending", "running")
            for op in _OPS.values()
        )


# ── the service ───────────────────────────────────────────────────────────────


class OfflineCacheService:
    """Estimate, download, track and describe offline tile areas.

    Args:
        settings: Backend settings — budgets, cache paths.
        imagery: The imagery service the worker fetches through. Constructed from
            ``settings`` when not injected (tests inject a fake).
    """

    def __init__(self, settings: Settings, *, imagery: ImageryService | None = None) -> None:
        self._settings = settings
        self._imagery = imagery if imagery is not None else ImageryService(settings)

    # ── enumeration & estimation ──────────────────────────────────────────────

    def _enumerate(self, req: OfflineAreaRequest) -> tuple[list[TileRef], bool]:
        ring = [(float(p[0]), float(p[1])) for p in req.polygon]
        try:
            return tiles_for_polygon(
                ring, req.zoom_min, req.zoom_max, cap=_HARD_ENUMERATION_CAP
            )
        except ValueError as exc:
            raise PrecacheConflict(str(exc)) from exc

    def _cache_key(self, provider_name: str, kind: str, t: TileRef) -> TileCacheKey:
        provider = self._imagery.get_provider(provider_name)
        return TileCacheKey(
            provider=provider.name,
            z=t.z,
            x=t.x,
            y=t.y,
            variant=provider.cache_variant(BasemapKind(kind)),
        )

    def _split_cached(
        self, provider_name: str, kind: str, tiles: list[TileRef]
    ) -> tuple[list[TileRef], int]:
        """Partition ``tiles`` into (missing, cached_count) via cheap ``contains``."""
        cache = self._imagery.tile_cache
        if cache is None:
            return (list(tiles), 0)
        provider = self._imagery.get_provider(provider_name)
        variant = provider.cache_variant(BasemapKind(kind))
        missing: list[TileRef] = []
        cached = 0
        for t in tiles:
            key = TileCacheKey(
                provider=provider.name, z=t.z, x=t.x, y=t.y, variant=variant
            )
            try:
                if cache.contains(key):
                    cached += 1
                else:
                    missing.append(t)
            except Exception:  # noqa: BLE001 — a cache fault means "treat as missing"
                missing.append(t)
        return (missing, cached)

    def _budgets_for(self, provider_name: str) -> tuple[int | None, int | None, int | None]:
        """``(per_operation, max_prefetch, per_day)`` limits for a provider; None = none.

        Only Mapbox has configured budgets today; the tuple shape keeps the door open for
        per-provider settings without another code path.
        """
        if provider_name == "mapbox_satellite":
            s = self._settings
            return (
                s.mapbox_max_tile_requests_per_operation or None,
                s.mapbox_max_prefetch_tiles or None,
                s.mapbox_max_tile_requests_per_day or None,
            )
        return (None, None, None)

    def _average_tile_size(self, provider_name: str) -> tuple[int, str]:
        cache = self._imagery.tile_cache
        sample = None
        if cache is not None and hasattr(cache, "sample_average_tile_size"):
            try:
                sample = cache.sample_average_tile_size(provider_name)
            except Exception:  # noqa: BLE001
                sample = None
        if sample:
            return (int(sample), "measured")
        return (_DEFAULT_TILE_SIZE_BYTES, "default")

    def estimate(self, req: OfflineAreaRequest) -> OfflineEstimate:
        """Tile counts, upstream requests and storage for a would-be run — endpoint input
        to the Offline Area Manager's confirmation panel. Read-only; fetches nothing."""
        tiles, capped = self._enumerate(req)
        missing, cached = self._split_cached(req.provider, req.kind, tiles)
        avg, avg_source = self._average_tile_size(req.provider)
        per_op, max_prefetch, per_day = self._budgets_for(req.provider)
        used_today = get_usage().upstream_today(req.provider)

        within, reason = True, None
        if capped:
            within = False
            reason = (
                f"AOI enumerates more than {_HARD_ENUMERATION_CAP:,} tiles; shrink the "
                "area or the zoom band."
            )
        elif max_prefetch is not None and len(tiles) > max_prefetch:
            within = False
            reason = (
                f"{len(tiles):,} tiles exceeds LE_MAPBOX_MAX_PREFETCH_TILES "
                f"({max_prefetch:,}); shrink the AOI/zoom range or raise the setting."
            )
        elif per_op is not None and len(missing) > per_op:
            within = False
            reason = (
                f"{len(missing):,} new tiles exceeds "
                f"LE_MAPBOX_MAX_TILE_REQUESTS_PER_OPERATION ({per_op:,}); shrink the "
                "AOI/zoom range or raise the setting."
            )
        elif per_day is not None and used_today + len(missing) > per_day:
            within = False
            reason = (
                f"{used_today:,} upstream requests already used today; "
                f"{len(missing):,} more would exceed LE_MAPBOX_MAX_TILE_REQUESTS_PER_DAY "
                f"({per_day:,})."
            )

        return OfflineEstimate(
            provider=req.provider,
            zoom_min=req.zoom_min,
            zoom_max=req.zoom_max,
            total_tiles=len(tiles),
            cached_tiles=cached,
            missing_tiles=len(missing),
            estimated_upstream_requests=len(missing),
            average_tile_size_bytes=avg,
            average_tile_size_source=avg_source,  # type: ignore[arg-type]
            estimated_storage_bytes=avg * len(missing),
            capped=capped,
            budget=PrecacheBudget(
                per_operation_limit=per_op,
                max_prefetch_tiles=max_prefetch,
                per_day_limit=per_day,
                per_day_used=used_today,
                within_budget=within,
                reason=reason,
            ),
        )

    def coverage(self, req: OfflineAreaRequest) -> OfflineCoverage:
        """How much of the AOI the cache already holds, overall and per zoom."""
        tiles, capped = self._enumerate(req)
        cache = self._imagery.tile_cache
        provider = self._imagery.get_provider(req.provider)
        variant = provider.cache_variant(BasemapKind(req.kind))
        by_zoom: dict[str, dict[str, int]] = {}
        cached_total = 0
        for t in tiles:
            bucket = by_zoom.setdefault(str(t.z), {"total": 0, "cached": 0})
            bucket["total"] += 1
            if cache is not None:
                key = TileCacheKey(
                    provider=provider.name, z=t.z, x=t.x, y=t.y, variant=variant
                )
                try:
                    if cache.contains(key):
                        bucket["cached"] += 1
                        cached_total += 1
                except Exception:  # noqa: BLE001
                    pass
        return OfflineCoverage(
            provider=req.provider,
            total_tiles=len(tiles),
            cached_tiles=cached_total,
            coverage_ratio=(cached_total / len(tiles)) if tiles else 0.0,
            by_zoom=by_zoom,
            capped=capped,
        )

    # ── run lifecycle ─────────────────────────────────────────────────────────

    def start(self, req: OfflineAreaRequest) -> PrecacheOperation:
        """Validate budgets, register the run and launch the worker threads.

        Raises:
            PrecacheBudgetExceeded: The run exceeds a configured budget — the estimate's
                ``budget.reason`` verbatim, so the refusal names the setting.
            PrecacheConflict: A run for this provider is already active.
        """
        estimate = self.estimate(req)
        if not estimate.budget.within_budget:
            raise PrecacheBudgetExceeded(estimate.budget.reason or "over budget")

        with _OPS_LOCK:
            for other in _OPS.values():
                if other.provider == req.provider and other.state in ("pending", "running", "paused"):
                    raise PrecacheConflict(
                        f"operation {other.id} for {req.provider} is already "
                        f"{other.state}; cancel it or let it finish first"
                    )
            tiles, _capped = self._enumerate(req)
            op = _Op(
                id=uuid.uuid4().hex[:12],
                provider=req.provider,
                kind=req.kind,
                ring=[(float(p[0]), float(p[1])) for p in req.polygon],
                zoom_min=req.zoom_min,
                zoom_max=req.zoom_max,
                project_id=req.project_id,
                tiles=tiles,
                total=len(tiles),
            )
            _OPS[op.id] = op

        thread = threading.Thread(
            target=self._run, args=(op,), name=f"precache-{op.id}", daemon=True
        )
        op.state = "running"
        op.started_at = datetime.now(UTC)
        thread.start()
        _log.info(
            "precache.started",
            extra={"op": op.id, "provider": op.provider, "tiles": op.total},
        )
        return self._status(op)

    def _run(self, op: _Op) -> None:
        """The download loop. Runs in a daemon thread; never raises."""
        _per_op, _prefetch, per_day = self._budgets_for(op.provider)
        usage = get_usage()
        queue = list(op.tiles)

        def next_tile() -> TileRef | None:
            with op.lock:
                if not queue:
                    return None
                return queue.pop(0)

        def worker() -> None:
            while True:
                if op.cancel_evt.is_set():
                    return
                while op.pause_evt.is_set():
                    if op.cancel_evt.is_set():
                        return
                    op.cancel_evt.wait(0.25)
                if per_day is not None and usage.upstream_today(op.provider) >= per_day:
                    # ★ The daily budget ran out mid-run: PAUSE, resumable, with the
                    #   reason on the operation — never a silent overrun.
                    with op.lock:
                        op.note = (
                            "paused: LE_MAPBOX_MAX_TILE_REQUESTS_PER_DAY "
                            f"({per_day:,}) reached; resume tomorrow or raise the limit"
                        )
                    op.pause_evt.set()
                    continue
                t = next_tile()
                if t is None:
                    return
                self._fetch_one(op, t)

        try:
            workers = min(_DOWNLOAD_CONCURRENCY, max(1, op.total))
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f"pc-{op.id}") as pool:
                futures = [pool.submit(worker) for _ in range(workers)]
                for f in futures:
                    f.exception()  # workers never raise; this only awaits them
        except Exception as exc:  # noqa: BLE001 — a run failure is a state, not a crash
            with op.lock:
                op.state = "failed"
                op.note = f"run crashed: {exc}"
                op.finished_at = datetime.now(UTC)
            _log.warning("precache.failed", extra={"op": op.id, "error": str(exc)})
            return

        with op.lock:
            if op.cancel_evt.is_set():
                op.state = "cancelled"
            elif op.pause_evt.is_set() and op.remaining > 0:
                op.state = "paused"
            else:
                op.state = "completed"
            op.finished_at = datetime.now(UTC)
        if op.state == "completed":
            self._write_manifest(op)
            self._post_run_sweep()
        _log.info(
            "precache.%s" % op.state,
            extra={
                "op": op.id,
                "completed": op.completed,
                "cached": op.skipped_cached,
                "failed": op.failed,
            },
        )

    def _fetch_one(self, op: _Op, t: TileRef) -> None:
        """Pull one tile through the normal read-through path; classify the outcome."""
        cache = self._imagery.tile_cache
        try:
            key = self._cache_key(op.provider, op.kind, t)
            if cache is not None and cache.contains(key):
                with op.lock:
                    op.skipped_cached += 1
                return
        except Exception:  # noqa: BLE001 — treat as uncached
            pass
        try:
            data, _mime = self._imagery.get_tile_bytes(
                op.provider, t.z, t.x, t.y, kind=BasemapKind(op.kind), source="precache"
            )
            with op.lock:
                op.completed += 1
                op.downloaded_bytes += len(data)
        except TileNotAvailableError:
            with op.lock:
                op.no_imagery += 1  # ocean/gap — a real answer, not a failure
        except (GisError, LandExplorerError) as exc:
            with op.lock:
                op.failed += 1
                op.failed_tiles.append(t)
                if op.failed <= 3:
                    op.note = f"last error: {exc}"

    def _post_run_sweep(self) -> None:
        """Enforce the size cap after a large write burst. Best-effort."""
        cache = self._imagery.tile_cache
        if cache is not None and hasattr(cache, "sweep"):
            try:
                cache.sweep(
                    negative_ttl_s=self._settings.imagery_negative_tile_cache_ttl_seconds
                )
            except Exception:  # noqa: BLE001
                pass

    # ── run control ───────────────────────────────────────────────────────────

    def _get_op(self, op_id: str) -> _Op:
        op = _OPS.get(op_id)
        if op is None:
            raise PrecacheOperationNotFound(f"no pre-cache operation {op_id!r}")
        return op

    def pause(self, op_id: str) -> PrecacheOperation:
        op = self._get_op(op_id)
        if op.state not in ("running",):
            raise PrecacheConflict(f"operation {op_id} is {op.state}; only a running one pauses")
        op.pause_evt.set()
        with op.lock:
            op.state = "paused"
        return self._status(op)

    def resume(self, op_id: str) -> PrecacheOperation:
        op = self._get_op(op_id)
        if op.state != "paused":
            raise PrecacheConflict(f"operation {op_id} is {op.state}; only a paused one resumes")
        with op.lock:
            op.note = None
            op.state = "running"
        was_finished = op.finished_at is not None
        op.pause_evt.clear()
        if was_finished:
            # The worker pool already drained (e.g. paused by the daily budget and the
            # threads exited). Relaunch over what remains.
            with op.lock:
                op.finished_at = None
            threading.Thread(
                target=self._run, args=(op,), name=f"precache-{op.id}", daemon=True
            ).start()
        return self._status(op)

    def cancel(self, op_id: str) -> PrecacheOperation:
        op = self._get_op(op_id)
        if op.state in ("completed", "cancelled", "failed"):
            raise PrecacheConflict(f"operation {op_id} already {op.state}")
        op.cancel_evt.set()
        op.pause_evt.clear()
        with op.lock:
            op.state = "cancelled"
        return self._status(op)

    def retry_failed(self, op_id: str) -> PrecacheOperation:
        """Re-queue this run's failed tiles as a fresh pass."""
        op = self._get_op(op_id)
        if op.state not in ("completed", "failed", "cancelled", "paused"):
            raise PrecacheConflict(f"operation {op_id} is {op.state}; wait for it to stop")
        with op.lock:
            if not op.failed_tiles:
                raise PrecacheConflict(f"operation {op_id} has no failed tiles to retry")
            op.tiles = list(op.failed_tiles)
            op.failed_tiles = []
            op.failed = 0
            op.note = None
            op.state = "running"
            op.finished_at = None
        op.cancel_evt.clear()
        op.pause_evt.clear()
        threading.Thread(
            target=self._run, args=(op,), name=f"precache-{op.id}", daemon=True
        ).start()
        return self._status(op)

    def list_operations(self) -> list[PrecacheOperation]:
        with _OPS_LOCK:
            ops = list(_OPS.values())
        return [self._status(op) for op in sorted(ops, key=lambda o: o.id)]

    def get_operation(self, op_id: str) -> PrecacheOperation:
        return self._status(self._get_op(op_id))

    def _status(self, op: _Op) -> PrecacheOperation:
        with op.lock:
            done = op.completed + op.skipped_cached + op.no_imagery + op.failed
            return PrecacheOperation(
                id=op.id,
                state=op.state,  # type: ignore[arg-type]
                provider=op.provider,
                kind=op.kind,  # type: ignore[arg-type]
                zoom_min=op.zoom_min,
                zoom_max=op.zoom_max,
                project_id=op.project_id,
                total_tiles=op.total,
                completed_tiles=op.completed,
                skipped_cached=op.skipped_cached,
                no_imagery_tiles=op.no_imagery,
                failed_tiles=op.failed,
                remaining_tiles=op.remaining,
                downloaded_bytes=op.downloaded_bytes,
                percent=round(100.0 * done / op.total, 2) if op.total else 100.0,
                started_at=op.started_at,
                finished_at=op.finished_at,
                note=op.note,
                manifest_id=op.manifest_id,
            )

    # ── manifests ─────────────────────────────────────────────────────────────

    def _manifest_dir(self) -> Path:
        return Path(self._settings.imagery_tile_cache_dir) / "manifests"

    def _write_manifest(self, op: _Op) -> None:
        """Write the offline-area manifest for a completed run. Best-effort."""
        try:
            provider = self._imagery.get_provider(op.provider)
            caps = provider.capabilities()
            variant = provider.cache_variant(BasemapKind(op.kind))
            ttl = provider.cache_ttl_seconds
            if ttl is None:
                ttl = self._settings.imagery_tile_cache_ttl_seconds
            created = datetime.now(UTC)
            lons = [p[0] for p in op.ring]
            lats = [p[1] for p in op.ring]
            manifest = OfflineManifest(
                id=op.id,
                project_id=op.project_id,
                provider=op.provider,
                kind=op.kind,  # type: ignore[arg-type]
                cache_variant=variant,
                polygon=[[lon, lat] for lon, lat in op.ring],
                bbox=[min(lons), min(lats), max(lons), max(lats)],
                zoom_min=op.zoom_min,
                zoom_max=op.zoom_max,
                tile_size_px=caps.tile_size_px,
                tile_count=op.total,
                completed_tiles=op.completed + op.skipped_cached,
                no_imagery_tiles=op.no_imagery,
                missing_tiles=op.failed + op.remaining,
                downloaded_bytes=op.downloaded_bytes,
                created_at=created,
                expires_at=(created + timedelta(seconds=ttl)) if ttl and ttl > 0 else None,
            )
            directory = self._manifest_dir()
            directory.mkdir(parents=True, exist_ok=True)
            (directory / f"{op.id}.json").write_text(manifest.model_dump_json(indent=2))
            with op.lock:
                op.manifest_id = op.id
        except Exception as exc:  # noqa: BLE001 — a manifest failure must not fail the run
            _log.warning("precache.manifest_failed", extra={"op": op.id, "error": str(exc)})

    def list_manifests(self) -> list[OfflineManifest]:
        directory = self._manifest_dir()
        manifests: list[OfflineManifest] = []
        if not directory.is_dir():
            return manifests
        for path in sorted(directory.glob("*.json")):
            try:
                manifests.append(OfflineManifest.model_validate_json(path.read_text()))
            except (OSError, ValueError):
                _log.warning("offline manifest %s is unreadable; skipping", path)
        return manifests

    def delete_manifest(self, manifest_id: str) -> None:
        """Forget an offline area. ★ Deletes the RECORD only — cached tiles are shared
        with the live map (and possibly other areas) and are reclaimed by TTL/size GC,
        never yanked out from under a map that may be offline right now."""
        path = self._manifest_dir() / f"{manifest_id}.json"
        if not path.is_file():
            raise OfflineManifestNotFound(f"no offline manifest {manifest_id!r}")
        try:
            path.unlink()
        except OSError as exc:
            raise OfflineManifestNotFound(f"cannot remove manifest {manifest_id!r}: {exc}") from exc
