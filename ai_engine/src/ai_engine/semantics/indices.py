"""Spectral indices — ExG, GLI, NDWI, MNDWI. **DEFERRED.**

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``).

★ `ndwi` AND `mndwi` RAISE WHEN THEIR BANDS ARE ABSENT. THEY DO NOT IMPROVISE.
They need NIR and SWIR, which they read from `CandidateWindow.extra_bands`, and which an
RGB-only window does not have. Substituting the green band produces a number in the right
range, with the right shape and dtype, that means nothing — and it would be labelled
`water_body` and used to gate features and to score a candidate.

So they raise `ValueError`, and `ClassicalSemantics` gates on
`CandidateWindow.supports_multispectral`, uses an HSV heuristic when the bands are absent,
and records ``provenance="hsv_heuristic"`` for the classes it derived that way. The
decision to fall back to a heuristic belongs to the caller who can label it, not to the
index that would hide it.

`exg` and `gli` are RGB-only by construction and have no such failure mode.
"""

from __future__ import annotations

from typing import NoReturn

import numpy as np

from ai_engine.errors import NotImplementedDeferred

__all__ = ["exg", "gli", "mndwi", "ndwi"]


def _deferred(feature: str) -> NoReturn:
    """Raise `NotImplementedDeferred` naming this module and `feature`."""
    raise NotImplementedDeferred(__name__, feature=feature)


def exg(image: np.ndarray) -> np.ndarray:
    """Excess Green index: ``2g - r - b`` over chromatic coordinates.

    Args:
        image: `(H,W,3)` uint8 RGB.

    Returns:
        `(H,W)` float32 in `[-1, 2]`. Higher means more vegetation.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    _deferred("Excess Green vegetation index")


def gli(image: np.ndarray) -> np.ndarray:
    """Green Leaf Index: ``(2g - r - b) / (2g + r + b)``.

    Args:
        image: `(H,W,3)` uint8 RGB.

    Returns:
        `(H,W)` float32 in `[-1, 1]`.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    _deferred("Green Leaf Index")


def ndwi(green: np.ndarray, nir: np.ndarray) -> np.ndarray:
    """Normalised Difference Water Index: ``(green - nir) / (green + nir)``.

    Args:
        green: `(H,W)` float32 green band.
        nir: `(H,W)` float32 near-infrared band, from `CandidateWindow.extra_bands["NIR"]`.

    Returns:
        `(H,W)` float32 in `[-1, 1]`. Higher means more water.

    Raises:
        ValueError: `nir` is absent or the wrong shape. ★ It raises rather than
            substituting a visible band — see the module docstring.
        NotImplementedDeferred: Always, in this build.
    """
    _deferred("Normalised Difference Water Index")


def mndwi(green: np.ndarray, swir: np.ndarray) -> np.ndarray:
    """Modified NDWI: ``(green - swir) / (green + swir)``.

    Better than NDWI at separating water from built-up surfaces, which matters in
    farmland, where an irrigation canal and a metal roof can otherwise look alike.

    Args:
        green: `(H,W)` float32 green band.
        swir: `(H,W)` float32 short-wave infrared band, from
            `CandidateWindow.extra_bands["SWIR16"]`.

    Returns:
        `(H,W)` float32 in `[-1, 1]`.

    Raises:
        ValueError: `swir` is absent or the wrong shape.
        NotImplementedDeferred: Always, in this build.
    """
    _deferred("Modified Normalised Difference Water Index")
