"""``project_service`` — survey projects: the owner of images, revisions, exports.

CRUD orchestration over ``ProjectRepository``, plus the two guards that are policy rather
than SQL: a soft-delete is refused while the project has a live job
(``PROJECT_HAS_ACTIVE_JOBS``), and a name collision under ``LE_PROJECT_NAMES_UNIQUE`` is a
``PROJECT_NAME_CONFLICT`` rather than a 500.
"""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ProjectHasActiveJobs, ProjectNameConflict, ProjectNotFound
from app.core.pagination import PaginationParams, SortParams
from app.db.repositories.base import constraint_name_of
from app.db.repositories.images import ImageRepository
from app.db.repositories.jobs import JobRepository
from app.db.repositories.projects import ProjectRepository
from app.db.repositories.videos import VideoRepository
from app.models.project import Project
from app.schemas.project import ProjectCreate, ProjectUpdate

__all__ = ["ProjectService"]


class ProjectService:
    """Create, read, list, update and soft-delete projects."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._projects = ProjectRepository(session)
        self._jobs = JobRepository(session)
        self._images = ImageRepository(session)
        self._videos = VideoRepository(session)

    # ── reads ─────────────────────────────────────────────────────────────────

    async def get(self, project_id: uuid.UUID, *, include_deleted: bool = False) -> Project:
        """One project, or ``ProjectNotFound``."""
        project = (
            await self._projects.get(project_id)
            if include_deleted
            else await self._projects.get_active(project_id)
        )
        if project is None:
            raise ProjectNotFound(f"No project {project_id}.")
        return project

    async def list(
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
        """``GET /projects`` (5). ``album_id`` narrows to one album's members."""
        return await self._projects.list_projects(
            pagination=pagination,
            sort=sort,
            owner_id=owner_id,
            q=q,
            tags=tags,
            bbox=bbox,
            album_id=album_id,
            include_deleted=include_deleted,
        )

    async def image_counts(self, project_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
        """``ProjectSummary.image_count`` for many projects, batched."""
        return await self._projects.image_counts(project_ids)

    # ── writes ────────────────────────────────────────────────────────────────

    async def create(self, body: ProjectCreate, *, owner_id: str | None = None) -> Project:
        """``POST /projects`` (4). ``{"name": "x"}`` alone is a valid project."""
        project = Project(
            name=body.name,
            description=body.description,
            owner_id=owner_id,
            aoi=_aoi_to_wkt(body.aoi),
            default_provider=body.default_provider.value,
            default_extractor=body.default_extractor.value,
            default_matcher=body.default_matcher.value,
            default_estimator=body.default_estimator.value,
            default_search_radius_m=body.default_search_radius_m,
            default_search_zoom=body.default_search_zoom,
            tags=list(body.tags),
            meta=getattr(body, "metadata", None) or {},
        )
        self._projects.add(project)
        await self._flush_mapping_name_conflict(project.name)
        return project

    async def update(self, project_id: uuid.UUID, body: ProjectUpdate) -> Project:
        """``PATCH /projects/{id}`` — only the sent fields change; ``{"aoi": null}`` clears."""
        project = await self.get(project_id)
        changed = body.changed_fields()

        for field in (
            "name",
            "description",
            "default_search_radius_m",
            "default_search_zoom",
        ):
            if field in changed:
                setattr(project, field, getattr(body, field))
        for field in (
            "default_provider",
            "default_extractor",
            "default_matcher",
            "default_estimator",
        ):
            if field in changed:
                value = getattr(body, field)
                if value is not None:  # these are not nullable — clearing is meaningless
                    setattr(project, field, value.value)
        if "tags" in changed and body.tags is not None:
            project.tags = list(body.tags)
        if "aoi" in changed:
            project.aoi = _aoi_to_wkt(body.aoi)
        if "metadata" in changed:
            project.meta = getattr(body, "metadata", None) or {}

        await self._flush_mapping_name_conflict(project.name)
        # ★ Reload the row before anyone reads it back. `updated_at` is maintained by a
        #   DB trigger (`server_onupdate` — models/mixins.py), so after the UPDATE flush
        #   SQLAlchemy holds an EXPIRED attribute; the router then touches it to build
        #   the ETag, and an expired-attribute load in an ASYNC session is implicit sync
        #   IO → MissingGreenlet → a bare 500 on every PATCH (the "Could not save the
        #   project settings" field report). An explicit refresh is async-safe, and it
        #   also makes the returned ETag carry the trigger's REAL new timestamp instead
        #   of the stale pre-update one.
        await self._session.refresh(project)
        return project

    async def soft_delete(self, project_id: uuid.UUID) -> bool:
        """``DELETE /projects/{id}`` — refused while a job is live.

        Raises:
            ProjectNotFound: no such active project.
            ProjectHasActiveJobs: the project has a running/queued job (409). Destroying it
                mid-export would orphan the artifact and confuse the job panel.
        """
        await self.get(project_id)  # 404 if absent
        # Clear orphaned jobs (recorded but never submitted to the broker — the residue of a
        # worker-less upload) so they don't block deletion forever. Genuinely in-flight jobs
        # survive this and still trip the guard below.
        await self._jobs.cancel_never_submitted_for_project(project_id)
        if await self._jobs.has_active_jobs(project_id):
            raise ProjectHasActiveJobs(
                f"Project {project_id} has active jobs; wait for them to finish or cancel "
                "them before deleting it."
            )
        # ★ Cascade the soft-delete to the project's photographs and videos, in this same
        #   transaction. Without it, a deleted project's images/videos stay live — still in
        #   the image list, still counted on the dashboard — because the DB FK does not
        #   cascade a soft-delete. `restore()` re-clears the project's own flag only; the
        #   children stay tombstoned, which is the honest behaviour (a restore brings the
        #   project back empty rather than silently resurrecting deleted media).
        await self._images.soft_delete_all_for_project(project_id)
        await self._videos.soft_delete_all_for_project(project_id)
        return await self._projects.soft_delete(project_id)

    async def restore(self, project_id: uuid.UUID) -> bool:
        """Clear ``deleted_at``. Idempotent."""
        if await self._projects.get(project_id) is None:
            raise ProjectNotFound(f"No project {project_id}.")
        return await self._projects.restore(project_id)

    # ── internals ─────────────────────────────────────────────────────────────

    async def _flush_mapping_name_conflict(self, name: str) -> None:
        """Flush, mapping a unique-name violation to ``PROJECT_NAME_CONFLICT``."""
        try:
            await self._projects.flush()
        except IntegrityError as exc:
            constraint = constraint_name_of(exc)
            if constraint and "name" in constraint:
                raise ProjectNameConflict(
                    f"A project named {name!r} already exists "
                    "(LE_PROJECT_NAMES_UNIQUE is on)."
                ) from exc
            raise


def _aoi_to_wkt(aoi):
    """A ``GeoJsonPolygon`` → a 4326 ``WKTElement`` for the ``geography`` column, or None.

    GeoJSON rings are ``[lon, lat]``, which is exactly WKT's ``x y`` order, so no field
    flip is needed here — unlike the ``LatLon`` point path. ``None`` passes straight
    through, which is how ``PATCH {"aoi": null}`` clears the column.
    """
    if aoi is None:
        return None
    from app.db.types import WGS84_SRID, WKTElement

    rings: list[str] = []
    for ring in aoi.coordinates:
        vertices = ", ".join(f"{position[0]} {position[1]}" for position in ring)
        rings.append(f"({vertices})")
    return WKTElement(f"POLYGON({', '.join(rings)})", srid=WGS84_SRID)
