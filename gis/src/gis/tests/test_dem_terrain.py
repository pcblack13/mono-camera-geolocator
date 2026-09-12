"""``gis.dem.terrain`` — Terrarium encoding, and agreement with the authoritative sampler.

★ **THE CROSS-CHECK IS THE POINT OF THIS MODULE'S TESTS.** `terrain.py` and
`dem/sample.py` reach the same DEM by completely different routes: the first projects a
whole slippy-tile grid and interpolates inside one windowed read, the second transforms a
handful of points and samples each. Two paths to one number is the only thing that catches
a systematic geometry error, because a displaced terrain surface looks entirely plausible.

That is not hypothetical. During development this pair caught a **half-pixel offset** —
`invert_geotransform` returns EDGE coordinates and bilinear interpolation wants CENTRES —
which shifted every rendered height by half a DEM cell (14 m on Copernicus 30 m). Against
the sampler it showed up as a ~0.34 m disagreement on sloping ground and would have been
invisible to the eye. Do not delete these tests to make a refactor pass.
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest

from gis.dem.sample import sample_points
from gis.dem.terrain import (
    TERRARIUM_OFFSET_M,
    TILE_SIZE_PX,
    encode_terrarium,
    terrain_tile_png,
)
from gis.tiles import lonlat_to_tile, meters_to_lonlat_array, tile_bbox_meters

pytest.importorskip("PIL", reason="terrain tiles are PNG-encoded")

#: The committed Copernicus DEM — UTM 37N, ~28 m posting, real terrain.
DEM_PATH = Path(__file__).resolve().parents[4] / (
    "DTM_Proccesing/Copernicus_DSM_COG_10_N34_00_E036_00_DEM_processed.tif"
)

#: Somewhere inside that raster.
DEM_LON, DEM_LAT = 36.49696, 34.50116

#: 1/256 m — the finest height the encoding can express. Nothing may disagree by more.
QUANTISATION_M = 1.0 / 256.0

pytestmark = pytest.mark.skipif(
    not DEM_PATH.is_file(), reason="the committed DEM fixture is not present"
)


def _decode(png: bytes) -> np.ndarray:
    """PNG bytes → the height grid a renderer would reconstruct."""
    from PIL import Image

    rgb = np.asarray(Image.open(io.BytesIO(png))).astype(np.float64)
    return rgb[..., 0] * 256.0 + rgb[..., 1] + rgb[..., 2] / 256.0 - TERRARIUM_OFFSET_M


# ── the encoding ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "height",
    [0.0, 1.0 / 256, -430.0, 412.5, 1234.567, 8848.86, -500.0, 9000.0],
    ids=["sea-level", "one-lsb", "dead-sea", "typical", "fractional", "everest",
         "floor", "ceiling"],
)
def test_encoding_round_trips_to_the_quantisation_floor(height: float) -> None:
    """Encode then decode must return the input to within one least-significant bit."""
    decoded = _decode_array(encode_terrarium(np.array([[height]])))
    assert decoded[0, 0] == pytest.approx(height, abs=QUANTISATION_M)


def _decode_array(rgb: np.ndarray) -> np.ndarray:
    v = rgb.astype(np.float64)
    return v[..., 0] * 256.0 + v[..., 1] + v[..., 2] / 256.0 - TERRARIUM_OFFSET_M


def test_sea_level_is_the_documented_rgb() -> None:
    """0 m is RGB(128, 0, 0). A regression here silently reprojects every height."""
    assert tuple(encode_terrarium(np.array([[0.0]]))[0, 0]) == (128, 0, 0)


def test_non_finite_heights_encode_without_raising() -> None:
    """A NaN must not crash the renderer's tile; it becomes 0 m for the mesh only."""
    out = encode_terrarium(np.array([[np.nan, np.inf, -np.inf]]))
    assert out.shape == (1, 3, 3)
    assert out.dtype == np.uint8


def test_encoding_saturates_rather_than_wrapping() -> None:
    """★ A value past the range must clamp, not alias to an unrelated height.

    Wrapping would turn an absurd sentinel into a *plausible* elevation, which is far
    worse than an obviously clipped one.
    """
    assert _decode_array(encode_terrarium(np.array([[1e9]])))[0, 0] > 30000.0
    assert _decode_array(encode_terrarium(np.array([[-1e9]])))[0, 0] == -TERRARIUM_OFFSET_M


# ── tiles over the real DEM ──────────────────────────────────────────────────


@pytest.mark.parametrize("zoom", [10, 12, 14])
def test_a_tile_over_the_dem_renders(zoom: int) -> None:
    tile = lonlat_to_tile(DEM_LON, DEM_LAT, zoom)
    png = terrain_tile_png(DEM_PATH, zoom, tile.x, tile.y)
    assert png is not None and png[:8] == b"\x89PNG\r\n\x1a\n"

    heights = _decode(png)
    assert heights.shape == (TILE_SIZE_PX, TILE_SIZE_PX)
    # Real terrain in the Homs/Bekaa basin — a few hundred metres, never sea level.
    assert 100.0 < float(np.nanmedian(heights)) < 2000.0


def test_a_tile_outside_the_dem_is_None_not_a_flat_surface() -> None:
    """★ None becomes a 404, and the renderer draws no terrain.

    Returning an all-zero tile instead would carpet the globe in a fabricated sea-level
    surface that looks exactly like real data.
    """
    tile = lonlat_to_tile(-100.0, 40.0, 12)  # Kansas; the DEM is in Syria
    assert terrain_tile_png(DEM_PATH, 12, tile.x, tile.y) is None


def test_tile_heights_agree_with_the_authoritative_sampler() -> None:
    """★★ THE REGRESSION GUARD. Two independent paths to the same DEM must agree.

    This is what caught the half-pixel offset described in the module docstring. The
    tolerance is the encoding's own quantisation — anything larger is a geometry bug,
    not a rounding artefact.
    """
    zoom = 14
    tile = lonlat_to_tile(DEM_LON, DEM_LAT, zoom)
    png = terrain_tile_png(DEM_PATH, zoom, tile.x, tile.y)
    assert png is not None
    from_tile = _decode(png)

    # Reconstruct the exact lon/lat of a scatter of tile pixel CENTRES.
    west, south, east, north = tile_bbox_meters(zoom, tile.x, tile.y)
    step_x = (east - west) / TILE_SIZE_PX
    step_y = (north - south) / TILE_SIZE_PX
    picks = [(20, 30), (64, 64), (128, 128), (200, 90), (250, 250), (5, 240)]

    mx = np.array([west + (col + 0.5) * step_x for _row, col in picks])
    my = np.array([north - (row + 0.5) * step_y for row, _col in picks])
    lons, lats = meters_to_lonlat_array(mx, my)

    sampled, _dem_crs, _out_crs = sample_points(
        DEM_PATH,
        [(f"P{i}", float(lon), float(lat)) for i, (lon, lat) in enumerate(zip(lons, lats))],
        method="bilinear",
    )

    for (row, col), point in zip(picks, sampled, strict=True):
        assert point.z_m is not None, "the picks are inside the DEM by construction"
        assert from_tile[row, col] == pytest.approx(point.z_m, abs=QUANTISATION_M), (
            f"tile pixel ({row},{col}) disagrees with the DEM sampler by "
            f"{abs(from_tile[row, col] - point.z_m):.4f} m — a geometry bug, not rounding"
        )


def test_the_north_edge_is_row_zero() -> None:
    """★ Slippy y descends while mercator y ascends. Flipping this mirrors the terrain.

    On real ground that renders as plausible hills in the wrong places — the kind of
    error that survives review because the picture still looks like landscape.
    """
    zoom = 13
    tile = lonlat_to_tile(DEM_LON, DEM_LAT, zoom)
    png = terrain_tile_png(DEM_PATH, zoom, tile.x, tile.y)
    assert png is not None
    heights = _decode(png)

    west, south, east, north = tile_bbox_meters(zoom, tile.x, tile.y)
    step_x = (east - west) / TILE_SIZE_PX
    step_y = (north - south) / TILE_SIZE_PX
    mid_col = TILE_SIZE_PX // 2

    # ★ The centre of column `mid_col`, not the centre of the tile. Those differ by half
    #   a pixel (~10 m at this zoom), which on sloping ground is a ~0.1 m height
    #   difference — enough to fail against the quantisation tolerance and send someone
    #   hunting a bug in the encoder that is not there. This test made that mistake once.
    mid_x = np.array([west + (mid_col + 0.5) * step_x] * 2)
    edge_y = np.array([north - 0.5 * step_y, north - (TILE_SIZE_PX - 0.5) * step_y])
    lons, lats = meters_to_lonlat_array(mid_x, edge_y)

    sampled, _a, _b = sample_points(
        DEM_PATH,
        [("top", float(lons[0]), float(lats[0])), ("bottom", float(lons[1]), float(lats[1]))],
        method="bilinear",
    )
    if sampled[0].z_m is None or sampled[1].z_m is None:
        pytest.skip("tile edge falls outside the DEM here")

    assert heights[0, mid_col] == pytest.approx(sampled[0].z_m, abs=QUANTISATION_M)
    assert heights[TILE_SIZE_PX - 1, mid_col] == pytest.approx(
        sampled[1].z_m, abs=QUANTISATION_M
    )


class TestFillVoids:
    """The line between 'project DEM in real surroundings' and 'island on a cliff'."""

    def test_voids_fill_from_the_fallback_tile(self) -> None:
        import io

        from PIL import Image

        from gis.dem.terrain import encode_terrarium, fill_voids

        fallback = np.full((4, 4), 700.0)
        img = Image.fromarray(encode_terrarium(fallback), mode="RGB")
        buf = io.BytesIO()
        img.save(buf, format="PNG")

        heights = np.full((4, 4), 1500.0)
        heights[0, 0] = np.nan
        merged = fill_voids(heights, buf.getvalue())
        # ★ The void becomes the SURROUNDING terrain, not sea level: the old 0 m fill
        #   rendered a 1.4 km cliff wall around a mountain-plateau DEM.
        assert merged[0, 0] == 700.0
        assert merged[1, 1] == 1500.0

    def test_offline_fill_is_the_dem_floor_not_zero(self) -> None:
        from gis.dem.terrain import fill_voids

        heights = np.full((4, 4), 1500.0)
        heights[0, 0] = np.nan
        merged = fill_voids(heights, None)
        assert merged[0, 0] == 1500.0  # flat apron at the DEM's own floor — no chasm

    def test_decode_is_the_inverse_of_encode(self) -> None:
        import io

        from PIL import Image

        from gis.dem.terrain import decode_terrarium, encode_terrarium

        h = np.array([[1401.25, -430.0], [0.0, 8848.86]])
        img = Image.fromarray(encode_terrarium(h), mode="RGB")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        assert float(np.abs(decode_terrarium(buf.getvalue()) - h).max()) <= 1.0 / 256
