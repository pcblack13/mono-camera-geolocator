"""Albums — user-defined, **many-to-many** collections of projects.

* ``GET    /albums``                              — Page[AlbumSummary], paginated + sorted.
* ``POST   /albums``                              — 201 AlbumRead.
* ``GET    /albums/{album_id}``                   — AlbumRead.
* ``PATCH  /albums/{album_id}``                   — AlbumRead (rename / describe / tint).
* ``DELETE /albums/{album_id}``                   — 204. ★ **Does NOT delete the projects.**
* ``POST   /albums/{album_id}/projects/{project_id}``   — 204, **idempotent**.
* ``DELETE /albums/{album_id}/projects/{project_id}``   — 204, **idempotent**.
* ``GET    /albums/{album_id}/projects``          — Page[ProjectSummary].

★ **The two membership routes answer 204 whether or not they changed anything.** The
caller's request is *"let this project be in this album"* (or not be), and after the call
it is — twice-added is not an error and twice-removed is not a 404. Reporting "already
there" as a 409 would make every optimistic UI implement a retry-and-swallow, which is
the server pushing its bookkeeping onto its clients.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps, presenters
from app.core.exceptions import EmptyPatch
from app.core.pagination import SortKey, SortParams
from app.schemas.album import (
    ALBUM_SORT_FIELDS,
    AlbumCreate,
    AlbumRead,
    AlbumSummary,
    AlbumUpdate,
)
from app.schemas.common import Page
from app.schemas.project import PROJECT_SORT_FIELDS, ProjectSummary
from app.services.album_service import AlbumService
from app.services.project_service import ProjectService

router = APIRouter()

_DEFAULT_SORT = (SortKey("created_at", descending=True),)
_DEFAULT_PROJECT_SORT = (SortKey("updated_at", descending=True),)


@router.post(
    "/albums",
    response_model=AlbumRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an album",
)
async def create_album(
    body: AlbumCreate,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(deps.get_db),
    _: None = Depends(deps.require_writable),
) -> AlbumRead:
    album = await AlbumService(db).create(body)
    await db.flush()
    response.headers["Location"] = (
        f"{request.scope.get('root_path', '')}/api/v1/albums/{album.id}"
    )
    return presenters.to_album_read(album, project_count=0)


@router.get("/albums", response_model=Page[AlbumSummary], summary="List albums")
async def list_albums(
    pagination=Depends(deps.get_pagination),
    sort: str | None = Depends(deps.get_sort),
    q: str | None = Query(None, description="Free-text over name + description."),
    include_deleted: bool = Query(False),
    db: AsyncSession = Depends(deps.get_db),
) -> Page[AlbumSummary]:
    service = AlbumService(db)
    parsed = SortParams.parse(sort, allowed=ALBUM_SORT_FIELDS, default=_DEFAULT_SORT)
    rows, total = await service.list(
        pagination=pagination, sort=parsed, q=q, include_deleted=include_deleted
    )
    # ★ ONE aggregate for the whole page, not one per row.
    counts = await service.project_counts([a.id for a in rows])
    items = [
        presenters.to_album_summary(a, project_count=counts.get(a.id, 0)) for a in rows
    ]
    return Page.of(items, total, pagination)


@router.get("/albums/{album_id}", response_model=AlbumRead, summary="Get an album")
async def get_album(
    album_id: UUID,
    include_deleted: bool = Query(False),
    db: AsyncSession = Depends(deps.get_db),
) -> AlbumRead:
    service = AlbumService(db)
    album = await service.get(album_id, include_deleted=include_deleted)
    counts = await service.project_counts([album.id])
    return presenters.to_album_read(album, project_count=counts.get(album.id, 0))


@router.patch("/albums/{album_id}", response_model=AlbumRead, summary="Update an album")
async def update_album(
    album_id: UUID,
    body: AlbumUpdate,
    db: AsyncSession = Depends(deps.get_db),
    _: None = Depends(deps.require_writable),
) -> AlbumRead:
    if body.is_empty():
        raise EmptyPatch("The PATCH body is empty; send at least one field to change.")
    service = AlbumService(db)
    album = await service.update(album_id, body)
    await db.flush()
    counts = await service.project_counts([album.id])
    return presenters.to_album_read(album, project_count=counts.get(album.id, 0))


@router.delete(
    "/albums/{album_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an album (never its projects)",
)
async def delete_album(
    album_id: UUID,
    db: AsyncSession = Depends(deps.get_db),
    _: None = Depends(deps.require_writable),
) -> Response:
    # ★ An album is a view over projects. Deleting a view deletes no data: this removes
    #   one row from `albums` and nothing else. The memberships survive, so a restore
    #   brings the album back with its contents.
    await AlbumService(db).soft_delete(album_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── membership ──────────────────────────────────────────────────────────────────


@router.post(
    "/albums/{album_id}/projects/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Add a project to an album (idempotent)",
)
async def add_project_to_album(
    album_id: UUID,
    project_id: UUID,
    db: AsyncSession = Depends(deps.get_db),
    _: None = Depends(deps.require_writable),
) -> Response:
    await AlbumService(db).add_project(album_id, project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/albums/{album_id}/projects/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a project from an album (idempotent)",
)
async def remove_project_from_album(
    album_id: UUID,
    project_id: UUID,
    db: AsyncSession = Depends(deps.get_db),
    _: None = Depends(deps.require_writable),
) -> Response:
    await AlbumService(db).remove_project(album_id, project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/albums/{album_id}/projects",
    response_model=Page[ProjectSummary],
    summary="An album's projects",
)
async def list_album_projects(
    album_id: UUID,
    pagination=Depends(deps.get_pagination),
    sort: str | None = Depends(deps.get_sort),
    include_deleted: bool = Query(False),
    db: AsyncSession = Depends(deps.get_db),
) -> Page[ProjectSummary]:
    service = AlbumService(db)
    parsed = SortParams.parse(
        sort, allowed=PROJECT_SORT_FIELDS, default=_DEFAULT_PROJECT_SORT
    )
    rows, total = await service.list_projects(
        album_id, pagination=pagination, sort=parsed, include_deleted=include_deleted
    )
    project_ids = [p.id for p in rows]
    # ★ Two batched lookups for the whole page — never one per row.
    counts = await ProjectService(db).image_counts(project_ids)
    albums = await service.albums_for_projects(project_ids)
    items = [
        presenters.to_project_summary(
            p, image_count=counts.get(p.id, 0), albums=albums.get(p.id, [])
        )
        for p in rows
    ]
    return Page.of(items, total, pagination)
