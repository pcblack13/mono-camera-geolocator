"""The `ai_engine` exception hierarchy.

Nothing that escapes this package is outside :class:`AiEngineError`. Callers may
therefore write ``except AiEngineError`` and know they have caught everything the
engine can deliberately raise; anything else escaping is a programmer error and
should crash loudly.

This module is deliberately **stdlib-only**. ``ai_engine.types.features`` imports it
(for :class:`IncompatibleDescriptors`), so importing anything from ``ai_engine.types``
at module scope here would create a genuine import cycle. The single type reference
needed for annotations is bound under ``TYPE_CHECKING``: real for ``mypy --strict``,
free at runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only, never executed
    from ai_engine.types.degeneracy import DegeneracyReport

__all__ = [
    "SCOPE_DOC",
    "AiEngineError",
    "ComponentUnavailable",
    "ConfigurationError",
    "DegenerateSolve",
    "DetectorFreeRequiresImages",
    "IncompatibleDescriptors",
    "InsufficientCorrespondences",
    "NoViableCandidate",
    "NotImplementedDeferred",
    "WeightsCorrupt",
    "WeightsMissing",
    "WindowFetchError",
]

#: Where the scope ruling lives. Every :class:`NotImplementedDeferred` points here, so a
#: developer who hits one is one path away from the reasoning rather than one guess away.
SCOPE_DOC = "docs/architecture/SCOPE.md"


class AiEngineError(Exception):
    """Root of every ai_engine exception. Nothing else escapes the package."""


class ConfigurationError(AiEngineError):
    """Bad config. Raised at composition time, never per-request."""


class ComponentUnavailable(ConfigurationError):
    """Fallback chain exhausted. Raised at COMPOSITION time, never per-request."""


class WeightsMissing(ComponentUnavailable):
    """A required weight file is absent. NOT an error on the default path (L1)."""


class WeightsCorrupt(ComponentUnavailable):
    """Weight file present but sha256 mismatch. Treated exactly like missing.

    A half-downloaded checkpoint that imports and then produces garbage is far worse
    than one that is simply absent, so the policy layer treats the two identically.
    """


class NotImplementedDeferred(AiEngineError):
    """★ A feature that is DESIGNED, TYPED and REGISTERED — but not built in this build.

    See ``docs/architecture/SCOPE.md``. The automatic matching engine (feature
    extraction, matching, RANSAC, pose, semantics, scoring, heatmap, suggestion) is
    deferred; the product ships as a **manual** GCP surveying tool where the coordinate
    is a direct observation rather than an inference. Every deferred body raises this,
    and it is the *only* thing a deferred body may do:

    * never ``pass`` — a silent no-op is indistinguishable from success;
    * never a bare ``None`` — the caller cannot tell "no result" from "not built";
    * never a fabricated coordinate or confidence — a confidently-wrong coordinate
      handed to a surveyor is this system's worst failure mode (L12).

    It is a **distinct** class, and deliberately does *not* inherit from the builtin
    ``NotImplementedError``: this must never be swallowed by a generic
    ``except NotImplementedError`` that meant to catch an unimplemented ABC method.
    The distinctness is the entire point — ``backend.app.api`` catches exactly this to
    return ``501`` with a ``feature: "deferred"`` marker, and it must not be able to
    catch anything else by accident.

    Attributes:
        module: The dotted module path of the deferred implementation, e.g.
            ``"ai_engine.extractors.sift"``. Carried so the 501 envelope and the log
            line can name what was asked for.
        feature: Optional human-readable feature name, e.g. ``"SIFT feature extraction"``.
        doc_ref: Path to the document that explains the deferral and the re-enabling plan.
    """

    def __init__(
        self,
        module: str,
        *,
        feature: str | None = None,
        doc_ref: str = SCOPE_DOC,
    ) -> None:
        self.module = module
        self.feature = feature
        self.doc_ref = doc_ref
        what = feature or module
        super().__init__(
            f"{what} is deferred in this build and has no implementation. "
            f"The automatic matching engine is not enabled — place GCPs manually. "
            f"Declared in {module}; see {doc_ref} for the ruling and the rationale."
        )


class IncompatibleDescriptors(AiEngineError):
    """FLANN-KDTree asked to match BINARY descriptors, or D_a != D_b.

    This is the bug class ``DescriptorKind`` exists to prevent: FLANN-KDTree over
    packed ORB bytes returns plausible-looking garbage rather than failing.
    """


class DetectorFreeRequiresImages(AiEngineError):
    """A detector-free matcher was invoked through the Matcher ABC without a live ImageRef."""


class DegenerateSolve(AiEngineError):
    """Carries the DegeneracyReport. Callers MUST handle; never swallow."""

    def __init__(self, report: DegeneracyReport) -> None:
        self.report = report
        hard = ", ".join(report.hard_failures) or "none"
        super().__init__(f"Degenerate solve (gate={report.gate:.3f}); hard failures: {hard}")


class InsufficientCorrespondences(AiEngineError):
    """Fewer than 4 point pairs. A homography is not defined."""


class WindowFetchError(AiEngineError):
    """★ PART OF THE WindowSource PROTOCOL CONTRACT (§4.10).

    A WindowSource MAY raise this for an INDIVIDUAL window; the orchestrator logs it,
    counts it, and continues to the next window.

    It lives HERE, on the ai_engine side, because ai_engine DECLARES WindowSource and
    ai_engine.pipeline MUST NOT import gis (§10.2). An implementation
    (gis.candidates.source.TileWindowSource) MUST wrap gis.errors.ProviderError in this
    before letting it cross the seam. The seam's exception type must live on the side
    that declares the Protocol — otherwise the orchestrator's only option is
    ``except Exception``, which §4.13 calls a defect.

    Attributes:
        window_key: The opaque ``WindowRef.key`` that failed. Never parsed here.
        cause_type: The wrapped exception's class name, as a plain string, so the
            engine can report provenance without importing the package that raised it.
    """

    def __init__(self, window_key: str, cause_type: str, message: str | None = None) -> None:
        self.window_key = window_key
        self.cause_type = cause_type
        super().__init__(message or f"Failed to fetch window {window_key!r} ({cause_type})")


class NoViableCandidate(AiEngineError):
    """★ NEVER RAISED ACROSS THE PACKAGE BOUNDARY. Retained ONLY as an internal marker
    inside step9_finalize.

    ``run_match_job`` RETURNS ``MatchJobResult(status="no_viable_candidate")``. See §4.13,
    §11.6 and §12 C-46. Returning is also the internally consistent choice: §4.7 already
    rules that ``estimate_homography`` RETURNS a sub-threshold result rather than raising,
    because "estimation reports, policy judges" — and a status is data.
    """
