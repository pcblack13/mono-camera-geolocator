"""Async jobs (§6.2) — endpoints 31–33, and the ``202`` body of 30/42/43/47/58/59.

★ **Only seven endpoints initiate async work**: 30, 42, 43, 47, 54, 58, 59.
Everything else answers immediately. That is the shape of a system where CV never
touches a request handler (L5).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from .common import ApiModel, ListParams, ResultRef, WarningItem
from .enums import JobStage, JobStatus, JobType
from .errors import ErrorBody

__all__ = [
    "JOB_SORT_FIELDS",
    "JobListParams",
    "JobPollParams",
    "JobProgress",
    "JobRead",
    "JobSummary",
]

JOB_SORT_FIELDS = frozenset({"created_at", "started_at", "finished_at", "status", "type"})


class JobProgress(ApiModel):
    """★ Rules the workers MUST honour, because the UI depends on them (§6.2):

    - ``percent`` is **monotonic non-decreasing within an attempt** and resets to
      ``0`` on ``retrying``. *A progress bar that goes backwards is a bug report.*
    - ``percent`` is a **weighted blend of stages, not ``stage_index /
      n_stages``**, so the bar tracks wall-clock rather than stage count.
      ``STAGE_WEIGHTS`` lives in ``app.core.constants`` (IU-15) and nowhere else.
    - Progress writes are throttled to ≥ 250 ms apart and use a plain ``UPDATE``,
      **never inside the CV transaction**. Progress is telemetry; it must never
      hold a lock a matcher needs.
    """

    percent: float = Field(ge=0.0, le=100.0)
    stage: JobStage
    message: str | None = None
    current: int | None = None
    total: int | None = None
    eta_seconds: int | None = Field(
        default=None,
        description=(
            "★ Null until >= 3 rate samples. **A wrong ETA is worse than none** — "
            "a bar that says '2 minutes remaining' for eleven minutes destroys "
            "trust in every other number on the screen."
        ),
    )
    tiles_fetched: int | None = None
    tiles_total: int | None = None
    candidates_evaluated: int | None = None


class JobRead(ApiModel):
    """The full job. ★ Read from the ``v_jobs`` union (§5.5), discriminated by
    ``type``.
    """

    id: UUID
    type: JobType
    status: JobStatus
    image_id: UUID | None
    project_id: UUID | None
    batch_id: UUID | None
    cancel_requested: bool = Field(
        description=(
            "★ `running` -> DELETE sets this and returns 202; the worker polls it "
            "at every stage boundary and inside the tile-fetch loop. "
            "revoke(terminate=True) is NEVER used — a hard kill of a process "
            "holding GDAL dataset handles orphans *.part files and can wedge the "
            "CUDA context so the worker's NEXT task fails too. A one-second "
            "cooperative window is worth avoiding an entire class of corruption."
        )
    )
    attempt: int
    max_attempts: int
    progress: JobProgress
    degraded: bool = Field(
        description=(
            "★ `degraded: true` whose only cause is 'no deep weights present' is "
            "INFORMATIONAL, not a warning — per SCOPE.md and §0.1 that is the "
            "DEFAULT state on a fresh machine. The field that decides the "
            "rendering is warnings[].requested: an unrequested fallback is "
            "informational; a requested-and-denied one is a warning."
        )
    )
    degradation_reason: str | None
    warnings: list[WarningItem] = Field(default_factory=list)
    result_ref: ResultRef | None = Field(default=None, description="Null until succeeded.")
    result_url: str | None = None
    error: ErrorBody | None = Field(
        default=None,
        description=(
            "★ ErrorBody-shaped: the client renders job failures with the SAME "
            "component as HTTP errors. `error_traceback` is stored server-side "
            "and NEVER serialised — tracebacks contain storage paths, connection "
            "strings and provider keys.\n\n"
            "★ 'No match found' is `succeeded`, NOT `failed`. A job that fetched "
            "tiles, extracted features and found no candidate above "
            "min_confidence DID ITS JOB CORRECTLY: it ends `succeeded` with "
            "result_count=0. Modelling it as `failed` would trigger pointless "
            "retries of a deterministic outcome and tell the surveyor the system "
            "broke when the answer is 'not here'. `failed` is reserved for *the "
            "pipeline could not run*."
        ),
    )
    queued_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    created_at: datetime
    updated_at: datetime


class JobSummary(ApiModel):
    """List projection — endpoint 31. Flattens the two progress fields the job
    list actually renders rather than nesting a whole :class:`JobProgress`.
    """

    id: UUID
    type: JobType
    status: JobStatus
    image_id: UUID | None
    project_id: UUID | None
    percent: float = Field(ge=0.0, le=100.0)
    stage: JobStage
    degraded: bool
    created_at: datetime
    finished_at: datetime | None


class JobListParams(ListParams):
    """``GET /jobs`` — endpoint 31."""

    type: str | None = Field(default=None, description="CSV of JobType.")
    status: str | None = Field(default=None, description="CSV of JobStatus.")
    image_id: UUID | None = None
    project_id: UUID | None = None
    batch_id: UUID | None = None


class JobPollParams(ApiModel):
    """``GET /jobs/{job_id}`` — endpoint 32.

    ★ Long-poll ``?wait=0..30`` subscribes to the Redis pubsub channel
    ``job:{id}:events``, cutting poll traffic ~25×. **Falls back transparently**
    (L11): if Redis pubsub is unavailable, ``wait`` is ignored and the current
    state returns immediately — never an error, never a hang. nginx's
    ``proxy_read_timeout`` must exceed 30 s.

    ★ ``Retry-After`` is ``1`` running, ``2`` pending/queued, ``5`` retrying, and
    **absent when terminal — its absence IS the machine-readable "stop polling"**.
    """

    wait: int = Field(default=0, ge=0, le=30)
