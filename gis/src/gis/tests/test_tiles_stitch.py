"""Tests for mosaicking and cropping (§13.1 IU-09).

Stitching is where a set of tiles becomes one raster with one geotransform. Every
coordinate the product emits passes through that geotransform, so the tests here are about
one thing: **the pixels and the geotransform must agree about where they are.**
"""

from __future__ import annotations

import numpy as np
import pytest

from gis.tiles import (
    EARTH_CIRCUMFERENCE_M,
    crop_to_bbox,
    lonlat_to_pixel,
    meters_to_lonlat,
    pixel_to_lonlat,
    stitch_tiles,
    tile_bbox_lonlat,
    tile_bbox_meters,
)
from gis.types import BBox, TileRange, TileRef


def _tile(value: int, size: int = 256) -> np.ndarray:
    """A solid-colour tile, so a misplaced tile is visible as a value."""
    return np.full((size, size, 3), value, dtype=np.uint8)


class TestStitchLayout:
    def test_single_tile(self) -> None:
        rng = TileRange(12, 2046, 1362, 2046, 1362)
        mosaic, gt = stitch_tiles({TileRef(12, 2046, 1362): _tile(42)}, rng, 256)
        assert mosaic.shape == (256, 256, 3)
        assert np.all(mosaic == 42)
        assert mosaic.flags["C_CONTIGUOUS"]

    def test_grid_layout_and_ordering(self) -> None:
        """★ Tile (x, y) must land at pixel ((x-min_x)*S, (y-min_y)*S) — x is COLUMN.

        Transposing x and y here produces a mosaic that looks fine on a symmetric range
        and is silently mirrored on any other.
        """
        z, x0, y0 = 10, 100, 200
        rng = TileRange(z, x0, y0, x0 + 2, y0 + 1)  # 3 wide, 2 tall
        tiles = {
            TileRef(z, x0 + dx, y0 + dy): _tile(10 * dy + dx)
            for dy in range(2)
            for dx in range(3)
        }
        mosaic, _ = stitch_tiles(tiles, rng, 256)
        assert mosaic.shape == (2 * 256, 3 * 256, 3)
        for dy in range(2):
            for dx in range(3):
                patch = mosaic[dy * 256 : (dy + 1) * 256, dx * 256 : (dx + 1) * 256]
                assert np.all(patch == 10 * dy + dx), f"tile ({dx},{dy}) is misplaced"

    def test_missing_tiles_are_filled_not_dropped(self) -> None:
        z, x0, y0 = 10, 100, 200
        rng = TileRange(z, x0, y0, x0 + 1, y0)
        mosaic, _ = stitch_tiles(
            {TileRef(z, x0, y0): _tile(200)}, rng, 256, missing_fill=(1, 2, 3)
        )
        assert mosaic.shape == (256, 512, 3)
        assert np.all(mosaic[:, :256] == 200)
        assert np.all(mosaic[:, 256:] == np.array([1, 2, 3], dtype=np.uint8))

    def test_tiles_outside_the_range_are_ignored(self) -> None:
        z, x0, y0 = 10, 100, 200
        rng = TileRange(z, x0, y0, x0, y0)
        tiles = {TileRef(z, x0, y0): _tile(5), TileRef(z, x0 + 9, y0): _tile(6)}
        mosaic, _ = stitch_tiles(tiles, rng, 256)
        assert np.all(mosaic == 5)

    def test_512_tiles(self) -> None:
        rng = TileRange(10, 100, 200, 100, 200)
        mosaic, gt = stitch_tiles({TileRef(10, 100, 200): _tile(9, 512)}, rng, 512)
        assert mosaic.shape == (512, 512, 3)
        assert gt[1] == pytest.approx(EARTH_CIRCUMFERENCE_M / (512 * 2**10), rel=1e-15)

    def test_rejects_wrong_shape(self) -> None:
        rng = TileRange(10, 100, 200, 100, 200)
        with pytest.raises(ValueError, match="shape"):
            stitch_tiles({TileRef(10, 100, 200): _tile(1, 128)}, rng, 256)

    def test_rejects_wrong_dtype(self) -> None:
        rng = TileRange(10, 100, 200, 100, 200)
        bad = np.zeros((256, 256, 3), dtype=np.float32)
        with pytest.raises(ValueError, match="dtype"):
            stitch_tiles({TileRef(10, 100, 200): bad}, rng, 256)

    def test_rejects_wrong_zoom(self) -> None:
        rng = TileRange(10, 100, 200, 100, 200)
        with pytest.raises(ValueError, match="zoom"):
            stitch_tiles({TileRef(11, 100, 200): _tile(1)}, rng, 256)


class TestStitchGeoreferencing:
    """The mosaic's geotransform must place its pixels exactly where the tiles are."""

    def test_origin_is_the_nw_tile_corner(self) -> None:
        z, x0, y0 = 14, 8000, 5000
        rng = TileRange(z, x0, y0, x0 + 2, y0 + 1)
        tiles = {ref: _tile(1) for ref in rng}
        _, gt = stitch_tiles(tiles, rng, 256)
        west, _, _, north = tile_bbox_meters(z, x0, y0)
        assert gt[0] == pytest.approx(west, rel=1e-12)
        assert gt[3] == pytest.approx(north, rel=1e-12)

    def test_north_up_has_negative_pixel_height(self) -> None:
        """★ GDAL order: gt[5] < 0 for north-up. A positive value flips the raster."""
        rng = TileRange(14, 8000, 5000, 8000, 5000)
        _, gt = stitch_tiles({TileRef(14, 8000, 5000): _tile(1)}, rng, 256)
        assert gt[5] < 0
        assert gt[1] > 0
        assert gt[2] == 0.0 and gt[4] == 0.0  # no rotation

    def test_every_tile_corner_lands_on_its_own_pixel(self) -> None:
        """The end-to-end invariant: each tile's NW corner is at its own pixel offset."""
        z, x0, y0 = 12, 2046, 1362
        rng = TileRange(z, x0, y0, x0 + 1, y0 + 1)
        tiles = {ref: _tile(1) for ref in rng}
        _, gt = stitch_tiles(tiles, rng, 256)

        for dy in range(2):
            for dx in range(2):
                bbox = tile_bbox_lonlat(z, x0 + dx, y0 + dy)
                # The tile's NW corner is an EDGE, so it sits at pixel centre -0.5.
                col, row = lonlat_to_pixel(gt, "EPSG:3857", bbox.west, bbox.north)
                assert col == pytest.approx(dx * 256 - 0.5, abs=1e-6)
                assert row == pytest.approx(dy * 256 - 0.5, abs=1e-6)

    def test_mosaic_centre_pixel_is_the_geographic_centre(self) -> None:
        z, x0, y0 = 12, 2046, 1362
        rng = TileRange(z, x0, y0, x0 + 1, y0 + 1)
        mosaic, gt = stitch_tiles({ref: _tile(1) for ref in rng}, rng, 256)
        h, w = mosaic.shape[0], mosaic.shape[1]
        lon, lat = pixel_to_lonlat(gt, "EPSG:3857", w / 2.0 - 0.5, h / 2.0 - 0.5)
        # That is the shared corner of the four tiles: the NW corner of (x0+1, y0+1).
        expected = tile_bbox_lonlat(z, x0 + 1, y0 + 1)
        assert lon == pytest.approx(expected.west, abs=1e-9)
        assert lat == pytest.approx(expected.north, abs=1e-9)


class TestCrop:
    """★ Cropping without folding the offset into the origin is the ~150 m silent bug."""

    def _mosaic(self) -> tuple[np.ndarray, tuple[float, ...]]:
        z, x0, y0 = 18, 131072, 87025
        rng = TileRange(z, x0, y0, x0 + 1, y0 + 1)
        return stitch_tiles({ref: _tile(7) for ref in rng}, rng, 256)

    def _full_bbox(self, gt: tuple[float, ...], w: int, h: int) -> BBox:
        west, north = meters_to_lonlat(gt[0], gt[3])
        east, south = meters_to_lonlat(gt[0] + w * gt[1], gt[3] + h * gt[5])
        return BBox(west, south, east, north)

    def test_ground_position_is_preserved_through_the_crop(self) -> None:
        """★ THE invariant. A pixel in the cropped raster and the same ground point in the
        original must agree — that is what "the offset is folded in" MEANS."""
        mosaic, gt = self._mosaic()
        full = self._full_bbox(gt, mosaic.shape[1], mosaic.shape[0])
        inset = BBox(
            west=full.west + (full.east - full.west) * 0.3,
            south=full.south + (full.north - full.south) * 0.25,
            east=full.east - (full.east - full.west) * 0.15,
            north=full.north - (full.north - full.south) * 0.35,
        )
        cropped, gt2 = crop_to_bbox(mosaic, gt, inset)

        # The crop offset, recovered from the two geotransforms.
        dcol = round((gt2[0] - gt[0]) / gt[1])
        drow = round((gt2[3] - gt[3]) / gt[5])

        for c, r in ((0.0, 0.0), (3.5, 7.25), (float(cropped.shape[1] - 1), 0.0)):
            lon_c, lat_c = pixel_to_lonlat(gt2, "EPSG:3857", c, r)
            lon_f, lat_f = pixel_to_lonlat(gt, "EPSG:3857", c + dcol, r + drow)
            assert lon_c == pytest.approx(lon_f, abs=1e-12)
            assert lat_c == pytest.approx(lat_f, abs=1e-12)

    def test_crop_covers_the_requested_bbox(self) -> None:
        """The crop rounds OUTWARD: it must never lose a pixel the caller asked for."""
        mosaic, gt = self._mosaic()
        full = self._full_bbox(gt, mosaic.shape[1], mosaic.shape[0])
        inset = BBox(
            west=full.west + (full.east - full.west) * 0.31,
            south=full.south + (full.north - full.south) * 0.27,
            east=full.east - (full.east - full.west) * 0.13,
            north=full.north - (full.north - full.south) * 0.29,
        )
        cropped, gt2 = crop_to_bbox(mosaic, gt, inset)
        got = self._full_bbox(gt2, cropped.shape[1], cropped.shape[0])
        assert got.west <= inset.west + 1e-9
        assert got.east >= inset.east - 1e-9
        assert got.south <= inset.south + 1e-9
        assert got.north >= inset.north - 1e-9

    def test_scale_terms_survive_a_crop(self) -> None:
        mosaic, gt = self._mosaic()
        full = self._full_bbox(gt, mosaic.shape[1], mosaic.shape[0])
        _, gt2 = crop_to_bbox(mosaic, gt, full.buffered_m(-10.0))
        assert gt2[1] == gt[1]
        assert gt2[2] == gt[2]
        assert gt2[4] == gt[4]
        assert gt2[5] == gt[5]

    def test_full_extent_crop_is_a_no_op(self) -> None:
        mosaic, gt = self._mosaic()
        full = self._full_bbox(gt, mosaic.shape[1], mosaic.shape[0])
        cropped, gt2 = crop_to_bbox(mosaic, gt, full)
        assert cropped.shape == mosaic.shape
        assert gt2 == pytest.approx(list(gt))

    def test_crop_is_clamped_to_the_mosaic(self) -> None:
        """A bbox larger than the mosaic yields the mosaic, not an out-of-bounds read."""
        mosaic, gt = self._mosaic()
        full = self._full_bbox(gt, mosaic.shape[1], mosaic.shape[0])
        cropped, _ = crop_to_bbox(mosaic, gt, full.buffered_m(500.0))
        assert cropped.shape == mosaic.shape

    def test_rejects_disjoint_bbox(self) -> None:
        mosaic, gt = self._mosaic()
        with pytest.raises(ValueError, match="overlap"):
            crop_to_bbox(mosaic, gt, BBox(-170.0, -80.0, -169.0, -79.0))

    def test_rejects_antimeridian_bbox(self) -> None:
        mosaic, gt = self._mosaic()
        with pytest.raises(ValueError, match="antimeridian"):
            crop_to_bbox(mosaic, gt, BBox(179.0, -1.0, -179.0, 1.0))

    def test_rotated_geotransform_folds_correctly(self) -> None:
        """★ The fold uses the full affine, so a rotated raster crops correctly too.

        A north-up-only implementation (``origin += col0 * gt[1]``) silently drops the
        rotation terms' contribution to the origin.
        """
        # A 5-degree-rotated 3857 raster.
        import math

        theta = math.radians(5.0)
        res = 0.6
        gt = (
            1234567.0,
            res * math.cos(theta),
            -res * math.sin(theta),
            7361866.0,
            -res * math.sin(theta),
            -res * math.cos(theta),
        )
        mosaic = np.full((300, 300, 3), 3, dtype=np.uint8)
        west, north = meters_to_lonlat(gt[0] + 40 * gt[1], gt[3] + 40 * gt[5])
        east, south = meters_to_lonlat(gt[0] + 200 * gt[1], gt[3] + 200 * gt[5])
        cropped, gt2 = crop_to_bbox(mosaic, gt, BBox(min(west, east), min(south, north), max(west, east), max(south, north)))

        dcol = 0
        drow = 0
        # Recover the offset by solving the 2x2 system, since both terms now move both axes.
        from gis.tiles import invert_geotransform

        igt = invert_geotransform(gt)
        dx, dy = gt2[0] - gt[0], gt2[3] - gt[3]
        dcol = round(igt[1] * dx + igt[2] * dy)
        drow = round(igt[4] * dx + igt[5] * dy)

        for c, r in ((0.0, 0.0), (10.0, 12.0)):
            lon_c, lat_c = pixel_to_lonlat(gt2, "EPSG:3857", c, r)
            lon_f, lat_f = pixel_to_lonlat(gt, "EPSG:3857", c + dcol, r + drow)
            assert lon_c == pytest.approx(lon_f, abs=1e-9)
            assert lat_c == pytest.approx(lat_f, abs=1e-9)
