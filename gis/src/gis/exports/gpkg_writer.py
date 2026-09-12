"""GeoPackage export — geopandas/fiona, DEGRADES (CONTRACT.md §4.21).

OGC GeoPackage is what Shapefile should have been: one file, real NULLs, real timestamps,
UTF-8 by definition, and no 10-character field-name limit. Everything
``shapefile_writer.py`` has to apologise for, this format simply does — which is why the
attribute names here are the **unabbreviated** ones and no :class:`FieldNameMapper` is
involved.

★ **Call-time bound** (§11.3): ``geopandas`` is imported inside :meth:`GpkgExportWriter.write`.
"""

from __future__ import annotations

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
    format_timestamp,
    include_attribution,
    missing_dependency_reason,
    module_available,
    record_provenance,
)

__all__ = ["GPKG_LAYER_NAME", "GpkgExportWriter"]


GPKG_LAYER_NAME: Final[str] = "gcps"
"""The layer a consumer opens. Named for what it holds, not for the project."""


def _io_engine() -> str | None:
    """Return the OGR I/O engine geopandas can use here, or None."""
    for engine in ("pyogrio", "fiona"):
        if module_available(engine):
            return engine
    return None


class GpkgExportWriter(ExportWriter):
    """OGC GeoPackage, one point layer plus a full provenance record per row."""

    format_id = "gpkg"
    label = "OGC GeoPackage"
    media_type = "application/geopackage+sqlite3"
    file_extension = ".gpkg"
    is_stdlib_only = False
    supports_target_srid = True
    supports_imagery = False

    def is_available(self) -> tuple[bool, str | None]:
        """Report whether geopandas and an OGR engine can be bound here.

        Returns:
            ``(True, None)``, or ``(False, "requires …")``. Never raises, never imports.
        """
        missing = missing_dependency_reason("geopandas", "shapely")
        if missing is not None:
            return (False, missing)
        if _io_engine() is None:
            return (False, "requires fiona")
        return (True, None)

    def write(self, ctx: ExportContext, out_path: Path) -> ExportBundle:
        """Write the ``gcps`` layer to a GeoPackage.

        Args:
            ctx: The assembled context.
            out_path: Destination ``.gpkg``.

        Returns:
            The bundle.

        Raises:
            ExportError: If geopandas is absent, or a record is not serialisable.
        """
        self._prepare(ctx, out_path)

        # ★ CALL-TIME BINDING (§11.3).
        import geopandas as gpd
        from shapely.geometry import Point

        attribution_on = include_attribution()
        warnings: list[str] = []
        warnings.extend(self._attribution_warnings(ctx, included=attribution_on))

        rows = [self._row(ctx, index, attribution_on) for index in range(len(ctx.gcps))]
        geometry = [Point(gcp.lon, gcp.lat) for gcp in ctx.gcps]

        frame = gpd.GeoDataFrame(
            rows,
            columns=list(self._columns()),
            geometry=geometry,
            crs="EPSG:4326",
        )
        if ctx.target_srid != 4326:
            frame = frame.to_crs(epsg=ctx.target_srid)

        # A GeoPackage is a SQLite database and to_file APPENDS by default in some driver
        # versions. Removing any stale file first makes a re-export idempotent rather than
        # doubling its rows.
        if out_path.exists():
            out_path.unlink()

        frame.to_file(out_path, driver="GPKG", layer=GPKG_LAYER_NAME)

        return self._bundle(out_path, warnings)

    def _columns(self) -> tuple[str, ...]:
        """Attribute column order. Unabbreviated — GeoPackage has no name-length limit."""
        return (
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
            "accuracy_statement",
        )

    def _row(self, ctx: ExportContext, index: int, attribution_on: bool) -> dict[str, Any]:
        """Build one attribute row.

        ★ ``None`` stays ``None``: GeoPackage stores a real NULL, so a missing elevation is
        a NULL rather than the ``.dbf``'s ambiguous zero.
        """
        gcp = ctx.gcps[index]
        # ★ SCOPE.md §5 — provenance of THIS row, preferring the GCP's own source.
        prov = record_provenance(gcp, ctx)
        return {
            "gcp_id": gcp.gcp_id,
            "code": gcp.code,
            "label": gcp.label,
            "longitude": round(gcp.lon, LONLAT_DECIMALS),
            "latitude": round(gcp.lat, LONLAT_DECIMALS),
            "elevation_m": (
                None if gcp.elevation_m is None else round(gcp.elevation_m, ACCURACY_DECIMALS)
            ),
            "elevation_source": gcp.elevation_source,
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
            "manually_adjusted": gcp.manually_adjusted,
            "adjustment_offset_m": (
                None
                if gcp.adjustment_offset_m is None
                else round(gcp.adjustment_offset_m, ACCURACY_DECIMALS)
            ),
            "landmark_kind": gcp.landmark_kind,
            "rmse_m": None if ctx.rmse_m is None else round(ctx.rmse_m, ACCURACY_DECIMALS),
            "provider": ctx.provider_name,
            "attribution": ctx.attribution if attribution_on else None,
            "terms_url": ctx.terms_url if attribution_on else None,
            "imagery_captured_at": format_timestamp(ctx.imagery_captured_at) or None,
            "generated_at": format_timestamp(ctx.generated_at),
            "software_version": ctx.software_version,
            # Carried per row rather than in a sidecar table: a GeoPackage layer is
            # routinely copied out on its own, and the statement must not be the thing
            # that gets left behind.
            "accuracy_statement": ctx.accuracy_statement(),
        }
