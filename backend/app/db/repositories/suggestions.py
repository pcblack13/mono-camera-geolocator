"""``landmark_suggestions`` — :class:`LandmarkSuggestionRepository`.

★ SCOPE.md §4: automatic landmark suggestion is **deferred** (ABC only) and ``POST
/images/{id}/suggest-landmarks`` returns 501. Per §4 rule 5 the table exists; per the
unit brief this is real code with no writer in this build.

★ **Why suggestions are a separate resource** (ADR-014). Writing AI guesses straight into
``annotations`` would put unreviewed machine output into the surveyor's revision history,
the undo stack, and — via ``is_gcp_candidate`` — the GCP deriver. **A suggestion is a
proposal; an annotation is an assertion by a human.** The boundary between them is
:meth:`LandmarkSuggestionRepository.accept`, and it is the only door.
"""

from __future__ import annotations

import uuid
from typing import Any, Sequence

from sqlalchemy import Select, delete, func, select, update

from app.core.pagination import PaginationParams, SortParams
from app.db.repositories.base import BaseRepository, SortableColumns, csv_enum_filter
from app.models.enums import AnnotationKind, SuggestionStatus
from app.models.suggestion import LandmarkSuggestion

__all__ = ["LandmarkSuggestionRepository"]


class LandmarkSuggestionRepository(BaseRepository[LandmarkSuggestion]):
    """Proposed landmarks, pending a human decision."""

    model = LandmarkSuggestion

    @property
    def _sortable(self) -> SortableColumns:
        """``SUGGESTION_SORT_FIELDS`` resolved onto SQL."""
        return {
            "rank": LandmarkSuggestion.rank,
            "score": LandmarkSuggestion.score,
            "created_at": LandmarkSuggestion.created_at,
            "kind": LandmarkSuggestion.kind,
        }

    async def list_for_image(
        self,
        image_id: uuid.UUID,
        *,
        pagination: PaginationParams,
        sort: SortParams,
        status_csv: str | None = None,
        kind_csv: str | None = None,
        score_gte: float | None = None,
        detector: str | None = None,
    ) -> tuple[Sequence[LandmarkSuggestion], int]:
        """``GET /images/{image_id}/landmark-suggestions`` (44).

        Args:
            image_id: The photograph.
            pagination: Validated limit/offset.
            sort: Whitelisted against ``SUGGESTION_SORT_FIELDS``.
            status_csv: ``?status=pending``. ``ix_landmark_suggestions_image_rank`` is
                partial on ``status = 'pending'``, which is the query the review UI makes
                every time.
            kind_csv: ``?kind=field_corner,tree``.
            score_gte: **0–1** — the detector's own score, never shown as a survey
                confidence. A suggestion has no accuracy, because nothing was measured.
            detector: Which model proposed it.

        Returns:
            ``(rows, total)``.
        """
        stmt: Select[Any] = select(LandmarkSuggestion).where(
            LandmarkSuggestion.image_id == image_id
        )
        statuses = csv_enum_filter(status_csv, [m.value for m in SuggestionStatus])
        if statuses:
            stmt = stmt.where(LandmarkSuggestion.status.in_(statuses))
        kinds = csv_enum_filter(kind_csv, [m.value for m in AnnotationKind])
        if kinds:
            stmt = stmt.where(LandmarkSuggestion.kind.in_(kinds))
        if score_gte is not None:
            stmt = stmt.where(LandmarkSuggestion.score >= score_gte)
        if detector is not None:
            stmt = stmt.where(LandmarkSuggestion.detector == detector)
        return await self.page(stmt, pagination, sort, self._sortable)

    async def get_many_pending(
        self, suggestion_ids: Sequence[uuid.UUID], *, image_id: uuid.UUID
    ) -> dict[uuid.UUID, LandmarkSuggestion]:
        """Load a batch of *pending* suggestions for the accept path.

        ★ Pending-only, and scoped to the image. Accepting an already-accepted
        suggestion would mint a second annotation from one proposal; accepting a
        rejected one would resurrect a decision a human already made. Both are silent
        under a bare id lookup and neither is recoverable once the annotation exists.
        """
        if not suggestion_ids:
            return {}
        rows = await self._scalars(
            select(LandmarkSuggestion).where(
                LandmarkSuggestion.id.in_(list(suggestion_ids)),
                LandmarkSuggestion.image_id == image_id,
                LandmarkSuggestion.status == SuggestionStatus.PENDING,
            )
        )
        return {s.id: s for s in rows}

    async def accept(
        self,
        suggestion_id: uuid.UUID,
        *,
        annotation_id: uuid.UUID,
        decided_by: str | None = None,
    ) -> bool:
        """★ The door: a proposal becomes an assertion by a human.

        A compare-and-set on ``status = 'pending'``, so two reviewers clicking accept on
        one suggestion produce **one** annotation: the loser matches no row and gets
        False, rather than both minting an annotation and the second overwriting
        ``accepted_annotation_id`` so the first annotation is orphaned and invisible.

        ``status`` and ``accepted_annotation_id`` are set in one statement because
        ``ck_landmark_suggestions_accepted`` binds them — an accepted suggestion must
        name the annotation it became.

        Args:
            suggestion_id: The proposal.
            annotation_id: The annotation the caller has **already created** in this
                transaction. Created first, so the FK and the CHECK are both satisfiable
                at this statement.
            decided_by: The principal.

        Returns:
            True when this caller performed the accept.
        """
        stmt = (
            update(LandmarkSuggestion)
            .where(
                LandmarkSuggestion.id == suggestion_id,
                LandmarkSuggestion.status == SuggestionStatus.PENDING,
            )
            .values(
                status=SuggestionStatus.ACCEPTED,
                accepted_annotation_id=annotation_id,
                decided_by=decided_by,
                decided_at=func.now(),
            )
            .returning(LandmarkSuggestion.id)
        )
        return (await self._execute(stmt)).scalar_one_or_none() is not None

    async def reject(
        self,
        suggestion_ids: Sequence[uuid.UUID],
        *,
        image_id: uuid.UUID,
        decided_by: str | None = None,
    ) -> int:
        """Reject pending suggestions. Rejection is a **decision**, and it is recorded.

        The row is kept, not deleted: "the model proposed this and a human said no" is
        the training signal that makes the next model better, and deleting it throws
        that away to save a row.

        Returns:
            How many were rejected. Already-decided ones are skipped.
        """
        if not suggestion_ids:
            return 0
        stmt = (
            update(LandmarkSuggestion)
            .where(
                LandmarkSuggestion.id.in_(list(suggestion_ids)),
                LandmarkSuggestion.image_id == image_id,
                LandmarkSuggestion.status == SuggestionStatus.PENDING,
            )
            .values(
                status=SuggestionStatus.REJECTED,
                decided_by=decided_by,
                decided_at=func.now(),
            )
        )
        return int((await self._execute(stmt)).rowcount or 0)

    async def replace_pending_for_job(
        self, image_id: uuid.UUID, *, suggestions: Sequence[LandmarkSuggestion]
    ) -> int:
        """Clear the undecided proposals for an image and insert a fresh set.

        ★ **Only ``pending`` rows are cleared.** A re-run must not erase the decisions a
        human already made — an accepted suggestion still names the annotation it became
        (``accepted_annotation_id``, ``ON DELETE SET NULL``), and a rejected one is the
        record that a human looked and declined.

        Returns:
            How many suggestions were inserted.
        """
        await self._execute(
            delete(LandmarkSuggestion).where(
                LandmarkSuggestion.image_id == image_id,
                LandmarkSuggestion.status == SuggestionStatus.PENDING,
            )
        )
        if not suggestions:
            return 0
        self.add_all(suggestions)
        await self.flush()
        return len(suggestions)

    async def count_pending(self, image_id: uuid.UUID) -> int:
        """Undecided proposals on an image — the review badge's number."""
        stmt: Select[Any] = (
            select(func.count())
            .select_from(LandmarkSuggestion)
            .where(
                LandmarkSuggestion.image_id == image_id,
                LandmarkSuggestion.status == SuggestionStatus.PENDING,
            )
        )
        return int(await self._scalar(stmt) or 0)
