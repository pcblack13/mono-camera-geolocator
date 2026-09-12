"""The three stages, composed — one call, one report.

    upload -> [crop to AOI] -> [reproject to metres] -> processed GeoTIFF (+ statistics)

Both raster stages are **optional and independently skippable**, because both are
legitimately unnecessary:

* a DEM that is already clipped to the survey area needs no crop, and cropping it to a
  larger AOI would only pad it back out;
* a DEM already in UTM needs no reprojection, and round-tripping it through a second
  resample would blur it for nothing. :func:`process_dem` detects that case itself and
  skips the stage rather than resampling a raster into the CRS it is already in.

★ The pipeline never mutates its input. Each stage writes a new file into ``work_dir`` and
the caller decides what to keep — which is what makes a failed stage recoverable and the
intermediate crop inspectable when a result looks wrong.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from gis.dem.crop import CropReport, aoi_geojson, crop_to_aoi
from gis.dem.reproject import ReprojectReport, reproject_to_metric
from gis.dem.sample import summarise_elevation
from gis.errors import GisError, RasterBackendUnavailable

__all__ = ["DemPipelineReport", "process_dem"]

_log = logging.getLogger("gis.dem.pipeline")


@dataclass(frozen=True, slots=True)
class DemPipelineReport:
    """Everything the run did, in the order it did it.

    Attributes:
        source_name: The input file's name.
        source_crs: The input's CRS, before anything was done to it.
        crop: Stage 1's report, or None when cropping was skipped.
        reproject: Stage 2's report, or None when reprojection was skipped or unnecessary.
        statistics: min/max/mean elevation and valid-cell counts of the OUTPUT.
        output_path: The final processed GeoTIFF.
        output_crs: The final CRS.
        output_size: Final ``(width, height)`` in pixels.
        output_pixel_size_m: Final cell size in metres, or None if the output is still
            geographic (both raster stages skipped on a degrees-based input).
        aoi_geojson: The AOI polygon, for drawing on a map. None when no AOI was given.
        warnings: Honest notes — a clamped crop, a skipped stage, a suspicious range.
    """

    source_name: str
    source_crs: str
    crop: CropReport | None
    reproject: ReprojectReport | None
    statistics: dict[str, Any]
    output_path: str
    output_crs: str
    output_size: tuple[int, int]
    output_pixel_size_m: tuple[float, float] | None
    aoi_geojson: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)


def _describe(path: Path) -> tuple[str, tuple[int, int], tuple[float, float]]:
    """Return ``(crs, (width, height), (px, py))`` for a raster."""
    import rasterio

    with rasterio.open(path) as src:
        return (
            str(src.crs) if src.crs else "",
            (src.width, src.height),
            (abs(src.transform.a), abs(src.transform.e)),
        )


def process_dem(
    src_path: Path | str,
    work_dir: Path | str,
    *,
    aoi_corners: Sequence[object] | None = None,
    tolerance: float = 0.10,
    reproject: bool = True,
    target_crs: str | None = None,
    resampling: str = "bilinear",
    target_resolution_m: float | None = None,
    output_stem: str = "dem_processed",
) -> DemPipelineReport:
    """Run crop and reprojection over a DEM and report what happened.

    Args:
        src_path: The uploaded DEM.
        work_dir: Directory for intermediate and final outputs. Created if absent.
        aoi_corners: AOI corners to crop to, or None to skip stage 1.
        tolerance: Stage 1 padding fraction.
        reproject: Whether to run stage 2 at all.
        target_crs: Explicit projected CRS, or None to auto-pick the UTM zone.
        resampling: Stage 2 kernel.
        target_resolution_m: Output cell size in metres, or None to preserve the source's.
        output_stem: Base filename for the final output.

    Returns:
        The :class:`DemPipelineReport`.

    Raises:
        RasterBackendUnavailable: rasterio is not installed.
        GisError: Any stage's own validation failure.
    """
    try:
        import rasterio  # noqa: F401 - presence check before doing any work
    except ImportError as exc:  # pragma: no cover
        raise RasterBackendUnavailable(
            "DEM processing needs rasterio; install it with "
            "`pip install 'landexplorer-gis[rasterio]'`"
        ) from exc

    src_path = Path(src_path)
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []

    source_crs, _size, _px = _describe(src_path)
    if not source_crs:
        raise GisError(
            f"{src_path.name} carries no coordinate reference system. A DEM without "
            "georeferencing cannot be cropped to an AOI or reprojected — it is a grid of "
            "numbers with no place on Earth."
        )

    current = src_path
    crop_report: CropReport | None = None
    aoi_feature: dict[str, Any] | None = None

    # ── Stage 1 — crop ────────────────────────────────────────────────────────
    if aoi_corners:
        cropped = work_dir / f"{output_stem}_cropped.tif"
        crop_report = crop_to_aoi(current, cropped, aoi_corners, tolerance=tolerance)
        current = cropped
        from gis.dem.aoi import corners_to_lonlat

        aoi_feature = aoi_geojson(corners_to_lonlat(list(aoi_corners)), tolerance)
        if crop_report.clipped:
            warnings.append(
                "The AOI extends beyond the DEM's coverage; the crop was clamped to the "
                "tile edge. Part of the area of interest has no elevation data."
            )
        _log.info("stage 1 crop -> %sx%s px", *crop_report.output_size)
    else:
        warnings.append("No AOI given — the whole DEM was processed.")

    # ── Stage 2 — reproject ───────────────────────────────────────────────────
    reproject_report: ReprojectReport | None = None
    if reproject:
        from gis.crs import is_ground_metric_crs

        current_crs, _, _ = _describe(current)
        already_metric = is_ground_metric_crs(current_crs)
        if already_metric and target_crs is None:
            # ★ Do not resample a DEM into the CRS it is already in. A no-op warp is not
            #   free: it is a full bilinear resample that blurs the surface for nothing.
            warnings.append(
                f"The DEM is already in a projected metre CRS ({current_crs}); "
                "reprojection was skipped to avoid a needless resample."
            )
            _log.info("stage 2 skipped: %s is already ground-metric", current_crs)
        else:
            projected = work_dir / f"{output_stem}_utm.tif"
            reproject_report = reproject_to_metric(
                current,
                projected,
                target_crs=target_crs,
                resampling=resampling,
                target_resolution_m=target_resolution_m,
            )
            current = projected
            _log.info(
                "stage 2 reproject -> %s at %.3f m/px",
                reproject_report.target_crs,
                reproject_report.output_pixel_size_m[0],
            )
    else:
        warnings.append(
            "Reprojection was skipped. The DEM remains in its source CRS; if that is "
            "geographic, distances and slopes derived from it will not be in metres."
        )

    # ── Final output ──────────────────────────────────────────────────────────
    final = work_dir / f"{output_stem}.tif"
    if current != final:
        final.write_bytes(current.read_bytes())

    out_crs, out_size, out_px = _describe(final)
    from gis.crs import is_ground_metric_crs

    pixel_size_m = out_px if is_ground_metric_crs(out_crs) else None
    if pixel_size_m is None:
        warnings.append(
            f"The output is in {out_crs}, whose units are not ground metres, so no cell "
            "size in metres can be reported."
        )

    statistics = summarise_elevation(final)
    if statistics.get("valid_cells") == 0:
        warnings.append(
            "The processed DEM contains no valid elevation cells — every cell is nodata. "
            "Check that the AOI overlaps real terrain in this tile."
        )
    # ★ NO WARNING FOR PARTIAL VOIDS — deliberate, and deliberately not a deletion of
    #   the fact. Voids are normal in every real DEM (water is blanked; radar sources
    #   leave gaps in shadow), so a banner over 10% fired on ordinary terrain and
    #   became noise the operator learned to dismiss — which is worse than silence,
    #   because it trains dismissal. The COUNT still travels in `statistics`
    #   (`void_cells` / `valid_cells`) and the result panel shows it, so the
    #   information is one glance away rather than in the way. The all-nodata case
    #   above still warns: that is not a partial void, it is an unusable output.

    return DemPipelineReport(
        source_name=src_path.name,
        source_crs=source_crs,
        crop=crop_report,
        reproject=reproject_report,
        statistics=statistics,
        output_path=str(final),
        output_crs=out_crs,
        output_size=out_size,
        output_pixel_size_m=pixel_size_m,
        aoi_geojson=aoi_feature,
        warnings=warnings,
    )
