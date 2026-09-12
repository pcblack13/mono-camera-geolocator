"""``batch_service`` — batch reads are real; batch *matching* is DEFERRED.

★ SCOPE.md §3: *"Batch processing of multiple uploaded images — batch upload/metadata/export
only; no batch matching."* A ``BatchCreate`` fans out to the automatic ``match`` pipeline,
which is deferred (SCOPE.md §1) — so :meth:`create` raises
:class:`~app.core.exceptions.FeatureDeferredError` → ``501`` + ``feature: "deferred"`` **at
creation**, rather than enqueueing a batch of child jobs that would never complete.

The reads (a batch's status, its item roll-up) are real against the empty ``batch_jobs`` /
``batch_job_items`` tables — the schema and the seam are exact, so re-enabling batch
matching costs no caller a change (SCOPE.md §7).
"""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BatchNotFound, FeatureDeferredError
from app.core.pagination import PaginationParams, SortParams
from app.db.repositories.batches import BatchRepository
from app.models.job import BatchJob

__all__ = ["BatchService"]

_COMPONENT = "ai_engine.pipeline.orchestrator"
_DEFERRED_MESSAGE = (
    "Batch matching is not enabled in this build — batch upload, metadata and export are "
    "supported, but automatic matching (which a batch fans out to) is deferred. Place GCPs "
    "manually per image."
)


class BatchService:
    """Batch jobs — deferred creation (match fan-out), real reads."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._batches = BatchRepository(session)

    def create(self, *args: object, **kwargs: object) -> None:
        """``POST /batch`` (54) — **DEFERRED** (501): a batch fans out to match."""
        raise FeatureDeferredError(_DEFERRED_MESSAGE, component=_COMPONENT)

    async def get(self, batch_id: uuid.UUID) -> BatchJob:
        """One batch, or ``BatchNotFound``."""
        batch = await self._batches.get(batch_id)
        if batch is None:
            raise BatchNotFound(f"No batch {batch_id}.")
        return batch

    async def list(
        self,
        *,
        pagination: PaginationParams,
        sort: SortParams,
        project_id: uuid.UUID | None = None,
        status_csv: str | None = None,
    ) -> tuple[Sequence[BatchJob], int]:
        """``GET /batch`` (55) — real; empty in this build."""
        return await self._batches.list_batches(
            pagination=pagination,
            sort=sort,
            project_id=project_id,
            status_csv=status_csv,
        )

    async def counts(self, batch_id: uuid.UUID) -> dict[str, int]:
        """Child-job status tallies for the batch roll-up."""
        return await self._batches.counts_by_status(batch_id)
