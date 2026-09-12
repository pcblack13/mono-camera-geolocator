"""Tests for ``gis.geometry`` — box algebra, true-metre metrics, the antimeridian.

★ The rule under test: **never measure in 4326, never measure in 3857.** Every ``_m``
function must transform to UTM first and must REFUSE a CRS that would return numbers that
look like metres and are not.

(Not named in §13.1's IU-09 list, which enumerates the modules with goldens. ``geometry.py``
is IU-09-owned and metric, so it is tested here rather than left to a downstream unit to
discover.)
"""

from __future__ import annotations

import math

import pytest

from gis.crs import backend_name
from gis.errors import NonMetricCrsError, OutsideUtmError
from gis.geometry import (
    bbox_contains_bbox,
    bbox_from_points,
    bbox_intersection,
    bbox_to_utm_epsg,
    bbox_union,
    buffer_bbox_m,
    crosses_antimeridian,
    disc_to_bbox,
    distance_m,
    great_circle_distance_m,
    polygon_area_m2,
    split_antimeridian,
)
from gis.types import BBox, LonLat

_HAVE_FULL_BACKEND = backend_name() in ("pyproj", "osr")
_needs_utm = pytest.mark.skipif(not _HAVE_FULL_BACKEND, reason="UTM metrics need pyproj or osr")


class TestBBoxAlgebra:
    def test_from_points(self) -> None:
        box = bbox_from_points([LonLat(1.0, 10.0), LonLat(-2.0, 5.0), LonLat(3.0, 7.0)])
        assert box == BBox(west=-2.0, south=5.0, east=3.0, north=10.0)

    def test_from_points_rejects_empty(self) -> None:
        with pytest.raises(ValueError):
            bbox_from_points([])

    def test_union(self) -> None:
        a = BBox(0.0, 0.0, 1.0, 1.0)
        b = BBox(2.0, 2.0, 3.0, 3.0)
        assert bbox_union(a, b) == BBox(0.0, 0.0, 3.0, 3.0)

    def test_intersection(self) -> None:
        a = BBox(0.0, 0.0, 2.0, 2.0)
        b = BBox(1.0, 1.0, 3.0, 3.0)
        assert bbox_intersection(a, b) == BBox(1.0, 1.0, 2.0, 2.0)

    def test_disjoint_intersection_is_none(self) -> None:
        assert bbox_intersection(BBox(0.0, 0.0, 1.0, 1.0), BBox(2.0, 2.0, 3.0, 3.0)) is None

    def test_edge_touching_counts_as_disjoint(self) -> None:
        """A zero-area overlap is not an overlap; returning it invites divide-by-zero."""
        assert bbox_intersection(BBox(0.0, 0.0, 1.0, 1.0), BBox(1.0, 0.0, 2.0, 1.0)) is None

    def test_contains(self) -> None:
        outer = BBox(0.0, 0.0, 10.0, 10.0)
        assert bbox_contains_bbox(outer, BBox(1.0, 1.0, 2.0, 2.0))
        assert bbox_contains_bbox(outer, outer)
        assert not bbox_contains_bbox(outer, BBox(-1.0, 1.0, 2.0, 2.0))

    def test_bbox_contains_point(self) -> None:
        box = BBox(0.0, 0.0, 10.0, 10.0)
        assert box.contains(5.0, 5.0)
        assert box.contains(0.0, 0.0)  # edges inclusive
        assert not box.contains(11.0, 5.0)

    def test_centre(self) -> None:
        assert BBox(0.0, 0.0, 10.0, 20.0).center() == (5.0, 10.0)

    def test_rejects_inverted_latitude(self) -> None:
        with pytest.raises(ValueError, match="south"):
            BBox(0.0, 10.0, 1.0, 5.0)

    def test_rejects_out_of_domain(self) -> None:
        with pytest.raises(ValueError):
            BBox(-181.0, 0.0, 1.0, 1.0)
        with pytest.raises(ValueError):
            BBox(0.0, -91.0, 1.0, 1.0)


class TestAntimeridian:
    """★ Split it, or reject it. Never silently wrap it."""

    def test_detection(self) -> None:
        assert crosses_antimeridian(179.0, -179.0)
        assert not crosses_antimeridian(-179.0, 179.0)
        assert BBox(179.0, -1.0, -179.0, 1.0).crosses_antimeridian

    def test_split_produces_two_boxes(self) -> None:
        parts = split_antimeridian(179.0, -1.0, -179.0, 1.0)
        assert len(parts) == 2
        assert parts[0] == BBox(179.0, -1.0, 180.0, 1.0)
        assert parts[1] == BBox(-180.0, -1.0, -179.0, 1.0)
        assert not any(p.crosses_antimeridian for p in parts)

    def test_split_is_a_no_op_for_a_normal_box(self) -> None:
        parts = split_antimeridian(10.0, -1.0, 20.0, 1.0)
        assert parts == (BBox(10.0, -1.0, 20.0, 1.0),)

    def test_split_preserves_total_width(self) -> None:
        parts = split_antimeridian(170.0, -1.0, -170.0, 1.0)
        total = sum(p.east - p.west for p in parts)
        assert total == pytest.approx(20.0)

    def test_crossing_centre_wraps_correctly(self) -> None:
        """The centre of [179, -179] is 180/-180, not 0 in the middle of Africa."""
        lon, _ = BBox(179.0, -1.0, -179.0, 1.0).center()
        assert abs(lon) == pytest.approx(180.0)

    def test_crossing_contains(self) -> None:
        box = BBox(179.0, -1.0, -179.0, 1.0)
        assert box.contains(179.5, 0.0)
        assert box.contains(-179.5, 0.0)
        assert not box.contains(0.0, 0.0)

    def test_union_refuses_a_crossing_box(self) -> None:
        with pytest.raises(ValueError, match="antimeridian"):
            bbox_union(BBox(179.0, -1.0, -179.0, 1.0), BBox(0.0, 0.0, 1.0, 1.0))


class TestArea:
    def test_bbox_area_is_the_spherical_zone(self) -> None:
        """Exact on a sphere: A = R^2 * dlon * (sin(north) - sin(south))."""
        box = BBox(0.0, 0.0, 1.0, 1.0)
        r = 6378137.0
        expected = r**2 * math.radians(1.0) * (math.sin(math.radians(1.0)) - 0.0)
        assert box.area_m2() == pytest.approx(expected, rel=1e-12)

    def test_one_degree_at_the_equator(self) -> None:
        """~111 km x ~111 km = ~1.23e10 m2. A well-known figure."""
        assert BBox(0.0, 0.0, 1.0, 1.0).area_m2() == pytest.approx(1.23e10, rel=0.02)

    def test_area_shrinks_toward_the_pole(self) -> None:
        """★ THE property a 3857 area computation gets backwards."""
        equator = BBox(0.0, 0.0, 1.0, 1.0).area_m2()
        high = BBox(0.0, 60.0, 1.0, 61.0).area_m2()
        assert high < equator
        assert high / equator == pytest.approx(math.cos(math.radians(60.5)), rel=0.01)

    def test_zero_width_box_has_zero_area(self) -> None:
        assert BBox(5.0, 5.0, 5.0, 5.0).area_m2() == 0.0


class TestBuffer:
    def test_buffer_grows_the_box(self) -> None:
        box = BBox(10.0, 50.0, 11.0, 51.0)
        grown = buffer_bbox_m(box, 1000.0)
        assert grown.west < box.west
        assert grown.east > box.east
        assert grown.south < box.south
        assert grown.north > box.north

    def test_latitude_buffer_is_about_right(self) -> None:
        """1000 m north is ~0.009 degrees of latitude, everywhere."""
        grown = BBox(10.0, 50.0, 10.0, 50.0).buffered_m(1000.0)
        assert grown.north - 50.0 == pytest.approx(0.00899, rel=0.01)

    def test_longitude_buffer_widens_with_latitude(self) -> None:
        """★ 1000 m of longitude is more DEGREES at 60N than at the equator."""
        at_eq = BBox(0.0, 0.0, 0.0, 0.0).buffered_m(1000.0)
        at_60 = BBox(0.0, 60.0, 0.0, 60.0).buffered_m(1000.0)
        assert (at_60.east - at_60.west) > (at_eq.east - at_eq.west)
        assert (at_60.east - at_60.west) == pytest.approx(
            (at_eq.east - at_eq.west) / math.cos(math.radians(60.0)), rel=0.05
        )

    def test_buffer_uses_the_worst_case_latitude(self) -> None:
        """★ The result must CONTAIN the true buffer, never approximate it from the middle.

        Under-covering silently excludes the correct answer from a search.
        """
        box = BBox(0.0, 50.0, 1.0, 60.0)
        grown = box.buffered_m(1000.0)
        # The widening must be computed at 60N (the smallest cos), not at 50 or 55.
        expected = 1000.0 / (math.pi * 6378137.0 / 180.0 * math.cos(math.radians(60.0)))
        assert box.west - grown.west == pytest.approx(expected, rel=1e-6)

    def test_buffer_is_clamped_to_the_domain(self) -> None:
        grown = BBox(0.0, 0.0, 1.0, 1.0).buffered_m(20_000_000.0)
        assert grown.west >= -180.0
        assert grown.east <= 180.0
        assert grown.south >= -90.0
        assert grown.north <= 90.0

    def test_negative_buffer_shrinks(self) -> None:
        shrunk = BBox(0.0, 0.0, 1.0, 1.0).buffered_m(-1000.0)
        assert shrunk.west > 0.0
        assert shrunk.east < 1.0


class TestDisc:
    def test_disc_bbox_contains_the_centre(self) -> None:
        box = disc_to_bbox(LonLat(10.0, 55.0), 500.0)
        assert box.contains(10.0, 55.0)

    def test_disc_bbox_over_covers(self) -> None:
        """A bbox over a disc over-covers by ~4/pi. Callers filter by true distance."""
        box = disc_to_bbox(LonLat(10.0, 0.0), 1000.0)
        assert box.north == pytest.approx(0.00899, rel=0.01)

    def test_rejects_negative_radius(self) -> None:
        with pytest.raises(ValueError, match="radius_m"):
            disc_to_bbox(LonLat(0.0, 0.0), -1.0)


class TestGreatCircle:
    def test_known_distance(self) -> None:
        """London to Paris is ~344 km."""
        d = great_circle_distance_m(LonLat(-0.1278, 51.5074), LonLat(2.3522, 48.8566))
        assert d == pytest.approx(343_500.0, rel=0.01)

    def test_one_degree_of_latitude(self) -> None:
        """One degree on OUR sphere is ``R * radians(1)`` with ``R = EARTH_RADIUS_M``.

        ★ That is 111_319.49 m, not the 111_195 m often quoted — the latter uses the MEAN
        Earth radius (6_371_008 m) while we use the WGS84 semi-major (6_378_137 m), which
        is the radius EPSG:3857 projects. The 0.11% difference is deliberate consistency
        with ``gis.tiles``: one sphere everywhere beats a more "accurate" constant that
        disagrees with the tile math. This is a coarse filter anyway — ``distance_m``
        (UTM, on the ellipsoid) is what a surveyor reads.
        """
        d = great_circle_distance_m(LonLat(0.0, 0.0), LonLat(0.0, 1.0))
        assert d == pytest.approx(math.radians(1.0) * 6_378_137.0, rel=1e-12)
        assert d == pytest.approx(111_319.49, rel=1e-6)

    def test_zero_distance(self) -> None:
        assert great_circle_distance_m(LonLat(5.0, 5.0), LonLat(5.0, 5.0)) == 0.0

    def test_is_symmetric(self) -> None:
        a, b = LonLat(10.0, 55.0), LonLat(11.0, 56.0)
        assert great_circle_distance_m(a, b) == pytest.approx(great_circle_distance_m(b, a))


@_needs_utm
class TestMetricGate:
    """★ A ``_m`` function must REFUSE a CRS whose metres are not metres."""

    def test_distance_refuses_4326(self) -> None:
        with pytest.raises(NonMetricCrsError, match="degrees"):
            distance_m(LonLat(10.0, 55.0), LonLat(11.0, 55.0), crs="EPSG:4326")

    def test_distance_refuses_3857(self) -> None:
        """★ THE ONE THAT MATTERS. 3857's linear unit IS the metre — and it is 74% wrong at 55N."""
        with pytest.raises(NonMetricCrsError, match="cos"):
            distance_m(LonLat(10.0, 55.0), LonLat(11.0, 55.0), crs="EPSG:3857")

    def test_area_refuses_3857(self) -> None:
        ring = [LonLat(10.0, 55.0), LonLat(10.01, 55.0), LonLat(10.01, 55.01)]
        with pytest.raises(NonMetricCrsError):
            polygon_area_m2(ring, crs="EPSG:3857")

    def test_distance_accepts_utm(self) -> None:
        d = distance_m(LonLat(15.0, 55.0), LonLat(15.0, 55.0), crs="EPSG:32633")
        assert d == pytest.approx(0.0, abs=1e-6)


@_needs_utm
class TestTrueMetrics:
    def test_distance_matches_the_great_circle_at_short_range(self) -> None:
        """UTM and the great circle must agree closely over an AOI-sized baseline."""
        a, b = LonLat(15.0, 55.0), LonLat(15.02, 55.01)
        assert distance_m(a, b) == pytest.approx(great_circle_distance_m(a, b), rel=1e-3)

    def test_one_degree_of_latitude_is_111km(self) -> None:
        d = distance_m(LonLat(15.0, 55.0), LonLat(15.0, 56.0))
        assert d == pytest.approx(111_000.0, rel=0.01)

    def test_distance_is_not_inflated_like_3857(self) -> None:
        """★ The contrast, measured. In 3857 at 55N this would read ~74% larger."""
        from gis.tiles import lonlat_to_meters

        d_true = distance_m(LonLat(15.0, 55.0), LonLat(15.0, 56.0))
        (_, y0), (_, y1) = lonlat_to_meters(15.0, 55.0), lonlat_to_meters(15.0, 56.0)
        d_mercator = abs(y1 - y0)
        assert d_mercator / d_true > 1.5
        assert d_true == pytest.approx(111_000.0, rel=0.01)

    def test_square_area(self) -> None:
        """A ~1 km square must measure ~1e6 m2."""
        d = 0.01  # ~1.1 km of latitude
        ring = [
            LonLat(15.0, 55.0),
            LonLat(15.0 + d / math.cos(math.radians(55.0)), 55.0),
            LonLat(15.0 + d / math.cos(math.radians(55.0)), 55.0 + d),
            LonLat(15.0, 55.0 + d),
        ]
        area = polygon_area_m2(ring)
        assert area == pytest.approx(1.11e3 * 1.11e3, rel=0.02)

    def test_area_ignores_winding_order(self) -> None:
        ring = [LonLat(15.0, 55.0), LonLat(15.01, 55.0), LonLat(15.01, 55.01), LonLat(15.0, 55.01)]
        assert polygon_area_m2(ring) == pytest.approx(polygon_area_m2(list(reversed(ring))))

    def test_area_accepts_a_closed_ring(self) -> None:
        open_ring = [LonLat(15.0, 55.0), LonLat(15.01, 55.0), LonLat(15.01, 55.01)]
        closed = [*open_ring, open_ring[0]]
        assert polygon_area_m2(open_ring) == pytest.approx(polygon_area_m2(closed))

    def test_area_rejects_a_degenerate_ring(self) -> None:
        with pytest.raises(ValueError, match="at least 3"):
            polygon_area_m2([LonLat(15.0, 55.0), LonLat(15.01, 55.0)])


class TestUtmSelection:
    def test_bbox_utm_is_chosen_from_the_centre(self) -> None:
        assert bbox_to_utm_epsg(BBox(14.0, 54.0, 16.0, 56.0)) == "EPSG:32633"

    def test_polar_bbox_is_rejected(self) -> None:
        with pytest.raises(OutsideUtmError):
            bbox_to_utm_epsg(BBox(0.0, 85.0, 1.0, 86.0))
