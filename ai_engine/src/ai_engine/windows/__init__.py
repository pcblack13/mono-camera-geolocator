"""Windows: candidate imagery arrives here. `ai_engine` never fetches it.

The `CandidateWindow` and `WindowSource` **types** live in `ai_engine.types.windows` — the
side that declares the Protocol owns the Protocol. This package holds what produces windows
*inside* the engine, which is exactly one thing: a synthetic source for testing.

★ `SyntheticWindowSource` IS REAL AND SHIPS (SCOPE §6). It is procedural numpy with a known
ground-truth homography, and it is the harness the automatic engine will have to satisfy
before it can be enabled. It costs nothing now and it is what makes the whole engine
measurable with no network, no weights and no GPU.
"""

from __future__ import annotations

from ai_engine.windows.testing import (
    SyntheticCameraPose,
    SyntheticWindowSource,
    ground_truth_homography,
)

__all__ = [
    "SyntheticCameraPose",
    "SyntheticWindowSource",
    "ground_truth_homography",
]
