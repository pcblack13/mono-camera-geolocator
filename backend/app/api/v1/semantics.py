"""Semantic features — endpoints 46, 47.

★★ SCOPE.md §4: semantic detection is an ABC only. ``POST /images/{id}/segment`` (47) returns
``501`` (``SemanticService.segment``). The list (46) is a real **empty** ``Page`` — the read
succeeds and the collection is genuinely empty, so it is never a 501.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core.pagination import SortKey, SortParams
from app.schemas.common import Page
from app.schemas.semantic import (
    SEMANTIC_SORT_FIELDS,
    SegmentRequest,
    SemanticFeatureRead,
)
from app.services.semantic_service import SemanticService

router = APIRouter()

_DEFAULT_SORT = (SortKey("created_at", descending=True),)


@router.get(
    "/images/{image_id}/semantic-features",
    response_model=Page[SemanticFeatureRead],
    summary="An image's semantic features",
)
async def list_semantic_features(
    class_csv: str | None = Query(None, alias="class"),
    space: str | None = Query(None),
    detector: str | None = Query(None),
    confidence_gte: float | None = Query(None, alias="confidence__gte", ge=0.0, le=1.0),
    match_result_id: UUID | None = Query(None),
    pagination=Depends(deps.get_pagination),
    sort: str | None = Depends(deps.get_sort),
    image=Depends(deps.get_image),
    db: AsyncSession = Depends(deps.get_db),
) -> Page[SemanticFeatureRead]:
    parsed = SortParams.parse(sort, allowed=SEMANTIC_SORT_FIELDS, default=_DEFAULT_SORT)
    rows, total = await SemanticService(db).list_for_image(
        image.id, pagination=pagination, sort=parsed, class_csv=class_csv, space=space,
        detector=detector, confidence_gte=confidence_gte, match_result_id=match_result_id,
    )
    return Page.of([], total, pagination)  # empty in this build (segmentation deferred)


@router.post("/images/{image_id}/segment", summary="Segment an image (DEFERRED)")
async def segment(
    body: SegmentRequest,
    image=Depends(deps.get_image),
    db: AsyncSession = Depends(deps.get_db),
    _: None = Depends(deps.require_writable),
):
    SemanticService(db).segment(image.id)  # ★ DEFERRED → 501
