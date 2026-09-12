"""The `SemanticSegmenter` ABC — image → masks plus agricultural structure.

★ THE ABC IS REAL AND COMPLETE; every segmenter is deferred
(``docs/architecture/SCOPE.md``).

Semantics exist here to *gate* features rather than to label pictures: knowing that a
keypoint sits on a road junction rather than in the middle of a wheat field is what makes
it worth more, and knowing that a whole region is water is what makes its keypoints worth
nothing.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import ClassVar

import numpy as np

from ai_engine.types import SemanticCapabilities, SemanticMap

__all__ = ["SemanticSegmenter"]


class SemanticSegmenter(ABC):
    """Segments one image into the agricultural classes the engine reasons about.

    Attributes:
        name: The registry key, e.g. ``"classical"``.
        version: Cache-key input.
    """

    name: ClassVar[str]
    version: ClassVar[str]

    @abstractmethod
    def segment(
        self,
        image: np.ndarray,
        *,
        bands: Mapping[str, np.ndarray] | None = None,
    ) -> SemanticMap:
        """Segment `image`, using extra spectral bands when they are available.

        Args:
            image: `(H,W,3)` uint8 RGB.
            bands: Extra bands keyed by name, e.g. ``{"NIR": (H,W) float32}``, fed from
                `CandidateWindow.extra_bands`. None on an RGB-only window.

        Returns:
            A `SemanticMap` whose `provenance` records, **per class**, how each mask was
            actually produced.

        ★ `provenance` IS MANDATORY AND IT IS NOT BOOKKEEPING. On an RGB-only window the
        water classes come from an HSV heuristic rather than a real spectral index, and the
        two are not equally trustworthy. Recording ``"hsv_heuristic"`` is what lets a
        consumer tell them apart; without it, a guess and a measurement arrive in the same
        array and are weighted the same.
        """

    def capabilities(self) -> SemanticCapabilities:
        """What this segmenter can actually emit — asked, never assumed.

        `SemanticMap.regions_of` treats an absent class as contributing nothing rather
        than as an error, precisely because a segmenter that cannot emit `GREENHOUSE` is a
        capability difference and not a fault. This method is how a caller finds out which
        it is dealing with, instead of inferring it from an empty mask.

        Raises:
            NotImplementedError: The base class cannot know. Subclasses must answer.
        """
        raise NotImplementedError(
            f"{type(self).__name__} must implement capabilities(): there is no honest "
            f"default for which classes a segmenter can emit, and a guess here would be "
            f"reported to callers as fact."
        )
