"""The coverage rule (upstream §8): raise the reach only when it does not contain the view.

A coverage rule, not a distance. Drone flights see past 1100 m at their frame corners,
so "always use the farthest ray" would enlarge every drone footprint and move
published numbers; a mast whose 1100 m circle holds 3% of what it sees would
otherwise fetch a mosaic centred on the wrong ground and lock nothing.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.accuracy_service import (
    REACH_CAP_M,
    REACH_MIN_COVERAGE,
    coverage_at,
    resolve_reach,
    view_ranges,
)


def _view(inside: int, outside: int, far: float = 2500.0) -> np.ndarray:
    return np.array([300.0] * inside + [far] * outside)


class TestTheRule:
    def test_a_view_the_reach_already_contains_is_left_alone(self) -> None:
        """94% inside — a drone at its frame corners — keeps its 1100 m exactly."""
        got = resolve_reach(_view(94, 6), 1100.0)
        assert got["raised"] is False
        assert got["used_m"] == 1100.0
        assert got["coverage_requested"] == pytest.approx(0.94)

    def test_the_threshold_is_eighty_five_per_cent(self) -> None:
        assert REACH_MIN_COVERAGE == 0.85
        assert resolve_reach(_view(85, 15), 1100.0)["raised"] is False
        assert resolve_reach(_view(84, 16), 1100.0)["raised"] is True

    def test_a_view_mostly_beyond_the_reach_gets_the_scenes_far_edge(self) -> None:
        """3% inside: the reach becomes the far ground, rounded up to 100 m."""
        ranges = np.array([300.0] * 3 + [2200.0 + 15.0 * i for i in range(97)])
        got = resolve_reach(ranges, 1100.0)
        assert got["raised"] is True
        assert got["used_m"] % 100 == 0
        assert got["used_m"] >= np.percentile(ranges, 98)
        assert got["coverage_used"] >= 0.98

    def test_a_sliver_of_horizon_does_not_fetch_a_horizon_sized_mosaic(self) -> None:
        """One pixel at 4.9 km among ground at ~2 km: the 98th percentile ignores it."""
        ranges = np.array([2000.0] * 199 + [4900.0])
        got = resolve_reach(ranges, 1100.0)
        assert got["used_m"] == 2000.0

    def test_the_reach_is_never_raised_past_the_cap(self) -> None:
        got = resolve_reach(np.array([9000.0] * 50), 1100.0)
        assert got["used_m"] == REACH_CAP_M
        assert got["coverage_used"] == 0.0     # honestly: still nothing inside

    def test_no_visible_ground_changes_nothing(self) -> None:
        got = resolve_reach(np.array([]), 1100.0)
        assert got["raised"] is False and got["visible_samples"] == 0
        assert coverage_at(np.array([]), 1100.0) == 0.0

    def test_a_reach_already_past_the_far_edge_is_not_lowered(self) -> None:
        """The rule raises; it never shrinks what the surveyor asked for."""
        got = resolve_reach(_view(10, 90, far=1500.0), 3000.0)
        assert got["raised"] is False and got["used_m"] == 3000.0


# ── on the synthetic scene ────────────────────────────────────────────────────

from app.tests.test_accuracy_service import scene  # noqa: E402, F401
from app.tests.test_photo_zones import _scene_for  # noqa: E402


@pytest.mark.slow
def test_the_synthetic_scene_is_inside_the_default_reach_and_not_inside_half_of_it(
    scene: dict,  # noqa: F811
) -> None:
    """The fixture's ground reaches ~1070 m: 1100 m contains it, 500 m does not.

    ★ This is the drone case and the mast case on one scene. At 1100 m the rule
    must leave the request alone — that is what keeps the phase-1 equivalence
    (589/589 identical tiles) true under the default. At 500 m it must raise the
    reach to the scene's far edge, which is the 1100 m the default already was.
    """
    from app.vendor.geo_accuracy.geo_io import DEM

    dem = DEM(str(scene["dem_path"]))
    try:
        ranges = view_ranges(_scene_for(scene, dem))
    finally:
        dem.ds.close()
    assert ranges.size > 100
    assert coverage_at(ranges, 1100.0) >= REACH_MIN_COVERAGE
    assert resolve_reach(ranges, 1100.0)["raised"] is False
    half = resolve_reach(ranges, 500.0)
    assert half["raised"] is True
    assert half["used_m"] == 1100.0
