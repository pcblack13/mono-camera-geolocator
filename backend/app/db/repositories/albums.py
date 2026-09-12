"""``albums`` — :class:`AlbumRepository`.

★ **Membership is Core SQL, not a relationship append.** ``Album.projects`` and
``Project.albums`` are both ``lazy="raise"``, so neither can be mutated by loading it —
and that is the point: adding a project to an album must be **idempotent** (adding twice
is not an error), and the honest way to say that in SQL is
``INSERT … ON CONFLICT DO NOTHING`` against the composite primary key. Loading the
collection, checking membership in Python and appending is a lost-update race with a
concurrent add, and it costs a full collection load to write one 32-byte row.

★ **Nothing here can delete a project.** The only DELETE in this module targets
``album_projects``. Deleting the album itself is a soft delete of one row in ``albums``;
the members are untouched by construction, not by care.
"""

from __future__ import annotations

import uuid
from typing import Any, Sequence

from sqlalchemy import Select, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.pagination import PaginationParams, SortParams
from app.db.repositories.base import BaseRepository, SortableColumns, like_escape
from app.models.album import Album, album_projects
from app.models.project import Project

__all__ = ["AlbumRepository"]


def _project_count_subquery() -> Any:
    """``project_count`` — a correlated scalar subquery, not a column.

    ``ALBUM_SORT_FIELDS`` whitelists ``project_count`` and ``albums`` has no such column:
    it is a count over ``album_projects``. **Only this layer can make that mapping**,
    which is why the sort map lives in the repository and the whitelist in the schema —
    the same split ``ProjectRepository._image_count_subquery`` uses.

    ★ Soft-deleted projects are excluded, so the number a client sorts by is the number
    the client is shown when it opens the album.
    """
    return (
        select(func.count())
        .select_from(album_projects)
        .join(Project, Project.id == album_projects.c.project_id)
        .where(album_projects.c.album_id == Album.id, Project.deleted_at.is_(None))
        .correlate(Album)
        .scalar_subquery()
    )


class AlbumRepository(BaseRepository[Album]):
    """User-defined collections of projects. Holds many; owns none."""

    model = Album

    @property
    def _sortable(self) -> SortableColumns:
        """``ALBUM_SORT_FIELDS`` resolved onto SQL."""
        return {
            "name": Album.name,
            "created_at": Album.created_at,
            "updated_at": Album.updated_at,
            "project_count": _project_count_subquery(),
        }

    # ── reads ────────────────────────────────────────────────────────────────

    async def get_active(self, album_id: uuid.UUID) -> Album | None:
        """One album, excluding soft-deleted rows. The default read."""
        return await self._scalar_one_or_none(
            select(Album).where(Album.id == album_id, Album.deleted_at.is_(None))
        )

    async def list_albums(
        self,
        *,
        pagination: PaginationParams,
        sort: SortParams,
        q: str | None = None,
        include_deleted: bool = False,
    ) -> tuple[Sequence[Album], int]:
        """``GET /albums``.

        Args:
            pagination: Validated limit/offset.
            sort: Whitelisted against ``ALBUM_SORT_FIELDS``.
            q: Free-text over ``name`` + ``description``.
            include_deleted: Include soft-deleted albums.

        Returns:
            ``(rows, total)``. ``project_count`` is **not** on the rows — the caller
            fetches it for the whole page with :meth:`project_counts`.
        """
        stmt: Select[Any] = select(Album)
        if not include_deleted:
            stmt = stmt.where(Album.deleted_at.is_(None))
        if q:
            pattern = f"%{like_escape(q)}%"
            stmt = stmt.where(
                or_(
                    Album.name.ilike(pattern, escape="\\"),
                    Album.description.ilike(pattern, escape="\\"),
                )
            )
        return await self.page(stmt, pagination, sort, self._sortable)

    async def project_counts(
        self, album_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, int]:
        """``AlbumSummary.project_count`` for many albums in **one** query.

        The list endpoint renders a count per row; a per-row query is a page-sized
        round-trip storm, and ``Album.projects`` is ``lazy="raise"`` so the N+1 cannot
        sneak in through the relationship either.

        Returns:
            ``{album_id: count}``. Albums with no projects are **absent**; the caller
            defaults them to 0.
        """
        if not album_ids:
            return {}
        stmt = (
            select(album_projects.c.album_id, func.count())
            .select_from(album_projects)
            .join(Project, Project.id == album_projects.c.project_id)
            .where(
                album_projects.c.album_id.in_(list(album_ids)),
                Project.deleted_at.is_(None),
            )
            .group_by(album_projects.c.album_id)
        )
        return {aid: int(count) for aid, count in (await self._execute(stmt)).all()}

    async def albums_for_projects(
        self, project_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, list[tuple[uuid.UUID, str]]]:
        """``ProjectSummary.albums`` for many projects in **one** query.

        ★ The reverse lookup, and the reason ``ix_album_projects_project`` exists: the
        composite PK leads on ``album_id``, so "which albums is this project in?" has no
        usable prefix in it.

        Ordered by album name so the chips on a project row render in a stable order —
        a set rendered in whatever order the join returned changes between page loads
        for no reason the user can see.

        Args:
            project_ids: The projects to look up. Empty ⇒ ``{}``, no query.

        Returns:
            ``{project_id: [(album_id, album_name), ...]}``. Projects in no album are
            **absent**; the caller defaults them to ``[]``. Soft-deleted albums are
            excluded — a project must not advertise membership of a collection the user
            has deleted.
        """
        if not project_ids:
            return {}
        stmt = (
            select(album_projects.c.project_id, Album.id, Album.name)
            .select_from(album_projects)
            .join(Album, Album.id == album_projects.c.album_id)
            .where(
                album_projects.c.project_id.in_(list(project_ids)),
                Album.deleted_at.is_(None),
            )
            .order_by(album_projects.c.project_id.asc(), Album.name.asc(), Album.id.asc())
        )
        out: dict[uuid.UUID, list[tuple[uuid.UUID, str]]] = {}
        for project_id, album_id, name in (await self._execute(stmt)).all():
            out.setdefault(project_id, []).append((album_id, name))
        return out

    # ── membership — both operations idempotent ──────────────────────────────

    async def add_project(self, album_id: uuid.UUID, project_id: uuid.UUID) -> bool:
        """Put a project in an album. **Idempotent** — adding twice is not an error.

        ``INSERT … ON CONFLICT (album_id, project_id) DO NOTHING``. One statement, so
        two concurrent adds cannot both pass a "is it already there?" check and then
        both insert; the composite primary key decides, and the loser simply does
        nothing.

        Returns:
            True when this call actually created the membership, False when it already
            existed. The router answers ``204`` either way — the caller asked for the
            project to be in the album, and it is — but the service and the tests can
            still tell the two apart.
        """
        stmt = (
            pg_insert(album_projects)
            .values(album_id=album_id, project_id=project_id)
            .on_conflict_do_nothing(index_elements=["album_id", "project_id"])
            .returning(album_projects.c.album_id)
        )
        return (await self._execute(stmt)).scalar_one_or_none() is not None

    async def remove_project(self, album_id: uuid.UUID, project_id: uuid.UUID) -> bool:
        """Take a project out of an album. **Idempotent.**

        ★ Deletes the *membership*, never the member. This is the only DELETE in this
        module and it names ``album_projects`` explicitly.

        Returns:
            True when a membership was removed, False when there was none.
        """
        stmt = (
            delete(album_projects)
            .where(
                album_projects.c.album_id == album_id,
                album_projects.c.project_id == project_id,
            )
            .returning(album_projects.c.album_id)
        )
        return (await self._execute(stmt)).scalar_one_or_none() is not None

    # ── writes ───────────────────────────────────────────────────────────────

    async def soft_delete(self, album_id: uuid.UUID) -> bool:
        """Set ``deleted_at``. Idempotent — a second call matches nothing.

        ★ The album's projects are untouched, and so are its membership rows: the album
        is recoverable *with* its contents. Freeing the name is handled by
        ``uq_albums_name_lower``'s ``WHERE deleted_at IS NULL``.
        """
        stmt = (
            update(Album)
            .where(Album.id == album_id, Album.deleted_at.is_(None))
            .values(deleted_at=func.now())
            .returning(Album.id)
        )
        return (await self._execute(stmt)).scalar_one_or_none() is not None

    async def restore(self, album_id: uuid.UUID) -> bool:
        """Clear ``deleted_at``. Idempotent."""
        stmt = (
            update(Album)
            .where(Album.id == album_id, Album.deleted_at.isnot(None))
            .values(deleted_at=None)
            .returning(Album.id)
        )
        return (await self._execute(stmt)).scalar_one_or_none() is not None
