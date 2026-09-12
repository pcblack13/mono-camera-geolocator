"""``gis.exports`` — the export writers and THE registry (CONTRACT.md §4.21, §9.9).

★ **The registry lives HERE**, not in a ``registry.py``. §9.9's consumer column reads
``gis.exports``.

★ **This module eagerly imports all eight writers**, which is exactly the collection path
that module-scope optional imports break. It works because every writer binds its optional
dependency INSIDE the function that uses it (§11.3): with ``geopandas``, ``fiona``,
``ezdxf`` and ``reportlab`` all absent — the state of the machine this was written on —
``import gis.exports`` succeeds, :func:`available_formats` answers, and only an actual
:meth:`ExportWriter.write` on a degraded format raises.

**CSV, GeoJSON, KML and KMZ are stdlib-only and can NEVER degrade**, so the surveyor can
always get their coordinates out, regardless of environment. That is not an accident of
implementation; it is why the four most important formats were built on the standard
library.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from gis.errors import ExportError
from gis.exports.base import (
    ExportBundle,
    ExportContext,
    ExportFormatInfo,
    ExportMethod,
    ExportProvenance,
    ExportWriter,
    enabled_format_ids,
    provenance_for,
    record_provenance,
)
from gis.exports.csv_writer import CsvExportWriter
from gis.exports.dxf_writer import DxfExportWriter
from gis.exports.fieldmap import FieldNameMapper
from gis.exports.geojson_writer import GeoJsonExportWriter
from gis.exports.gpkg_writer import GpkgExportWriter
from gis.exports.kml_writer import KmlExportWriter, KmzExportWriter
from gis.exports.models import GcpRecord
from gis.exports.pdf_writer import PdfReportWriter
from gis.exports.shapefile_writer import ShapefileExportWriter

__all__ = [
    "EXPORT_WRITERS",
    "CsvExportWriter",
    "DxfExportWriter",
    "ExportBundle",
    "ExportContext",
    "ExportFormatInfo",
    "ExportMethod",
    "ExportProvenance",
    "ExportWriter",
    "FieldNameMapper",
    "GcpRecord",
    "GeoJsonExportWriter",
    "GpkgExportWriter",
    "KmlExportWriter",
    "KmzExportWriter",
    "PdfReportWriter",
    "ShapefileExportWriter",
    "available_formats",
    "get_writer",
    "provenance_for",
    "record_provenance",
]


EXPORT_WRITERS: Final[dict[str, Callable[[], ExportWriter]]] = {
    "csv": CsvExportWriter,
    "geojson": GeoJsonExportWriter,
    "kml": KmlExportWriter,
    # ★ KMZ is a DIFFERENT class, not the same class under a second key. `format_id` is a
    #   single class attribute and get_writer() is keyed on it, so one class physically
    #   cannot register under two ids (§14 F-46).
    "kmz": KmzExportWriter,
    "shapefile": ShapefileExportWriter,
    "gpkg": GpkgExportWriter,
    "dxf": DxfExportWriter,
    "pdf": PdfReportWriter,
}
"""THE export registry. Explicit, in version control, no entry-point autodiscovery — the
same reasoning that governs the imagery providers (§11.5): a format that can appear by
being pip-installed is a format nobody reviewed.

Insertion order is the order the UI lists them: the four that can never fail first."""


def get_writer(format_id: str) -> ExportWriter:
    """Return a fresh writer for ``format_id``.

    ★ **Availability is the CALLER's check**, via :meth:`ExportWriter.is_available`. This
    function succeeds for a known format whose dependency is missing, so the API can answer
    *"Shapefile export requires fiona"* with a considered response instead of 500-ing from
    inside a writer.

    Args:
        format_id: A key of :data:`EXPORT_WRITERS`, e.g. ``"kmz"``. Case-insensitive.

    Returns:
        A new writer instance.

    Raises:
        ExportError: If ``format_id`` is not registered. The message names the known ids —
            an unknown format is a caller bug or a typo'd config, and both are cheaper to
            fix when the error says what was available.
    """
    key = format_id.strip().lower()
    factory = EXPORT_WRITERS.get(key)
    if factory is None:
        known = ", ".join(sorted(EXPORT_WRITERS))
        raise ExportError(f"unknown export format {format_id!r}; known formats: {known}")
    return factory()


def available_formats() -> list[ExportFormatInfo]:
    """Report every export format, with a truthful availability answer for THIS machine.

    Backs ``GET /capabilities``' export list. ★ Unavailable formats are RETURNED with
    ``available=False`` and a ``reason``, not omitted: the UI greys the option and shows
    *"requires fiona"* as a tooltip, which is a better answer than the option silently not
    existing (§4.21). Deciding to hide them is the caller's prerogative, not ours.

    Formats the operator has excluded via ``LE_EXPORT_FORMATS`` are omitted entirely —
    that is a deliberate configuration, not a degradation.

    Returns:
        One :class:`ExportFormatInfo` per enabled format, in registry order. Never raises,
        never imports an optional dependency.
    """
    enabled = enabled_format_ids()
    infos: list[ExportFormatInfo] = []
    for format_id, factory in EXPORT_WRITERS.items():
        if format_id not in enabled:
            continue
        infos.append(factory().format_info())
    return infos
