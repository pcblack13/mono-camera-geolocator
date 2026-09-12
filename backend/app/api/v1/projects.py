"""Projects — endpoints 4–8."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps, presenters
from app.api.etag import etag_for, if_none_match_hit
from app.core.exceptions import BboxCrossesAntimeridian, EmptyPatch, InvalidBBox
from app.core.pagination import SortKey, SortParams
from app.core.security import Principal
from app.schemas.common import BBox, Page
from app.schemas.project import (
    PROJECT_SORT_FIELDS,
    ProjectCreate,
    ProjectExportRead,
    ProjectRead,
    ProjectSummary,
    ProjectUpdate,
)
from app.services import project_export_service
from app.services.album_service import AlbumService
from app.services.project_service import ProjectService

router = APIRouter()

_DEFAULT_SORT = (SortKey("created_at", descending=True),)


def parse_bbox(raw: str | None) -> tuple[float, float, float, float] | None:
    """``"minlon,minlat,maxlon,maxlat"`` -> a validated tuple, or None.

    ★ **Public and shared.** ``GET /gcps`` takes the same ``?bbox=`` and must map the
    same two failures to the same two codes — ``422 INVALID_BBOX`` and
    ``422 BBOX_CROSSES_ANTIMERIDIAN``. A second copy is a second chance for one endpoint
    to silently accept a box the other rejects, and an antimeridian box that is *not*
    refused returns the entire world minus the requested strip: plausible-looking, and
    exactly inverted.
    """
    if raw is None:
        return None
    try:
        b = BBox.from_csv(raw)
    except ValueError as exc:
        if "antimeridian" in str(exc).lower():
            raise BboxCrossesAntimeridian(str(exc)) from exc
        raise InvalidBBox(str(exc)) from exc
    return (b.min_lon, b.min_lat, b.max_lon, b.max_lat)


@router.post("/projects", response_model=ProjectRead, status_code=status.HTTP_201_CREATED, summary="Create a project")
async def create_project(
    body: ProjectCreate,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(deps.get_db),
    principal: Principal = Depends(deps.get_principal),
    _: None = Depends(deps.require_writable),
) -> ProjectRead:
    service = ProjectService(db)
    project = await service.create(body, owner_id=None if principal.is_anonymous else principal.subject)
    await db.flush()
    response.headers["Location"] = f"{request.scope.get('root_path', '')}/api/v1/projects/{project.id}"
    return presenters.to_project_read(project)


@router.post(
    "/projects/{project_id}/export-folder",
    response_model=ProjectExportRead,
    summary="Write a self-contained folder of this project (photos, GCPs, DEM, outputs)",
)
async def export_project_folder(
    project_id: UUID,
    db: AsyncSession = Depends(deps.get_db),
    settings=Depends(deps.get_settings),
    _: None = Depends(deps.require_writable),
) -> ProjectExportRead:
    """★ Gather everything a project owns into one browsable
    ``<LandExplorer>/projects/<name>-<ts>/`` folder — the answer to "there is no
    project folder" (2026-09-03). The DB read + file copy is synchronous, so it
    runs in a threadpool to keep the event loop free."""
    from fastapi import HTTPException
    from fastapi.concurrency import run_in_threadpool

    # 404s honestly if the project is gone; the service raises the same words.
    await ProjectService(db).get(project_id)
    try:
        summary = await run_in_threadpool(
            project_export_service.export_project, str(project_id), settings
        )
    except project_export_service.ProjectExportError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ProjectExportRead(**summary)


@router.get("/projects", response_model=Page[ProjectSummary], summary="List projects")
async def list_projects(
    pagination=Depends(deps.get_pagination),
    sort: str | None = Depends(deps.get_sort),
    q: str | None = Query(None),
    tags: str | None = Query(None, description="CSV; ANDed."),
    bbox: str | None = Query(None),
    album_id: UUID | None = Query(None, description="Only projects filed in this album."),
    include_deleted: bool = Query(False),
    db: AsyncSession = Depends(deps.get_db),
) -> Page[ProjectSummary]:
    service = ProjectService(db)
    parsed = SortParams.parse(sort, allowed=PROJECT_SORT_FIELDS, default=_DEFAULT_SORT)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    rows, total = await service.list(
        pagination=pagination,
        sort=parsed,
        q=q,
        tags=tag_list,
        bbox=parse_bbox(bbox),
        album_id=album_id,
        include_deleted=include_deleted,
    )
    project_ids = [p.id for p in rows]
    counts = await service.image_counts(project_ids)
    # ★ The album chips for the WHOLE PAGE in one query. `project.albums` is
    #   `lazy="raise"` — a many-to-many walked per row is a page-sized round-trip storm.
    albums = await AlbumService(db).albums_for_projects(project_ids)
    items = [
        presenters.to_project_summary(
            p, image_count=counts.get(p.id, 0), albums=albums.get(p.id, [])
        )
        for p in rows
    ]
    return Page.of(items, total, pagination)


@router.get("/projects/{project_id}", response_model=ProjectRead, summary="Get a project")
async def get_project(
    request: Request,
    response: Response,
    project=Depends(deps.get_project),
) -> ProjectRead | Response:
    tag = etag_for(project.current_revision_seq, project.updated_at)
    if if_none_match_hit(request, tag):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": tag})
    response.headers["ETag"] = tag
    return presenters.to_project_read(project)


@router.patch("/projects/{project_id}", response_model=ProjectRead, summary="Update a project")
async def update_project(
    project_id: UUID,
    body: ProjectUpdate,
    response: Response,
    db: AsyncSession = Depends(deps.get_db),
    _: None = Depends(deps.require_writable),
) -> ProjectRead:
    if body.is_empty():
        raise EmptyPatch("The PATCH body is empty; send at least one field to change.")
    service = ProjectService(db)
    project = await service.update(project_id, body)
    await db.flush()
    response.headers["ETag"] = etag_for(project.current_revision_seq, project.updated_at)
    return presenters.to_project_read(project)


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a project")
async def delete_project(
    project_id: UUID,
    request: Request,
    hard: bool = Query(False),
    db: AsyncSession = Depends(deps.get_db),
    _: None = Depends(deps.require_writable),
) -> Response:
    if hard:
        deps.require_confirm_delete(request)
    service = ProjectService(db)
    # ★ The service exposes soft delete only; a hard purge (prefix-delete of stored bytes) is
    #   IU-19/IU-20 work not present in this build, so a confirmed hard delete degrades to a
    #   soft delete here rather than fabricating a purge. Flagged in IU-21's report.
    await service.soft_delete(project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
