"""Degeneracy reporting — the vocabulary of "this fit is not trustworthy".

A homography can fit beautifully and still be wrong: the estimator reports, the
validator judges. These types carry the judgement. The gate they produce multiplies the
score, and a HARD failure zeroes it outright — refusing to answer beats a confident wrong
coordinate (L12).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ai_engine.types.enums import Severity

__all__ = ["DegeneracyCheck", "DegeneracyReport"]


@dataclass(frozen=True, slots=True)
class DegeneracyCheck:
    """One check's verdict.

    `detail` carries the numbers the check actually saw, so a rejection can be explained
    to a surveyor rather than merely asserted at them.
    """

    code: str  # e.g. "insufficient_inliers"
    severity: Severity
    passed: bool
    factor: float  # SOFT: multiplicative in [0,1]. HARD: 1.0 if passed else 0.0.
    detail: Mapping[str, Any]
    message: str


@dataclass(frozen=True, slots=True)
class DegeneracyReport:
    """The full verdict for one candidate window.

    ``gate = 0.0 if hard_failures else prod(soft factors)``, in [0,1].
    """

    checks: tuple[DegeneracyCheck, ...]
    gate: float
    hard_failures: tuple[str, ...]
    soft_penalties: Mapping[str, float]

    @property
    def rejected(self) -> bool:
        """True iff the gate is fully closed — i.e. at least one HARD check failed."""
        return self.gate == 0.0
