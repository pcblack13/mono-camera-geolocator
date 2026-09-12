"""ESRI Shapefile export — geopandas/fiona, DEGRADES (CONTRACT.md §4.21, 40-imagery §8.4).

Shapefile is a 1990s format the industry cannot leave, and its limits are not edge cases;
they are load-bearing:

=========================  =============  =================================================
Limit                      Value          Consequence here
=========================  =============  =================================================
``.dbf`` field names       <= 10 ASCII    ``elevation_source`` collides with ``elevation_m``
Text fields                254 chars      long attribution strings truncate
No datetime type           date only      timestamps lose time-of-day
No NULL for numerics       0 vs missing   a missing elevation is indistinguishable from 0
Multi-file                 5 sidecars     **must ship as a zip**
Encoding                   ``.cpg``       mojibake without it
=========================  =============  =================================================

Every one of those is handled explicitly below and **reported in**
:attr:`ExportBundle.warnings`. The user must be told what the format did to their data —
not left to discover it in their GIS at 6pm.

★ **Call-time bound** (§11.3). ``geopandas`` is not installed on the dev machine and is not
in this package's base install, so it is imported INSIDE :meth:`ShapefileExportWriter.write`
and nowhere else. Importing ``gis.exports`` — which eagerly imports this module to build
the registry — therefore succeeds, and :meth:`ShapefileExportWriter.is_available` answers
``(False, "requires geopandas")`` instead of crashing the capabilities endpoint.
"""

from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path
from typing import Any, Final

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
    missing_dependency_reason,
    module_available,
    record_provenance,
)
from gis.exports.fieldmap import DBF_MAX_TEXT_LEN, FieldNameMapper

__all__ = ["SHAPEFILE_FIELDS", "ShapefileExportWriter"]


SHAPEFILE_FIELDS: Final[tuple[str, ...]] = (
    "gcp_id",
    "code",
    "label",
    "longitude",
    "latitude",
    "elevation_m",
    "elevation_source",
    "pixel_col",
    "pixel_row",
    "satellite_pixel_x",
    "satellite_pixel_y",
    "confidence",
    "confidence_basis",
    "source",
    "coordinate_kind",
    "method",
    "horizontal_accuracy_m",
    "total_ce90_m",
    "relative_ce90_m",
    "georef_ce90_m",
    "accuracy_dominant_term",
    "residual_px",
    "manually_adjusted",
    "adjustment_offset_m",
    "landmark_kind",
    "rmse_m",
    "provider",
    "attribution",
    "terms_url",
    "imagery_captured_at",
    "generated_at",
    "software_version",
)
"""Attribute column order. ``longitude``/``latitude`` are kept as attributes as well as
geometry so that the numbers survive a reprojection to ``target_srid`` — after which the
geometry is in projected units and the original degrees would otherwise be gone."""


def _io_engine() -> str | None:
    """Return the OGR I/O engine geopandas can use here, or None.

    geopandas 1.x prefers ``pyogrio`` and falls back to ``fiona``; either satisfies us.
    """
    for engine in ("pyogrio", "fiona"):
        if module_available(engine):
            return engine
    return None


def _truncate_text(value: str, warnings: list[str], field: str) -> str:
    """Clip a string to the ``.dbf`` 254-character limit, reporting it if it bites.

    The message deliberately omits the original length so that N over-long rows produce ONE
    warning after de-duplication rather than N nearly-identical ones.
    """
    if len(value) <= DBF_MAX_TEXT_LEN:
        return value
    warnings.append(
        f"Shapefile field {field!r} exceeded the .dbf {DBF_MAX_TEXT_LEN}-character limit "
        "for one or more records and was truncated. The full value is in README.txt in "
        "this archive."
    )
    return value[:DBF_MAX_TEXT_LEN]


def _dedupe(warnings: list[str]) -> list[str]:
    """Collapse repeated warnings, preserving first-seen order.

    A per-row check fires once per row; the user needs to be told once.
    """
    seen: set[str] = set()
    unique: list[str] = []
    for warning in warnings:
        if warning not in seen:
            seen.add(warning)
            unique.append(warning)
    return unique


class ShapefileExportWriter(ExportWriter):
    """ESRI Shapefile, delivered as a zip of ``.shp``/``.shx``/``.dbf``/``.prj``/``.cpg``.

    ★ ``file_extension`` is ``.zip`` and ``media_type`` is ``application/zip`` (20-api.md
    §20.5). A shapefile is physically not one file — a single-file "shapefile" download is
    an unusable shapefile.
    """

    format_id = "shapefile"
    label = "ESRI Shapefile"
    media_type = "application/zip"
    file_extension = ".zip"
    is_stdlib_only = False
    supports_target_srid = True
    supports_imagery = False

    def is_available(self) -> tuple[bool, str | None]:
        """Report whether geopandas and an OGR engine can be bound here.

        ★ Never raises and never imports. ``GET /capabilities`` calls this so the UI can
        grey the option with a reason instead of offering a 500.

        Returns:
            ``(True, None)``, or ``(False, "requires …")`` naming what to install.
        """
        missing = missing_dependency_reason("geopandas", "shapely")
        if missing is not None:
            return (False, missing)
        if _io_engine() is None:
            return (False, "requires fiona")
        return (True, None)

    def write(self, ctx: ExportContext, out_path: Path) -> ExportBundle:
        """Write the shapefile set and zip it to ``out_path``.

        Args:
            ctx: The assembled context.
            out_path: Destination ``.zip``.

        Returns:
            The bundle. ``warnings`` names every field rename, every text truncation, and
            the ``.dbf``'s inability to distinguish a missing number from zero.

        Raises:
            ExportError: If geopandas is absent, or a record is not serialisable.
        """
        self._prepare(ctx, out_path)

        # ★ CALL-TIME BINDING (§11.3). Not at module scope, ever.
        import geopandas as gpd
        from shapely.geometry import Point

        attribution_on = include_attribution()
        warnings: list[str] = []
        warnings.extend(self._attribution_warnings(ctx, included=attribution_on))

        mapper = FieldNameMapper()
        mapping, field_warnings = mapper.map(SHAPEFILE_FIELDS)
        warnings.extend(field_warnings)

        rows = [self._row(ctx, index, attribution_on, warnings) for index in range(len(ctx.gcps))]
        geometry = [Point(gcp.lon, gcp.lat) for gcp in ctx.gcps]

        # `columns=` is load-bearing for a zero-GCP export: without it an empty row list
        # yields a frame with NO columns, and the shapefile would ship with no attribute
        # schema at all rather than an empty table with the right one.
        frame = gpd.GeoDataFrame(
            [{mapping[k]: v for k, v in row.items()} for row in rows],
            columns=[mapping[field] for field in SHAPEFILE_FIELDS],
            geometry=geometry,
            crs="EPSG:4326",
        )

        if ctx.target_srid != 4326:
            frame = frame.to_crs(epsg=ctx.target_srid)

        if any(gcp.elevation_m is None for gcp in ctx.gcps):
            warnings.append(
                "One or more GCPs have no elevation. The .dbf format cannot store NULL in "
                "a numeric field, so a missing elevation is indistinguishable from 0.0 in "
                f"{mapping['elevation_m']}. Use {mapping['elevation_source']} — it is "
                "empty for exactly those points — or export GeoPackage/GeoJSON, which "
                "carry a real NULL."
            )

        with tempfile.TemporaryDirectory(prefix="landexplorer-shp-") as tmp:
            tmp_dir = Path(tmp)
            stem = "gcps"
            shp_path = tmp_dir / f"{stem}.shp"
            frame.to_file(shp_path, driver="ESRI Shapefile", encoding="utf-8")

            # fiona does not always write a .cpg. Without one, ArcGIS guesses the codepage
            # and every non-ASCII label becomes mojibake.
            (tmp_dir / f"{stem}.cpg").write_text("UTF-8\n", encoding="ascii")

            # A shapefile without a .prj is a shapefile with NO CRS, and the receiving GIS
            # will guess — wrongly. Verify rather than assume the driver emitted one.
            prj_path = tmp_dir / f"{stem}.prj"
            if not prj_path.exists():
                written = self._write_prj_fallback(prj_path, frame.crs)
                if written:
                    warnings.append(
                        "The OGR driver did not emit a .prj; one was written from the "
                        "layer's CRS definition."
                    )
                else:
                    warnings.append(
                        "★ No .prj could be written for this shapefile: the coordinate "
                        f"reference system (EPSG:{ctx.target_srid}) could not be rendered "
                        "as WKT. The receiving GIS will have to be told the CRS manually."
                    )

            warnings = _dedupe(warnings)
            (tmp_dir / "README.txt").write_text(
                self._readme(ctx, mapper, attribution_on, warnings), encoding="utf-8"
            )

            self._zip_dir(tmp_dir, out_path)

        return self._bundle(out_path, warnings)

    # ── internals ───────────────────────────────────────────────────────────

    def _row(
        self,
        ctx: ExportContext,
        index: int,
        attribution_on: bool,
        warnings: list[str],
    ) -> dict[str, Any]:
        """Build one attribute row, keyed by ORIGINAL field name."""
        gcp = ctx.gcps[index]
        # ★ SCOPE.md §5 — provenance of THIS row, preferring the GCP's own source.
        prov = record_provenance(gcp, ctx)
        return {
            "gcp_id": gcp.gcp_id,
            "code": gcp.code or "",
            "label": _truncate_text(gcp.label or "", warnings, "label"),
            "longitude": round(gcp.lon, LONLAT_DECIMALS),
            "latitude": round(gcp.lat, LONLAT_DECIMALS),
            "elevation_m": (
                None if gcp.elevation_m is None else round(gcp.elevation_m, ACCURACY_DECIMALS)
            ),
            "elevation_source": gcp.elevation_source or "",
            "pixel_col": round(gcp.pixel_col, PIXEL_DECIMALS),
            "pixel_row": round(gcp.pixel_row, PIXEL_DECIMALS),
            "satellite_pixel_x": round(gcp.satellite_pixel_x, PIXEL_DECIMALS),
            "satellite_pixel_y": round(gcp.satellite_pixel_y, PIXEL_DECIMALS),
            "confidence": round(gcp.confidence, CONFIDENCE_DECIMALS),
            "confidence_basis": prov.confidence_basis,
            "source": prov.source,
            "coordinate_kind": "observed" if prov.is_observation else "inferred",
            "method": ctx.method,
            "horizontal_accuracy_m": (
                None
                if gcp.horizontal_accuracy_m is None
                else round(gcp.horizontal_accuracy_m, ACCURACY_DECIMALS)
            ),
            "total_ce90_m": round(gcp.total_ce90_m, ACCURACY_DECIMALS),
            "relative_ce90_m": round(gcp.relative_ce90_m, ACCURACY_DECIMALS),
            "georef_ce90_m": round(gcp.georef_ce90_m, ACCURACY_DECIMALS),
            "accuracy_dominant_term": gcp.accuracy_dominant_term,
            "residual_px": (
                None if gcp.residual_px is None else round(gcp.residual_px, PIXEL_DECIMALS)
            ),
            "manually_adjusted": "true" if gcp.manually_adjusted else "false",
            "adjustment_offset_m": (
                None
                if gcp.adjustment_offset_m is None
                else round(gcp.adjustment_offset_m, ACCURACY_DECIMALS)
            ),
            "landmark_kind": gcp.landmark_kind or "",
            "rmse_m": None if ctx.rmse_m is None else round(ctx.rmse_m, ACCURACY_DECIMALS),
            "provider": ctx.provider_name,
            "attribution": _truncate_text(
                ctx.attribution if attribution_on else "", warnings, "attribution"
            ),
            "terms_url": _truncate_text(
                ctx.terms_url if attribution_on else "", warnings, "terms_url"
            ),
            # The .dbf has no datetime type — date only. Keeping the full ISO string in a
            # text field preserves the time of day the format would otherwise discard.
            "imagery_captured_at": format_timestamp(ctx.imagery_captured_at),
            "generated_at": format_timestamp(ctx.generated_at),
            "software_version": ctx.software_version,
        }

    def _write_prj_fallback(self, prj_path: Path, crs: Any) -> bool:
        """Write a ``.prj`` from the layer CRS. Returns whether it succeeded."""
        try:
            wkt = crs.to_wkt(version="WKT1_ESRI")
        except Exception:  # noqa: BLE001 — any pyproj failure means "no WKT", not a crash
            return False
        if not wkt:
            return False
        prj_path.write_text(wkt, encoding="ascii")
        return True

    def _zip_dir(self, tmp_dir: Path, out_path: Path) -> None:
        """Zip every sidecar into ``out_path``, deterministically ordered."""
        if out_path.exists():
            out_path.unlink()
        with zipfile.ZipFile(
            out_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            for member in sorted(tmp_dir.iterdir()):
                if member.is_file():
                    archive.write(member, arcname=member.name)

    def _readme(
        self,
        ctx: ExportContext,
        mapper: FieldNameMapper,
        attribution_on: bool,
        warnings: list[str],
    ) -> str:
        """Build ``README.txt``.

        ★ This is the only lossless record of what the format did. The ``.dbf`` physically
        cannot hold the original field names, the full attribution string, or the note that
        a zero elevation might mean "unknown" — so all three live here.
        """
        lines: list[str] = [
            f"{ctx.project_name} — Ground Control Points",
            "=" * 72,
            "",
        ]
        for key, value in ctx.metadata_items(include_attribution_value=attribution_on):
            lines.append(f"{key}: {value}")
        lines += [
            "",
            "Accuracy",
            "-" * 72,
            ctx.accuracy_statement(),
            "",
            "Field-name map",
            "-" * 72,
            "The .dbf attribute table limits field names to 10 ASCII characters, so the",
            "names below were shortened. This table is the only complete record of that.",
            "",
            mapper.readme_table(SHAPEFILE_FIELDS),
            "Format limitations that affect this data",
            "-" * 72,
            "* The .dbf cannot store NULL in a numeric field. A blank or zero ELEV_M may",
            "  mean 'unknown'; ELEV_SRC is empty for exactly those points and is the",
            "  authoritative answer.",
            f"* Text fields are capped at {DBF_MAX_TEXT_LEN} characters.",
            "* The .dbf has no timestamp type; date-times are kept as ISO 8601 text.",
            "",
        ]
        if warnings:
            lines += ["Warnings issued for this export", "-" * 72]
            lines += [f"* {w}" for w in warnings]
            lines.append("")
        return "\n".join(lines)
