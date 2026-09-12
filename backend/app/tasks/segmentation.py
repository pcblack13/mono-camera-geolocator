"""``segment_image_task`` and ``suggest_landmarks_task`` — **DEFERRED (SCOPE.md §1, §4).**

Semantic segmentation (field borders, roads, canals, trees, greenhouses, water, crop rows)
and automatic landmark suggestion are both parts of the deferred automatic vertical: SAM /
DINOv2-seg and the saliency/ranking suggester are typed ABCs with no bodies in this build.
Their services (``semantic_service``, ``suggestion_service``) return ``501 feature:
"deferred"`` before a job is enqueued, so these tasks are not normally reached.

When re-enabled (SCOPE.md §7):

* ``segment_image_task`` — ``pending → loading_model → segmenting → vectorizing →
  persisting → done``: load the segmenter (recording any weight fallback at
  ``loading_model``), run it, vectorise masks to polygons, write ``semantic_features``.
* ``suggest_landmarks_task`` — ``pending → loading_model → detecting → ranking →
  persisting → done``: score candidate landmark locations and write ranked
  ``landmark_suggestions``.

Both keep their file, name, stage list and job type so re-enabling touches no caller. Until
then they fail the job honestly as ``FEATURE_DEFERRED`` rather than fabricate a mask or a
suggestion.
"""

from __future__ import annotations

from typing import Any

from celery import shared_task

from ai_engine.errors import NotImplementedDeferred
from app.models.enums import JobType
from app.tasks.base import BaseJobTask, job_lifecycle
from app.tasks.celery_app import TASK_SEGMENT, TASK_SUGGEST_LANDMARKS

__all__ = ["segment_image_task", "suggest_landmarks_task"]


@shared_task(bind=True, base=BaseJobTask, name=TASK_SEGMENT)
def segment_image_task(self: Any, job_id: str, **payload: Any) -> None:
    """Semantic segmentation of one image. **Deferred** — see module docstring."""
    with job_lifecycle(self, JobType.SEGMENT, job_id):
        raise NotImplementedDeferred(
            "ai_engine.semantics.segmenter",
            feature="Semantic segmentation",
        )


@shared_task(bind=True, base=BaseJobTask, name=TASK_SUGGEST_LANDMARKS)
def suggest_landmarks_task(self: Any, job_id: str, **payload: Any) -> None:
    """Automatic landmark suggestion for one image. **Deferred** — see module docstring."""
    with job_lifecycle(self, JobType.SUGGEST_LANDMARKS, job_id):
        raise NotImplementedDeferred(
            "ai_engine.landmarks.suggester",
            feature="Automatic landmark suggestions",
        )
