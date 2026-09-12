"""``BaseJobTask`` — the worker-side job lifecycle: transitions, retry policy, error map.

This module owns the **single place retry semantics are decided** (CONTRACT.md §6.3):
the mapping from a package exception (``gis.errors`` / ``ai_engine.errors`` / a
``core.exceptions`` dependency failure) to *(error code, retry?)*. ``ai_engine`` and
``gis`` never import Celery, so the classification cannot live in them; it lives here,
once, and every task routes its failures through :func:`job_lifecycle`.

The lifecycle is a context manager, not a base-class ``run`` override, because a task's
*work* is task-specific but its *bookkeeping* is not::

    @shared_task(bind=True, base=BaseJobTask, name=TASK_INGEST)
    def ingest_image_task(self, job_id, image_id):
        with job_lifecycle(self, JobType.INGEST, job_id) as ctx:
            ...              # do the work; call ctx.progress(...)
            ctx.set_result(width=w, height=h)   # extra columns for mark_succeeded

On a clean exit the job is marked ``succeeded`` (with any ``set_result`` extras). On
:class:`JobCancelled` it is marked ``cancelled``. On any other exception it is classified:
transient failures ``retry`` with jittered backoff until the DB budget is spent, then
``failed``; terminal failures go straight to ``failed`` with a stable ``error_code`` and a
scrubbed message (the traceback is stored, never serialised — §5.5).

★ **The task-entry terminal guard** (§12 C-27): the lifecycle re-reads the job row on
entry and returns immediately if it is already terminal. That is what makes ``acks_late``
redelivery safe — a job that succeeded before the ack was lost is not run twice.
"""

from __future__ import annotations

import asyncio
import random
import traceback
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Final, Iterator, TypeVar

from celery import Task
from celery.exceptions import Ignore, Retry, SoftTimeLimitExceeded

from ai_engine.errors import (
    ComponentUnavailable,
    NotImplementedDeferred,
    WeightsCorrupt,
    WeightsMissing,
)
from gis.errors import (
    AreaTooLargeError,
    OutOfCoverage,
    ProviderNotConfiguredError,
    ProviderRateLimitError,
    ProviderTransportError,
    RasterBackendUnavailable,
    TileNotAvailableError,
    TileOutOfRangeError,
)

from app.core.exceptions import DatabaseUnavailable, RedisUnavailable
from app.core.logging import get_logger
from app.db.repositories.jobs import JOB_MODEL_BY_TYPE, SyncJobRepository
from app.db.session import sync_session
from app.models.base import Base

__all__ = [
    "BaseJobTask",
    "JobCancelled",
    "JobContext",
    "classify_failure",
    "job_lifecycle",
    "run_async",
]

log = get_logger(__name__)

_T = TypeVar("_T")

#: Backoff cap: ``min(2**attempt * 5, RETRY_MAX_BACKOFF_S)`` (§5.5). Two minutes is long
#: enough to ride out a database restart or a rate-limit window, short enough that a
#: surveyor's job is not parked for an unreasonable time.
RETRY_BASE_S: Final = 5.0
RETRY_MAX_BACKOFF_S: Final = 120.0


class JobCancelled(Exception):
    """Cooperative cancellation. Raised by the progress reporter's cancel poll when
    ``cancel_requested`` flips (§5.5). Terminal, never retried; the lifecycle marks the
    job ``cancelled`` rather than ``failed``.

    ★ Distinct from ``asyncio.CancelledError`` and from a hard ``revoke(terminate=True)``,
    which is **never** used — a hard kill of a process holding GDAL handles orphans
    ``*.part`` files. Cancellation is always a raised, catchable signal at a stage
    boundary.
    """


@dataclass(frozen=True, slots=True)
class FailureClass:
    """How :func:`classify_failure` graded an exception."""

    code: str
    retry: bool
    #: When set, use this as the retry countdown (an upstream ``Retry-After``) instead of
    #: the exponential backoff, and do **not** count the attempt against the budget.
    retry_after_s: float | None = None


def classify_failure(exc: BaseException) -> FailureClass:
    """Map a package exception to *(error code, retry?)* — the §6.3 table, verbatim.

    The ``retry`` flag is deliberately conservative: only genuinely *transient* failures
    (a flaky upstream, a rate limit, a database blip) retry. A validation error, a
    deferred feature, a wrong provider key or "no coverage" retries to the identical
    outcome and is graded terminal.
    """
    # ── transient — worth another attempt ─────────────────────────────────────
    if isinstance(exc, ProviderRateLimitError):
        retry_after = getattr(exc, "retry_after", None)
        return FailureClass(
            "PROVIDER_RATE_LIMITED",
            retry=True,
            retry_after_s=float(retry_after) if retry_after else None,
        )
    if isinstance(exc, ProviderTransportError):
        return FailureClass("PROVIDER_UPSTREAM_ERROR", retry=True)
    if isinstance(exc, (DatabaseUnavailable, RedisUnavailable)):
        return FailureClass(exc.code, retry=True)

    # ── terminal — a retry cannot change the answer ───────────────────────────
    if isinstance(exc, ProviderNotConfiguredError):
        return FailureClass("PROVIDER_NOT_CONFIGURED", retry=False)
    if isinstance(exc, OutOfCoverage):
        return FailureClass("OUT_OF_COVERAGE", retry=False)
    if isinstance(exc, AreaTooLargeError):
        return FailureClass("SEARCH_AREA_TOO_LARGE", retry=False)
    if isinstance(exc, NotImplementedDeferred):
        # A deferred feature that somehow reached a worker (all deferred endpoints 501 at
        # the API before enqueue). Fail honestly as deferred rather than as a 500.
        return FailureClass("FEATURE_DEFERRED", retry=False)
    if isinstance(exc, SoftTimeLimitExceeded):
        # Retrying a too-slow job just repeats the timeout (§5.5).
        return FailureClass("TIMEOUT", retry=False)
    if isinstance(
        exc,
        (
            TileOutOfRangeError,
            TileNotAvailableError,
            RasterBackendUnavailable,
            ComponentUnavailable,
            WeightsMissing,
            WeightsCorrupt,
        ),
    ):
        # Caller bugs and configuration failures. ``WeightsMissing``/``WeightsCorrupt``
        # are "not an error" on the default path (they warn + fall back inside the
        # pipeline); reaching a task boundary means the pipeline could not recover, which
        # is a genuine internal failure.
        return FailureClass("INTERNAL_ERROR", retry=False)

    return FailureClass("INTERNAL_ERROR", retry=False)


def run_async(coro_factory: Callable[[], Awaitable[_T]]) -> _T:
    """Run one async coroutine to completion from inside a synchronous worker task.

    The domain repositories (images, gcps, exports, batches) are ``async`` — they are the
    single home of ``select()`` — while a Celery prefork worker is synchronous. There is
    no event loop running in a prefork child, so a fresh :func:`asyncio.run` per call is
    safe here (the hazard ``db.session`` warns about is a loop that is *already* running,
    which only the API has).

    ★ The job **state machine** never comes through here: it uses the synchronous
    :class:`~app.db.repositories.jobs.SyncJobRepository` on its own committed transactions,
    because progress writes must not sit inside a long domain transaction (§5.9). This
    bridge is only for the one-shot domain read/write a real task needs.

    Args:
        coro_factory: A zero-arg callable returning the coroutine. A factory rather than a
            coroutine so the coroutine is created *inside* the new loop.
    """
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is None:
        return asyncio.run(coro_factory())

    # A loop is already running (``task_always_eager`` under pytest-asyncio, say):
    # ``asyncio.run`` would raise. Run the coroutine on its own loop in a worker thread so
    # the bridge stays usable in every runtime.
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(coro_factory())).result()


@dataclass(slots=True)
class JobContext:
    """The handle a task body uses inside :func:`job_lifecycle`.

    Carries the concrete job model and id, exposes the progress reporter, and collects the
    extra columns that :meth:`SyncJobRepository.mark_succeeded` writes on success.
    """

    task: Task
    model: type[Base]
    job_id: uuid.UUID
    job_type: str
    _result_extra: dict[str, Any] = field(default_factory=dict)
    _progress: Any = None

    @property
    def progress(self) -> Any:
        """The :class:`~app.tasks.progress.ProgressReporter` for this job (lazy)."""
        if self._progress is None:
            # Imported here, not at module scope, to keep the worker↔progress edge acyclic
            # and to avoid loading the constants table for tasks that report no progress.
            from app.tasks.progress import ProgressReporter

            self._progress = ProgressReporter(
                task=self.task,
                model=self.model,
                job_id=self.job_id,
                job_type=self.job_type,
            )
        return self._progress

    def set_result(self, **extra: Any) -> None:
        """Accumulate columns to write when the job is marked ``succeeded``.

        Pruned to the model's real columns by the repository, so passing a field a given
        job table does not have is harmless.
        """
        self._result_extra.update(extra)

    def check_cancelled(self) -> None:
        """Raise :class:`JobCancelled` if cancellation was requested. Call at stage
        boundaries and inside long loops."""
        self.progress.check_cancelled()


@contextmanager
def job_lifecycle(task: Task, job_type: Any, job_id: str | uuid.UUID) -> Iterator[JobContext]:
    """Drive one job through running → (succeeded | failed | cancelled | retrying).

    Args:
        task: The bound Celery task (``bind=True``), for ``self.retry`` and the attempt
            counter.
        job_type: A ``JobType`` enum member or its wire value.
        job_id: The job row id, as passed in the task payload.

    Yields:
        A :class:`JobContext`. The body does its work and may call ``ctx.progress`` /
        ``ctx.set_result``.
    """
    jid = job_id if isinstance(job_id, uuid.UUID) else uuid.UUID(str(job_id))
    type_value = str(getattr(job_type, "value", job_type))
    model = JOB_MODEL_BY_TYPE[type_value]

    # ── entry: the terminal guard + running transition ────────────────────────
    #
    # ★ These early exits ``raise Ignore()`` rather than ``return``: a @contextmanager that
    # returns before it yields raises RuntimeError in the ``with`` statement. Ignore
    # propagates cleanly out of ``with job_lifecycle(...)``, the task body never runs, and
    # Celery acks the message without recording a failure — exactly the "nothing to do"
    # semantics these cases want.
    # ★ Each transition is its own committed session: raising ``Ignore`` while still inside
    # a ``sync_session()`` would roll the transition back (the context manager rolls back on
    # exception), so a ``mark_cancelled`` must commit *before* the raise, not with it.
    with sync_session() as db:
        view = SyncJobRepository(db).get_view(jid)

    if view is None:
        log.warning("task.job_missing", job_id=str(jid), job_type=type_value)
        # The row was deleted (retention) between submit and pickup. Ack and move on.
        raise Ignore()
    if view.is_terminal:
        log.info(
            "task.redelivery_ignored",
            job_id=str(jid),
            job_type=type_value,
            status=view.status.value,
        )
        raise Ignore()
    if view.cancel_requested:
        with sync_session() as db:
            SyncJobRepository(db).mark_cancelled(model, jid)
        log.info("task.cancelled_before_start", job_id=str(jid), job_type=type_value)
        raise Ignore()

    with sync_session() as db:
        SyncJobRepository(db).mark_running(model, jid)

    ctx = JobContext(task=task, model=model, job_id=jid, job_type=type_value)
    log.info("task.started", job_id=str(jid), job_type=type_value)

    try:
        yield ctx
    except JobCancelled:
        with sync_session() as db:
            SyncJobRepository(db).mark_cancelled(model, jid)
        log.info("task.cancelled", job_id=str(jid), job_type=type_value)
        raise Ignore() from None
    except Retry:
        # A nested ``self.retry`` already scheduled the redelivery — let it propagate.
        raise
    except (Exception, SoftTimeLimitExceeded) as exc:  # noqa: BLE001 — the boundary
        fc = classify_failure(exc)
        tb = traceback.format_exc()
        log.warning(
            "task.failed",
            job_id=str(jid),
            job_type=type_value,
            error_code=fc.code,
            error_type=type(exc).__name__,
            retry=fc.retry,
        )
        if fc.retry:
            countdown = _backoff(task, fc)
            if fc.retry_after_s is not None:
                # Rate limit: honour the upstream's window and do NOT spend the attempt
                # budget (§6.3). Status stays ``running``; the redelivery re-marks it.
                raise task.retry(exc=exc, countdown=countdown, max_retries=None)
            with sync_session() as db:
                moved = SyncJobRepository(db).mark_retrying(model, jid, reason=str(exc))
            if moved:
                raise task.retry(exc=exc, countdown=countdown, max_retries=None)
            # Budget spent — fall through to a terminal failure.
        with sync_session() as db:
            SyncJobRepository(db).mark_failed(
                model,
                jid,
                error_message=_scrub(exc, fc),
                error_type=type(exc).__name__,
                error_traceback=tb,
            )
        raise Ignore() from None

    # ── clean exit: succeed ───────────────────────────────────────────────────
    with sync_session() as db:
        SyncJobRepository(db).mark_succeeded(model, jid, **ctx._result_extra)
    log.info("task.succeeded", job_id=str(jid), job_type=type_value)


def _backoff(task: Task, fc: FailureClass) -> float:
    """Retry delay in seconds. Upstream ``Retry-After`` wins; otherwise exponential with
    full jitter (``random.uniform(0, cap)``) so a fleet does not retry in lockstep."""
    if fc.retry_after_s is not None:
        return max(0.0, fc.retry_after_s)
    attempt = int(getattr(getattr(task, "request", None), "retries", 0) or 0)
    cap = min(RETRY_BASE_S * (2**attempt), RETRY_MAX_BACKOFF_S)
    return random.uniform(0.0, cap)


def _scrub(exc: BaseException, fc: FailureClass) -> str:
    """The message written to ``error_message`` and shown to the client.

    For a classified, non-internal failure the exception text is a domain message safe to
    show (e.g. "provider X is not configured"). For ``INTERNAL_ERROR`` it is generic — a
    traceback string can carry storage paths and connection strings, and it is stored in
    ``error_traceback`` (never serialised) for operators instead.
    """
    if fc.code == "INTERNAL_ERROR":
        return "The job failed due to an internal error."
    text = str(exc).strip()
    return text or fc.code


class BaseJobTask(Task):
    """Celery ``Task`` base for every LandExplorer job task.

    Kept intentionally thin: the lifecycle lives in :func:`job_lifecycle` (a context
    manager the body opts into) rather than in ``run``/``on_failure`` overrides, because a
    global ``on_failure`` cannot see the job id without re-parsing args and would fight the
    explicit state machine. This base only pins the retry ceiling and disables Celery's own
    result-state bookkeeping for failures we handle ourselves.

    ``acks_late`` and ``reject_on_worker_lost`` are set on the app, not here, so they apply
    uniformly and are visible in one place.
    """

    #: A hard ceiling independent of the per-job DB budget, so a misconfigured
    #: ``max_attempts`` cannot produce an unbounded retry storm. The DB budget
    #: (``mark_retrying`` returning False) is the real limiter and is usually smaller.
    max_retries = 10
    #: We write terminal state to the DB and raise ``Ignore``; Celery need not also store a
    #: FAILURE result for jobs whose truth lives in Postgres.
    ignore_result = True
