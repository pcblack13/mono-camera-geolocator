"""``suggestion_service`` — fronts DEFERRED automatic landmark suggestion.

★ SCOPE.md §4: automatic landmark suggestion is an ABC only. The *run* path
(``POST /images/{id}/suggest-landmarks``, endpoint 43) raises
:class:`~app.core.exceptions.FeatureDeferredError` → ``501`` + ``feature: "deferred"``.
It enqueues nothing: a deferred ``suggest_landmarks_task`` would never complete.

The reads and the accept/reject writes are **real** against a schema that simply holds no
rows in this build (``landmark_suggestions``). Accepting a suggestion that does not exist
is an honest 404 from the repository — not a fabricated landmark.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import FeatureDeferredError
from app.core.pagination import PaginationParams, SortParams
from app.db.repositories.suggestions import LandmarkSuggestionRepository

__all__ = ["SuggestionService"]

_COMPONENT = "ai_engine.landmarks.suggest"
_DEFERRED_MESSAGE = (
    "Automatic landmark suggestion is not enabled in this build. Mark landmarks manually "
    "in the photograph and pair them on the map."
)


class SuggestionService:
    """Landmark suggestions — deferred run path, real reads/accept/reject."""

    def __init__(self, session: AsyncSession) -> None:
        self._repo = LandmarkSuggestionRepository(session)

    def suggest(self, image_id: uuid.UUID, *args: object, **kwargs: object) -> None:
        """``POST /images/{id}/suggest-landmarks`` (43) — **DEFERRED** (501)."""
        raise FeatureDeferredError(_DEFERRED_MESSAGE, component=_COMPONENT)

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
    ):
        """``GET /images/{id}/suggestions`` (44) — real; empty in this build."""
        return await self._repo.list_for_image(
            image_id,
            pagination=pagination,
            sort=sort,
            status_csv=status_csv,
            kind_csv=kind_csv,
            score_gte=score_gte,
            detector=detector,
        )

    async def accept(self, suggestion_id: uuid.UUID, **kwargs: object):
        """``POST /suggestions/{id}/accept`` (45) — real; 404 when the row is absent."""
        return await self._repo.accept(suggestion_id, **kwargs)  # type: ignore[arg-type]

    async def reject(self, suggestion_id: uuid.UUID):
        """``POST /suggestions/{id}/reject`` — real; 404 when the row is absent."""
        return await self._repo.reject(suggestion_id)
