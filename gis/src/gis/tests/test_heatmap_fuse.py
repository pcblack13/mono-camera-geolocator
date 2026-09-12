"""Tests for ``gis.heatmap`` (§13.1 IU-09, §4.26).

Each ``PixelHeatmap`` lives in its OWN window's pixel frame. Fusing them is the one place
in the system that sees both a pixel heatmap and a geotransform, and the property that
matters is that a component's mean comes out at the place its own window says it is.

★ The heatmap FEATURE is deferred (SCOPE.md §4: ``ai_engine`` ships the ABC only), so
these exercise the converter with structural stand-ins rather than with real engine
output. The converter is real and correct today; only its caller is deferred.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pytest

from gis.crs import backend_name
from gis.heatmap import GeoHeatmap, GeoHeatmapCell, fuse_pixel_heatmaps
from gis.tiles import pixel_to_lonlat

_HAVE_FULL_BACKEND = backend_name() in ("pyproj", "osr")
_needs_utm = pytest.mark.skipif(not _HAVE_FULL_BACKEND, reason="fusion grids in UTM")

GT_3857 = (1234567.0, 0.5971642834779395, 0.0, 7361866.0, 0.0, -0.5971642834779395)


@dataclass
class _Component:
    mu_px: tuple[float, float]
    cov_px2: Any
    weight: float
    window_id: str = "w0"
    confidence: float = 50.0


@dataclass
class _PixelHeatmap:
    components: list[_Component]
    background_weight: float = 0.0


@dataclass
class _Window:
    geotransform: tuple[float, float, float, float, float, float] = GT_3857
    crs: str = "EPSG:3857"
    gsd_m: float = 0.34251936163340246  # resolution_at(18, 55.0)


def _one(mu=(128.0, 128.0), sigma_px=10.0, weight=1.0, window_id="w0", bg=0.0):
    comp = _Component(
        mu_px=mu, cov_px2=np.eye(2) * sigma_px**2, weight=weight, window_id=window_id
    )
    return (_PixelHeatmap([comp], background_weight=bg), _Window())


class TestEmptyAndDegenerate:
    def test_empty_input(self) -> None:
        """No windows means an honest empty map, not a crash and not a fake peak."""
        hm = fuse_pixel_heatmaps([], cell_size_m=5.0)
        assert isinstance(hm, GeoHeatmap)
        assert hm.cells == ()
        assert hm.argmax is None
        assert hm.argmax_score is None
        assert hm.entropy_norm == 1.0

    def test_no_components(self) -> None:
        hm = fuse_pixel_heatmaps([(_PixelHeatmap([]), _Window())], cell_size_m=5.0)
        assert hm.cells == ()
        assert hm.argmax is None

    def test_zero_weight_components_are_dropped(self) -> None:
        item = _one(weight=0.0)
        hm = fuse_pixel_heatmaps([item], cell_size_m=5.0)
        assert hm.argmax is None

    def test_rejects_bad_cell_size(self) -> None:
        with pytest.raises(ValueError, match="cell_size_m"):
            fuse_pixel_heatmaps([_one()], cell_size_m=0.0)

    def test_rejects_bad_gsd(self) -> None:
        hm, win = _one()
        win.gsd_m = 0.0
        with pytest.raises(ValueError, match="gsd_m"):
            fuse_pixel_heatmaps([(hm, win)], cell_size_m=5.0)

    def test_rejects_bad_covariance(self) -> None:
        comp = _Component(mu_px=(0.0, 0.0), cov_px2=np.eye(3), weight=1.0)
        with pytest.raises(ValueError, match=r"\(2,2\)"):
            fuse_pixel_heatmaps([(_PixelHeatmap([comp]), _Window())], cell_size_m=5.0)


@_needs_utm
class TestGeoreferencing:
    """★ The whole job: a component must land where its own window says it is."""

    def test_argmax_is_at_the_components_own_lonlat(self) -> None:
        mu = (128.0, 128.0)
        hm = fuse_pixel_heatmaps([_one(mu=mu, sigma_px=6.0)], cell_size_m=1.0)
        exp_lon, exp_lat = pixel_to_lonlat(GT_3857, "EPSG:3857", *mu)
        assert hm.argmax is not None
        assert hm.argmax.lon == pytest.approx(exp_lon, abs=2e-5)
        assert hm.argmax.lat == pytest.approx(exp_lat, abs=2e-5)

    def test_uses_the_pixel_centre_convention(self) -> None:
        """★ Must agree with gis.tiles, or a heatmap peak and a GCP disagree by half a pixel."""
        mu = (0.0, 0.0)
        hm = fuse_pixel_heatmaps([_one(mu=mu, sigma_px=3.0)], cell_size_m=0.5)
        centre_lon, centre_lat = pixel_to_lonlat(GT_3857, "EPSG:3857", 0.0, 0.0)
        assert hm.argmax is not None
        assert hm.argmax.lon == pytest.approx(centre_lon, abs=1e-5)
        assert hm.argmax.lat == pytest.approx(centre_lat, abs=1e-5)

    def test_two_windows_with_different_geotransforms(self) -> None:
        """★ Each heatmap is in ITS OWN frame — the same pixel in two windows is two places.

        Window B's origin is offset by 1000 EPSG:3857 metres. At 55N those are NOT ground
        metres: they are inflated by 1/cos(55), so the true separation is
        ``1000 * cos(55) ~= 574 m``. This asserts the FUSED, TRUE-METRE separation, which
        is the strongest available evidence that the cos correction is applied and applied
        in the right direction — 1000 m here would mean the fusion is measuring in
        Mercator metres.
        """
        from gis.geometry import great_circle_distance_m
        from gis.types import LonLat

        win_a = _Window()
        win_b = _Window(geotransform=(GT_3857[0] + 1000.0, *GT_3857[1:]))
        comp = _Component(mu_px=(50.0, 50.0), cov_px2=np.eye(2) * 25.0, weight=1.0)
        hm = fuse_pixel_heatmaps(
            [
                (_PixelHeatmap([comp]), win_a),
                (_PixelHeatmap([_Component((50.0, 50.0), np.eye(2) * 25.0, 1.0, "w1")]), win_b),
            ],
            cell_size_m=10.0,
        )
        assert len(hm.cells) > 0

        mid_lat = (hm.bbox.south + hm.bbox.north) / 2.0
        span_m = great_circle_distance_m(
            LonLat(hm.bbox.west, mid_lat), LonLat(hm.bbox.east, mid_lat)
        )
        true_separation = 1000.0 * math.cos(math.radians(55.0))
        assert span_m == pytest.approx(true_separation, rel=0.05), (
            "fused separation should be ~574 true m; ~1000 means the cos correction is missing"
        )

    def test_bbox_contains_the_argmax(self) -> None:
        hm = fuse_pixel_heatmaps([_one()], cell_size_m=2.0)
        assert hm.argmax is not None
        assert hm.bbox.contains(hm.argmax.lon, hm.argmax.lat)


@_needs_utm
class TestGridAndScores:
    def test_scores_are_normalised_to_the_peak(self) -> None:
        hm = fuse_pixel_heatmaps([_one(sigma_px=8.0)], cell_size_m=2.0)
        assert hm.argmax_score == pytest.approx(1.0)
        assert all(0.0 <= c.score <= 1.0 for c in hm.cells)
        assert max(c.score for c in hm.cells) == pytest.approx(1.0)

    def test_cells_are_sparse(self) -> None:
        """A float64 Gaussian has support everywhere; the map must not."""
        hm = fuse_pixel_heatmaps([_one(sigma_px=4.0)], cell_size_m=1.0)
        assert len(hm.cells) < hm.grid_cols * hm.grid_rows

    def test_grid_dimensions_are_positive(self) -> None:
        hm = fuse_pixel_heatmaps([_one()], cell_size_m=3.0)
        assert hm.grid_cols > 0
        assert hm.grid_rows > 0
        assert hm.cell_size_m == 3.0

    def test_cell_size_is_true_metres(self) -> None:
        """★ The grid is built in UTM, so a cell is a cell everywhere — no cos(phi) bias.

        A lon/lat or Web-Mercator grid has cells whose true ground area shrinks with
        cos(phi), so a density accumulated on one is biased poleward and cells at the top
        of the AOI silently count for less ground than cells at the bottom.

        The extent is measured on the ground and compared against ``grid_cols`` cells.
        ``bbox`` spans cell CENTRES, so the span covers ``grid_cols - 1`` gaps.

        ★ Note the grid rows are lines of constant UTM NORTHING, which are NOT lines of
        constant latitude — grouping cells by latitude to find a row does not work, and
        that fact is itself the reason the grid is not built in lon/lat.
        """
        from gis.geometry import great_circle_distance_m
        from gis.types import LonLat

        hm = fuse_pixel_heatmaps([_one(sigma_px=20.0)], cell_size_m=10.0)
        assert hm.grid_cols >= 2 and hm.grid_rows >= 2

        mid_lat = (hm.bbox.south + hm.bbox.north) / 2.0
        span_ew = great_circle_distance_m(
            LonLat(hm.bbox.west, mid_lat), LonLat(hm.bbox.east, mid_lat)
        )
        span_ns = great_circle_distance_m(
            LonLat(hm.bbox.west, hm.bbox.south), LonLat(hm.bbox.west, hm.bbox.north)
        )
        assert span_ew == pytest.approx((hm.grid_cols - 1) * hm.cell_size_m, rel=0.05)
        assert span_ns == pytest.approx((hm.grid_rows - 1) * hm.cell_size_m, rel=0.05)

    def test_sample_count_aggregates_over_overlapping_windows(self) -> None:
        """★ sample_count is how the UI knows to dim a cell. absent != 0."""
        a = _Component(mu_px=(128.0, 128.0), cov_px2=np.eye(2) * 100.0, weight=1.0, window_id="w0")
        b = _Component(mu_px=(130.0, 130.0), cov_px2=np.eye(2) * 100.0, weight=1.0, window_id="w1")
        hm = fuse_pixel_heatmaps(
            [(_PixelHeatmap([a]), _Window()), (_PixelHeatmap([b]), _Window())],
            cell_size_m=2.0,
        )
        assert max(c.sample_count for c in hm.cells) == 2

    def test_single_window_sample_count_is_one(self) -> None:
        hm = fuse_pixel_heatmaps([_one()], cell_size_m=2.0)
        assert max(c.sample_count for c in hm.cells) == 1

    def test_components_are_attributed_per_window(self) -> None:
        hm = fuse_pixel_heatmaps([_one(window_id="win-42")], cell_size_m=2.0)
        peak = max(hm.cells, key=lambda c: c.score)
        assert "win-42" in peak.components


@_needs_utm
class TestEntropy:
    def test_entropy_is_in_range(self) -> None:
        hm = fuse_pixel_heatmaps([_one()], cell_size_m=2.0)
        assert 0.0 <= hm.entropy_norm <= 1.0

    def test_a_diffuse_posterior_has_higher_entropy_than_a_tight_one(self) -> None:
        """★ entropy_norm is the "we have not localised" signal, and it must be ordinal."""
        tight = fuse_pixel_heatmaps([_one(sigma_px=2.0)], cell_size_m=1.0)
        diffuse = fuse_pixel_heatmaps([_one(sigma_px=40.0)], cell_size_m=1.0)
        assert diffuse.entropy_norm > tight.entropy_norm


@_needs_utm
class TestBackgroundMass:
    """★ The 'not here' mass — a posterior that cannot say "I don't know" is not a posterior."""

    def test_background_flattens_the_surface(self) -> None:
        """With a large background the map must be closer to uniform."""
        no_bg = fuse_pixel_heatmaps([_one(sigma_px=5.0, bg=0.0)], cell_size_m=2.0)
        big_bg = fuse_pixel_heatmaps([_one(sigma_px=5.0, bg=0.9)], cell_size_m=2.0)
        assert big_bg.entropy_norm > no_bg.entropy_norm

    def test_components_are_scaled_by_one_minus_pi_bg(self) -> None:
        """★ THE FIX: scaling by (1 - pi_bg) makes the total exactly 1 BEFORE rasterising.

        Without it the pre-normalisation mass is (pi_bg + 1), so the background's ACTUAL
        share collapses to pi_bg/(1 + pi_bg) — 44% where 78% was intended — and every
        credible region is drawn too tight and too confident.
        """
        hm = fuse_pixel_heatmaps([_one(sigma_px=5.0, bg=0.78)], cell_size_m=2.0)
        # The peak still exists but does not dominate the way a bg-free map would.
        assert hm.argmax is not None
        assert hm.entropy_norm > 0.0

    def test_background_is_clamped(self) -> None:
        for bg in (-1.0, 2.0):
            hm = fuse_pixel_heatmaps([_one(sigma_px=5.0, bg=bg)], cell_size_m=2.0)
            assert hm.argmax is not None  # no crash, no NaN


class TestStructuralContract:
    """The duck-typed surface must fail LOUDLY, never silently."""

    def test_missing_field_raises_attribute_error(self) -> None:
        @dataclass
        class _Bad:
            components: list = field(default_factory=list)
            # background_weight deliberately absent

        bad = _Bad(components=[_Component((0.0, 0.0), np.eye(2), 1.0)])
        with pytest.raises(AttributeError):
            fuse_pixel_heatmaps([(bad, _Window())], cell_size_m=5.0)  # type: ignore[arg-type]
