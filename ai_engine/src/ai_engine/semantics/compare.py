"""``semantic_similarity()`` — the `S_s` term of the composite score. **DEFERRED.**

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``).

Compares the query photograph's semantics against a candidate window's, under the
homography that claims to relate them. It is the weakest of the four score terms
(`w_semantic = 0.10`) and deliberately so: semantics are the most likely to be wrong, and
they answer a question the other terms cannot — *does this window even contain the same
kind of place?* A window whose field borders and canals land where the photograph's do is
evidence of a different sort from a low reprojection error.

★ WHEN SEMANTICS ARE UNAVAILABLE THIS TERM IS `None`, NOT `0.5`. The scorer renormalises
the remaining weights over the terms it has. Substituting a neutral value would be a
fabricated measurement dressed as a real one, and it would drag every confidence toward
the middle — which is exactly the sort of quiet, plausible distortion this engine is built
to refuse (L12).
"""

from __future__ import annotations

import numpy as np

from ai_engine.errors import NotImplementedDeferred
from ai_engine.types import SemanticMap

__all__ = ["semantic_similarity"]


def semantic_similarity(
    query: SemanticMap,
    window: SemanticMap,
    *,
    H: np.ndarray,
) -> float:
    """Compare two semantic maps under the homography relating them.

    Args:
        query: The query photograph's semantics.
        window: The candidate window's semantics.
        H: `(3,3)` float64 mapping the query frame to the window frame.

    Returns:
        `S_s` in `[0,1]`. Higher means the two agree about what kind of place this is.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    raise NotImplementedDeferred(__name__, feature="semantic similarity scoring")
