"""Structured events — ★ REAL. Plain dataclasses, no CV.

`ComponentFallback` · `StepTiming` · `DegeneracyTripped`. These are the typed shapes the
pipeline emits so that a degradation is visible from outside the process, which is L11's
whole point: never a traceback, and **never silent**.

★ WHY `models/policy.py` EMITS A LOG RECORD INSTEAD OF `ComponentFallback` DIRECTLY.
§10.2 confines `ai_engine.models` to stdlib + `ai_engine.{types,errors}`, and `runtime` sits
above it — importing this module from the policy layer would invert the dependency and cycle
the build order. So the split is: **policy reports data** (a `Resolution` carrying
`requested`, `resolved`, `chain`, `reason`, `degraded`) and logs a WARNING carrying the four
§4.14 fields in `extra`; **the pipeline turns that data into a typed event**, where it also
has the `job_id` and `stage` that §11.8's table requires and that the registry cannot know.
:meth:`ComponentFallback.from_resolution` is that conversion, and it is the reason this
class is not merely a log line with extra steps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ai_engine.types import ComponentKind, Resolution

__all__ = ["ComponentFallback", "DegeneracyTripped", "StepTiming"]


@dataclass(frozen=True, slots=True)
class ComponentFallback:
    """A component resolved to something other than what was asked for.

    ★ THIS EVENT IS HOW A USER FINDS OUT THEY CONFIGURED SUPERPOINT AND GOT SIFT. It is a
    WARNING, it carries a `WarningItem` onto the response, it increments
    `model_fallbacks_total{requested,effective}`, and it sets `match_jobs.degraded`. An
    unrequested fallback (the fresh-machine default) renders in the UI as an informational
    chip; a requested-and-denied one renders as a warning. The distinction is exactly
    ``requested is not None``.

    Attributes:
        component_kind: Which slot fell back.
        requested: The name the configuration asked for.
        effective: The name actually resolved.
        chain: The full walk, e.g. ``("superpoint", "sift")``.
        reason: Why the requested one was unavailable — destined for a human.
        exc_type: The exception class name when construction failed, else None.
        degraded: Whether the result differs from what was requested.
        deferred: ★ True when the resolved component is registered but **not implemented in
            this build** (``docs/architecture/SCOPE.md``). Distinct from `degraded`, and the
            distinction is the honest one: "we used a lesser backend" and "this capability
            does not exist yet" are different facts, and collapsing them would let the
            second hide inside the first.
        job_id: The job this happened in. The registry cannot know it; the pipeline can.
        stage: The job stage at which it was discovered — ``"resolving_models"``, which is
            the instant it is known rather than the end of the job.
    """

    component_kind: ComponentKind
    requested: str
    effective: str
    chain: tuple[str, ...]
    reason: str | None
    exc_type: str | None = None
    degraded: bool = True
    deferred: bool = False
    job_id: str | None = None
    stage: str = "resolving_models"

    @classmethod
    def from_resolution(
        cls,
        kind: ComponentKind,
        resolution: Resolution,
        *,
        job_id: str | None = None,
    ) -> ComponentFallback:
        """Build the event from a `Resolution` — the models→runtime bridge.

        Args:
            kind: The slot that was resolved.
            resolution: What the registry reported.
            job_id: The job it happened in.

        Returns:
            The typed event, with `deferred` set from the resolution's instance rather than
            from string-matching its `reason`.
        """
        from ai_engine.models.policy import is_deferred  # noqa: PLC0415 — avoids a cycle

        return cls(
            component_kind=kind,
            requested=resolution.requested,
            effective=resolution.resolved,
            chain=resolution.chain,
            reason=resolution.reason,
            degraded=resolution.degraded,
            deferred=is_deferred(resolution),
            job_id=job_id,
        )


@dataclass(frozen=True, slots=True)
class StepTiming:
    """How long one pipeline step took.

    Attributes:
        step: The step name, e.g. ``"step5_correspond"``.
        duration_ms: Wall-clock milliseconds.
        window_key: The opaque `WindowRef.key` when the step was per-window. Never parsed.
        job_id: The job.
        meta: Anything else worth recording — counts, sizes.
    """

    step: str
    duration_ms: float
    window_key: str | None = None
    job_id: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DegeneracyTripped:
    """A candidate was gated by the degeneracy validator.

    ★ Emitted for HARD failures, which zero the gate and reject the candidate. This is L12
    working rather than breaking: the fit was arithmetically fine and physically absurd, and
    the engine refused it. It is worth a structured event precisely because it looks like an
    absence from the outside — a job that rejected every window returns
    `no_viable_candidate`, and without these events nobody could tell that from a job that
    found nothing to look at.

    Attributes:
        checks: The names of the hard checks that failed, e.g. ``("H4", "H6")``.
        gate: The resulting gate value. 0.0 for a hard failure.
        window_key: The opaque `WindowRef.key`. Never parsed.
        job_id: The job.
        severity: ``"hard"`` or ``"soft"``. Soft checks multiply the gate and never zero it.
    """

    checks: tuple[str, ...]
    gate: float
    window_key: str | None = None
    job_id: str | None = None
    severity: str = "hard"
