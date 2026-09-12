"""Terrarium-encoded terrain tiles from a project DEM — the 3D view's height source.

A WebGL map cannot read a GeoTIFF. It reads *tiles*, and it reads elevation as an RGB
image in which the three channels pack a height. This module turns one DEM into that
stream, one 256×256 tile at a time.

★★ **THE MESH IS A VISUALISATION. IT IS NOT THE SURVEY ANSWER.**
This is the single most important thing about this module. The tiles it produces are fed
to a renderer to make hills look like hills — they are resampled, quantised to ~1/256 m,
and (see below) they fill data voids with sea level so the mesh does not tear. **No GCP
elevation ever comes from here.** A point's Z comes from
``app/api/v1/dem.py::sample_project_elevation``, which reads the DEM directly, returns
``null`` where there is no data, and carries a vertical CE90. If those two ever disagree,
*the mesh is wrong and the sample is right*, by construction. Nothing downstream of this
module may treat a rendered height as a measurement.

★ **TERRARIUM, NOT MAPBOX TERRAIN-RGB.** Both encodings pack a height into RGB and both
are understood by MapLibre. Terrarium is used because its decode —
``h = R*256 + G + B/256 - 32768`` — is a documented open format from the Mapzen/Tilezen
lineage with no vendor licensing attached to the *encoding*, which matters for a codebase
whose imagery layer is shaped entirely around provenance (``docs/legal/imagery-terms.md``).

★ **ONE WINDOWED READ PER TILE.** The naïve implementation samples the DEM 65 536 times
per tile through a per-point call. This one projects the tile's pixel grid into the DEM's
own CRS, computes the bounding pixel window, reads *that window once*, and interpolates
inside NumPy. A tile is one I/O.

★ **VOIDS RENDER AS SEA LEVEL, AND THAT IS A RENDERING CHOICE, NOT A CLAIM.** Terrarium
has no nodata value; every pixel decodes to some height. A tile with *no* data at all is
refused (``None``) so the renderer simply draws no terrain there. Within a partially
covered tile, voids encode to 0 m — which will look like a pit, and is meant to: an
obviously wrong hole is a better failure than a smoothly interpolated invention that reads
as real terrain. The authoritative sampler still returns ``null`` for those coordinates.
"""

from __future__ import annotations

import io
import logging
import math
from pathlib import Path
from typing import Final

import numpy as np

from gis import rasterio_shim
from gis.crs import transform_points
from gis.errors import RasterBackendUnavailable
from gis.tiles import invert_geotransform, meters_to_lonlat_array, tile_bbox_meters

__all__ = [
    "TERRARIUM_OFFSET_M",
    "TILE_SIZE_PX",
    "encode_terrarium",
    "terrain_tile_png",
]

_log = logging.getLogger("gis.dem.terrain")

TILE_SIZE_PX: Final[int] = 256
"""Slippy tile edge. 256 is what MapLibre's ``raster-dem`` expects by default."""

TERRARIUM_OFFSET_M: Final[float] = 32768.0
"""The encoding's zero point. ``h = R*256 + G + B/256 - 32768``, so heights from
-32768 m to +32767 m are representable — comfortably beyond any land surface."""

_WGS84: Final[str] = "EPSG:4326"

#: Heights outside this range are treated as void rather than encoded.
#:
#: ★ A DEM whose nodata was never declared shows up as a sentinel like -9999 or -3.4e38.
#: Encoding one of those produces a spike thousands of metres deep that dominates the
#: rendered scene and makes the real terrain unreadable. The guard is deliberately wide —
#: the Dead Sea shore is about -430 m and Everest about 8849 m — so it can only catch
#: sentinels, never a legitimate surface.
_PLAUSIBLE_MIN_M: Final[float] = -500.0
_PLAUSIBLE_MAX_M: Final[float] = 9000.0


def encode_terrarium(heights: np.ndarray) -> np.ndarray:
    """Pack a float height grid into a ``(H, W, 3)`` uint8 Terrarium image.

    ``R = (v >> 8) & 0xFF``, ``G = v & 0xFF``, ``B = frac(v) * 256`` where
    ``v = height + 32768``.

    Args:
        heights: ``(H, W)`` float array in metres. Non-finite entries encode as 0 m —
            callers that care about voids must mask them *before* calling, because by
            this point the distinction is gone. See the module docstring.

    Returns:
        ``(H, W, 3)`` uint8, ready to be written as PNG.
    """
    shifted = np.nan_to_num(heights, nan=0.0, posinf=0.0, neginf=0.0) + TERRARIUM_OFFSET_M
    # Clip rather than wrap: a value outside the representable range must saturate, not
    # alias to an unrelated height on the other side of the world.
    shifted = np.clip(shifted, 0.0, 65535.999)

    whole = np.floor(shifted)
    frac = shifted - whole
    whole_i = whole.astype(np.int32)

    out = np.empty((*heights.shape, 3), dtype=np.uint8)
    out[..., 0] = ((whole_i >> 8) & 0xFF).astype(np.uint8)
    out[..., 1] = (whole_i & 0xFF).astype(np.uint8)
    out[..., 2] = np.clip(frac * 256.0, 0, 255).astype(np.uint8)
    return out


def _bilinear(band: np.ndarray, cols: np.ndarray, rows: np.ndarray) -> np.ndarray:
    """Bilinearly sample ``band`` at fractional ``(col, row)``, NaN outside.

    ★ NaN, not 0 and not edge-clamping. A sample beyond the array has no value, and
    clamping would smear the boundary row across the void — which renders as a plausible
    ridge running along the DEM's edge.
    """
    height, width = band.shape
    col0 = np.floor(cols).astype(np.int64)
    row0 = np.floor(rows).astype(np.int64)

    inside = (col0 >= 0) & (row0 >= 0) & (col0 < width - 1) & (row0 < height - 1)
    if not inside.any():
        return np.full(cols.shape, np.nan, dtype=np.float64)

    c0 = np.clip(col0, 0, width - 2)
    r0 = np.clip(row0, 0, height - 2)
    dc = cols - c0
    dr = rows - r0

    v00 = band[r0, c0]
    v01 = band[r0, c0 + 1]
    v10 = band[r0 + 1, c0]
    v11 = band[r0 + 1, c0 + 1]

    top = v00 * (1.0 - dc) + v01 * dc
    bottom = v10 * (1.0 - dc) + v11 * dc
    out = top * (1.0 - dr) + bottom * dr

    # ★ A void adjacent to data must not bleed into its neighbours through the weights.
    #   If any contributing corner is NaN, the result is NaN.
    corners_finite = (
        np.isfinite(v00) & np.isfinite(v01) & np.isfinite(v10) & np.isfinite(v11)
    )
    return np.where(inside & corners_finite, out, np.nan)


def decode_terrarium(png_bytes: bytes) -> np.ndarray:
    """Decode a Terrarium PNG back to float64 metres. The exact inverse of
    :func:`encode_terrarium`, to quantisation (1/256 m)."""
    from PIL import Image

    rgb = np.asarray(Image.open(io.BytesIO(png_bytes)).convert("RGB"), dtype=np.float64)
    return rgb[:, :, 0] * 256.0 + rgb[:, :, 1] + rgb[:, :, 2] / 256.0 - 32768.0


def fill_voids(heights: np.ndarray, fallback_png: bytes | None) -> np.ndarray:
    """Fill non-finite heights from a fallback terrarium tile, or from the array's floor.

    ★ Pure and unit-tested: this is the line between "project DEM in real
    surroundings" and "island on a kilometre-high cliff".
    """
    mask = ~np.isfinite(heights)
    if not mask.any():
        return heights
    if fallback_png is not None:
        fallback = decode_terrarium(fallback_png)
        if fallback.shape == heights.shape:
            return np.where(mask, fallback, heights)
    floor = float(np.nanmin(heights)) if np.isfinite(heights).any() else 0.0
    return np.where(mask, floor, heights)


def terrain_tile_png(
    dem_path: Path | str,
    z: int,
    x: int,
    y: int,
    *,
    fallback_png: bytes | None = None,
) -> bytes | None:
    """Render one slippy tile of ``dem_path`` as a Terrarium PNG.

    Args:
        dem_path: The project's DEM. Any CRS the raster backend can report.
        z: Zoom. x, y: Slippy tile indices (XYZ, y-down).
        fallback_png: A terrarium tile for the SAME ``z/x/y`` (typically the global
            AWS/Mapzen one) whose heights fill pixels the project DEM does not cover.
            None (offline) fills with the DEM's own minimum instead.

    Returns:
        PNG bytes, or **None** when the tile lies entirely outside the DEM or is entirely
        void. ★ None is the signal for a 404 — "no terrain here" — which makes the
        renderer draw flat ground rather than a fabricated surface.

    Raises:
        RasterBackendUnavailable: Neither rasterio nor GDAL is installed.
        CrsError: The DEM's CRS cannot be transformed from WGS 84.
        ValueError: The DEM has a singular geotransform.
    """
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - Pillow ships with the export extra
        raise RasterBackendUnavailable(
            "Pillow is required to encode terrain tiles; install it with `pip install pillow`"
        ) from exc

    # ── the tile's pixel-centre grid, in web mercator metres ──────────────────
    west, south, east, north = tile_bbox_meters(z, x, y)
    step_x = (east - west) / TILE_SIZE_PX
    step_y = (north - south) / TILE_SIZE_PX
    xs = west + (np.arange(TILE_SIZE_PX) + 0.5) * step_x
    # y descends: row 0 is the tile's NORTH edge, which is the slippy convention and the
    # opposite of the mercator axis. Getting this backwards flips the terrain vertically,
    # which reads as plausible hills in the wrong places.
    ys = north - (np.arange(TILE_SIZE_PX) + 0.5) * step_y
    grid_x, grid_y = np.meshgrid(xs, ys)

    lon, lat = meters_to_lonlat_array(grid_x, grid_y)

    with rasterio_shim.open_dataset(str(dem_path)) as dataset:
        dem_crs = dataset.crs or _WGS84
        geotransform = dataset.geotransform

        # ── project the grid into the DEM's own CRS ───────────────────────────
        if dem_crs.upper().endswith("4326"):
            px, py = lon, lat
        else:
            px, py = transform_points(lon, lat, _WGS84, dem_crs)

        # ★★ THE HALF PIXEL. `invert_geotransform` is documented EDGE convention: it maps
        #    a coordinate to fractional pixel *edge* position, where pixel i spans
        #    [i, i+1). Bilinear interpolation samples between pixel *centres*, which sit
        #    at i + 0.5. Subtracting the half pixel converts one to the other.
        #
        #    Omitting it is not a rounding error. It shifts every reading half a cell —
        #    14 m on a 28 m Copernicus DEM — so the rendered terrain is a real surface
        #    displaced sideways, which on a slope reads as a plausible sub-metre error
        #    against the authoritative sampler and is invisible by inspection. It was
        #    caught only by cross-checking this module against `dem.sample.sample_points`
        #    at identical coordinates; keep that comparison in the tests.
        inverse = invert_geotransform(geotransform)
        cols = inverse[0] + px * inverse[1] + py * inverse[2] - 0.5
        rows = inverse[3] + px * inverse[4] + py * inverse[5] - 0.5

        finite = np.isfinite(cols) & np.isfinite(rows)
        if not finite.any():
            return None

        # ── the one window that covers every sample, padded for interpolation ─
        col_min = int(math.floor(np.nanmin(np.where(finite, cols, np.nan)))) - 1
        col_max = int(math.ceil(np.nanmax(np.where(finite, cols, np.nan)))) + 1
        row_min = int(math.floor(np.nanmin(np.where(finite, rows, np.nan)))) - 1
        row_max = int(math.ceil(np.nanmax(np.where(finite, rows, np.nan)))) + 1

        if col_max < 0 or row_max < 0 or col_min >= dataset.width or row_min >= dataset.height:
            return None  # wholly outside the DEM

        col_off = max(col_min, 0)
        row_off = max(row_min, 0)
        win_w = min(col_max, dataset.width - 1) - col_off + 1
        win_h = min(row_max, dataset.height - 1) - row_off + 1
        if win_w <= 1 or win_h <= 1:
            return None

        band = dataset.read(1, window=(col_off, row_off, win_w, win_h)).astype(np.float64)
        nodata = dataset.nodata

    # ── voids out, before anything interpolates across them ──────────────────
    if nodata is not None and math.isfinite(nodata):
        band = np.where(np.isclose(band, nodata), np.nan, band)
    band = np.where(
        (band >= _PLAUSIBLE_MIN_M) & (band <= _PLAUSIBLE_MAX_M), band, np.nan
    )
    if not np.isfinite(band).any():
        return None

    heights = _bilinear(band, cols - col_off, rows - row_off)
    if not np.isfinite(heights).any():
        return None  # the tile touches the DEM's box but lands entirely in void

    # ★ Remaining NaNs — pixels outside the DEM's coverage or inside its voids — are
    #   filled from the SURROUNDING TERRAIN, not from sea level. The old fill (0 m)
    #   turned a mountain-plateau project DEM into an island ringed by a kilometre-high
    #   cliff wall: at 1400 m of relief the draped imagery stretched down the wall into
    #   the vertical ribbons a surveyor reads as "the 3D view is broken". Merged with a
    #   fallback surface the project DEM sits seamlessly in real surroundings; with no
    #   fallback (offline) the fill is the DEM's own floor — a flat apron, not a chasm.
    heights = fill_voids(heights, fallback_png)
    image = Image.fromarray(encode_terrarium(heights), mode="RGB")
    buffer = io.BytesIO()
    # PNG is lossless by necessity — JPEG's chroma subsampling would corrupt the low bits
    # of the encoding, and those bits ARE the sub-metre part of every height.
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
