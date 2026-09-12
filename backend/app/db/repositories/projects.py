"""``projects`` — :class:`ProjectRepository`.

★ :meth:`ProjectRepository.allocate_revision_seq` is the concurrency control for the
entire undo/redo system. It is three lines and it is the most load-bearing SQL in this
file; read its docstring before touching it.
"""

from __future__ import annotations

import uuid
from typing import Any, Sequence

from sqlalchemy import Select, func, or_, select, update

from app.core.pagination import PaginationParams, SortParams
from app.db.repositories.base import (
    BaseRepository,
    SortableColumns,
    bbox_geography,
    like_escape,
)
from app.models.album import album_projects
from app.models.image import Image
from app.models.project import Project

__all__ = ["ProjectRepository"]


def _image_count_subquery() -> Any:
    """``image_count`` — a correlated scalar subquery, not a column.

    ``PROJECT_SORT_FIELDS`` whitelists ``image_count`` and ``projects`` has no such
    column: it is a count over ``images``. **Only this layer can make that mapping**,
    which is precisely why the sort map lives in the repository and the whitelist lives
    in the schema.

    Soft-deleted images are excluded, so the number a client sorts by is the number the
    client is shown.
    """
    return (
        select(func.count(Image.id))
        .where(Image.project_id == Project.id, Image.deleted_at.is_(None))
        .correlate(Project)
        .scalar_subquery()
    )


class ProjectRepository(BaseRepository[Project]):
    """Survey projects: the owner of images, revisions, batches and exports."""

    model = Project

    @property
    def _sortable(self) -> SortableColumns:
        """``PROJECT_SORT_FIELDS`` resolved onto SQL."""
        return {
            "name": Project.name,
            "created_at": Project.created_at,
            "updated_at": Project.updated_at,
            "image_count": _image_count_subquery(),
        }

    # ── reads ────────────────────────────────────────────────────────────────

    async def get_active(self, project_id: uuid.UUID) -> Project | None:
        """One project, excluding soft-deleted rows.

        The default read. ``get()`` (inherited) returns soft-deleted rows too, which is
        what ``?include_deleted=true`` and the restore path want — and nothing else.
        """
        return await self._scalar_one_or_none(
            select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
        )

    async def list_projects(
        self,
        *,
        pagination: PaginationParams,
        sort: SortParams,
        owner_id: str | None = None,
        q: str | None = None,
        tags: Sequence[str] | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        album_id: uuid.UUID | None = None,
        include_deleted: bool = False,
    ) -> tuple[Sequence[Project], int]:
        """``GET /projects`` (5) — and, with ``album_id``, ``GET /albums/{id}/projects``.

        Args:
            pagination: Validated limit/offset.
            sort: Whitelisted against ``PROJECT_SORT_FIELDS``.
            owner_id: The principal's projects. Uses ``ix_projects_owner_active``.
            q: Free-text over ``name`` + ``description``. ``name`` has a trigram GIN
                index (``ix_projects_name_trgm``), which is what makes an unanchored
                ``ILIKE '%foo%'`` a plan rather than a scan.
            tags: **AND**, not OR — every listed tag must be present. ``@>`` is the
                operator ``ix_projects_tags`` (GIN) serves.
            bbox: ``(min_lon, min_lat, max_lon, max_lat)`` — ★ **longitudes first**.
                Matches projects whose AOI intersects the box.
            album_id: Only projects filed in this album. ★ **One query serves both
                directions** — ``GET /projects?album_id=`` and
                ``GET /albums/{id}/projects`` — so the two views can never disagree
                about what an album contains, and neither needs its own sort map. The
                join is against the composite PK's leading column, so it is an index
                scan, and it cannot duplicate a row: ``(album_id, project_id)`` is
                unique.
            include_deleted: Include soft-deleted projects.

        Returns:
            ``(rows, total)``.

        Raises:
            ValueError: a transposed or inverted bbox.
        """
        stmt: Select[Any] = select(Project)
        if not include_deleted:
            stmt = stmt.where(Project.deleted_at.is_(None))
        if owner_id is not None:
            stmt = stmt.where(Project.owner_id == owner_id)
        if q:
            pattern = f"%{like_escape(q)}%"
            stmt = stmt.where(
                or_(
                    Project.name.ilike(pattern, escape="\\"),
                    Project.description.ilike(pattern, escape="\\"),
                )
            )
        if tags:
            stmt = stmt.where(Project.tags.contains(list(tags)))
        if bbox is not None:
            stmt = stmt.where(
                Project.aoi.isnot(None),
                func.ST_Intersects(Project.aoi, bbox_geography(*bbox)),
            )
        if album_id is not None:
            stmt = stmt.join(
                album_projects, album_projects.c.project_id == Project.id
            ).where(album_projects.c.album_id == album_id)
        return await self.page(stmt, pagination, sort, self._sortable)

    async def image_counts(
        self, project_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, int]:
        """``ProjectSummary.image_count`` for many projects in **one** query.

        The list endpoint renders a count per row; a per-row query is a page-sized
        round-trip storm, and every relationship is ``lazy="raise"`` so the N+1 cannot
        sneak in through ``project.images`` either.

        Returns:
            ``{project_id: count}``. Projects with no images are **absent**; the caller
            defaults them to 0.
        """
        if not project_ids:
            return {}
        stmt = (
            select(Image.project_id, func.count(Image.id))
            .where(Image.project_id.in_(list(project_ids)), Image.deleted_at.is_(None))
            .group_by(Image.project_id)
        )
        return {pid: int(count) for pid, count in (await self._execute(stmt)).all()}

    # ── writes ───────────────────────────────────────────────────────────────

    async def allocate_revision_seq(self, project_id: uuid.UUID) -> int:
        """★★ Allocate the next revision number. **This is the undo/redo lock.**

        ::

            UPDATE projects SET current_revision_seq = current_revision_seq + 1
             WHERE id = :id RETURNING current_revision_seq

        **The row-level lock this UPDATE takes _is_ the concurrency control for the
        whole versioning system** (§5.6). Two surveyors editing one project serialise
        here and nowhere else, and each walks away with a distinct, gapless, monotonic
        sequence number.

        ★ It must be called **inside the same transaction** that writes the revision and
        its events. That is not a style note — it is the entire mechanism. The lock is
        held until that transaction commits, so a second allocator blocks rather than
        reading a number the first has taken but not yet used. Allocate in one
        transaction and write in another and you get two revisions claiming one ``seq``,
        which ``uq_project_revisions_project_seq`` will reject — *after* the surveyor's
        edit is lost.

        ★ The read and the increment are one statement for the same reason:
        ``SELECT current_revision_seq`` then ``UPDATE ... SET = :n + 1`` is a lost
        update under concurrency, and the symptom is a revision history with a hole in
        it that nobody notices until a restore replays to the wrong state.

        Returns:
            The newly allocated sequence number. Always ``> 0``, satisfying
            ``ck_project_revisions_seq_pos``.

        Raises:
            ValueError: no such project. A revision for a project that does not exist is
                not a thing this layer will invent an id for.
        """
        stmt = (
            update(Project)
            .where(Project.id == project_id)
            .values(current_revision_seq=Project.current_revision_seq + 1)
            .returning(Project.current_revision_seq)
        )
        seq = (await self._execute(stmt)).scalar_one_or_none()
        if seq is None:
            raise ValueError(f"No project {project_id}; cannot allocate a revision seq.")
        return int(seq)

    async def soft_delete(self, project_id: uuid.UUID) -> bool:
        """Set ``deleted_at``. Idempotent — a second call matches nothing.

        Returns:
            True when this call performed the delete.
        """
        stmt = (
            update(Project)
            .where(Project.id == project_id, Project.deleted_at.is_(None))
            .values(deleted_at=func.now())
            .returning(Project.id)
        )
        return (await self._execute(stmt)).scalar_one_or_none() is not None

    async def restore(self, project_id: uuid.UUID) -> bool:
        """Clear ``deleted_at``. Idempotent."""
        stmt = (
            update(Project)
            .where(Project.id == project_id, Project.deleted_at.isnot(None))
            .values(deleted_at=None)
            .returning(Project.id)
        )
        return (await self._execute(stmt)).scalar_one_or_none() is not None
