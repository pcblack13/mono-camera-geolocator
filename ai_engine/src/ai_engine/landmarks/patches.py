"""`LandmarkPatchBank` — multi-scale/affine patch extraction around landmarks. **DEFERRED.**

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``).

★ THIS IS WHERE MULTIPLICITY BELONGS, AND SAYING SO IS THE POINT. `extract_at()` is
contractually 1:1 — K points in, at most K descriptors out, `landmark_ids` unique — because
everything downstream assumes it: the per-landmark fix loop, PROSAC's landmark weight, and
`S_l`'s sum over k. A backend that emits two descriptors for one bi-modal patch does not
crash anything; it quietly gives that landmark twice the sampling priority it was assigned.

But multiplicity is genuinely useful — one landmark seen under five simulated tilts is five
chances to match. So it lives *here*, in a structure designed to hold it, where "best over
tilt simulations" is an explicit reduction rather than an accident of an OpenCV return
value.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ai_engine.errors import NotImplementedDeferred
from ai_engine.types import LandmarkSet

__all__ = ["LandmarkPatchBank"]


class LandmarkPatchBank:
    """Patches around each landmark, at several scales and simulated tilts."""

    def __init__(
        self,
        image: np.ndarray,
        landmarks: LandmarkSet,
        *,
        scales: tuple[float, ...] = (1.0, 1.41, 2.0),
        tilts: tuple[float, ...] = (1.0, 1.41, 2.0),
    ) -> None:
        """Build the bank.

        Args:
            image: `(H,W,3)` uint8 RGB — the query photograph.
            landmarks: The surveyor's landmarks.
            scales: The patch scale ladder, as multiples of `Landmark.radius_px`.
            tilts: The affine tilt ladder.

        Raises:
            NotImplementedDeferred: Always, in this build.
        """
        raise NotImplementedDeferred(__name__, feature="landmark patch bank extraction")

    def patches_for(self, landmark_id: int) -> tuple[np.ndarray, ...]:
        """Every patch variant for one landmark.

        Args:
            landmark_id: The dense landmark index.

        Returns:
            The patch variants, one per (scale, tilt) combination.

        Raises:
            NotImplementedDeferred: Always, in this build.
        """
        raise NotImplementedDeferred(__name__, feature="landmark patch bank extraction")

    def best_over_variants(
        self,
        landmark_id: int,
        score_fn: Any,
    ) -> tuple[np.ndarray, float]:
        """Reduce a landmark's variants to the single best one under `score_fn`.

        ★ THE REDUCTION THAT KEEPS `extract_at` 1:1. Multiplicity is exploited here and
        collapsed here; exactly one descriptor per landmark leaves this class.

        Args:
            landmark_id: The dense landmark index.
            score_fn: Scores one patch. Higher is better.

        Returns:
            `(patch, score)` for the winning variant.

        Raises:
            NotImplementedDeferred: Always, in this build.
        """
        raise NotImplementedDeferred(__name__, feature="landmark patch bank extraction")
