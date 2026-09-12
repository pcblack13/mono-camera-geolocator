"""``v_jobs`` reads and ★ **atomic job state transitions**.

**This module is `v_jobs`'s only reader** (§5.5) and the only writer of a job's status.

★★ **Every transition is a compare-and-set, and that is the whole design.** A job is
driven by three parties at once — the API (cancel), the worker (running → succeeded),
and the beat reaper (stale → failed) — with no lock between them. So a transition is
never "read the status, decide, write the status": it is one statement whose ``WHERE``
carries the expected state.

    UPDATE match_jobs SET status = 'succeeded', finished_at = now()
     WHERE id = :id AND status IN ('pending','queued','running','retrying')

**Exactly one concurrent caller matches a row; every other one matches nothing, updates
nothing, and returns False.** No exception, no retry, no lost update — the loser
*no-ops*, which is exactly what the test contract asserts. The read-then-write version of
the same code silently lets a cancel overwrite a success, and the surveyor's completed
job disappears.

The terminal set is excluded from the ``WHERE`` of every terminal transition, so **a
finished job can never be moved again**. That single property is what makes the
cancel-versus-succeed race safe without a lock.

★ **Four tables, one state machine.** ``match_jobs``, ``aux_jobs``, ``batch_jobs`` and
``exports`` do **not** share a column set — ``batch_jobs`` and ``exports`` have no
``error_type`` or ``error_traceback``, ``batch_jobs`` uses ``celery_group_id`` where the
others use ``celery_task_id``, and only ``match_jobs`` has tile counters. Rather than
four drifting copies of one state machine, the writes here are built against whichever
columns the target model actually declares (:func:`_prune`). The alternative — a common
base table — was rejected in §5.5 for good reasons; this is the cost of that, paid once,
here.

★ **Sync and async, deliberately.** The API polls jobs over an ``AsyncSession``; the
Celery worker drives the state machine over a sync one, because prefork workers are not
async and ``session.py`` is explicit that an asyncio loop per task is how a task hangs.
:class:`SyncJobRepository` is what ``tasks/base.py`` and ``tasks/progress.py`` use. Both
classes call the *same* statement builders, so there is one definition of each
transition and only the ``await`` differs.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Mapping, Sequence

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Double,
    Integer,
    MetaData,
    Select,
    Table,
    Text,
    Update,
    case,
    cast,
    extract,
    func,
    inspect,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.constants import TERMINAL_JOB_STATUSES
from app.core.exceptions import JobNotFound
from app.core.pagination import PaginationParams, SortParams
from app.db.repositories.base import (
    BaseRepository,
    SortableColumns,
    apply_pagination,
    apply_sort,
    count_stmt_of,
    csv_enum_filter,
)
from app.db.session import raise_if_unavailable
from app.models.base import Base
from app.models.enums import JobStatus, JobType, pg_enum
from app.models.export import Export
from app.models.image import Image
from app.models.job import AuxJob, BatchJob, MatchJob

__all__ = [
    "JOB_MODEL_BY_TYPE",
    "LIVE_JOB_STATUSES",
    "JobRepository",
    "JobView",
    "SyncJobRepository",
    "v_jobs",
]

#: The four non-terminal states. **Derived** from the enum minus the terminal set rather
#: than typed out: a fifth live status added to ``job_status`` must not silently become
#: un-cancellable because a hand-written tuple here forgot it.
LIVE_JOB_STATUSES: Final[frozenset[str]] = (
    frozenset(member.value for member in JobStatus) - TERMINAL_JOB_STATUSES
)

#: ``job_type`` → the table that actually stores it. ``match``/``batch``/``export`` each
#: have their own table because each has its own columns; the four aux types share one
#: shape exactly and share ``aux_jobs`` (§12 C-19).
JOB_MODEL_BY_TYPE: Final[Mapping[str, type[Base]]] = {
    JobType.MATCH.value: MatchJob,
    JobType.BATCH.value: BatchJob,
    JobType.EXPORT.value: Export,
    JobType.SEGMENT.value: AuxJob,
    JobType.SUGGEST_LANDMARKS.value: AuxJob,
    JobType.GCP_RECOMPUTE.value: AuxJob,
    JobType.INGEST.value: AuxJob,
}

# ─────────────────────────────────────────────────────────────────────────────
# v_jobs
# ─────────────────────────────────────────────────────────────────────────────

#: ★ A **private** MetaData, and this is load-bearing. ``v_jobs`` is a VIEW created by
#: migration ``0009``; binding it to ``Base.metadata`` would put it in the collection
#: Alembic autogenerates against, and autogenerate would see a "table" with no model —
#: or worse, a model with no table — and propose ``CREATE TABLE v_jobs`` /
#: ``DROP TABLE v_jobs`` on the next migration. A view is not a table and must not live
#: in the table registry.
_VIEW_METADATA: Final = MetaData()

#: The view's column list, in the exact order of §5.5's ``SELECT``. Typed rather than
#: declared with bare ``column()`` so the driver's results are coerced the same way the
#: ORM coerces them: ``job_status`` arrives as :class:`JobStatus`, ``warnings`` as a
#: list, ``id`` as a :class:`uuid.UUID`. An untyped view would hand a service raw
#: strings where ``JobRead`` expects enums.
v_jobs: Final = Table(
    "v_jobs",
    _VIEW_METADATA,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("type", pg_enum(JobType, "job_type")),
    Column("status", pg_enum(JobStatus, "job_status")),
    Column("image_id", PGUUID(as_uuid=True)),
    Column("project_id", PGUUID(as_uuid=True)),
    Column("batch_id", PGUUID(as_uuid=True)),
    Column("cancel_requested", Boolean),
    Column("attempt", Integer),
    Column("max_attempts", Integer),
    Column("progress", Double),
    Column("progress_stage", Text),
    Column("progress_message", Text),
    Column("tiles_fetched", Integer),
    Column("tiles_total", Integer),
    Column("candidates_evaluated", Integer),
    Column("degraded", Boolean),
    Column("degradation_reason", Text),
    Column("warnings", JSONB),
    Column("error_type", Text),
    Column("error_message", Text),
    Column("queued_at", DateTime(timezone=True)),
    Column("started_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
    Column("duration_ms", Integer),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)


@dataclass(frozen=True, slots=True)
class JobView:
    """★ A read-model over ``v_jobs``, **not an ORM entity**.

    The view is a ``UNION ALL`` of four tables: it is not updatable, and no row of it is
    a row of any table. Making it an ORM class would invite ``session.add(job_view)`` and
    a runtime error at flush; a frozen dataclass cannot be mistaken for something you can
    save. Writes go to the concrete model — that is what
    :data:`JOB_MODEL_BY_TYPE` is for.

    Field-for-field the §5.5 column list, so ``JobRead.model_validate(job_view)``
    succeeds by construction. ``JobProgress`` is assembled from
    ``progress``/``progress_stage``/``progress_message``/``tiles_*``/
    ``candidates_evaluated`` by the service — this layer does not reshape, it reads.
    """

    id: uuid.UUID
    type: JobType
    status: JobStatus
    image_id: uuid.UUID | None
    project_id: uuid.UUID | None
    batch_id: uuid.UUID | None
    cancel_requested: bool
    attempt: int
    max_attempts: int
    #: ★ **0–1 in the DB**; ``JobProgress.percent`` is 0–100 on the wire. The conversion
    #: is the service's, and it is the only place it happens.
    progress: float
    progress_stage: str
    progress_message: str | None
    tiles_fetched: int | None
    tiles_total: int | None
    candidates_evaluated: int | None
    degraded: bool
    degradation_reason: str | None
    warnings: list[dict[str, Any]]
    error_type: str | None
    error_message: str | None
    queued_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    created_at: datetime
    updated_at: datetime

    @property
    def is_terminal(self) -> bool:
        """Whether polling should stop. ``Retry-After``'s absence is derived from this."""
        return self.status.value in TERMINAL_JOB_STATUSES

    @property
    def model(self) -> type[Base]:
        """The concrete table this view row came from — the one a write must target."""
        return JOB_MODEL_BY_TYPE[self.type.value]


def _to_view(row: Any) -> JobView:
    """Row → :class:`JobView`.

    Splatted rather than field-by-field on purpose: if the view and the dataclass ever
    drift, this raises ``TypeError`` naming the offending field on the first call, which
    is a far better failure than a silently dropped column that the wire model then
    reports as null.
    """
    return JobView(**dict(row._mapping))


# ─────────────────────────────────────────────────────────────────────────────
# Statement builders — shared verbatim by the async and sync repositories
# ─────────────────────────────────────────────────────────────────────────────


def _known(model: type[Base]) -> frozenset[str]:
    return frozenset(inspect(model).columns.keys())


def _prune(model: type[Base], values: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only what ``model`` has a column for. See the module docstring."""
    columns = _known(model)
    return {k: v for k, v in values.items() if k in columns}


def _duration_ms(model: type[Base]) -> Any:
    """``(now() - started_at)`` in whole milliseconds, or NULL when never started.

    ★ Computed **in SQL**, against the same ``now()`` that sets ``finished_at``. In
    PostgreSQL ``now()`` is the transaction timestamp, so the duration and the finish
    time are consistent by construction. Computing it in Python would measure the
    worker's clock against the database's — and a worker whose clock is 40 ms off would
    report a negative duration on a fast job.
    """
    started = model.started_at  # type: ignore[attr-defined]
    return case(
        (started.is_(None), None),
        else_=cast(func.round(extract("epoch", func.now() - started) * 1000), Integer),
    )


def _transition(
    model: type[Base],
    job_id: uuid.UUID,
    *,
    to_status: JobStatus,
    from_statuses: frozenset[str],
    values: Mapping[str, Any] | None = None,
    extra_where: Sequence[Any] = (),
) -> Update:
    """★ The compare-and-set. Every status change in this module is built here.

    Args:
        model: The concrete job table.
        job_id: The row.
        to_status: The state to move to.
        from_statuses: The states the caller believes the row is in. **This is the
            compare half**; it goes in the ``WHERE``, not in an ``if``.
        values: Extra columns to set. Pruned to what ``model`` actually has.
        extra_where: Further guards — e.g. ``attempt < max_attempts``.

    Returns:
        An ``UPDATE ... RETURNING id``. ``scalar_one_or_none() is None`` ⇒ this caller
        lost the race (or the row is gone), and **must treat that as a no-op, not an
        error**.
    """
    status_col = model.status  # type: ignore[attr-defined]
    id_col = model.id  # type: ignore[attr-defined]
    payload = {"status": to_status, **_prune(model, values or {})}
    return (
        update(model)
        .where(id_col == job_id, status_col.in_(sorted(from_statuses)), *extra_where)
        .values(**payload)
        .returning(id_col)
    )


def _task_id_column(model: type[Base]) -> str | None:
    """Which column carries the broker's handle for this table.

    ``batch_jobs`` tracks a Celery **group**, not a task, and names its column
    accordingly. One writer, two column names, and neither is optional: without it the
    ``uq_*_celery_task_id`` uniqueness that de-duplicates a double submit has nothing to
    key on.
    """
    columns = _known(model)
    if "celery_task_id" in columns:
        return "celery_task_id"
    if "celery_group_id" in columns:
        return "celery_group_id"
    return None  # pragma: no cover — all four tables have one.


def _queued_stmt(model: type[Base], job_id: uuid.UUID, task_id: str | None) -> Update:
    values: dict[str, Any] = {"queued_at": func.now()}
    column = _task_id_column(model)
    if column is not None and task_id is not None:
        values[column] = task_id
    return _transition(
        model,
        job_id,
        to_status=JobStatus.QUEUED,
        from_statuses=frozenset({JobStatus.PENDING.value}),
        values=values,
    )


def _running_stmt(model: type[Base], job_id: uuid.UUID) -> Update:
    started = model.started_at  # type: ignore[attr-defined]
    return _transition(
        model,
        job_id,
        to_status=JobStatus.RUNNING,
        from_statuses=frozenset(
            {JobStatus.PENDING.value, JobStatus.QUEUED.value, JobStatus.RETRYING.value}
        ),
        # ★ COALESCE, so a retry does not erase the first start. `duration_ms` then
        #   measures the whole job including its retries — which is what the person
        #   watching the progress bar is actually experiencing.
        values={"started_at": func.coalesce(started, func.now())},
    )


def _succeeded_stmt(model: type[Base], job_id: uuid.UUID, extra: Mapping[str, Any]) -> Update:
    return _transition(
        model,
        job_id,
        to_status=JobStatus.SUCCEEDED,
        # Any live state, not just `running`: a task that finishes before its first
        # progress tick never passed through `running`, and refusing to record its
        # success would strand it live forever.
        from_statuses=LIVE_JOB_STATUSES,
        values={
            "finished_at": func.now(),
            "duration_ms": _duration_ms(model),
            "progress": 1.0,
            "progress_message": None,
            **extra,
        },
    )


def _failed_stmt(
    model: type[Base],
    job_id: uuid.UUID,
    *,
    error_type: str | None,
    error_message: str,
    error_traceback: str | None,
) -> Update:
    return _transition(
        model,
        job_id,
        to_status=JobStatus.FAILED,
        from_statuses=LIVE_JOB_STATUSES,
        values={
            "finished_at": func.now(),
            "duration_ms": _duration_ms(model),
            "error_type": error_type,
            "error_message": error_message,
            # ★ Stored server-side only, NEVER serialised (§5.6). It is on the row so an
            #   operator can read it; `JobRead` has no field for it.
            "error_traceback": error_traceback,
        },
    )


def _cancelled_stmt(model: type[Base], job_id: uuid.UUID) -> Update:
    return _transition(
        model,
        job_id,
        to_status=JobStatus.CANCELLED,
        from_statuses=LIVE_JOB_STATUSES,
        values={"finished_at": func.now(), "duration_ms": _duration_ms(model)},
    )


def _retrying_stmt(model: type[Base], job_id: uuid.UUID, reason: str | None) -> Update:
    attempt = model.attempt  # type: ignore[attr-defined]
    max_attempts = model.max_attempts  # type: ignore[attr-defined]
    return _transition(
        model,
        job_id,
        to_status=JobStatus.RETRYING,
        from_statuses=frozenset({JobStatus.RUNNING.value, JobStatus.QUEUED.value}),
        values={"attempt": attempt + 1, "error_message": reason},
        # ★ The budget check is a WHERE clause, not an `if`. It enforces
        #   `ck_*_attempt (attempt <= max_attempts)` at the same instant it reads it, so
        #   two workers retrying the same job cannot both pass the check and then both
        #   increment past the ceiling — the second one matches no row and gets False,
        #   which the caller reads as "budget exhausted, fail it".
        extra_where=(attempt < max_attempts,),
    )


def _request_cancel_stmt(model: type[Base], job_id: uuid.UUID) -> Update:
    id_col = model.id  # type: ignore[attr-defined]
    status_col = model.status  # type: ignore[attr-defined]
    return (
        update(model)
        .where(id_col == job_id, status_col.in_(sorted(LIVE_JOB_STATUSES)))
        .values(cancel_requested=True)
        .returning(id_col)
    )


def _cancel_requested_stmt(model: type[Base], job_id: uuid.UUID) -> Select[Any]:
    return select(model.cancel_requested).where(model.id == job_id)  # type: ignore[attr-defined]


def _progress_stmt(
    model: type[Base],
    job_id: uuid.UUID,
    *,
    progress: float,
    stage: str | None,
    message: str | None,
    counters: Mapping[str, Any],
) -> Update:
    """A plain progress ``UPDATE``. **Not a transition** — it never touches ``status``.

    ★ Restricted to live rows. Without that guard a progress tick still in flight when a
    job is cancelled would land afterwards and drag ``progress`` back to 0.6 on a
    finished job — a progress bar that walks backwards after "Cancelled", forever.

    ★ ``progress`` is **clamped**, not validated. It is telemetry: a tick that violates
    ``ck_*_progress`` would abort the transaction and take down a CV job that had
    actually succeeded. Refusing to answer wrongly (L12) protects *survey coordinates*;
    a progress bar is not one, and killing a good job over its cosmetics would be the
    worse lie.
    """
    id_col = model.id  # type: ignore[attr-defined]
    status_col = model.status  # type: ignore[attr-defined]
    values: dict[str, Any] = {"progress": min(1.0, max(0.0, float(progress)))}
    if stage is not None:
        values["progress_stage"] = stage
    if message is not None:
        values["progress_message"] = message
    values.update(counters)
    return (
        update(model)
        .where(id_col == job_id, status_col.in_(sorted(LIVE_JOB_STATUSES)))
        .values(**_prune(model, values))
        .returning(id_col)
    )


def _require_error_message(error_message: str) -> str:
    """``ck_*_failed_has_error`` in Python, where the caller can still be told why.

    Not a duplicated CHECK for its own sake: the constraint would abort the whole
    transaction — including the traceback we were trying to record — and psycopg's
    message names the constraint, not the call site that passed the empty string.
    """
    if not error_message or not error_message.strip():
        raise ValueError(
            "A failed job must carry an error_message (ck_*_failed_has_error). "
            "A failure with no reason is a job nobody can debug."
        )
    return error_message


def _view_filters(
    stmt: Select[Any],
    *,
    types: Sequence[str],
    statuses: Sequence[str],
    image_id: uuid.UUID | None,
    project_id: uuid.UUID | None,
    batch_id: uuid.UUID | None,
) -> Select[Any]:
    if types:
        stmt = stmt.where(v_jobs.c.type.in_(types))
    if statuses:
        stmt = stmt.where(v_jobs.c.status.in_(statuses))
    if image_id is not None:
        stmt = stmt.where(v_jobs.c.image_id == image_id)
    if project_id is not None:
        stmt = stmt.where(v_jobs.c.project_id == project_id)
    if batch_id is not None:
        stmt = stmt.where(v_jobs.c.batch_id == batch_id)
    return stmt


_VIEW_SORTABLE: Final[SortableColumns] = {
    "created_at": v_jobs.c.created_at,
    "started_at": v_jobs.c.started_at,
    "finished_at": v_jobs.c.finished_at,
    "status": v_jobs.c.status,
    "type": v_jobs.c.type,
    "id": v_jobs.c.id,
}


# ─────────────────────────────────────────────────────────────────────────────
# Async — the API
# ─────────────────────────────────────────────────────────────────────────────


class JobRepository(BaseRepository[Any]):
    """Reads ``v_jobs``; writes the four concrete job tables.

    ``model`` is deliberately unset: this repository has no single table. The generic
    ``get``/``exists`` of the base are therefore unavailable, which is correct — "get a
    job" means :meth:`get_view`, and there is no row of ``v_jobs`` to fetch by the
    ORM.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    # ── reads ────────────────────────────────────────────────────────────────

    async def get_view(self, job_id: uuid.UUID) -> JobView | None:
        """One job of any type. What ``deps.get_job()`` returns (§6.4)."""
        row = (await self._execute(select(v_jobs).where(v_jobs.c.id == job_id))).one_or_none()
        return _to_view(row) if row is not None else None

    async def get_view_or_raise(self, job_id: uuid.UUID) -> JobView:
        """:meth:`get_view`, or ``JobNotFound``."""
        view = await self.get_view(job_id)
        if view is None:
            raise JobNotFound(f"No job {job_id}.")
        return view

    async def list_views(
        self,
        *,
        pagination: PaginationParams,
        sort: SortParams,
        type_csv: str | None = None,
        status_csv: str | None = None,
        image_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        batch_id: uuid.UUID | None = None,
    ) -> tuple[list[JobView], int]:
        """``GET /jobs`` (31) over the union of all four job tables.

        Args:
            pagination: Validated limit/offset.
            sort: Whitelisted against ``JOB_SORT_FIELDS``.
            type_csv: ``?type=match,export``.
            status_csv: ``?status=running,queued``.
            image_id: Jobs for one photograph.
            project_id: Jobs for one project — resolved *inside the view*, which is why
                the match branch joins ``images``: ``match_jobs`` has no ``project_id``
                column of its own.
            batch_id: Jobs belonging to one batch.

        Returns:
            ``(views, total)``.
        """
        types = csv_enum_filter(type_csv, [m.value for m in JobType])
        statuses = csv_enum_filter(status_csv, [m.value for m in JobStatus])
        stmt = _view_filters(
            select(v_jobs),
            types=types,
            statuses=statuses,
            image_id=image_id,
            project_id=project_id,
            batch_id=batch_id,
        )
        total = int(await self._scalar(count_stmt_of(stmt)) or 0)
        ordered = apply_sort(stmt, sort, _VIEW_SORTABLE, tiebreaker=v_jobs.c.id)
        rows = (await self._execute(apply_pagination(ordered, pagination))).all()
        return [_to_view(r) for r in rows], total

    async def has_active_jobs(self, project_id: uuid.UUID) -> bool:
        """Whether a project has any live job. Gates ``409 PROJECT_HAS_ACTIVE_JOBS``.

        Asked of the view rather than of four tables, which is the view's whole purpose:
        a delete guard that checked only ``match_jobs`` would happily destroy a project
        mid-export.
        """
        stmt = (
            select(func.count())
            .select_from(v_jobs)
            .where(
                v_jobs.c.project_id == project_id,
                v_jobs.c.status.in_(sorted(LIVE_JOB_STATUSES)),
            )
        )
        return bool(await self._scalar(stmt))

    async def cancel_never_submitted_for_project(self, project_id: uuid.UUID) -> int:
        """Cancel a project's PENDING jobs that were never handed to the broker.

        ★ An upload with no Celery worker/broker running leaves an ``ingest`` aux-job (and an
        export leaves an ``exports`` row) ``pending`` with ``celery_task_id IS NULL`` — it was
        recorded but never submitted, so it will never run and never leave ``pending``. Such an
        orphan otherwise blocks ``DELETE /projects/{id}`` (and the cascade) forever with
        ``409 PROJECT_HAS_ACTIVE_JOBS``. This tombstones ONLY those never-submitted pending
        jobs; a genuinely in-flight job (``celery_task_id`` set, or ``running``) is untouched,
        so a project mid-export is still protected. Returns the count cancelled.

        ★ ``finished_at`` is set alongside the terminal status: ``ck_*_status_finished``
        (models/job.py, models/export.py) require ``finished_at IS NOT NULL`` iff the status is
        terminal, so cancelling without it would violate the constraint.
        """
        terminal = dict(
            status=JobStatus.CANCELLED.value,
            cancel_requested=True,
            finished_at=func.now(),
        )
        project_image_ids = select(Image.id).where(Image.project_id == project_id)
        aux = (
            update(AuxJob)
            .where(
                AuxJob.status == JobStatus.PENDING.value,
                AuxJob.celery_task_id.is_(None),
                AuxJob.image_id.in_(project_image_ids),
            )
            .values(**terminal)
            .returning(AuxJob.id)
        )
        exp = (
            update(Export)
            .where(
                Export.project_id == project_id,
                Export.status == JobStatus.PENDING.value,
                Export.celery_task_id.is_(None),
            )
            .values(**terminal)
            .returning(Export.id)
        )
        n = len((await self._execute(aux)).scalars().all())
        n += len((await self._execute(exp)).scalars().all())
        return n

    async def count_active_for_image(
        self, image_id: uuid.UUID, *, job_type: JobType | None = None
    ) -> int:
        """Live jobs on an image. Feeds the ``MATCH_JOB_ALREADY_RUNNING`` pre-flight."""
        stmt = (
            select(func.count())
            .select_from(v_jobs)
            .where(
                v_jobs.c.image_id == image_id,
                v_jobs.c.status.in_(sorted(LIVE_JOB_STATUSES)),
            )
        )
        if job_type is not None:
            stmt = stmt.where(v_jobs.c.type == job_type.value)
        return int(await self._scalar(stmt) or 0)

    # ── transitions ──────────────────────────────────────────────────────────

    async def mark_queued(
        self, model: type[Base], job_id: uuid.UUID, *, task_id: str | None = None
    ) -> bool:
        """``pending → queued``, recording the broker handle. ``False`` ⇒ not pending."""
        return await self._won(_queued_stmt(model, job_id, task_id))

    async def mark_running(self, model: type[Base], job_id: uuid.UUID) -> bool:
        """``pending|queued|retrying → running``. ``False`` ⇒ already terminal."""
        return await self._won(_running_stmt(model, job_id))

    async def mark_succeeded(
        self, model: type[Base], job_id: uuid.UUID, **extra: Any
    ) -> bool:
        """``live → succeeded``, with ``finished_at`` and ``duration_ms``.

        ★ ``finished_at`` is set in the same statement because
        ``ck_*_finished_iff_terminal`` is a **biconditional**: a terminal status without
        a finish time and a finish time without a terminal status are both rejected, and
        both are exactly the states that make a progress UI hang forever.

        Args:
            model: The concrete job table.
            job_id: The row.
            **extra: Result columns for this job type — ``result_count``,
                ``best_confidence``, ``degraded``, ``warnings``. Silently pruned to what
                the table has, so one caller serves four shapes.

        Returns:
            True if this caller won. False ⇒ someone already finished or cancelled it,
            and **that is not an error** — it is the race resolving.
        """
        return await self._won(_succeeded_stmt(model, job_id, extra))

    async def mark_failed(
        self,
        model: type[Base],
        job_id: uuid.UUID,
        *,
        error_message: str,
        error_type: str | None = None,
        error_traceback: str | None = None,
    ) -> bool:
        """``live → failed``. ``error_message`` is required and must be non-blank."""
        return await self._won(
            _failed_stmt(
                model,
                job_id,
                error_type=error_type,
                error_message=_require_error_message(error_message),
                error_traceback=error_traceback,
            )
        )

    async def mark_cancelled(self, model: type[Base], job_id: uuid.UUID) -> bool:
        """``live → cancelled``. ``False`` ⇒ it finished first; the cancel simply lost."""
        return await self._won(_cancelled_stmt(model, job_id))

    async def mark_retrying(
        self, model: type[Base], job_id: uuid.UUID, *, reason: str | None = None
    ) -> bool:
        """``running|queued → retrying``, incrementing ``attempt``.

        Returns:
            False when the retry budget is spent (``attempt >= max_attempts``) **or**
            the job is no longer live. The caller reads False as "stop retrying" and
            calls :meth:`mark_failed`.
        """
        return await self._won(_retrying_stmt(model, job_id, reason))

    async def request_cancel(self, model: type[Base], job_id: uuid.UUID) -> bool:
        """Ask a live job to stop. **Cooperative — nothing kills a process.**

        The worker polls :meth:`is_cancel_requested` between stages and unwinds itself.
        A killed process leaves a half-written result set and a job stuck at
        ``running``; a cooperative one records ``cancelled`` and cleans up.

        Returns:
            True when the flag was set. False ⇒ the job is already terminal, which is
            the ``409 JOB_NOT_CANCELLABLE`` the endpoint reports.
        """
        return await self._won(_request_cancel_stmt(model, job_id))

    async def is_cancel_requested(self, model: type[Base], job_id: uuid.UUID) -> bool:
        """The poll. False for a job that no longer exists."""
        return bool(await self._scalar(_cancel_requested_stmt(model, job_id)))

    async def write_progress(
        self,
        model: type[Base],
        job_id: uuid.UUID,
        *,
        progress: float,
        stage: str | None = None,
        message: str | None = None,
        **counters: Any,
    ) -> bool:
        """A progress tick. See :func:`_progress_stmt` for the two guarantees."""
        return await self._won(
            _progress_stmt(
                model,
                job_id,
                progress=progress,
                stage=stage,
                message=message,
                counters=counters,
            )
        )

    async def _won(self, stmt: Update) -> bool:
        """Did this caller's compare-and-set match a row?"""
        return (await self._execute(stmt)).scalar_one_or_none() is not None


# ─────────────────────────────────────────────────────────────────────────────
# Sync — the Celery worker
# ─────────────────────────────────────────────────────────────────────────────


class SyncJobRepository:
    """The job state machine for a prefork worker.

    ``tasks/base.py`` (transitions, retry policy, error map) and ``tasks/progress.py``
    (throttled writer, cancel polling) are its callers::

        with sync_session() as db:
            repo = SyncJobRepository(db)
            repo.mark_running(MatchJob, job_id)

    ★ **Every method delegates to the same builder its async twin uses.** There is one
    definition of "how a job becomes succeeded" in this codebase, and it is above. If
    these two ever disagree, it is because someone added a method to one and not the
    other — not because the SQL drifted.

    ★ Progress writes must not run inside the CV transaction (§5.9): progress is
    telemetry, and it must never hold a lock a matcher needs. Wrap :meth:`write_progress`
    in ``session_scope()`` (a SAVEPOINT) or issue it on its own session — this class does
    not own the transaction and will not pretend to.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def _execute(self, stmt: Any) -> Any:
        """The sync twin of :meth:`BaseRepository._execute` — same narrow catch.

        ``OperationalError``/``InterfaceError`` become ``DatabaseUnavailable``, which
        ``tasks.base`` classifies as transient and retryable. ``IntegrityError`` is
        deliberately **not** caught: a violated constraint is a domain answer, not an
        outage, and retrying it would just violate it again.
        """
        try:
            return self.session.execute(stmt)
        except (OperationalError, InterfaceError) as exc:
            raise_if_unavailable(exc)
            raise  # pragma: no cover

    def _won(self, stmt: Update) -> bool:
        return self._execute(stmt).scalar_one_or_none() is not None

    def _scalar(self, stmt: Any) -> Any:
        return self._execute(stmt).scalar()

    def get_view(self, job_id: uuid.UUID) -> JobView | None:
        """One job of any type, for a worker that needs the union's shape."""
        row = self._execute(select(v_jobs).where(v_jobs.c.id == job_id)).one_or_none()
        return _to_view(row) if row is not None else None

    def mark_queued(
        self, model: type[Base], job_id: uuid.UUID, *, task_id: str | None = None
    ) -> bool:
        """``pending → queued``."""
        return self._won(_queued_stmt(model, job_id, task_id))

    def mark_running(self, model: type[Base], job_id: uuid.UUID) -> bool:
        """``pending|queued|retrying → running``."""
        return self._won(_running_stmt(model, job_id))

    def mark_succeeded(self, model: type[Base], job_id: uuid.UUID, **extra: Any) -> bool:
        """``live → succeeded``."""
        return self._won(_succeeded_stmt(model, job_id, extra))

    def mark_failed(
        self,
        model: type[Base],
        job_id: uuid.UUID,
        *,
        error_message: str,
        error_type: str | None = None,
        error_traceback: str | None = None,
    ) -> bool:
        """``live → failed``."""
        return self._won(
            _failed_stmt(
                model,
                job_id,
                error_type=error_type,
                error_message=_require_error_message(error_message),
                error_traceback=error_traceback,
            )
        )

    def mark_cancelled(self, model: type[Base], job_id: uuid.UUID) -> bool:
        """``live → cancelled``."""
        return self._won(_cancelled_stmt(model, job_id))

    def mark_retrying(
        self, model: type[Base], job_id: uuid.UUID, *, reason: str | None = None
    ) -> bool:
        """``running|queued → retrying``. False ⇒ budget spent; fail it."""
        return self._won(_retrying_stmt(model, job_id, reason))

    def is_cancel_requested(self, model: type[Base], job_id: uuid.UUID) -> bool:
        """★ The worker's cancel poll, called between stages."""
        return bool(self._scalar(_cancel_requested_stmt(model, job_id)))

    def write_progress(
        self,
        model: type[Base],
        job_id: uuid.UUID,
        *,
        progress: float,
        stage: str | None = None,
        message: str | None = None,
        **counters: Any,
    ) -> bool:
        """A progress tick. Throttle to ≥ 250 ms apart in the caller (§5.9)."""
        return self._won(
            _progress_stmt(
                model,
                job_id,
                progress=progress,
                stage=stage,
                message=message,
                counters=counters,
            )
        )
