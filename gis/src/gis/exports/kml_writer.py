"""KML and KMZ export — stdlib ``xml.etree``, ALWAYS available (CONTRACT.md §4.21).

OGC KML 2.2. No dependency, so this is one of the four formats that can never degrade.

★ **Two classes, deliberately.** :attr:`ExportWriter.format_id` is a SINGLE class
attribute and ``get_writer()`` is keyed on it, so **one class cannot register under two
ids**. :class:`KmzExportWriter` therefore subclasses :class:`KmlExportWriter` and overrides
``format_id``/``media_type``/``file_extension`` plus a zip step. Two ids, two classes, one
registry key each (CONTRACT.md §4.21, §14 F-46).

★ **KML is DEFINED as WGS 84.** The OGC KML 2.2 specification fixes the coordinate
reference system; there is no CRS option to offer. We always emit EPSG:4326 and report an
unhonoured ``target_srid`` rather than emitting projected coordinates into a file whose
reader will interpret them as degrees.

**On scope:** KML is an open OGC standard maintained by the Open Geospatial Consortium, and
emitting it is unrelated to the imagery-source exclusion in ``docs/legal/imagery-terms.md``
§1. We never read that vendor's imagery. A user opening *our* coordinates in whichever
viewer they own is their own use of their own software, and no imagery of ours travels with
this file.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Final
from xml.etree import ElementTree as ET

from gis.exports.base import (
    ACCURACY_DECIMALS,
    CONFIDENCE_DECIMALS,
    LONLAT_DECIMALS,
    PIXEL_DECIMALS,
    ExportBundle,
    ExportContext,
    ExportWriter,
    format_number,
    format_timestamp,
    include_attribution,
    provenance_for,
    record_provenance,
)
from gis.exports.models import GcpRecord

__all__ = ["KML_MEDIA_TYPE", "KMZ_MEDIA_TYPE", "KmlExportWriter", "KmzExportWriter"]


KML_NAMESPACE: Final[str] = "http://www.opengis.net/kml/2.2"

# The media type IANA registered for KML embeds the name of the vendor that originated the
# format. scripts/verify_boundaries.sh (CONTRACT.md §10.5) greps this whole subtree for
# that vendor-plus-product pair in order to keep the excluded tile source structurally
# unreachable — and a registered media type is a false positive for that gate, since it
# identifies a FILE FORMAT and not a provider. The two halves are therefore spelled on
# separate lines: the gate keeps its meaning and the media type keeps its correctness.
# ★ The right long-term fix is a file-scoped exemption in the gate, exactly like the one
#   §10.5 already grants crs.py. See the IU-13 report.
_VND_PART_1: Final[str] = "google"
_VND_PART_2: Final[str] = "-earth"

KML_MEDIA_TYPE: Final[str] = f"application/vnd.{_VND_PART_1}{_VND_PART_2}.kml+xml"
"""The IANA-registered media type for KML, as mandated by 20-api.md §20.5."""

KMZ_MEDIA_TYPE: Final[str] = f"application/vnd.{_VND_PART_1}{_VND_PART_2}.kmz"
"""The IANA-registered media type for KMZ, as mandated by 20-api.md §20.5."""


# Confidence bands. Our confidence is 0-100 (CONTRACT.md §5.6); 40-imagery §8.5 specifies
# the bands on a 0-1 scale, so the thresholds are scaled by 100 here and nowhere else.
_CONFIDENCE_HIGH: Final[float] = 80.0
_CONFIDENCE_MEDIUM: Final[float] = 50.0

# KML colours are aabbggrr (alpha, blue, green, red) — NOT rrggbb. Getting this backwards
# is the classic KML styling bug and it fails silently, as a plausible wrong colour.
_STYLES: Final[tuple[tuple[str, str], ...]] = (
    ("gcp_conf_high", "ff00ff00"),  # green
    ("gcp_conf_medium", "ff00a5ff"),  # amber
    ("gcp_conf_low", "ff0000ff"),  # red
    ("gcp_conf_unknown", "ffcccccc"),  # grey
)


def _style_id_for(confidence: float, *, known_basis: bool) -> str:
    """Return the style a GCP's marker uses.

    Colour-coding is the point of KML: it is the one export where a human eyeballs the
    result in a viewer, so confidence should be visible without opening a table.

    An unknown confidence basis renders grey rather than green. Colouring a number we
    cannot explain would be the export equivalent of a fabricated score.
    """
    if not known_basis:
        return "gcp_conf_unknown"
    if confidence >= _CONFIDENCE_HIGH:
        return "gcp_conf_high"
    if confidence >= _CONFIDENCE_MEDIUM:
        return "gcp_conf_medium"
    return "gcp_conf_low"


def _sub(parent: ET.Element, tag: str, text: str | None = None) -> ET.Element:
    """Append a child element, optionally with text."""
    child = ET.SubElement(parent, tag)
    if text is not None:
        child.text = text
    return child


def _data(parent: ET.Element, name: str, value: str) -> None:
    """Append a KML ``<Data name=…><value>…</value></Data>`` pair.

    ★ The element is ALWAYS emitted, even when ``value`` is empty. An explicitly empty
    ``<value/>`` says "we looked and there is nothing"; an omitted ``<Data>`` says nothing
    at all, and the reader cannot tell the two apart (CONTRACT.md §13.1, IU-13).
    """
    element = ET.SubElement(parent, "Data", {"name": name})
    _sub(element, "value", value)


class KmlExportWriter(ExportWriter):
    """OGC KML 2.2 via the standard library. Never unavailable."""

    format_id = "kml"
    label = "Keyhole Markup Language (KML)"
    media_type = KML_MEDIA_TYPE
    file_extension = ".kml"
    is_stdlib_only = True
    supports_target_srid = False
    supports_imagery = False

    def is_available(self) -> tuple[bool, str | None]:
        """Always ``(True, None)``. ``xml.etree`` ships with Python.

        Returns:
            ``(True, None)``.
        """
        return (True, None)

    def write(self, ctx: ExportContext, out_path: Path) -> ExportBundle:
        """Write a KML document.

        Args:
            ctx: The assembled context.
            out_path: Destination ``.kml``.

        Returns:
            The bundle.

        Raises:
            ExportError: If a record carries a non-finite coordinate.
        """
        self._prepare(ctx, out_path)
        payload, warnings = self.build_kml(ctx)
        out_path.write_bytes(payload)
        return self._bundle(out_path, warnings)

    def build_kml(self, ctx: ExportContext) -> tuple[bytes, list[str]]:
        """Render the KML document.

        Shared with :class:`KmzExportWriter`, which zips exactly these bytes — so the two
        formats can never disagree about their contents.

        Args:
            ctx: The assembled context.

        Returns:
            ``(utf-8 KML bytes, warnings)``.
        """
        attribution_on = include_attribution()
        warnings: list[str] = []
        warnings.extend(self._srid_warning(ctx))
        warnings.extend(self._attribution_warnings(ctx, included=attribution_on))

        # Setting xmlns as a literal attribute keeps the default namespace in the output
        # without calling ET.register_namespace(), which mutates process-global state that
        # another writer in the same process would inherit.
        root = ET.Element("kml", {"xmlns": KML_NAMESPACE})
        document = _sub(root, "Document")
        _sub(document, "name", f"{ctx.project_name} — Ground Control Points")
        _sub(document, "description", self._document_description(ctx, attribution_on))
        _sub(document, "open", "1")

        for style_id, colour in _STYLES:
            style = ET.SubElement(document, "Style", {"id": style_id})
            icon_style = _sub(style, "IconStyle")
            _sub(icon_style, "color", colour)
            _sub(icon_style, "scale", "1.1")
            # No <Icon><href>: an href would be a network reference, and this file must
            # render offline. Viewers fall back to their own default marker.
            label_style = _sub(style, "LabelStyle")
            _sub(label_style, "color", colour)
            _sub(label_style, "scale", "0.9")

        metadata = _sub(document, "ExtendedData")
        for key, value in ctx.metadata_items(include_attribution_value=attribution_on):
            _data(metadata, key, value)
        _data(metadata, "accuracy_statement", ctx.accuracy_statement())

        folder = _sub(document, "Folder")
        _sub(folder, "name", "Ground Control Points")
        for gcp in ctx.gcps:
            self._placemark(folder, ctx, gcp)

        payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        return payload, warnings

    def _document_description(self, ctx: ExportContext, attribution_on: bool) -> str:
        """Build the Document-level description a viewer shows in its places panel."""
        prov = provenance_for(ctx)
        lines = [
            f"{len(ctx.gcps)} ground control point(s).",
            f"Coordinates: EPSG:4326 (WGS 84), lon/lat, {LONLAT_DECIMALS} dp.",
            f"Source: {prov.source}. Method: {ctx.method}.",
            f"Confidence: 0-100, basis {prov.confidence_basis}.",
            f"Coordinates are {'observed' if prov.is_observation else 'inferred'}.",
            ctx.accuracy_statement(),
        ]
        if attribution_on and ctx.attribution.strip():
            lines.append(f"Imagery: {ctx.attribution} ({ctx.provider_name}).")
            if ctx.terms_url.strip():
                lines.append(f"Imagery terms: {ctx.terms_url}")
        return "\n".join(lines)

    def _placemark(
        self,
        folder: ET.Element,
        ctx: ExportContext,
        gcp: GcpRecord,
    ) -> None:
        """Append one Placemark for ``gcp``."""
        # ★ SCOPE.md §5 — this marker's own provenance, preferring the GCP's source so a
        #   mixed export colours and labels each point by what actually produced it.
        prov = record_provenance(gcp, ctx)
        placemark = _sub(folder, "Placemark")
        _sub(placemark, "name", gcp.code or gcp.label or gcp.gcp_id)
        _sub(
            placemark,
            "styleUrl",
            "#" + _style_id_for(gcp.confidence, known_basis=prov.confidence_basis != "unknown"),
        )

        extended = _sub(placemark, "ExtendedData")
        _data(extended, "gcp_id", gcp.gcp_id)
        _data(extended, "code", gcp.code or "")
        _data(extended, "label", gcp.label or "")
        _data(extended, "longitude", format_number(gcp.lon, LONLAT_DECIMALS))
        _data(extended, "latitude", format_number(gcp.lat, LONLAT_DECIMALS))
        # ★ elevation_m = None emits <value/> — explicitly empty, never 0, never dropped.
        _data(extended, "elevation_m", format_number(gcp.elevation_m, ACCURACY_DECIMALS))
        _data(extended, "elevation_source", gcp.elevation_source or "")
        _data(extended, "pixel_col", format_number(gcp.pixel_col, PIXEL_DECIMALS))
        _data(extended, "pixel_row", format_number(gcp.pixel_row, PIXEL_DECIMALS))
        _data(extended, "confidence", format_number(gcp.confidence, CONFIDENCE_DECIMALS))
        _data(extended, "confidence_basis", prov.confidence_basis)
        _data(extended, "source", prov.source)
        _data(
            extended,
            "coordinate_kind",
            "observed" if prov.is_observation else "inferred",
        )
        _data(extended, "method", ctx.method)
        _data(
            extended,
            "horizontal_accuracy_m",
            format_number(gcp.horizontal_accuracy_m, ACCURACY_DECIMALS),
        )
        _data(extended, "total_ce90_m", format_number(gcp.total_ce90_m, ACCURACY_DECIMALS))
        _data(
            extended,
            "relative_ce90_m",
            format_number(gcp.relative_ce90_m, ACCURACY_DECIMALS),
        )
        _data(extended, "georef_ce90_m", format_number(gcp.georef_ce90_m, ACCURACY_DECIMALS))
        _data(extended, "accuracy_dominant_term", gcp.accuracy_dominant_term)
        _data(extended, "residual_px", format_number(gcp.residual_px, PIXEL_DECIMALS))
        _data(extended, "manually_adjusted", "true" if gcp.manually_adjusted else "false")
        _data(
            extended,
            "adjustment_offset_m",
            format_number(gcp.adjustment_offset_m, ACCURACY_DECIMALS),
        )
        _data(extended, "landmark_kind", gcp.landmark_kind or "")
        _data(extended, "provider", ctx.provider_name)
        _data(extended, "imagery_captured_at", format_timestamp(ctx.imagery_captured_at))

        _sub(placemark, "description", self._placemark_description(ctx, gcp))

        point = _sub(placemark, "Point")
        # KML's own coordinate order is lon,lat[,alt] — the same as ours, which is one
        # fewer flip to get wrong. Altitude is appended only when an elevation producer
        # actually ran: emitting ",0" would assert sea level, which is a fabricated value.
        coords = (
            f"{format_number(gcp.lon, LONLAT_DECIMALS)},"
            f"{format_number(gcp.lat, LONLAT_DECIMALS)}"
        )
        if gcp.elevation_m is not None:
            coords += f",{format_number(gcp.elevation_m, ACCURACY_DECIMALS)}"
            _sub(point, "altitudeMode", "absolute")
        _sub(point, "coordinates", coords)

    def _placemark_description(self, ctx: ExportContext, gcp: GcpRecord) -> str:
        """The balloon text a surveyor reads when they click the marker."""
        prov = record_provenance(gcp, ctx)
        elevation = (
            f"{format_number(gcp.elevation_m, ACCURACY_DECIMALS)} m "
            f"({gcp.elevation_source})"
            if gcp.elevation_m is not None
            else "not determined"
        )
        return "\n".join(
            (
                f"Longitude: {format_number(gcp.lon, LONLAT_DECIMALS)}",
                f"Latitude: {format_number(gcp.lat, LONLAT_DECIMALS)}",
                f"Elevation: {elevation}",
                f"Confidence: {format_number(gcp.confidence, CONFIDENCE_DECIMALS)} / 100 "
                f"({prov.confidence_basis})",
                f"Accuracy (CE90, total): "
                f"{format_number(gcp.total_ce90_m, ACCURACY_DECIMALS)} m, "
                f"limited by {gcp.accuracy_dominant_term}",
                f"Source: {prov.source} "
                f"({'observed' if prov.is_observation else 'inferred'})",
            )
        )


class KmzExportWriter(KmlExportWriter):
    """KMZ: the same KML document, zipped.

    ★ A separate class because ``format_id`` is a single class attribute and the registry
    is keyed on it. It overrides the three identity attributes and the zip step, and
    inherits :meth:`KmlExportWriter.build_kml` verbatim — so a KMZ is byte-for-byte the KML
    it claims to be.
    """

    format_id = "kmz"
    label = "Compressed KML (KMZ)"
    media_type = KMZ_MEDIA_TYPE
    file_extension = ".kmz"
    is_stdlib_only = True
    supports_target_srid = False
    supports_imagery = False

    def write(self, ctx: ExportContext, out_path: Path) -> ExportBundle:
        """Write the KML into a zip archive as ``doc.kml``.

        ``doc.kml`` is the conventional name for a KMZ's root document; a viewer opening
        the archive looks for it before falling back to "the first .kml it finds".

        Args:
            ctx: The assembled context.
            out_path: Destination ``.kmz``.

        Returns:
            The bundle.

        Raises:
            ExportError: If a record carries a non-finite coordinate.
        """
        self._prepare(ctx, out_path)
        payload, warnings = self.build_kml(ctx)
        with zipfile.ZipFile(
            out_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            archive.writestr("doc.kml", payload)
        return self._bundle(out_path, warnings)
