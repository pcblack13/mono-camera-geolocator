"""``batch_jobs`` + ``batch_job_items`` — :class:`BatchRepository`.

★ SCOPE.md §3: batch **upload / metadata / export** is built; batch *matching* is not,
because matching is not. The table's shape does not change for that, and neither does
this module — a fan-out is a fan-out whichever task it fans out to.

★ **The counters are the interesting part.** Many workers finish many items
concurrently, and each must bump its batch's ``completed_items`` or ``failed_items``.
``completed_items = completed_items + 1`` is evaluated by the database under a row lock,
so N concurrent workers produce N increments. ``read, add one, write`` produces
somewhere between 1 and N, non-deterministically, and the batch quietly reports 7 of 10
done forever while the UI spins.

★ Status transitions for a batch go through
:class:`~app.db.repositories.jobs.JobRepository` — ``batch_jobs`` is one of the four
tables in :data:`~app.db.repositories.jobs.JOB_MODEL_BY_TYPE`, and its lifecycle is the
same state machine as everything else's. **This module owns what is batch-shaped**: the
membership, the counters, the rollup.
"""

from __future__ import annotations

import uuid
from typing import Any, Sequence

from sqlalchemy import Double, Select, case, cast, func, select, update
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import BatchNotFound
from app.core.pagination import PaginationParams, SortParams
from app.db.repositories.base import (
    BaseRepository,
    SortableColumns,
    constraint_name_of,
    csv_enum_filter,
)
from app.db.repositories.jobs import LIVE_JOB_STATUSES
from app.models.enums import JobStatus
from app.models.job import BatchJob, BatchJobItem

__all__ = ["BatchRepository"]


class BatchRepository(BaseRepository[BatchJob]):
    """Fan-outs over many images of one project, and their per-image slots."""

    model = BatchJob

    @property
    def _sortable(self) -> SortableColumns:
        """``BATCH_SORT_FIELDS`` resolved onto SQL."""
        return {
            "created_at": BatchJob.created_at,
            "finished_at": BatchJob.finished_at,
            "status": BatchJob.status,
        }

    # ── reads ────────────────────────────────────────────────────────────────

    async def list_batches(
        self,
        *,
        pagination: PaginationParams,
        sort: SortParams,
        project_id: uuid.UUID | None = None,
        status_csv: str | None = None,
    ) -> tuple[Sequence[BatchJob], int]:
        """``GET /batch`` (55)."""
        stmt: Select[Any] = select(BatchJob)
        if project_id is not None:
            stmt = stmt.where(BatchJob.project_id == project_id)
        statuses = csv_enum_filter(status_csv, [m.value for m in JobStatus])
        if statuses:
            stmt = stmt.where(BatchJob.status.in_(statuses))
        return await self.page(stmt, pagination, sort, self._sortable)

    async def list_items(
        self, batch_job_id: uuid.UUID, *, status_csv: str | None = None
    ) -> Sequence[BatchJobItem]:
        """A batch's slots, in submission order.

        Unpaginated: a batch is capped at ``MAX_BATCH_ITEMS`` (100), and ``BatchRead``
        renders the whole list. Ordered by ``ordinal``, which
        ``uq_batch_job_items_batch_ordinal`` makes a total order.
        """
        stmt: Select[Any] = select(BatchJobItem).where(
            BatchJobItem.batch_job_id == batch_job_id
        )
        statuses = csv_enum_filter(status_csv, [m.value for m in JobStatus])
        if statuses:
            stmt = stmt.where(BatchJobItem.status.in_(statuses))
        return await self._scalars(stmt.order_by(BatchJobItem.ordinal.asc()))

    async def get_item(self, item_id: uuid.UUID) -> BatchJobItem | None:
        """One slot by id."""
        return await self._scalar_one_or_none(
            select(BatchJobItem).where(BatchJobItem.id == item_id)
        )

    async def counts_by_status(self, batch_job_id: uuid.UUID) -> dict[str, int]:
        """``{job_status: count}`` over a batch's items — ``BatchCounts``.

        ★ Counted from the items rather than read off the parent's ``completed_items`` /
        ``failed_items``, and the difference is deliberate: this is the **audit**. The
        parent's counters are maintained incrementally by racing workers, and a rollup
        that read them back would be unable to notice if one increment were ever lost.
        ``ix_batch_job_items_batch_status`` makes the group-by an index-only scan.
        """
        stmt = (
            select(BatchJobItem.status, func.count())
            .where(BatchJobItem.batch_job_id == batch_job_id)
            .group_by(BatchJobItem.status)
        )
        return {
            str(getattr(status, "value", status)): int(count)
            for status, count in (await self._execute(stmt)).all()
        }

    # ── writes ───────────────────────────────────────────────────────────────

    async def add_items(self, items: Sequence[BatchJobItem]) -> Sequence[BatchJobItem]:
        """Insert a batch's slots and set ``total_items`` to match.

        Raises:
            ValueError: ``uq_batch_job_items_batch_image`` was violated — the same image
                appears twice in one batch. ★ **This is the double-click-submit bug
                caught in the database**, which is where it has to be caught: two
                requests racing cannot see each other's uncommitted rows, so no
                application-level check can prevent it. The constraint can.

        Returns:
            The staged items, flushed.
        """
        if not items:
            return []
        batch_ids = {i.batch_job_id for i in items}
        if len(batch_ids) != 1:
            raise ValueError("add_items takes the items of exactly one batch.")

        self.add_all(items)
        try:
            await self.flush()
        except IntegrityError as exc:
            name = constraint_name_of(exc)
            if name == "uq_batch_job_items_batch_image":
                raise ValueError(
                    "The same image appears more than once in this batch "
                    "(uq_batch_job_items_batch_image). A batch runs each image once."
                ) from exc
            if name == "uq_batch_job_items_batch_ordinal":
                raise ValueError(
                    "Two items share an ordinal (uq_batch_job_items_batch_ordinal); "
                    "ordinals must be distinct within a batch."
                ) from exc
            raise

        await self._execute(
            update(BatchJob)
            .where(BatchJob.id == batch_ids.pop())
            .values(total_items=len(items))
        )
        return items

    async def set_item_status(
        self,
        item_id: uuid.UUID,
        status: JobStatus,
        *,
        error_message: str | None = None,
        match_job_id: uuid.UUID | None = None,
    ) -> bool:
        """Move one slot's status. Guarded against re-entering a terminal state.

        Args:
            item_id: The slot.
            status: Its new status.
            error_message: Required in spirit for ``failed``; ``batch_job_items`` carries
                no CHECK for it, unlike the job tables, so this layer does not pretend
                there is one.
            match_job_id: The ★ other half of the deliberate ``match_jobs`` ↔
                ``batch_job_items`` FK cycle. Both sides are ``ON DELETE SET NULL``, so
                the cycle can never cascade; migration ``0005`` creates the tables
                without the mutual FKs and adds them at the end.

        Returns:
            True when a row moved.
        """
        values: dict[str, Any] = {"status": status}
        if error_message is not None:
            values["error_message"] = error_message
        if match_job_id is not None:
            values["match_job_id"] = match_job_id

        stmt = (
            update(BatchJobItem)
            .where(
                BatchJobItem.id == item_id,
                BatchJobItem.status.in_(sorted(LIVE_JOB_STATUSES)),
            )
            .values(**values)
            .returning(BatchJobItem.id)
        )
        return (await self._execute(stmt)).scalar_one_or_none() is not None

    async def record_item_finished(
        self, batch_job_id: uuid.UUID, *, failed: bool
    ) -> bool:
        """★ Atomically bump a batch's counters and recompute its progress.

        Called once per finished item, by whichever worker finished it. **One statement,
        every arithmetic step evaluated by the database**, so N concurrent workers
        produce exactly N increments.

        ★ The ``WHERE completed_items + failed_items < total_items`` guard is
        ``ck_batch_jobs_counts`` restated as a predicate rather than duplicated as a
        check. Under the constraint alone, a double-report — a task retried after its
        result was already recorded — would abort the transaction and take the *item's*
        successful work down with it. As a ``WHERE``, the double-report matches no row
        and no-ops, which is what an idempotent report should do.

        Args:
            batch_job_id: The batch.
            failed: Which counter to bump.

        Returns:
            True when a counter moved. False ⇒ the batch was already fully accounted
            for, which is not an error.
        """
        done_after = BatchJob.completed_items + BatchJob.failed_items + 1
        progress = case(
            (BatchJob.total_items <= 0, 0.0),
            else_=cast(done_after, Double) / BatchJob.total_items,
        )
        values: dict[str, Any] = {"progress": progress}
        if failed:
            values["failed_items"] = BatchJob.failed_items + 1
        else:
            values["completed_items"] = BatchJob.completed_items + 1

        stmt = (
            update(BatchJob)
            .where(
                BatchJob.id == batch_job_id,
                BatchJob.completed_items + BatchJob.failed_items < BatchJob.total_items,
            )
            .values(**values)
            .returning(BatchJob.id)
        )
        return (await self._execute(stmt)).scalar_one_or_none() is not None

    async def is_complete(self, batch_job_id: uuid.UUID) -> bool:
        """Whether every item is accounted for — the aggregate task's exit test.

        Read from the counters, which is the cheap form. The authoritative form is
        :meth:`counts_by_status`; they agree unless an increment was lost, and
        ``batch_aggregate_task`` should prefer the audit before declaring a batch done.

        Raises:
            BatchNotFound: no such batch.
        """
        row = (
            await self._execute(
                select(
                    BatchJob.completed_items + BatchJob.failed_items, BatchJob.total_items
                ).where(BatchJob.id == batch_job_id)
            )
        ).one_or_none()
        if row is None:
            raise BatchNotFound(f"No batch {batch_job_id}.")
        done, total = int(row[0]), int(row[1])
        return total > 0 and done >= total

    async def cancel_pending_items(self, batch_job_id: uuid.UUID) -> int:
        """Cancel a batch's not-yet-started slots.

        ★ Only ``pending`` and ``queued`` items. A ``running`` item is a worker holding
        real work, and cancelling it *here* would leave the batch claiming a state the
        worker will contradict two seconds later; the worker's own cooperative cancel
        poll (``cancel_requested`` on its job) is what stops it.

        Returns:
            How many slots were cancelled.
        """
        stmt = (
            update(BatchJobItem)
            .where(
                BatchJobItem.batch_job_id == batch_job_id,
                BatchJobItem.status.in_([JobStatus.PENDING.value, JobStatus.QUEUED.value]),
            )
            .values(status=JobStatus.CANCELLED)
        )
        return int((await self._execute(stmt)).rowcount or 0)
