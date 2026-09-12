"""Golden-value tests for ``gis.tiles`` (§13.1 IU-09, §13.3).

★ These are the product's safety net for every coordinate it will ever emit.

**Numbers, not tolerances.** The goldens here are checked against published references
and against first-principles arithmetic — never against our own implementation. A test
written to agree with the code it tests proves only that the code is self-consistent,
which is exactly how the half-pixel and the hardcoded-256 bugs survive.
"""

from __future__ import annotations

import math
import subprocess
import sys

import numpy as np
import pytest

from gis.tiles import (
    EARTH_CIRCUMFERENCE_M,
    EARTH_RADIUS_M,
    MAX_LATITUDE,
    ORIGIN_SHIFT_M,
    RESOLUTION_Z0_256,
    bbox_to_tile_range,
    choose_zoom,
    crop_to_bbox,
    invert_geotransform,
    lonlat_to_meters,
    lonlat_to_pixel,
    lonlat_to_tile,
    lonlat_to_tile_fractional,
    meters_to_lonlat,
    pixel_to_lonlat,
    quadkey_to_tile,
    resolution_at,
    stitch_tiles,
    tile_bbox_lonlat,
    tile_to_lonlat,
    tile_to_quadkey,
    zoom_for_resolution,
)
from gis.types import BBox, TileRange, TileRef


class TestConstants:
    """The constants are DEFINITIONS, not measurements. Exact float equality."""

    def test_constants(self) -> None:
        assert EARTH_RADIUS_M == 6378137.0
        assert EARTH_CIRCUMFERENCE_M == 40075016.685578488
        assert ORIGIN_SHIFT_M == 20037508.342789244
        assert MAX_LATITUDE == 85.0511287798066
        assert RESOLUTION_Z0_256 == 156543.03392804097

    def test_constants_are_internally_derived(self) -> None:
        """Each constant must equal its own definition, bit for bit."""
        assert EARTH_CIRCUMFERENCE_M == 2.0 * math.pi * EARTH_RADIUS_M
        assert ORIGIN_SHIFT_M == EARTH_CIRCUMFERENCE_M / 2.0
        assert RESOLUTION_Z0_256 == EARTH_CIRCUMFERENCE_M / 256.0
        assert MAX_LATITUDE == math.degrees(math.atan(math.sinh(math.pi)))


class TestOsmGoldens:
    """Published slippy tile numbers, both hemispheres, both sides of the prime meridian."""

    # (name, lon, lat, z, expected_x, expected_y)
    #
    # ★ CONTRACT DEVIATION, VERIFIED BY HAND. CONTRACT.md §13.3 states the London golden
    #   as TileRef(12, 2047, 1362). That x is ARITHMETICALLY WRONG and the contract's own
    #   formula proves it:
    #       x = (lon + 180) / 360 * 2**z
    #         = (-0.1278 + 180) / 360 * 4096
    #         = (179.8722 / 360) * 4096
    #         = 0.499645  * 4096
    #         = 2046.5459...   -> floor -> 2046, NOT 2047.
    #   The y value (1362) is correct. Bending the implementation to satisfy a wrong
    #   golden would put a real one-tile (~9.8 km at z12) error into every coordinate the
    #   product emits, which is precisely what §4.18's ruling on the VOID NW-corner
    #   invariant warns about: a test "written to pass" forcing correct code out.
    GOLDENS = [
        ("London", -0.1278, 51.5074, 12, 2046, 1362),
        ("London z0", -0.1278, 51.5074, 0, 0, 0),
        ("Greenwich prime meridian, east side", 0.0001, 51.4779, 12, 2048, 1362),
        ("Greenwich prime meridian, west side", -0.0001, 51.4779, 12, 2047, 1362),
        ("New York", -74.0060, 40.7128, 12, 1205, 1540),
        ("Sydney (S hemisphere)", 151.2093, -33.8688, 12, 3768, 2457),
        ("Rio de Janeiro (S, W)", -43.1729, -22.9068, 12, 1556, 2315),
        ("Nairobi (S, E, near equator)", 36.8219, -1.2921, 12, 2466, 2062),
        ("Tokyo", 139.6917, 35.6895, 12, 3637, 1612),
        ("Cape Town", 18.4241, -33.9249, 12, 2257, 2458),
        ("Reykjavik (high N)", -21.8277, 64.1265, 12, 1799, 1089),
        ("Null Island", 0.0, 0.0, 1, 1, 1),
        ("Origin corner", -180.0, MAX_LATITUDE, 1, 0, 0),
    ]

    @pytest.mark.parametrize(("name", "lon", "lat", "z", "exp_x", "exp_y"), GOLDENS)
    def test_osm_goldens(
        self, name: str, lon: float, lat: float, z: int, exp_x: int, exp_y: int
    ) -> None:
        assert lonlat_to_tile(lon, lat, z) == TileRef(z, exp_x, exp_y), name

    @pytest.mark.parametrize(("name", "lon", "lat", "z", "exp_x", "exp_y"), GOLDENS)
    def test_goldens_against_first_principles(
        self, name: str, lon: float, lat: float, z: int, exp_x: int, exp_y: int
    ) -> None:
        """Recompute each golden from the published slippy formula, independently.

        This is the check that would have caught the contract's London typo.
        """
        n = 2**z
        x = int(math.floor((lon + 180.0) / 360.0 * n))
        lat_rad = math.radians(max(-MAX_LATITUDE, min(MAX_LATITUDE, lat)))
        y = int(
            math.floor(
                (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi)
                / 2.0
                * n
            )
        )
        x = max(0, min(n - 1, x))
        y = max(0, min(n - 1, y))
        assert (x, y) == (exp_x, exp_y), f"{name}: golden disagrees with the published formula"

    def test_y_increases_southward(self) -> None:
        """★ The single easiest sign to get backwards. TMS flips y; slippy does not."""
        north = lonlat_to_tile(0.0, 60.0, 8)
        south = lonlat_to_tile(0.0, 20.0, 8)
        assert north.y < south.y

    def test_x_increases_eastward(self) -> None:
        west = lonlat_to_tile(-100.0, 0.0, 8)
        east = lonlat_to_tile(100.0, 0.0, 8)
        assert west.x < east.x

    def test_plus_180_is_the_east_edge_not_the_west(self) -> None:
        """★ REGRESSION: ``lon = +180`` must NOT fold onto ``-180``.

        A naive ``((lon + 180) % 360) - 180`` sends the east edge of the world to tile
        x = 0 — the WEST-most tile — and projects it to ``-ORIGIN_SHIFT_M``. Agriculture
        happens in Fiji and New Zealand, and this is the one longitude nobody checks.
        """
        for z in (1, 2, 8, 12):
            n = 2**z
            assert lonlat_to_tile(180.0, 0.0, z).x == n - 1, f"+180 at z={z}"
            assert lonlat_to_tile(-180.0, 0.0, z).x == 0, f"-180 at z={z}"
        assert lonlat_to_meters(180.0, 0.0)[0] == pytest.approx(ORIGIN_SHIFT_M, rel=1e-12)
        assert lonlat_to_meters(-180.0, 0.0)[0] == pytest.approx(-ORIGIN_SHIFT_M, rel=1e-12)

    def test_out_of_range_longitude_still_wraps(self) -> None:
        """190 degrees is genuinely out of range and IS the same place as -170."""
        assert lonlat_to_tile(190.0, 0.0, 8) == lonlat_to_tile(-170.0, 0.0, 8)
        assert lonlat_to_tile(-190.0, 0.0, 8) == lonlat_to_tile(170.0, 0.0, 8)


class TestRoundTrip:
    """``lonlat -> tile_fractional -> lonlat`` must be exact to 1e-9 degrees."""

    @pytest.mark.parametrize("z", list(range(0, 23)))
    @pytest.mark.parametrize("lat", [-85.0, -60.0, -33.9, -1.0, 0.0, 1.0, 45.0, 55.0, 85.0])
    @pytest.mark.parametrize("lon", [-179.9, -100.0, -0.1278, 0.0, 0.1, 100.0, 179.9])
    def test_roundtrip(self, z: int, lat: float, lon: float) -> None:
        x, y = lonlat_to_tile_fractional(lon, lat, z)
        from gis.tiles import _tile_to_lonlat_f

        lon2, lat2 = _tile_to_lonlat_f(z, x, y)
        assert abs(lon2 - lon) < 1e-9, f"lon drift at z={z}"
        assert abs(lat2 - lat) < 1e-9, f"lat drift at z={z}"

    def test_tile_to_lonlat_is_nw_corner(self) -> None:
        """``tile_to_lonlat`` names the NW corner: north and west of the tile's centre."""
        from gis.tiles import tile_to_lonlat_center

        corner_lon, corner_lat = tile_to_lonlat(10, 511, 340)
        centre_lon, centre_lat = tile_to_lonlat_center(10, 511, 340)
        assert corner_lon < centre_lon
        assert corner_lat > centre_lat


class TestMercator:
    """Closed-form 4326 <-> 3857."""

    def test_origin(self) -> None:
        assert lonlat_to_meters(0.0, 0.0) == (0.0, 0.0)

    def test_world_edges(self) -> None:
        mx, _ = lonlat_to_meters(180.0, 0.0)
        assert mx == pytest.approx(ORIGIN_SHIFT_M, rel=1e-12)
        mx, _ = lonlat_to_meters(-180.0, 0.0)
        assert mx == pytest.approx(-ORIGIN_SHIFT_M, rel=1e-12)
        _, my = lonlat_to_meters(0.0, MAX_LATITUDE)
        assert my == pytest.approx(ORIGIN_SHIFT_M, rel=1e-9)

    @pytest.mark.parametrize("lon", [-179.0, -45.0, 0.0, 45.0, 179.0])
    @pytest.mark.parametrize("lat", [-85.0, -45.0, 0.0, 45.0, 55.0, 85.0])
    def test_roundtrip(self, lon: float, lat: float) -> None:
        mx, my = lonlat_to_meters(lon, lat)
        lon2, lat2 = meters_to_lonlat(mx, my)
        assert lon2 == pytest.approx(lon, abs=1e-9)
        assert lat2 == pytest.approx(lat, abs=1e-9)

    def test_vectorised_matches_scalar(self) -> None:
        from gis.tiles import lonlat_to_meters_array

        lons = np.array([-179.0, 0.0, 45.0, 179.0])
        lats = np.array([-85.0, 0.0, 55.0, 85.0])
        vx, vy = lonlat_to_meters_array(lons, lats)
        for i in range(len(lons)):
            sx, sy = lonlat_to_meters(float(lons[i]), float(lats[i]))
            assert vx[i] == pytest.approx(sx, rel=1e-15)
            assert vy[i] == pytest.approx(sy, rel=1e-15)


class TestResolution:
    """``resolution_at`` against the published res(z, phi) table."""

    @pytest.mark.parametrize("z", list(range(0, 23)))
    @pytest.mark.parametrize("lat", [0.0, 30.0, 45.0, 53.0, 60.0, 85.0])
    def test_resolution_table(self, z: int, lat: float) -> None:
        """The published formula: res = 156543.03392804097 * cos(phi) / 2**z at S=256."""
        expected = RESOLUTION_Z0_256 * math.cos(math.radians(lat)) / (2**z)
        assert resolution_at(z, lat, 256) == pytest.approx(expected, rel=1e-6)

    def test_known_values(self) -> None:
        """Spot values every GIS practitioner knows."""
        assert resolution_at(0, 0.0, 256) == pytest.approx(156543.034, rel=1e-8)
        assert resolution_at(18, 0.0, 256) == pytest.approx(0.5971642834779395, rel=1e-12)
        # ★ THE accuracy golden's input.
        assert resolution_at(18, 55.0, 256) == 0.34251936163340246

    def test_tile_size_halves_resolution(self) -> None:
        """A 512px tile covers the same ground at half the metres per pixel."""
        assert resolution_at(18, 45.0, 512) == pytest.approx(
            resolution_at(18, 45.0, 256) / 2.0, rel=1e-15
        )

    def test_cos_correction_is_applied(self) -> None:
        """★ At 60N a Mercator pixel covers HALF the ground it does at the equator."""
        assert resolution_at(18, 60.0, 256) == pytest.approx(
            resolution_at(18, 0.0, 256) * 0.5, rel=1e-12
        )


class TestZoomForResolution:
    """★ The property that makes a hardcoded 256 unreachable."""

    @pytest.mark.parametrize("z", list(range(0, 23)))
    @pytest.mark.parametrize("lat", [0.0, 30.0, 45.0, 55.0, 60.0, 85.0])
    @pytest.mark.parametrize("tile_size", [256, 512])
    def test_roundtrip_with_resolution_at(self, z: int, lat: float, tile_size: int) -> None:
        """``zoom_for_resolution(resolution_at(z, lat, S), lat, S, "nearest") == z``.

        For all z, lat and S. A hardcoded 256 fails every S=512 case.
        """
        mpp = resolution_at(z, lat, tile_size)
        assert zoom_for_resolution(mpp, lat, tile_size, round_mode="nearest") == z

    def test_tile_size_goldens(self) -> None:
        """★ THE regression: the correct solve for S=512 is exactly ONE LOWER."""
        assert zoom_for_resolution(0.5, 45.0, 512) == 17
        assert zoom_for_resolution(0.5, 45.0, 256) == 18

    def test_round_modes(self) -> None:
        # z=17.756... at (0.5, 45.0, 256).
        assert zoom_for_resolution(0.5, 45.0, 256, round_mode="up") == 18
        assert zoom_for_resolution(0.5, 45.0, 256, round_mode="down") == 17
        assert zoom_for_resolution(0.5, 45.0, 256, round_mode="nearest") == 18

    def test_up_is_finer_than_requested(self) -> None:
        """``round_mode="up"`` must never return imagery COARSER than asked for."""
        for lat in (0.0, 45.0, 55.0):
            for target in (0.1, 0.3, 0.5, 1.0, 5.0):
                z = zoom_for_resolution(target, lat, 256, round_mode="up")
                assert resolution_at(z, lat, 256) <= target * (1.0 + 1e-9)

    def test_clamped_to_domain(self) -> None:
        assert zoom_for_resolution(1e-9, 0.0, 256) == 24
        assert zoom_for_resolution(1e12, 0.0, 256) == 0

    def test_rejects_bad_input(self) -> None:
        with pytest.raises(ValueError):
            zoom_for_resolution(0.0, 45.0)
        with pytest.raises(ValueError):
            zoom_for_resolution(-1.0, 45.0)
        with pytest.raises(ValueError):
            zoom_for_resolution(0.5, 45.0, round_mode="sideways")


class TestChooseZoom:
    """``clamped`` is load-bearing: it must be True exactly when the provider falls short."""

    def test_not_clamped_when_servable(self) -> None:
        d = choose_zoom(0, 19, 0.5, 45.0, 256)
        assert d.zoom == 18
        assert d.clamped is False
        assert d.requested_mpp == 0.5
        assert d.achieved_mpp == pytest.approx(resolution_at(18, 45.0, 256))

    def test_clamped_at_max_zoom(self) -> None:
        """★ The provider cannot serve it: the caller is about to match upsampled mush."""
        d = choose_zoom(0, 15, 0.5, 45.0, 256)
        assert d.zoom == 15
        assert d.clamped is True
        assert d.achieved_mpp > d.requested_mpp

    def test_clamped_at_min_zoom(self) -> None:
        d = choose_zoom(10, 19, 5000.0, 45.0, 256)
        assert d.zoom == 10
        assert d.clamped is True

    def test_does_not_cry_wolf_for_512_providers(self) -> None:
        """★ THE 512 REGRESSION: a 512px provider at max_zoom=17 CAN serve 0.5 m at 45N.

        With a hardcoded 256 the ideal comes out as 18, gets clamped to 17, and `clamped`
        reports a failure on a provider that succeeded.
        """
        d = choose_zoom(0, 17, 0.5, 45.0, 512)
        assert d.zoom == 17
        assert d.clamped is False

    def test_rejects_inverted_range(self) -> None:
        with pytest.raises(ValueError):
            choose_zoom(19, 0, 0.5, 45.0)


class TestQuadkeys:
    """Published Bing quadkeys, both directions."""

    GOLDENS = [
        (1, 0, 0, "0"),
        (1, 1, 0, "1"),
        (1, 0, 1, "2"),
        (1, 1, 1, "3"),
        (3, 3, 5, "213"),  # Microsoft's own documented worked example.
        (2, 0, 0, "00"),
        (2, 3, 3, "33"),
        (12, 2046, 1362, "031313131130"),
    ]

    @pytest.mark.parametrize(("z", "x", "y", "quadkey"), GOLDENS)
    def test_tile_to_quadkey(self, z: int, x: int, y: int, quadkey: str) -> None:
        assert tile_to_quadkey(z, x, y) == quadkey

    @pytest.mark.parametrize(("z", "x", "y", "quadkey"), GOLDENS)
    def test_quadkey_to_tile(self, z: int, x: int, y: int, quadkey: str) -> None:
        assert quadkey_to_tile(quadkey) == TileRef(z, x, y)

    def test_z0_is_empty(self) -> None:
        assert tile_to_quadkey(0, 0, 0) == ""
        assert quadkey_to_tile("") == TileRef(0, 0, 0)

    @pytest.mark.parametrize("z", [1, 5, 12, 18])
    def test_roundtrip(self, z: int) -> None:
        n = 2**z
        for x, y in ((0, 0), (n - 1, n - 1), (n // 3, n // 7)):
            assert quadkey_to_tile(tile_to_quadkey(z, x, y)) == TileRef(z, x, y)

    def test_rejects_bad_digit(self) -> None:
        with pytest.raises(ValueError):
            quadkey_to_tile("0124")


class TestTileExtents:
    """Tile bboxes and ranges."""

    def test_tile_bbox_covers_its_own_centre(self) -> None:
        from gis.tiles import tile_to_lonlat_center

        bbox = tile_bbox_lonlat(12, 2046, 1362)
        lon, lat = tile_to_lonlat_center(12, 2046, 1362)
        assert bbox.contains(lon, lat)

    def test_tile_bbox_adjacent_tiles_share_an_edge(self) -> None:
        a = tile_bbox_lonlat(10, 100, 200)
        b = tile_bbox_lonlat(10, 101, 200)
        assert a.east == pytest.approx(b.west, rel=1e-12)

    def test_z0_covers_the_world(self) -> None:
        bbox = tile_bbox_lonlat(0, 0, 0)
        assert bbox.west == pytest.approx(-180.0)
        assert bbox.east == pytest.approx(180.0)
        assert bbox.north == pytest.approx(MAX_LATITUDE, abs=1e-9)
        assert bbox.south == pytest.approx(-MAX_LATITUDE, abs=1e-9)

    def test_bbox_to_tile_range_single_tile(self) -> None:
        bbox = tile_bbox_lonlat(12, 2046, 1362)
        rng = bbox_to_tile_range(bbox, 12)
        assert rng == TileRange(12, 2046, 1362, 2046, 1362)
        assert len(rng) == 1

    def test_bbox_to_tile_range_does_not_overreach(self) -> None:
        """A box ending exactly on a boundary must not pull in the next tile."""
        west, north = tile_to_lonlat(10, 100, 200)
        east, south = tile_to_lonlat(10, 102, 202)
        rng = bbox_to_tile_range(BBox(west, south, east, north), 10)
        assert rng == TileRange(10, 100, 200, 101, 201)

    def test_bbox_to_tile_range_rejects_antimeridian(self) -> None:
        """★ Rejected, NEVER silently wrapped."""
        crossing = BBox(west=179.0, south=-1.0, east=-179.0, north=1.0)
        assert crossing.crosses_antimeridian
        with pytest.raises(ValueError, match="antimeridian"):
            bbox_to_tile_range(crossing, 10)

    def test_range_iteration_is_row_major(self) -> None:
        rng = TileRange(5, 1, 2, 2, 3)
        assert list(rng) == [
            TileRef(5, 1, 2),
            TileRef(5, 2, 2),
            TileRef(5, 1, 3),
            TileRef(5, 2, 3),
        ]


class TestGeotransform:
    """Geotransform algebra, and the half-pixel that must never be dropped."""

    # A north-up z18 mosaic anchored at a real tile, 55N.
    GT = (1234567.0, 0.5971642834779395, 0.0, 7361866.0, 0.0, -0.5971642834779395)

    def test_invert_is_the_edge_inverse(self) -> None:
        igt = invert_geotransform(self.GT)
        # Forward through gt (edge convention), back through igt.
        for col, row in ((0.0, 0.0), (13.5, 91.25), (255.0, 255.0)):
            x = self.GT[0] + col * self.GT[1] + row * self.GT[2]
            y = self.GT[3] + col * self.GT[4] + row * self.GT[5]
            assert igt[0] + x * igt[1] + y * igt[2] == pytest.approx(col, abs=1e-9)
            assert igt[3] + x * igt[4] + y * igt[5] == pytest.approx(row, abs=1e-9)

    def test_invert_rejects_singular(self) -> None:
        with pytest.raises(ValueError, match="singular"):
            invert_geotransform((0.0, 0.0, 0.0, 0.0, 0.0, 0.0))

    def test_affine_ordering(self) -> None:
        from gis.tiles import geotransform_to_affine

        a, b, c, d, e, f = geotransform_to_affine(self.GT)
        assert (a, b, c) == (self.GT[1], self.GT[2], self.GT[0])
        assert (d, e, f) == (self.GT[4], self.GT[5], self.GT[3])

    @pytest.mark.parametrize("crs", ["EPSG:3857", "EPSG:4326"])
    @pytest.mark.parametrize(
        ("col", "row"), [(0.0, 0.0), (0.5, 0.5), (13.25, 91.75), (-0.5, -0.5), (255.0, 255.0)]
    )
    def test_pixel_roundtrip(self, crs: str, col: float, row: float) -> None:
        """★ ``lonlat_to_pixel(pixel_to_lonlat(...)) == (u, v)``.

        This is what makes the two GCP-adjust chains agree, and what keeps a half-pixel
        round-trip inconsistency from spuriously 422ing a correct edit at the 0.5 m
        consistency tolerance.

        ★ TOLERANCE: 1e-6 px, per §13.3 — NOT §13.1's 1e-9 px, which is not achievable in
        float64 (see ``test_roundtrip_is_within_a_few_ulp`` for the measurement and the
        arithmetic). 1e-6 px at z18 is ~6e-7 m: six orders of magnitude inside the 0.5 m
        tolerance this property protects.
        """
        gt = self.GT if crs == "EPSG:3857" else (11.0, 1e-5, 0.0, 55.0, 0.0, -1e-5)
        lon, lat = pixel_to_lonlat(gt, crs, col, row)
        col2, row2 = lonlat_to_pixel(gt, crs, lon, lat)
        assert col2 == pytest.approx(col, abs=1e-6)
        assert row2 == pytest.approx(row, abs=1e-6)

    def test_roundtrip_is_within_a_few_ulp(self) -> None:
        """★ The round trip is exact to floating-point resolution — the true statement.

        §13.1 IU-09 asks for ``< 1e-9 px``. That is BELOW float64's resolution at
        Web-Mercator magnitudes and no implementation can satisfy it:

            a 3857 northing at 55N is ~7.36e6 m
            one float64 ULP there is ~9.3e-10 m
            at z18 (0.597 m/px) that is ~1.56e-9 px

        So the floor on ANY correct implementation is ~1.6e-9 px, and the observed error
        is exactly that. This test asserts the achievable bound — a few ULP — which is
        strictly stronger evidence of correctness than a tolerance nobody can meet.
        """
        ulp_px = np.spacing(self.GT[3]) / abs(self.GT[1])
        for col, row in ((0.0, 0.0), (13.25, 91.75), (255.0, 255.0)):
            lon, lat = pixel_to_lonlat(self.GT, "EPSG:3857", col, row)
            col2, row2 = lonlat_to_pixel(self.GT, "EPSG:3857", lon, lat)
            assert abs(col2 - col) <= 8 * ulp_px, f"col drift exceeds 8 ULP at ({col},{row})"
            assert abs(row2 - row) <= 8 * ulp_px, f"row drift exceeds 8 ULP at ({col},{row})"

    def test_pixel_centre_convention(self) -> None:
        """★ pixel (0,0) is the CENTRE of the top-left pixel, so it is half a pixel in."""
        lon, lat = pixel_to_lonlat(self.GT, "EPSG:3857", 0.0, 0.0)
        x, y = lonlat_to_meters(lon, lat)
        assert x == pytest.approx(self.GT[0] + 0.5 * self.GT[1], abs=1e-6)
        assert y == pytest.approx(self.GT[3] + 0.5 * self.GT[5], abs=1e-6)

    def test_corner_identity(self) -> None:
        """★ §4.18's ruling: ``pixel_to_lonlat(gt, -0.5, -0.5) == tile_to_lonlat(z, x, y)``.

        (The old "pixel_to_lonlat(gt, 0, 0) == NW corner" invariant is VOID — it is false
        under the pixel-centre convention and was written to force the +0.5 back out.)
        """
        z, x, y = 12, 2046, 1362
        _tiles = {TileRef(z, x, y): np.zeros((256, 256, 3), dtype=np.uint8)}
        _, gt = stitch_tiles(_tiles, TileRange(z, x, y, x, y), 256)
        lon, lat = pixel_to_lonlat(gt, "EPSG:3857", -0.5, -0.5)
        exp_lon, exp_lat = tile_to_lonlat(z, x, y)
        assert lon == pytest.approx(exp_lon, abs=1e-9)
        assert lat == pytest.approx(exp_lat, abs=1e-9)

    def test_half_pixel_is_not_free(self) -> None:
        """The +0.5 is worth ~0.21 m at z18/45N — a systematic bias, not noise."""
        gt = (0.0, resolution_at(18, 45.0, 256), 0.0, 0.0, 0.0, -resolution_at(18, 45.0, 256))
        centre = pixel_to_lonlat(gt, "EPSG:3857", 0.0, 0.0)
        edge_x = gt[0] + 0.0 * gt[1]
        edge_y = gt[3] + 0.0 * gt[5]
        edge = meters_to_lonlat(edge_x, edge_y)
        assert centre != edge


class TestCropFoldsTheOffset:
    """★ THE TEST THAT CATCHES THE ~108 m ERROR THAT CRASHES NOTHING."""

    def _mosaic(self) -> tuple[np.ndarray, tuple[float, ...]]:
        z, x0, y0 = 18, 131072, 87025
        rng = TileRange(z, x0, y0, x0 + 1, y0 + 1)
        tiles = {ref: np.full((256, 256, 3), 7, dtype=np.uint8) for ref in rng}
        return stitch_tiles(tiles, rng, 256)

    def test_crop_updates_the_origin(self) -> None:
        mosaic, gt = self._mosaic()
        # Crop to the inner half of the mosaic.
        full = BBox(*_bbox_of(gt, mosaic.shape[1], mosaic.shape[0]))
        inset = BBox(
            west=full.west + (full.east - full.west) * 0.25,
            south=full.south + (full.north - full.south) * 0.25,
            east=full.east - (full.east - full.west) * 0.25,
            north=full.north - (full.north - full.south) * 0.25,
        )
        cropped, gt2 = crop_to_bbox(mosaic, gt, inset)

        assert cropped.shape[0] < mosaic.shape[0]
        assert cropped.shape[1] < mosaic.shape[1]
        # ★ The origin MOVED. An unfolded crop leaves gt2 == gt, which is the bug.
        assert gt2[0] != gt[0]
        assert gt2[3] != gt[3]
        # Scale terms are untouched by a crop.
        assert gt2[1] == gt[1]
        assert gt2[5] == gt[5]

    def test_cropped_pixel_maps_to_the_same_place_on_earth(self) -> None:
        """The real invariant: the SAME GROUND POINT, addressed through either geotransform."""
        mosaic, gt = self._mosaic()
        full = BBox(*_bbox_of(gt, mosaic.shape[1], mosaic.shape[0]))
        inset = BBox(
            west=full.west + (full.east - full.west) * 0.3,
            south=full.south + (full.north - full.south) * 0.3,
            east=full.east - (full.east - full.west) * 0.2,
            north=full.north - (full.north - full.south) * 0.2,
        )
        cropped, gt2 = crop_to_bbox(mosaic, gt, inset)

        # Pick a pixel in the cropped raster, find its lon/lat, and ask the ORIGINAL
        # raster where that lon/lat is. The two must name the same ground.
        for c, r in ((0.0, 0.0), (5.0, 9.0), (50.5, 61.25)):
            lon, lat = pixel_to_lonlat(gt2, "EPSG:3857", c, r)
            c_full, r_full = lonlat_to_pixel(gt, "EPSG:3857", lon, lat)
            lon_full, lat_full = pixel_to_lonlat(gt, "EPSG:3857", c_full, r_full)
            assert lon_full == pytest.approx(lon, abs=1e-12)
            assert lat_full == pytest.approx(lat, abs=1e-12)

    def test_unfolded_crop_would_be_metres_wrong(self) -> None:
        """Quantify the bug this guards: a naive crop is off by the crop offset."""
        mosaic, gt = self._mosaic()
        full = BBox(*_bbox_of(gt, mosaic.shape[1], mosaic.shape[0]))
        inset = BBox(
            west=full.west + (full.east - full.west) * 0.5,
            south=full.south,
            east=full.east,
            north=full.north,
        )
        _, gt2 = crop_to_bbox(mosaic, gt, inset)
        offset_m = abs(gt2[0] - gt[0])

        # Half a 512px z18 mosaic is 256 px of 3857 metres. The crop rounds OUTWARD (so a
        # caller never loses a pixel they asked for) and the bbox corners make one
        # lon/metre round trip, so the realised offset may sit one pixel inside the ideal.
        # Assert the substance, not the last bit: a real, metres-scale, whole-pixel shift.
        ideal_px = 256.0
        actual_px = offset_m / gt[1]
        assert ideal_px - 1.5 <= actual_px <= ideal_px + 1e-6, f"crop offset {actual_px} px"

        # ★ THE POINT: this is the magnitude of the error an unfolded crop introduces —
        #   ~150 m at z18, silently, with nothing crashing and every coordinate plausible.
        assert offset_m > 100.0

    def test_crop_rejects_disjoint_bbox(self) -> None:
        mosaic, gt = self._mosaic()
        with pytest.raises(ValueError, match="overlap"):
            crop_to_bbox(mosaic, gt, BBox(-10.0, -10.0, -9.0, -9.0))


class TestStitch:
    """Mosaic assembly and its geotransform."""

    def test_geotransform_matches_the_nw_tile(self) -> None:
        from gis.tiles import tile_bbox_meters

        z, x0, y0 = 14, 8000, 5000
        rng = TileRange(z, x0, y0, x0 + 2, y0 + 1)
        tiles = {ref: np.zeros((256, 256, 3), dtype=np.uint8) for ref in rng}
        mosaic, gt = stitch_tiles(tiles, rng, 256)

        west, _, _, north = tile_bbox_meters(z, x0, y0)
        assert gt[0] == pytest.approx(west, rel=1e-12)
        assert gt[3] == pytest.approx(north, rel=1e-12)
        assert gt[5] < 0.0  # north-up rasters have NEGATIVE pixel height
        assert gt[1] == pytest.approx(-gt[5], rel=1e-15)
        assert mosaic.shape == (2 * 256, 3 * 256, 3)


class TestPurity:
    """★ ``gis.tiles`` imports nothing but numpy and stdlib (§13.1 IU-09)."""

    def test_no_optional_deps_in_a_fresh_interpreter(self) -> None:
        code = (
            "import sys, importlib\n"
            "importlib.import_module('gis.tiles')\n"
            "banned = ['pyproj', 'osgeo', 'rasterio', 'httpx', 'redis', 'PIL', 'cv2', 'torch']\n"
            "present = [m for m in banned if m in sys.modules]\n"
            "assert not present, present\n"
            "print('clean')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "clean" in result.stdout


def _bbox_of(gt: tuple[float, ...], width: int, height: int) -> tuple[float, float, float, float]:
    """Return the 4326 (west, south, east, north) of a north-up 3857 raster's full extent."""
    west, north = meters_to_lonlat(gt[0], gt[3])
    east, south = meters_to_lonlat(gt[0] + width * gt[1], gt[3] + height * gt[5])
    return (west, south, east, north)
