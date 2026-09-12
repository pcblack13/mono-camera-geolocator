"""Tile budgeting — the ``AreaTooLargeError`` guard (CONTRACT.md §4.19, §9.7).

★ THE BUDGET IS CHECKED BEFORE A JOB IS ACCEPTED, NOT WHILE IT RUNS. ``plan_search`` is
pure arithmetic, so the exact cost of a search is knowable with no network, no provider and
no pixels. A job that cannot afford itself is refused at submission — a 422 the operator can
act on — rather than discovered thirty seconds in, having already spent someone's quota.

★ WHAT IS COUNTED, AND WHY IT IS THE GROSS COUNT. The budget counts TILE FETCHES —
``sum(len(plan.tile_range))`` — not distinct tiles. Overlapping windows re-request the same
tiles, and at overlap 0.5 each tile falls inside ~4 windows, so the two numbers differ by
almost 4x. ``LE_MAX_TILES_PER_JOB`` was re-costed against the gross number and raised to 512
for exactly this reason (§9.7, §14 F-80): the published 1 km/z18 figure of ~342 was a disc
count with NO overlap factor at all, while the real cost at overlap 0.5 is ~1370 — the
row labelled "at budget" was already three times over it. Only a warm cache collapses the
gross count toward the distinct one, and a budget that assumes a cache hit is not a budget.

The default budget and the default window bound are two views of one number, and they must
be read together: 25 windows of 1024 px against 256 px tiles is 25 x ~20 = ~500 tile
fetches. ``LE_SEARCH_MAX_CANDIDATES=25`` and ``LE_MAX_TILES_PER_JOB=512`` are consistent by
construction. Change one and check the other.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from gis.candidates.strategy import WindowPlan
from gis.errors import AreaTooLargeError
from gis.types import BBox, TileRef

__all__ = [
    "DEFAULT_MAX_BBOX_AREA_KM2",
    "DEFAULT_MAX_TILE_FETCHES",
    "TileBudget",
    "check_aoi_area",
    "check_tile_budget",
    "estimate_budget",
]

_log: Final = logging.getLogger(__name__)

DEFAULT_MAX_TILE_FETCHES: Final[int] = 512
"""``LE_MAX_TILES_PER_JOB``. The backend passes its own ``Settings`` value; this is the
working default that makes ``GisConfig()`` on an empty environment a real configuration
(L10)."""

DEFAULT_MAX_BBOX_AREA_KM2: Final[float] = 2500.0
"""``LE_SEARCH_MAX_BBOX_AREA_KM2``. 2500 km2 is a 50 km square — beyond any plausible
"where was this photograph taken", and well past the point where the answer would be
ambiguous even if we could afford to look."""


@dataclass(frozen=True, slots=True)
class TileBudget:
    """What a search plan will cost, computed before any I/O.

    Attributes:
        window_count: Windows in the plan.
        tile_fetches: ``sum(len(plan.tile_range))`` — every tile every window needs, with
            re-requests counted. ★ THIS is what the budget gates on: it is the number of
            ``get_tile`` calls a cold cache actually makes.
        distinct_tiles: The size of the union of every window's tiles — the warm-cache
            cost. Reported, never gated on: a budget that assumes a cache hit is not a
            budget.
        max_tile_fetches: The limit ``tile_fetches`` was measured against.
    """

    window_count: int
    tile_fetches: int
    distinct_tiles: int
    max_tile_fetches: int

    @property
    def over_budget(self) -> bool:
        """True iff this plan exceeds its tile budget."""
        return self.tile_fetches > self.max_tile_fetches

    @property
    def redundancy(self) -> float:
        """``tile_fetches / distinct_tiles`` — what the window overlap costs, and what a
        warm tile cache is worth. ~4.0 at overlap 0.5. Returns 0.0 for an empty plan."""
        if self.distinct_tiles == 0:
            return 0.0
        return self.tile_fetches / self.distinct_tiles


def estimate_budget(
    plans: Sequence[WindowPlan],
    *,
    max_tile_fetches: int = DEFAULT_MAX_TILE_FETCHES,
) -> TileBudget:
    """Cost a search plan. Pure arithmetic — no provider, no network, no pixels.

    Args:
        plans: The plans from ``gis.candidates.strategy.plan_search``.
        max_tile_fetches: The budget to measure against. ``LE_MAX_TILES_PER_JOB``.

    Returns:
        The ``TileBudget``. ★ Never raises on an over-budget plan — reporting a cost and
        refusing a job are two different jobs. ``check_tile_budget`` does the refusing.

    Raises:
        ValueError: If ``max_tile_fetches < 1``.
    """
    if max_tile_fetches < 1:
        raise ValueError(f"max_tile_fetches must be >= 1, got {max_tile_fetches}")

    fetches = 0
    distinct: set[TileRef] = set()
    for plan in plans:
        fetches += len(plan.tile_range)
        distinct.update(plan.tile_range)
    return TileBudget(
        window_count=len(plans),
        tile_fetches=fetches,
        distinct_tiles=len(distinct),
        max_tile_fetches=max_tile_fetches,
    )


def check_tile_budget(
    plans: Sequence[WindowPlan],
    *,
    max_tile_fetches: int = DEFAULT_MAX_TILE_FETCHES,
    provider: str = "",
) -> TileBudget:
    """Refuse a plan that cannot afford itself. ★ Call this BEFORE accepting a job.

    Args:
        plans: The plans from ``gis.candidates.strategy.plan_search``.
        max_tile_fetches: The budget. ``LE_MAX_TILES_PER_JOB``.
        provider: Provider name, for the error's ``provider`` attribute.

    Returns:
        The ``TileBudget``, when the plan fits.

    Raises:
        AreaTooLargeError: The plan exceeds ``max_tile_fetches``. The message names the
            three levers that actually work — a smaller area, fewer zoom levels, a lower
            ``LE_SEARCH_MAX_CANDIDATES`` — because "too large" without a remedy is just a
            wall.
        ValueError: If ``max_tile_fetches < 1``.
    """
    budget = estimate_budget(plans, max_tile_fetches=max_tile_fetches)
    if budget.over_budget:
        zooms = sorted({plan.zoom for plan in plans})
        raise AreaTooLargeError(
            f"the search plan needs {budget.tile_fetches} tile fetches "
            f"({budget.distinct_tiles} distinct, {budget.redundancy:.1f}x window overlap) "
            f"across {budget.window_count} window(s) at zoom {zooms}, over the "
            f"{max_tile_fetches}-tile job budget. Search a smaller area, drop a zoom "
            f"level, or lower LE_SEARCH_MAX_CANDIDATES.",
            provider=provider,
        )
    _log.debug(
        "search plan fits: %d window(s), %d tile fetches (%d distinct, %.1fx overlap) "
        "against a %d budget",
        budget.window_count,
        budget.tile_fetches,
        budget.distinct_tiles,
        budget.redundancy,
        max_tile_fetches,
    )
    return budget


def check_aoi_area(
    aoi: BBox,
    *,
    max_area_km2: float = DEFAULT_MAX_BBOX_AREA_KM2,
    provider: str = "",
) -> float:
    """Refuse an area of interest that is too large to be a hint at all.

    ★ THE CHEAPEST GUARD IN THE SYSTEM, and it runs first. It is O(1) — one closed-form
    spherical area — so it can be applied to a request before any planning happens at all.
    It is a coarse sanity bound on the HINT, not a substitute for ``check_tile_budget``:
    the tile cost depends on the zoom levels, which this cannot see.

    Args:
        aoi: The search area, EPSG:4326.
        max_area_km2: The limit. ``LE_SEARCH_MAX_BBOX_AREA_KM2``.
        provider: Provider name, for the error's ``provider`` attribute.

    Returns:
        The area in km2, when it fits.

    Raises:
        AreaTooLargeError: The area exceeds ``max_area_km2``.
        ValueError: If ``max_area_km2 <= 0``.
    """
    if not (max_area_km2 > 0.0):
        raise ValueError(f"max_area_km2 must be > 0, got {max_area_km2}")
    area_km2 = aoi.area_m2() / 1e6
    if area_km2 > max_area_km2:
        raise AreaTooLargeError(
            f"the search area is {area_km2:.1f} km2, over the {max_area_km2:.0f} km2 "
            f"limit. A search area is a hint about where one photograph was taken; at "
            f"this size the question has no single answer.",
            provider=provider,
        )
    return area_km2
