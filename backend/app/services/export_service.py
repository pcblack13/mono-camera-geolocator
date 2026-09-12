"""``export_service`` — GCP exports: CSV, GeoJSON, Shapefile, KML, PDF, and the rest.

★ SCOPE.md §3: exports are BUILT, in full — a manual GCP set is a real deliverable and
this is how it leaves the system. This service owns the *real* pre-flight + enqueue ladder
(unlike the deferred match path): it de-duplicates against a byte-identical prior export,
creates the ``exports`` job row, and submits ``render_export_task`` through the injected
``JobQueue``. The rendering itself (``gis.exports`` writers) runs in the worker (L5).

★ **Reuse is matched on the WHOLE parameter set** — format, SRID, filter *and* options —
because those determine the bytes (``ExportRepository.find_reusable``). Handing back an
export built from a different filter and telling a surveyor it was theirs is the single
worst thing a deliverable cache can do.
"""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import ExportNotFound
from app.core.pagination import PaginationParams, SortParams
from app.core.queue import JobQueue, JobSpec, NullJobQueue
from app.db.repositories.exports import ExportRepository
from app.models.enums import JobStatus
from app.models.export import Export
from app.schemas.export import ExportRequest

__all__ = ["ExportService", "ExportSubmission"]


class ExportSubmission:
    """The outcome of an export request: the row, and whether it was reused vs enqueued."""

    __slots__ = ("export", "reused")

    def __init__(self, export: Export, *, reused: bool) -> None:
        self.export = export
        self.reused = reused


class ExportService:
    """Create, read and reuse GCP exports."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        queue: JobQueue | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._exports = ExportRepository(session)
        self._queue = queue if queue is not None else NullJobQueue()

    # ── reads ─────────────────────────────────────────────────────────────────

    async def get(self, export_id: uuid.UUID) -> Export:
        export = await self._exports.get(export_id)
        if export is None:
            raise ExportNotFound(f"No export {export_id}.")
        return export

    async def list(
        self,
        *,
        pagination: PaginationParams,
        sort: SortParams,
        project_id: uuid.UUID | None = None,
        image_id: uuid.UUID | None = None,
        status_csv: str | None = None,
    ) -> tuple[Sequence[Export], int]:
        """``GET /exports`` — real."""
        return await self._exports.list_exports(
            pagination=pagination,
            sort=sort,
            project_id=project_id,
            image_id=image_id,
            status_csv=status_csv,
        )

    # ── create ────────────────────────────────────────────────────────────────

    async def create(
        self,
        project_id: uuid.UUID,
        body: ExportRequest,
        *,
        requested_by: str | None = None,
    ) -> ExportSubmission:
        """``POST /images/{id}/export`` (58) · ``POST /projects/{id}/export`` (59).

        Returns a **reused** export when a byte-identical one already exists and has not
        expired; otherwise creates a ``pending`` row and enqueues the render.

        Args:
            project_id: The project scope (from the route).
            body: The validated request — format, filter, options, and the optional
                ``image_id`` that narrows a whole-project export to one photograph.
            requested_by: The principal.
        """
        target_srid = body.options.target_srid
        filter_dict = body.filter.model_dump(mode="json")
        options_dict = body.options.model_dump(mode="json")

        reusable = await self._exports.find_reusable(
            project_id=project_id,
            image_id=body.image_id,
            export_format=body.format,
            target_srid=target_srid,
            filter_=filter_dict,
            options=options_dict,
        )
        if reusable is not None:
            return ExportSubmission(reusable, reused=True)

        export = Export(
            id=uuid.uuid4(),
            project_id=project_id,
            image_id=body.image_id,
            format=body.format,
            filter=filter_dict,
            options=options_dict,
            target_srid=target_srid,
            requested_by=requested_by,
            status=JobStatus.PENDING,
            max_attempts=self._settings.job_max_attempts,
        )
        self._session.add(export)

        spec = JobSpec(
            job_id=export.id,
            job_type="export",
            payload={"export_id": str(export.id)},
            queue="export",
        )
        spec.validate()
        self._queue.submit(spec)
        return ExportSubmission(export, reused=False)
