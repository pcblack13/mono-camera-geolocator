"""``render_export_task`` — REAL GCP export rendering (SCOPE.md §3).

A manual GCP set is a real deliverable, and this is how it leaves the system. ``Export`` IS
the job row, so ``job_id`` and ``export_id`` are the same UUID. The task:

* collects the **committed** GCPs the export's filter selects (uncommitted correspondences
  were never written, so they cannot leak in — SCOPE.md §5);
* assembles an :class:`gis.exports.base.ExportContext` — ``method="assisted"``, because in
  this build every coordinate is a manual observation, and the writer's generated accuracy
  statement says exactly that;
* renders through the format's ``gis.exports`` writer (CSV/GeoJSON/KML/KMZ never degrade;
  Shapefile/PDF/DXF are dropped from ``/capabilities`` when their optional dep is absent);
* stores the artefact and records it on the row **before** the job is marked ``succeeded``
  (the ``ck_exports_succeeded_has_path`` constraint enforces that order — an export that
  claims success with no file is a download link that 404s).

★ **Reads and the artefact-record write go through the async repositories** (the single
home of ``select()``) via the :func:`~app.tasks.base.run_async` bridge; the writers and
storage are synchronous. The one place this task reaches past a repository method is
extracting each GCP's lon/lat with ``ST_X``/``ST_Y`` — there is no repository accessor for
it and no GCP→``GcpRecord`` adapter in this build; ideally that select lives in
``GcpRepository`` and this is a one-method move when it does.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from celery import shared_task

from app import __version__ as APP_VERSION
from app.core.config import get_settings
from app.core.constants import JobStage
from app.core.logging import get_logger
from app.db.session import get_sessionmaker
from app.models.enums import JobType
from app.storage import get_storage, keys
from app.tasks.base import BaseJobTask, job_lifecycle, run_async
from app.tasks.celery_app import TASK_RENDER_EXPORT

__all__ = ["render_export_task"]

log = get_logger(__name__)


@shared_task(bind=True, base=BaseJobTask, name=TASK_RENDER_EXPORT)
def render_export_task(self: Any, job_id: str, export_id: str) -> None:
    """Render one export to a file and record it. See module docstring.

    Args:
        job_id: The ``exports`` row id (the export IS the job).
        export_id: The same id, carried in the payload for symmetry with the other tasks.
    """
    from gis.exports import get_writer

    with job_lifecycle(self, JobType.EXPORT, job_id) as ctx:
        eid = uuid.UUID(str(export_id))
        settings = get_settings()

        ctx.progress.set_stage(JobStage.COLLECTING_GCPS)
        collected = run_load_export(eid)
        if collected is None:
            log.warning("export.row_missing", export_id=str(eid))
            return
        ctx.progress.advance(0.8)

        ctx.progress.set_stage(JobStage.REPROJECTING)
        context = _build_context(collected, eid)

        ctx.progress.set_stage(JobStage.RENDERING)
        writer = get_writer(collected.export_format)
        available, reason = writer.is_available()
        if not available:
            # The format was writable when requested; its dependency has since gone. Fail
            # with the honest reason rather than a stack trace.
            raise RuntimeError(
                f"export format {collected.export_format!r} is not available: {reason}"
            )

        with _temp_out(writer.file_extension) as out_path:
            bundle = writer.write(context, out_path)

            ctx.progress.set_stage(JobStage.WRITING)
            storage = get_storage()
            key = keys.export_key(collected.project_id, eid, bundle.filename)
            with open(bundle.path, "rb") as fh:
                storage.put(key, fh, content_type=bundle.media_type)

        expires_at = (
            datetime.now(UTC) + timedelta(seconds=settings.export_ttl_seconds)
            if settings.export_ttl_seconds > 0
            else None
        )
        run_record_artifact(
            eid,
            storage_path=key,
            filename=bundle.filename,
            size_bytes=bundle.size_bytes,
            checksum_sha256=bundle.checksum_sha256,
            gcp_count=len(collected.gcps),
            warnings=list(bundle.warnings),
            expires_at=expires_at,
        )
        log.info(
            "export.rendered",
            export_id=str(eid),
            format=collected.export_format,
            gcp_count=len(collected.gcps),
            size_bytes=bundle.size_bytes,
        )


# ── collection (async bridge) ─────────────────────────────────────────────────


@dataclass(slots=True)
class _Collected:
    gcps: list[Any]  # list[gis.exports.models.GcpRecord]
    project_name: str
    image_filename: str | None
    project_id: uuid.UUID
    export_format: str
    target_srid: int
    coordinate_format: str = "dd"


def run_load_export(export_id: uuid.UUID) -> _Collected | None:
    """Load the export, its GCP records and the names needed for the context header."""
    from sqlalchemy import cast, func, select
    from geoalchemy2 import Geometry

    from gis.exports.models import GcpRecord

    from app.db.repositories.exports import ExportRepository
    from app.db.repositories.gcps import GcpRepository
    from app.db.repositories.images import ImageRepository
    from app.db.repositories.projects import ProjectRepository
    from app.models.gcp import GCP

    async def _collect() -> _Collected | None:
        factory = get_sessionmaker()
        async with factory() as session:
            export = await ExportRepository(session).get(export_id)
            if export is None:
                return None

            flt = export.filter or {}
            source = flt.get("source")
            confidence_gte = flt.get("confidence__gte")
            include_stale = bool(flt.get("include_stale", False))

            rows = await GcpRepository(session).list_for_export(
                image_id=export.image_id,
                project_id=None if export.image_id is not None else export.project_id,
                source=source,
                confidence_gte=confidence_gte,
                include_stale=include_stale,
            )

            # lon/lat is the one value not on the ORM row (it is a geography WKB). One
            # extra query resolves it for the whole set.
            lonlat: dict[uuid.UUID, tuple[float, float]] = {}
            ids = [g.id for g in rows]
            if ids:
                geom = cast(GCP.geom, Geometry())
                coord_rows = await session.execute(
                    select(GCP.id, func.ST_X(geom), func.ST_Y(geom)).where(GCP.id.in_(ids))
                )
                for gid, lon, lat in coord_rows.all():
                    lonlat[gid] = (float(lon), float(lat))

            # The GCP's "Name" is the LINKED LANDMARK's label (e.g. "P1"), which lives on the
            # annotations table, not the GCP row — exactly what the UI table shows. Resolve it
            # for the whole set so the CSV/export Name column matches the screen.
            from app.models.annotation import Annotation

            labels: dict[uuid.UUID, str | None] = {}
            landmark_ids = [g.landmark_id for g in rows if getattr(g, "landmark_id", None) is not None]
            if landmark_ids:
                label_rows = await session.execute(
                    select(Annotation.id, Annotation.label).where(Annotation.id.in_(landmark_ids))
                )
                for aid, label in label_rows.all():
                    labels[aid] = label

            project = await ProjectRepository(session).get(export.project_id)
            project_name = project.name if project is not None else str(export.project_id)

            image_filename: str | None = None
            if export.image_id is not None:
                image = await ImageRepository(session).get(export.image_id)
                image_filename = image.filename if image is not None else None

            records = [
                _to_record(
                    GcpRecord,
                    g,
                    lonlat.get(g.id, (0.0, 0.0)),
                    labels.get(getattr(g, "landmark_id", None)),
                )
                for g in rows
            ]
            csv_opts = (export.options or {}).get("csv") or {}
            return _Collected(
                gcps=records,
                project_name=project_name,
                image_filename=image_filename,
                project_id=export.project_id,
                export_format=str(getattr(export.format, "value", export.format)),
                target_srid=int(export.target_srid),
                coordinate_format=str(csv_opts.get("coordinate_format") or "dd"),
            )

    return run_async(_collect)


def _to_record(
    GcpRecord: type, g: Any, lonlat: tuple[float, float], label: str | None = None
) -> Any:
    """Map a ``GCP`` ORM row to a ``gis.exports.models.GcpRecord`` (the writers' input).

    ``label`` is the linked landmark's name, resolved by the caller — the GCP row itself has
    none.
    """
    lon, lat = lonlat
    return GcpRecord(
        gcp_id=str(g.id),
        code=g.code,
        # The GCP's own free-text name wins; otherwise the linked landmark's label.
        label=getattr(g, "name", None) or label,
        lon=lon,
        lat=lat,
        elevation_m=g.elevation_m,
        pixel_col=float(g.pixel_x),
        pixel_row=float(g.pixel_y),
        satellite_pixel_x=float(g.satellite_pixel_x) if g.satellite_pixel_x is not None else 0.0,
        satellite_pixel_y=float(g.satellite_pixel_y) if g.satellite_pixel_y is not None else 0.0,
        confidence=float(g.confidence),
        source=g.source,
        horizontal_accuracy_m=g.accuracy_total_ce90_m,
        total_ce90_m=float(g.accuracy_total_ce90_m),
        relative_ce90_m=float(g.accuracy_relative_ce90_m),
        georef_ce90_m=float(g.georef_ce90_m),
        accuracy_dominant_term=g.accuracy_dominant_term,
        residual_px=g.residual_px,
        manually_adjusted=bool(g.manually_adjusted),
        adjustment_offset_m=g.adjustment_offset_m,
        landmark_kind=getattr(g, "landmark_kind", None),
        elevation_source=g.elevation_source,
    )


# ── context assembly (sync) ───────────────────────────────────────────────────


def _build_context(collected: _Collected, export_id: uuid.UUID) -> Any:
    """Assemble the :class:`ExportContext`. ``method='assisted'`` — manual observations."""
    from gis.exports.base import ExportContext

    from app.services.imagery_service import ImageryService

    settings = get_settings()
    provider = ImageryService(settings).resolve(None)
    caps = provider.capabilities()

    # ★ chip is None: this build has no stored satellite mosaic to draw a figure from, and a
    # provider that forbids derivative export would force None anyway. The PDF writer omits
    # its map figure and SAYS SO in the bundle warnings — it never draws something else.
    return ExportContext(
        export_id=export_id,
        job_id=export_id,
        project_name=collected.project_name,
        image_filename=collected.image_filename,
        gcps=collected.gcps,
        chip=None,
        provider_name=provider.name,
        attribution=provider.attribution,
        terms_url=provider.terms_url,
        imagery_captured_at=None,
        retrieved_at=datetime.now(UTC),
        method="assisted",
        homography=None,
        rmse_m=None,
        georef_ce90_m=caps.georef_ce90_m,
        target_srid=collected.target_srid,
        software_version=APP_VERSION,
        coordinate_format=collected.coordinate_format,
    )


# ── artefact record (async bridge) ────────────────────────────────────────────


def run_record_artifact(
    export_id: uuid.UUID,
    *,
    storage_path: str,
    filename: str,
    size_bytes: int,
    checksum_sha256: str,
    gcp_count: int,
    warnings: list[str],
    expires_at: datetime | None,
) -> None:
    """Record the rendered file on the export row — BEFORE ``mark_succeeded`` (§ constraint).

    ``set_artifact`` writes the path/size/checksum/gcp_count; the warnings (a truncated
    field, an omitted map figure) are written alongside so the UI can surface them. The
    lifecycle's clean-exit ``mark_succeeded`` then flips the status, in that order.
    """
    from sqlalchemy import update

    from app.db.repositories.exports import ExportRepository
    from app.models.export import Export

    async def _record() -> None:
        factory = get_sessionmaker()
        async with factory() as session:
            await ExportRepository(session).set_artifact(
                export_id,
                storage_path=storage_path,
                filename=filename,
                size_bytes=size_bytes,
                checksum_sha256=checksum_sha256,
                gcp_count=gcp_count,
                expires_at=expires_at,
            )
            if warnings:
                await session.execute(
                    update(Export)
                    .where(Export.id == export_id)
                    .values(warnings=[{"code": "EXPORT_WARNING", "message": w} for w in warnings])
                )
            await session.commit()

    run_async(_record)


# ── helpers ───────────────────────────────────────────────────────────────────


class _TempOut:
    """A temp output path with the writer's extension, cleaned up on exit."""

    __slots__ = ("_ext", "_path")

    def __init__(self, ext: str) -> None:
        self._ext = ext
        self._path = ""

    def __enter__(self) -> Path:
        fd, self._path = tempfile.mkstemp(suffix=self._ext, prefix="le_export_")
        os.close(fd)
        return Path(self._path)

    def __exit__(self, *exc: Any) -> None:
        try:
            if self._path and os.path.exists(self._path):
                os.unlink(self._path)
        except OSError:
            pass


def _temp_out(ext: str) -> _TempOut:
    return _TempOut(ext)
