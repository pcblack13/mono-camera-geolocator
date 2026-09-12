"""CSV export — stdlib only, ALWAYS available (40-imagery §8.2).

CSV is one of the four formats that can never degrade. That is not an accident of
implementation: it is why the most important format was built on the standard library. On a
machine with no geo stack — which is precisely the machine this was developed on — the
surveyor can still get their coordinates out.

**The columns mirror the on-screen GCP table**, in the same order the surveyor sees them
(:data:`CSV_COLUMNS`): Point ID · Name · Image X · Image Y · Latitude · Longitude · Source ·
Accuracy. So the file that opens in a spreadsheet reads exactly like the table it came from —
a header row, the data rows, and nothing else.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Final

from gis.exports.base import (
    LONLAT_DECIMALS,
    ExportBundle,
    ExportContext,
    ExportWriter,
    format_number,
    include_attribution,
)

__all__ = ["CSV_COLUMNS", "CsvExportWriter"]


CSV_COLUMNS: Final[tuple[str, ...]] = (
    "Point ID",
    "Name",
    "Image X",
    "Image Y",
    "Latitude",
    "Longitude",
    "Source",
    "Accuracy",
)
"""★ Mirrors the on-screen GCP table (frontend ``GcpTable``): the same columns, in the same
order, so the export reads like what the surveyor sees. Point ID · Name · Image X · Image Y ·
Latitude · Longitude · Source · Accuracy."""

#: Photo-pixel columns show 1 decimal, exactly as the table does (`.toFixed(1)`).
_PIXEL_DP: Final[int] = 1


def _source_label(source: str) -> str:
    """Map the wire source to the table's chip text: OBSERVED vs INFERRED."""
    return "Observed" if source in ("manual", "direct_georeference") else "Inferred"


#: The DD+UTM+Z column set — mirrors the table's DD+UTM+Z view (no Source column).
DDUTMZ_COLUMNS: Final[tuple[str, ...]] = (
    "Point ID",
    "Name",
    "Image X",
    "Image Y",
    "Latitude",
    "Longitude",
    "Easting",
    "Northing",
    "Zone",
    "Z (m)",
    "Accuracy",
)

# ── UTM (WGS 84 Transverse Mercator), stdlib-only — see the frontend `toUtm` twin ──
_WGS84_A: Final[float] = 6378137.0
_WGS84_F: Final[float] = 1 / 298.257223563
_UTM_K0: Final[float] = 0.9996
_UTM_FALSE_EASTING: Final[float] = 500000.0
_UTM_FALSE_NORTHING: Final[float] = 10000000.0


def _utm_zone(lat: float, lon: float) -> int:
    zone = int((lon + 180) // 6) + 1
    if 56 <= lat < 64 and 3 <= lon < 12:
        zone = 32
    if 72 <= lat < 84:
        if 0 <= lon < 9:
            zone = 31
        elif 9 <= lon < 21:
            zone = 33
        elif 21 <= lon < 33:
            zone = 35
        elif 33 <= lon < 42:
            zone = 37
    return zone


def _to_utm(lat: float, lon: float) -> tuple[int, str, float, float] | None:
    """``(zone, hemisphere, easting_m, northing_m)`` or None outside UTM's ±80/84° range."""
    if not (-80.0 <= lat <= 84.0) or not math.isfinite(lat) or not math.isfinite(lon):
        return None
    zone = _utm_zone(lat, lon)
    lon0 = math.radians((zone - 1) * 6 - 180 + 3)
    phi = math.radians(lat)
    lam = math.radians(lon)
    e2 = _WGS84_F * (2 - _WGS84_F)
    ep2 = e2 / (1 - e2)
    sin_phi, cos_phi, tan_phi = math.sin(phi), math.cos(phi), math.tan(phi)
    n = _WGS84_A / math.sqrt(1 - e2 * sin_phi * sin_phi)
    t = tan_phi * tan_phi
    c = ep2 * cos_phi * cos_phi
    d_lam = lam - lon0
    while d_lam > math.pi:
        d_lam -= 2 * math.pi
    while d_lam < -math.pi:
        d_lam += 2 * math.pi
    a = d_lam * cos_phi
    e4, e6 = e2 * e2, e2 * e2 * e2
    m = _WGS84_A * (
        (1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
        - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * phi)
        + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * phi)
        - (35 * e6 / 3072) * math.sin(6 * phi)
    )
    a2, a3 = a * a, a * a * a
    a4, a5, a6 = a3 * a, a3 * a * a, a3 * a3
    easting = (
        _UTM_K0 * n * (a + (1 - t + c) * a3 / 6 + (5 - 18 * t + t * t + 72 * c - 58 * ep2) * a5 / 120)
        + _UTM_FALSE_EASTING
    )
    northing = _UTM_K0 * (
        m
        + n
        * tan_phi
        * (a2 / 2 + (5 - t + 9 * c + 4 * c * c) * a4 / 24 + (61 - 58 * t + t * t + 600 * c - 330 * ep2) * a6 / 720)
    )
    hemisphere = "N" if lat >= 0 else "S"
    if hemisphere == "S":
        northing += _UTM_FALSE_NORTHING
    return (zone, hemisphere, easting, northing)


def _accuracy_cell(total_ce90_m: float | None) -> str:
    """The Accuracy column, formatted exactly like the table's ``formatAccuracy`` — e.g.
    ``±9 m``. The decimals follow the table's ``metreDecimals``: <1 m → 2, <5 m → 1, else 0."""
    if total_ce90_m is None or not math.isfinite(total_ce90_m):
        return ""
    if total_ce90_m < 1:
        decimals = 2
    elif total_ce90_m < 5:
        decimals = 1
    else:
        decimals = 0
    return f"±{total_ce90_m:.{decimals}f} m"


class CsvExportWriter(ExportWriter):
    """The normative CSV writer. Stdlib only; never unavailable."""

    format_id = "csv"
    label = "Comma-Separated Values (CSV)"
    media_type = "text/csv"
    file_extension = ".csv"
    is_stdlib_only = True
    supports_target_srid = False
    supports_imagery = False

    def is_available(self) -> tuple[bool, str | None]:
        """Always ``(True, None)``. The standard library is not optional.

        Returns:
            ``(True, None)``.
        """
        return (True, None)

    def write(self, ctx: ExportContext, out_path: Path) -> ExportBundle:
        """Write the GCP table as UTF-8-with-BOM CSV, mirroring the on-screen table.

        The BOM (``utf-8-sig``) is deliberate: Excel mis-decodes plain UTF-8 CSV, and field
        labels contain non-ASCII more often than anyone expects. The BOM costs nothing and
        prevents a support ticket.

        The header row is the columns; each data row is one GCP formatted as the UI shows it
        (photo pixels to 1 dp, coordinates in decimal degrees, source as Observed/Inferred,
        accuracy as ``±N m``). Nothing else — no comment lines — so the file reads exactly
        like the on-screen table.

        Args:
            ctx: The assembled context.
            out_path: Destination ``.csv``.

        Returns:
            The bundle. ``warnings`` reports any suppressed attribution and any
            ``target_srid`` this format could not honour.
        """
        self._prepare(ctx, out_path)

        attribution_on = include_attribution()
        warnings: list[str] = []
        warnings.extend(self._srid_warning(ctx))
        warnings.extend(self._attribution_warnings(ctx, included=attribution_on))

        # newline="" is required by the csv module: it does its own line-ending handling,
        # and letting the text layer translate as well produces stray CRs on Windows.
        ddutmz = ctx.coordinate_format == "ddutmz"

        with out_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, dialect="excel", quoting=csv.QUOTE_MINIMAL)
            writer.writerow(DDUTMZ_COLUMNS if ddutmz else CSV_COLUMNS)

            for gcp in ctx.gcps:
                if ddutmz:
                    u = _to_utm(gcp.lat, gcp.lon)
                    writer.writerow(
                        (
                            gcp.code or gcp.gcp_id[:8],
                            gcp.label or "",
                            format_number(gcp.pixel_col, _PIXEL_DP),
                            format_number(gcp.pixel_row, _PIXEL_DP),
                            format_number(gcp.lat, LONLAT_DECIMALS),
                            format_number(gcp.lon, LONLAT_DECIMALS),
                            format_number(u[2], 2) if u else "",  # Easting
                            format_number(u[3], 2) if u else "",  # Northing
                            f"{u[0]}{u[1]}" if u else "",  # Zone, e.g. 37N
                            format_number(gcp.elevation_m, 2),  # Z — blank until computed
                            _accuracy_cell(gcp.total_ce90_m),
                        )
                    )
                else:
                    writer.writerow(
                        (
                            gcp.code or gcp.gcp_id[:8],
                            gcp.label or "",
                            format_number(gcp.pixel_col, _PIXEL_DP),
                            format_number(gcp.pixel_row, _PIXEL_DP),
                            format_number(gcp.lat, LONLAT_DECIMALS),
                            format_number(gcp.lon, LONLAT_DECIMALS),
                            _source_label(gcp.source),
                            _accuracy_cell(gcp.total_ce90_m),
                        )
                    )

        return self._bundle(out_path, warnings)
