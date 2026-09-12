"""Version constants — and they are CACHE-KEY INPUTS, not decoration.

A cached FeatureSet computed by an older extractor must not be served to a newer one.
Every component that caches anything folds its `*_VERSION` into the key, so bumping the
constant is how you invalidate the cache. **Bump the component version in the same commit
as any change to what that component produces**, or stale descriptors will be silently
matched against fresh ones — which fails as a slightly worse answer rather than as an
error, and is therefore the kind of bug that survives review.

`ENGINE_VERSION` is recorded on every `MatchJobResult` and persisted, so a result can
always be attributed to the code that produced it.
"""

from __future__ import annotations

__all__ = [
    "COMPONENT_VERSIONS",
    "ENGINE_VERSION",
    "EXTRACTOR_VERSION",
    "GEOMETRY_VERSION",
    "HEATMAP_VERSION",
    "LANDMARK_VERSION",
    "MATCHER_VERSION",
    "PIPELINE_VERSION",
    "SCORING_VERSION",
    "SEMANTICS_VERSION",
    "TYPES_VERSION",
    "version",
]

#: The package version. Kept in step with the version declared in the packaging metadata.
ENGINE_VERSION = "2.0.0"

# --- per-component versions (cache-key inputs) ---------------------------------------
#: Extraction: keypoint conventions, descriptor normalisation, RootSIFT.
EXTRACTOR_VERSION = "1"
#: Matching: filters, score normalisation, guided search.
MATCHER_VERSION = "1"
#: Estimation: normalisation, refinement, covariance, degeneracy checks.
GEOMETRY_VERSION = "1"
#: Segmentation: masks, indices, crop rows, ridges.
SEMANTICS_VERSION = "1"
#: Landmark mechanisms: patch bank, priors, consistency, suggestion.
LANDMARK_VERSION = "1"
#: Scoring: the composite formula and its feature vector layout.
SCORING_VERSION = "1"
#: The camera-location posterior.
HEATMAP_VERSION = "1"
#: Orchestration: step order and result assembly.
PIPELINE_VERSION = "1"
#: The value-type layer. Bump when a stored dataclass's field set changes.
TYPES_VERSION = "1"

#: Every component version, keyed by the component family. Folded into cache keys and
#: reported by `GET /capabilities` so a stale cache is diagnosable from outside.
COMPONENT_VERSIONS: dict[str, str] = {
    "extractor": EXTRACTOR_VERSION,
    "matcher": MATCHER_VERSION,
    "geometry": GEOMETRY_VERSION,
    "semantics": SEMANTICS_VERSION,
    "landmark": LANDMARK_VERSION,
    "scoring": SCORING_VERSION,
    "heatmap": HEATMAP_VERSION,
    "pipeline": PIPELINE_VERSION,
    "types": TYPES_VERSION,
}


def version() -> str:
    """Return the engine version string.

    Re-exported as `ai_engine.version()`. This is the one thing a caller can ask the
    package without importing anything heavy.
    """
    return ENGINE_VERSION
