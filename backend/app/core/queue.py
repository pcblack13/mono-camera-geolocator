"""``JobQueue`` — the seam that lets a service enqueue without importing Celery.

CONTRACT.md §10.2 records the contradiction this module resolves: §2.4 said
``match_service`` *"enqueues"* — which needs ``.delay()`` — while §10.2's
``app.services`` row, §10.4's ``services-no-framework`` contract and §3's IU-19
import column **all forbade celery in services**. The contract said both that
services enqueue and that they cannot.

The ruling splits the two concerns rather than picking a loser, because both
instincts were right:

1. **The service owns job creation.** The ``match_jobs`` INSERT and the submit are
   one transaction-ordered unit (``celery_task_id`` is NULL between them), so one
   owner does both.
2. **Services stay framework-free** — the stronger rule, and Celery is as much a
   framework as FastAPI. So the service submits through this Protocol, whose Celery
   implementation (``app.tasks.queue.CeleryJobQueue``, IU-20) is injected at the
   composition root.

Same Protocol/implementation split as ``WindowSource``, for the same reason. It also
makes IU-18/IU-19's mocked-repo tests **honest** rather than mock-the-broker theatre:
a fake JobQueue is four lines and asserts on a value object.

★ **The spec is a plain JSON-serialisable value.** ``match_service`` builds a
``JobSpec`` carrying a provider *name*, a resolved AOI and an ``AiEngineConfig``
*dict* — never a live ``WindowSource``. A ``TileWindowSource`` holds an httpx
session; it is not broker-serialisable and cannot cross into a worker. The
composition root for CV jobs is ``app.tasks.matching`` (§10.2 ruling 3).
"""

from __future__ import annotations

import logging

import json
from dataclasses import dataclass, field
from typing import Any, Final, Mapping, Protocol, runtime_checkable
from uuid import UUID

from app.core.exceptions import WorkerUnavailable

__all__ = [
    "QUEUE_CV",
    "QUEUE_EXPORT",
    "QUEUE_IO",
    "QUEUE_NAMES",
    "JobQueue",
    "JobSpec",
    "NullJobQueue",
]


# ── Queue names ───────────────────────────────────────────────────────────────
#
# Three queues, because the three workloads have incompatible shapes and sharing one
# queue makes each of them the other's tail latency:
#
#   cv     — SIFT/matching. CPU-saturating, minutes long. Concurrency stays LOW
#            (LE_CELERY_WORKER_CONCURRENCY=2) precisely because each task wants a
#            whole core.
#   io     — tile fetch, ingest, thumbnails. Network/disk-bound, seconds long. Can
#            run wide.
#   export — rendering. Bursty, and a surveyor is watching a spinner for it.
#
# The names are declared here, next to JobSpec.queue, so IU-19 (which sets them) and
# IU-20 (which declares the Celery queues and routes) read the same constants rather
# than two string literals that agree today.

QUEUE_CV: Final = "cv"
QUEUE_IO: Final = "io"
QUEUE_EXPORT: Final = "export"

QUEUE_NAMES: Final[tuple[str, ...]] = (QUEUE_CV, QUEUE_IO, QUEUE_EXPORT)


@dataclass(frozen=True, slots=True)
class JobSpec:
    """A broker-crossable description of work to be done.

    Frozen, because a spec that is mutated after submission describes something other
    than what was submitted.

    Attributes:
        job_id: The row already INSERTed by the service. The worker re-reads this row
            on entry and returns immediately if it is terminal — that task-level
            guard is not optional: it is what makes ``acks_late`` redelivery safe
            (§12 C-27).
        job_type: One of ``core.constants.JOB_TYPES``. A ``JobType`` enum member is
            accepted and normalised to its value, since ``core`` cannot import the
            enum (see ``core.constants``).
        payload: Task arguments. **Must be JSON-serialisable** — see ``validate()``.
        queue: One of ``QUEUE_NAMES``, or None to let the implementation's routing
            decide.
        priority: Broker priority, if the transport supports it. None = default.
        countdown_seconds: Delay before the task becomes eligible to run.
        idempotency_key: The client's ``Idempotency-Key``, propagated so the worker
            can correlate a redelivery with the original request.
    """

    job_id: UUID
    job_type: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    queue: str | None = None
    priority: int | None = None
    countdown_seconds: float | None = None
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        # Normalise a JobType enum member to its value. `core` may not import the
        # enum (it is declared in IU-16/IU-17, both of which depend on core), so this
        # accepts either and stores the wire value.
        value = getattr(self.job_type, "value", self.job_type)
        if not isinstance(value, str) or not value:
            raise ValueError(f"job_type must be a non-empty string, got {self.job_type!r}")
        object.__setattr__(self, "job_type", value)

        if self.queue is not None and self.queue not in QUEUE_NAMES:
            raise ValueError(f"queue must be one of {QUEUE_NAMES}, got {self.queue!r}")

    def validate(self) -> None:
        """Assert the payload actually survives the broker.

        Called by implementations before submitting. Celery serialises with JSON, and
        a payload holding a UUID, a Path, a numpy scalar or a live session fails
        *inside* the broker client — by which point the job row is already INSERTed
        and the job is a `pending` that no worker will ever pick up. Failing here
        instead means the service's transaction can roll back cleanly.

        Raises:
            TypeError: if ``payload`` is not JSON-serialisable.
        """
        try:
            json.dumps(self.payload, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise TypeError(
                f"JobSpec.payload for job {self.job_id} is not JSON-serialisable "
                f"and cannot cross the broker: {exc}"
            ) from exc


_log = logging.getLogger("app.core.queue")


@runtime_checkable
class JobQueue(Protocol):
    """Submits work to a broker. The only enqueue vocabulary ``app.services`` knows.

    Structural: ``CeleryJobQueue`` satisfies this without inheriting from it. Services
    depend on this Protocol; the concrete implementation is injected at the
    composition root (``main.py``'s lifespan, or the worker bootstrap).
    """

    def submit(self, spec: JobSpec) -> str:
        """Enqueue ``spec`` and return the transport's task id.

        The caller writes the returned id to ``celery_task_id`` on the job row, which
        is NULL between the INSERT and this call.

        Raises:
            WorkerUnavailable: the broker could not be reached. Transient: the job row
                exists and stays ``pending``, so the stale-job reaper
                (``LE_JOB_STALE_AFTER_SECONDS``) will eventually mark it ``failed``
                rather than leaving it to sit forever.
        """
        ...

    def dispatch(self, task_name: str, *args: str) -> None:
        """Fire-and-forget: enqueue a task that has NO job row.

        ★ For enhancements, not work products. ``submit`` is for jobs the user
        watches (a row, a status, a spinner); ``dispatch`` is for background
        derivations whose absence degrades the experience rather than breaking it
        (the video preview transcode). Callers poll for the ARTEFACT, never for the
        task — so there is nothing to track and failure must be survivable.
        """
        ...

    def revoke(self, task_id: str) -> None:
        """Ask the broker to drop a not-yet-started task.

        ★ There is no ``terminate`` parameter, and its absence is the design.
        ``revoke(terminate=True)`` is **never** used: a hard kill of a process holding
        GDAL dataset handles and an open mosaic orphans ``*.part`` files and, with
        torch, can wedge the CUDA context so the worker's *next* task fails too. A
        running job is cancelled cooperatively instead — ``cancel_requested`` is set,
        the worker polls it at every stage boundary and inside the tile-fetch loop,
        and a 1-second window is worth avoiding an entire class of corruption.

        Idempotent: revoking an unknown or already-finished task is not an error.
        """
        ...


class NullJobQueue:
    """The honest default when no broker is configured: refuse, loudly.

    Injected only when nothing else has been. It satisfies ``JobQueue`` structurally
    so the composition root always has *something* to inject, and it raises rather
    than silently dropping work — a queue that accepts a job and discards it produces
    a row stuck at ``pending`` forever and a surveyor watching a spinner that will
    never resolve, which is precisely the failure mode L11 and L12 exist to forbid.

    Not a test double. Tests that need to assert on submissions should use their own
    recording fake; this one is production code and its job is to fail correctly.
    """

    def submit(self, spec: JobSpec) -> str:
        raise WorkerUnavailable(
            f"No job queue is configured, so {spec.job_type} job {spec.job_id} cannot be "
            f"started. Check that the Celery broker (LE_CELERY_BROKER_URL) is reachable "
            f"and that a worker is running."
        )

    def dispatch(self, task_name: str, *args: str) -> None:
        # ★ Deliberately SOFTER than submit's refusal: a dispatch has no job row to
        #   strand and every caller has a working fallback (the player scrubs via
        #   server frames until a preview exists). Failing the upload because an
        #   optional derivation cannot start would invert the feature's value.
        _log.warning("no queue configured; dropping dispatch of %s%r", task_name, args)

    def revoke(self, task_id: str) -> None:
        # Deliberately a no-op, not a raise: nothing was ever submitted, so there is
        # nothing to revoke, and the caller's cancellation has already succeeded by
        # virtue of the work never existing. Revoke is idempotent by contract.
        return None
