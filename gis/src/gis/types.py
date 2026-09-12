"""Value types for the ``gis`` package (CONTRACT.md §4.16).

Framework-free: ``numpy`` + stdlib only. This module is imported by every other module
in the package and must stay import-cheap forever.

Coordinate conventions, stated once and obeyed everywhere:

* ``BBox`` is **always** EPSG:4326, **always** ``(west, south, east, north)``, **always**
  degrees.
* ``TileRef`` is the **slippy/XYZ** scheme: ``y = 0`` at NORTH, ``y`` increasing
  SOUTHWARD. TMS flips this; we do not.
* ``geotransform`` is the **GDAL 6-tuple**
  ``(origin_x, pixel_width, row_rotation, origin_y, col_rotation, pixel_height)`` with
  ``pixel_height`` negative for north-up rasters. Its origin is the **outer edge** of the
  top-left pixel. This is the interchange format for the whole system.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

import numpy as np

__all__ = [
    "BasemapKind",
    "BBox",
    "GeoTransform",
    "LonLat",
    "RasterMeta",
    "SatelliteChip",
    "TileRange",
    "TileRef",
    "ZoomDecision",
]


GeoTransform = tuple[float, float, float, float, float, float]
"""GDAL 6-tuple: ``(origin_x, pixel_width, row_rotation, origin_y, col_rotation, pixel_height)``.

The origin is the OUTER EDGE of the top-left pixel (GDAL convention), which is why
``gis.tiles.pixel_to_lonlat`` adds the half-pixel to reach a pixel CENTRE.
"""


@dataclass(frozen=True, slots=True)
class TileRef:
    """One slippy-map tile.

    Args:
        z: Zoom level, ``>= 0``.
        x: Tile column, ``0 <= x < 2**z``, increasing EASTWARD.
        y: Tile row, ``0 <= y < 2**z``, increasing SOUTHWARD (``y = 0`` is the north edge).
    """

    z: int
    x: int
    y: int

    def __post_init__(self) -> None:
        if self.z < 0:
            raise ValueError(f"zoom must be >= 0, got {self.z}")
        n = 1 << self.z
        if not (0 <= self.x < n):
            raise ValueError(f"x={self.x} outside [0, {n}) at z={self.z}")
        if not (0 <= self.y < n):
            raise ValueError(f"y={self.y} outside [0, {n}) at z={self.z}")

    def quadkey(self) -> str:
        """Return this tile's Bing quadkey.

        The quadkey interleaves the bits of ``x`` and ``y`` from the most significant
        bit down, one base-4 digit per zoom level. ``z = 0`` has the empty quadkey.

        Returns:
            A string of ``z`` characters drawn from ``"0123"``.
        """
        digits: list[str] = []
        for i in range(self.z, 0, -1):
            digit = 0
            mask = 1 << (i - 1)
            if self.x & mask:
                digit += 1
            if self.y & mask:
                digit += 2
            digits.append(str(digit))
        return "".join(digits)

    def parent(self) -> TileRef:
        """Return the tile one zoom level up that contains this one.

        Raises:
            ValueError: At ``z == 0``, which has no parent.
        """
        if self.z == 0:
            raise ValueError("the z=0 tile has no parent")
        return TileRef(self.z - 1, self.x >> 1, self.y >> 1)

    def children(self) -> tuple[TileRef, TileRef, TileRef, TileRef]:
        """Return the four tiles one zoom level down, in ``(NW, NE, SW, SE)`` order."""
        z, x2, y2 = self.z + 1, self.x << 1, self.y << 1
        return (
            TileRef(z, x2, y2),
            TileRef(z, x2 + 1, y2),
            TileRef(z, x2, y2 + 1),
            TileRef(z, x2 + 1, y2 + 1),
        )


@dataclass(frozen=True, slots=True)
class LonLat:
    """A geographic position in EPSG:4326 degrees. Longitude FIRST, always."""

    lon: float
    lat: float


@dataclass(frozen=True, slots=True)
class BBox:
    """An axis-aligned geographic box.

    ALWAYS EPSG:4326, ALWAYS ``(west, south, east, north)``, ALWAYS degrees.

    A box with ``west > east`` denotes an antimeridian-crossing region. Such a box is
    representable so that ``gis.geometry.split_antimeridian`` can split it, but it is
    REJECTED by ``gis.tiles.bbox_to_tile_range`` rather than silently wrapped.
    """

    west: float
    south: float
    east: float
    north: float

    def __post_init__(self) -> None:
        for name, value in (
            ("west", self.west),
            ("east", self.east),
        ):
            if not math.isfinite(value) or not (-180.0 <= value <= 180.0):
                raise ValueError(f"{name}={value!r} outside [-180, 180]")
        for name, value in (
            ("south", self.south),
            ("north", self.north),
        ):
            if not math.isfinite(value) or not (-90.0 <= value <= 90.0):
                raise ValueError(f"{name}={value!r} outside [-90, 90]")
        if self.south > self.north:
            raise ValueError(f"south={self.south} is north of north={self.north}")

    @property
    def crosses_antimeridian(self) -> bool:
        """True iff this box wraps across +/-180 degrees longitude."""
        return self.west > self.east

    def center(self) -> tuple[float, float]:
        """Return ``(lon, lat)`` of the box centre.

        For an antimeridian-crossing box the longitude is computed through the wrap and
        re-wrapped into ``[-180, 180)``.
        """
        lat = (self.south + self.north) / 2.0
        if self.crosses_antimeridian:
            span = (self.east - self.west) % 360.0
            lon = self.west + span / 2.0
            lon = ((lon + 180.0) % 360.0) - 180.0
        else:
            lon = (self.west + self.east) / 2.0
        return (lon, lat)

    def contains(self, lon: float, lat: float) -> bool:
        """True iff ``(lon, lat)`` lies inside this box, edges inclusive."""
        if not (self.south <= lat <= self.north):
            return False
        if self.crosses_antimeridian:
            return lon >= self.west or lon <= self.east
        return self.west <= lon <= self.east

    def buffered_m(self, meters: float) -> BBox:
        """Return this box grown by ``meters`` on every side.

        The longitude expansion uses the latitude with the SMALLEST ``cos`` (i.e. the
        pole-most edge), so the result is guaranteed to CONTAIN the true geodesic buffer
        rather than to approximate it from the middle. Over-covering is safe for the
        search/budget callers this exists for; under-covering would silently exclude the
        correct answer.

        Args:
            meters: Buffer distance in true ground metres. May be negative to shrink.

        Returns:
            A new ``BBox``, clamped to the valid lon/lat domain.
        """
        from gis.tiles import EARTH_RADIUS_M  # call-time: breaks the types<->tiles cycle

        m_per_deg_lat = math.pi * EARTH_RADIUS_M / 180.0
        dlat = meters / m_per_deg_lat

        worst_lat = max(abs(self.south), abs(self.north))
        cos_phi = math.cos(math.radians(min(worst_lat, 90.0)))
        if cos_phi <= 1e-12:
            dlon = 180.0
        else:
            dlon = meters / (m_per_deg_lat * cos_phi)

        south = max(-90.0, self.south - dlat)
        north = min(90.0, self.north + dlat)
        if south > north:
            south = north = (south + north) / 2.0

        if dlon >= 180.0 or (self.east - self.west) + 2.0 * dlon >= 360.0:
            return BBox(-180.0, south, 180.0, north)

        west = max(-180.0, self.west - dlon)
        east = min(180.0, self.east + dlon)
        if west > east:
            west = east = (west + east) / 2.0
        return BBox(west, south, east, north)

    def area_m2(self) -> float:
        """Return the box's area in true square metres.

        Exact on a sphere of radius ``EARTH_RADIUS_M``:
        ``A = R**2 * dlon_rad * (sin(north) - sin(south))``. Used for budget checks, so
        an equal-area spherical figure is the right tool; it is never reported as a
        survey number.
        """
        from gis.tiles import EARTH_RADIUS_M  # call-time: breaks the types<->tiles cycle

        dlon = (self.east - self.west) % 360.0 if self.crosses_antimeridian else (self.east - self.west)
        dlon_rad = math.radians(dlon)
        return abs(
            EARTH_RADIUS_M**2
            * dlon_rad
            * (math.sin(math.radians(self.north)) - math.sin(math.radians(self.south)))
        )


@dataclass(frozen=True, slots=True)
class TileRange:
    """An inclusive rectangle of tiles at one zoom level."""

    z: int
    min_x: int
    min_y: int
    max_x: int
    max_y: int

    def __post_init__(self) -> None:
        if self.z < 0:
            raise ValueError(f"zoom must be >= 0, got {self.z}")
        if self.max_x < self.min_x:
            raise ValueError(f"max_x={self.max_x} < min_x={self.min_x}")
        if self.max_y < self.min_y:
            raise ValueError(f"max_y={self.max_y} < min_y={self.min_y}")

    @property
    def cols(self) -> int:
        """Number of tile columns in the range."""
        return self.max_x - self.min_x + 1

    @property
    def rows(self) -> int:
        """Number of tile rows in the range."""
        return self.max_y - self.min_y + 1

    def __len__(self) -> int:
        return self.cols * self.rows

    def __iter__(self) -> Iterator[TileRef]:
        """Yield every tile, ROW-MAJOR: ``y`` outer (north to south), ``x`` inner (west to east).

        ``gis.tiles.stitch_tiles`` relies on this order matching the mosaic's raster order.
        """
        for y in range(self.min_y, self.max_y + 1):
            for x in range(self.min_x, self.max_x + 1):
                yield TileRef(self.z, x, y)


@dataclass(frozen=True, slots=True)
class ZoomDecision:
    """The outcome of choosing a zoom level for a target ground sample distance."""

    zoom: int
    achieved_mpp: float
    requested_mpp: float
    clamped: bool
    """★ Load-bearing: True means the provider cannot serve the requested resolution and
    we are about to work against upsampled mush. Callers surface it; they never ignore it."""


class BasemapKind(StrEnum):
    """Which rendering of the basemap a caller wants.

    ★ Matching ALWAYS uses ``SATELLITE``, normatively. Labels and hillshade are for human
    eyes only; feeding a label-burned tile to a matcher is a genuine accuracy regression.
    """

    SATELLITE = "satellite"
    HYBRID = "hybrid"
    """Imagery plus a labels/boundaries reference overlay, composited server-side."""
    TERRAIN = "terrain"


@dataclass(frozen=True, slots=True)
class RasterMeta:
    """Georeferencing metadata read off a raster file, with no pixels attached."""

    width: int
    height: int
    band_count: int
    geotransform: GeoTransform
    crs: str | None
    """Authority string of ``geotransform``, or None when the file is not georeferenced."""
    is_georeferenced: bool
    """★ False for a plain scanned TIFF. GDAL hands back an identity transform for those;
    treating that as 'georeferenced at the equator' is the bug this flag exists to stop."""
    nodata: float | None = None
    dtype: str = "uint8"
    overview_count: int = 0
    driver: str | None = None


@dataclass(frozen=True, slots=True)
class SatelliteChip:
    """A provider's output: pixels plus everything needed to place and licence them.

    ``attribution`` and ``terms_url`` are REQUIRED, not optional — that is what makes the
    licence obligation unforgeable rather than reviewer-dependent.
    """

    image: np.ndarray
    """(H, W, 3) uint8, RGB, C-contiguous."""
    geotransform: GeoTransform
    crs: str
    """Authority string of ``geotransform``. EPSG:3857 for slippy providers; PER-FILE
    (typically a UTM zone) for local orthophotos. It is NOT fixed."""
    provider_name: str
    """Provenance only, NEVER control flow."""
    attribution: str
    terms_url: str
    zoom: int | None
    captured_at: datetime | None
    gsd_m: float
    """★ TRUE ground metres per pixel at chip centre, cos(phi)-corrected. NOT a 3857 metre."""
    georef_ce90_m: float
    """The provider's own absolute georeferencing error, CE90 metres."""
    is_authoritative: bool
    """True means survey-grade georeferencing."""
    kind: BasemapKind = BasemapKind.SATELLITE
    placeholder_fraction: float = 0.0
    bands: tuple[str, ...] = ("R", "G", "B")
    extra_bands: Mapping[str, np.ndarray] | None = None
    """(H, W) float32 per non-RGB band, keys matching ``bands[3:]``."""

    @property
    def size(self) -> tuple[int, int]:
        """Return ``(width, height)`` in pixels."""
        return (int(self.image.shape[1]), int(self.image.shape[0]))
