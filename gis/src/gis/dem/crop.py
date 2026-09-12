"""Stage 1 — crop a DEM to an AOI bounding box with a fractional tolerance.

Faithful to ``DTM_Proccesing/tif_map/Cropping_stage1/crop_dtm.py``:

1. corners (DMS or decimal) -> decimal degrees;
2. reproject the corners into the raster's CRS if it is not EPSG:4326;
3. bounding box, expanded by ``tolerance`` on every side;
4. clamp to the raster extent and read that window;
5. write the cropped GeoTIFF, carrying the window's own transform.

★ **The crop offset is folded into the output transform** via rasterio's
``window_transform``. Cropping without moving the origin is the defect that produces
coordinates wrong by up to a whole window while crashing nothing — the same failure
``gis.tiles.crop_to_bbox`` calls out for mosaics.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from gis.dem.aoi import AoiCorner, AoiExtent, corners_to_lonlat, extent_of
from gis.errors import GisError, RasterBackendUnavailable

__all__ = ["CropReport", "crop_to_aoi"]

_log = logging.getLogger("gis.dem.crop")


@dataclass(frozen=True, slots=True)
class CropReport:
    """What the crop did — the sidecar the original wrote as ``*_cropped_report.json``.

    Attributes:
        source_crs: The source raster's CRS authority string.
        source_bounds: The source extent in its own CRS, ``(l, b, r, t)``.
        requested_bounds: The padded AOI box, before clamping.
        clamped_bounds: What was actually readable after clamping to the raster.
        output_size: ``(width, height)`` in pixels.
        pixel_size: ``(x, y)`` pixel size in the source CRS's units.
        tolerance: The padding fraction applied.
        aoi_corners_lonlat: The AOI corners as ``(lon, lat)`` pairs, EPSG:4326.
        clipped: True when the padded box reached past the raster edge and was clamped.
            ★ Load-bearing: it means the AOI is not fully covered by this tile, so the
            output is missing ground the surveyor asked for.
        output_path: Where the cropped GeoTIFF was written.
    """

    source_crs: str
    source_bounds: tuple[float, float, float, float]
    requested_bounds: tuple[float, float, float, float]
    clamped_bounds: tuple[float, float, float, float]
    output_size: tuple[int, int]
    pixel_size: tuple[float, float]
    tolerance: float
    aoi_corners_lonlat: list[tuple[float, float]] = field(default_factory=list)
    clipped: bool = False
    output_path: str = ""


def _reproject_extent_to(corners: Sequence[AoiCorner], dst_crs: str) -> AoiExtent:
    """Return the AOI extent expressed in ``dst_crs``.

    ★ All corners are transformed and THEN bounded, never the other way round. Bounding
    first and transforming two corners is only correct for an axis-aligned transform; for
    anything rotated or genuinely projected it silently clips the AOI.
    """
    from gis.crs import normalize_crs, transform_points  # call-time: binds pyproj/osr

    if normalize_crs(dst_crs) == "EPSG:4326":
        return extent_of(corners)

    import numpy as np

    xs, ys = transform_points(
        np.asarray([c.lon for c in corners], dtype=np.float64),
        np.asarray([c.lat for c in corners], dtype=np.float64),
        "EPSG:4326",
        dst_crs,
    )
    extent = AoiExtent(
        left=float(np.min(xs)),
        bottom=float(np.min(ys)),
        right=float(np.max(xs)),
        top=float(np.max(ys)),
    )
    if extent.is_degenerate:
        raise GisError(f"the AOI collapsed to zero area when projected into {dst_crs}")
    return extent


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


def crop_to_aoi(
    src_path: Path | str,
    dst_path: Path | str,
    corners: Sequence[object],
    *,
    tolerance: float = 0.10,
) -> CropReport:
    """Crop ``src_path`` to the AOI's padded bounding box and write ``dst_path``.

    Args:
        src_path: The source DEM, any format GDAL/rasterio reads.
        dst_path: Where to write the cropped GeoTIFF. Parents are created.
        corners: At least three AOI corners; see :func:`gis.dem.corners_to_lonlat`.
        tolerance: Padding as a fraction of the AOI's own span, per side. ``0.10`` is
            the algorithm's 10%.

    Returns:
        The :class:`CropReport`.

    Raises:
        RasterBackendUnavailable: rasterio is not installed.
        GisError: The raster carries no CRS, the AOI is degenerate, or the AOI does not
            overlap the raster at all.
    """
    try:
        import rasterio
        from rasterio.windows import from_bounds
    except ImportError as exc:  # pragma: no cover - depends on the install
        raise RasterBackendUnavailable(
            "cropping a DEM needs rasterio; install it with "
            "`pip install 'landexplorer-gis[rasterio]'`"
        ) from exc

    src_path = Path(src_path)
    dst_path = Path(dst_path)
    aoi = corners_to_lonlat(list(corners))

    with rasterio.open(src_path) as src:
        if src.crs is None:
            raise GisError(
                f"{src_path.name} carries no CRS, so an AOI in lon/lat cannot be located "
                "in it. A DEM without georeferencing cannot be cropped to ground coordinates."
            )
        src_crs = str(src.crs)
        aoi_extent = _reproject_extent_to(aoi, src_crs)
        padded = aoi_extent.padded(tolerance)

        bounds = src.bounds
        clamped = AoiExtent(
            left=max(padded.left, bounds.left),
            bottom=max(padded.bottom, bounds.bottom),
            right=min(padded.right, bounds.right),
            top=min(padded.top, bounds.top),
        )
        if clamped.is_degenerate:
            raise GisError(
                f"the AOI does not overlap {src_path.name}. AOI bounds "
                f"{aoi_extent.as_tuple()} vs raster bounds {tuple(bounds)} in {src_crs}. "
                "This is usually the wrong source tile for these coordinates."
            )

        clipped = (
            padded.left < bounds.left
            or padded.bottom < bounds.bottom
            or padded.right > bounds.right
            or padded.top > bounds.top
        )
        if clipped:
            _log.warning(
                "AOI padded box reaches outside %s; the crop was clamped to the tile edge",
                src_path.name,
            )

        window = from_bounds(*clamped.as_tuple(), transform=src.transform)
        window = window.round_offsets().round_lengths()
        if window.width < 1 or window.height < 1:
            raise GisError(
                "the AOI is smaller than one pixel of this DEM "
                f"({abs(src.transform.a)} units/px); there is nothing to crop"
            )

        data = src.read(window=window)
        profile: dict[str, Any] = src.profile.copy()
        profile.update(
            driver="GTiff",
            height=int(window.height),
            width=int(window.width),
            transform=src.window_transform(window),
            compress=profile.get("compress") or "deflate",
        )
        # ★ Replace the inherited block layout — never keep the source's.
        for key in ("tiled", "blockxsize", "blockysize"):
            profile.pop(key, None)
        profile.update(_tiling(int(profile["width"]), int(profile["height"])))
        # BigTIFF only when the payload actually warrants it: an unconditional
        # BIGTIFF=YES makes small outputs unreadable to some older GIS clients.
        if data.nbytes > 3_000_000_000:
            profile["BIGTIFF"] = "YES"

        dst_path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(dst_path, "w", **profile) as dst:
            dst.write(data)

        return CropReport(
            source_crs=src_crs,
            source_bounds=(bounds.left, bounds.bottom, bounds.right, bounds.top),
            requested_bounds=padded.as_tuple(),
            clamped_bounds=clamped.as_tuple(),
            output_size=(int(window.width), int(window.height)),
            pixel_size=(abs(src.transform.a), abs(src.transform.e)),
            tolerance=tolerance,
            aoi_corners_lonlat=[(c.lon, c.lat) for c in aoi],
            clipped=clipped,
            output_path=str(dst_path),
        )


def aoi_geojson(corners: Sequence[AoiCorner], tolerance: float) -> dict[str, Any]:
    """Return the AOI as a GeoJSON FeatureCollection, as stage 1 wrote alongside the crop.

    The ring is closed explicitly — GeoJSON requires the first and last position to be
    identical, and a viewer that tolerates an open ring is doing you a favour, not
    following the spec.
    """
    ring = [[c.lon, c.lat] for c in corners]
    if ring and ring[0] != ring[-1]:
        ring.append(ring[0])
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"id": "AOI", "tolerance": tolerance},
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            }
        ],
    }
