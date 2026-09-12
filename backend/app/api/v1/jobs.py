"""Jobs — endpoints 31–33.

There is no ``JobService`` (§ IU-19 provides none); the ``v_jobs`` reads and the cooperative
cancel state machine live in ``deps`` over ``JobRepository`` — the exempt layer. ``GET
/jobs/{id}``'s long-poll ``?wait=`` **falls back transparently** (L11): with no Redis pubsub the
current state returns immediately, never a hang.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps, presenters
from app.api.etag import etag_for, if_none_match_hit
from app.core.pagination import SortKey, SortParams
from app.schemas.common import Page
from app.schemas.job import JOB_SORT_FIELDS, JobRead, JobSummary

router = APIRouter()

_DEFAULT_SORT = (SortKey("created_at", descending=True),)

#: ``Retry-After`` by live status; **absent when terminal — its absence IS "stop polling"**.
_RETRY_AFTER = {"running": "1", "pending": "2", "queued": "2", "retrying": "5"}


def _job_etag(job) -> str:
    return etag_for(job.status.value, job.updated_at)


@router.get("/jobs", response_model=Page[JobSummary], summary="List jobs")
async def list_jobs(
    pagination=Depends(deps.get_pagination),
    sort: str | None = Depends(deps.get_sort),
    type_csv: str | None = Query(None, alias="type", description="CSV of JobType."),
    status_csv: str | None = Query(None, alias="status", description="CSV of JobStatus."),
    image_id: UUID | None = Query(None),
    project_id: UUID | None = Query(None),
    batch_id: UUID | None = Query(None),
    db: AsyncSession = Depends(deps.get_db),
) -> Page[JobSummary]:
    parsed = SortParams.parse(sort, allowed=JOB_SORT_FIELDS, default=_DEFAULT_SORT)
    rows, total = await deps.list_job_views(
        db,
        pagination=pagination,
        sort=parsed,
        type_csv=type_csv,
        status_csv=status_csv,
        image_id=image_id,
        project_id=project_id,
        batch_id=batch_id,
    )
    return Page.of([presenters.to_job_summary(j) for j in rows], total, pagination)


@router.get("/jobs/{job_id}", response_model=JobRead, summary="Get a job")
async def get_job(
    request: Request,
    response: Response,
    wait: int = Query(0, ge=0, le=30),
    job=Depends(deps.get_job),
):
    # wait>0: long-poll falls back transparently (L11) — no pubsub here, return current state.
    tag = _job_etag(job)
    if if_none_match_hit(request, tag):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": tag})
    response.headers["ETag"] = tag
    retry = _RETRY_AFTER.get(job.status.value)
    if retry is not None:
        response.headers["Retry-After"] = retry
    # ★ Carry the download link on a FINISHED export job. The export POST sets `result_url`,
    #   but the client polls THIS endpoint to learn the job succeeded — and without the link
    #   here, `result_url` is null on every poll, so the export dialog's Download button never
    #   appears even though the file is ready. The export IS the job, so its id addresses the
    #   artifact directly.
    result_url: str | None = None
    job_type = getattr(job.type, "value", job.type)
    if job_type == "export" and job.status.value == "succeeded":
        result_url = f"{request.scope.get('root_path', '')}/api/v1/exports/{job.id}/download"
    return presenters.to_job_read(job, result_url=result_url)


@router.delete("/jobs/{job_id}", response_model=JobRead, summary="Cancel a job")
async def cancel_job(
    response: Response,
    job=Depends(deps.get_job),
    db: AsyncSession = Depends(deps.get_db),
    _: None = Depends(deps.require_writable),
) -> JobRead:
    refreshed, status_code = await deps.cancel_job(db, job)
    await db.flush()
    response.status_code = status_code
    return presenters.to_job_read(refreshed)
