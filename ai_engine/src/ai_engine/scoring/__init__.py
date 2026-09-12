"""Scoring: match quality → the confidence the product reports.

★ EVERYTHING IN THIS PACKAGE IS DEFERRED (``docs/architecture/SCOPE.md``). The
`ScoringModel` ABC and the `composite` registry entry are real; the bodies are not.

★ THIS PACKAGE MUST NOT COMPUTE A GROUND SAMPLE DISTANCE. It is passed in on
`CandidateWindow.gsd_m`, already corrected for where the window sits on the planet.
Deriving one here would need the window's position, which is exactly what `ai_engine` may
not know (L3).

The chain: ``composite → ⊥``.
"""

from __future__ import annotations

from ai_engine.scoring.base import ScoringModel
from ai_engine.scoring.composite import CompositeScoringModel

__all__ = ["CompositeScoringModel", "ScoringModel"]
