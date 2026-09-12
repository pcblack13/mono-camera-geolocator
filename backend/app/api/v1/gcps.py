"""GCPs — endpoints 38–42, 64, plus the SCOPE.md §5 additions 65 and 66.

★★ **THE CORE OF THIS BUILD** (SCOPE.md §5). With automatic matching deferred, a GCP is a
**manual correspondence**: the surveyor marks a landmark in the photo and clicks the same spot
on the satellite map. The coordinate is a **direct observation**, ``source='manual'``.

* 65 ``POST /images/{id}/gcps``            — create a manual GCP (the product's core write).
* 66 ``PUT /gcps/{id}/correspondence``     — re-commit the pairing (either endpoint draggable).
* 40 ``PATCH /gcps/{id}``                  — adjust / metadata edit (``If-Match`` REQUIRED).
* 41 ``POST /gcps/{id}/reset``             — restore the original answer (idempotent-safe).
* 42 ``POST /images/{id}/gcps/recompute``  — **DEFERRED** (501): needs the homography estimator.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps, presenters
from app.api.etag import etag_for, if_match_ok
from app.core.config import Settings
from app.api.v1.projects import parse_bbox
from app.core.exceptions import StaleGcpVersion
from app.core.pagination import SortKey, SortParams
from app.observability import metrics
from app.schemas.common import GeoJsonFeature, GeoJsonFeatureCollection, Page
from app.schemas.gcp import (
    GCP_SORT_FIELDS,
    GcpCorrespondenceUpdate,
    GcpCopyResult,
    GcpManualCreate,
    GcpOverview,
    GcpRead,
    GcpResetRequest,
    GcpUpdate,
)
from app.services.gcp_service import GcpService

router_image = APIRouter()
router_flat = APIRouter()
router_results = APIRouter()

_DEFAULT_SORT = (SortKey("created_at", descending=True),)


def _gcp_etag(gcp) -> str:
    return etag_for(int(gcp.updated_at.timestamp() * 1_000_000) if gcp.updated_at else 0, gcp.updated_at)


def _feature_collection(gcps) -> GeoJsonFeatureCollection:
    features: list[GeoJsonFeature] = []
    for gcp in gcps:
        read = presenters.to_gcp_read(gcp)
        features.append(
            GeoJsonFeature(
                geometry={"type": "Point", "coordinates": [read.lon, read.lat]},
                properties={
                    "id": str(read.id),
                    "code": read.code,
                    "confidence": read.confidence,
                    "source": read.source.value if hasattr(read.source, "value") else read.source,
                    "total_ce90_m": read.accuracy.total_ce90_m,
                },
                id=str(read.id),
            )
        )
    return GeoJsonFeatureCollection(features=features)


# ── router_image ────────────────────────────────────────────────────────────────


@router_image.get("/images/{image_id}/gcps", summary="List an image's GCPs")
async def list_gcps(
    format: str = Query("json", pattern="^(json|geojson)$"),
    match_result_id: UUID | None = Query(None),
    source: str | None = Query(None, description="manual|automatic (SCOPE.md §5 filter)."),
    confidence_gte: float | None = Query(None, alias="confidence__gte", ge=0.0, le=100.0),
    confidence_lte: float | None = Query(None, alias="confidence__lte", ge=0.0, le=100.0),
    manually_adjusted: bool | None = Query(None),
    is_stale: bool | None = Query(None),
    is_included_in_export: bool | None = Query(None),
    q: str | None = Query(None),
    pagination=Depends(deps.get_pagination),
    sort: str | None = Depends(deps.get_sort),
    image=Depends(deps.get_image),
    db: AsyncSession = Depends(deps.get_db),
):
    parsed = SortParams.parse(sort, allowed=GCP_SORT_FIELDS, default=_DEFAULT_SORT)
    rows, total = await deps.list_gcps_for_image(
        db,
        image.id,
        pagination=pagination,
        sort=parsed,
        match_result_id=match_result_id,
        source=source,
        confidence_gte=confidence_gte,
        confidence_lte=confidence_lte,
        manually_adjusted=manually_adjusted,
        is_stale=is_stale,
        is_included_in_export=is_included_in_export,
        q=q,
    )
    if format == "geojson":
        return _feature_collection(rows)
    return Page.of([presenters.to_gcp_read(g) for g in rows], total, pagination)


@router_image.post(
    "/images/{image_id}/gcps",
    response_model=GcpRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a manual GCP (SCOPE.md §5)",
)
async def create_manual_gcp(
    body: GcpManualCreate,
    request: Request,
    response: Response,
    image=Depends(deps.get_image),
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    _: None = Depends(deps.require_writable),
) -> GcpRead:
    from app.services.imagery_service import ImageryService

    service = GcpService(
        db, settings, imagery=ImageryService(settings, registry=deps.get_imagery_registry(request))
    )
    gcp = await service.create_manual(image, body)
    await db.flush()
    response.headers["Location"] = f"{request.scope.get('root_path', '')}/api/v1/gcps/{gcp.id}"
    return presenters.to_gcp_read(gcp)


@router_image.post(
    "/images/{image_id}/gcps/copy-from/{source_image_id}",
    response_model=GcpCopyResult,
    status_code=status.HTTP_201_CREATED,
    summary="Carry another frame's control points onto this one (same camera, same aim)",
)
async def copy_gcps_from(
    source_image_id: UUID,
    request: Request,
    image=Depends(deps.get_image),
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    _: None = Depends(deps.require_writable),
) -> GcpCopyResult:
    """★ A NEW FRAME, THE SAME AIM (2026-09-09, owner ask). When a camera adopts a
    fresh frame and the operator says the camera has not moved, every control
    point of the previous frame is valid at the same pixel — so it is recreated
    on the new frame through the ordinary manual-GCP path (its own annotation,
    its own elevation sample, provenance kept) instead of being placed again.
    Both frames must belong to the same project."""
    from app.db.repositories.images import ImageRepository
    from app.services.imagery_service import ImageryService

    source = await ImageRepository(db).get_active(source_image_id)
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"No image {source_image_id}."
        )
    if source.project_id != image.project_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="control points can only be carried between frames of the same project.",
        )
    service = GcpService(
        db, settings, imagery=ImageryService(settings, registry=deps.get_imagery_registry(request))
    )
    copied = await service.copy_to(source, image)
    await db.flush()
    return GcpCopyResult(copied=len(copied), items=[presenters.to_gcp_read(g) for g in copied])


@router_image.post("/images/{image_id}/gcps/recompute", summary="Recompute GCPs (DEFERRED)")
async def recompute_gcps(
    image=Depends(deps.get_image),
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    _: None = Depends(deps.require_writable),
):
    # ★ DEFERRED (SCOPE.md §4): both refit and rederive need the homography estimator. 501.
    GcpService(db, settings).recompute(image.id)


# ── router_flat ─────────────────────────────────────────────────────────────────


@router_flat.get(
    "/gcps",
    response_model=Page[GcpOverview],
    summary="List GCPs across every project (dashboard map)",
)
async def list_gcps_overview(
    project_id: UUID | None = Query(None),
    image_id: UUID | None = Query(None),
    album_id: UUID | None = Query(None, description="Every GCP in this album's projects."),
    min_confidence: float | None = Query(None, ge=0.0, le=100.0),
    bbox: str | None = Query(None, description='"minlon,minlat,maxlon,maxlat", EPSG:4326.'),
    pagination=Depends(deps.get_pagination),
    sort: str | None = Depends(deps.get_sort),
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
) -> Page[GcpOverview]:
    """★ The **only** cross-project view of the deliverable.

    Newest first by default. ``project_name``, ``image_filename`` and ``landmark_name``
    are resolved by joins inside the repository — one statement for the whole page, no
    matter how many rows, because this feeds a map that may render thousands of markers.
    """
    parsed = SortParams.parse(sort, allowed=GCP_SORT_FIELDS, default=_DEFAULT_SORT)
    rows, total = await GcpService(db, settings).list_overview(
        pagination=pagination,
        sort=parsed,
        project_id=project_id,
        image_id=image_id,
        album_id=album_id,
        min_confidence=min_confidence,
        bbox=parse_bbox(bbox),
    )
    return Page.of([presenters.to_gcp_overview(r) for r in rows], total, pagination)


@router_flat.get("/gcps/{gcp_id}", response_model=GcpRead, summary="Get a GCP")
async def get_gcp(response: Response, gcp=Depends(deps.get_gcp)) -> GcpRead:
    response.headers["ETag"] = _gcp_etag(gcp)
    return presenters.to_gcp_read(gcp)


@router_flat.patch("/gcps/{gcp_id}", response_model=GcpRead, summary="Adjust a GCP")
async def update_gcp(
    body: GcpUpdate,
    request: Request,
    response: Response,
    gcp=Depends(deps.get_gcp),
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    _: None = Depends(deps.require_writable),
) -> GcpRead:
    supplied = deps.require_if_match(request)  # ★ If-Match REQUIRED → 428 when absent
    if not if_match_ok(supplied, _gcp_etag(gcp)):
        raise StaleGcpVersion(f"GCP {gcp.id} was modified since your ETag; refetch and retry.")
    updated = await GcpService(db, settings).adjust(gcp, body)
    await db.flush()
    if updated.manually_adjusted:
        try:
            metrics.gcp_adjustments_total.inc()
        except Exception:  # noqa: BLE001
            pass
    response.headers["ETag"] = _gcp_etag(updated)
    return presenters.to_gcp_read(updated)


@router_flat.post("/gcps/{gcp_id}/reset", response_model=GcpRead, summary="Reset a GCP to its original")
async def reset_gcp(
    gcp_id: UUID,
    body: GcpResetRequest,
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    _: None = Depends(deps.require_writable),
) -> GcpRead:
    gcp = await GcpService(db, settings).reset(gcp_id)
    await db.flush()
    return presenters.to_gcp_read(gcp)


@router_flat.delete("/gcps/{gcp_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a GCP")
async def delete_gcp(
    gcp=Depends(deps.get_gcp),
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    _: None = Depends(deps.require_writable),
) -> Response:
    """Permanently remove a manual GCP.

    ★ A hard delete, by design: a manual GCP is the surveyor's own observation, not
    algorithm output that needs a tombstone for provenance — the ``gcps`` table carries no
    ``deleted_at``, nothing references a GCP as a FK child, and the backing landmark
    annotation is left intact (deleting a control point is not deleting the feature it
    marked). ``get_gcp`` already 404s an unknown id.
    """
    await GcpService(db, settings).delete(gcp)
    await db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router_flat.put("/gcps/{gcp_id}/correspondence", response_model=GcpRead, summary="Re-commit the pairing (SCOPE.md §5)")
async def update_correspondence(
    body: GcpCorrespondenceUpdate,
    request: Request,
    response: Response,
    gcp=Depends(deps.get_gcp),
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    _: None = Depends(deps.require_writable),
) -> GcpRead:
    supplied = deps.require_if_match(request)  # ★ If-Match REQUIRED
    if not if_match_ok(supplied, _gcp_etag(gcp)):
        raise StaleGcpVersion(f"GCP {gcp.id} was modified since your ETag; refetch and retry.")
    from app.services.imagery_service import ImageryService

    service = GcpService(
        db, settings, imagery=ImageryService(settings, registry=deps.get_imagery_registry(request))
    )
    updated = await service.update_correspondence(gcp, body)
    await db.flush()
    response.headers["ETag"] = _gcp_etag(updated)
    return presenters.to_gcp_read(updated)


# ── router_results ───────────────────────────────────────────────────────────────


@router_results.get("/match-results/{match_result_id}/gcps", response_model=Page[GcpRead], summary="A match result's GCPs")
async def list_gcps_for_match_result(
    match_result_id: UUID,
    pagination=Depends(deps.get_pagination),
    sort: str | None = Depends(deps.get_sort),
    db: AsyncSession = Depends(deps.get_db),
) -> Page[GcpRead]:
    parsed = SortParams.parse(sort, allowed=GCP_SORT_FIELDS, default=_DEFAULT_SORT)
    rows, total = await deps.list_gcps_for_match_result(
        db, match_result_id, pagination=pagination, sort=parsed
    )
    return Page.of([presenters.to_gcp_read(g) for g in rows], total, pagination)
