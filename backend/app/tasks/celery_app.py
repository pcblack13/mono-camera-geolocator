"""The Celery application — broker, queues, routes and the maintenance beat (§2.4).

★ **Three queues, because the three workloads have incompatible shapes** (see
``app.core.queue``): ``cv`` (CPU-saturating, minutes long, low concurrency), ``io``
(network/disk, seconds long, wide), and ``export`` (bursty, a surveyor watching a
spinner). Sharing one queue makes each workload the others' tail latency.

★ **Every setting resolves through ``Settings`` (L10):** ``Settings()`` with an empty
env never raises, so ``celery -A app.tasks.celery_app:celery_app worker`` starts even
with nothing configured — it just points at the default ``redis://redis:6379``. The
broker is *not* contacted at import; ``Celery(...)`` only records the URL.

Task modules are wired in through ``include`` (import paths, resolved by the worker at
startup) rather than imported here, so importing this module to read a task **name** or
to build :class:`~app.tasks.queue.CeleryJobQueue` does not drag in torch/GDAL/PIL.
"""

from __future__ import annotations

from typing import Final

from celery import Celery
from celery.schedules import schedule
from kombu import Queue

from app.core.config import get_settings
from app.core.queue import QUEUE_CV, QUEUE_EXPORT, QUEUE_IO

__all__ = [
    "JOB_TYPE_TO_TASK",
    "TASK_BATCH_AGGREGATE",
    "TASK_BATCH_FANOUT",
    "TASK_EXPORT_TTL_SWEEP",
    "TASK_INGEST",
    "TASK_MATCH",
    "TASK_RECOMPUTE_GCPS",
    "TASK_RENDER_EXPORT",
    "TASK_SEGMENT",
    "TASK_STALE_JOB_REAPER",
    "TASK_SUGGEST_LANDMARKS",
    "TASK_TILE_CACHE_GC",
    "celery_app",
    "get_celery_app",
]

# ── Task names — the single source of truth ───────────────────────────────────
#
# Dotted, matching the module and function, so a name in a log line points straight at
# the code. ``JobSpec.job_type`` (a wire string) is mapped to one of these by
# :data:`JOB_TYPE_TO_TASK`; the queue submits by name (``send_task``) so it never has to
# import the task functions and there is no import cycle worker↔queue.

TASK_INGEST: Final = "app.tasks.ingest.ingest_image_task"
TASK_MATCH: Final = "app.tasks.matching.match_image_task"
TASK_SEGMENT: Final = "app.tasks.segmentation.segment_image_task"
TASK_SUGGEST_LANDMARKS: Final = "app.tasks.segmentation.suggest_landmarks_task"
TASK_RECOMPUTE_GCPS: Final = "app.tasks.gcps.recompute_gcps_task"
TASK_RENDER_EXPORT: Final = "app.tasks.exporting.render_export_task"
TASK_BATCH_FANOUT: Final = "app.tasks.batch.batch_fanout_task"
TASK_BATCH_AGGREGATE: Final = "app.tasks.batch.batch_aggregate_task"

TASK_TILE_CACHE_GC: Final = "app.tasks.maintenance.tile_cache_gc_task"
TASK_EXPORT_TTL_SWEEP: Final = "app.tasks.maintenance.export_ttl_sweep_task"
TASK_STALE_JOB_REAPER: Final = "app.tasks.maintenance.stale_job_reaper_task"

#: ``core.constants.JOB_TYPES`` value → the task that runs it. A batch fans out through
#: :data:`TASK_BATCH_FANOUT`. Deferred job types map to their stub task, which fails the
#: job honestly rather than 404-ing at submit time.
JOB_TYPE_TO_TASK: Final[dict[str, str]] = {
    "ingest": TASK_INGEST,
    "match": TASK_MATCH,
    "segment": TASK_SEGMENT,
    "suggest_landmarks": TASK_SUGGEST_LANDMARKS,
    "gcp_recompute": TASK_RECOMPUTE_GCPS,
    "export": TASK_RENDER_EXPORT,
    "batch": TASK_BATCH_FANOUT,
}

#: Import paths the worker loads so ``@shared_task`` registrations attach to this app.
_INCLUDE: Final[tuple[str, ...]] = (
    "app.tasks.ingest",
    "app.tasks.matching",
    "app.tasks.segmentation",
    "app.tasks.gcps",
    "app.tasks.exporting",
    "app.tasks.batch",
    "app.tasks.maintenance",
    "app.tasks.transcoding",
)

# ── Task → queue routing ──────────────────────────────────────────────────────
#
# CV-family work (matching, segmentation, suggestion) → cv. Ingest, recompute and batch
# bookkeeping → io. Export rendering → export. Maintenance is io.
_TASK_ROUTES: Final[dict[str, dict[str, str]]] = {
    TASK_INGEST: {"queue": QUEUE_IO},
    TASK_MATCH: {"queue": QUEUE_CV},
    TASK_SEGMENT: {"queue": QUEUE_CV},
    TASK_SUGGEST_LANDMARKS: {"queue": QUEUE_CV},
    TASK_RECOMPUTE_GCPS: {"queue": QUEUE_IO},
    TASK_RENDER_EXPORT: {"queue": QUEUE_EXPORT},
    TASK_BATCH_FANOUT: {"queue": QUEUE_IO},
    TASK_BATCH_AGGREGATE: {"queue": QUEUE_IO},
    TASK_TILE_CACHE_GC: {"queue": QUEUE_IO},
    TASK_EXPORT_TTL_SWEEP: {"queue": QUEUE_IO},
    TASK_STALE_JOB_REAPER: {"queue": QUEUE_IO},
}


def _build_celery_app() -> Celery:
    """Construct the Celery app from ``Settings``. No I/O, no broker contact."""
    settings = get_settings()

    app = Celery("landexplorer", include=list(_INCLUDE))
    app.conf.update(
        broker_url=settings.celery_broker_url,
        result_backend=settings.celery_result_backend,
        # JSON only — a payload that crosses the broker must be JSON-serialisable, and
        # ``JobSpec.validate()`` asserts that on the service side. Pickle would silently
        # accept a live session or a numpy scalar and detonate in the worker.
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        # ★ acks_late + the task-entry terminal-guard (see BaseJobTask) is what makes a
        # broker redelivery safe: a job that already finished is re-read and skipped.
        task_acks_late=settings.celery_acks_late,
        task_reject_on_worker_lost=True,
        # One CV task wants a whole core; prefetching hides jobs behind a busy worker.
        worker_prefetch_multiplier=settings.celery_prefetch_multiplier,
        worker_concurrency=settings.celery_worker_concurrency,
        task_soft_time_limit=settings.celery_task_soft_time_limit,
        task_time_limit=settings.celery_task_time_limit,
        task_always_eager=settings.celery_task_always_eager,
        task_eager_propagates=True,
        task_default_queue=QUEUE_IO,
        task_queues=(
            Queue(QUEUE_CV),
            Queue(QUEUE_IO),
            Queue(QUEUE_EXPORT),
        ),
        task_routes=_TASK_ROUTES,
        # Keep the worker responsive to a restart while the broker is briefly down.
        broker_connection_retry_on_startup=True,
        result_expires=settings.export_ttl_seconds,
        # The maintenance beat. Intervals are conservative — these sweeps are cheap and
        # their job is to keep disk from growing without bound, not to be timely.
        beat_schedule={
            "tile-cache-gc": {
                "task": TASK_TILE_CACHE_GC,
                "schedule": schedule(3600.0),
            },
            "export-ttl-sweep": {
                "task": TASK_EXPORT_TTL_SWEEP,
                "schedule": schedule(3600.0),
            },
            "stale-job-reaper": {
                "task": TASK_STALE_JOB_REAPER,
                "schedule": schedule(300.0),
            },
        },
    )
    return app


#: The module-level app the worker CLI and ``@shared_task`` bind to
#: (``celery -A app.tasks.celery_app:celery_app``). Standard Celery layout.
celery_app: Final[Celery] = _build_celery_app()


def get_celery_app() -> Celery:
    """The process-wide Celery app. A function so callers do not import the module global
    directly and can be given a different app in a test harness."""
    return celery_app
