"""``landmark_sampling_prior()`` — a spatial density map for MATCHING. **DEFERRED.**

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``).

★ NOT A SUGGESTER. This returns a density field that biases where matching spends its
effort — it does not propose landmarks to a human. `landmarks/suggest.py` does that, and
the two were conflated once already: the entire suggestion vertical (endpoints, job type,
table, service, task, schema) shipped against this module, which cannot produce a ranked
proposal and never could. Different output, different consumer, different file.

The prior is built from `LandmarkWeightField`, whose bounds are pinned by test: with K=12
landmarks at `w_k=4` all inside `R_L`, `max(g) <= 1.0` and the priority ratio is bounded by
12. An unbounded prior would let a cluster of landmarks monopolise PROSAC's sampling
budget.
"""

from __future__ import annotations

import numpy as np

from ai_engine.errors import NotImplementedDeferred
from ai_engine.types import LandmarkSet, LandmarkWeightField

__all__ = ["landmark_sampling_prior", "weight_field_from_landmarks"]


def weight_field_from_landmarks(
    landmarks: LandmarkSet,
    *,
    radius_px: float = 96.0,
) -> LandmarkWeightField:
    """Build the weight field a `LandmarkSet` implies.

    Args:
        landmarks: The surveyor's landmarks.
        radius_px: `R_L`, the influence radius.

    Returns:
        A `LandmarkWeightField` ready to `evaluate()` at arbitrary points.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    raise NotImplementedDeferred(__name__, feature="landmark weight field construction")


def landmark_sampling_prior(
    landmarks: LandmarkSet,
    image_size: tuple[int, int],
    *,
    radius_px: float = 96.0,
) -> np.ndarray:
    """Rasterise the landmark-derived sampling prior over the image.

    Args:
        landmarks: The surveyor's landmarks.
        image_size: `(width, height)` of the query image.
        radius_px: `R_L`, the influence radius.

    Returns:
        `(H,W)` float32 density. Bounded — see the module docstring.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    raise NotImplementedDeferred(__name__, feature="landmark sampling prior")
