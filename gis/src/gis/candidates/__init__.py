"""``gis.candidates`` — an area of interest becomes windows of imagery (CONTRACT.md §4.19).

Three pure modules and one seam:

* ``hint`` — where a search area comes from, and the honest refusal when there isn't one.
* ``strategy`` — the window lattice. Pure arithmetic, no I/O, fully known up front.
* ``budget`` — what a plan costs, and the guard that refuses one before a job is accepted.
* ``source`` — ★ THE SEAM. ``TileWindowSource`` structurally satisfies
  ``ai_engine.types.WindowSource``. The only place ``gis`` imports ``ai_engine``.
"""

from __future__ import annotations

from gis.candidates.budget import (
    DEFAULT_MAX_BBOX_AREA_KM2,
    DEFAULT_MAX_TILE_FETCHES,
    TileBudget,
    check_aoi_area,
    check_tile_budget,
    estimate_budget,
)
from gis.candidates.hint import SearchHint, resolve_hint
from gis.candidates.source import GUARANTEED_FOOTPRINT_PX, TileWindowSource
from gis.candidates.strategy import (
    WindowPlan,
    guaranteed_footprint_px,
    plan_search,
    stride_px,
)

__all__ = [
    "DEFAULT_MAX_BBOX_AREA_KM2",
    "DEFAULT_MAX_TILE_FETCHES",
    "GUARANTEED_FOOTPRINT_PX",
    "SearchHint",
    "TileBudget",
    "TileWindowSource",
    "WindowPlan",
    "check_aoi_area",
    "check_tile_budget",
    "estimate_budget",
    "guaranteed_footprint_px",
    "plan_search",
    "resolve_hint",
    "stride_px",
]
