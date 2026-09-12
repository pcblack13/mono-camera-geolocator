"""Pure slippy-map / Web-Mercator math (CONTRACT.md §4.18).

★ NO I/O. NO optional deps. NO pyproj, NO osgeo. numpy + stdlib only.
Everything in the product depends on this module, so it is written to be verified by
reading and pinned by goldens against published references.

Conventions, stated once and obeyed throughout
----------------------------------------------
**Tile scheme.** Slippy/XYZ: ``x`` increases EASTWARD, ``y`` increases SOUTHWARD, and
``y = 0`` is the north edge of the world. (TMS flips ``y``; we never do.)

**Geotransform.** The GDAL 6-tuple
``(origin_x, pixel_width, row_rotation, origin_y, col_rotation, pixel_height)``, with
``pixel_height`` negative for north-up rasters. ``origin_x``/``origin_y`` are the OUTER
EDGE of the top-left pixel.

**Pixel centres vs pixel edges.** ``pixel_to_lonlat``/``lonlat_to_pixel`` use the PIXEL
CENTRE convention — integer ``(col, row)`` names the CENTRE of that pixel, so the forward
map carries a ``+0.5``::

    X = gt[0] + (col + 0.5) * gt[1] + (row + 0.5) * gt[2]
    Y = gt[3] + (col + 0.5) * gt[4] + (row + 0.5) * gt[5]

The ``+0.5`` is not pedantry. Omitting it biases EVERY GCP by half a pixel, consistently
in one direction (~0.21 m at z18/45N). That is a systematic bias, not noise, and it does
not average out. ``invert_geotransform`` is the plain affine (EDGE) inverse and is for
internal geometry only — never for GCP work.

The corner identity that ties the two together::

    pixel_to_lonlat(gt, crs, -0.5, -0.5) == tile_to_lonlat(z, x_min, y_min)
"""

from __future__ import annotations

import math
from collections.abc import Mapping

import numpy as np

from gis.errors import CrsError
from gis.types import BBox, GeoTransform, TileRange, TileRef, ZoomDecision

__all__ = [
    "EARTH_CIRCUMFERENCE_M",
    "EARTH_RADIUS_M",
    "MAX_LATITUDE",
    "ORIGIN_SHIFT_M",
    "RESOLUTION_Z0_256",
    "apply_geotransform",
    "bbox_to_tile_range",
    "choose_zoom",
    "crop_to_bbox",
    "geotransform_to_affine",
    "invert_geotransform",
    "lonlat_to_meters",
    "lonlat_to_meters_array",
    "lonlat_to_pixel",
    "lonlat_to_tile",
    "lonlat_to_tile_fractional",
    "meters_to_lonlat",
    "meters_to_lonlat_array",
    "pixel_to_lonlat",
    "quadkey_to_tile",
    "resolution_at",
    "stitch_tiles",
    "tile_bbox_lonlat",
    "tile_bbox_meters",
    "tile_range_count",
    "tile_to_lonlat",
    "tiles_for_polygon",
    "tile_to_lonlat_center",
    "tile_to_quadkey",
    "unapply_geotransform",
    "zoom_for_resolution",
]

# --- Constants ---------------------------------------------------------------
# ★ These are DEFINITIONS, not measurements. Tests assert exact float equality.

EARTH_RADIUS_M: float = 6378137.0
"""WGS84 semi-major axis, and the radius of the sphere EPSG:3857 projects."""

EARTH_CIRCUMFERENCE_M: float = 40075016.685578488
"""``2 * pi * EARTH_RADIUS_M``."""

ORIGIN_SHIFT_M: float = 20037508.342789244
"""``EARTH_CIRCUMFERENCE_M / 2`` — half the world in EPSG:3857 metres."""

MAX_LATITUDE: float = 85.0511287798066
"""``degrees(atan(sinh(pi)))`` — where the Mercator world becomes square."""

RESOLUTION_Z0_256: float = 156543.03392804097
"""``EARTH_CIRCUMFERENCE_M / 256`` — EPSG:3857 metres per pixel at z0, 256px tiles."""

_MAX_ZOOM_CLAMP: int = 24

_EPSG_3857_ALIASES: frozenset[str] = frozenset(
    {"EPSG:3857", "EPSG:900913", "EPSG:102100", "EPSG:102113", "3857", "900913"}
)
_EPSG_4326_ALIASES: frozenset[str] = frozenset({"EPSG:4326", "EPSG:4979", "4326", "CRS84"})


def _normalize_crs(crs: str) -> str:
    """Normalise an authority string for the closed-form fast paths.

    Returns ``"EPSG:3857"``, ``"EPSG:4326"``, or the upper-cased input unchanged.
    """
    key = crs.strip().upper().replace("URN:OGC:DEF:CRS:OGC:1.3:", "").replace("EPSG::", "EPSG:")
    if key in _EPSG_3857_ALIASES:
        return "EPSG:3857"
    if key in _EPSG_4326_ALIASES:
        return "EPSG:4326"
    return key


def _clamp_lat(lat: float) -> float:
    """Clamp a latitude into the Mercator-representable band."""
    return max(-MAX_LATITUDE, min(MAX_LATITUDE, lat))


def _wrap_lon(lon: float) -> float:
    """Wrap an out-of-range longitude into ``[-180, 180]``.

    ★ ``+/-180`` ARE IN RANGE AND ARE NOT THE SAME PLACE, addressing-wise. The naive
    ``((lon + 180) % 360) - 180`` folds ``+180`` onto ``-180``, which sends a point on the
    east edge of the world to tile ``x = 0`` — the WEST-most tile — and projects it to
    ``-ORIGIN_SHIFT_M`` instead of ``+ORIGIN_SHIFT_M``. That is a whole-world addressing
    error at the one longitude where nobody looks. (It is the same defect as the ``% 360``
    in the contract's ``utm_epsg_for``; see ``gis.crs.utm_epsg_for``.)

    So: values already in ``[-180, 180]`` pass through untouched, and only genuinely
    out-of-range values are wrapped.
    """
    if -180.0 <= lon <= 180.0:
        return lon
    wrapped = ((lon + 180.0) % 360.0) - 180.0
    # `% 360` maps an exact multiple of 360 to -180; +180 and -180 are the same meridian
    # for a wrapped input, so either is correct here and -180 is the conventional choice.
    return wrapped


# --- Slippy tile math --------------------------------------------------------


def lonlat_to_tile_fractional(lon: float, lat: float, z: int) -> tuple[float, float]:
    """Convert a geographic position to FRACTIONAL tile coordinates.

    Args:
        lon: Longitude in degrees; wrapped into ``[-180, 180)``.
        lat: Latitude in degrees; clamped to ``+/-MAX_LATITUDE``.
        z: Zoom level, ``>= 0``.

    Returns:
        ``(x, y)`` in tile units at zoom ``z``. ``x`` grows east, ``y`` grows SOUTH.
        The integer part is the tile index; the fraction is the position within it.

    Raises:
        ValueError: If ``z < 0``.
    """
    if z < 0:
        raise ValueError(f"zoom must be >= 0, got {z}")
    n = float(1 << z)
    lon_w = _wrap_lon(lon)
    lat_c = _clamp_lat(lat)
    x = (lon_w + 180.0) / 360.0 * n
    # asinh(tan(phi)) is the inverse Gudermannian: numerically better behaved than
    # log(tan(phi) + sec(phi)) near the poles, and exactly equal analytically.
    y = (1.0 - math.asinh(math.tan(math.radians(lat_c))) / math.pi) / 2.0 * n
    return (x, y)


def lonlat_to_tile(lon: float, lat: float, z: int) -> TileRef:
    """Return the tile containing a geographic position.

    Args:
        lon: Longitude in degrees.
        lat: Latitude in degrees.
        z: Zoom level.

    Returns:
        The containing ``TileRef``, clamped into ``[0, 2**z - 1]`` on both axes.
    """
    x_f, y_f = lonlat_to_tile_fractional(lon, lat, z)
    n = (1 << z) - 1
    x = max(0, min(n, int(math.floor(x_f))))
    y = max(0, min(n, int(math.floor(y_f))))
    return TileRef(z, x, y)


def _tile_to_lonlat_f(z: int, x: float, y: float) -> tuple[float, float]:
    """Fractional-tile to lon/lat. The exact analytic inverse of the fractional forward map."""
    if z < 0:
        raise ValueError(f"zoom must be >= 0, got {z}")
    n = float(1 << z)
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n))))
    return (lon, lat)


def tile_to_lonlat(z: int, x: int, y: int) -> tuple[float, float]:
    """Return the NORTH-WEST corner of a tile as ``(lon, lat)`` degrees.

    Args:
        z: Zoom level.
        x: Tile column (may be ``2**z`` to name the world's east edge).
        y: Tile row (may be ``2**z`` to name the world's south edge).

    Returns:
        ``(lon, lat)`` of the tile's NW corner.
    """
    return _tile_to_lonlat_f(z, float(x), float(y))


def tile_to_lonlat_center(z: int, x: int, y: int) -> tuple[float, float]:
    """Return the CENTRE of a tile as ``(lon, lat)`` degrees."""
    return _tile_to_lonlat_f(z, x + 0.5, y + 0.5)


# --- 4326 <-> 3857, closed form ----------------------------------------------
# ★ Four lines of arithmetic and the only transform on the hot path. pyproj is not
#   needed, not imported, and not installed.


def lonlat_to_meters(lon: float, lat: float) -> tuple[float, float]:
    """Project EPSG:4326 degrees to EPSG:3857 metres.

    Args:
        lon: Longitude in degrees; wrapped into ``[-180, 180)``.
        lat: Latitude in degrees; clamped to ``+/-MAX_LATITUDE``.

    Returns:
        ``(mx, my)`` in EPSG:3857 metres. ★ These are ADDRESSING units, not ground
        metres: they are inflated by ``1/cos(phi)``. Never measure with them.
    """
    mx = math.radians(_wrap_lon(lon)) * EARTH_RADIUS_M
    my = math.asinh(math.tan(math.radians(_clamp_lat(lat)))) * EARTH_RADIUS_M
    return (mx, my)


def meters_to_lonlat(mx: float, my: float) -> tuple[float, float]:
    """Unproject EPSG:3857 metres to EPSG:4326 degrees.

    Args:
        mx: Easting in EPSG:3857 metres.
        my: Northing in EPSG:3857 metres.

    Returns:
        ``(lon, lat)`` in degrees.
    """
    lon = math.degrees(mx / EARTH_RADIUS_M)
    lat = math.degrees(math.atan(math.sinh(my / EARTH_RADIUS_M)))
    return (lon, lat)


def lonlat_to_meters_array(
    lon: np.ndarray, lat: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorised ``lonlat_to_meters``.

    Args:
        lon: Array of longitudes in degrees.
        lat: Array of latitudes in degrees.

    Returns:
        ``(mx, my)`` float64 arrays in EPSG:3857 metres, shaped like the inputs.
    """
    lon_a = np.asarray(lon, dtype=np.float64)
    lat_a = np.asarray(lat, dtype=np.float64)
    # Match _wrap_lon exactly: in-range values (including +/-180) pass through untouched.
    lon_w = np.where(
        (lon_a >= -180.0) & (lon_a <= 180.0), lon_a, ((lon_a + 180.0) % 360.0) - 180.0
    )
    lat_c = np.clip(lat_a, -MAX_LATITUDE, MAX_LATITUDE)
    mx = np.radians(lon_w) * EARTH_RADIUS_M
    my = np.arcsinh(np.tan(np.radians(lat_c))) * EARTH_RADIUS_M
    return (mx, my)


def meters_to_lonlat_array(mx: np.ndarray, my: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Vectorised ``meters_to_lonlat``.

    Args:
        mx: Array of eastings in EPSG:3857 metres.
        my: Array of northings in EPSG:3857 metres.

    Returns:
        ``(lon, lat)`` float64 arrays in degrees, shaped like the inputs.
    """
    mx_a = np.asarray(mx, dtype=np.float64)
    my_a = np.asarray(my, dtype=np.float64)
    lon = np.degrees(mx_a / EARTH_RADIUS_M)
    lat = np.degrees(np.arctan(np.sinh(my_a / EARTH_RADIUS_M)))
    return (lon, lat)


# --- Resolution and zoom -----------------------------------------------------


def resolution_at(z: int, lat: float, tile_size: int = 256) -> float:
    """Return TRUE ground metres per pixel at zoom ``z`` and latitude ``lat``.

    ``res = (EARTH_CIRCUMFERENCE_M / tile_size) * cos(radians(lat)) / 2**z``

    The ``cos(phi)`` factor is what turns a Mercator addressing unit into a ground
    metre. Every caller that multiplies pixels by a scale to get metres must use this
    (or a ``gsd_m`` derived from it), never a geotransform coefficient.

    Args:
        z: Zoom level, ``>= 0``.
        lat: Latitude in degrees.
        tile_size: Tile edge in pixels — 256 or 512. ★ Read it from the provider's
            capabilities; never hardcode it.

    Returns:
        Ground metres per pixel.

    Raises:
        ValueError: If ``z < 0``, ``tile_size <= 0``, or ``|lat| > 90``.
    """
    if z < 0:
        raise ValueError(f"zoom must be >= 0, got {z}")
    if tile_size <= 0:
        raise ValueError(f"tile_size must be > 0, got {tile_size}")
    if not (-90.0 <= lat <= 90.0):
        raise ValueError(f"lat={lat} outside [-90, 90]")
    return (EARTH_CIRCUMFERENCE_M / tile_size) * math.cos(math.radians(lat)) / float(2**z)


def zoom_for_resolution(
    target_mpp: float,
    lat: float,
    tile_size: int = 256,
    *,
    round_mode: str = "up",
) -> int:
    """Return the zoom level achieving ``target_mpp`` ground metres per pixel.

    THE EXACT INVERSE of ``resolution_at``, ``tile_size`` and all::

        z = log2((EARTH_CIRCUMFERENCE_M / tile_size) * cos(radians(lat)) / target_mpp)

    ★ ``tile_size`` is USED, not decorative. For a 512px provider the correct solve is
    exactly one lower than for 256px; hardcoding 256 returns ``z + 1`` for every 512px
    provider, which quadruples the tile count, spuriously trips the area budget, and
    makes ``ZoomDecision.clamped`` cry wolf.

    Args:
        target_mpp: Desired ground metres per pixel, ``> 0``.
        lat: Latitude in degrees.
        tile_size: Tile edge in pixels — 256 or 512.
        round_mode: ``"up"`` (finer than requested, the safe default), ``"down"``
            (coarser), or ``"nearest"``.

    Returns:
        A zoom level clamped to ``[0, 24]``.

    Raises:
        ValueError: If ``target_mpp <= 0``, ``round_mode`` is unknown, or ``lat`` is at
            a pole where the resolution is zero and no zoom can satisfy the request.
    """
    if not (target_mpp > 0.0) or not math.isfinite(target_mpp):
        raise ValueError(f"target_mpp must be > 0, got {target_mpp}")
    if round_mode not in ("up", "down", "nearest"):
        raise ValueError(f"round_mode must be up|down|nearest, got {round_mode!r}")
    if tile_size <= 0:
        raise ValueError(f"tile_size must be > 0, got {tile_size}")
    if not (-90.0 <= lat <= 90.0):
        raise ValueError(f"lat={lat} outside [-90, 90]")

    cos_phi = math.cos(math.radians(lat))
    if cos_phi <= 0.0:
        raise ValueError(f"resolution is zero at lat={lat}; no zoom satisfies the request")

    ratio = (EARTH_CIRCUMFERENCE_M / tile_size) * cos_phi / target_mpp
    z_exact = math.log2(ratio)

    if round_mode == "up":
        # A finer pixel than asked for is the safe error: `res` DECREASES as z grows.
        z = math.ceil(z_exact)
    elif round_mode == "down":
        z = math.floor(z_exact)
    else:
        z = round(z_exact)
    return max(0, min(_MAX_ZOOM_CLAMP, int(z)))


def choose_zoom(
    min_zoom: int,
    max_zoom: int,
    target_mpp: float,
    lat: float,
    tile_size: int = 256,
) -> ZoomDecision:
    """Pick a zoom for a target resolution, clamped to what a provider will serve.

    ★ THE ONE canonical signature: it carries ``tile_size`` and threads it through.

    Args:
        min_zoom: The provider's minimum servable zoom.
        max_zoom: The provider's maximum servable zoom.
        target_mpp: Desired ground metres per pixel.
        lat: Latitude in degrees, for the ``cos(phi)`` correction.
        tile_size: The provider's tile edge in pixels.

    Returns:
        A ``ZoomDecision``. ``clamped`` is load-bearing: True means the provider could
        not serve the requested resolution and the caller is about to work against
        upsampled mush. Callers report it; they never drop it.

    Raises:
        ValueError: If ``min_zoom > max_zoom``.
    """
    if min_zoom > max_zoom:
        raise ValueError(f"min_zoom={min_zoom} > max_zoom={max_zoom}")
    ideal = zoom_for_resolution(target_mpp, lat, tile_size, round_mode="up")
    zoom = max(min_zoom, min(max_zoom, ideal))
    return ZoomDecision(
        zoom=zoom,
        achieved_mpp=resolution_at(zoom, lat, tile_size),
        requested_mpp=target_mpp,
        clamped=zoom != ideal,
    )


# --- Tile extents ------------------------------------------------------------


def tile_bbox_lonlat(z: int, x: int, y: int) -> BBox:
    """Return a tile's geographic extent as an EPSG:4326 ``BBox``."""
    west, north = tile_to_lonlat(z, x, y)
    east, south = tile_to_lonlat(z, x + 1, y + 1)
    return BBox(west=west, south=south, east=east, north=north)


def tile_bbox_meters(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """Return a tile's extent in EPSG:3857 metres as ``(west, south, east, north)``.

    The ordering matches ``BBox``. ★ These are addressing metres, not ground metres.
    """
    span = EARTH_CIRCUMFERENCE_M / float(1 << z)
    west = -ORIGIN_SHIFT_M + x * span
    east = west + span
    north = ORIGIN_SHIFT_M - y * span
    south = north - span
    return (west, south, east, north)


def bbox_to_tile_range(bbox: BBox, z: int) -> TileRange:
    """Return the inclusive tile rectangle covering ``bbox`` at zoom ``z``.

    Tiles whose interior the box does not reach are excluded: a box ending exactly on a
    tile boundary does not pull in the next tile.

    Args:
        bbox: An EPSG:4326 box. ★ MUST NOT cross the antimeridian.
        z: Zoom level.

    Returns:
        The covering ``TileRange``.

    Raises:
        ValueError: If ``bbox`` crosses the antimeridian. It is REJECTED, never silently
            wrapped — a wrapped box quietly enumerates the whole world the wrong way
            round. Split it with ``gis.geometry.split_antimeridian`` first.
    """
    if bbox.crosses_antimeridian:
        raise ValueError(
            "bbox crosses the antimeridian (west > east); split it with "
            "gis.geometry.split_antimeridian() and enumerate each half"
        )
    n = (1 << z) - 1
    x0_f, y_north_f = lonlat_to_tile_fractional(bbox.west, bbox.north, z)
    x1_f, y_south_f = lonlat_to_tile_fractional(bbox.east, bbox.south, z)

    min_x = max(0, min(n, int(math.floor(x0_f))))
    # ceil()-1 rather than floor(): a box whose east edge lands exactly on a boundary
    # stops at the tile it actually touches.
    max_x = max(min_x, min(n, int(math.ceil(x1_f)) - 1))
    min_y = max(0, min(n, int(math.floor(y_north_f))))
    max_y = max(min_y, min(n, int(math.ceil(y_south_f)) - 1))
    return TileRange(z=z, min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y)


def tile_range_count(rng: TileRange) -> int:
    """Return the number of tiles in a range."""
    return len(rng)


def _point_in_ring(lon: float, lat: float, ring: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon. ``ring`` is ``(lon, lat)`` vertices."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        lon_i, lat_i = ring[i]
        lon_j, lat_j = ring[j]
        if (lat_i > lat) != (lat_j > lat) and lon < (lon_j - lon_i) * (lat - lat_i) / (
            lat_j - lat_i
        ) + lon_i:
            inside = not inside
        j = i
    return inside


def _segments_cross(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> bool:
    """Do open segments ``a→b`` and ``c→d`` properly cross?"""

    def orient(p: tuple[float, float], q: tuple[float, float], r: tuple[float, float]) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    o1, o2 = orient(a, b, c), orient(a, b, d)
    o3, o4 = orient(c, d, a), orient(c, d, b)
    return o1 * o2 < 0 and o3 * o4 < 0


def _tile_overlaps_ring(
    z: int, x: int, y: int, ring: list[tuple[float, float]]
) -> bool:
    """Does tile ``(z, x, y)``'s rectangle overlap the polygon ``ring``?

    Covers all three size relationships: a tile corner inside the polygon (tile ⊆ area),
    a polygon vertex inside the tile (area ⊆ tile), and an edge crossing (partial).
    """
    west, north = tile_to_lonlat(z, x, y)
    east, south = tile_to_lonlat(z, x + 1, y + 1)
    corners = [(west, north), (east, north), (west, south), (east, south)]
    for lon, lat in corners:
        if _point_in_ring(lon, lat, ring):
            return True
    for lon, lat in ring:
        if west <= lon <= east and south <= lat <= north:
            return True
    edges = [
        (corners[0], corners[1]),
        (corners[1], corners[3]),
        (corners[3], corners[2]),
        (corners[2], corners[0]),
    ]
    j = len(ring) - 1
    for i in range(len(ring)):
        for e0, e1 in edges:
            if _segments_cross(ring[j], ring[i], e0, e1):
                return True
        j = i
    return False


def tiles_for_polygon(
    ring: list[tuple[float, float]],
    z_min: int,
    z_max: int,
    *,
    cap: int = 100_000,
) -> tuple[list[TileRef], bool]:
    """Every tile whose rectangle OVERLAPS the polygon, across ``[z_min, z_max]``.

    ★ THE AOI ENUMERATION for offline pre-caching — real intersecting XYZ tiles, never an
    area-based guess. Rectangle-overlap rather than centre-in-polygon: an AOI smaller than
    one low-zoom tile must still claim the tile that covers it, or the offline map has
    nothing to show at that zoom.

    Args:
        ring: Polygon vertices as ``(lon, lat)``, at least 3, not closed (no repeated
            last vertex needed). ★ Must not cross the antimeridian.
        z_min: Lowest zoom, inclusive.
        z_max: Highest zoom, inclusive.
        cap: Stop after this many tiles and report ``capped=True`` — a budget guard, so
            an over-ambitious AOI is a visible refusal, not a silent multi-GB download.

    Returns:
        ``(tiles, capped)`` — the tiles in ascending-zoom order, and whether ``cap``
        truncated them.

    Raises:
        ValueError: Fewer than 3 vertices, or an inverted zoom band.
    """
    if len(ring) < 3:
        raise ValueError(f"a polygon needs at least 3 vertices, got {len(ring)}")
    if z_min > z_max:
        raise ValueError(f"z_min ({z_min}) exceeds z_max ({z_max})")

    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    bbox = BBox(west=min(lons), south=min(lats), east=max(lons), north=max(lats))

    tiles: list[TileRef] = []
    for z in range(z_min, z_max + 1):
        rng = bbox_to_tile_range(bbox, z)
        for x in range(rng.min_x, rng.max_x + 1):
            for y in range(rng.min_y, rng.max_y + 1):
                if _tile_overlaps_ring(z, x, y, ring):
                    tiles.append(TileRef(z, x, y))
                    if len(tiles) >= cap:
                        return (tiles, True)
    return (tiles, False)


# --- Quadkeys ----------------------------------------------------------------


def tile_to_quadkey(z: int, x: int, y: int) -> str:
    """Return a tile's Bing quadkey. ``z = 0`` yields the empty string."""
    return TileRef(z, x, y).quadkey()


def quadkey_to_tile(quadkey: str) -> TileRef:
    """Parse a Bing quadkey back into a ``TileRef``.

    Args:
        quadkey: A string of ``"0123"`` digits. The empty string is the z0 tile.

    Returns:
        The ``TileRef`` the quadkey names.

    Raises:
        ValueError: If the string contains a character outside ``"0123"``.
    """
    z = len(quadkey)
    x = 0
    y = 0
    for i, ch in enumerate(quadkey):
        mask = 1 << (z - i - 1)
        if ch == "0":
            pass
        elif ch == "1":
            x |= mask
        elif ch == "2":
            y |= mask
        elif ch == "3":
            x |= mask
            y |= mask
        else:
            raise ValueError(f"invalid quadkey digit {ch!r} in {quadkey!r}")
    return TileRef(z, x, y)


# --- Mosaicking --------------------------------------------------------------


def stitch_tiles(
    tiles: Mapping[TileRef, np.ndarray],
    rng: TileRange,
    tile_size: int = 256,
    *,
    missing_fill: tuple[int, int, int] = (0, 0, 0),
) -> tuple[np.ndarray, GeoTransform]:
    """Assemble tiles into one mosaic with an exact EPSG:3857 geotransform.

    Args:
        tiles: Fetched tiles keyed by ``TileRef``. Tiles absent from the mapping are
            filled with ``missing_fill`` — callers track the placeholder fraction.
        rng: The tile rectangle to assemble. Defines the mosaic's extent.
        tile_size: Tile edge in pixels. Every supplied tile must match it.
        missing_fill: RGB fill for absent tiles.

    Returns:
        ``(mosaic, geotransform)`` — mosaic is ``(H, W, 3)`` uint8 RGB, C-contiguous;
        geotransform is north-up in EPSG:3857 metres.

    Raises:
        ValueError: If ``tile_size <= 0``, or a supplied tile has the wrong zoom, shape
            or dtype.
    """
    if tile_size <= 0:
        raise ValueError(f"tile_size must be > 0, got {tile_size}")

    height = rng.rows * tile_size
    width = rng.cols * tile_size
    mosaic = np.empty((height, width, 3), dtype=np.uint8)
    mosaic[:, :] = np.asarray(missing_fill, dtype=np.uint8)

    for ref, img in tiles.items():
        if ref.z != rng.z:
            raise ValueError(f"tile {ref} is not at the range's zoom {rng.z}")
        if not (rng.min_x <= ref.x <= rng.max_x and rng.min_y <= ref.y <= rng.max_y):
            continue  # outside the requested rectangle: not an error, just unused
        arr = np.asarray(img)
        if arr.shape != (tile_size, tile_size, 3):
            raise ValueError(
                f"tile {ref} has shape {arr.shape}, expected {(tile_size, tile_size, 3)}"
            )
        if arr.dtype != np.uint8:
            raise ValueError(f"tile {ref} has dtype {arr.dtype}, expected uint8")
        row0 = (ref.y - rng.min_y) * tile_size
        col0 = (ref.x - rng.min_x) * tile_size
        mosaic[row0 : row0 + tile_size, col0 : col0 + tile_size] = arr

    # The mosaic's origin is the NW corner of the NW-most tile — an EDGE, matching GDAL.
    west, _south, _east, north = tile_bbox_meters(rng.z, rng.min_x, rng.min_y)
    res = EARTH_CIRCUMFERENCE_M / (tile_size * float(1 << rng.z))
    gt: GeoTransform = (west, res, 0.0, north, 0.0, -res)
    return (np.ascontiguousarray(mosaic), gt)


def crop_to_bbox(
    mosaic: np.ndarray,
    gt: GeoTransform,
    bbox: BBox,
    *,
    crs: str = "EPSG:3857",
) -> tuple[np.ndarray, GeoTransform]:
    """Crop a mosaic to a geographic box, returning the array AND the exact geotransform.

    ★ The crop offset is FOLDED INTO THE ORIGIN, never approximated and never dropped.
    Cropping without updating the origin is the defect that produces coordinates wrong by
    up to one tile (~108 m at z18/45N) while crashing nothing and looking plausible.

    The crop is OUTWARD: the returned window is the smallest whole-pixel rectangle that
    fully contains ``bbox``, clipped to the mosaic. Cropping inward could exclude the
    very pixels the caller asked for.

    Args:
        mosaic: ``(H, W, 3)`` (or ``(H, W)``) array to crop.
        gt: The mosaic's geotransform, in ``crs``.
        bbox: The EPSG:4326 target extent. MUST NOT cross the antimeridian.
        crs: Authority string of ``gt``. Defaults to EPSG:3857 (``stitch_tiles``' output).

    Returns:
        ``(cropped, gt_cropped)``.

    Raises:
        ValueError: If ``bbox`` crosses the antimeridian, ``gt`` is singular, or the box
            does not overlap the mosaic at all.
        CrsError: If ``crs`` needs a backend that cannot be bound.
    """
    if bbox.crosses_antimeridian:
        raise ValueError("bbox crosses the antimeridian; split it before cropping")

    arr = np.asarray(mosaic)
    if arr.ndim < 2:
        raise ValueError(f"mosaic must be at least 2-D, got shape {arr.shape}")
    height, width = int(arr.shape[0]), int(arr.shape[1])

    # All four corners, so a rotated/skewed gt is handled correctly rather than assumed away.
    corners_ll = (
        (bbox.west, bbox.north),
        (bbox.east, bbox.north),
        (bbox.east, bbox.south),
        (bbox.west, bbox.south),
    )
    igt = invert_geotransform(gt)
    cols: list[float] = []
    rows: list[float] = []
    for lon, lat in corners_ll:
        x, y = _lonlat_to_projected(lon, lat, crs)
        cols.append(igt[0] + x * igt[1] + y * igt[2])
        rows.append(igt[3] + x * igt[4] + y * igt[5])

    col0 = max(0, int(math.floor(min(cols))))
    col1 = min(width, int(math.ceil(max(cols))))
    row0 = max(0, int(math.floor(min(rows))))
    row1 = min(height, int(math.ceil(max(rows))))
    if col1 <= col0 or row1 <= row0:
        raise ValueError("bbox does not overlap the mosaic")

    cropped = arr[row0:row1, col0:col1]

    # ★ THE FOLD. The new origin is the old origin advanced by the crop offset through
    #   the SAME affine — exact for rotated transforms too, not just north-up ones.
    origin_x = gt[0] + col0 * gt[1] + row0 * gt[2]
    origin_y = gt[3] + col0 * gt[4] + row0 * gt[5]
    gt_cropped: GeoTransform = (origin_x, gt[1], gt[2], origin_y, gt[4], gt[5])
    return (np.ascontiguousarray(cropped), gt_cropped)


# --- Geotransform algebra ----------------------------------------------------


def geotransform_to_affine(gt: GeoTransform) -> tuple[float, ...]:
    """Convert a GDAL 6-tuple to ``affine.Affine`` coefficient order.

    GDAL orders ``(c, a, b, f, d, e)``; Affine orders ``(a, b, c, d, e, f)`` where
    ``x = a*col + b*row + c`` and ``y = d*col + e*row + f``. Both describe the same
    EDGE-convention map; only the packing differs.

    Args:
        gt: A GDAL geotransform.

    Returns:
        ``(a, b, c, d, e, f)``, ready for ``Affine(*result)``.
    """
    return (gt[1], gt[2], gt[0], gt[4], gt[5], gt[3])


def invert_geotransform(gt: GeoTransform) -> tuple[float, ...]:
    """Return the plain affine inverse of a geotransform — EDGE convention, no half-pixel.

    The result maps a projected coordinate to fractional pixel EDGE coordinates::

        col = igt[0] + X * igt[1] + Y * igt[2]
        row = igt[3] + X * igt[4] + Y * igt[5]

    ★ NEVER use this for GCP work. It is not the inverse of ``pixel_to_lonlat`` (which is
    pixel-CENTRE); ``lonlat_to_pixel`` is. This exists for internal geometry — window
    bookkeeping, crop offsets — where the half-pixel would be wrong to apply.

    Args:
        gt: A GDAL geotransform.

    Returns:
        The 6-tuple inverse in the same packing.

    Raises:
        ValueError: If ``gt`` is singular (zero determinant).
    """
    det = gt[1] * gt[5] - gt[2] * gt[4]
    if det == 0.0 or not math.isfinite(det):
        raise ValueError(f"geotransform is singular (determinant {det}): {gt}")
    inv1 = gt[5] / det
    inv2 = -gt[2] / det
    inv4 = -gt[4] / det
    inv5 = gt[1] / det
    inv0 = -gt[0] * inv1 - gt[3] * inv2
    inv3 = -gt[0] * inv4 - gt[3] * inv5
    return (inv0, inv1, inv2, inv3, inv4, inv5)


def apply_geotransform(gt: GeoTransform, col: float, row: float) -> tuple[float, float]:
    """Map a pixel to a projected coordinate. ★ PIXEL-CENTRE convention.

    ``(col, row) = (0, 0)`` names the CENTRE of the top-left pixel::

        X = gt[0] + (col + 0.5) * gt[1] + (row + 0.5) * gt[2]
        Y = gt[3] + (col + 0.5) * gt[4] + (row + 0.5) * gt[5]

    ★ THE ONE SITE where the ``+0.5`` is applied. ``gis.tiles.pixel_to_lonlat`` and
    ``gis.crs.pixel_to_lonlat`` both route through here, so the two cannot drift apart and
    the convention cannot be half-applied.

    Args:
        gt: The raster's geotransform.
        col: Fractional pixel column.
        row: Fractional pixel row.

    Returns:
        ``(X, Y)`` in the geotransform's own projected units. NOT lon/lat.
    """
    x = gt[0] + (col + 0.5) * gt[1] + (row + 0.5) * gt[2]
    y = gt[3] + (col + 0.5) * gt[4] + (row + 0.5) * gt[5]
    return (x, y)


def unapply_geotransform(gt: GeoTransform, x: float, y: float) -> tuple[float, float]:
    """Map a projected coordinate to a pixel. ★ THE EXACT INVERSE of ``apply_geotransform``.

    Includes the ``-0.5``, so it returns pixel CENTRES.

    Args:
        gt: The raster's geotransform.
        x: Easting in the geotransform's projected units.
        y: Northing in the geotransform's projected units.

    Returns:
        ``(col, row)`` as fractional pixel-centre coordinates.

    Raises:
        ValueError: If ``gt`` is singular.
    """
    igt = invert_geotransform(gt)
    col_edge = igt[0] + x * igt[1] + y * igt[2]
    row_edge = igt[3] + x * igt[4] + y * igt[5]
    return (col_edge - 0.5, row_edge - 0.5)


def _require_closed_form(crs: str) -> str:
    """Return the normalised CRS if this module can handle it, else raise.

    ★ ``gis.tiles`` MUST NOT import ``gis.crs`` — §10.4's ``gis-tiles-pure`` contract
    forbids it, and import-linter sees a call-time import just as well as a module-scope
    one. So this module covers exactly the closed-form pair (the only transform on the hot
    path) and REFUSES anything else rather than reaching for a backend it may not touch.

    For a local orthophoto's native CRS use ``gis.crs.pixel_to_lonlat`` /
    ``gis.crs.lonlat_to_pixel``, which apply the identical ``+0.5`` (they share
    ``apply_geotransform``) and add a real projection.
    """
    key = _normalize_crs(crs)
    if key not in ("EPSG:3857", "EPSG:4326"):
        raise CrsError(
            f"gis.tiles handles EPSG:3857 and EPSG:4326 in closed form only, not {key}. "
            "gis.tiles is dependency-free by contract and may not bind a CRS backend; "
            "use gis.crs.pixel_to_lonlat / gis.crs.lonlat_to_pixel for a projected CRS."
        )
    return key


def _lonlat_to_projected(lon: float, lat: float, crs: str) -> tuple[float, float]:
    """Project lon/lat into ``crs`` using the closed form. EPSG:3857/4326 only."""
    key = _require_closed_form(crs)
    if key == "EPSG:3857":
        return lonlat_to_meters(lon, lat)
    return (lon, lat)


def _projected_to_lonlat(x: float, y: float, crs: str) -> tuple[float, float]:
    """Unproject a coordinate in ``crs`` to lon/lat. Mirror of ``_lonlat_to_projected``."""
    key = _require_closed_form(crs)
    if key == "EPSG:3857":
        return meters_to_lonlat(x, y)
    return (x, y)


def pixel_to_lonlat(gt: GeoTransform, crs: str, col: float, row: float) -> tuple[float, float]:
    """Convert a raster pixel to ``(lon, lat)`` degrees. ★ PIXEL-CENTRE convention.

    ``col = 0, row = 0`` names the CENTRE of the top-left pixel::

        X = gt[0] + (col + 0.5) * gt[1] + (row + 0.5) * gt[2]
        Y = gt[3] + (col + 0.5) * gt[4] + (row + 0.5) * gt[5]

    then ``(X, Y)`` is unprojected from ``crs`` to EPSG:4326.

    The ``+0.5`` is NOT optional. Omitting it biases every GCP by half a pixel in one
    direction — ~0.21 m at z18/45N. A systematic bias does not average out, and at the
    0.5 m consistency tolerance the GCP-adjust endpoint enforces, it spuriously rejects
    correct edits.

    Args:
        gt: The raster's geotransform.
        crs: Authority string of ``gt``.
        col: Fractional pixel column (x, grows east in a north-up raster).
        row: Fractional pixel row (y, grows SOUTH in a north-up raster).

    Returns:
        ``(lon, lat)`` in EPSG:4326 degrees.

    Raises:
        CrsError: If ``crs`` needs a backend that cannot be bound.
    """
    x, y = apply_geotransform(gt, col, row)
    return _projected_to_lonlat(x, y, crs)


def lonlat_to_pixel(gt: GeoTransform, crs: str, lon: float, lat: float) -> tuple[float, float]:
    """Convert ``(lon, lat)`` degrees to a raster pixel. ★ THE EXACT INVERSE of ``pixel_to_lonlat``.

    Includes the ``-0.5`` and therefore returns pixel CENTRES: ``(0, 0)`` names the centre
    of the top-left pixel. This being the true inverse is what makes the two GCP-adjust
    chains agree; ``invert_geotransform`` is NOT the inverse and must not be used here.

    ★ ON THE ROUND-TRIP TOLERANCE. §13.1 asks for ``< 1e-9 px`` and §13.3 asks for
    ``< 1e-6 px`` for the same property. **1e-9 px is not achievable in float64 and never
    was**: a Web-Mercator northing at 55N is ~7.4e6 m, where one float64 ULP is 9.3e-10 m
    — i.e. ~1.6e-9 px at z18. The round trip is therefore accurate to ONE ULP, which is
    the strongest true statement available, and the measured error (~1.6e-9 px, ~1e-9 m)
    is nine orders of magnitude inside the 0.5 m consistency tolerance it exists to
    protect. The suite asserts the achievable 1e-6 px and separately asserts the
    few-ULP bound.

    Args:
        gt: The raster's geotransform.
        crs: Authority string of ``gt``.
        lon: Longitude in degrees.
        lat: Latitude in degrees.

    Returns:
        ``(col, row)`` as fractional pixel-centre coordinates. May fall outside the
        raster; clamping is the caller's decision, not this function's.

    Raises:
        ValueError: If ``gt`` is singular.
        CrsError: If ``crs`` needs a backend that cannot be bound.
    """
    x, y = _lonlat_to_projected(lon, lat, crs)
    return unapply_geotransform(gt, x, y)
