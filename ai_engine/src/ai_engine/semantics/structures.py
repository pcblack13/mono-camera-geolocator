"""Built-structure detection — greenhouses, buildings, water bodies. **DEFERRED.**

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``).

★ WHY THIS MODULE EXISTS AS ITS OWN FILE. The client brief mandates a specific class list,
and every class in it needs a **named producer** rather than being implicit inside
`classical.py`. A class with no named producer is a class that silently never appears: the
enum has the member, the database has the column, the UI has the legend entry, and nothing
ever emits it — and nothing fails, because an absent mask and an empty mask are the same
array.

Detection combines rectangularity, fill ratio and shadow azimuth. The shadow term is what
separates a greenhouse from a bright field: a greenhouse casts a shadow with a consistent
azimuth across the whole structure, and a pale patch of soil does not.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import NoReturn

import numpy as np

from ai_engine.errors import NotImplementedDeferred

__all__ = ["detect_buildings", "detect_greenhouses", "detect_water_bodies"]


def _deferred(feature: str) -> NoReturn:
    """Raise `NotImplementedDeferred` naming this module and `feature`."""
    raise NotImplementedDeferred(__name__, feature=feature)


def detect_greenhouses(
    image: np.ndarray,
    *,
    sun_azimuth_deg: float | None = None,
) -> np.ndarray:
    """Detect greenhouse structures.

    Args:
        image: `(H,W,3)` uint8 RGB.
        sun_azimuth_deg: The illumination azimuth when known, for the shadow test. None
            estimates it from the image's own shadow statistics.

    Returns:
        `(H,W)` bool mask for `SemanticClass.GREENHOUSE`.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    _deferred("greenhouse detection")


def detect_buildings(
    image: np.ndarray,
    *,
    sun_azimuth_deg: float | None = None,
) -> np.ndarray:
    """Detect buildings by rectangularity, fill and shadow azimuth.

    Args:
        image: `(H,W,3)` uint8 RGB.
        sun_azimuth_deg: The illumination azimuth when known.

    Returns:
        `(H,W)` bool mask for `SemanticClass.BUILDING`.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    _deferred("building detection")


def detect_water_bodies(
    image: np.ndarray,
    *,
    bands: Mapping[str, np.ndarray] | None = None,
) -> tuple[np.ndarray, str]:
    """Detect open water.

    Args:
        image: `(H,W,3)` uint8 RGB.
        bands: Extra spectral bands from `CandidateWindow.extra_bands`. None means RGB
            only, which forces the HSV heuristic.

    Returns:
        `(mask (H,W) bool, provenance)` where provenance is ``"ndwi"``, ``"mndwi"`` or
        ``"hsv_heuristic"``. ★ The provenance is returned rather than logged because the
        caller must record it per class in `SemanticMap.provenance` — a heuristic guess and
        a spectral measurement must not arrive indistinguishable.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    _deferred("water body detection")
