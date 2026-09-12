"""``recompute_gcps_task`` — re-derive a GCP set (§5.5 ``gcp_recompute`` stages).

The ``gcp_recompute`` job has two modes, and in this build both resolve to *deferred*:

* **refit** — re-estimate the homography from the current anchor set and re-derive every
  GCP from it. Needs the RANSAC homography estimator, which is a typed ABC only
  (SCOPE.md §4).
* **rederive** — re-apply the *existing* transform to the stored image pixels. For an
  automatically-matched image that transform is the (deferred) homography; for the
  GeoTIFF short-circuit it is the file's geotransform, which needs no matching — but a
  manual GCP's coordinate is a **direct observation** (SCOPE.md §5), not something derived
  from a transform, so there is nothing to recompute for the rows this build actually
  creates, and no non-adjustment GCP-geometry writer exists to persist a system
  re-derivation without mislabelling it as a manual adjustment.

Consequently ``gcp_service.recompute`` (endpoint 42) returns ``501 feature: "deferred"``
*before a job is enqueued*, exactly like the other automatic paths, so this task is not
normally reached. It keeps its file, name, stage list and job type so that re-enabling the
automatic engine is a zero-caller change (SCOPE.md §7): implement the estimator in
``ai_engine`` and a system-rederive writer in ``GcpRepository``, flip the service from 501
to enqueue, and fill the body below (``pending → refitting_homography → deriving_gcps →
persisting → done``). Until then it fails the job honestly rather than fabricate a
coordinate.
"""

from __future__ import annotations

from typing import Any

from celery import shared_task

from ai_engine.errors import NotImplementedDeferred
from app.models.enums import JobType
from app.tasks.base import BaseJobTask, job_lifecycle
from app.tasks.celery_app import TASK_RECOMPUTE_GCPS

__all__ = ["recompute_gcps_task"]


@shared_task(bind=True, base=BaseJobTask, name=TASK_RECOMPUTE_GCPS)
def recompute_gcps_task(self: Any, job_id: str, **payload: Any) -> None:
    """Recompute an image's GCPs. **Deferred** — see module docstring."""
    with job_lifecycle(self, JobType.GCP_RECOMPUTE, job_id):
        raise NotImplementedDeferred(
            "ai_engine.geometry.homography",
            feature="GCP recompute (homography refit / re-derivation)",
        )
