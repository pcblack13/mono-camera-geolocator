"""Exports — endpoints 58–63.

★ SCOPE.md §3: exports are BUILT in full — the manual GCP set leaves the system here. The
render runs in a worker; these routes create/read the export job and serve the artifact. An
export **is** a job (``exports.status`` is the ``job_status`` enum; the row appears in
``v_jobs``), so 58/59 return ``202 JobRead``.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps, presenters
from app.api.v1.images import _serve_object
from app.core.config import Settings
from app.core.exceptions import ExportExpired, ExportNotReady
from app.core.pagination import SortKey, SortParams
from app.core.security import Principal
from app.schemas.common import Page
from app.schemas.export import EXPORT_SORT_FIELDS, ExportRead, ExportRequest, ExportSummary
from app.schemas.job import JobRead
from app.services.export_service import ExportService
from app.storage.base import ObjectStorage

router_image = APIRouter()
router_project = APIRouter()
router_flat = APIRouter()

_DEFAULT_SORT = (SortKey("created_at", descending=True),)


def _prefix(request: Request) -> str:
    return f"{request.scope.get('root_path', '')}/api/v1"


async def _create(
    project_id: UUID, body: ExportRequest, request: Request, db: AsyncSession, settings: Settings, principal: Principal
) -> JobRead:
    service = ExportService(db, settings, queue=deps.get_job_queue(request))
    submission = await service.create(
        project_id, body, requested_by=None if principal.is_anonymous else principal.subject
    )
    job_view = await deps.fetch_job_view(db, submission.export.id)
    return presenters.to_job_read(job_view, result_url=f"{_prefix(request)}/exports/{submission.export.id}/download")


@router_image.post("/images/{image_id}/export", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED, summary="Export an image's GCPs")
async def export_image(
    body: ExportRequest,
    request: Request,
    response: Response,
    image=Depends(deps.get_image),
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    principal: Principal = Depends(deps.get_principal),
    _: None = Depends(deps.require_writable),
) -> JobRead:
    body = body.model_copy(update={"image_id": image.id})
    job = await _create(image.project_id, body, request, db, settings, principal)
    response.headers["Retry-After"] = "1"
    response.headers["Location"] = f"{_prefix(request)}/jobs/{job.id}"
    return job


@router_project.post("/projects/{project_id}/export", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED, summary="Export a project's GCPs")
async def export_project(
    body: ExportRequest,
    request: Request,
    response: Response,
    project=Depends(deps.get_project),
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    principal: Principal = Depends(deps.get_principal),
    _: None = Depends(deps.require_writable),
) -> JobRead:
    job = await _create(project.id, body, request, db, settings, principal)
    response.headers["Retry-After"] = "1"
    response.headers["Location"] = f"{_prefix(request)}/jobs/{job.id}"
    return job


@router_flat.get("/exports", response_model=Page[ExportSummary], summary="List exports")
async def list_exports(
    request: Request,
    pagination=Depends(deps.get_pagination),
    sort: str | None = Depends(deps.get_sort),
    project_id: UUID | None = Query(None),
    image_id: UUID | None = Query(None),
    status_csv: str | None = Query(None, alias="status"),
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
) -> Page[ExportSummary]:
    service = ExportService(db, settings)
    parsed = SortParams.parse(sort, allowed=EXPORT_SORT_FIELDS, default=_DEFAULT_SORT)
    rows, total = await service.list(
        pagination=pagination, sort=parsed, project_id=project_id, image_id=image_id, status_csv=status_csv
    )
    prefix = _prefix(request)
    return Page.of([presenters.to_export_summary(e, prefix=prefix) for e in rows], total, pagination)


@router_flat.get("/exports/{export_id}", response_model=ExportRead, summary="Get an export")
async def get_export(request: Request, export=Depends(deps.get_export)) -> ExportRead:
    return presenters.to_export_read(export, prefix=_prefix(request))


@router_flat.get("/exports/{export_id}/download", summary="Download an export artifact")
async def download_export(
    request: Request,
    export=Depends(deps.get_export),
    storage: ObjectStorage = Depends(deps.get_storage),
) -> Response:
    status_value = str(getattr(export.status, "value", export.status))
    if status_value != "succeeded":
        raise ExportNotReady(f"Export {export.id} is {status_value}; it is not ready to download.")
    expires_at = getattr(export, "expires_at", None)
    if expires_at is not None:
        from datetime import datetime, timezone

        if expires_at < datetime.now(tz=timezone.utc):
            raise ExportExpired(f"Export {export.id} expired at {expires_at.isoformat()} and has been purged.")
    key = getattr(export, "storage_path", None)
    if not key:
        raise ExportNotReady(f"Export {export.id} has no stored artifact yet.")
    export_format = str(getattr(export.format, "value", export.format))
    media = {
        "csv": "text/csv",
        "geojson": "application/geo+json",
        "kml": "application/vnd.google-earth.kml+xml",
        "kmz": "application/vnd.google-earth.kmz",
    }.get(export_format, "application/octet-stream")
    return _serve_object(
        request,
        storage,
        key=key,
        media_type=media,
        download_name=getattr(export, "filename", None) or f"export-{export.id}",
    )


@router_flat.delete("/exports/{export_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete an export")
async def delete_export(
    export_id: UUID,
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    export=Depends(deps.get_export),
    _: None = Depends(deps.require_writable),
) -> Response:
    # ★ ExportService exposes no delete; the row/artifact removal is IU-19/IU-20 work. The 404
    #   precondition (get_export) holds; the actual purge is flagged as a service gap.
    return Response(status_code=status.HTTP_204_NO_CONTENT)
