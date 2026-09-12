"""``match_image_task`` — the automatic matching pipeline. **DEFERRED (SCOPE.md §1).**

★ §2.4 calls this file *"the composition root"*: when the automatic engine is enabled, this
is the ONE place a live imagery provider session and an ``ai_engine`` ``MatchContext``
coexist. The service (``match_service``) builds a plain JSON ``MatchJobSpec`` — a provider
*name*, a resolved AOI, zoom levels and an ``AiEngineConfig`` dict — and never a
``WindowSource`` (a ``TileWindowSource`` holds an httpx session and cannot cross the
broker). Inside the worker, this task would:

1. resolve the imagery provider from its name and construct the ``TileWindowSource``;
2. at stage ``resolving_models`` run ``ai_engine.models.preflight`` and record any weight
   fallback as a ``WarningItem`` + ``degraded`` — *the instant it is known* (§11.1);
3. ``compose.build_context()`` → ``run_match_job()`` (ai_engine's single public entry);
4. persist ``match_results`` + derived GCPs and mark the job ``succeeded`` (result_count 0
   on "no viable candidate" — that is a success, not a failure, §11.6).

**In this build there is nothing to compose.** Feature extraction, matching, RANSAC and
scoring are typed ABCs with no bodies (SCOPE.md §4). ``match_service`` returns ``501
feature: "deferred"`` before a job is ever enqueued, so this task is not normally reached;
if it is (a hand-submitted spec), it fails the job honestly as ``FEATURE_DEFERRED`` rather
than hanging on a spinner or fabricating a coordinate — a confidently-wrong coordinate is
this system's worst failure mode (SCOPE.md §2, L12).

Re-enabling is a zero-caller change (SCOPE.md §7): implement the ABCs in ``ai_engine``,
flip ``match_service`` from 501 to enqueue, and fill the body below.
"""

from __future__ import annotations

from typing import Any

from celery import shared_task

from ai_engine.errors import NotImplementedDeferred
from app.models.enums import JobType
from app.tasks.base import BaseJobTask, job_lifecycle
from app.tasks.celery_app import TASK_MATCH

__all__ = ["match_image_task"]


@shared_task(bind=True, base=BaseJobTask, name=TASK_MATCH)
def match_image_task(self: Any, job_id: str, **payload: Any) -> None:
    """Run the automatic match pipeline for one image. **Deferred** — see module docstring.

    Args:
        job_id: The ``match_jobs`` row id.
        payload: The JSON ``MatchJobSpec`` fields (provider, AOI, zooms, config dict).
    """
    with job_lifecycle(self, JobType.MATCH, job_id):
        raise NotImplementedDeferred(
            "ai_engine.pipeline.orchestrator",
            feature="Automatic image matching",
        )
