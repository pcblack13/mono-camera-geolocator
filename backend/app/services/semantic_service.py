"""``semantic_service`` — fronts DEFERRED semantic segmentation.

★ SCOPE.md §4: semantic detection (field borders, roads, canals, trees, greenhouses,
buildings, water, crop rows) is an ABC only. The *run* path
(``POST /images/{id}/segment``, endpoint 46) raises
:class:`~app.core.exceptions.FeatureDeferredError` → ``501`` + ``feature: "deferred"`` and
enqueues nothing. The reads are real against the empty ``semantic_features`` table.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import FeatureDeferredError
from app.core.pagination import PaginationParams, SortParams
from app.db.repositories.semantics import SemanticFeatureRepository
from app.models.enums import FeatureSpace

__all__ = ["SemanticService"]

_COMPONENT = "ai_engine.semantics"
_DEFERRED_MESSAGE = (
    "Automatic semantic segmentation is not enabled in this build. Place GCPs manually."
)


class SemanticService:
    """Semantic features — deferred run path, real reads."""

    def __init__(self, session: AsyncSession) -> None:
        self._repo = SemanticFeatureRepository(session)

    def segment(self, image_id: uuid.UUID, *args: object, **kwargs: object) -> None:
        """``POST /images/{id}/segment`` (46) — **DEFERRED** (501)."""
        raise FeatureDeferredError(_DEFERRED_MESSAGE, component=_COMPONENT)

    async def list_for_image(
        self,
        image_id: uuid.UUID,
        *,
        pagination: PaginationParams,
        sort: SortParams,
        class_csv: str | None = None,
        space: FeatureSpace | None = None,
        detector: str | None = None,
        confidence_gte: float | None = None,
        match_result_id: uuid.UUID | None = None,
    ):
        """``GET /images/{id}/semantic-features`` (47) — real; empty in this build."""
        return await self._repo.list_for_image(
            image_id,
            pagination=pagination,
            sort=sort,
            class_csv=class_csv,
            space=space,
            detector=detector,
            confidence_gte=confidence_gte,
            match_result_id=match_result_id,
        )
