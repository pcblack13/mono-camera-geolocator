"""IU-12 · ``gis.candidates`` — the hint, the plan, the budget, and ★ THE SEAM (§13.1).

What this suite is really defending:

* **The seam is structural.** ``TileWindowSource`` satisfies ``ai_engine.types.WindowSource``
  without inheriting from it, and ``gis.candidates`` imports nothing else from the engine.
  Both are asserted mechanically — the second by parsing the source, because an import that
  sneaks in during a refactor is exactly the kind of thing a reviewer waves through.
* **The plan is known before the I/O.** ``len()`` is exact with a socket-blocking provider
  that has never been touched, and the budget guard fires with the fetch counter still at
  zero. Everything about the cost of a job is decidable before accepting it.
* **Nothing degrades silently.** A clamped zoom reaches ``meta["zoom_clamped"]``; a missing
  tile skips rather than fails; a provider failure crosses the seam as the one exception the
  engine is allowed to name; an unhinted search raises instead of guessing.
* **The 512 px guarantee is arithmetic, not a comment.** It is asserted as a property over
  the actual lattice, footprint by footprint.

★ NO NETWORK. The provider here is a local stub that counts its own calls.
"""

from __future__ import annotations

import ast
import math
from pathlib import Path

import numpy as np
import pytest

from ai_engine.errors import WindowFetchError
from ai_engine.types import CandidateWindow, WindowSource
from gis.candidates import budget as budget_mod
from gis.candidates.budget import check_aoi_area, check_tile_budget, estimate_budget
from gis.candidates.hint import SearchHint, resolve_hint
from gis.candidates.source import GUARANTEED_FOOTPRINT_PX, TileWindowSource
from gis.candidates.strategy import (
    _lonlat_to_global_px,
    guaranteed_footprint_px,
    plan_search,
    stride_px,
)
from gis.errors import (
    AreaTooLargeError,
    ProviderRateLimitError,
    SearchHintRequired,
    TileNotAvailableError,
)
from gis.imagery.base import (
    ImageryProvider,
    ProviderCapabilities,
    TileProviderMixin,
)
from gis.types import BasemapKind, BBox, LonLat

# A hectare of Bavarian farmland: 48.1 N, 11.6 E. Mid-latitude, so the cos(phi) factor is
# ~0.67 — a bug that drops it would be visible here, unlike at the equator.
_LON = 11.6
_LAT = 48.1
_CENTER = LonLat(lon=_LON, lat=_LAT)


# --------------------------------------------------------------------------- stubs


class _StubProvider(TileProviderMixin, ImageryProvider):
    """A deterministic offline provider that counts every tile it is asked for.

    Not a mock: it is a real ``ImageryProvider`` and goes through the real
    ``TileProviderMixin.get_static_bbox`` — the same stitch, crop and geotransform folding
    a live provider uses. Only the bytes are invented.
    """

    def __init__(
        self,
        *,
        min_zoom: int = 0,
        max_zoom: int = 19,
        tile_size_px: int = 256,
        missing: bool = False,
        raises: Exception | None = None,
        supports_tiles: bool = True,
        supports_multispectral: bool = False,
        requires_attribution: bool = True,
        attribution: str = "Stub imagery",
        max_static_px: tuple[int, int] | None = (4096, 4096),
    ) -> None:
        self._min_zoom = min_zoom
        self._max_zoom = max_zoom
        self._tile_size_px = tile_size_px
        self._missing = missing
        self._raises = raises
        self._supports_tiles = supports_tiles
        self._supports_multispectral = supports_multispectral
        self._requires_attribution = requires_attribution
        self._attribution = attribution
        self._max_static_px = max_static_px
        self.tile_calls = 0

    @property
    def name(self) -> str:
        return "fixture"  # A real member of PROVIDER_NAMES; this stub stands in for it.

    @property
    def requires_api_key(self) -> bool:
        return False

    @property
    def min_zoom(self) -> int:
        return self._min_zoom

    @property
    def max_zoom(self) -> int:
        return self._max_zoom

    @property
    def attribution(self) -> str:
        return self._attribution

    @property
    def terms_url(self) -> str:
        return "https://example.invalid/terms"

    def is_configured(self) -> bool:
        return True

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_tiles=self._supports_tiles,
            supports_static_bbox=True,
            supports_offline=True,
            native_crs="EPSG:3857",
            tile_size_px=self._tile_size_px,
            typical_gsd_m=0.5,
            georef_ce90_m=3.0,
            imagery_date_known=False,
            rate_limit_rps=None,
            requires_attribution=self._requires_attribution,
            allows_caching=True,
            allows_derivative_export=True,
            max_static_px=self._max_static_px,
            supports_multispectral=self._supports_multispectral,
        )

    def get_tile(self, z: int, x: int, y: int, *, kind: BasemapKind = BasemapKind.SATELLITE):
        self.tile_calls += 1
        if self._raises is not None:
            raise self._raises
        if self._missing:
            raise TileNotAvailableError("stub has no imagery here", provider=self.name)
        s = self._tile_size_px
        # Deterministic in (z, x, y) so a window's pixels are a function of where it is.
        tile = np.empty((s, s, 3), dtype=np.uint8)
        tile[:, :, 0] = x % 256
        tile[:, :, 1] = y % 256
        tile[:, :, 2] = z % 256
        return tile


def _aoi(radius_m: float = 400.0) -> BBox:
    from gis.geometry import disc_to_bbox

    return disc_to_bbox(_CENTER, radius_m)


# --------------------------------------------------------------------------- hint


def test_search_hint_defaults_are_the_contract() -> None:
    hint = SearchHint()
    assert hint.aoi is None
    assert hint.center is None
    assert hint.radius_m == 1000.0
    assert hint.zoom_levels == (18,)
    assert hint.use_image_gps is True


@pytest.mark.parametrize(
    "kwargs",
    [
        {"radius_m": 0.0},
        {"radius_m": -1.0},
        {"radius_m": math.inf},
        {"zoom_levels": ()},
        {"zoom_levels": (25,)},
        {"zoom_levels": (-1,)},
    ],
)
def test_search_hint_rejects_nonsense(kwargs: dict) -> None:
    """★ An empty ``zoom_levels`` is REFUSED, not defaulted: a search at no zoom finds
    nothing, and by the time "found nothing" reaches a user it is indistinguishable from a
    genuine no-match."""
    with pytest.raises(ValueError):
        SearchHint(**kwargs)


def test_resolve_hint_1_explicit_aoi_wins_and_ignores_radius() -> None:
    aoi = BBox(west=11.0, south=48.0, east=11.1, north=48.1)
    got = resolve_hint(
        SearchHint(aoi=aoi, center=_CENTER, radius_m=50_000.0),
        exif_gps=LonLat(lon=0.0, lat=0.0),
        geotiff_bounds=BBox(west=1.0, south=1.0, east=2.0, north=2.0),
        project_aoi=BBox(west=3.0, south=3.0, east=4.0, north=4.0),
    )
    assert got == aoi


def test_resolve_hint_2_center_and_radius() -> None:
    got = resolve_hint(
        SearchHint(center=_CENTER, radius_m=1000.0),
        exif_gps=LonLat(lon=0.0, lat=0.0),
        geotiff_bounds=BBox(west=1.0, south=1.0, east=2.0, north=2.0),
        project_aoi=BBox(west=3.0, south=3.0, east=4.0, north=4.0),
    )
    assert got.contains(_LON, _LAT)
    # ~1 km north-south either side, and never smaller than the radius asked for.
    assert got.area_m2() >= math.pi * 1000.0**2


def test_resolve_hint_3_exif_gps() -> None:
    got = resolve_hint(
        SearchHint(radius_m=500.0),
        exif_gps=_CENTER,
        geotiff_bounds=BBox(west=1.0, south=1.0, east=2.0, north=2.0),
        project_aoi=BBox(west=3.0, south=3.0, east=4.0, north=4.0),
    )
    assert got.contains(_LON, _LAT)


def test_resolve_hint_4_geotiff_bounds() -> None:
    bounds = BBox(west=11.0, south=48.0, east=11.1, north=48.1)
    got = resolve_hint(
        SearchHint(),
        exif_gps=None,
        geotiff_bounds=bounds,
        project_aoi=BBox(west=3.0, south=3.0, east=4.0, north=4.0),
    )
    assert got == bounds


def test_resolve_hint_5_project_aoi() -> None:
    project = BBox(west=3.0, south=3.0, east=4.0, north=4.0)
    got = resolve_hint(
        SearchHint(), exif_gps=None, geotiff_bounds=None, project_aoi=project
    )
    assert got == project


def test_resolve_hint_6_nothing_resolves_raises() -> None:
    """★ THE HONEST CASE. No hint at all is not a slow search, it is an impossible one:
    ~6.9e10 tiles at z18, and ambiguous even if we could afford it. It raises."""
    with pytest.raises(SearchHintRequired):
        resolve_hint(SearchHint(), exif_gps=None, geotiff_bounds=None, project_aoi=None)


def test_resolve_hint_use_image_gps_false_skips_both_image_sources() -> None:
    """``use_image_gps=False`` gates steps 3 AND 4 — both are the image's own claims."""
    project = BBox(west=3.0, south=3.0, east=4.0, north=4.0)
    got = resolve_hint(
        SearchHint(use_image_gps=False),
        exif_gps=_CENTER,
        geotiff_bounds=BBox(west=1.0, south=1.0, east=2.0, north=2.0),
        project_aoi=project,
    )
    assert got == project

    with pytest.raises(SearchHintRequired):
        resolve_hint(
            SearchHint(use_image_gps=False),
            exif_gps=_CENTER,
            geotiff_bounds=BBox(west=1.0, south=1.0, east=2.0, north=2.0),
            project_aoi=None,
        )


def test_resolve_hint_exif_error_can_only_inflate() -> None:
    """★ A poor fix WIDENS the search; it never narrows it. A box that confidently excludes
    the right answer returns a plausible match from the neighbouring field, and the surveyor
    believes it."""
    small = resolve_hint(
        SearchHint(radius_m=300.0), exif_gps=_CENTER, geotiff_bounds=None, project_aoi=None
    )
    inflated = resolve_hint(
        SearchHint(radius_m=300.0),
        exif_gps=_CENTER,
        geotiff_bounds=None,
        project_aoi=None,
        exif_hpe_m=200.0,  # -> max(300, 200 * 3) = 600 m
    )
    assert inflated.area_m2() > small.area_m2()

    # A good fix does not SHRINK the requested radius.
    good = resolve_hint(
        SearchHint(radius_m=5_000.0),
        exif_gps=_CENTER,
        geotiff_bounds=None,
        project_aoi=None,
        exif_hpe_m=1.0,
    )
    assert good.area_m2() == pytest.approx(
        resolve_hint(
            SearchHint(radius_m=5_000.0),
            exif_gps=_CENTER,
            geotiff_bounds=None,
            project_aoi=None,
        ).area_m2()
    )


@pytest.mark.parametrize("hpe", [None, math.nan, math.inf, -1.0])
def test_resolve_hint_unusable_exif_error_is_ignored(hpe: float | None) -> None:
    """A malformed error claim is a fact about the file, not a reason to crash."""
    got = resolve_hint(
        SearchHint(radius_m=400.0),
        exif_gps=_CENTER,
        geotiff_bounds=None,
        project_aoi=None,
        exif_hpe_m=hpe,
    )
    assert got.contains(_LON, _LAT)


# --------------------------------------------------------------------------- strategy


def test_stride_and_guarantee_arithmetic() -> None:
    assert stride_px(1024, 0.5) == 512
    assert guaranteed_footprint_px(1024, 0.5) == 512  # ✔ the design's number
    assert stride_px(1024, 0.25) == 768
    assert guaranteed_footprint_px(1024, 0.25) == 256  # ✘ half the guarantee
    assert stride_px(512, 0.0) == 512
    assert stride_px(1024, 0.99) == 10  # Never zero: a zero stride is an infinite lattice.


@pytest.mark.parametrize("overlap", [-0.1, 1.0, 1.5, math.nan])
def test_stride_rejects_impossible_overlap(overlap: float) -> None:
    with pytest.raises(ValueError):
        stride_px(1024, overlap)


def test_plan_search_clamps_zoom_and_never_returns_empty() -> None:
    """★ THE GOLDEN (§13.1). ``LE_SENTINEL_MAX_ZOOM=15`` against a default z18 request.

    The two answers that must never happen: zero windows (every job dying as
    ``no_viable_candidate``, indistinguishable from a genuine no-match) and a silent clamp
    to 10 m imagery under a job row still claiming z18. Instead: clamped, and the caller is
    told, in a field routed all the way to a warning and a quality flag.
    """
    plans = plan_search(
        _aoi(),
        zoom_levels=(18,),
        min_zoom=0,
        max_zoom=15,
        window_size_px=1024,
        tile_size_px=256,
        overlap_ratio=0.5,
        max_windows=25,
    )
    assert plans, "clamping must never yield an empty plan"
    assert {p.zoom for p in plans} == {15}
    assert all(p.zoom_decision.clamped for p in plans)
    assert all(p.zoom_decision.zoom == 15 for p in plans)
    # The decision reports BOTH resolutions honestly: what was asked, what was served.
    assert all(p.zoom_decision.achieved_mpp > p.zoom_decision.requested_mpp for p in plans)


def test_plan_search_unclamped_zoom_reports_it() -> None:
    plans = plan_search(
        _aoi(),
        zoom_levels=(18,),
        min_zoom=0,
        max_zoom=19,
        window_size_px=1024,
        tile_size_px=256,
        overlap_ratio=0.5,
        max_windows=25,
    )
    assert plans
    assert all(not p.zoom_decision.clamped for p in plans)
    assert all(p.zoom == 18 for p in plans)


def test_plan_search_dedupes_zooms_that_clamp_together() -> None:
    """z18 and z19 both clamp to z15: one search, not two identical ones."""
    plans = plan_search(
        _aoi(),
        zoom_levels=(18, 19),
        min_zoom=0,
        max_zoom=15,
        window_size_px=1024,
        tile_size_px=256,
        overlap_ratio=0.5,
        max_windows=100,
    )
    assert {p.zoom for p in plans} == {15}
    assert all(p.zoom_decision.requested_mpp == plans[0].zoom_decision.requested_mpp for p in plans)


def test_plan_search_respects_max_windows_and_ordinals_are_contiguous() -> None:
    plans = plan_search(
        _aoi(2_000.0),
        zoom_levels=(18,),
        min_zoom=0,
        max_zoom=19,
        window_size_px=1024,
        tile_size_px=256,
        overlap_ratio=0.5,
        max_windows=7,
    )
    assert len(plans) == 7
    assert [p.ordinal for p in plans] == list(range(7))


def test_plan_search_truncation_keeps_the_centre() -> None:
    """★ Truncation is the NORMAL case, so what it keeps matters. The centre is where every
    hint says the photograph was taken; row-major order would drop the southern two thirds
    of the area for no reason at all."""
    aoi = _aoi(2_000.0)
    plans = plan_search(
        aoi,
        zoom_levels=(18,),
        min_zoom=0,
        max_zoom=19,
        window_size_px=1024,
        tile_size_px=256,
        overlap_ratio=0.5,
        max_windows=1,
    )
    assert len(plans) == 1
    assert plans[0].bbox.contains(*aoi.center())


def test_plan_search_interleaves_zoom_levels_under_truncation() -> None:
    """★ Zoom-major order would let ``max_windows`` silently delete the second zoom — a
    multi-zoom search that quietly became a single-zoom one."""
    plans = plan_search(
        _aoi(2_000.0),
        zoom_levels=(17, 18),
        min_zoom=0,
        max_zoom=19,
        window_size_px=1024,
        tile_size_px=256,
        overlap_ratio=0.5,
        max_windows=6,
    )
    assert len(plans) == 6
    assert {p.zoom for p in plans} == {17, 18}


def test_plan_search_is_deterministic() -> None:
    kwargs = dict(
        zoom_levels=(17, 18),
        min_zoom=0,
        max_zoom=19,
        window_size_px=1024,
        tile_size_px=256,
        overlap_ratio=0.5,
        max_windows=13,
    )
    first = plan_search(_aoi(1_500.0), **kwargs)
    second = plan_search(_aoi(1_500.0), **kwargs)
    assert first == second


def test_plan_search_overlap_ratio_sets_the_stride() -> None:
    """A denser overlap is more windows over the same ground — the parameter is real."""
    kwargs = dict(
        zoom_levels=(18,),
        min_zoom=0,
        max_zoom=19,
        window_size_px=1024,
        tile_size_px=256,
        max_windows=10_000,
    )
    sparse = plan_search(_aoi(1_500.0), overlap_ratio=0.0, **kwargs)
    dense = plan_search(_aoi(1_500.0), overlap_ratio=0.5, **kwargs)
    assert len(dense) > len(sparse)


def test_plan_search_tile_size_is_used_not_assumed() -> None:
    """★ A hardcoded 256 against a 512 provider is a silent 2x error in ground extent. At
    the same zoom, a 512 px tile provider's 1024 px window covers a quarter of the ground,
    so it takes ~4x the windows to cover the same area."""
    kwargs = dict(
        zoom_levels=(18,),
        min_zoom=0,
        max_zoom=19,
        window_size_px=1024,
        overlap_ratio=0.5,
        max_windows=10_000,
    )
    at_256 = plan_search(_aoi(1_000.0), tile_size_px=256, **kwargs)
    at_512 = plan_search(_aoi(1_000.0), tile_size_px=512, **kwargs)
    assert len(at_512) > len(at_256)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"zoom_levels": ()},
        {"max_windows": 0},
        {"min_zoom": 19, "max_zoom": 15},
        {"tile_size_px": 0},
        {"window_size_px": 0},
        {"overlap_ratio": 1.0},
    ],
)
def test_plan_search_refuses_rather_than_returning_nothing(kwargs: dict) -> None:
    """★ Every one of these would otherwise return an empty plan, and an empty plan reads
    downstream as "we looked and found nothing"."""
    base = dict(
        zoom_levels=(18,),
        min_zoom=0,
        max_zoom=19,
        window_size_px=1024,
        tile_size_px=256,
        overlap_ratio=0.5,
        max_windows=25,
    )
    with pytest.raises(ValueError):
        plan_search(_aoi(), **{**base, **kwargs})


def test_plan_search_rejects_an_antimeridian_aoi() -> None:
    """Rejected, never silently wrapped: a wrapped box enumerates the whole world the
    wrong way round."""
    with pytest.raises(ValueError, match="antimeridian"):
        plan_search(
            BBox(west=179.5, south=-1.0, east=-179.5, north=1.0),
            zoom_levels=(18,),
            min_zoom=0,
            max_zoom=19,
            window_size_px=1024,
            tile_size_px=256,
            overlap_ratio=0.5,
            max_windows=25,
        )


def test_plan_search_near_the_antimeridian_stays_representable() -> None:
    """A window that would run off the edge of the world is clamped to it, not projected
    past |lon| = 180 where BBox — correctly — refuses to exist."""
    plans = plan_search(
        BBox(west=179.90, south=0.0, east=179.99, north=0.09),
        zoom_levels=(18,),
        min_zoom=0,
        max_zoom=19,
        window_size_px=1024,
        tile_size_px=256,
        overlap_ratio=0.5,
        max_windows=25,
    )
    assert plans
    assert all(p.bbox.east <= 180.0 and p.bbox.west >= -180.0 for p in plans)


def test_plan_search_refuses_an_aoi_outside_the_mercator_world() -> None:
    with pytest.raises(ValueError, match="Mercator"):
        plan_search(
            BBox(west=10.0, south=86.0, east=11.0, north=88.0),
            zoom_levels=(18,),
            min_zoom=0,
            max_zoom=19,
            window_size_px=1024,
            tile_size_px=256,
            overlap_ratio=0.5,
            max_windows=25,
        )


def test_the_512px_footprint_guarantee_holds_over_the_whole_lattice() -> None:
    """★ THE GUARANTEE THE OVERLAP RATIO EXISTS TO BUY, asserted as arithmetic.

    Any footprint of ``GUARANTEED_FOOTPRINT_PX`` or smaller, anywhere in the area of
    interest, lies WHOLLY inside at least one window. The failure this prevents is silent
    and location-dependent — it depends on where the field falls against the lattice — so it
    presents as an intermittent, irreproducible "no match" on a perfectly correct area.
    """
    z, tile_size, window = 18, 256, 1024
    aoi = _aoi(600.0)
    plans = plan_search(
        aoi,
        zoom_levels=(z,),
        min_zoom=0,
        max_zoom=19,
        window_size_px=window,
        tile_size_px=tile_size,
        overlap_ratio=0.5,
        max_windows=10_000,  # No truncation: the guarantee is a property of the lattice.
    )
    boxes = [
        (
            *_lonlat_to_global_px(p.bbox.west, p.bbox.north, z, tile_size),
            *_lonlat_to_global_px(p.bbox.east, p.bbox.south, z, tile_size),
        )
        for p in plans
    ]
    x0, y0 = _lonlat_to_global_px(aoi.west, aoi.north, z, tile_size)
    x1, y1 = _lonlat_to_global_px(aoi.east, aoi.south, z, tile_size)

    g = float(GUARANTEED_FOOTPRINT_PX)
    steps = 17
    # A window's bbox is drawn one ten-thousandth of a pixel inside its own pixel extent so
    # that its tile range is decidable (see strategy._EDGE_INSET_PX). Allow a thousandth of
    # a pixel — 4e-9 m at z18 — for it. Anything the eye or the imagery could resolve is
    # eight orders of magnitude above this.
    tol = 1e-3
    for i in range(steps):
        for j in range(steps):
            # Every footprint origin such that the footprint still lies inside the aoi.
            ax = x0 + (x1 - g - x0) * i / (steps - 1)
            ay = y0 + (y1 - g - y0) * j / (steps - 1)
            assert any(
                left <= ax + tol
                and ax + g <= right + tol
                and top <= ay + tol
                and ay + g <= bottom + tol
                for left, top, right, bottom in boxes
            ), f"footprint at ({ax:.1f}, {ay:.1f}) straddles every window boundary"


def test_plan_bbox_matches_its_tile_range() -> None:
    """The tile range is the one covering the window, at the window's zoom — which is what
    makes the budget's arithmetic the real fetch count."""
    from gis.tiles import bbox_to_tile_range

    for plan in plan_search(
        _aoi(),
        zoom_levels=(18,),
        min_zoom=0,
        max_zoom=19,
        window_size_px=1024,
        tile_size_px=256,
        overlap_ratio=0.5,
        max_windows=25,
    ):
        assert plan.tile_range == bbox_to_tile_range(plan.bbox, plan.zoom)
        assert plan.tile_range.z == plan.zoom


# --------------------------------------------------------------------------- budget


def _plans(radius_m: float = 400.0, max_windows: int = 25):
    return plan_search(
        _aoi(radius_m),
        zoom_levels=(18,),
        min_zoom=0,
        max_zoom=19,
        window_size_px=1024,
        tile_size_px=256,
        overlap_ratio=0.5,
        max_windows=max_windows,
    )


def test_estimate_budget_counts_gross_fetches_and_reports_redundancy() -> None:
    """★ The budget counts TILE FETCHES, not distinct tiles. Overlapping windows re-request
    the same tiles ~4x at overlap 0.5, and a budget that assumes a warm cache is not a
    budget — ``LE_MAX_TILES_PER_JOB`` was re-costed to 512 for exactly this reason."""
    plans = _plans()
    est = estimate_budget(plans)
    assert est.window_count == len(plans)
    assert est.tile_fetches == sum(len(p.tile_range) for p in plans)
    assert est.distinct_tiles <= est.tile_fetches
    assert est.redundancy >= 1.0
    assert est.max_tile_fetches == budget_mod.DEFAULT_MAX_TILE_FETCHES


def test_budget_guard_raises_before_any_io() -> None:
    """★ §13.1: the guard fires with the fetch counter still at zero. A job that cannot
    afford itself is refused at submission, not discovered thirty seconds in having already
    spent someone's quota."""
    provider = _StubProvider()
    plans = _plans(2_000.0, max_windows=25)
    with pytest.raises(AreaTooLargeError) as excinfo:
        check_tile_budget(plans, max_tile_fetches=8, provider=provider.name)
    assert provider.tile_calls == 0
    assert "tile fetches" in str(excinfo.value)
    assert excinfo.value.provider == "fixture"
    assert excinfo.value.retryable is False  # A budget is not a transient failure.


def test_budget_guard_passes_a_plan_that_fits() -> None:
    budget = check_tile_budget(_plans(), max_tile_fetches=100_000)
    assert budget.over_budget is False


@pytest.mark.parametrize("lon", [-170.3, -60.7, -0.4, 11.6, 90.2, 179.1])
@pytest.mark.parametrize("lat", [-54.9, -12.3, 0.7, 33.4, 48.1, 66.8])
def test_a_default_job_fits_the_default_budget_everywhere_on_earth(lon: float, lat: float) -> None:
    """★ THE REGRESSION TEST FOR A BUG THIS SUITE FOUND. ``LE_SEARCH_MAX_CANDIDATES=25`` and
    ``LE_MAX_TILES_PER_JOB=512`` are two views of one number: 25 tile-aligned windows of
    1024 px against 256 px tiles is 25 x 16 = 400 fetches, and 400 < 512.

    It is parametrised over the planet because the first implementation was NOT, and the
    defect it missed was exactly location-dependent: an unaligned window costs 5x5 = 25
    tiles instead of 4x4 = 16, and whether a window lands aligned depended on ~1e-11 of
    projection round-trip noise. Measured across 800 locations, the cost ranged from 400 to
    586 and ~2% of the planet EXCEEDED ITS OWN DEFAULT BUDGET — a job that 422s because of
    the longitude it happens to be at, which is unreproducible on the reporter's machine
    and undebuggable from the message. A single-location test passed the whole time.
    """
    from gis.geometry import disc_to_bbox

    plans = plan_search(
        disc_to_bbox(LonLat(lon=lon, lat=lat), 5_000.0),
        zoom_levels=(18,),
        min_zoom=0,
        max_zoom=19,
        window_size_px=1024,
        tile_size_px=256,
        overlap_ratio=0.5,
        max_windows=25,
    )
    est = estimate_budget(plans)
    assert est.window_count == 25
    assert {len(p.tile_range) for p in plans} == {16}, "windows must sit ON the tile grid"
    assert est.tile_fetches == 400
    assert est.tile_fetches <= budget_mod.DEFAULT_MAX_TILE_FETCHES


@pytest.mark.parametrize(("tile_size_px", "expected"), [(256, 16), (512, 4)])
def test_every_window_costs_its_ideal_tile_count(tile_size_px: int, expected: int) -> None:
    """A 1024 px window is exactly ``(1024/S)**2`` tiles when it sits on the tile grid, and
    56% more when it straddles it — the same pixels, more requests, for nothing."""
    plans = plan_search(
        _aoi(3_000.0),
        zoom_levels=(18,),
        min_zoom=0,
        max_zoom=19,
        window_size_px=1024,
        tile_size_px=tile_size_px,
        overlap_ratio=0.5,
        max_windows=25,
    )
    assert {len(p.tile_range) for p in plans} == {expected}


def test_a_tightly_hinted_search_is_one_window() -> None:
    """An area smaller than a window must not buy a ring of them. This is the common case:
    a GNSS fix with a small radius is the best hint the product ever gets."""
    plans = plan_search(
        _aoi(120.0),
        zoom_levels=(18,),
        min_zoom=0,
        max_zoom=19,
        window_size_px=1024,
        tile_size_px=256,
        overlap_ratio=0.5,
        max_windows=25,
    )
    assert len(plans) == 1


def test_check_aoi_area_guards_the_hint_itself() -> None:
    assert check_aoi_area(_aoi(1_000.0)) < 20.0
    with pytest.raises(AreaTooLargeError):
        check_aoi_area(BBox(west=0.0, south=0.0, east=10.0, north=10.0))


def test_estimate_budget_rejects_a_nonsense_limit() -> None:
    with pytest.raises(ValueError):
        estimate_budget(_plans(), max_tile_fetches=0)


# --------------------------------------------------------------------------- the seam


def test_tile_window_source_structurally_satisfies_the_protocol() -> None:
    """★ THE SEAM. ``TileWindowSource`` satisfies ``WindowSource`` WITHOUT inheriting from
    it — that is what a structural Protocol buys, and it is why ``gis`` may import the
    engine's types at all."""
    source = TileWindowSource(_StubProvider(), _aoi(), zoom_levels=(18,))
    assert isinstance(source, WindowSource)
    assert WindowSource not in type(source).__mro__
    assert isinstance(source.name, str) and source.name


def test_len_is_exact_and_known_before_any_fetch() -> None:
    """★ §13.1. The plan is computed before any I/O, which is what makes the budget
    enforceable up front and progress reporting honest."""
    provider = _StubProvider()
    source = TileWindowSource(provider, _aoi(), zoom_levels=(18,), max_windows=25)
    assert provider.tile_calls == 0
    assert len(source) == len(source.plans)
    assert len(source) > 0
    assert provider.tile_calls == 0  # `len` fetches nothing either.


def test_iteration_is_lazy() -> None:
    provider = _StubProvider()
    source = TileWindowSource(provider, _aoi(), zoom_levels=(18,))
    iterator = iter(source)
    assert provider.tile_calls == 0
    next(iterator)
    after_one = provider.tile_calls
    assert after_one > 0
    next(iterator)
    assert provider.tile_calls > after_one


def test_windows_carry_the_full_contract() -> None:
    provider = _StubProvider()
    source = TileWindowSource(provider, _aoi(300.0), zoom_levels=(18,), max_windows=3)
    windows = list(source)
    assert windows
    for window in windows:
        assert isinstance(window, CandidateWindow)
        assert window.rgb.dtype == np.uint8
        assert window.rgb.ndim == 3 and window.rgb.shape[2] == 3
        assert window.rgb.flags["C_CONTIGUOUS"]
        assert window.gsd_m > 0.0  # TRUE ground metres, cos(phi)-corrected by the provider.
        assert window.georef_ce90_m == 3.0
        assert window.attribution == "Stub imagery"  # ★ A licence condition, not a nicety.
        assert window.terms_url
        assert window.crs == "EPSG:3857"
        assert len(window.geotransform) == 6
        assert window.ref.provider == "fixture"
        assert window.ref.key


def test_window_gsd_is_true_ground_metres_not_a_mercator_metre() -> None:
    """★ THE 1/cos(phi) TRAP. ``geotransform[1]`` is a Web Mercator metre — inflated by
    1/cos(phi), which is ~1.5x at 48 N. ``gsd_m`` is the only sanctioned metric scale in the
    engine and it must be the corrected one; anything metric built from the transform is
    silently wrong by that factor."""
    source = TileWindowSource(_StubProvider(), _aoi(300.0), zoom_levels=(18,), max_windows=1)
    window = next(iter(source))
    mercator_mpp = window.geotransform[1]
    assert window.gsd_m < mercator_mpp
    assert window.gsd_m == pytest.approx(mercator_mpp * math.cos(math.radians(_LAT)), rel=1e-3)


def test_window_meta_carries_the_normative_keys() -> None:
    provider = _StubProvider()
    source = TileWindowSource(provider, _aoi(300.0), zoom_levels=(18,), max_windows=2)
    for plan, window in zip(source.plans, source, strict=False):
        assert set(window.meta) == {
            "tile_z",
            "tile_x",
            "tile_y",
            "mosaic_cols",
            "mosaic_rows",
            "zoom_clamped",
        }
        # The ANCHOR tile: the window's north-west-most source tile. Addressing metadata
        # only — the window's transform is its geotransform, never these three.
        assert window.meta["tile_z"] == plan.zoom
        assert window.meta["tile_x"] == plan.tile_range.min_x
        assert window.meta["tile_y"] == plan.tile_range.min_y
        assert window.meta["mosaic_cols"] == plan.tile_range.cols
        assert window.meta["zoom_clamped"] is False


def test_zoom_clamped_reaches_the_window_meta() -> None:
    """★ THE LOOP CLOSED. ``ZoomDecision.clamped`` exists for exactly this, and in v1.0
    nothing routed it anywhere: plan -> meta["zoom_clamped"] -> a ZOOM_CLAMPED warning ->
    degraded = true -> a quality flag."""
    provider = _StubProvider(max_zoom=15)
    source = TileWindowSource(provider, _aoi(300.0), zoom_levels=(18,), max_windows=1)
    window = next(iter(source))
    assert window.meta["zoom_clamped"] is True
    assert window.meta["tile_z"] == 15


def test_meta_is_null_for_a_provider_with_no_tile_pyramid() -> None:
    """Nullable at the DB for exactly this case (§5.6) — not zero, not a fake triple."""
    provider = _StubProvider(supports_tiles=False)
    source = TileWindowSource(provider, _aoi(300.0), zoom_levels=(18,), max_windows=1)
    window = next(iter(source))
    assert window.meta["tile_z"] is None
    assert window.meta["tile_x"] is None
    assert window.meta["mosaic_rows"] is None
    assert window.meta["zoom_clamped"] is False


def test_window_key_is_geometry_not_enumeration() -> None:
    """★ The key is a cache key: the same key must mean the same pixels. So it is a pure
    function of the window's geometry and the ordinal is nowhere near it — otherwise a
    truncated plan would re-key every window it kept."""
    aoi = _aoi(300.0)
    a = list(TileWindowSource(_StubProvider(), aoi, zoom_levels=(18,), max_windows=3))
    b = list(TileWindowSource(_StubProvider(), aoi, zoom_levels=(18,), max_windows=1))
    assert a[0].ref.key == b[0].ref.key
    assert len({w.ref.key for w in a}) == len(a)  # Distinct windows, distinct keys.


def test_missing_imagery_skips_the_window_rather_than_failing() -> None:
    """★ ``TileNotAvailableError`` is not an error here — it is the provider's honest
    "there is no imagery here" (ocean, a gap, a cloud). The window is skipped."""
    provider = _StubProvider(missing=True)
    source = TileWindowSource(provider, _aoi(300.0), zoom_levels=(18,), max_windows=3)
    assert len(source) == 3
    assert list(source) == []  # Skipped, and nothing raised.


def test_len_is_an_upper_bound_on_what_is_yielded() -> None:
    """And deliberately so: knowing which windows have imagery requires fetching them, so
    the alternative to an upper bound is planning by network call."""
    provider = _StubProvider(missing=True)
    source = TileWindowSource(provider, _aoi(300.0), zoom_levels=(18,), max_windows=3)
    assert len(list(source)) <= len(source)


def test_provider_errors_cross_the_seam_as_window_fetch_error() -> None:
    """★ §4.10. The engine may not import ``gis``, so it cannot name — let alone catch — a
    ``gis`` exception; its only alternative would be ``except Exception``, which the
    contract calls a defect. So every ProviderError is wrapped here."""
    provider = _StubProvider(raises=ProviderRateLimitError("slow down", provider="fixture"))
    source = TileWindowSource(provider, _aoi(300.0), zoom_levels=(18,), max_windows=2)
    with pytest.raises(WindowFetchError) as excinfo:
        list(source)
    assert excinfo.value.cause_type == "ProviderRateLimitError"
    assert isinstance(excinfo.value.window_key, str) and excinfo.value.window_key
    # The original is kept as __cause__ for our logs; the engine sees only a type it is
    # allowed to know about.
    assert isinstance(excinfo.value.__cause__, ProviderRateLimitError)


def test_multispectral_is_true_only_when_the_bands_are_actually_there() -> None:
    """★ A window claiming the capability while carrying no extra bands is a guaranteed
    ValueError inside the engine's water indices, which read ``extra_bands`` and refuse to
    substitute a green-band proxy. The capability describes the PROVIDER; the flag must
    describe THESE PIXELS."""
    provider = _StubProvider(supports_multispectral=True)  # Claims it; ships RGB only.
    source = TileWindowSource(provider, _aoi(300.0), zoom_levels=(18,), max_windows=1)
    window = next(iter(source))
    assert window.supports_multispectral is False
    assert window.extra_bands is None


def test_source_refuses_a_window_the_provider_cannot_serve() -> None:
    """★ Refused at construction, not once per window: every window would fail identically,
    the engine would return ``no_viable_candidate``, and a configuration error would present
    as "we looked and found nothing"."""
    provider = _StubProvider(max_static_px=(512, 512))
    with pytest.raises(AreaTooLargeError):
        TileWindowSource(provider, _aoi(), zoom_levels=(18,), window_size_px=1024)


def test_empty_zoom_levels_resolves_from_the_target_gsd() -> None:
    """The source knows the provider, so it can turn a resolution into a zoom.
    ``plan_search`` cannot, and refuses to guess."""
    source = TileWindowSource(
        _StubProvider(), _aoi(), zoom_levels=(), target_gsd_m=0.5, max_windows=4
    )
    assert source.plans
    # 0.5 m/px at 48.1 N with 256 px tiles is z18 (~0.4 m/px), rounding finer.
    assert {p.zoom for p in source.plans} == {18}


def test_matching_always_uses_plain_satellite_imagery() -> None:
    """★ NORMATIVE and not a parameter: feeding a label-burned tile to the engine would be
    a real accuracy regression, and a basemap switcher must not be able to change the
    algorithm."""
    seen: list[BasemapKind] = []

    class _KindSpy(_StubProvider):
        def get_tile(self, z, x, y, *, kind=BasemapKind.SATELLITE):
            seen.append(kind)
            return super().get_tile(z, x, y, kind=kind)

    source = TileWindowSource(_KindSpy(), _aoi(300.0), zoom_levels=(18,), max_windows=1)
    next(iter(source))
    assert seen and set(seen) == {BasemapKind.SATELLITE}


def test_repr_is_useful_and_does_not_fetch() -> None:
    provider = _StubProvider()
    source = TileWindowSource(provider, _aoi(), zoom_levels=(18,))
    text = repr(source)
    assert "fixture" in text and "windows=" in text
    assert provider.tile_calls == 0


# --------------------------------------------------------------------------- boundaries


def test_gis_candidates_imports_only_the_permitted_engine_modules() -> None:
    """★ §10.3, asserted by parsing the source rather than by trusting a reviewer.

    ``gis.candidates`` may see ``ai_engine.types`` — cheap, numpy-and-stdlib-only, and
    structurally a vocabulary — and ``ai_engine.errors``, for the one name
    (``WindowFetchError``) that §4.10 requires an implementation to raise and that must live
    on the side declaring the Protocol. Nothing else. §13.1's IU-12 row names only
    ``ai_engine.types``; §10.2's module table, §10.3's ruling and ``.importlinter``'s
    ``gis-ai-types-only`` contract all name both, and they are the later, mechanically
    enforced statement.

    Anything beyond these two would drag cv2 and torch into this package and destroy the
    exact property that permits the cross-import at all.
    """
    permitted = {"ai_engine.types", "ai_engine.errors"}
    package = Path(__file__).resolve().parent.parent / "candidates"
    found: dict[str, set[str]] = {}
    for path in sorted(package.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("ai_engine"):
                modules.add(node.module or "")
            elif isinstance(node, ast.Import):
                modules.update(
                    alias.name for alias in node.names if alias.name.startswith("ai_engine")
                )
        if modules:
            found[path.name] = modules

    assert found, "the seam vanished: gis.candidates must import ai_engine.types"
    for filename, modules in found.items():
        assert modules <= permitted, f"{filename} imports {modules - permitted} from ai_engine"


def test_the_seam_still_exists() -> None:
    """The counterpart of the rule above: nobody gets to satisfy the boundary check by
    deleting the boundary."""
    source_py = Path(__file__).resolve().parent.parent / "candidates" / "source.py"
    text = source_py.read_text(encoding="utf-8")
    assert "from ai_engine.types import" in text
    assert "WindowFetchError" in text


def test_the_shipped_defaults_deliver_the_documented_guarantee() -> None:
    """The import-time assertion in ``source.py``, restated where a reader will see it fail.
    Three documents once held three values for this one parameter, and the code shipped the
    weakest of them."""
    assert GUARANTEED_FOOTPRINT_PX == 512
    assert guaranteed_footprint_px(1024, 0.5) >= GUARANTEED_FOOTPRINT_PX
