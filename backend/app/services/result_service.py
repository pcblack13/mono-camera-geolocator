"""``result_service`` — match-result selection and the staleness it implies.

★ SCOPE.md §4 rule 5: ``match_results`` holds no rows in this build (the automatic engine
is deferred), but the **reads are real and the selection path is real**. Stubbing it would
mean the day the engine lands, this layer is unwritten and untested and SCOPE.md §7's "zero
changes outside ai_engine/" is already broken.

★ **Selecting a different result marks the superseded GCPs stale — and that is a
*deliberate* call, never a side effect** (§6.2). Staleness is a flag a human's action sets;
it is never an implicit recompute. The repository returns the previously-selected id so
this layer can make that second call explicitly.
"""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import PaginationParams, SortParams
from app.db.repositories.gcps import GcpRepository
from app.db.repositories.matches import MatchResultRepository
from app.models.enums import GcpStaleReason
from app.models.job import MatchJob
from app.models.match import MatchResult

__all__ = ["ResultService"]


class ResultService:
    """Read match results; select one and mark what it supersedes."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._results = MatchResultRepository(session)
        self._gcps = GcpRepository(session)

    # ── reads ─────────────────────────────────────────────────────────────────

    async def list_for_image(
        self,
        image_id: uuid.UUID,
        *,
        pagination: PaginationParams,
        sort: SortParams,
        match_job_id: uuid.UUID | None = None,
        is_selected: bool | None = None,
        confidence_gte: float | None = None,
        confidence_lte: float | None = None,
    ) -> tuple[Sequence[MatchResult], int]:
        """``GET /images/{id}/match-results`` (34) — real; empty in this build."""
        return await self._results.list_for_image(
            image_id,
            pagination=pagination,
            sort=sort,
            match_job_id=match_job_id,
            is_selected=is_selected,
            confidence_gte=confidence_gte,
            confidence_lte=confidence_lte,
        )

    async def get_selected_for_image(self, image_id: uuid.UUID) -> MatchResult | None:
        """The result currently driving the map for a photograph."""
        return await self._results.get_selected_for_image(image_id)

    # ── selection ─────────────────────────────────────────────────────────────

    async def select(self, match_result_id: uuid.UUID) -> MatchResult:
        """``POST /match-results/{id}/select`` (37) — promote a candidate.

        ★ Marks the GCPs that cited the *previous* selection stale, with
        ``homography_superseded`` — a deliberate second call, because staleness is never a
        side effect (§6.2). The GCPs are flagged, never recomputed: a coordinate already in
        a survey report changes only when a human opens ``POST .../gcps/recompute``.

        Raises:
            MatchResultNotFound: no such candidate.
        """
        result, previous = await self._results.select_result(match_result_id)
        if previous is not None:
            image_id = await self._image_id_for_result(result)
            if image_id is not None:
                await self._gcps.mark_stale(
                    reason=GcpStaleReason.HOMOGRAPHY_SUPERSEDED,
                    image_id=image_id,
                    exclude_match_result_id=match_result_id,
                )
        return result

    # ── internals ─────────────────────────────────────────────────────────────

    async def _image_id_for_result(self, result: MatchResult) -> uuid.UUID | None:
        """The photograph a result belongs to, via its match job.

        A result has no ``image_id`` of its own (§5.5) — denormalising one would be a
        second chance to disagree about which photograph a coordinate came from — so it is
        read through the job.
        """
        from sqlalchemy import select

        job = await self._session.get(MatchJob, result.match_job_id)
        if job is not None:
            return job.image_id
        # Fallback for a detached result: read only the id column.
        return await self._session.scalar(
            select(MatchJob.image_id).where(MatchJob.id == result.match_job_id)
        )
