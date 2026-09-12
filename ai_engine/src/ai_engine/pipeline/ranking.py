"""``rank_windows()`` and ``ambiguity_margin()``. **DEFERRED.**

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``).

★ BOTH OPERATE ON `ScoreResult.raw`, NEVER ON `confidence`. `confidence` is clamped by the
view regime — an oblique-raw view is capped no matter how well it fits, because the planar
model is wrong for it. Two genuinely different windows can therefore both saturate at the
same ceiling, and a margin computed on the clamped number would report them as
indistinguishable and flag the job `ambiguous`. The raw score still separates them. The
clamp exists to stop the product overstating its certainty; it must not also make the
product lose track of which candidate won.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NoReturn

from ai_engine.errors import NotImplementedDeferred
from ai_engine.types import WindowResult

__all__ = ["ambiguity_margin", "rank_windows"]


def _deferred(feature: str) -> NoReturn:
    """Raise `NotImplementedDeferred` naming this module and `feature`."""
    raise NotImplementedDeferred(__name__, feature=feature)


def rank_windows(
    results: Sequence[WindowResult],
    *,
    min_confidence: float = 40.0,
    max_results: int = 5,
) -> list[WindowResult]:
    """Rank scored windows best-first and drop the unconvincing ones.

    Args:
        results: The scored windows.
        min_confidence: `[0,100]`. Below this a candidate is dropped entirely — refusing to
            answer beats a confident wrong coordinate (L12).
        max_results: How many ranked candidates to keep.

    Returns:
        At most `max_results` windows, best first. Empty is a legitimate outcome and means
        `status="no_viable_candidate"`.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    _deferred("candidate window ranking")


def ambiguity_margin(results: Sequence[WindowResult]) -> float | None:
    """The separation between the winner and the runner-up, **on `ScoreResult.raw`**.

    Args:
        results: The ranked windows, best first.

    Returns:
        The margin, or None when there are fewer than two candidates — one candidate is
        unambiguous by definition, and reporting a margin of 0 or 100 for it would both be
        inventions.

    ★ Computed on `raw`, never on `confidence`. See the module docstring: the regime clamp
    saturates, and a margin measured after it reports two well-separated windows as a tie.

    Raises:
        NotImplementedDeferred: Always, in this build.
    """
    _deferred("ambiguity margin computation")
