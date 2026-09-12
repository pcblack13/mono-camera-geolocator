"""Pipeline: orchestrate the steps, emit progress.

★ THE AUTOMATIC MATCHING PIPELINE IS DEFERRED (``docs/architecture/SCOPE.md``).
`run_match_job` and `build_context` raise `NotImplementedDeferred` immediately. The
`MatchContext` bundle, the nine step signatures, and the normative `component_config` /
`params_hash` are real.

★ `run_match_job` RAISES RATHER THAN RETURNING ITS OWN EMPTY RESULT, and that is the most
consequential decision in this package — `orchestrator.py`'s docstring argues it at length.
In one line: ``status="no_viable_candidate"`` asserts *the engine looked and found nothing*,
which is a claim about the surveyor's imagery. Saying that when the engine never looked
would be false, believable, and unfalsifiable from the outside.

This package may import all of `ai_engine`. It may not import `gis`, `app`, `celery`, a
database or a network — `ctx.on_progress` is the entire coupling to the outside world.
"""

from __future__ import annotations

from ai_engine.pipeline.compose import build_context, component_config, params_hash
from ai_engine.pipeline.context import MatchContext, SearchSeed
from ai_engine.pipeline.orchestrator import run_match_job

__all__ = [
    "MatchContext",
    "SearchSeed",
    "build_context",
    "component_config",
    "params_hash",
    "run_match_job",
]
