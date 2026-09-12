"""Exports (§6.2) — endpoints 58–63.

★ **SCOPE.md §3: exports are BUILT, in full** — CSV, GeoJSON, Shapefile, KML,
PDF (plus KMZ, GPKG, DXF). With matching deferred, the export IS the deliverable
handoff: the surveyor's manual GCPs leave the system through here.

★ **SCOPE.md §5: "Uncommitted correspondences must never appear in the GCP table
or an export."** That is upheld structurally rather than by a filter default —
an uncommitted correspondence is never written to ``gcps`` at all (see
``gcp.GcpManualCreate``), so there is nothing here to exclude. A filter that had
to remember to exclude them would be a filter that eventually forgets.

★ :class:`ExportFilter` carries ``source`` for the *other* half of that
sentence: SCOPE.md §5 requires that an automatic GCP *"can never be confused with
an observed one … in an export"*.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from .common import ApiModel, ListParams, WarningItem
from .enums import CoordinateFormat, ExportFormat, GcpSource, JobStatus

__all__ = [
    "EXPORT_SORT_FIELDS",
    "CsvExportOptions",
    "DxfExportOptions",
    "ExportFilter",
    "ExportListParams",
    "ExportOptions",
    "ExportRead",
    "ExportRequest",
    "ExportSummary",
    "KmlExportOptions",
    "PdfExportOptions",
    "ShapefileExportOptions",
]

EXPORT_SORT_FIELDS = frozenset({"created_at", "format", "status", "size_bytes"})


class CsvExportOptions(ApiModel):
    """★ The mandated GCP columns: Point ID · Image X · Image Y · Latitude ·
    Longitude · Confidence (+ elevation, accuracy, and ``source``).
    """

    delimiter: Literal[",", ";", "\t"] = ","
    include_header: bool = True
    coordinate_format: CoordinateFormat = CoordinateFormat.DD
    decimals: int = Field(
        default=8,
        ge=0,
        le=12,
        description=(
            "★ **Full precision is ALWAYS available in the export.** The UI's "
            "decimal truncation (§8.7) is a DISPLAY policy — a decimal digit IS a "
            "claim about accuracy, and a screen should not claim 1 mm on 3 m "
            "imagery — but the file is the record, and truncating the record "
            "loses data that cannot be recovered. Nothing is lost here."
        ),
    )


class ShapefileExportOptions(ApiModel):
    """★ The ``.dbf`` 10-character field-name problem is handled by
    ``gis.exports.fieldmap.FieldNameMapper``, not by asking the client to
    pre-truncate.
    """

    target_srid: int = Field(default=4326, ge=1024, le=32767)
    encoding: str = "UTF-8"


class KmlExportOptions(ApiModel):
    """KML/KMZ. ★ ``include_photo_overlay`` is gated by the provider's
    ``allows_derivative_export`` — a ToS question, not a preference.
    """

    include_photo_overlay: bool = False
    icon_scale: float = Field(default=1.0, gt=0.0, le=10.0)


class DxfExportOptions(ApiModel):
    """DXF, for the CAD handoff."""

    target_srid: int = Field(default=4326, ge=1024, le=32767)
    layer_name: str = Field(default="GCP", max_length=64)


class PdfExportOptions(ApiModel):
    """The report. ★ ``include_accuracy_table`` defaults **true**: a GCP report
    without its error budget is a list of numbers pretending to be a survey.
    """

    include_map: bool = True
    include_photo: bool = True
    include_accuracy_table: bool = True
    title: str | None = Field(default=None, max_length=200)
    author: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=4000)


class ExportOptions(ApiModel):
    """Per-format options, plus the one that applies to all of them.

    ★ A flat bag keyed by format rather than a discriminated union: an
    ``ExportRead`` echoes back what was *requested*, and a client that switches
    format in the dialog should not lose the CSV settings it already typed.
    """

    csv: CsvExportOptions | None = None
    shapefile: ShapefileExportOptions | None = None
    kml: KmlExportOptions | None = None
    dxf: DxfExportOptions | None = None
    pdf: PdfExportOptions | None = None
    target_srid: int = Field(
        default=4326,
        ge=1024,
        le=32767,
        description="Reprojection happens server-side in gis.crs. TRUE metres, always.",
    )


class ExportFilter(ApiModel):
    """Which GCPs go in the file.

    ★ **Persisted with the export** so "regenerate this export" is reproducible —
    and so a stale export whose ``gcp_count`` disagrees with today's GCP count is
    **detectable**, which is exactly the audit question a surveyor asks: *"is the
    file I sent the client still current?"*
    """

    gcp_ids: list[UUID] | None = Field(
        default=None, description="An explicit set. Null -> everything matching the rest."
    )
    match_result_id: UUID | None = None
    source: GcpSource | None = Field(
        default=None,
        description=(
            "★★ SCOPE.md §5: an automatic GCP must never be confused with an "
            "observed one in an export. In this build every row is 'manual', so "
            "this filter is a no-op today and a guarantee tomorrow — which is "
            "the point of building the seam now."
        ),
    )
    confidence__gte: float | None = Field(default=None, ge=0.0, le=100.0)
    manually_adjusted: bool | None = None
    include_stale: bool = Field(
        default=False,
        description=(
            "★ Default FALSE. A stale GCP is one the system has said it can no "
            "longer justify; shipping it in a deliverable by default would make "
            "the staleness flag decorative."
        ),
    )
    only_included_in_export: bool = True


class ExportRequest(ApiModel):
    """``POST /images/{image_id}/export`` (58) · ``POST /projects/{id}/export`` (59)."""

    format: ExportFormat
    image_id: UUID | None = Field(default=None, description="Null => a whole-project export.")
    filter: ExportFilter = Field(default_factory=ExportFilter)
    options: ExportOptions = Field(default_factory=ExportOptions)
    acknowledge_low_confidence: bool = Field(
        default=False,
        description=(
            "★ **Required when the set contains low-confidence points** (§8.5.3) "
            "-> else 422. Every output format carries the confidence column plus "
            "a `low_confidence: true` flag, and the PDF report gets a full-width "
            "warning block on page 1.\n\n"
            "★ SCOPE.md §5 sharpens this rather than softening it: a manual GCP's "
            "confidence is the surveyor's OWN declared judgement, so this "
            "acknowledgement asks them to confirm they meant to ship points they "
            "themselves marked uncertain."
        ),
    )


class ExportRead(ApiModel):
    """``ExportRead`` — endpoints 60, 61."""

    id: UUID
    project_id: UUID
    image_id: UUID | None
    format: ExportFormat
    status: JobStatus = Field(
        description="Reuses JobStatus values — exports.status IS the job_status PG enum."
    )
    cancel_requested: bool
    download_url: str | None = Field(
        default=None,
        description=(
            "Null until succeeded. ★ `storage_path` itself is NEVER serialised — "
            "it is a server-controlled path and exposing it leaks the storage "
            "layout."
        ),
    )
    filename: str | None
    size_bytes: int | None
    checksum_sha256: str | None
    gcp_count: int | None
    target_srid: int
    options: ExportOptions
    filter: ExportFilter
    warnings: list[WarningItem] = Field(default_factory=list)
    error_message: str | None
    requested_by: str | None
    expires_at: datetime | None = Field(
        default=None,
        description=(
            "★ After this the download is **410 EXPORT_EXPIRED** — gone, not "
            "missing. A 404 would say the export never existed; it did, and the "
            "surveyor may have its URL in an email."
        ),
    )
    created_at: datetime
    updated_at: datetime


class ExportSummary(ApiModel):
    """List projection — endpoint 60."""

    id: UUID
    format: ExportFormat
    status: JobStatus
    filename: str | None
    size_bytes: int | None
    gcp_count: int | None
    download_url: str | None
    expires_at: datetime | None
    created_at: datetime


class ExportListParams(ListParams):
    """``GET /exports`` — endpoint 60."""

    project_id: UUID | None = None
    image_id: UUID | None = None
    format: str | None = Field(default=None, description="CSV of ExportFormat.")
    status: str | None = Field(default=None, description="CSV of JobStatus.")
