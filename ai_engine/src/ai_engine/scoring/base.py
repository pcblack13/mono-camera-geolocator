"""The `ScoringModel` ABC — evidence → the number the product reports.

★ THE ABC IS REAL AND COMPLETE; the scorer is deferred (``docs/architecture/SCOPE.md``).

★ WHAT `confidence` IS, AND WHAT IT IS NOT. It is a **score** in `[0,100]`, not a
probability. `ScoreResult.calibrated` ships **False** and `calibration_id` ships
``"identity"`` — because a fabricated calibration curve is not a nicety, it is a lie with a
probability attached to it, and the surveyor reading "87% confident" would have no way to
know it meant "87 arbitrary units". Calibration is a thing you earn from data, and the
honest default is to say you have not earned it yet.

★ AND NOTE WHERE THIS BUILD LEAVES THE WHOLE QUESTION. In manual mode there is no computed
confidence at all: the surveyor **declares** it (1-5 / low-med-high). Every GCP records
``source="manual"``, so a declared judgement can never be confused with an inferred one in
the table or in an export. That is not a workaround for the deferral — SCOPE §2 argues it
is the better number, because it is the one whose meaning its reader actually knows.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from ai_engine.types import ScoreEvidence, ScoreResult

__all__ = ["ScoringModel"]


class ScoringModel(ABC):
    """Turns the evidence for one candidate window into a `ScoreResult`.

    Attributes:
        name: The registry key, e.g. ``"composite"``.
    """

    name: ClassVar[str]

    @abstractmethod
    def score(self, evidence: ScoreEvidence) -> ScoreResult:
        """Score one candidate window.

        Args:
            evidence: Everything known about this window's fit — correspondences, the
                homography, the degeneracy report, landmark evidence, semantics and the
                view regime.

        Returns:
            A `ScoreResult` with `confidence` in `[0,100]`, the per-term breakdown, and an
            honest `calibrated` flag.

        ★ `gate == 0` MUST produce `confidence == 0` and `status == "rejected"`, and it must
        do so **through the calibrator, not around it**. The gate is multiplicative and it
        is the degeneracy verdict — a calibration curve that swallowed it would resurrect a
        fit the validator rejected. `logit(0)` is `NaN`, not 0, which is exactly how that
        bug hides from an identity-only test.
        """

    @abstractmethod
    def feature_names(self) -> tuple[str, ...]:
        """Column names for `ScoreResult.feature_vector`, in order.

        ★ STABLE ACROSS VERSIONS, or the persisted training data becomes unreadable. The
        feature vector is stored on every result precisely so that calibration can be refit
        offline without re-running any CV — which only works if the columns still mean what
        they meant when they were written.
        """
