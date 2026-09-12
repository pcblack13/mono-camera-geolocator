"""``CeleryJobQueue`` — the :class:`~app.core.queue.JobQueue` implementation (IU-20).

``app.services`` enqueues through the ``JobQueue`` Protocol so it never imports Celery
(the same framework-free discipline that keeps services off FastAPI). This is the concrete
side, injected at the composition root (``main.py``'s lifespan for the API, the worker
bootstrap otherwise).

★ **Submit by name, never by importing the task.** ``send_task`` takes the registered task
name (``app.tasks.celery_app.JOB_TYPE_TO_TASK``), so this module does not import the task
functions and there is no import cycle between the queue (which the API loads) and the task
bodies (which pull in torch/GDAL/PIL). The name is the whole coupling.

★ **The spec is already JSON-validated** by the service (``JobSpec.validate``); we assert
it again here as the last gate before the broker, because a payload that fails *inside* the
broker client leaves an INSERTed job row that no worker will ever pick up.
"""

from __future__ import annotations

from typing import Any

from celery import Celery

from app.core.exceptions import WorkerUnavailable
from app.core.logging import get_logger
from app.core.queue import JobSpec
from app.tasks.celery_app import JOB_TYPE_TO_TASK, get_celery_app

__all__ = ["CeleryJobQueue"]

log = get_logger(__name__)


class CeleryJobQueue:
    """Submits and revokes work through a Celery broker. Satisfies ``JobQueue``
    structurally (no inheritance), so services depend only on the Protocol.

    Args:
        app: The Celery app to submit through. Defaults to the process-wide app; injectable
            for tests and alternate bootstraps.
    """

    def __init__(self, app: Celery | None = None) -> None:
        self._app = app if app is not None else get_celery_app()

    def submit(self, spec: JobSpec) -> str:
        """Enqueue ``spec`` and return the transport task id.

        The caller writes the returned id to ``celery_task_id`` on the job row (NULL
        between the INSERT and this call). The worker re-reads the row on entry and skips it
        if already terminal, which is what makes ``acks_late`` redelivery safe.

        Raises:
            WorkerUnavailable: the broker could not be reached — transient. The job row
                exists and stays ``pending`` for the stale-job reaper to fail eventually,
                rather than being silently dropped (L11/L12).
            KeyError: ``spec.job_type`` names no task. A programmer error, not a runtime
                one — every job type in ``core.constants.JOB_TYPES`` has a task.
        """
        spec.validate()
        task_name = JOB_TYPE_TO_TASK[spec.job_type]

        # ``job_id`` travels beside the payload so the task signature is
        # ``(self, job_id, **payload)`` — the job row is the worker's first read.
        kwargs: dict[str, Any] = {"job_id": str(spec.job_id), **dict(spec.payload)}

        try:
            result = self._app.send_task(
                task_name,
                kwargs=kwargs,
                queue=spec.queue,  # None ⇒ the app's task_routes decide
                priority=spec.priority,
                countdown=spec.countdown_seconds,
                headers={"idempotency_key": spec.idempotency_key}
                if spec.idempotency_key
                else None,
            )
        except Exception as exc:  # noqa: BLE001 — the broker boundary
            # kombu raises assorted transport errors (OperationalError, ConnectionError,
            # OSError). All mean the same thing to a caller: the broker is unreachable.
            log.warning(
                "queue.submit_failed",
                job_id=str(spec.job_id),
                job_type=spec.job_type,
                error=str(exc),
            )
            raise WorkerUnavailable(
                f"The job broker could not be reached, so {spec.job_type} job "
                f"{spec.job_id} could not be started. Check LE_CELERY_BROKER_URL and that a "
                f"worker is running."
            ) from exc

        log.info(
            "queue.submitted",
            job_id=str(spec.job_id),
            job_type=spec.job_type,
            task_id=result.id,
            queue=spec.queue,
        )
        return str(result.id)

    def dispatch(self, task_name: str, *args: str) -> None:
        # ``send_task`` by NAME: importing the task function here would drag worker
        # dependencies into the API process — the same seam submit() uses.
        self._app.send_task(task_name, args=list(args))

    def revoke(self, task_id: str) -> None:
        """Ask the broker to drop a not-yet-started task.

        ★ **Never ``terminate=True``** (§5.5): a hard kill of a process holding GDAL dataset
        handles and an open mosaic orphans ``*.part`` files and can wedge the CUDA context
        so the worker's *next* task fails too. A running job is cancelled cooperatively —
        the API sets ``cancel_requested`` and the worker polls it. This revoke only prevents
        a still-queued task from starting.

        Idempotent: revoking an unknown or finished task is not an error, so broker
        failures here are swallowed with a warning rather than raised — the caller's
        cancellation intent is recorded in the DB regardless.
        """
        try:
            self._app.control.revoke(task_id, terminate=False)
        except Exception as exc:  # noqa: BLE001 — revoke is best-effort and idempotent
            log.warning("queue.revoke_failed", task_id=task_id, error=str(exc))
