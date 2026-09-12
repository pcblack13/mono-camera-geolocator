"""Landmark suggestions — endpoints 43–45.

★★ SCOPE.md §4: automatic landmark suggestion is an ABC only. ``POST …/suggest-landmarks`` (43)
returns ``501`` (``SuggestionService.suggest``). The list (44) is a real **empty** ``Page`` — not
a 501, because the read genuinely succeeds and the collection is genuinely empty. Accept (45) has
nothing to accept, so it is an honest ``404 SUGGESTION_NOT_FOUND``, never a fabricated landmark.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core.pagination import SortKey, SortParams
from app.schemas.annotation import AnnotationBulkUpsertResponse
from app.schemas.common import Page
from app.schemas.suggestion import (
    SUGGESTION_SORT_FIELDS,
    LandmarkSuggestionRead,
    SuggestionAcceptRequest,
    SuggestLandmarksRequest,
)
from app.services.suggestion_service import SuggestionService

router = APIRouter()

_DEFAULT_SORT = (SortKey("rank", descending=False),)


@router.post("/images/{image_id}/suggest-landmarks", summary="Suggest landmarks (DEFERRED)")
async def suggest_landmarks(
    body: SuggestLandmarksRequest,
    image=Depends(deps.get_image),
    db: AsyncSession = Depends(deps.get_db),
    _: None = Depends(deps.require_writable),
):
    SuggestionService(db).suggest(image.id)  # ★ DEFERRED → 501


@router.get(
    "/images/{image_id}/landmark-suggestions",
    response_model=Page[LandmarkSuggestionRead],
    summary="An image's landmark suggestions",
)
async def list_suggestions(
    status_csv: str | None = Query(None, alias="status"),
    kind: str | None = Query(None),
    score_gte: float | None = Query(None, alias="score__gte", ge=0.0, le=1.0),
    detector: str | None = Query(None),
    pagination=Depends(deps.get_pagination),
    sort: str | None = Depends(deps.get_sort),
    image=Depends(deps.get_image),
    db: AsyncSession = Depends(deps.get_db),
) -> Page[LandmarkSuggestionRead]:
    parsed = SortParams.parse(sort, allowed=SUGGESTION_SORT_FIELDS, default=_DEFAULT_SORT)
    rows, total = await SuggestionService(db).list_for_image(
        image.id, pagination=pagination, sort=parsed, status_csv=status_csv, kind_csv=kind,
        score_gte=score_gte, detector=detector,
    )
    return Page.of([], total, pagination)  # empty in this build (suggestion deferred)


@router.post(
    "/images/{image_id}/landmark-suggestions/accept",
    response_model=AnnotationBulkUpsertResponse,
    summary="Accept suggestions into annotations",
)
async def accept_suggestions(
    body: SuggestionAcceptRequest,
    image=Depends(deps.get_image),
    db: AsyncSession = Depends(deps.get_db),
    _: None = Depends(deps.require_writable),
) -> AnnotationBulkUpsertResponse:
    service = SuggestionService(db)
    # No suggestion rows exist (deferred); accept of any id is an honest 404, never a fake landmark.
    for suggestion_id in body.suggestion_ids:
        await service.accept(suggestion_id)
    from app.core.exceptions import SuggestionNotFound

    raise SuggestionNotFound("There are no landmark suggestions to accept (suggestion is deferred).")
