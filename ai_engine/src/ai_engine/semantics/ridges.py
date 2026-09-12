"""Multi-scale ridge detection — roads, tracks and irrigation canals. **DEFERRED.**

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``).

Hessian vesselness across a scale ladder, because a road two pixels wide and a canal
twenty pixels wide are the same kind of structure at different scales, and a single-scale
filter finds one and misses the other.

★ THE JUNCTIONS ARE THE POINT. A road crossing a canal is the highest-value landmark
farmland offers: unambiguous, locally unique, stable for decades, and identifiable from
both a ground-level photograph and a nadir raster. `RidgeSet.junctions` is what
`ClassicalSuggester`'s `semantic` strategy ranks, and it is why ridges are detected here
rather than left to a generic corner detector — a corner detector finds the same junction
as four unremarkable corners.
"""

from __future__ import annotations

import numpy as np

from ai_engine.errors import NotImplementedDeferred
from ai_engine.types import RidgeSet

__all__ = ["DEFAULT_SCALES_PX", "detect_ridges"]

#: The default scale ladder in pixels — a farm track through to a major canal.
DEFAULT_SCALES_PX: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0, 16.0)


def detect_ridges(
    image: np.ndarray,
    *,
    scales_px: tuple[float, ...] = DEFAULT_SCALES_PX,
    mask: np.ndarray | None = None,
) -> RidgeSet:
    """Detect linear ridge structures and their intersections.

    Args:
        image: `(H,W,3)` uint8 RGB or `(H,W)` uint8 gray.
        scales_px: The scale ladder to evaluate. The response is the max over scales, and
            `RidgeSet.scale_map` records which scale won where.
        mask: `(H,W)` uint8; nonzero marks the region to analyse.

    Returns:
        A `RidgeSet` with `response`, `segments` and — the useful part — `junctions`.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    raise NotImplementedDeferred(
        __name__, feature="multi-scale ridge detection (roads, tracks, canals)"
    )
