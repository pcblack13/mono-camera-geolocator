"""Shared image preprocessing for the extractors. **DEFERRED.**

CLAHE, grayscale conversion, resizing and gamma — the operations every extractor applies
before it detects anything. CLAHE in particular is a large win on hazy field photographs,
which is why `clahe_enabled` defaults to True.

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``), and deliberately so even though
none of it is "matching". Every caller of this module is a deferred extractor, so a real
implementation here would be code that nothing can reach, that no test can exercise, and
whose only effect would be to make the deferred surface look partly alive. The scope
ruling's line is drawn at the automatic path as a whole, not at the algorithms inside it.

When implemented: `cv2.createCLAHE(clipLimit=..., tileGridSize=(8,8))` on the L channel of
LAB, `cv2.cvtColor` for grayscale, `cv2.resize` with INTER_AREA for downscale and
INTER_LINEAR for upscale, and a lookup-table gamma. All of it call-time-binds `cv2`.
"""

from __future__ import annotations

from typing import NoReturn

import numpy as np

from ai_engine.errors import NotImplementedDeferred

__all__ = ["apply_clahe", "gamma_correct", "to_grayscale", "resize_max_side"]


def _deferred(feature: str) -> NoReturn:
    """Raise `NotImplementedDeferred` naming this module and `feature`."""
    raise NotImplementedDeferred(__name__, feature=feature)


def to_grayscale(image: np.ndarray) -> np.ndarray:
    """Convert `(H,W,3)` uint8 RGB to `(H,W)` uint8 gray. Passes `(H,W)` through.

    Args:
        image: `(H,W,3)` uint8 RGB or `(H,W)` uint8 gray.

    Returns:
        `(H,W)` uint8.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    _deferred("grayscale conversion")


def apply_clahe(
    image: np.ndarray,
    *,
    clip_limit: float = 2.0,
    tile_grid: tuple[int, int] = (8, 8),
) -> np.ndarray:
    """Contrast-limited adaptive histogram equalisation.

    Args:
        image: `(H,W,3)` uint8 RGB or `(H,W)` uint8 gray.
        clip_limit: Contrast clipping threshold.
        tile_grid: `(rows, cols)` of the equalisation tiling.

    Returns:
        An image of the same shape and dtype as `image`.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    _deferred("CLAHE contrast equalisation")


def resize_max_side(image: np.ndarray, max_side_px: int) -> tuple[np.ndarray, float]:
    """Downscale so that the longest side is at most `max_side_px`.

    Args:
        image: `(H,W,3)` uint8 RGB or `(H,W)` uint8 gray.
        max_side_px: The cap on the longest side. Images already within it are returned
            unchanged with `scale == 1.0`.

    Returns:
        `(resized, scale)`, where `scale` is the factor applied. ★ The caller MUST divide
        keypoints by `scale` to lift them back into the original frame — a resize whose
        scale is dropped is a silent, uniform pixel error that no test of the resize
        itself can see.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    _deferred("image resizing")


def gamma_correct(image: np.ndarray, gamma: float) -> np.ndarray:
    """Apply a gamma curve via a 256-entry lookup table.

    Args:
        image: uint8 image of any shape.
        gamma: The exponent. `> 1` darkens; `< 1` brightens.

    Returns:
        An image of the same shape and dtype.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    _deferred("gamma correction")
