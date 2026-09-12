"""Stage 2 — reproject a DEM from geographic degrees to projected metres.

``(lambda, phi, H)  ->  (E, N, H)``

★ **This is the stage that makes the DEM measurable.** Ray directions, camera positions,
buffers, slope and distance are all metric operations, and a degree of longitude is 111 km
at the equator, 64 km at 55N and 0 at the pole. Everything downstream of a DEM still in
degrees is arithmetic on a non-uniform axis.

Faithful to ``DTM_Proccesing/tif_map/CRS/reproject_dtm.py``, with one fix: the UTM zone is
resolved by :func:`gis.crs.utm_epsg_for`, not by a local ``(lon + 180) // 6 + 1``. The
original overflows to zone 61 at ``lon = 180`` and returns EPSG:32661 — UPS North, a polar
stereographic CRS, not a UTM zone.

★ Resampling defaults to **bilinear**. Elevation is a continuous surface, so nearest-
neighbour leaves visible terracing along the reprojection grid; that terracing then shows
up as spurious slope. ``nearest`` remains available for the case where preserving exact
source values matters more than smoothness — a categorical or already-quantised raster.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from gis.errors import CrsError, GisError, RasterBackendUnavailable

__all__ = ["RESAMPLING_METHODS", "ReprojectReport", "reproject_to_metric", "resolve_target_crs"]

_log = logging.getLogger("gis.dem.reproject")

RESAMPLING_METHODS: Final[tuple[str, ...]] = ("nearest", "bilinear", "cubic", "cubic_spline",
                                              "lanczos", "average", "mode")
"""Resampling kernels offered for elevation. ``bilinear`` is the default and the right
default; ``average`` is useful when deliberately downsampling to a coarser cell size."""

_FLOAT_NODATA: Final[float] = -9999.0
"""Nodata to declare on a float output whose source declared none. The DEM convention."""

_INT_NODATA: Final[int] = -32768
"""Nodata to declare on an integer output whose source declared none. SRTM's convention."""


def _fill_nodata_for(dtype: str, src_nodata: float | None) -> float:
    """Return the nodata value the OUTPUT must declare.

    ★ **THE ZERO-FILL TRAP, and why this function exists.**

    Warping rotates the source grid inside the destination grid, so the output always has
    margin cells that no source pixel covers. GDAL fills them with ``dst_nodata`` — and
    when that is ``None`` it fills them with **0**.

    On a DEM, 0 is a perfectly ordinary elevation. So an undeclared-nodata source produces
    an output where 6% of the cells (measured on the project's own Copernicus tile) read
    exactly 0.00 m and are **indistinguishable from real terrain sitting at sea level**.
    Sample a control point near the AOI edge and you get ``Z = 0.00`` where the ground is
    at 1400 m — a 1400 m error wearing the costume of a valid measurement, on terrain
    whose true range is 1348-1834 m.

    The source-of-truth crop has no zeros at all; they are manufactured by the warp. So
    when the source declares no nodata we declare one, and the margin becomes honestly
    absent instead of silently wrong.
    """
    if src_nodata is not None:
        return float(src_nodata)
    return float(_INT_NODATA) if dtype.startswith(("int", "uint")) else _FLOAT_NODATA


@dataclass(frozen=True, slots=True)
class ReprojectReport:
    """What the reprojection did — the original's ``*_utm_report.json``.

    Attributes:
        source_crs: Input CRS authority string.
        target_crs: Output CRS authority string. Always a projected metre CRS.
        resampling: The kernel used.
        source_size: ``(width, height)`` in pixels, before.
        output_size: ``(width, height)`` in pixels, after.
        source_pixel_size: ``(x, y)`` in the SOURCE CRS's units — degrees, when the input
            was geographic.
        output_pixel_size_m: ``(x, y)`` in TRUE metres. ★ This is the DEM's ground sample
            distance and the number a surveyor should be reading.
        output_bounds_m: The output extent in target-CRS metres.
        auto_utm: True when the zone was chosen from the raster centre rather than given.
        output_path: Where the reprojected GeoTIFF was written.
    """

    source_crs: str
    target_crs: str
    resampling: str
    source_size: tuple[int, int]
    output_size: tuple[int, int]
    source_pixel_size: tuple[float, float]
    output_pixel_size_m: tuple[float, float]
    output_bounds_m: tuple[float, float, float, float]
    auto_utm: bool = False
    output_path: str = ""


def resolve_target_crs(
    centre_lon: float, centre_lat: float, target_crs: str | None
) -> tuple[str, bool]:
    """Decide the output CRS: the caller's, or the UTM zone under the raster centre.

    ★ Routes through :func:`gis.crs.utm_epsg_for`, which clamps the zone to 60 and
    rejects ``|lat| > 84``. Choosing from the CENTRE rather than a corner keeps the
    projection error symmetric across the tile instead of piling it up at one edge.

    Args:
        centre_lon: Longitude of the raster centre, degrees.
        centre_lat: Latitude of the raster centre, degrees.
        target_crs: An explicit authority string, or None to auto-select UTM.

    Returns:
        ``(crs, auto_selected)``.

    Raises:
        GisError: If ``target_crs`` is given but does not measure in true ground metres.
        OutsideUtmError: If auto-selecting and the centre is beyond ``|lat| = 84``.
    """
    from gis.crs import is_ground_metric_crs, normalize_crs, utm_epsg_for

    if target_crs is None:
        return (utm_epsg_for(centre_lon, centre_lat), True)

    crs = normalize_crs(target_crs)
    # ★ The whole point of this stage is metres, so a target that is not a ground-metre
    #   CRS is refused rather than honoured. EPSG:3857 is the trap this catches: its
    #   linear unit genuinely IS the metre, so a units-only check passes it, and the
    #   result is a DEM whose "metres" are inflated by 1/cos(phi) — 41% at 45N.
    if not is_ground_metric_crs(crs):
        if crs in ("EPSG:3857", "EPSG:900913", "EPSG:102100", "EPSG:102113"):
            raise GisError(
                f"{crs} (Web Mercator) is a pixel-addressing scheme, not a measurement "
                "system: its metres are inflated by 1/cos(latitude) — 41% at 45N, 74% at "
                "55N. Reprojecting a DEM into it would make every distance, slope and "
                "volume derived from it wrong. Use a UTM zone (or leave the target unset "
                "to pick one automatically)."
            )
        raise GisError(
            f"{crs} does not measure in true ground metres. This stage exists to convert "
            "(lambda, phi, H) to (E, N, H); a geographic target would be a no-op."
        )
    return (crs, False)


def _tiling(width: int, height: int) -> dict[str, Any]:
    """GTiff block options for an output of this size.

    ★ THE INHERITED PROFILE IS POISON HERE. Both writers start from
    ``src.profile.copy()``, which carries the SOURCE's ``blockxsize``/``blockysize``.
    A striped source (every SRTM/FABDEM-style export: ``tiled=False``,
    ``blockysize=5``) then meets our ``tiled=True`` and GDAL refuses the file
    outright — *"The height and width of TIFF dataset blocks must be multiples of
    16"* — so processing a perfectly good DEM failed with a message about TIFF
    internals. The block keys must be REPLACED, never inherited.

    Small outputs are written striped: a 256-px tile grid over an 88x131 crop is
    mostly padding, and tiling buys nothing a GIS client will ever page through.
    """
    if width >= 256 and height >= 256:
        return {"tiled": True, "blockxsize": 256, "blockysize": 256}
    return {"tiled": False}


def reproject_to_metric(
    src_path: Path | str,
    dst_path: Path | str,
    *,
    target_crs: str | None = None,
    resampling: str = "bilinear",
    target_resolution_m: float | None = None,
) -> ReprojectReport:
    """Reproject ``src_path`` into a projected metre CRS and write ``dst_path``.

    Args:
        src_path: The input DEM — normally stage 1's cropped output.
        dst_path: Where to write the reprojected GeoTIFF.
        target_crs: Explicit projected CRS, or None to auto-pick the UTM zone under the
            raster centre.
        resampling: One of :data:`RESAMPLING_METHODS`.
        target_resolution_m: Output cell size in metres, or None to let GDAL derive the
            resolution equivalent to the source. ★ None is the right default: naming a
            cell size finer than the source invents detail the DEM never had, and one
            much coarser throws away detail silently.

    Returns:
        The :class:`ReprojectReport`.

    Raises:
        RasterBackendUnavailable: rasterio is not installed.
        GisError: Unknown resampling kernel, missing/invalid CRS, or a non-metric target.
    """
    try:
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.warp import calculate_default_transform, reproject
    except ImportError as exc:  # pragma: no cover - depends on the install
        raise RasterBackendUnavailable(
            "reprojecting a DEM needs rasterio; install it with "
            "`pip install 'landexplorer-gis[rasterio]'`"
        ) from exc

    if resampling not in RESAMPLING_METHODS:
        raise GisError(
            f"unknown resampling method {resampling!r}; expected one of "
            f"{', '.join(RESAMPLING_METHODS)}"
        )
    try:
        kernel = Resampling[resampling]
    except KeyError as exc:  # pragma: no cover - guarded above
        raise GisError(f"rasterio does not offer resampling {resampling!r}") from exc

    src_path = Path(src_path)
    dst_path = Path(dst_path)

    with rasterio.open(src_path) as src:
        if src.crs is None:
            raise GisError(
                f"{src_path.name} carries no CRS, so it cannot be reprojected. "
                "A DEM without georeferencing has no place on Earth to convert from."
            )

        centre_lon, centre_lat = _centre_lonlat(src)
        dst_crs, auto = resolve_target_crs(centre_lon, centre_lat, target_crs)
        _log.info(
            "reprojecting %s: %s -> %s (%s, %s)",
            src_path.name, src.crs, dst_crs, resampling,
            "auto UTM" if auto else "explicit",
        )

        kwargs: dict[str, Any] = {}
        if target_resolution_m is not None:
            if not (target_resolution_m > 0):
                raise GisError(
                    f"target resolution must be > 0 m, got {target_resolution_m}"
                )
            kwargs["resolution"] = target_resolution_m

        try:
            dst_transform, dst_width, dst_height = calculate_default_transform(
                src.crs, dst_crs, src.width, src.height, *src.bounds, **kwargs
            )
        except Exception as exc:  # noqa: BLE001 - rasterio/GDAL raise assorted types
            raise CrsError(
                f"could not compute a {dst_crs} grid for {src_path.name}: {exc}. "
                "The raster may lie outside the target CRS's domain of validity."
            ) from exc

        # ★ See _fill_nodata_for: a warp ALWAYS creates margin cells, and an undeclared
        #   nodata makes GDAL fill them with 0 — a valid-looking sea-level elevation.
        dst_nodata = _fill_nodata_for(src.dtypes[0], src.nodata)
        if src.nodata is None:
            _log.info(
                "%s declares no nodata; the output declares %s so the warp margin is "
                "honestly void rather than 0 m",
                src_path.name, dst_nodata,
            )

        profile: dict[str, Any] = src.profile.copy()
        profile.update(
            driver="GTiff",
            crs=dst_crs,
            transform=dst_transform,
            width=int(dst_width),
            height=int(dst_height),
            nodata=dst_nodata,
            compress=profile.get("compress") or "deflate",
        )
        # ★ Replace the inherited block layout — never keep the source's.
        for key in ("tiled", "blockxsize", "blockysize"):
            profile.pop(key, None)
        profile.update(_tiling(int(profile["width"]), int(profile["height"])))

        dst_path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(dst_path, "w", **profile) as dst:
            for band in range(1, src.count + 1):
                reproject(
                    source=rasterio.band(src, band),
                    destination=rasterio.band(dst, band),
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=dst_transform,
                    dst_crs=dst_crs,
                    resampling=kernel,
                    src_nodata=src.nodata,
                    dst_nodata=dst_nodata,
                )

        bounds = rasterio.transform.array_bounds(dst_height, dst_width, dst_transform)
        return ReprojectReport(
            source_crs=str(src.crs),
            target_crs=str(dst_crs),
            resampling=resampling,
            source_size=(src.width, src.height),
            output_size=(int(dst_width), int(dst_height)),
            source_pixel_size=(abs(src.transform.a), abs(src.transform.e)),
            output_pixel_size_m=(abs(dst_transform.a), abs(dst_transform.e)),
            output_bounds_m=(bounds[0], bounds[1], bounds[2], bounds[3]),
            auto_utm=auto,
            output_path=str(dst_path),
        )


def _centre_lonlat(src: Any) -> tuple[float, float]:
    """Return the raster centre as ``(lon, lat)`` degrees, whatever CRS it is in."""
    from gis.crs import normalize_crs, transform_point

    bounds = src.bounds
    cx = (bounds.left + bounds.right) / 2.0
    cy = (bounds.bottom + bounds.top) / 2.0
    if normalize_crs(str(src.crs)) == "EPSG:4326":
        return (cx, cy)
    return transform_point(cx, cy, str(src.crs), "EPSG:4326")
