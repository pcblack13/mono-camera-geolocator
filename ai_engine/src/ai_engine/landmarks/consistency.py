"""``landmark_consistency()`` — the `S_l` term of the composite score. **DEFERRED.**

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``).

`S_l` is the heaviest single term after geometry (`w_landmark = 0.30`) because it is the
one that uses what only this product has: a human being pointed at a thing and said *that
one*. A window that puts the surveyor's landmarks where the surveyor put them is evidence
of a different kind from a good reprojection error over a thousand anonymous corners.
"""

from __future__ import annotations

from collections.abc import Sequence

from ai_engine.errors import NotImplementedDeferred
from ai_engine.types import LandmarkEvidence, LandmarkSet

__all__ = ["landmark_consistency"]


def landmark_consistency(
    landmarks: LandmarkSet,
    evidence: Sequence[LandmarkEvidence],
) -> float:
    """Combine per-landmark evidence into `S_l`.

    Args:
        landmarks: The surveyor's landmarks, carrying `user_weight` per landmark.
        evidence: One `LandmarkEvidence` per landmark, in `landmark_id` order.

    Returns:
        `S_l` in `[0,1]` — the user-weighted mean of the per-landmark scores.

    ★ The weighting is by `Landmark.user_weight`, which is a **declared** judgement rather
    than a computed one, and the sum is over k with each landmark counted exactly once.
    Both facts depend on `extract_at`'s 1:1 cardinality contract holding: a duplicated
    `landmark_id` silently gives that landmark two votes here.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    raise NotImplementedDeferred(__name__, feature="landmark consistency scoring")
