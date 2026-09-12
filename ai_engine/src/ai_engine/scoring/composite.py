"""`CompositeScoringModel` — ★ the DEFAULT scorer. TERMINAL. **DEFERRED.**

★ DEFERRED IN THIS BUILD (``docs/architecture/SCOPE.md``): SCOPE §4 lists the composite
score (feature + geometric + landmark + semantic) as ABC only.

The formula, when implemented (§4.12, normative)::

    raw = (Σ_t w_t · S_t) / (Σ_t w_t) · gate        over the terms that EXIST
    confidence = 100 · calibrate(raw)               clamped by the view regime

Four properties the implementation must have, each of which is a real bug that was found
rather than a style rule:

* **A `None` term drops from BOTH the numerator and the denominator.** Absent semantics
  must score exactly like `w_semantic = 0` renormalised — **not** like `s_semantic = 0.5`.
  A neutral substitute is a fabricated measurement, and it drags every confidence toward
  the middle.
* **`gate == 0` ⇒ `confidence == 0` and `status == "rejected"`, through the calibrator.**
  See `scoring/base.py`: a curve that swallows the gate resurrects a fit the degeneracy
  validator rejected, and `logit(0)` is `NaN` rather than 0, so an identity-only test
  cannot see it.
* **The regime ceiling clamps and sets `clamp_reason`.** An oblique-raw view cannot support
  a high confidence no matter how well it fits, because the model itself is wrong for it.
  Clamping silently would hide the single most important caveat on the number.
* **Every element of `feature_names()` appears in EXACTLY ONE of `{S_f, S_g, S_l, S_s,
  gate}`.** A feature counted twice is a term secretly weighted twice.

`ambiguity_margin` is computed on `ScoreResult.raw`, never on the clamped `confidence` —
two windows both above the regime ceiling would otherwise saturate to the same number and
be reported as ambiguous when they are not.
"""

from __future__ import annotations

from typing import ClassVar

from ai_engine.models import ComponentKind, DeferredImplementation, register
from ai_engine.scoring.base import ScoringModel
from ai_engine.types import Device, ScoreEvidence, ScoreResult

__all__ = ["CompositeScoringModel"]


@register(ComponentKind.SCORER, fallback=None, is_terminal=True, device_preference=Device.CPU)
class CompositeScoringModel(DeferredImplementation, ScoringModel):
    """The weighted composite of the four evidence terms, gated by degeneracy.

    ★ TERMINAL and DEFAULT. The scorer chain ends here.
    """

    name: ClassVar[str] = "composite"

    deferred_module: ClassVar[str] = __name__
    deferred_feature: ClassVar[str] = "composite match scoring"

    def score(self, evidence: ScoreEvidence) -> ScoreResult:
        """Deferred. See the module docstring."""
        self._deferred()

    def feature_names(self) -> tuple[str, ...]:
        """Deferred. See the module docstring."""
        self._deferred()
