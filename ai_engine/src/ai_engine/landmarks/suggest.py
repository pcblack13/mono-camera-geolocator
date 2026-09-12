"""`LandmarkSuggester` — automatic landmark suggestions. **DEFERRED.**

★ THE ABC IS REAL AND COMPLETE; both suggesters are deferred
(``docs/architecture/SCOPE.md``, which lists automatic landmark suggestion as ABC only).

``suggest_landmarks()`` is `ai_engine`'s **second public entry point**, alongside
`run_match_job`. It is re-exported lazily from `ai_engine/__init__.py`, and
`LandmarkProposal` maps 1:1 onto a `landmark_suggestions` row.

★ EVERY PROPOSAL CARRIES A `rationale`, AND IT IS A REQUIRED FIELD RATHER THAN A NICETY.
A suggestion a surveyor cannot interrogate is one they will not accept — and *should* not
accept. "Ranked #3, score 0.71" tells them nothing they can check; "road/canal junction,
strong ridge response at two scales" tells them what to look at and lets them disagree.
This product's whole posture is that a coordinate someone may dig against must be
defensible, and a suggestion is the start of that chain.

★ WHAT THE MANUAL BUILD MEANS HERE. Suggestion is an *accelerant* for the manual flow, not
part of the automatic pipeline — it proposes where a surveyor might look, and the surveyor
still places and confirms every GCP. It is deferred with the rest of the CV surface, and
`POST /images/{id}/suggest-landmarks` returns 501 with ``feature: "deferred"`` rather than
404: the feature is planned, not absent.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar

import numpy as np

from ai_engine.errors import NotImplementedDeferred
from ai_engine.models import ComponentKind, DeferredImplementation, Registry, register
from ai_engine.models.torch_guard import TORCH_MODULE_NAME
from ai_engine.types import (
    Device,
    LandmarkProposal,
    SemanticMap,
    SuggesterCapabilities,
    SuggestionStrategy,
)
from ai_engine.version import LANDMARK_VERSION

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ai_engine.config import AiEngineConfig

__all__ = [
    "ClassicalSuggester",
    "LandmarkSuggester",
    "SamSuggester",
    "suggest_landmarks",
]


class LandmarkSuggester(ABC):
    """Proposes landmarks a surveyor might want to place a GCP on.

    Attributes:
        name: The registry key, e.g. ``"classical_suggester"``.
        version: Cache-key input.
    """

    name: ClassVar[str]
    version: ClassVar[str]

    @abstractmethod
    def suggest(
        self,
        image: np.ndarray,
        *,
        strategy: SuggestionStrategy,
        semantics: SemanticMap | None = None,
        max_results: int = 25,
    ) -> tuple[LandmarkProposal, ...]:
        """Propose landmarks in `image`, ranked best first.

        Args:
            image: `(H,W,3)` uint8 RGB — the QUERY photograph.
            strategy: Which strategy to run. A suggester that cannot run the requested one
                must say so through :meth:`capabilities` rather than substitute another
                silently — the caller reports the substitution as a `WarningItem` with an
                `effective` field, and can only do that if it knows.
            semantics: A prior segment job's output, reused rather than recomputed.
            max_results: The cap on returned proposals.

        Returns:
            Proposals sorted **descending by score**, at most `max_results` of them.

        ★ MUST return `()` rather than raise when it finds nothing. A featureless
        photograph is an ordinary outcome, and an empty list says so precisely.
        """

    def capabilities(self) -> SuggesterCapabilities:
        """Which strategies this suggester can actually run.

        ★ Not decorative. `SuggestionStrategy.SALIENCY` is not offered by the classical
        path at all, so on a weightless box a request for it resolves through the normal
        fallback and reports ``effective: "hybrid"`` in a `WarningItem`. That only works
        because this method answers honestly instead of claiming all four.

        Raises:
            NotImplementedError: The base class cannot know. Subclasses must answer.
        """
        raise NotImplementedError(
            f"{type(self).__name__} must implement capabilities(): a suggester that will "
            f"not say which strategies it supports forces its caller to guess, and the "
            f"guess is reported to the surveyor as fact."
        )


@register(
    ComponentKind.SUGGESTER,
    fallback=None,
    is_terminal=True,
    device_preference=Device.CPU,
)
class ClassicalSuggester(DeferredImplementation, LandmarkSuggester):
    """★ TERMINAL, no weights. **DEFERRED.**

    When implemented it offers three of the four strategies:

    * ``corners``  — Shi-Tomasi/Harris, non-max-suppressed, scored by cornerness ×
      distance-from-edge. A corner on the frame boundary is worthless as a GCP because
      half its neighbourhood is missing.
    * ``semantic`` — ridge intersections from `semantics/ridges.py` (road and canal
      crossings are the highest-value GCPs farmland offers) plus contour corners from
      `semantics/classical.py`.
    * ``hybrid``   — reciprocal-rank fusion of the two.

    ``saliency`` is **not** offered, and `capabilities()` says so.
    """

    name: ClassVar[str] = "classical_suggester"
    version: ClassVar[str] = LANDMARK_VERSION

    deferred_module: ClassVar[str] = __name__
    deferred_feature: ClassVar[str] = "classical landmark suggestion"

    def suggest(
        self,
        image: np.ndarray,
        *,
        strategy: SuggestionStrategy,
        semantics: SemanticMap | None = None,
        max_results: int = 25,
    ) -> tuple[LandmarkProposal, ...]:
        """Deferred. See the class docstring."""
        self._deferred()

    def capabilities(self) -> SuggesterCapabilities:
        """Deferred. See the class docstring."""
        self._deferred()


@register(
    ComponentKind.SUGGESTER,
    fallback="classical_suggester",
    requires_packages=(TORCH_MODULE_NAME,),
    requires_weights=("sam_vit_h_v1",),
    device_preference=Device.AUTO,
)
class SamSuggester(DeferredImplementation, LandmarkSuggester):
    """SAM-backed suggestion — all four strategies, including `saliency`. **DEFERRED.**

    Falls back to `classical_suggester`, which is terminal, so the chain provably ends.
    """

    name: ClassVar[str] = "sam_suggester"
    version: ClassVar[str] = LANDMARK_VERSION

    deferred_module: ClassVar[str] = __name__
    deferred_feature: ClassVar[str] = "SAM-backed landmark suggestion"

    def suggest(
        self,
        image: np.ndarray,
        *,
        strategy: SuggestionStrategy,
        semantics: SemanticMap | None = None,
        max_results: int = 25,
    ) -> tuple[LandmarkProposal, ...]:
        """Deferred. See the class docstring."""
        self._deferred()

    def capabilities(self) -> SuggesterCapabilities:
        """Deferred. See the class docstring."""
        self._deferred()


def suggest_landmarks(
    image: np.ndarray,
    *,
    cfg: AiEngineConfig,
    registry: Registry | None = None,
    strategy: SuggestionStrategy = SuggestionStrategy.HYBRID,
    semantics: SemanticMap | None = None,
    max_results: int = 25,
) -> tuple[LandmarkProposal, ...]:
    """★ `ai_engine`'s SECOND public entry point. **DEFERRED.**

    Resolves the configured suggester through the registry and runs it. Re-exported lazily
    as `ai_engine.suggest_landmarks`; backs `job_type='suggest_landmarks'` and the
    suggestion endpoints.

    Args:
        image: `(H,W,3)` uint8 RGB — the query photograph.
        cfg: The engine configuration. `cfg.suggester` names the component.
        registry: The registry to resolve against. Defaults to the process singleton.
        strategy: Which strategy to run.
        semantics: A prior segment job's output, to reuse rather than recompute.
        max_results: The cap on returned proposals.

    Returns:
        Proposals ranked best first. Empty is a legitimate result.

    Raises:
        NotImplementedDeferred: Always, in this build. ★ It raises IMMEDIATELY and
            unmistakably rather than resolving components first: there is nothing to
            resolve *for* — no suggester can be constructed — and burning a registry walk
            to arrive at the same exception would only make the failure look conditional
            when it is categorical. `preflight()` is where the resolution is reported; this
            is where the refusal happens. The API layer catches this exact class and
            answers 501 with ``feature: "deferred"``.
    """
    raise NotImplementedDeferred(
        __name__,
        feature="automatic landmark suggestion",
    )
