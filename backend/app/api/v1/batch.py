"""Batch — endpoints 54–57.

★ SCOPE.md §3: batch **upload/metadata/export** is built; batch **matching** is not. A batch
fans out to ``match``, which is deferred, so ``POST /batch`` returns ``501`` + ``feature:
"deferred"`` **at creation** (``BatchService.create``) rather than fanning out into jobs that
would each 501. The reads are real against the empty ``batch_jobs`` tables.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps, presenters
from app.core.pagination import SortKey, SortParams
from app.schemas.batch import BATCH_SORT_FIELDS, BatchCreate, BatchRead, BatchSummary
from app.schemas.common import Page
from app.services.batch_service import BatchService

router = APIRouter()

_DEFAULT_SORT = (SortKey("created_at", descending=True),)


@router.post(
    "/batch",
    response_model=BatchRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create a batch (matching DEFERRED)",
)
async def create_batch(
    body: BatchCreate,
    db: AsyncSession = Depends(deps.get_db),
    _: None = Depends(deps.require_writable),
) -> BatchRead:
    # ★ DEFERRED (SCOPE.md §3/§4): a batch fans out to match. 501 at creation. The multipart
    #   upload branch (§7) also 501s here; both share this refusal. Flagged.
    BatchService(db).create()
    raise AssertionError("unreachable — BatchService.create always raises FeatureDeferredError")


@router.get("/batch", response_model=Page[BatchSummary], summary="List batches")
async def list_batches(
    pagination=Depends(deps.get_pagination),
    sort: str | None = Depends(deps.get_sort),
    project_id: UUID | None = Query(None),
    status_csv: str | None = Query(None, alias="status"),
    db: AsyncSession = Depends(deps.get_db),
) -> Page[BatchSummary]:
    service = BatchService(db)
    parsed = SortParams.parse(sort, allowed=BATCH_SORT_FIELDS, default=_DEFAULT_SORT)
    rows, total = await service.list(
        pagination=pagination, sort=parsed, project_id=project_id, status_csv=status_csv
    )
    items = [presenters.to_batch_summary(b, tally=await service.counts(b.id)) for b in rows]
    return Page.of(items, total, pagination)


@router.get("/batch/{batch_id}", response_model=BatchRead, summary="Get a batch")
async def get_batch(batch_id: UUID, db: AsyncSession = Depends(deps.get_db)) -> BatchRead:
    service = BatchService(db)
    batch = await service.get(batch_id)
    return presenters.to_batch_read(batch, tally=await service.counts(batch_id))


@router.delete("/batch/{batch_id}", response_model=BatchRead, status_code=status.HTTP_202_ACCEPTED, summary="Cancel a batch")
async def cancel_batch(
    batch_id: UUID,
    db: AsyncSession = Depends(deps.get_db),
    _: None = Depends(deps.require_writable),
) -> BatchRead:
    service = BatchService(db)
    batch = await service.get(batch_id)  # 404 when absent (no batches in this build)
    # ★ BatchService exposes no cancel; the state transition is IU-19/IU-20 work. The 404
    #   precondition holds; the cooperative cancel is flagged as a service gap.
    return presenters.to_batch_read(batch, tally=await service.counts(batch_id))
