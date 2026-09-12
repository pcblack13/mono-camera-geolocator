"""The maintenance beat — tile-cache GC, export TTL sweep, stale-job reaper (§2.4).

These are periodic tasks (scheduled in ``celery_app.beat_schedule``), not job-backed work,
so they do **not** go through :func:`~app.tasks.base.job_lifecycle`. Each is idempotent and
self-limiting: a beat that fires twice, or on top of the previous run, must be harmless.

* **tile-cache GC** enforces the disk tile cache's TTL and its ``LE_IMAGERY_TILE_CACHE_MAX_BYTES``
  LRU cap. A shared disk cache in a container grows without bound otherwise; this keeps it
  under budget by evicting the least-recently-used tiles.
* **export TTL sweep** reclaims the bytes of exports past ``expires_at``. The row is left in
  place — the download endpoint serves ``410 EXPORT_EXPIRED`` from ``expires_at`` — so this
  only deletes the artefact from storage (idempotently).
* **stale-job reaper** fails jobs that have sat in a live state past
  ``LE_JOB_STALE_AFTER_SECONDS``. This is the safety net behind ``JobQueue.submit`` raising
  ``WorkerUnavailable``: a job whose broker submit failed stays ``pending`` and a surveyor
  watches a spinner forever — until this marks it ``failed`` with a legible reason.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from celery import shared_task
from sqlalchemy import func, inspect, update

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.repositories.jobs import JOB_MODEL_BY_TYPE, LIVE_JOB_STATUSES
from app.db.session import get_sessionmaker, sync_session
from app.storage import get_storage
from app.tasks.base import run_async
from app.tasks.celery_app import (
    TASK_EXPORT_TTL_SWEEP,
    TASK_STALE_JOB_REAPER,
    TASK_TILE_CACHE_GC,
)

__all__ = [
    "export_ttl_sweep_task",
    "stale_job_reaper_task",
    "tile_cache_gc_task",
]

log = get_logger(__name__)


# ── tile cache GC ─────────────────────────────────────────────────────────────


@shared_task(name=TASK_TILE_CACHE_GC)
def tile_cache_gc_task() -> dict[str, int]:
    """Evict expired and over-budget tiles from the disk cache. Returns a small summary.

    ★ Delegates to ``tile_cache_maintenance.sweep_tile_cache`` — ONE sweep implementation
    (``DiskTileCache.sweep``: per-provider ToS TTLs, negatives, temp files, corruption,
    the size cap) shared with the desktop API process, which has no beat and sweeps from
    its own lifespan instead.
    """
    from app.services.tile_cache_maintenance import sweep_tile_cache

    settings = get_settings()
    result = sweep_tile_cache(settings)
    log.info("maintenance.tile_cache_gc", **{k: int(v) for k, v in result.items()})
    return result


# ── export TTL sweep ──────────────────────────────────────────────────────────


@shared_task(name=TASK_EXPORT_TTL_SWEEP)
def export_ttl_sweep_task() -> dict[str, int]:
    """Delete the stored bytes of exports past their TTL. The row is left to serve 410."""
    storage = get_storage()

    def _paths() -> list[str]:
        from app.db.repositories.exports import ExportRepository

        async def _load() -> list[str]:
            factory = get_sessionmaker()
            async with factory() as session:
                expired = await ExportRepository(session).find_expired(limit=500)
                return [e.storage_path for e in expired if e.storage_path]

        return run_async(_load)

    deleted = 0
    for path in _paths():
        try:
            if storage.delete(path):
                deleted += 1
        except Exception as exc:  # noqa: BLE001 — one bad path must not abort the sweep
            log.warning("maintenance.export_delete_failed", storage_path=path, error=str(exc))

    log.info("maintenance.export_ttl_sweep", deleted=deleted)
    return {"deleted": deleted}


# ── stale job reaper ──────────────────────────────────────────────────────────


@shared_task(name=TASK_STALE_JOB_REAPER)
def stale_job_reaper_task() -> dict[str, int]:
    """Fail jobs that have sat in a live state past ``LE_JOB_STALE_AFTER_SECONDS``.

    A bulk, guarded ``UPDATE`` per job table (the four are ``match_jobs``, ``aux_jobs``,
    ``batch_jobs``, ``exports``): live status **and** ``updated_at`` older than the cutoff
    → ``failed`` with a legible reason. Bulk rather than per-row because this is the reaper,
    not a state machine — there is no progress to preserve, only rows to lay to rest.
    """
    settings = get_settings()
    cutoff = datetime.now(UTC) - timedelta(seconds=int(settings.job_stale_after_seconds))
    live = sorted(LIVE_JOB_STATUSES)
    message = (
        f"Job exceeded LE_JOB_STALE_AFTER_SECONDS ({settings.job_stale_after_seconds}s) "
        "without progressing and was reaped. The worker or broker was likely unavailable "
        "when it was submitted."
    )

    reaped = 0
    models = {id(m): m for m in JOB_MODEL_BY_TYPE.values()}.values()  # de-dupe AuxJob
    with sync_session() as db:
        for model in models:
            columns = set(inspect(model).columns.keys())
            values: dict[str, Any] = {"status": "failed"}
            if "error_message" in columns:
                values["error_message"] = message
            if "error_type" in columns:
                values["error_type"] = "StaleJob"
            if "finished_at" in columns:
                values["finished_at"] = func.now()

            stmt = (
                update(model)
                .where(
                    model.status.in_(live),  # type: ignore[attr-defined]
                    model.updated_at < cutoff,  # type: ignore[attr-defined]
                )
                .values(**values)
            )
            result = db.execute(stmt)
            reaped += int(result.rowcount or 0)

    if reaped:
        log.warning("maintenance.stale_jobs_reaped", count=reaped)
    return {"reaped": reaped}
