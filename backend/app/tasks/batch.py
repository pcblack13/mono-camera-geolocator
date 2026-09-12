"""``batch_fanout_task`` / ``batch_aggregate_task`` — batch orchestration (§5.5 ``batch``).

★ SCOPE.md §3: *"Batch processing of multiple uploaded images — batch upload/metadata/export
only; no batch matching."* A ``BatchCreate`` in the full design fans out to the automatic
``match`` pipeline (one child per image), which is deferred — so ``batch_service.create``
returns ``501 feature: "deferred"`` and **no batch job is enqueued in this build**. These
tasks therefore keep their file, names and stage list (``pending → fanning_out →
waiting_children → aggregating → done``) but are dormant.

The orchestration skeleton is real so that re-enabling is a zero-caller change (SCOPE.md §7):

* :func:`batch_fanout_task` reads the batch's slots and — where a child dispatch is
  attached — submits one child job per pending item, then the batch waits for them. In this
  build there is no legal child to create (the only child type is a deferred ``match``), so
  the fan-out is empty and the batch proceeds straight to aggregation. It does **not**
  fabricate child jobs.
* :func:`batch_aggregate_task` is the terminal roll-up (the tail of the future two-phase
  design): it audits the item counts and completes the batch. In this build the fan-out
  task performs the whole batch in one pass, so this task is registered but not enqueued.

★ A batch **job** succeeds as an *orchestration* even when some of its items failed — a
partial batch is reported through the per-item counters (``completed_items`` /
``failed_items``), never by failing the parent, which would tell a surveyor the whole run
broke when most of it did not.
"""

from __future__ import annotations

import uuid
from typing import Any

from celery import shared_task

from app.core.constants import JobStage
from app.core.logging import get_logger
from app.db.session import get_sessionmaker
from app.models.enums import JobType
from app.tasks.base import BaseJobTask, job_lifecycle, run_async
from app.tasks.celery_app import TASK_BATCH_AGGREGATE, TASK_BATCH_FANOUT

__all__ = ["batch_aggregate_task", "batch_fanout_task"]

log = get_logger(__name__)


@shared_task(bind=True, base=BaseJobTask, name=TASK_BATCH_FANOUT)
def batch_fanout_task(self: Any, job_id: str, **payload: Any) -> None:
    """Fan a batch out to its child jobs, then aggregate. See module docstring.

    Args:
        job_id: The ``batch_jobs`` row id (the batch IS the job).
        payload: Reserved for the future ``BatchJobSpec`` (child job type, options).
    """
    with job_lifecycle(self, JobType.BATCH, job_id) as ctx:
        batch_id = uuid.UUID(str(job_id))

        ctx.progress.set_stage(JobStage.FANNING_OUT)
        pending = _dispatch_children(batch_id)
        log.info("batch.fanned_out", batch_id=str(batch_id), children_dispatched=pending)

        # No asynchronous children exist in this build, so there is nothing to wait for;
        # the stage is still reported for a faithful timeline.
        ctx.progress.set_stage(JobStage.WAITING_CHILDREN)

        ctx.progress.set_stage(JobStage.AGGREGATING)
        counts = _audit_counts(batch_id)
        log.info("batch.aggregated", batch_id=str(batch_id), counts=counts)
        # Clean exit → the lifecycle marks the batch job succeeded (→ done).


@shared_task(bind=True, base=BaseJobTask, name=TASK_BATCH_AGGREGATE)
def batch_aggregate_task(self: Any, job_id: str, **payload: Any) -> None:
    """Roll up a batch once its children have finished. See module docstring.

    Registered for the future two-phase design (children enqueue this on completion); in
    this build :func:`batch_fanout_task` performs aggregation inline, so this is not
    enqueued.
    """
    with job_lifecycle(self, JobType.BATCH, job_id) as ctx:
        batch_id = uuid.UUID(str(job_id))
        ctx.progress.set_stage(JobStage.AGGREGATING)
        counts = _audit_counts(batch_id)
        log.info("batch.aggregated", batch_id=str(batch_id), counts=counts)


# ── internals ─────────────────────────────────────────────────────────────────


def _dispatch_children(batch_id: uuid.UUID) -> int:
    """Submit one child job per pending item — the re-enable seam.

    Returns the number of children dispatched. In this build the only child type is a
    deferred ``match`` job, so nothing is dispatched (dispatching deferred children would
    create rows that can only fail — a fabrication this refuses). When batch matching is
    enabled, this is where each pending ``BatchJobItem`` becomes a child ``JobSpec``
    submitted through the injected ``CeleryJobQueue`` and the item is moved to ``queued``.
    """
    from app.db.repositories.batches import BatchRepository

    async def _load() -> int:
        factory = get_sessionmaker()
        async with factory() as session:
            items = await BatchRepository(session).list_items(batch_id, status_csv="pending")
            # child dispatch attaches here (deferred — see docstring)
            return len(items)

    return run_async(_load)


def _audit_counts(batch_id: uuid.UUID) -> dict[str, int]:
    """The authoritative per-status item tally (the audit, not the parent's counters)."""
    from app.db.repositories.batches import BatchRepository

    async def _load() -> dict[str, int]:
        factory = get_sessionmaker()
        async with factory() as session:
            return await BatchRepository(session).counts_by_status(batch_id)

    return run_async(_load)
