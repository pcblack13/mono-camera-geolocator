"""``cameras`` — :class:`CameraRepository` (async, the API) and
:class:`SyncCameraRepository` (the boot reconciliation thread).

Plain CRUD over a registry table. The one query worth a comment is ``list_with_desire``:
the boot reconciliation wants every camera whose ``desired`` says anything — a JSONB
containment/existence filter — so the API's session never has to page the whole
registry from a background thread.
"""

from __future__ import annotations

from typing import Any, Sequence

from sqlalchemy import Select, or_, select, text

from app.core.pagination import PaginationParams, SortParams
from app.db.repositories.base import (
    BaseRepository,
    BaseSyncRepository,
    SortableColumns,
    like_escape,
)
from app.models.camera import Camera

__all__ = ["CameraRepository", "SyncCameraRepository"]


class CameraRepository(BaseRepository[Camera]):
    """The registered fixed cameras."""

    model = Camera

    @property
    def _sortable(self) -> SortableColumns:
        return {
            "name": Camera.name,
            "created_at": Camera.created_at,
            "updated_at": Camera.updated_at,
        }

    async def list_cameras(
        self,
        *,
        pagination: PaginationParams,
        sort: SortParams,
        q: str | None = None,
    ) -> tuple[Sequence[Camera], int]:
        stmt: Select[Any] = select(Camera)
        if q:
            pattern = f"%{like_escape(q)}%"
            stmt = stmt.where(
                or_(
                    Camera.name.ilike(pattern, escape="\\"),
                    Camera.source.ilike(pattern, escape="\\"),
                    Camera.data_source.ilike(pattern, escape="\\"),
                )
            )
        return await self.page(stmt, pagination, sort, self._sortable)

    async def all_cameras(self) -> Sequence[Camera]:
        """Every camera, by name — the registry is small (a site has tens of cameras,
        not thousands) and the globe wants all of them at once."""
        return await self._scalars(select(Camera).order_by(Camera.name, Camera.id))

    async def find_by_source(self, source: str) -> Camera | None:
        return await self._scalar_one_or_none(
            select(Camera).where(Camera.source == source).order_by(Camera.created_at).limit(1)
        )


class SyncCameraRepository(BaseSyncRepository[Camera]):
    """The reconciliation thread's view — sync engine, NullPool, read-mostly."""

    model = Camera

    def list_with_desire(self) -> Sequence[Camera]:
        """Cameras whose ``desired`` records anything to restore."""
        stmt = (
            select(Camera)
            .where(
                text(
                    "jsonb_typeof(desired->'watch') = 'object'"
                    " OR jsonb_typeof(desired->'detect') = 'object'"
                    " OR desired->>'feed' = 'true'"
                )
            )
            .order_by(Camera.name, Camera.id)
        )
        return self._scalars(stmt)


def desired_of(camera: Camera) -> dict[str, Any]:
    """The row's ``desired`` as a plain dict (never None)."""
    return dict(camera.desired or {})
