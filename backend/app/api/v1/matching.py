"""Matching — endpoints 30, 34–37.

★★ SCOPE.md §1: the automatic matching engine is DEFERRED. ``POST /images/{id}/match`` (30) is
**registered and documented** and returns ``501`` + ``feature: "deferred"``
(``MatchService.start_match``) — never 404, never a fabricated result. The result reads (34–37)
are real against the empty ``match_results`` table: a list is an empty ``Page``; a single
result is ``404 MATCH_RESULT_NOT_FOUND`` (no rows in this build), never a fake.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core.config import Settings
from app.core.exceptions import MatchResultNotFound
from app.core.pagination import SortKey, SortParams
from app.schemas.common import Page
from app.schemas.matching import (
    MATCH_RESULT_SORT_FIELDS,
    MatchRequest,
    MatchResultRead,
    MatchResultSelectRequest,
    MatchResultSummary,
)
from app.services.match_service import MatchService
from app.services.result_service import ResultService

router_image = APIRouter()
router_results = APIRouter()

_DEFAULT_SORT = (SortKey("rank", descending=False),)


@router_image.post("/images/{image_id}/match", summary="Start a match job (DEFERRED)")
async def start_match(
    body: MatchRequest,
    image=Depends(deps.get_image),
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    _: None = Depends(deps.require_writable),
):
    # ★ DEFERRED (SCOPE.md §1): 501, no job enqueued, no result fabricated.
    MatchService(db, settings).start_match(image.id)


@router_image.get(
    "/images/{image_id}/match-results",
    response_model=Page[MatchResultSummary],
    summary="A match's candidate results",
)
async def list_match_results(
    match_job_id: UUID | None = Query(None),
    is_selected: bool | None = Query(None),
    confidence_gte: float | None = Query(None, alias="confidence__gte", ge=0.0, le=100.0),
    confidence_lte: float | None = Query(None, alias="confidence__lte", ge=0.0, le=100.0),
    pagination=Depends(deps.get_pagination),
    sort: str | None = Depends(deps.get_sort),
    image=Depends(deps.get_image),
    db: AsyncSession = Depends(deps.get_db),
) -> Page[MatchResultSummary]:
    parsed = SortParams.parse(sort, allowed=MATCH_RESULT_SORT_FIELDS, default=_DEFAULT_SORT)
    rows, total = await ResultService(db).list_for_image(
        image.id,
        pagination=pagination,
        sort=parsed,
        match_job_id=match_job_id,
        is_selected=is_selected,
        confidence_gte=confidence_gte,
        confidence_lte=confidence_lte,
    )
    # Empty in this build (matching deferred); presented as an honest empty page, never a 404.
    return Page.of([], total, pagination)


@router_results.get("/match-results/{match_result_id}", response_model=MatchResultRead, summary="A single result")
async def get_match_result(match_result_id: UUID) -> MatchResultRead:
    # No rows exist in this build (matching deferred). Honest 404, never a fabricated candidate.
    raise MatchResultNotFound(f"No match result {match_result_id} (automatic matching is deferred).")


@router_results.get("/match-results/{match_result_id}/satellite-image", summary="A result's satellite mosaic")
async def get_satellite_image(match_result_id: UUID) -> Response:
    raise MatchResultNotFound(f"No match result {match_result_id} (automatic matching is deferred).")


@router_results.post(
    "/match-results/{match_result_id}/select",
    response_model=MatchResultRead,
    summary="Select a candidate result",
)
async def select_match_result(
    match_result_id: UUID,
    body: MatchResultSelectRequest,
    db: AsyncSession = Depends(deps.get_db),
    _: None = Depends(deps.require_writable),
) -> MatchResultRead:
    # ResultService.select raises MatchResultNotFound for the (empty) table — real path, no rows.
    await ResultService(db).select(match_result_id)
    raise MatchResultNotFound(f"No match result {match_result_id} (automatic matching is deferred).")
