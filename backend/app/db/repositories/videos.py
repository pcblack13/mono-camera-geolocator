"""``videos`` — :class:`VideoRepository`.

Mirrors :class:`~app.db.repositories.images.ImageRepository`'s reads and lifecycle: an
active-only ``get``, a filtered+paginated ``list_videos``, a constraint-aware ``insert``
and a soft delete. A video has no ingest status and no dedupe-on-reupload contract, so the
surface is smaller — there is no ``set_status`` and no ``find_by_checksum`` here.
"""

from __future__ import annotations

import uuid
from typing import Any, Sequence

from sqlalchemy import Select, func, select, update
from sqlalchemy.exc import IntegrityError

from app.core.pagination import PaginationParams, SortParams
from app.db.repositories.base import (
    BaseRepository,
    SortableColumns,
    constraint_name_of,
    like_escape,
)
from app.models.video import Video

__all__ = ["VideoRepository"]


class VideoRepository(BaseRepository[Video]):
    """Uploaded field videos — frame sources."""

    model = Video

    @property
    def _sortable(self) -> SortableColumns:
        """``VIDEO_SORT_FIELDS`` resolved onto SQL."""
        return {
            "filename": Video.filename,
            "created_at": Video.created_at,
            "updated_at": Video.updated_at,
            "size_bytes": Video.size_bytes,
            "duration_s": Video.duration_s,
        }

    # ── reads ──────────────────────────────────────────────────────────────────

    async def get_active(self, video_id: uuid.UUID) -> Video | None:
        """One video, excluding soft-deleted rows. The default read."""
        return await self._scalar_one_or_none(
            select(Video).where(Video.id == video_id, Video.deleted_at.is_(None))
        )

    async def list_videos(
        self,
        *,
        pagination: PaginationParams,
        sort: SortParams,
        project_id: uuid.UUID | None = None,
        q: str | None = None,
        include_deleted: bool = False,
    ) -> tuple[Sequence[Video], int]:
        """``GET /videos``.

        Args:
            pagination: Validated limit/offset.
            sort: Whitelisted against ``VIDEO_SORT_FIELDS``.
            project_id: Restrict to one project.
            q: Free-text over ``filename``.
            include_deleted: Include soft-deleted videos.

        Returns:
            ``(rows, total)``.
        """
        stmt: Select[Any] = select(Video)
        if not include_deleted:
            stmt = stmt.where(Video.deleted_at.is_(None))
        if project_id is not None:
            stmt = stmt.where(Video.project_id == project_id)
        if q:
            pattern = f"%{like_escape(q)}%"
            stmt = stmt.where(Video.filename.ilike(pattern, escape="\\"))
        return await self.page(stmt, pagination, sort, self._sortable)

    # ── writes ─────────────────────────────────────────────────────────────────

    async def insert(self, video: Video) -> Video:
        """Stage and flush a video.

        Raises:
            IntegrityError: re-raised untouched for any constraint other than the
                storage-path uniqueness — guessing which one fired is how a 409 lands on
                a 500.
        """
        self.add(video)
        try:
            await self.flush()
        except IntegrityError as exc:
            _ = constraint_name_of(exc)  # named for symmetry with images; none mapped here
            raise
        return video

    async def soft_delete(self, video_id: uuid.UUID) -> bool:
        """Set ``deleted_at``. Idempotent.

        ★ The images already captured from this video are untouched: the FK on
        ``images.source_video_id`` is ``ON DELETE SET NULL`` and applies to a HARD delete,
        not this soft one, so a soft-deleted video's frames keep pointing at it and a
        restore reunites them.
        """
        stmt = (
            update(Video)
            .where(Video.id == video_id, Video.deleted_at.is_(None))
            .values(deleted_at=func.now())
            .returning(Video.id)
        )
        return (await self._execute(stmt)).scalar_one_or_none() is not None

    async def soft_delete_all_for_project(self, project_id: uuid.UUID) -> int:
        """Soft-delete every live video of a project (the project-delete cascade)."""
        stmt = (
            update(Video)
            .where(Video.project_id == project_id, Video.deleted_at.is_(None))
            .values(deleted_at=func.now())
            .returning(Video.id)
        )
        return len((await self._execute(stmt)).scalars().all())
