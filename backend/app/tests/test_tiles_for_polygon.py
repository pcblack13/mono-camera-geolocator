"""``gis.tiles.tiles_for_polygon`` — the server-side AOI enumeration."""

from __future__ import annotations

import pytest

from gis.tiles import lonlat_to_tile, tile_bbox_lonlat, tiles_for_polygon

RING = [(35.50, 33.90), (35.52, 33.90), (35.52, 33.92), (35.50, 33.92)]


def test_returns_real_intersecting_tiles_not_an_area_guess() -> None:
    tiles, capped = tiles_for_polygon(RING, 14, 14)
    assert not capped
    assert tiles
    # Every vertex's containing tile must be in the answer…
    for lon, lat in RING:
        assert lonlat_to_tile(lon, lat, 14) in tiles
    # …and every returned tile's bbox must genuinely overlap the AOI's bbox.
    for t in tiles:
        bb = tile_bbox_lonlat(t.z, t.x, t.y)
        assert bb.west <= 35.52 and bb.east >= 35.50
        assert bb.south <= 33.92 and bb.north >= 33.90


def test_tiny_aoi_still_claims_its_covering_tile_at_low_zoom() -> None:
    """Rectangle-overlap, not centre-in-polygon: an AOI smaller than one z8 tile must
    still cache the tile that covers it."""
    tiny = [(35.500, 33.900), (35.501, 33.900), (35.501, 33.901)]
    tiles, _ = tiles_for_polygon(tiny, 8, 8)
    assert tiles == [lonlat_to_tile(35.5005, 33.9003, 8)]


def test_zoom_band_is_inclusive_and_ascending() -> None:
    tiles, _ = tiles_for_polygon(RING, 12, 14)
    zooms = sorted({t.z for t in tiles})
    assert zooms == [12, 13, 14]


def test_cap_truncates_and_reports() -> None:
    tiles, capped = tiles_for_polygon(RING, 10, 18, cap=10)
    assert capped
    assert len(tiles) == 10


def test_degenerate_inputs_raise() -> None:
    with pytest.raises(ValueError):
        tiles_for_polygon(RING[:2], 10, 12)
    with pytest.raises(ValueError):
        tiles_for_polygon(RING, 14, 12)


def test_no_duplicates() -> None:
    tiles, _ = tiles_for_polygon(RING, 12, 15)
    assert len(tiles) == len(set(tiles))
