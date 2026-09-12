"""``match_results`` — :class:`MatchResultRepository`.

★ **SCOPE.md §4 rule 5: this is real code against a real schema that simply has no
writer in this build.** The automatic matching engine is deferred, so nothing inserts a
``match_results`` row today — but the table is created exactly as specified, the reads
are real, and ``select_result`` is real. Stubbing it would mean the day the engine lands,
the persistence layer is unwritten and untested and the "zero changes outside
``ai_engine/``" promise (SCOPE.md §7) is already broken.

One row per **candidate** the matcher scored. The winner is ``is_selected``. **Losers are
kept** — the UI offers "other candidates", and a surveyor overruling the algorithm is a
first-class workflow.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any, Sequence

from sqlalchemy import Select, delete, func, select, update

from app.core.exceptions import MatchResultNotFound
from app.core.pagination import PaginationParams, SortParams
from app.db.repositories.base import BaseRepository, SortableColumns
from app.models.gcp import GCP
from app.models.job import MatchJob
from app.models.match import MatchResult

__all__ = ["MatchResultRepository"]


class MatchResultRepository(BaseRepository[MatchResult]):
    """Scored candidate windows and their transform chains."""

    model = MatchResult

    @property
    def _sortable(self) -> SortableColumns:
        """``MATCH_RESULT_SORT_FIELDS`` resolved onto SQL."""
        return {
            "rank": MatchResult.rank,
            "overall_confidence": MatchResult.overall_confidence,
            "created_at": MatchResult.created_at,
        }

    # ── reads ────────────────────────────────────────────────────────────────

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
        """``GET /images/{image_id}/match-results`` (34).

        Joins ``match_jobs``: a result knows its job, and a job knows its image, but a
        result has no ``image_id`` of its own — denormalising one would be a second
        chance to disagree about which photograph a coordinate came from.
        """
        stmt: Select[Any] = (
            select(MatchResult)
            .join(MatchJob, MatchJob.id == MatchResult.match_job_id)
            .where(MatchJob.image_id == image_id)
        )
        if match_job_id is not None:
            stmt = stmt.where(MatchResult.match_job_id == match_job_id)
        if is_selected is not None:
            stmt = stmt.where(MatchResult.is_selected.is_(is_selected))
        if confidence_gte is not None:
            stmt = stmt.where(MatchResult.overall_confidence >= confidence_gte)
        if confidence_lte is not None:
            stmt = stmt.where(MatchResult.overall_confidence <= confidence_lte)
        return await self.page(stmt, pagination, sort, self._sortable)

    async def list_for_job(self, match_job_id: uuid.UUID) -> Sequence[MatchResult]:
        """Every candidate of one job, best rank first. ``uq_match_results_job_rank``."""
        return await self._scalars(
            select(MatchResult)
            .where(MatchResult.match_job_id == match_job_id)
            .order_by(MatchResult.rank.asc())
        )

    async def get_selected_for_job(self, match_job_id: uuid.UUID) -> MatchResult | None:
        """The winner of one job, if it has one.

        At most one exists — ``uq_match_results_job_selected`` is a partial unique index
        and enforces it in the database rather than by hope — so this is
        ``scalar_one_or_none`` and not a "take the first".
        """
        return await self._scalar_one_or_none(
            select(MatchResult).where(
                MatchResult.match_job_id == match_job_id,
                MatchResult.is_selected.is_(True),
            )
        )

    async def get_selected_for_image(self, image_id: uuid.UUID) -> MatchResult | None:
        """The most recent selected result for a photograph.

        Unlike the per-job read this **can** legitimately see several rows — one per job
        — so it is ordered and limited rather than ``scalar_one``. The newest selection
        is the one the map is showing.
        """
        return await self._scalar_one_or_none(
            select(MatchResult)
            .join(MatchJob, MatchJob.id == MatchResult.match_job_id)
            .where(MatchJob.image_id == image_id, MatchResult.is_selected.is_(True))
            .order_by(MatchResult.created_at.desc())
            .limit(1)
        )

    async def best_confidence_for_job(self, match_job_id: uuid.UUID) -> float | None:
        """``match_jobs.best_confidence``'s source value. NULL when there are no results."""
        return await self._scalar(
            select(func.max(MatchResult.overall_confidence)).where(
                MatchResult.match_job_id == match_job_id
            )
        )

    async def count_for_job(self, match_job_id: uuid.UUID) -> int:
        """``match_jobs.result_count``'s source value."""
        return int(
            await self._scalar(
                select(func.count())
                .select_from(MatchResult)
                .where(MatchResult.match_job_id == match_job_id)
            )
            or 0
        )

    # ── writes ───────────────────────────────────────────────────────────────

    async def select_result(self, match_result_id: uuid.UUID) -> tuple[MatchResult, uuid.UUID | None]:
        """``POST /match-results/{id}/select`` (37) — move the selection within a job.

        ★ **Two statements, and it must be two.** ``uq_match_results_job_selected`` is a
        partial *unique index*, and PostgreSQL checks a unique index per row as an
        UPDATE walks the table — so a single ``SET is_selected = (id = :chosen)`` can
        fail spuriously depending on the order rows happen to be visited, with the new
        winner inserted into the index before the old one is removed. Clearing first and
        setting second leaves the index at "zero selected" in between, which is a state
        the partial index is perfectly happy with and which no other transaction can see
        anyway.

        Args:
            match_result_id: The candidate to promote.

        Returns:
            ``(result, previously_selected_id)``. The second element is what the caller
            needs to mark the superseded GCPs stale — **that is a separate, deliberate
            call** (``GcpRepository.mark_stale`` with ``homography_superseded``), because
            staleness is never a side effect (§6.2). None when nothing was selected
            before.

        Raises:
            MatchResultNotFound: no such candidate.
        """
        target = await self.get(match_result_id)
        if target is None:
            raise MatchResultNotFound(f"No match result {match_result_id}.")

        previous = await self._scalar(
            select(MatchResult.id).where(
                MatchResult.match_job_id == target.match_job_id,
                MatchResult.is_selected.is_(True),
                MatchResult.id != match_result_id,
            )
        )

        # [1] Clear the incumbent. The index now has no entry for this job.
        await self._execute(
            update(MatchResult)
            .where(
                MatchResult.match_job_id == target.match_job_id,
                MatchResult.is_selected.is_(True),
                MatchResult.id != match_result_id,
            )
            .values(is_selected=False)
        )
        # [2] Promote the challenger.
        await self._execute(
            update(MatchResult)
            .where(MatchResult.id == match_result_id)
            .values(is_selected=True)
        )
        return await self.refresh(target), previous

    async def clear_selection_for_job(self, match_job_id: uuid.UUID) -> uuid.UUID | None:
        """Deselect a job's winner, leaving it with none.

        Returns:
            The id of the row that was deselected, or None.
        """
        stmt = (
            update(MatchResult)
            .where(
                MatchResult.match_job_id == match_job_id,
                MatchResult.is_selected.is_(True),
            )
            .values(is_selected=False)
            .returning(MatchResult.id)
        )
        return (await self._execute(stmt)).scalar_one_or_none()

    async def prune_losers_older_than(self, *, days: int) -> int:
        """§5.9 retention: drop non-selected candidates older than ``days``.

        ★ **The ``NOT EXISTS`` is not a substitute for the FK, it is what lets the
        statement finish.** §5.9 says *"``RESTRICT`` from ``gcps`` automatically protects
        any a GCP cites — the retention job doesn't need to know about GCPs; the FK
        does."* That is true of the **guarantee** and not of the **mechanics**: a bulk
        ``DELETE`` that touches even one cited row raises, rolls back, and prunes
        *nothing* — so the sweep would silently do no work forever while looking healthy.
        Excluding cited rows up front makes the statement succeed; the ``RESTRICT`` stays
        the authority, and if this predicate is ever wrong the database refuses rather
        than letting a GCP lose its evidence.

        Returns:
            Rows deleted.
        """
        if days <= 0:
            raise ValueError(f"days must be > 0, got {days}")
        cutoff = func.now() - timedelta(days=days)
        cited = (
            select(GCP.id)
            .where(GCP.match_result_id == MatchResult.id)
            .correlate(MatchResult)
            .exists()
        )
        stmt = delete(MatchResult).where(
            MatchResult.is_selected.is_(False),
            MatchResult.created_at < cutoff,
            ~cited,
        )
        return int((await self._execute(stmt)).rowcount or 0)
