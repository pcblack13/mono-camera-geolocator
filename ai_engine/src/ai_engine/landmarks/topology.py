"""``cross_ratio_signature()`` — projective-invariant landmark topology. **DEFERRED.**

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``).

The cross ratio is invariant under any projective transformation, which makes it the right
tool for asking *"are these the same five landmarks, or five different ones arranged
similarly?"* — a question descriptor matching cannot answer, because in farmland the
landmarks genuinely do look alike.

★ `hull_order_invariant()` IS DELETED, DELIBERATELY, AND THIS NOTE IS THE RECORD.
It was H11: the landmark hull's cyclic order. It is provably redundant — any homography
that preserves orientation (H2: ``det(H̃) > 0``) and does not fold the plane through
infinity inside the region of interest (H4) **necessarily** preserves the cyclic order of a
convex hull. H2 and H4 together already imply it, so H11 could never fire on an input that
reached it, and IU-05's suite proves exactly that by constructing a valid `H` and asserting
the condition never trips. A check that cannot fail is not a safety net; it is a line of
code that makes the next reader believe there is one more safeguard than there is.
"""

from __future__ import annotations

import numpy as np

from ai_engine.errors import NotImplementedDeferred

__all__ = ["cross_ratio_signature"]


def cross_ratio_signature(points: np.ndarray) -> np.ndarray:
    """Compute the projective-invariant cross-ratio signature of a point configuration.

    Args:
        points: `(K,2)` float64 — at least 5 points. Fewer than five have no cross ratio,
            which is a property of projective geometry, not a limitation here.

    Returns:
        `(S,)` float64 signature, invariant under any projective transformation of
        `points`.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    raise NotImplementedDeferred(__name__, feature="cross-ratio landmark signature")
