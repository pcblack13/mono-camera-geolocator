"""Landmarks: the mechanisms that steer matching with what the surveyor pointed at.

★ EVERYTHING IN THIS PACKAGE IS DEFERRED (``docs/architecture/SCOPE.md``). The
`LandmarkSuggester` ABC and the two registry entries are real; the bodies are not.

The landmark path is what makes this engine a *surveying* tool rather than an image-matcher
— and in this build it is the whole product, from the other direction. The automatic path
is deferred precisely because a manually placed GCP needs none of it: the surveyor marks a
landmark in the photograph, clicks the same spot on the map, and the coordinate is recorded
as a direct observation. No homography, no degenerate solve, no estimated confidence to
calibrate. `confidence` is a declared judgement (1-5 / low-med-high), never a computed
number, and every GCP records ``source="manual"`` so an inferred fix can never be confused
with an observed one downstream or in an export.

These modules exist for the day the automatic path returns. The chain:
``sam_suggester → classical_suggester → ⊥``.
"""

from __future__ import annotations

from ai_engine.landmarks.suggest import (
    ClassicalSuggester,
    LandmarkSuggester,
    SamSuggester,
    suggest_landmarks,
)

__all__ = [
    "ClassicalSuggester",
    "LandmarkSuggester",
    "SamSuggester",
    "suggest_landmarks",
]
