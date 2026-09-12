"""``album_service`` — albums: user-defined, **many-to-many** collections of projects.

CRUD orchestration over :class:`~app.db.repositories.albums.AlbumRepository`, plus the
three things that are policy rather than SQL:

1. **Membership requires a live project.** Adding project X to album Y when X does not
   exist is a ``404 PROJECT_NOT_FOUND``, not a dangling row the FK would reject with a
   500 three frames later.
2. **A name collision is a ``409 ALBUM_NAME_CONFLICT``.** ``uq_albums_name_lower`` is
   case-insensitive over live albums; without the mapping it surfaces as an
   ``IntegrityError``.
3. **Deleting an album never deletes a project.** Enforced by the schema, restated here
   because it is the single most important property of this feature: :meth:`soft_delete`
   touches one row in ``albums`` and nothing else.
"""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AlbumNameConflict, AlbumNotFound, ProjectNotFound
from app.core.pagination import PaginationParams, SortParams
from app.db.repositories.albums import AlbumRepository
from app.db.repositories.base import constraint_name_of
from app.db.repositories.projects import ProjectRepository
from app.models.album import Album
from app.models.project import Project
from app.schemas.album import AlbumCreate, AlbumUpdate

__all__ = ["AlbumService"]


class AlbumService:
    """Create, read, list, update and soft-delete albums; add and remove members."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._albums = AlbumRepository(session)
        self._projects = ProjectRepository(session)

    # ── reads ─────────────────────────────────────────────────────────────────

    async def get(self, album_id: uuid.UUID, *, include_deleted: bool = False) -> Album:
        """One album, or ``AlbumNotFound``."""
        album = (
            await self._albums.get(album_id)
            if include_deleted
            else await self._albums.get_active(album_id)
        )
        if album is None:
            raise AlbumNotFound(f"No album {album_id}.")
        return album

    async def list(
        self,
        *,
        pagination: PaginationParams,
        sort: SortParams,
        q: str | None = None,
        include_deleted: bool = False,
    ) -> tuple[Sequence[Album], int]:
        """``GET /albums``."""
        return await self._albums.list_albums(
            pagination=pagination, sort=sort, q=q, include_deleted=include_deleted
        )

    async def project_counts(
        self, album_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, int]:
        """``AlbumSummary.project_count`` for many albums, batched."""
        return await self._albums.project_counts(album_ids)

    async def albums_for_projects(
        self, project_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, list[tuple[uuid.UUID, str]]]:
        """``ProjectSummary.albums`` for a whole page of projects, batched."""
        return await self._albums.albums_for_projects(project_ids)

    async def list_projects(
        self,
        album_id: uuid.UUID,
        *,
        pagination: PaginationParams,
        sort: SortParams,
        include_deleted: bool = False,
    ) -> tuple[Sequence[Project], int]:
        """``GET /albums/{album_id}/projects``.

        ★ Goes through ``ProjectRepository.list_projects(album_id=…)`` — the **same**
        query that serves ``GET /projects?album_id=``. Two hand-written queries for one
        question are two chances to disagree about what an album contains, and the
        symptom (a project visible from one side and not the other) is invisible in
        review.

        Raises:
            AlbumNotFound: no such live album. The 404 precedes the listing, so an empty
                page always means "this album is empty" and never "that album is gone".
        """
        await self.get(album_id)
        return await self._projects.list_projects(
            pagination=pagination,
            sort=sort,
            album_id=album_id,
            include_deleted=include_deleted,
        )

    # ── writes ────────────────────────────────────────────────────────────────

    async def create(self, body: AlbumCreate) -> Album:
        """``POST /albums``. ``{"name": "x"}`` alone is a valid album."""
        album = Album(name=body.name, description=body.description, color=body.color)
        self._albums.add(album)
        await self._flush_mapping_name_conflict(album.name)
        return album

    async def update(self, album_id: uuid.UUID, body: AlbumUpdate) -> Album:
        """``PATCH /albums/{id}`` — only the sent fields change; ``{"color": null}`` clears.

        ★ ``name`` is the one field a ``null`` cannot clear. It is typed
        ``AlbumName | None`` because every PATCH field must be omittable, but an album
        with no name is unrenderable and ``ck_albums_name_nonblank`` refuses it anyway —
        so a sent ``null`` is ignored here rather than turned into a 23514.
        """
        album = await self.get(album_id)
        changed = body.changed_fields()

        if "name" in changed and body.name is not None:
            album.name = body.name
        if "description" in changed:
            album.description = body.description
        if "color" in changed:
            album.color = body.color

        await self._flush_mapping_name_conflict(album.name)
        # ★ ``updated_at`` is maintained by ``tg_albums_set_updated_at``, not the ORM
        #   (§5.4), so after the flush SQLAlchemy holds it EXPIRED — it knows the server
        #   changed it and does not know to what. Reading it in the synchronous presenter
        #   would fire a lazy reload outside the greenlet and raise ``MissingGreenlet``.
        #   The re-read is explicit and awaited here, which is the only honest place for
        #   it: the alternative is a response carrying the pre-update timestamp.
        await self._albums.refresh(album)
        return album

    async def soft_delete(self, album_id: uuid.UUID) -> bool:
        """``DELETE /albums/{id}``. ★ **Does not delete the projects.**

        An album is a view over projects; deleting a view deletes no data. The
        memberships survive too, so restoring the album restores its contents.
        """
        await self.get(album_id)  # 404 if absent
        return await self._albums.soft_delete(album_id)

    async def add_project(self, album_id: uuid.UUID, project_id: uuid.UUID) -> bool:
        """``POST /albums/{id}/projects/{project_id}`` — **idempotent**.

        Returns:
            True when the membership was created by this call, False when it already
            existed. The router answers 204 for both: the caller asked for the project to
            be in the album, and it is.

        Raises:
            AlbumNotFound: no such live album.
            ProjectNotFound: no such live project. Checked here rather than left to the
                FK, so the client gets a 404 naming which id was wrong instead of a 500
                carrying a constraint name.
        """
        await self.get(album_id)
        await self._require_project(project_id)
        return await self._albums.add_project(album_id, project_id)

    async def remove_project(self, album_id: uuid.UUID, project_id: uuid.UUID) -> bool:
        """``DELETE /albums/{id}/projects/{project_id}`` — **idempotent**.

        ★ Removes the *membership*. The project is not touched, and this method has no
        way to touch it.

        The project's existence is **not** required: removing a membership whose project
        was hard-deleted underneath us is exactly the cleanup this call is for, and
        demanding a live project would make it impossible.
        """
        await self.get(album_id)
        return await self._albums.remove_project(album_id, project_id)

    # ── internals ─────────────────────────────────────────────────────────────

    async def _require_project(self, project_id: uuid.UUID) -> Project:
        project = await self._projects.get_active(project_id)
        if project is None:
            raise ProjectNotFound(f"No project {project_id}.")
        return project

    async def _flush_mapping_name_conflict(self, name: str) -> None:
        """Flush, mapping ``uq_albums_name_lower`` to ``ALBUM_NAME_CONFLICT``.

        ★ Only the **named** constraint is mapped; anything else is re-raised untouched.
        Guessing which constraint fired is how a 409 lands on a 500.
        """
        try:
            await self._albums.flush()
        except IntegrityError as exc:
            if constraint_name_of(exc) == "uq_albums_name_lower":
                raise AlbumNameConflict(
                    f"An album named {name!r} already exists (names are unique, "
                    "ignoring case)."
                ) from exc
            raise
