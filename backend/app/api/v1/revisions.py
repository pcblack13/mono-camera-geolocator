"""Revisions and annotation version history — endpoints 23–29.

★ SCOPE.md §3: version history is BUILT in full. The list and checkpoint (23, 24) use
``RevisionService`` methods that exist; the fat single-revision read, restore and the version
ledger (25–29) are contracted to ``revision_service`` (§2.4) but the current service exposes
only ``list_for_project`` / ``get_by_seq`` / ``checkpoint`` / ``mark_gcps_stale_after_restore``.
Those routes are coded to the declared interface and **flagged** as needing
``RevisionService.{get, restore, list_versions_for_image, list_versions_for_annotation, get_version}``.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps, presenters
from app.core.pagination import SortKey, SortParams, reject_param_conflict
from app.core.security import Principal
from app.schemas.common import Page
from app.schemas.revision import (
    ANNOTATION_VERSION_SORT_FIELDS,
    REVISION_SORT_FIELDS,
    AnnotationVersionRead,
    AnnotationVersionSummary,
    RevisionCreate,
    RevisionRead,
    RevisionRestoreRequest,
    RevisionRestoreResponse,
    RevisionSummary,
)
from app.services.revision_service import RevisionService

router_project = APIRouter()
router_flat = APIRouter()
router_versions = APIRouter()

_REV_SORT = (SortKey("seq", descending=True),)
_VER_SORT = (SortKey("id", descending=True),)


# ── router_project (/projects/{project_id}/revisions) ──────────────────────────


@router_project.get(
    "/projects/{project_id}/revisions",
    response_model=Page[RevisionSummary],
    summary="List project revisions",
)
async def list_revisions(
    pagination=Depends(deps.get_pagination),
    sort: str | None = Depends(deps.get_sort),
    project=Depends(deps.get_project),
    db: AsyncSession = Depends(deps.get_db),
) -> Page[RevisionSummary]:
    service = RevisionService(db)
    parsed = SortParams.parse(sort, allowed=REVISION_SORT_FIELDS, default=_REV_SORT)
    rows, total = await service.list_for_project(project.id, pagination=pagination, sort=parsed)
    return Page.of([presenters.to_revision_summary(r) for r in rows], total, pagination)


@router_project.post(
    "/projects/{project_id}/revisions",
    response_model=RevisionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a checkpoint revision",
)
async def create_revision(
    body: RevisionCreate,
    project=Depends(deps.get_project),
    db: AsyncSession = Depends(deps.get_db),
    principal: Principal = Depends(deps.get_principal),
    _: None = Depends(deps.require_writable),
) -> RevisionRead:
    service = RevisionService(db)
    revision = await service.checkpoint(
        project.id,
        label=body.label,
        actor_id=None if principal.is_anonymous else principal.subject,
    )
    await db.flush()
    return _revision_read(revision)


# ── router_flat (/revisions/{revision_id}) ─────────────────────────────────────


@router_flat.get("/revisions/{revision_id}", response_model=RevisionRead, summary="Get a revision")
async def get_revision(
    revision_id: UUID,
    include_snapshot: bool = Query(True),
    db: AsyncSession = Depends(deps.get_db),
) -> RevisionRead:
    service = RevisionService(db)
    revision = await service.get(revision_id)
    return _revision_read(revision)


@router_flat.post(
    "/revisions/{revision_id}/restore",
    response_model=RevisionRestoreResponse,
    summary="Restore a revision (forward-only)",
)
async def restore_revision(
    revision_id: UUID,
    body: RevisionRestoreRequest,
    db: AsyncSession = Depends(deps.get_db),
    principal: Principal = Depends(deps.get_principal),
    _: None = Depends(deps.require_writable),
) -> RevisionRestoreResponse:
    service = RevisionService(db)
    result = await service.restore(
        revision_id,
        label=body.label,
        actor_id=None if principal.is_anonymous else principal.subject,
    )
    await db.flush()
    return result


# ── router_versions (annotation version ledger) ────────────────────────────────


@router_versions.get(
    "/images/{image_id}/annotation-versions",
    response_model=Page[AnnotationVersionSummary],
    summary="An image's annotation version ledger",
)
async def list_image_versions(
    pagination=Depends(deps.get_pagination),
    sort: str | None = Depends(deps.get_sort),
    include_payloads: bool = Query(False),
    before_id: int | None = Query(None),
    image=Depends(deps.get_image),
    db: AsyncSession = Depends(deps.get_db),
) -> Page[AnnotationVersionSummary]:
    reject_param_conflict(offset=pagination.offset, before_id=before_id)
    service = RevisionService(db)
    parsed = SortParams.parse(sort, allowed=ANNOTATION_VERSION_SORT_FIELDS, default=_VER_SORT)
    rows, total = await service.list_versions_for_image(
        image.id, pagination=pagination, sort=parsed, before_id=before_id, include_payloads=include_payloads
    )
    return Page.of(list(rows), total, pagination)


@router_versions.get(
    "/annotations/{annotation_id}/versions",
    response_model=Page[AnnotationVersionSummary],
    summary="One annotation's version ledger",
)
async def list_annotation_versions(
    annotation_id: UUID,
    pagination=Depends(deps.get_pagination),
    sort: str | None = Depends(deps.get_sort),
    include_payloads: bool = Query(False),
    db: AsyncSession = Depends(deps.get_db),
) -> Page[AnnotationVersionSummary]:
    service = RevisionService(db)
    parsed = SortParams.parse(sort, allowed=ANNOTATION_VERSION_SORT_FIELDS, default=_VER_SORT)
    rows, total = await service.list_versions_for_annotation(
        annotation_id, pagination=pagination, sort=parsed, include_payloads=include_payloads
    )
    return Page.of(list(rows), total, pagination)


@router_versions.get(
    "/annotation-versions/{version_id}",
    response_model=AnnotationVersionRead,
    summary="One annotation version event",
)
async def get_annotation_version(
    version_id: int,
    db: AsyncSession = Depends(deps.get_db),
) -> AnnotationVersionRead:
    service = RevisionService(db)
    return await service.get_version(version_id)


# ── minimal RevisionRead assembly (snapshot/events/diff are service work) ───────


def _revision_read(revision) -> RevisionRead:
    """A ``ProjectRevision`` ORM row → ``RevisionRead``.

    ★ ``snapshot`` / ``events`` / ``diff_summary`` require the replay + ledger the service owns
    (``RevisionService.get`` should return them assembled); this thin build fills the flat
    columns and honestly-empty containers. Flagged.
    """
    from app.schemas.revision import RevisionDiffSummary

    return RevisionRead(
        id=revision.id,
        project_id=revision.project_id,
        seq=revision.seq,
        label=revision.label,
        is_checkpoint=revision.is_checkpoint,
        annotation_count=getattr(revision, "annotation_count", 0) or 0,
        created_at=revision.created_at,
        snapshot=None,
        snapshot_source="stored",
        events=[],
        diff_summary=RevisionDiffSummary(created=0, updated=0, deleted=0, restored=0),
        restorable=True,
    )
