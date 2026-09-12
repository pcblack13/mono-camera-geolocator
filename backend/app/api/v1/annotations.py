"""Annotations — endpoints 16–22.

★ SCOPE.md §5: a landmark is an ``Annotation`` and is the photo endpoint of a manual
correspondence. Reads (16, 20) and the checked single edit (21, via
``AnnotationService.update_fields``) use methods IU-19 provides. The **bulk** write path
(17 create, 18 upsert, 19 bulk-delete, 22 delete) is contracted to ``annotation_service``
(§2.4: *"bulk upsert · versioning · revision allocation"*) but the current service exposes
only ``update_fields``; those routes are coded to the declared interface and **flagged in
IU-21's report** as needing ``AnnotationService.{create,bulk_upsert,delete}``.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps, presenters
from app.api.etag import if_match_ok, version_etag
from app.core.exceptions import ConfirmationRequired, StaleAnnotationVersion
from app.core.pagination import SortKey, SortParams
from app.core.security import Principal
from app.schemas.annotation import (
    ANNOTATION_SORT_FIELDS,
    AnnotationBulkUpsertRequest,
    AnnotationBulkUpsertResponse,
    AnnotationCreate,
    AnnotationRead,
    AnnotationUpdate,
)
from app.schemas.common import Page
from app.services.annotation_service import AnnotationService

router_nested = APIRouter()
router_flat = APIRouter()

_DEFAULT_SORT = (SortKey("ordering", descending=False), SortKey("created_at", descending=False))


async def _read_with_gcps(service: AnnotationService, annotations) -> list[AnnotationRead]:
    """Attach batched ``gcp_ids`` (no N+1) and present."""
    ids = [a.id for a in annotations]
    gcp_map = await service.gcp_ids_for(ids) if ids else {}
    return [presenters.to_annotation_read(a, gcp_ids=gcp_map.get(a.id, [])) for a in annotations]


# ── router_nested (/images/{image_id}/annotations) ─────────────────────────────


@router_nested.get(
    "/images/{image_id}/annotations",
    response_model=Page[AnnotationRead],
    summary="List an image's annotations",
)
async def list_annotations(
    image_id: UUID,
    pagination=Depends(deps.get_pagination),
    sort: str | None = Depends(deps.get_sort),
    kind: str | None = Query(None, description="CSV of AnnotationKind."),
    geom_type: str | None = Query(None, description="CSV of AnnotationGeomType."),
    is_gcp_candidate: bool | None = Query(None),
    include_deleted: bool = Query(False),
    q: str | None = Query(None),
    image=Depends(deps.get_image),
    db: AsyncSession = Depends(deps.get_db),
) -> Page[AnnotationRead]:
    service = AnnotationService(db)
    parsed = SortParams.parse(sort, allowed=ANNOTATION_SORT_FIELDS, default=_DEFAULT_SORT)
    rows, total = await service.list_for_image(
        image.id,
        pagination=pagination,
        sort=parsed,
        kind_csv=kind,
        geom_type_csv=geom_type,
        is_gcp_candidate=is_gcp_candidate,
        include_deleted=include_deleted,
        q=q,
    )
    return Page.of(await _read_with_gcps(service, rows), total, pagination)


@router_nested.post(
    "/images/{image_id}/annotations",
    response_model=AnnotationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an annotation",
)
async def create_annotation(
    body: AnnotationCreate,
    image=Depends(deps.get_image),
    db: AsyncSession = Depends(deps.get_db),
    principal: Principal = Depends(deps.get_principal),
    _: None = Depends(deps.require_writable),
) -> AnnotationRead:
    service = AnnotationService(db)
    # AnnotationService converts the GeoJSON pixel geometry to pixel_geom + a representative
    # point, allocates a revision, and versions the write (§2.4).
    annotation = await service.create(
        image, body, actor_id=None if principal.is_anonymous else principal.subject
    )
    await db.flush()
    return (await _read_with_gcps(service, [annotation]))[0]


@router_nested.put(
    "/images/{image_id}/annotations",
    response_model=AnnotationBulkUpsertResponse,
    summary="Bulk upsert the annotation set (the canvas save path)",
)
async def bulk_upsert_annotations(
    body: AnnotationBulkUpsertRequest,
    image=Depends(deps.get_image),
    db: AsyncSession = Depends(deps.get_db),
    principal: Principal = Depends(deps.get_principal),
    _: None = Depends(deps.require_writable),
) -> AnnotationBulkUpsertResponse:
    service = AnnotationService(db)
    result = await service.bulk_upsert(
        image, body, actor_id=None if principal.is_anonymous else principal.subject
    )
    await db.flush()
    return result


@router_nested.delete(
    "/images/{image_id}/annotations",
    response_model=AnnotationBulkUpsertResponse,
    summary="Bulk delete annotations",
)
async def bulk_delete_annotations(
    request: Request,
    image=Depends(deps.get_image),
    kind: str | None = Query(None, description="CSV of AnnotationKind."),
    db: AsyncSession = Depends(deps.get_db),
    principal: Principal = Depends(deps.get_principal),
    _: None = Depends(deps.require_writable),
) -> AnnotationBulkUpsertResponse:
    deps.require_confirm_delete(request)  # ★ X-Confirm-Delete REQUIRED (endpoint 19)
    service = AnnotationService(db)
    result = await service.bulk_delete(
        image, kind_csv=kind, actor_id=None if principal.is_anonymous else principal.subject
    )
    await db.flush()
    return result


# ── router_flat (/annotations/{annotation_id}) ─────────────────────────────────


@router_flat.get("/annotations/{annotation_id}", response_model=AnnotationRead, summary="Get an annotation")
async def get_annotation(
    response: Response,
    annotation=Depends(deps.get_annotation),
    db: AsyncSession = Depends(deps.get_db),
) -> AnnotationRead:
    response.headers["ETag"] = version_etag(annotation.version_no)
    return (await _read_with_gcps(AnnotationService(db), [annotation]))[0]


@router_flat.patch("/annotations/{annotation_id}", response_model=AnnotationRead, summary="Edit an annotation")
async def update_annotation(
    annotation_id: UUID,
    body: AnnotationUpdate,
    request: Request,
    response: Response,
    annotation=Depends(deps.get_annotation),
    db: AsyncSession = Depends(deps.get_db),
    principal: Principal = Depends(deps.get_principal),
    _: None = Depends(deps.require_writable),
) -> AnnotationRead:
    supplied = deps.require_if_match(request)  # ★ If-Match REQUIRED (428 absent, 412 stale)
    if not if_match_ok(supplied, annotation.version_no):
        raise StaleAnnotationVersion(
            f"Annotation {annotation_id} is at version {annotation.version_no}; refetch and retry."
        )
    service = AnnotationService(db)
    # Revision allocation is the undo/redo lock, inside this transaction (§ annotation_service).
    # It is keyed by PROJECT, so resolve the annotation's image → project first.
    from app.services.image_service import ImageService

    image = await ImageService(db, deps.get_settings(), storage=deps.get_storage()).get(annotation.image_id)
    revision_seq = await service.allocate_revision(image.project_id)
    updated = await service.update_fields(
        annotation_id,
        expected_version_no=annotation.version_no,
        revision_seq=revision_seq,
        values=body.as_changes(),
        updated_by=None if principal.is_anonymous else principal.subject,
    )
    await db.flush()
    response.headers["ETag"] = version_etag(updated.version_no)
    return (await _read_with_gcps(service, [updated]))[0]


@router_flat.delete("/annotations/{annotation_id}", response_model=AnnotationRead, summary="Delete an annotation")
async def delete_annotation(
    annotation_id: UUID,
    request: Request,
    annotation=Depends(deps.get_annotation),
    db: AsyncSession = Depends(deps.get_db),
    principal: Principal = Depends(deps.get_principal),
    _: None = Depends(deps.require_writable),
) -> AnnotationRead:
    service = AnnotationService(db)
    deleted = await service.delete(
        annotation_id, actor_id=None if principal.is_anonymous else principal.subject
    )
    await db.flush()
    return (await _read_with_gcps(service, [deleted]))[0]
