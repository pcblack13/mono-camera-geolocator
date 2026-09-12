"""Stage 3 — sample elevations out of a DEM at geographic points.

``(X, Y) = project(lon, lat)`` in the output CRS, and ``Z = DEM(X, Y) + offset``.

Faithful to ``DTM_Proccesing/tif_map/converter/convert_gcps.py``, minus the Excel IO —
the spreadsheet was that script's interface, not part of the algorithm. Points come in as
lon/lat and go out as X/Y/Z; whoever called it decides whether that lands in a table, an
export, or ``gcps.elevation_m``.

★ **The DEM is always sampled in its OWN CRS**, read from the file, never in the output
CRS. The two are usually the same after stage 2, but they need not be, and sampling in the
wrong frame is a silent, plausible-looking wrong answer.

★ **The half-pixel is applied.** ``~transform`` maps a world coordinate to pixel EDGE
coordinates, and bilinear weights are relative to pixel CENTRES, so the sampler subtracts
0.5 before interpolating. Omitting it biases every elevation by half a cell — 15 m of
ground at Copernicus 30 m posting, which on a 10% slope is 1.5 m of height. The original
script gets this right and the comment survives here because it is the easiest thing in
the file to "simplify" away.

★ **nodata is never interpolated across.** Blending a valid 800 m against a -32768 void
yields a confident number that is pure fiction. The sampler falls back to the nearest of
the four, and reports None if that is void too — an honest absence, exactly as
``gis.elevation`` treats an unavailable elevation.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal, Sequence

from gis.errors import GisError, RasterBackendUnavailable

__all__ = ["SamplingMethod", "SampledPoint", "sample_points", "summarise_elevation"]

_log = logging.getLogger("gis.dem.sample")

SamplingMethod = Literal["bilinear", "nearest"]

#: Values that mean "void" in DEMs that never declared a nodata tag. Copernicus and SRTM
#: both ship -32767/-32768 voids; FABDEM uses -9999. A DEM claiming an elevation 32 km
#: below the geoid is not reporting terrain.
_SENTINEL_VOIDS: Final[tuple[float, ...]] = (-32768.0, -32767.0, -9999.0, -9998.0)

#: Below the Dead Sea shore (-430 m) and above Everest (8849 m) there is no land surface.
#: Used only to flag a suspicious result, never to silently discard one.
_PLAUSIBLE_MIN_M: Final[float] = -500.0
_PLAUSIBLE_MAX_M: Final[float] = 9000.0


@dataclass(frozen=True, slots=True)
class SampledPoint:
    """One point's projected position and its elevation, or an honest absence.

    Attributes:
        name: Caller's identifier for the point.
        lon: Input longitude, EPSG:4326 degrees.
        lat: Input latitude, EPSG:4326 degrees.
        x: Easting in the output CRS, metres. None if the projection failed.
        y: Northing in the output CRS, metres.
        dem_z_m: Raw elevation read from the DEM, or None when the point is outside the
            DEM or lands on nodata. ★ None and 0.0 are different claims.
        offset_m: The constant offset added to produce ``z_m``.
        z_m: ``dem_z_m + offset_m``, or None when ``dem_z_m`` is None.
        inside_dem: Whether the point falls within the DEM's extent at all.
        suspicious: True when the elevation is outside the plausible land-surface range.
            Reported, never silently dropped.
    """

    name: str
    lon: float
    lat: float
    x: float | None
    y: float | None
    dem_z_m: float | None
    offset_m: float
    z_m: float | None
    inside_dem: bool
    suspicious: bool = False


def _is_void(value: float, nodata: float | None) -> bool:
    """True when a raster value means 'no data here'."""
    if not math.isfinite(value):
        return True
    if nodata is not None and math.isclose(value, nodata, rel_tol=0.0, abs_tol=1e-6):
        return True
    return any(math.isclose(value, v, rel_tol=0.0, abs_tol=1e-6) for v in _SENTINEL_VOIDS)


def _sample_bilinear(band: Any, transform: Any, x: float, y: float, nodata: float | None) -> float | None:
    """Bilinearly interpolate the DEM at world coordinate ``(x, y)``.

    Blends the four surrounding pixel CENTRES by the point's sub-pixel position, so two
    points inside one 30 m cell get distinct, smoothly varying elevations instead of an
    identical stair-step value.
    """
    height, width = band.shape
    col_edge, row_edge = (~transform) * (x, y)
    # Edge -> centre. See the module docstring: this half-pixel is not optional.
    col = col_edge - 0.5
    row = row_edge - 0.5

    col0, row0 = math.floor(col), math.floor(row)
    col1, row1 = col0 + 1, row0 + 1
    dcol, drow = col - col0, row - row0

    # The full 2x2 neighbourhood must be inside the raster; at the edge, fall back to
    # the nearest valid pixel rather than extrapolating off the grid.
    if col0 < 0 or row0 < 0 or col1 >= width or row1 >= height:
        cc = min(max(int(round(col)), 0), width - 1)
        rr = min(max(int(round(row)), 0), height - 1)
        value = float(band[rr, cc])
        return None if _is_void(value, nodata) else value

    v00, v01 = float(band[row0, col0]), float(band[row0, col1])
    v10, v11 = float(band[row1, col0]), float(band[row1, col1])

    if any(_is_void(v, nodata) for v in (v00, v01, v10, v11)):
        # ★ Do not interpolate across a void. Use the nearest of the four instead.
        nearest = band[row0 if drow < 0.5 else row1, col0 if dcol < 0.5 else col1]
        value = float(nearest)
        return None if _is_void(value, nodata) else value

    top = v00 * (1.0 - dcol) + v01 * dcol
    bottom = v10 * (1.0 - dcol) + v11 * dcol
    return top * (1.0 - drow) + bottom * drow


def _sample_nearest(band: Any, transform: Any, x: float, y: float, nodata: float | None) -> float | None:
    """Return the single DEM cell covering ``(x, y)``."""
    col_edge, row_edge = (~transform) * (x, y)
    col, row = int(math.floor(col_edge)), int(math.floor(row_edge))
    height, width = band.shape
    if not (0 <= row < height and 0 <= col < width):
        return None
    value = float(band[row, col])
    return None if _is_void(value, nodata) else value


def sample_points(
    dem_path: Path | str,
    points: Sequence[tuple[str, float, float]],
    *,
    output_crs: str | None = None,
    method: SamplingMethod = "bilinear",
    offset_m: float = 0.0,
) -> tuple[list[SampledPoint], str, str]:
    """Project points and read their elevations from a DEM.

    Args:
        dem_path: The DEM to sample — normally stage 2's projected output.
        points: ``(name, lon, lat)`` triples in EPSG:4326.
        output_crs: CRS for the returned X/Y. None means the DEM's own CRS, which is what
            makes X/Y and Z consistent by construction.
        method: ``"bilinear"`` (recommended, sub-cell detail) or ``"nearest"`` (exact
            source values; points sharing a cell share a Z).
        offset_m: Constant height offset added to every sampled elevation.

    Returns:
        ``(samples, dem_crs, output_crs)``.

    Raises:
        RasterBackendUnavailable: rasterio is not installed.
        GisError: The DEM carries no CRS, or ``offset_m`` is not finite.
    """
    try:
        import rasterio
    except ImportError as exc:  # pragma: no cover - depends on the install
        raise RasterBackendUnavailable(
            "sampling a DEM needs rasterio; install it with "
            "`pip install 'landexplorer-gis[rasterio]'`"
        ) from exc

    if not math.isfinite(offset_m):
        raise GisError(f"offset_m must be finite, got {offset_m}")
    if method not in ("bilinear", "nearest"):
        raise GisError(f"unknown sampling method {method!r}; expected bilinear or nearest")

    from gis.crs import get_transformer, normalize_crs

    sampler = _sample_bilinear if method == "bilinear" else _sample_nearest
    results: list[SampledPoint] = []

    with rasterio.open(dem_path) as dem:
        if dem.crs is None:
            raise GisError(
                f"{Path(dem_path).name} carries no CRS, so a lon/lat point cannot be "
                "located in it."
            )
        dem_crs = str(dem.crs)
        out_crs = normalize_crs(output_crs) if output_crs else dem_crs
        nodata = dem.nodata
        bounds = dem.bounds
        transform = dem.transform
        band = dem.read(1)

        to_dem = get_transformer("EPSG:4326", dem_crs)
        to_out = to_dem if out_crs == dem_crs else get_transformer("EPSG:4326", out_crs)

        for name, lon, lat in points:
            try:
                x_dem_a, y_dem_a = to_dem.transform(lon, lat)
                x_dem, y_dem = float(x_dem_a[0]), float(y_dem_a[0])
                if to_out is to_dem:
                    x_out, y_out = x_dem, y_dem
                else:
                    x_out_a, y_out_a = to_out.transform(lon, lat)
                    x_out, y_out = float(x_out_a[0]), float(y_out_a[0])
            except Exception as exc:  # noqa: BLE001 - a bad point must not kill the batch
                _log.warning("point %s (%.6f, %.6f) could not be projected: %s", name, lon, lat, exc)
                results.append(
                    SampledPoint(name, lon, lat, None, None, None, offset_m, None, False)
                )
                continue

            inside = (
                bounds.left <= x_dem <= bounds.right and bounds.bottom <= y_dem <= bounds.top
            )
            dem_z = sampler(band, transform, x_dem, y_dem, nodata) if inside else None
            z_final = None if dem_z is None else dem_z + offset_m
            suspicious = z_final is not None and not (
                _PLAUSIBLE_MIN_M <= z_final <= _PLAUSIBLE_MAX_M
            )
            if suspicious:
                _log.warning(
                    "point %s sampled %.1f m, outside the plausible land-surface range; "
                    "check the DEM's vertical datum and nodata tag",
                    name, z_final,
                )
            results.append(
                SampledPoint(
                    name=name, lon=lon, lat=lat, x=x_out, y=y_out, dem_z_m=dem_z,
                    offset_m=offset_m, z_m=z_final, inside_dem=inside, suspicious=suspicious,
                )
            )

    return (results, dem_crs, out_crs)


def summarise_elevation(dem_path: Path | str) -> dict[str, float | int | None]:
    """Return min/max/mean elevation and the valid-cell count for a DEM.

    Used to put a real number in front of the surveyor after processing: a DEM whose
    range is 0-0 or 1e30 is a broken read, and seeing that immediately beats discovering
    it three steps later.

    Returns:
        ``{"min_m", "max_m", "mean_m", "valid_cells", "void_cells"}``. Elevation keys are
        None when the DEM has no valid cell at all.
    """
    try:
        import numpy as np
        import rasterio
    except ImportError as exc:  # pragma: no cover
        raise RasterBackendUnavailable("summarising a DEM needs rasterio and numpy") from exc

    with rasterio.open(dem_path) as dem:
        band = dem.read(1, masked=True)
        data = np.ma.masked_invalid(band)
        for void in _SENTINEL_VOIDS:
            data = np.ma.masked_values(data, void, atol=1e-6)

        valid = int(data.count())
        total = int(data.size)
        if valid == 0:
            return {"min_m": None, "max_m": None, "mean_m": None,
                    "valid_cells": 0, "void_cells": total}
        return {
            "min_m": round(float(data.min()), 3),
            "max_m": round(float(data.max()), 3),
            "mean_m": round(float(data.mean()), 3),
            "valid_cells": valid,
            "void_cells": total - valid,
        }
