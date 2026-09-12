"""Liveness and readiness (§6.2, §7.1) — endpoints 1 and 2."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from .common import ApiModel
from .enums import ComponentStatus, HealthStatus

__all__ = [
    "ComponentHealth",
    "HealthResponse",
    "LogRecordOut",
    "LogsResponse",
    "ReadinessParams",
    "ReadinessResponse",
]


class ComponentHealth(ApiModel):
    """One dependency's verdict.

    ★ ``GET /health/ready`` **NEVER returns 500.** Every check is individually
    wrapped; an exception inside a check becomes ``status: "down"`` plus a
    ``message`` for that component. *A readiness endpoint that can itself throw
    is useless precisely when you need it.*
    """

    name: str = Field(
        description="postgres | redis | storage | celery | imagery | models | raster (§7.1)."
    )
    status: ComponentStatus
    latency_ms: float | None = None
    message: str | None = None


class HealthResponse(ApiModel):
    """``GET /health`` — liveness only.

    ★ **Touches no dependency.** A liveness probe that checks Postgres restarts
    every API container when Postgres blips, turning a 30-second hiccup into a
    full outage. Liveness answers only "is this process wedged?"
    """

    status: HealthStatus
    version: str
    uptime_s: float


class ReadinessResponse(ApiModel):
    """``GET /health/ready`` — 200 or 503.

    ★ **THE SINGLE EXPLICIT EXCEPTION to the error envelope** (§6.2): this is
    returned on 503 too, *not* an ``ErrorEnvelope``. A probe wants the check
    detail, and that response is not an application error.

    ★ Only ``postgres``/``redis``/``storage`` gate readiness (§7.1). ``celery``,
    ``imagery`` and ``raster`` report ``degraded`` and still return **200** — if
    no worker is running the API can still serve every read, and 503 would take
    the whole UI offline including the screens that would tell the operator the
    workers are down. Meanwhile ``POST /images/{id}/match`` independently returns
    ``503 WORKER_UNAVAILABLE``, so the failure is reported *precisely at the
    operation that needs a worker*.

    ★ ``models`` **NEVER** affects readiness. That is L1 expressed in the health
    surface: the dev machine has no deep weights and must run end to end. Weight
    presence is reported so the UI can grey out ``superglue`` in a dropdown, and
    that is all it does.
    """

    status: HealthStatus
    components: list[ComponentHealth]
    checked_at: datetime


class LogRecordOut(ApiModel):
    """One captured log line — ``GET /health/logs`` (the app-status page's monitor).

    ★ Everything here has ALREADY been through the §9.10 scrubber — the ring buffer
    captures after the same processor chain stdout gets, so no secret reaches this
    model to begin with.
    """

    seq: int = Field(description="Monotonic cursor. Poll with ?after=<last seen seq>.")
    timestamp: str
    level: str = Field(description="debug | info | warning | error | critical.")
    logger: str | None = None
    event: str = Field(description="The log message (structlog's event).")
    request_id: str | None = Field(
        default=None,
        description="Bound by RequestIdMiddleware — the same id an ErrorEnvelope carries.",
    )
    exception: str | None = Field(default=None, description="The formatted traceback, if any.")
    fields: dict[str, Any] = Field(
        default_factory=dict, description="Every other structured field the line carried."
    )


class LogsResponse(ApiModel):
    """``GET /health/logs`` — the newest matching lines, oldest first.

    ★ ``last_seq`` is the buffer's cursor REGARDLESS of filters: pass it back as
    ``?after=`` and a quiet poll costs nothing. ``dropped_before > after`` tells a
    poller lines were evicted between polls — reported, never silent.
    """

    entries: list[LogRecordOut]
    last_seq: int
    dropped_before: int = Field(description="Seqs at or below this were evicted from the buffer.")
    capacity: int
    checked_at: datetime


class ReadinessParams(ApiModel):
    """``?verbose=&check=`` for endpoint 2."""

    verbose: bool = False
    check: str | None = Field(
        default=None,
        description=(
            "CSV subset of component names. Unrequested components report "
            "status='skipped' — never a fabricated 'up'."
        ),
    )
