"""Geographic geometry: box algebra, true-metre distance/area, antimeridian handling.

**The rule this module exists to enforce: never measure in EPSG:4326, never measure in
EPSG:3857.** Degrees are not a length unit (1 degree of longitude is 111 km at the
equator, 64 km at 55N, 0 at the pole). And Web Mercator metres are not metres — they are
inflated by ``1/cos(phi)``, i.e. 74% at 55N, which is Yorkshire, Denmark, southern Sweden
and the Canadian prairie belt.

Every function here that returns a distance, an area or an RMSE ends in ``_m``/``_m2``
and transforms to a local UTM zone first. A ``_m`` function that silently accepted
degrees would return numbers that look like metres and are not — the failure mode this
module exists to prevent.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from gis.crs import is_ground_metric_crs, transform_points, utm_epsg_for
from gis.errors import NonMetricCrsError
from gis.tiles import EARTH_RADIUS_M
from gis.types import BBox, LonLat

__all__ = [
    "bbox_contains_bbox",
    "bbox_from_points",
    "bbox_intersection",
    "bbox_to_utm_epsg",
    "bbox_union",
    "buffer_bbox_m",
    "crosses_antimeridian",
    "disc_to_bbox",
    "distance_m",
    "great_circle_distance_m",
    "polygon_area_m2",
    "split_antimeridian",
]


def bbox_from_points(points: Sequence[LonLat]) -> BBox:
    """Return the tightest box containing every point.

    ★ Does NOT attempt antimeridian detection: a set of points spanning the Pacific is
    indistinguishable from one spanning the globe, and guessing is how a box silently
    becomes 359 degrees wide. Callers that work across +/-180 must say so explicitly.

    Args:
        points: One or more geographic positions.

    Returns:
        The bounding ``BBox``.

    Raises:
        ValueError: If ``points`` is empty.
    """
    if not points:
        raise ValueError("bbox_from_points requires at least one point")
    lons = [p.lon for p in points]
    lats = [p.lat for p in points]
    return BBox(west=min(lons), south=min(lats), east=max(lons), north=max(lats))


def bbox_union(a: BBox, b: BBox) -> BBox:
    """Return the smallest box containing both inputs.

    Raises:
        ValueError: If either box crosses the antimeridian — split them first.
    """
    if a.crosses_antimeridian or b.crosses_antimeridian:
        raise ValueError("bbox_union does not accept antimeridian-crossing boxes; split them first")
    return BBox(
        west=min(a.west, b.west),
        south=min(a.south, b.south),
        east=max(a.east, b.east),
        north=max(a.north, b.north),
    )


def bbox_intersection(a: BBox, b: BBox) -> BBox | None:
    """Return the overlap of two boxes, or None if they are disjoint.

    Boxes that touch only at an edge or corner count as disjoint (zero area).

    Raises:
        ValueError: If either box crosses the antimeridian.
    """
    if a.crosses_antimeridian or b.crosses_antimeridian:
        raise ValueError(
            "bbox_intersection does not accept antimeridian-crossing boxes; split them first"
        )
    west = max(a.west, b.west)
    east = min(a.east, b.east)
    south = max(a.south, b.south)
    north = min(a.north, b.north)
    if west >= east or south >= north:
        return None
    return BBox(west=west, south=south, east=east, north=north)


def bbox_contains_bbox(outer: BBox, inner: BBox) -> bool:
    """True iff ``inner`` lies entirely within ``outer``, edges inclusive."""
    if outer.crosses_antimeridian or inner.crosses_antimeridian:
        raise ValueError("bbox_contains_bbox does not accept antimeridian-crossing boxes")
    return (
        outer.west <= inner.west
        and outer.east >= inner.east
        and outer.south <= inner.south
        and outer.north >= inner.north
    )


def crosses_antimeridian(west: float, east: float) -> bool:
    """True iff a west/east pair describes a region wrapping across +/-180."""
    return west > east


def split_antimeridian(west: float, south: float, east: float, north: float) -> tuple[BBox, ...]:
    """Split a possibly-wrapping extent into one or two non-wrapping boxes.

    ★ Splitting is the ONLY sanctioned way to handle the antimeridian in this codebase.
    ``gis.tiles.bbox_to_tile_range`` rejects a wrapping box rather than guessing, because
    a silently-wrapped box enumerates the whole world the wrong way round — and
    agriculture happens in New Zealand and Fiji too.

    Args:
        west: Western longitude in degrees.
        south: Southern latitude in degrees.
        east: Eastern longitude in degrees. If ``east < west`` the extent wraps.
        north: Northern latitude in degrees.

    Returns:
        A 1-tuple for a normal extent, or a 2-tuple ``(western_part, eastern_part)``
        split at the antimeridian.
    """
    if not crosses_antimeridian(west, east):
        return (BBox(west=west, south=south, east=east, north=north),)
    return (
        BBox(west=west, south=south, east=180.0, north=north),
        BBox(west=-180.0, south=south, east=east, north=north),
    )


def bbox_to_utm_epsg(bbox: BBox) -> str:
    """Return the UTM zone EPSG best suited to measuring inside ``bbox``.

    Chosen from the box CENTRE, so error is symmetric across the extent rather than
    piling up at one edge.

    Raises:
        OutsideUtmError: If the centre is beyond ``|lat| = 84``.
    """
    lon, lat = bbox.center()
    return utm_epsg_for(lon, lat)


def great_circle_distance_m(a: LonLat, b: LonLat) -> float:
    """Return the great-circle distance between two points, in metres.

    Uses the haversine formula on a sphere of radius ``EARTH_RADIUS_M``. Accurate to
    ~0.3% against the WGS84 ellipsoid — which is right for coarse work like filtering a
    tile list against a search disc, and NOT right for reporting a survey number. Use
    ``distance_m`` for anything a surveyor reads.

    Args:
        a: First position.
        b: Second position.

    Returns:
        Distance in true metres.
    """
    phi1 = math.radians(a.lat)
    phi2 = math.radians(b.lat)
    dphi = phi2 - phi1
    dlam = math.radians(b.lon - a.lon)
    h = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_M * math.asin(math.sqrt(min(1.0, h)))


def distance_m(a: LonLat, b: LonLat, *, crs: str | None = None) -> float:
    """Return the distance between two points in TRUE ground metres, measured in UTM.

    Args:
        a: First position, EPSG:4326.
        b: Second position, EPSG:4326.
        crs: Metric CRS to measure in. Defaults to the UTM zone of the midpoint.

    Returns:
        Distance in true metres.

    Raises:
        NonMetricCrsError: If ``crs`` is given and is not a true-ground-metre CRS. Passing
            EPSG:4326 (degrees) or EPSG:3857 (inflated metres) is rejected, not silently
            measured.
        OutsideUtmError: If the midpoint is beyond ``|lat| = 84`` and no ``crs`` is given.
    """
    if crs is None:
        crs = utm_epsg_for((a.lon + b.lon) / 2.0, (a.lat + b.lat) / 2.0)
    elif not is_ground_metric_crs(crs):
        raise NonMetricCrsError(
            f"{crs} does not measure in true ground metres; distance_m refuses it. "
            "EPSG:4326 is degrees and EPSG:3857 is inflated by 1/cos(phi) (74% at 55N)."
        )
    xs, ys = transform_points(
        np.asarray([a.lon, b.lon], dtype=np.float64),
        np.asarray([a.lat, b.lat], dtype=np.float64),
        "EPSG:4326",
        crs,
    )
    return float(math.hypot(xs[1] - xs[0], ys[1] - ys[0]))


def polygon_area_m2(ring: Sequence[LonLat], *, crs: str | None = None) -> float:
    """Return a polygon's area in TRUE square metres, measured in UTM.

    The ring may be open or closed; orientation is irrelevant (the result is absolute).

    Args:
        ring: The polygon's exterior ring, EPSG:4326, at least 3 distinct points.
        crs: Metric CRS to measure in. Defaults to the UTM zone of the ring's centroid.

    Returns:
        Area in true square metres.

    Raises:
        ValueError: If the ring has fewer than 3 points.
        NonMetricCrsError: If ``crs`` is given and does not measure in ground metres.
    """
    pts = list(ring)
    if len(pts) >= 2 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) < 3:
        raise ValueError(f"a polygon ring needs at least 3 distinct points, got {len(pts)}")

    if crs is None:
        crs = utm_epsg_for(
            sum(p.lon for p in pts) / len(pts), sum(p.lat for p in pts) / len(pts)
        )
    elif not is_ground_metric_crs(crs):
        raise NonMetricCrsError(
            f"{crs} does not measure in true ground metres; polygon_area_m2 refuses it."
        )

    xs, ys = transform_points(
        np.asarray([p.lon for p in pts], dtype=np.float64),
        np.asarray([p.lat for p in pts], dtype=np.float64),
        "EPSG:4326",
        crs,
    )
    # Shoelace.
    return float(abs(np.dot(xs, np.roll(ys, -1)) - np.dot(ys, np.roll(xs, -1))) / 2.0)


def buffer_bbox_m(bbox: BBox, meters: float) -> BBox:
    """Return ``bbox`` grown by ``meters`` on every side. See ``BBox.buffered_m``."""
    return bbox.buffered_m(meters)


def disc_to_bbox(center: LonLat, radius_m: float) -> BBox:
    """Return the smallest box containing a geodesic disc.

    ★ The box OVER-covers the disc by ~4/pi (~27%). Callers enumerating tiles should
    filter the result against the true distance; at high zoom that 27% is real money and
    real latency.

    Args:
        center: The disc's centre.
        radius_m: Radius in true metres, ``>= 0``.

    Returns:
        The bounding ``BBox``, clamped to the valid lon/lat domain.

    Raises:
        ValueError: If ``radius_m`` is negative or not finite.
    """
    if not math.isfinite(radius_m) or radius_m < 0.0:
        raise ValueError(f"radius_m must be finite and >= 0, got {radius_m}")
    point = BBox(west=center.lon, south=center.lat, east=center.lon, north=center.lat)
    return point.buffered_m(radius_m)
