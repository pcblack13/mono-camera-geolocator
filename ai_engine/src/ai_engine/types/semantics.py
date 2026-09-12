"""Semantic structure — what the pixels appear to BE, as opposed to how they correlate.

Semantics are a gate and a tiebreak, never a primary signal: they narrow where features
may match and they contribute one renormalisable term to the score. Everything here is
optional by construction, because on an RGB-only provider most of it is a heuristic and
must be labelled as one.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass

import numpy as np

from ai_engine.types.enums import Device, SemanticClass

__all__ = [
    "CropRowField",
    "RidgeSet",
    "SemanticCapabilities",
    "SemanticMap",
    "TreeLattice",
]


@dataclass(frozen=True, slots=True)
class CropRowField:
    """Estimated crop-row geometry.

    `curvature` is the honesty field: contour-ploughed and centre-pivot fields have no
    single row direction, and a segmenter that reports one anyway hands every downstream
    angle a fiction. Above ~0.3 the estimator must decline rather than answer.
    """

    theta_rad: float  # dominant orientation, folded to [0, pi) — rows are UNDIRECTED
    spacing_px: float
    strength: float  # [0,1] FFT peak power / annulus median
    coherence: float  # [0,1] structure-tensor coherence
    curvature: float  # [0,1] 0=straight, >0.3 => contour/pivot ploughing -> no vanishing point
    orientation_map: np.ndarray | None = None  # (H,W) float32 rad, per-pixel


@dataclass(frozen=True, slots=True)
class TreeLattice:
    """A planted orchard's two-axis lattice.

    `nodes` are the individual trees. In farmland these are among the best landmarks
    available: locally unique, stable across seasons, and visible from both a
    ground-level photograph and a nadir view.
    """

    theta1_rad: float
    theta2_rad: float
    spacing1_px: float
    spacing2_px: float
    nodes: np.ndarray  # (N,2) float32 — tree positions
    strength: float  # [0,1]


@dataclass(frozen=True, slots=True)
class RidgeSet:
    """Multi-scale ridge structures — roads, tracks and irrigation canals.

    These are linear features detected by Hessian vesselness rather than by a detector
    with descriptors. Their INTERSECTIONS are the highest-value landmark candidates in
    farmland, which is what `ClassicalSuggester`'s `semantic` strategy exploits.
    """

    response: np.ndarray  # (H,W) float32 in [0,1] — vesselness, max over scales
    scale_map: np.ndarray | None = None  # (H,W) float32 — the scale (px) that responded best
    segments: np.ndarray | None = None  # (L,4) float32 — x1,y1,x2,y2 fitted centrelines
    junctions: np.ndarray | None = None  # (J,2) float32 — centreline intersections
    scales_px: tuple[float, ...] = ()  # the scale ladder actually evaluated


@dataclass(frozen=True, slots=True)
class SemanticMap:
    """A segmentation of one image, plus the agricultural structure found in it.

    `provenance` is per-class and mandatory: on an RGB-only window the water classes come
    from an HSV heuristic rather than a true index, and a consumer must be able to tell
    the difference. Recording `"hsv_heuristic"` is the mechanism.
    """

    masks: Mapping[SemanticClass, np.ndarray]  # bool (H,W); stored bit-packed in cache
    histogram: np.ndarray  # (C,) float32, area fractions, sums to 1
    crop_rows: CropRowField | None
    lattice: TreeLattice | None
    lines: np.ndarray  # (L,4) float32 x1,y1,x2,y2
    ridges: RidgeSet | None
    provenance: Mapping[SemanticClass, str]  # class -> "classical" | "hsv_heuristic" | "sam" | ...
    image_size: tuple[int, int]  # (width, height)
    version: str

    def regions_of(self, classes: Collection[SemanticClass]) -> np.ndarray:
        """(H,W) bool — the union of the named classes' masks.

        Absent classes contribute nothing rather than raising: a segmenter that cannot
        emit `GREENHOUSE` is a capability difference, not an error, and the caller
        already has `SemanticCapabilities.classes` to ask with.
        """
        width, height = self.image_size
        out = np.zeros((height, width), dtype=bool)
        for cls in classes:
            mask = self.masks.get(cls)
            if mask is not None:
                out |= mask
        return out

    def class_at(self, xy: np.ndarray) -> np.ndarray:
        """(N,2) -> (N,) SemanticClass — the class at each query point.

        Points outside the image, and points no mask claims, return
        `SemanticClass.UNKNOWN`. Where masks overlap, the first class in `masks`
        iteration order wins; a segmenter that emits overlapping masks must order them
        most-specific first.
        """
        query = np.asarray(xy, dtype=np.float64)
        if query.ndim != 2 or query.shape[1] != 2:
            raise ValueError(f"xy must be (N,2); got shape {query.shape}")

        n = query.shape[0]
        out = np.full((n,), SemanticClass.UNKNOWN, dtype=object)
        if n == 0:
            return out

        width, height = self.image_size
        cols = np.rint(query[:, 0]).astype(np.int64)
        rows = np.rint(query[:, 1]).astype(np.int64)
        inside = (cols >= 0) & (cols < width) & (rows >= 0) & (rows < height)
        undecided = inside.copy()

        for cls, mask in self.masks.items():
            if not undecided.any():
                break
            hit = np.zeros((n,), dtype=bool)
            hit[undecided] = mask[rows[undecided], cols[undecided]]
            out[hit] = cls
            undecided &= ~hit
        return out


@dataclass(frozen=True, slots=True)
class SemanticCapabilities:
    """What a SemanticSegmenter can actually emit.

    `classes` is what stops a consumer inferring "no greenhouses here" from a segmenter
    that was never able to see one. Absence of a class in the map means nothing until you
    know whether it was on offer.
    """

    classes: frozenset[SemanticClass]  # what this segmenter can actually emit
    requires_multispectral: bool  # True => needs CandidateWindow.extra_bands
    requires_weights: bool
    supports_prompts: bool  # point/box prompts
    is_deterministic: bool
    device: Device
