"""``heatmap_service`` — fronts the DEFERRED confidence heatmap.

★ SCOPE.md §4: the confidence heatmap over candidate camera locations is an ABC only. The
*run* path (``POST /images/{id}/heatmap``, endpoint) raises
:class:`~app.core.exceptions.FeatureDeferredError` → ``501`` + ``feature: "deferred"``.

The read is real against the empty ``confidence_heatmaps`` / ``confidence_heatmap_cells``
tables. A photograph with no heatmap is a
:class:`~app.core.exceptions.HeatmapNotAvailable` (404), distinct from the 501.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import FeatureDeferredError
from app.db.repositories.heatmaps import HeatmapRepository

__all__ = ["HeatmapService"]

_COMPONENT = "ai_engine.heatmap.posterior"
_DEFERRED_MESSAGE = (
    "The confidence heatmap is not enabled in this build — it is part of the deferred "
    "automatic matching engine. Place GCPs manually."
)


class HeatmapService:
    """Confidence heatmap — deferred run path, real reads."""

    def __init__(self, session: AsyncSession) -> None:
        self._repo = HeatmapRepository(session)

    def compute(self, image_id: uuid.UUID, *args: object, **kwargs: object) -> None:
        """``POST /images/{id}/heatmap`` — **DEFERRED** (501)."""
        raise FeatureDeferredError(_DEFERRED_MESSAGE, component=_COMPONENT)

    async def get_latest_for_image(self, image_id: uuid.UUID):
        """``GET /images/{id}/heatmap`` — real; None in this build."""
        return await self._repo.get_latest_for_image(image_id)

    async def get_latest_for_image_or_raise(self, image_id: uuid.UUID):
        """The heatmap or ``HeatmapNotAvailable`` (404). Empty in this build."""
        return await self._repo.get_latest_for_image_or_raise(image_id)
