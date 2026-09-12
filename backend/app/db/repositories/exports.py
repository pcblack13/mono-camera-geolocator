"""``exports`` — :class:`ExportRepository`.

★ **``filter`` is persisted** so "regenerate this export" is reproducible — and so a
stale export whose ``gcp_count`` disagrees with today's GCP count is **detectable**,
which is exactly the audit question a surveyor asks: *"is the file I sent the client
still current?"* :meth:`ExportRepository.is_stale` is that question in SQL.

★ Status transitions go through :class:`~app.db.repositories.jobs.JobRepository` —
``exports`` is one of the four tables in
:data:`~app.db.repositories.jobs.JOB_MODEL_BY_TYPE` and its lifecycle is the same state
machine. **This module owns what is export-shaped**: the artifact, the TTL, the
staleness audit.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Mapping, Sequence

from sqlalchemy import Select, cast, func, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import ColumnElement

from app.core.pagination import PaginationParams, SortParams
from app.db.repositories.base import BaseRepository, SortableColumns, csv_enum_filter
from app.db.types import jsonb_contains
from app.models.enums import ExportFormat, JobStatus
from app.models.export import Export
from app.models.gcp import GCP
from app.models.image import Image

__all__ = ["ExportRepository"]


def _contained_by(
    column: ColumnElement[Any], value: Mapping[str, Any]
) -> ColumnElement[bool]:
    """``column <@ value`` — the direction ``db.types.jsonb_contains`` does not cover.

    ★ The explicit ``cast`` is the whole point, and it is the same one IU-15 spells out
    on ``jsonb_contains``: without it the bound parameter arrives as ``text``, the
    operator does not resolve against ``(jsonb, text)``, and the query **errors** rather
    than quietly using the wrong plan. The two directions together are set equality;
    each alone is not.
    """
    return column.op("<@")(cast(json.dumps(dict(value)), JSONB))


class ExportRepository(BaseRepository[Export]):
    """Rendered deliverables: CSV, GeoJSON, Shapefile, KML, KMZ, PDF, GPKG, DXF."""

    model = Export

    @property
    def _sortable(self) -> SortableColumns:
        """``EXPORT_SORT_FIELDS`` resolved onto SQL."""
        return {
            "created_at": Export.created_at,
            "format": Export.format,
            "status": Export.status,
            "size_bytes": Export.size_bytes,
        }

    # ── reads ────────────────────────────────────────────────────────────────

    async def list_exports(
        self,
        *,
        pagination: PaginationParams,
        sort: SortParams,
        project_id: uuid.UUID | None = None,
        image_id: uuid.UUID | None = None,
        format_csv: str | None = None,
        status_csv: str | None = None,
    ) -> tuple[Sequence[Export], int]:
        """``GET /exports`` (60).

        ★ ``image_id=None`` means a **whole-project** export, so this filter is
        ``== image_id`` and never doubles as "project-wide too". A caller wanting both
        passes ``project_id`` alone.
        """
        stmt: Select[Any] = select(Export)
        if project_id is not None:
            stmt = stmt.where(Export.project_id == project_id)
        if image_id is not None:
            stmt = stmt.where(Export.image_id == image_id)
        formats = csv_enum_filter(format_csv, [m.value for m in ExportFormat])
        if formats:
            stmt = stmt.where(Export.format.in_(formats))
        statuses = csv_enum_filter(status_csv, [m.value for m in JobStatus])
        if statuses:
            stmt = stmt.where(Export.status.in_(statuses))
        return await self.page(stmt, pagination, sort, self._sortable)

    async def find_expired(self, *, limit: int = 500) -> Sequence[Export]:
        """Succeeded exports past their TTL — the beat sweep's work list.

        ``ix_exports_expires`` is partial on exactly this predicate
        (``expires_at IS NOT NULL AND status = 'succeeded'``), so the sweep is an index
        scan rather than a walk of every export ever rendered.

        ★ Returns rows rather than deleting them: the **file** has to go before the row
        does, and only the caller holds the ``ObjectStorage``. Deleting the row first
        would orphan the bytes forever with nothing left pointing at them.
        """
        return await self._scalars(
            select(Export)
            .where(
                Export.expires_at.isnot(None),
                Export.expires_at < func.now(),
                Export.status == JobStatus.SUCCEEDED,
            )
            .order_by(Export.expires_at.asc())
            .limit(limit)
        )

    async def is_stale(self, export_id: uuid.UUID) -> bool | None:
        """★ *"Is the file I sent the client still current?"*

        Compares the export's recorded ``gcp_count`` against the count its **stored
        ``filter``** would select today. This is what persisting ``filter`` buys, and it
        is the whole reason the column exists.

        ★ Only the ``source`` and ``confidence__gte`` keys of the filter are re-applied,
        plus ``is_included_in_export`` and the stale exclusion — the same predicate
        :meth:`GcpRepository.list_for_export` uses. A filter key this method does not
        understand makes the answer **unknowable, not False**: reporting "current" for
        an export we cannot re-select is precisely the confident wrong answer L12
        forbids. Hence the ``None``.

        Returns:
            True when the counts differ (the file is out of date), False when they
            match, and **None when the answer cannot be established** — because
            ``gcp_count`` was never recorded, or the stored filter carries a key this
            audit does not implement.
        """
        export = await self.get(export_id)
        if export is None or export.gcp_count is None:
            return None

        stored: dict[str, Any] = dict(export.filter or {})
        understood = {"source", "confidence__gte", "include_stale"}
        if set(stored) - understood:
            return None

        stmt: Select[Any] = (
            select(func.count())
            .select_from(GCP)
            .where(GCP.is_included_in_export.is_(True))
        )
        if export.image_id is not None:
            stmt = stmt.where(GCP.image_id == export.image_id)
        else:
            stmt = stmt.join(Image, Image.id == GCP.image_id).where(
                Image.project_id == export.project_id, Image.deleted_at.is_(None)
            )
        if stored.get("source") is not None:
            stmt = stmt.where(GCP.source == stored["source"])
        if stored.get("confidence__gte") is not None:
            stmt = stmt.where(GCP.confidence >= stored["confidence__gte"])
        if not stored.get("include_stale", False):
            stmt = stmt.where(GCP.is_stale.is_(False))

        return int(await self._scalar(stmt) or 0) != export.gcp_count

    # ── writes ───────────────────────────────────────────────────────────────

    async def set_artifact(
        self,
        export_id: uuid.UUID,
        *,
        storage_path: str,
        filename: str,
        size_bytes: int,
        checksum_sha256: str | None = None,
        gcp_count: int | None = None,
        expires_at: datetime | None = None,
    ) -> bool:
        """Record the rendered file. ★ **Before** the status becomes ``succeeded``.

        ``ck_exports_succeeded_has_path`` requires ``storage_path`` and ``size_bytes``
        on a succeeded export, so this write must land first and
        ``JobRepository.mark_succeeded`` second. The reverse order is rejected by the
        database — which is the constraint doing exactly its job: an export that claims
        success with no file is a download link that 404s.

        Args:
            export_id: The export.
            storage_path: Server-controlled key. Never serialised to the wire.
            filename: What ``Content-Disposition`` offers.
            size_bytes: File size.
            checksum_sha256: Served on ``X-Checksum-SHA256``.
            gcp_count: How many GCPs went in — the number :meth:`is_stale` audits
                against.
            expires_at: TTL. None ⇒ kept until deleted.

        Returns:
            True when the row was updated.
        """
        values: dict[str, Any] = {
            "storage_path": storage_path,
            "filename": filename,
            "size_bytes": size_bytes,
        }
        if checksum_sha256 is not None:
            values["checksum_sha256"] = checksum_sha256
        if gcp_count is not None:
            values["gcp_count"] = gcp_count
        if expires_at is not None:
            values["expires_at"] = expires_at

        stmt = update(Export).where(Export.id == export_id).values(**values).returning(Export.id)
        return (await self._execute(stmt)).scalar_one_or_none() is not None

    async def find_reusable(
        self,
        *,
        project_id: uuid.UUID,
        image_id: uuid.UUID | None,
        export_format: ExportFormat,
        target_srid: int,
        filter_: dict[str, Any],
        options: dict[str, Any],
    ) -> Export | None:
        """A succeeded, unexpired, byte-identical export to hand back instead of re-rendering.

        ★ Matched on the **whole** parameter set — format, SRID, filter *and* options —
        because those are what determine the bytes. Matching on format alone would serve
        a surveyor an export built from a different filter and tell them it was theirs,
        which is the single worst thing a deliverable cache can do.

        ★ Containment in **both directions**, not ``=``: mutual containment is true set
        equality, whereas JSONB equality is sensitive to how the value was serialised. A
        reuse check that missed because the keys arrived in a different order is merely
        slow; one that matched a *superset* filter would hand over the wrong file.

        Returns:
            The reusable export, most recent first, or None.
        """
        stmt: Select[Any] = select(Export).where(
            Export.project_id == project_id,
            Export.format == export_format,
            Export.target_srid == target_srid,
            Export.status == JobStatus.SUCCEEDED,
            Export.storage_path.isnot(None),
            jsonb_contains(Export.filter, filter_),
            _contained_by(Export.filter, filter_),
            jsonb_contains(Export.options, options),
            _contained_by(Export.options, options),
        )
        stmt = stmt.where(
            Export.image_id == image_id if image_id is not None else Export.image_id.is_(None)
        )
        stmt = stmt.where(
            (Export.expires_at.is_(None)) | (Export.expires_at > func.now())
        )
        return await self._scalar_one_or_none(
            stmt.order_by(Export.created_at.desc()).limit(1)
        )
