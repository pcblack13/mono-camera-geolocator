"""``plan_search()`` — the search plan, computed before any I/O (CONTRACT.md §4.19).

★ FLAT ENUMERATION. The plan is the cross product of the area of interest with the
requested zoom levels, on a fixed-stride window lattice, bounded by ``max_windows``. It is
pure arithmetic: no network, no provider, no pixels, no scores. That is what makes the tile
budget enforceable BEFORE a job is accepted and progress reporting honest once it is.

★ Adaptive coarse-to-fine descent is DEFERRED (§12 C-11). It would require the matching
engine to score a window before this module decides where to descend, which inverts the
layer dependency. ``WindowSource`` is exactly the seam where it slots in later — as a
source that consumes a scoring callback — without touching a single interface here.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from gis.tiles import (
    EARTH_CIRCUMFERENCE_M,
    MAX_LATITUDE,
    ORIGIN_SHIFT_M,
    bbox_to_tile_range,
    lonlat_to_meters,
    meters_to_lonlat,
    resolution_at,
)
from gis.types import BBox, TileRange, ZoomDecision

__all__ = [
    "GUARANTEED_FOOTPRINT_PX",
    "WindowPlan",
    "guaranteed_footprint_px",
    "plan_search",
    "stride_px",
]

_log: Final = logging.getLogger(__name__)


GUARANTEED_FOOTPRINT_PX: Final[int] = 512
"""★ The contract the overlap ratio EXISTS to buy: any query footprint of this size or
smaller lies WHOLLY INSIDE at least one window::

    stride = window_size_px * (1 - overlap_ratio)
    slack  = window_size_px - stride  >=  GUARANTEED_FOOTPRINT_PX

At window=1024, overlap=0.5: stride 512, slack 512. Guaranteed.
At window=1024, overlap=0.25: stride 768, slack 256. Only a 256 px guarantee.

A 256 px tile at z18 is ~120 m across — smaller than one field — so the design reasons
from 512 and the shipped default must deliver it. Any footprint between the guarantee and
the window size can straddle every window boundary and be seen whole by none of them, and
that failure is SILENT and LOCATION-DEPENDENT: it depends on where the field falls against
the lattice, so it presents as an intermittent, irreproducible "no match" on a perfectly
correct area of interest.

★ It lives HERE rather than in ``source.py`` — where §4.19 names it — because it is a
property of the LATTICE, and the lattice is built here. ``gis.candidates.source``
re-exports it under the documented name and asserts the shipped defaults against it AT
IMPORT, via ``guaranteed_footprint_px()``, so the constant and the arithmetic cannot drift
apart the way three documents once did (one said 0.5 reasoning from 512, one said 0.25,
one said 0.25 reasoning from 256 — and the code shipped the weakest of the three).
"""


@dataclass(frozen=True, slots=True)
class WindowPlan:
    """One planned window: where to look, at what zoom, and what that cost us.

    Attributes:
        zoom: The EFFECTIVE zoom level — already clamped into what the provider serves.
            Read ``zoom_decision`` to learn what was asked for.
        tile_range: The tile rectangle covering ``bbox`` at ``zoom``. The unit of the tile
            budget, and the source of the window's anchor tile and mosaic shape.
            ★ Informational for a provider with no tile pyramid (a native-bbox provider
            still gets its imagery in one call); the budget is still the honest cost model
            because the ground area, and hence the pixel count, is the same.
        bbox: The window's geographic extent, EPSG:4326.
        ordinal: This plan's index in the returned list, ``0``-based and contiguous. ★
            Enumeration order, NOT identity: it depends on the whole plan and must never
            reach a cache key.
        zoom_decision: What resolution was requested, what was achieved, and whether the
            request was clamped. ★ ``.clamped`` is load-bearing and is routed all the way
            to ``CandidateWindow.meta["zoom_clamped"]`` and on to a ``ZOOM_CLAMPED``
            warning, ``degraded = true`` and a ``zoom_clamped`` quality flag (§11.8).
    """

    zoom: int
    tile_range: TileRange
    bbox: BBox
    ordinal: int
    zoom_decision: ZoomDecision


def stride_px(window_size_px: int, overlap_ratio: float) -> int:
    """Return the distance between adjacent window origins, in pixels.

    ``stride = window_size_px * (1 - overlap_ratio)``, rounded to a whole pixel and never
    below 1 — a zero stride is an infinite lattice, and a fractional one is a window grid
    that cannot be addressed in integers.

    Args:
        window_size_px: Window edge in pixels, ``> 0``.
        overlap_ratio: Fraction of a window shared with its neighbour, ``[0, 1)``.

    Returns:
        The stride in pixels, ``>= 1``.

    Raises:
        ValueError: If ``window_size_px <= 0`` or ``overlap_ratio`` is outside ``[0, 1)``.
    """
    if window_size_px <= 0:
        raise ValueError(f"window_size_px must be > 0, got {window_size_px}")
    if not math.isfinite(overlap_ratio) or not (0.0 <= overlap_ratio < 1.0):
        raise ValueError(f"overlap_ratio must be in [0, 1), got {overlap_ratio}")
    return max(1, int(round(window_size_px * (1.0 - overlap_ratio))))


def guaranteed_footprint_px(window_size_px: int, overlap_ratio: float) -> int:
    """Return the largest footprint this lattice guarantees to hold WHOLLY in one window.

    ``guarantee = window_size_px - stride``. Any query footprint of this size or smaller,
    anywhere inside the area of interest, lies entirely inside at least one window. A
    footprint LARGER than this can straddle every window boundary and be seen whole by
    none of them — and that failure is silent and location-dependent, because it depends
    on where the field falls against the lattice.

    ★ THIS FUNCTION EXISTS SO THE CONSTANT AND THE GUARANTEE CANNOT DRIFT APART. See
    ``gis.candidates.source.GUARANTEED_FOOTPRINT_PX``, which asserts against it at import.

    Args:
        window_size_px: Window edge in pixels, ``> 0``.
        overlap_ratio: Fraction of a window shared with its neighbour, ``[0, 1)``.

    Returns:
        The guaranteed footprint in pixels.

    Raises:
        ValueError: As ``stride_px``.
    """
    return window_size_px - stride_px(window_size_px, overlap_ratio)


_EDGE_INSET_PX: Final[float] = 1e-4
"""★ How far inside its own pixel extent a window's bbox is drawn, and why that is not a
fudge factor.

A tile-aligned window's edges land EXACTLY on tile boundaries — that is the point of
aligning them — and ``gis.tiles.bbox_to_tile_range`` resolves such an edge with
``floor(x0)`` and ``ceil(x1) - 1``, promising in its own docstring that "a box ending
exactly on a tile boundary does not pull in the next tile". Exactly is the problem: the
projection round-trip (pixels -> addressing metres -> degrees -> tile units) carries ~1e-11
tile units of double-precision noise, and ``ceil()`` amplifies a +1e-11 into a WHOLE EXTRA
TILE COLUMN. The sign of that noise depends on the longitude, so half the world's windows
cost 4x4 = 16 tiles and half cost 5x5 = 25, deterministically per location and unpredictably
across locations.

Measured, before this inset existed: a default 25-window job costs 400 tile fetches at 311
of 800 sampled locations worldwide and up to 586 at the unluckiest — so ~2% of the planet
exceeded ``LE_MAX_TILES_PER_JOB=512`` and would have been refused at the DEFAULT
configuration, with the error depending on nothing but where the field is. That is the same
silent, location-dependent, irreproducible failure that ``GUARANTEED_FOOTPRINT_PX`` exists
to prevent, arriving through a different door.

So the bbox names the pixels the window CONTAINS rather than the infinitesimal boundary it
shares with the next tile. The inset is one ten-thousandth of a pixel: ~4e-10 m at z18, four
orders of magnitude BELOW the half-pixel that could move a crop (``crop_to_bbox`` rounds to
whole pixels, so the returned imagery is bit-identical) and four orders ABOVE the round-trip
noise it defeats — a band that holds from z0 to z24. With it, every aligned window costs
exactly 16 tiles and the default job costs exactly 400, everywhere on Earth.
"""


def _world_px(z: int, tile_size_px: int) -> float:
    """Return the width of the whole world at zoom ``z``, in pixels."""
    return float(tile_size_px * (1 << z))


def _lonlat_to_global_px(lon: float, lat: float, z: int, tile_size_px: int) -> tuple[float, float]:
    """Project a position onto the global pixel grid at zoom ``z``.

    Identical to ``lonlat_to_tile_fractional(...) * tile_size_px`` — the projection is
    linear in the addressing metres and the two routes are analytically the same map. This
    route is used because its inverse is a public function and is exact.
    """
    mx, my = lonlat_to_meters(lon, lat)
    world = _world_px(z, tile_size_px)
    px = (mx + ORIGIN_SHIFT_M) / EARTH_CIRCUMFERENCE_M * world
    py = (ORIGIN_SHIFT_M - my) / EARTH_CIRCUMFERENCE_M * world
    return (px, py)


def _global_px_to_lonlat(px: float, py: float, z: int, tile_size_px: int) -> tuple[float, float]:
    """The exact inverse of ``_lonlat_to_global_px``."""
    world = _world_px(z, tile_size_px)
    mx = -ORIGIN_SHIFT_M + (px / world) * EARTH_CIRCUMFERENCE_M
    my = ORIGIN_SHIFT_M - (py / world) * EARTH_CIRCUMFERENCE_M
    return meters_to_lonlat(mx, my)


def _clamp_zoom_levels(
    zoom_levels: Sequence[int], min_zoom: int, max_zoom: int
) -> list[tuple[int, int]]:
    """Clamp each requested zoom into ``[min_zoom, max_zoom]``, dedupe, preserve order.

    Returns:
        ``(requested, effective)`` pairs. Deduped on the EFFECTIVE zoom — two requests
        that clamp to the same level are one search — keeping the first request that
        produced it, so the reported ``requested`` is the one the caller asked for first.
    """
    pairs: list[tuple[int, int]] = []
    seen: set[int] = set()
    for z_req in zoom_levels:
        z_eff = max(min_zoom, min(max_zoom, int(z_req)))
        if z_eff in seen:
            continue
        seen.add(z_eff)
        pairs.append((int(z_req), z_eff))
    return pairs


def _lattice_count(span_px: float, window_size_px: int, stride: int) -> int:
    """Return how many windows of ``window_size_px`` at ``stride`` cover ``span_px``."""
    if span_px <= window_size_px:
        return 1
    return int(math.ceil((span_px - window_size_px) / stride)) + 1


def _snap_down(px: float, tile_size_px: int) -> int:
    """Snap a global pixel coordinate down onto the tile grid."""
    return int(math.floor(px / tile_size_px)) * tile_size_px


def _windows_at_zoom(
    aoi: BBox,
    z: int,
    *,
    window_size_px: int,
    tile_size_px: int,
    stride: int,
) -> list[tuple[BBox, TileRange]]:
    """Build one zoom level's window lattice, ordered centre-out.

    The lattice is anchored on the tile grid at or before the area's north-west corner and
    extended until it covers the whole area, so it always over-covers and never under-covers.

    ★ SNAPPED TO THE TILE GRID, which is worth a third of the network traffic. A
    1024 px window costs 4x4 = 16 tiles when its origin sits ON a tile boundary and
    5x5 = 25 when it straddles one — the same pixels, 56% more requests, for nothing. The
    stride is already a whole number of tiles at the shipped defaults (512 px = 2 tiles at
    256), so snapping the ORIGIN aligns every window in the lattice, not just the first.

    ★ THIS IS NOT AN OPTIMISATION, IT IS WHAT MAKES THE SHIPPED DEFAULTS FIT. §9.7 budgets
    ``LE_MAX_TILES_PER_JOB=512`` against ``LE_SEARCH_MAX_CANDIDATES=25``: 25 x 16 = 400
    fits, 25 x 25 = 625 does not, so an unaligned lattice would make **every job at the
    default configuration exceed its own default budget** and 422. §9.7's own cost model
    says the same thing from the other end — it puts a 1 km/z18 search at "~1370", which is
    342 disc tiles x 4, and that 4x is exactly the redundancy of a tile-aligned lattice at a
    2-tile stride. At 25 tiles per window the figure would be ~2140. The contract's
    arithmetic only closes on an aligned grid.

    The anchor is snapped from the area's NORTH-WEST CORNER rather than from a lattice
    centred on the area, because snapping a centred lattice outward can push the far edge
    over a stride boundary and buy a whole extra ring of windows — 4 instead of 1 on an area
    smaller than a single window, which is the common case for a tightly hinted search. The
    guarantee below needs only that the lattice starts at or before the area and covers it;
    it never depended on the origin being centred. Nor does the centre-out ordering, which is
    measured from the area's centre and does not care where the lattice begins.

    ★ ORDERED BY DISTANCE FROM THE CENTRE, and that ordering is load-bearing twice over.
    ``max_windows`` truncates this list — at a 1 km radius and z18 the lattice is ~81
    windows against a budget of 25, so truncation is the normal case, not the edge case —
    and the centre is where every hint says the photograph was taken (§4.19's precedence
    resolves to a disc around a point four times out of five). Truncating centre-out drops
    the least probable windows; truncating row-major would drop the southern two thirds of
    the area for no reason at all. It also means a lazy consumer fetches the most probable
    window first.

    The ordering consults no imagery and no score — it is pure geometry, computed before
    any I/O — so this remains a flat enumeration, not the deferred adaptive descent.

    Returns:
        ``(bbox, tile_range)`` per window, centre-out, ties broken north-west first.
    """
    world = _world_px(z, tile_size_px)
    x_west, y_north = _lonlat_to_global_px(aoi.west, aoi.north, z, tile_size_px)
    x_east, y_south = _lonlat_to_global_px(aoi.east, aoi.south, z, tile_size_px)

    centre_x = (x_west + x_east) / 2.0
    centre_y = (y_north + y_south) / 2.0

    # Anchor on the tile grid at or before the area's north-west corner, then solve the
    # counts from the anchor, so the lattice provably reaches the south-east corner.
    left0 = _snap_down(x_west, tile_size_px)
    top0 = _snap_down(y_north, tile_size_px)
    n_cols = _lattice_count(x_east - left0, window_size_px, stride)
    n_rows = _lattice_count(y_south - top0, window_size_px, stride)

    ranked: list[tuple[float, int, int, BBox, TileRange]] = []
    for row in range(n_rows):
        for col in range(n_cols):
            # ★ Clamped to the world's own pixel extent. Without this a window near the
            #   antimeridian projects to |lon| > 180 and BBox — correctly — refuses to
            #   exist. A window at the edge of the world is simply smaller; there is no
            #   imagery out there to lose.
            left = max(0.0, min(world, float(left0 + col * stride)))
            right = max(0.0, min(world, float(left0 + col * stride + window_size_px)))
            top = max(0.0, min(world, float(top0 + row * stride)))
            bottom = max(0.0, min(world, float(top0 + row * stride + window_size_px)))
            if right - left < 1.0 or bottom - top < 1.0:
                continue  # Entirely off the edge of the Mercator world.

            # ★ Drawn a ten-thousandth of a pixel inside the window's own extent, so that
            #   an edge sitting exactly on a tile boundary lands on a decidable side of it.
            #   See _EDGE_INSET_PX: without it, 2% of the planet costs 46% more tiles than
            #   the budget allows, for arithmetic reasons alone.
            west, north = _global_px_to_lonlat(
                left + _EDGE_INSET_PX, top + _EDGE_INSET_PX, z, tile_size_px
            )
            east, south = _global_px_to_lonlat(
                right - _EDGE_INSET_PX, bottom - _EDGE_INSET_PX, z, tile_size_px
            )
            bbox = BBox(west=west, south=south, east=east, north=north)
            rng = bbox_to_tile_range(bbox, z)

            dx = (left + right) / 2.0 - centre_x
            dy = (top + bottom) / 2.0 - centre_y
            ranked.append((math.hypot(dx, dy), row, col, bbox, rng))

    ranked.sort(key=lambda item: (item[0], item[1], item[2]))
    return [(bbox, rng) for _, _, _, bbox, rng in ranked]


def plan_search(
    aoi: BBox,
    *,
    zoom_levels: Sequence[int],
    min_zoom: int,
    max_zoom: int,
    window_size_px: int,
    tile_size_px: int,
    overlap_ratio: float,
    max_windows: int,
) -> list[WindowPlan]:
    """Enumerate the windows to search. Deterministic, and fully known before any I/O.

    ★ ZOOM CLAMPING — normative. ``z_eff = clamp(z, min_zoom, max_zoom)`` for each
    requested ``z``; dedupe; preserve order. Each plan carries
    ``ZoomDecision(clamped = z_eff != z)``. This function NEVER returns an empty list for
    a non-empty ``zoom_levels`` and NEVER raises on an out-of-range zoom: clamping is the
    provider's honest best effort, and the CALLER IS TOLD.

    Why that matters: ``LE_SENTINEL_MAX_ZOOM=15`` and the provider correctly refuses
    z > 15 (Sentinel-2 is 10 m/px), while ``LE_SEARCH_DEFAULT_ZOOM``, ``SearchHint``,
    ``projects.default_search_zoom`` and ``match_jobs.search_zoom_levels`` all say 18. The
    two survivable answers are "zero windows" — every job dying as ``no_viable_candidate``,
    indistinguishable from a genuine no-match — and a silent clamp to 10 m imagery under a
    job row still claiming z18. Both are unacceptable, so neither happens: the request is
    clamped and ``clamped`` is routed to a warning, ``degraded = true`` and a quality flag.

    ★ TRUNCATION. ``max_windows`` bounds the result. At realistic areas the lattice is
    several times the budget, so truncation is normal; it is logged at WARNING with the
    counts, because a plan that silently covers a third of the area the operator drew is a
    coverage claim we did not earn. Windows are ordered centre-out, so what is dropped is
    the least probable, and the caller can see the full cost via
    ``gis.candidates.budget.estimate_budget``.

    Args:
        aoi: The search area, EPSG:4326. ★ MUST NOT cross the antimeridian — split it with
            ``gis.geometry.split_antimeridian`` and plan each half.
        zoom_levels: The requested zoom levels. Must be non-empty.
        min_zoom: The provider's minimum servable zoom.
        max_zoom: The provider's maximum servable zoom.
        window_size_px: Window edge in pixels.
        tile_size_px: The provider's tile edge in pixels. ★ Read it from
            ``capabilities().tile_size_px``; a hardcoded 256 against a 512 provider is a
            silent 2x error in every window's ground extent.
        overlap_ratio: Fraction of a window shared with its neighbour. ★ 0.5 buys the
            512 px footprint guarantee (§4.19).
        max_windows: Upper bound on the returned list, ``>= 1``.

    Returns:
        The plans, ``ordinal``-ordered and contiguous. Never empty. Windows from multiple
        zoom levels are INTERLEAVED round-robin, so a truncated multi-zoom plan still
        searches every zoom the caller asked for. Zoom-major order would let ``max_windows``
        silently delete the second zoom entirely — a multi-zoom search that quietly became
        a single-zoom one, which is the class of failure this whole module is written
        against.

    Raises:
        ValueError: If ``zoom_levels`` is empty, ``max_windows < 1``, ``min_zoom >
            max_zoom``, ``tile_size_px <= 0``, ``aoi`` crosses the antimeridian, ``aoi``
            lies wholly outside the Web Mercator world, or ``window_size_px`` /
            ``overlap_ratio`` are invalid. ★ An empty ``zoom_levels`` and a ``max_windows``
            of 0 are REFUSED, not honoured: both would return an empty plan, and an empty
            plan reads downstream as "we looked and found nothing".
    """
    if not zoom_levels:
        raise ValueError("zoom_levels must not be empty; a search at no zoom is not a search")
    if max_windows < 1:
        raise ValueError(f"max_windows must be >= 1, got {max_windows}")
    if min_zoom > max_zoom:
        raise ValueError(f"min_zoom={min_zoom} > max_zoom={max_zoom}")
    if tile_size_px <= 0:
        raise ValueError(f"tile_size_px must be > 0, got {tile_size_px}")
    if aoi.crosses_antimeridian:
        raise ValueError(
            "aoi crosses the antimeridian (west > east); split it with "
            "gis.geometry.split_antimeridian() and plan each half"
        )
    stride = stride_px(window_size_px, overlap_ratio)  # Validates the two of them.

    _, centre_lat = aoi.center()
    if aoi.south > MAX_LATITUDE or aoi.north < -MAX_LATITUDE:
        raise ValueError(
            f"aoi {aoi} lies outside the Web Mercator world (|lat| <= {MAX_LATITUDE}); "
            "no tiled imagery exists there"
        )

    guarantee = guaranteed_footprint_px(window_size_px, overlap_ratio)
    if guarantee < GUARANTEED_FOOTPRINT_PX:
        _log.warning(
            "window_size_px=%d at overlap_ratio=%.3f guarantees only a %d px footprint "
            "(stride %d): a query footprint larger than that can straddle every window "
            "boundary and be seen whole by none of them, intermittently and depending "
            "only on where the field falls against the lattice. The design reasons from "
            "%d px — LE_SEARCH_OVERLAP_RATIO=0.5 at LE_SEARCH_WINDOW_SIZE_PX=1024 "
            "delivers it.",
            window_size_px,
            overlap_ratio,
            guarantee,
            stride,
            GUARANTEED_FOOTPRINT_PX,
        )

    per_zoom: list[list[WindowPlan]] = []
    for z_req, z_eff in _clamp_zoom_levels(zoom_levels, min_zoom, max_zoom):
        decision = ZoomDecision(
            zoom=z_eff,
            achieved_mpp=resolution_at(z_eff, centre_lat, tile_size_px),
            requested_mpp=resolution_at(z_req, centre_lat, tile_size_px),
            clamped=z_eff != z_req,
        )
        if decision.clamped:
            _log.warning(
                "zoom %d clamped to %d (provider serves [%d, %d]): searching %.3f m/px "
                "imagery where %.3f m/px was requested",
                z_req,
                z_eff,
                min_zoom,
                max_zoom,
                decision.achieved_mpp,
                decision.requested_mpp,
            )
        windows = _windows_at_zoom(
            aoi,
            z_eff,
            window_size_px=window_size_px,
            tile_size_px=tile_size_px,
            stride=stride,
        )
        per_zoom.append(
            [
                WindowPlan(
                    zoom=z_eff,
                    tile_range=rng,
                    bbox=bbox,
                    ordinal=-1,  # Assigned once the interleave and the bound are settled.
                    zoom_decision=decision,
                )
                for bbox, rng in windows
            ]
        )

    planned = sum(len(w) for w in per_zoom)
    ordered: list[WindowPlan] = []
    for rank in range(max(len(w) for w in per_zoom)):
        for windows in per_zoom:
            if rank < len(windows):
                ordered.append(windows[rank])

    if not ordered:
        # Unreachable: every zoom yields >= 1 window for an aoi inside the world, which
        # the checks above guarantee. Refuse loudly rather than return the empty list the
        # docstring promises never to return.
        raise ValueError(f"planning produced no windows for {aoi} at {tuple(zoom_levels)!r}")

    if len(ordered) > max_windows:
        _log.warning(
            "search plan truncated to %d of %d windows (%d zoom level(s), aoi %.3f km2): "
            "the plan covers the most probable windows first, but it does NOT cover the "
            "whole area of interest. Raise LE_SEARCH_MAX_CANDIDATES or draw a smaller area.",
            max_windows,
            planned,
            len(per_zoom),
            aoi.area_m2() / 1e6,
        )
        ordered = ordered[:max_windows]

    return [
        WindowPlan(
            zoom=plan.zoom,
            tile_range=plan.tile_range,
            bbox=plan.bbox,
            ordinal=i,
            zoom_decision=plan.zoom_decision,
        )
        for i, plan in enumerate(ordered)
    ]
