"""DXF export — ezdxf, DEGRADES (CONTRACT.md §4.21).

DXF is the CAD interchange format. It is the one export in this package with **no concept
of a coordinate reference system**: a DXF holds bare numbers and the drawing's unit is
whatever the two parties agreed offline. That has one blunt consequence, and this writer
refuses to hide it:

★ **EPSG:4326 degrees are not a CAD unit.** Dropping lon/lat into a DXF produces a drawing
in which one "unit" is ~111 km north-south and a latitude-dependent distance east-west, so
every measurement a draughtsman takes off it is wrong. This writer honours
``ctx.target_srid`` (reprojecting via :mod:`gis.crs`), and when the target is 4326 it emits
the file the caller asked for **and warns loudly**, because silently substituting a
projected CRS would be a different kind of lie.

★ **Call-time bound** (§11.3): ``ezdxf`` is imported inside :meth:`DxfExportWriter.write`.
:mod:`gis.crs` is imported there too — it is in the base install, but it reaches for pyproj
or osgeo, and there is no reason to pay that on ``import gis.exports``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

from gis.errors import CrsError, ExportError
from gis.exports.base import (
    ExportBundle,
    ExportContext,
    ExportWriter,
    include_attribution,
    missing_dependency_reason,
    provenance_for,
    record_provenance,
)
from gis.exports.models import GcpRecord

__all__ = ["LAYER_ANNOTATION", "LAYER_LABELS", "LAYER_POINTS", "DxfExportWriter"]


LAYER_POINTS: Final[str] = "GCP_POINTS"
LAYER_LABELS: Final[str] = "GCP_LABELS"
LAYER_ANNOTATION: Final[str] = "GCP_METADATA"

# ACI colour indices, banded to match the KML writer so one export does not contradict
# another about the same point.
_ACI_GREEN: Final[int] = 3
_ACI_YELLOW: Final[int] = 2
_ACI_RED: Final[int] = 1
_ACI_GREY: Final[int] = 8
_ACI_WHITE: Final[int] = 7

_CONFIDENCE_HIGH: Final[float] = 80.0
_CONFIDENCE_MEDIUM: Final[float] = 50.0

_INSUNITS_UNITLESS: Final[int] = 0
_INSUNITS_METERS: Final[int] = 6


def _colour_for(confidence: float, *, known_basis: bool) -> int:
    """Return the ACI colour for a confidence value."""
    if not known_basis:
        return _ACI_GREY
    if confidence >= _CONFIDENCE_HIGH:
        return _ACI_GREEN
    if confidence >= _CONFIDENCE_MEDIUM:
        return _ACI_YELLOW
    return _ACI_RED


class DxfExportWriter(ExportWriter):
    """AutoCAD DXF R2010: a POINT per GCP on ``GCP_POINTS``, a TEXT label on ``GCP_LABELS``."""

    format_id = "dxf"
    label = "AutoCAD DXF"
    media_type = "image/vnd.dxf"
    file_extension = ".dxf"
    is_stdlib_only = False
    supports_target_srid = True
    supports_imagery = False

    def is_available(self) -> tuple[bool, str | None]:
        """Report whether ``ezdxf`` can be bound here.

        Returns:
            ``(True, None)`` or ``(False, "requires ezdxf")``. Never raises, never imports.
        """
        missing = missing_dependency_reason("ezdxf")
        if missing is not None:
            return (False, missing)
        return (True, None)

    def write(self, ctx: ExportContext, out_path: Path) -> ExportBundle:
        """Write the DXF drawing.

        Args:
            ctx: The assembled context.
            out_path: Destination ``.dxf``.

        Returns:
            The bundle. ``warnings`` always says which CRS the numbers are in, because the
            file itself cannot.

        Raises:
            ExportError: If ``ezdxf`` is absent, or the requested ``target_srid`` cannot be
                reached with the CRS backends available here.
        """
        self._prepare(ctx, out_path)

        # ★ CALL-TIME BINDING (§11.3).
        import ezdxf

        attribution_on = include_attribution()
        warnings: list[str] = []
        warnings.extend(self._attribution_warnings(ctx, included=attribution_on))

        xs, ys, srid, projected = self._coordinates(ctx, warnings)

        doc = ezdxf.new(dxfversion="R2010", setup=True)
        doc.header["$INSUNITS"] = _INSUNITS_METERS if projected else _INSUNITS_UNITLESS

        # Custom document properties: the closest thing DXF has to a metadata block, and
        # the only place a CAD user can read the provenance without opening the drawing.
        for key, value in ctx.metadata_items(include_attribution_value=attribution_on):
            if value:
                # DXF custom property names are capped well below this; keep them short and
                # let the METADATA layer carry the full text.
                doc.header.custom_vars.append(key[:32], value[:255])
        doc.header.custom_vars.append("coordinate_srid", f"EPSG:{srid}")

        for layer, colour in (
            (LAYER_POINTS, _ACI_WHITE),
            (LAYER_LABELS, _ACI_WHITE),
            (LAYER_ANNOTATION, _ACI_GREY),
        ):
            doc.layers.add(name=layer, color=colour)

        msp = doc.modelspace()
        label_height = self._label_height(projected)

        if any(gcp.elevation_m is None for gcp in ctx.gcps):
            warnings.append(
                "DXF requires a Z ordinate on every POINT. GCPs whose elevation was never "
                "determined were written at Z=0; that zero is a placeholder demanded by "
                "the format, NOT a measured height. Export GeoPackage or GeoJSON if you "
                "need to tell an unknown elevation from sea level."
            )

        for index, gcp in enumerate(ctx.gcps):
            # ★ SCOPE.md §5 — colour this point by ITS OWN confidence basis: a row whose
            #   source we cannot explain renders grey rather than borrowing the export's.
            prov = record_provenance(gcp, ctx)
            colour = _colour_for(
                gcp.confidence, known_basis=prov.confidence_basis != "unknown"
            )
            # NOT `gcp.elevation_m or 0.0`: a genuine 0.0 m (sea level) is falsy, and that
            # expression would silently reclassify a measured height as a placeholder.
            z = 0.0 if gcp.elevation_m is None else float(gcp.elevation_m)
            msp.add_point(
                (xs[index], ys[index], z),
                dxfattribs={"layer": LAYER_POINTS, "color": colour},
            )
            text = msp.add_text(
                self._label_for(gcp),
                height=label_height,
                dxfattribs={"layer": LAYER_LABELS, "color": colour},
            )
            text.set_placement((xs[index] + label_height, ys[index] + label_height))

        self._add_metadata_block(msp, ctx, srid, attribution_on, label_height)

        doc.saveas(out_path)
        return self._bundle(out_path, warnings)

    # ── internals ───────────────────────────────────────────────────────────

    def _coordinates(
        self, ctx: ExportContext, warnings: list[str]
    ) -> tuple[list[float], list[float], int, bool]:
        """Return ``(xs, ys, srid, is_projected)`` for the drawing.

        Raises:
            ExportError: If the requested reprojection cannot be performed. Refusing beats
                writing a CAD drawing full of coordinates in the wrong system (L12).
        """
        lons = [gcp.lon for gcp in ctx.gcps]
        lats = [gcp.lat for gcp in ctx.gcps]

        if ctx.target_srid == 4326:
            warnings.append(
                "★ This DXF holds EPSG:4326 coordinates, whose units are DEGREES, not "
                "metres. Distances, areas and angles measured in CAD from this drawing "
                "will be wrong. Re-export with target_srid set to a projected coordinate "
                "reference system (typically the local UTM zone) for a measurable drawing."
            )
            return (lons, lats, 4326, False)

        if not lons:
            return ([], [], ctx.target_srid, True)

        # Call-time: gis.crs reaches for pyproj/osgeo and there is no reason to pay that
        # cost on `import gis.exports`.
        import numpy as np

        from gis.crs import transform_points

        try:
            xs_arr, ys_arr = transform_points(
                np.asarray(lons, dtype=float),
                np.asarray(lats, dtype=float),
                "EPSG:4326",
                f"EPSG:{ctx.target_srid}",
            )
        except CrsError as exc:
            raise ExportError(
                f"cannot write a DXF in EPSG:{ctx.target_srid}: {exc}. Install pyproj, or "
                "export in EPSG:4326 and accept degree units."
            ) from exc

        warnings.append(
            f"DXF coordinates were reprojected from EPSG:4326 to EPSG:{ctx.target_srid}. "
            "DXF cannot record a coordinate reference system; it is stored in the "
            "drawing's custom properties and stated here."
        )
        return (list(xs_arr), list(ys_arr), ctx.target_srid, True)

    def _label_height(self, projected: bool) -> float:
        """Return a text height that is legible in the drawing's own units.

        2 m in a projected drawing; ~2e-5 degrees is the same distance in a 4326 one. A
        single hardcoded height would render labels either invisible or kilometres tall
        depending on the CRS.
        """
        return 2.0 if projected else 2.0 / 111_320.0

    def _label_for(self, gcp: GcpRecord) -> str:
        """Return the on-drawing label: the code, else the label, else the id."""
        return gcp.code or gcp.label or gcp.gcp_id

    def _add_metadata_block(
        self,
        msp: Any,
        ctx: ExportContext,
        srid: int,
        attribution_on: bool,
        label_height: float,
    ) -> None:
        """Write the provenance as MTEXT on the metadata layer.

        Placed in the drawing itself, not only in the header: a CAD user plots the sheet,
        and the attribution is a licence condition that must survive the plot.
        """
        prov = provenance_for(ctx)
        lines = [
            f"{ctx.project_name} — Ground Control Points",
            f"Coordinates: EPSG:{srid}",
            f"Source: {prov.source} · Method: {ctx.method}",
            f"Coordinates are {'observed' if prov.is_observation else 'inferred'}",
            f"Confidence: 0-100, basis {prov.confidence_basis}",
            f"Generated: {ctx.generated_at.isoformat()} by LandExplorer {ctx.software_version}",
        ]
        if attribution_on and ctx.attribution.strip():
            lines.append(f"Imagery: {ctx.attribution} ({ctx.provider_name})")
            if ctx.terms_url.strip():
                lines.append(f"Imagery terms: {ctx.terms_url}")
        lines.append(ctx.accuracy_statement())

        mtext = msp.add_mtext(
            r"\P".join(lines),
            dxfattribs={"layer": LAYER_ANNOTATION, "char_height": label_height},
        )
        mtext.set_location((0.0, 0.0))
