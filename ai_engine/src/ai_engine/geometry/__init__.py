"""Geometry: correspondences → homography and pose, **in pixel space**.

★ NO REFERENCE SYSTEM. EVER. (L3) This package begins at pixels and ends at pixels. It
cannot name a coordinate, it cannot convert one, and it does not import anything that
could. `gis` turns a pixel fix into a coordinate; the fact that nothing here *can* is what
makes the boundary mechanical rather than a matter of discipline.

★ EVERYTHING IN THIS PACKAGE IS DEFERRED (``docs/architecture/SCOPE.md``). The
`GeometryEstimator` ABC and the `opencv` registry entry are real; the estimator, the
degeneracy validator, the pose solver, the calibrator and the covariance propagation are
not. SCOPE §2 records the reason, and it is a judgement about this product rather than a
schedule: a planar homography is strictly valid only for a planar scene or a pure
rotation, a ground-level oblique violates both, and the manual GCP path this build ships
instead has no homography at all — so it has no degenerate solve, no viewpoint assumption
and no estimated confidence to calibrate. The coordinate is a direct observation.
"""

from __future__ import annotations

from ai_engine.geometry.base import GeometryEstimator
from ai_engine.geometry.degeneracy import DegeneracyValidator
from ai_engine.geometry.homography import OpenCvHomographyEstimator
from ai_engine.geometry.pose import PoseEstimator

__all__ = [
    "DegeneracyValidator",
    "GeometryEstimator",
    "OpenCvHomographyEstimator",
    "PoseEstimator",
]
