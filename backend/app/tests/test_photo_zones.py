"""The nine range zones on the photograph — the tracer, the binning, and the run.

The vendored `zone_overlay` is upstream's; what is pinned here is the contract our
service builds on: contours traced from the bottom of the frame upward, tiles binned
by their own range and their projected column, a floor under which a zone has no
number, and the measurement carrying all of it in original photo pixels.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.vendor.geo_accuracy import zone_overlay as ZO  # noqa: N812 — upstream's shorthand

W, H = 1200, 800


def _linear_range(k: float):  # noqa: ANN202
    """A frame whose ground range grows linearly from the bottom row up: r = k(H - v)."""

    def range_at(u: float, v: float) -> float | None:  # noqa: ARG001
        return k * (H - v) if v >= 40 else None  # the top 40 rows are sky

    return range_at


class TestContours:
    def test_a_contour_sits_where_the_range_crosses_the_edge(self) -> None:
        """R = 2(H - v) crosses 400 m at v = 600 and 800 m at v = 400."""
        curves = ZO.iso_range_curves([400.0, 800.0], _linear_range(2.0), W, H)
        assert set(curves) == {400.0, 800.0}
        for band, expected_v in ((400.0, 600.0), (800.0, 400.0)):
            rows = np.array([v for _u, v in curves[band]])
            assert len(rows) >= 30
            # Bisection to 7 levels over a ≤14 px step lands within a pixel.
            assert np.all(np.abs(rows - expected_v) < 1.0), (band, rows.min(), rows.max())

    def test_an_edge_the_frame_never_reaches_is_dropped_not_faked(self) -> None:
        """The farthest visible ground is 2(H - 40) = 1520 m; 3000 m is off the frame."""
        curves = ZO.iso_range_curves([400.0, 3000.0], _linear_range(2.0), W, H)
        assert 400.0 in curves
        assert 3000.0 not in curves

    def test_the_contour_bends_with_the_terrain(self) -> None:
        """A ridge on the right raises the range there; the contour must follow it."""

        def range_at(u: float, v: float) -> float | None:
            bump = 200.0 if u > W / 2 else 0.0
            return 2.0 * (H - v) + bump if v >= 40 else None

        curves = ZO.iso_range_curves([800.0], range_at, W, H)
        left = [v for u, v in curves[800.0] if u < W / 2]
        right = [v for u, v in curves[800.0] if u > W / 2]
        # right side: 2(H - v) + 200 = 800 → v = 500; left side: v = 400
        assert abs(np.median(left) - 400.0) < 1.0
        assert abs(np.median(right) - 500.0) < 1.0


class TestBinning:
    def test_tiles_land_in_the_band_of_their_range_and_the_column_of_their_pixel(self) -> None:
        bands = [300.0, 600.0, 900.0]
        tiles = [
            {"range": 100.0, "err": 1.0},   # band 0
            {"range": 450.0, "err": 2.0},   # band 1
            {"range": 850.0, "err": 3.0},   # band 2
            {"range": 950.0, "err": 9.0},   # beyond the last edge — ignored
        ]
        uv = np.array([[100.0, 700.0], [600.0, 500.0], [1100.0, 100.0], [600.0, 50.0]])
        stats, rng = ZO.zone_stats(tiles, bands, uv, W, min_tiles=1)
        assert stats == {(0, 0): (1, 1.0), (1, 1): (1, 2.0), (2, 2): (1, 3.0)}
        assert rng == (1.0, 3.0)

    def test_the_colour_scale_ignores_zones_under_the_floor(self) -> None:
        """A zone with too few tiles has no number, so it cannot set the scale."""
        bands = [300.0, 600.0, 900.0]
        many = [{"range": 100.0, "err": 4.0}] * 6          # L1, six tiles
        few = [{"range": 450.0, "err": 40.0}] * 2          # M2, two tiles
        uv = np.array([[100.0, 700.0]] * 6 + [[600.0, 500.0]] * 2)
        stats, rng = ZO.zone_stats(many + few, bands, uv, W, min_tiles=5)
        assert stats[(1, 1)] == (2, 40.0)      # counted…
        assert rng == (4.0, 4.0)               # …but not coloured


# ── the run ───────────────────────────────────────────────────────────────────

from app.tests.test_accuracy_service import scene  # noqa: E402, F401
from app.tests.test_error_map_updates import _run  # noqa: E402


def _scene_for(scene: dict, dem):  # noqa: ANN202, F811
    import cv2

    from app.services.accuracy_service import _Scene

    return _Scene(
        photo=cv2.imread(str(scene["photo_path"])), dem=dem, rotation=scene["rotation"],
        camera_xyz=scene["camera_xyz"],
        k_matrix=np.array([[1100.0, 0.0, 600.0], [0.0, 1100.0, 400.0], [0.0, 0.0, 1.0]]),
        dist=np.zeros(5), cam_lat=scene["cam_lat"], cam_lon=scene["cam_lon"], gcps_used=4,
        reproj_mean_px=0.0, reproj_max_px=0.0, warnings=[],
    )


@pytest.mark.slow
def test_the_run_puts_nine_measured_zones_on_the_frame(scene: dict, tmp_path) -> None:  # noqa: F811
    """Every zone populated, every median the injected shift, curves near → far.

    ★ The fixture injects one uniform (4, -3) m shift, so a zone reading anything but
    5.0 m would mean a tile was binned into the wrong zone, not that the error
    varies. Near ground is at the BOTTOM of a frame, so the first band's contour must
    sit below the second's, and the second's below the third's.
    """
    from app.schemas.accuracy import AccuracyZones
    from app.services.accuracy_service import ZONE_MIN_TILES, _photo_zones
    from app.vendor.geo_accuracy.geo_io import DEM

    res = _run(scene, tmp_path)
    dem = DEM(str(scene["dem_path"]))
    try:
        zones = _photo_zones(_scene_for(scene, dem), res)
    finally:
        dem.ds.close()
    assert zones is not None
    parsed = AccuracyZones(**zones)             # the wire contract holds
    assert (parsed.width, parsed.height) == (1200, 800)
    assert len(parsed.bands_m) == 3 and parsed.bands_m == sorted(parsed.bands_m)
    assert len(parsed.cells) == 9
    assert all(c.tiles >= ZONE_MIN_TILES for c in parsed.cells)
    assert all(c.median_error_m == pytest.approx(5.0, abs=0.05) for c in parsed.cells)
    assert parsed.range_m is not None
    rows = [np.median([v for _u, v in c]) for c in parsed.curves if c]
    assert len(rows) == 3
    assert rows[0] > rows[1] > rows[2], rows


@pytest.mark.slow
def test_a_run_with_nothing_locked_has_no_zones(scene: dict, tmp_path) -> None:  # noqa: F811
    """No tiles → None, not nine empty cells pretending to be a picture."""
    from app.services.accuracy_service import _photo_zones
    from app.vendor.geo_accuracy.geo_io import DEM

    res = _run(scene, tmp_path)
    for t in res.tiles:
        t["ok"] = False
    dem = DEM(str(scene["dem_path"]))
    try:
        assert _photo_zones(_scene_for(scene, dem), res) is None
    finally:
        dem.ds.close()
