"""`AffineSimulatedExtractor` — a decorator over any extractor. **DEFERRED.**

ASIFT re-extracts under a ladder of simulated affine tilts and lifts every keypoint back
into the original frame with `FeatureSet.transform()`. It exists because this product's
hardest case is a **ground-level oblique photograph matched against a nadir raster**: the
viewpoint change between them is far outside what a scale-and-rotation-invariant detector
covers, and simulating the tilt is the classical answer to it.

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``). Note that the automatic path
being deferred *at all* rests on the same observation from the other direction: a planar
homography between a ground-level oblique and a nadir view is only strictly valid for a
planar scene or a pure rotation, and the oblique violates both. See SCOPE §2.

When implemented: for each tilt `t` in `asift.tilts` and each rotation `phi` in steps of
`asift.phi_step_deg`, warp, run `base_extractor`, then `FeatureSet.transform(T_inv,
image_size=original)` back — passing the ORIGINAL frame's size, or the result will not
`validate()`. Falls back to plain `sift`, which is the same extractor without the ladder.
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from ai_engine.extractors.base import FeatureExtractor
from ai_engine.models import ComponentKind, DeferredImplementation, register
from ai_engine.types import DescriptorKind, Device, ExtractorCapabilities, FeatureSet
from ai_engine.version import EXTRACTOR_VERSION

__all__ = ["AffineSimulatedExtractor"]


@register(ComponentKind.EXTRACTOR, fallback="sift", device_preference=Device.CPU)
class AffineSimulatedExtractor(DeferredImplementation, FeatureExtractor):
    """Affine-simulated extraction wrapping a base extractor (default `sift`).

    Descriptor kind and dimension are inherited from the base extractor — the ladder
    changes which keypoints are found, never how they are described.
    """

    name: ClassVar[str] = "asift"
    descriptor_kind: ClassVar[DescriptorKind] = DescriptorKind.FLOAT
    descriptor_dim: ClassVar[int] = 128
    version: ClassVar[str] = EXTRACTOR_VERSION

    deferred_module: ClassVar[str] = __name__
    deferred_feature: ClassVar[str] = "ASIFT affine-simulated feature extraction"

    def extract(self, image: np.ndarray, mask: np.ndarray | None = None) -> FeatureSet:
        """Deferred. See the module docstring."""
        self._deferred()

    def extract_at(
        self,
        image: np.ndarray,
        points: np.ndarray,
        *,
        sizes: np.ndarray | None = None,
        angles: np.ndarray | None = None,
        landmark_ids: np.ndarray | None = None,
    ) -> FeatureSet:
        """Deferred. See the module docstring."""
        self._deferred()

    def capabilities(self) -> ExtractorCapabilities:
        """Deferred. See the module docstring."""
        self._deferred()
