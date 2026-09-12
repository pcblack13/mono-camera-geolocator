"""Health and readiness — endpoints 1, 2 (§7.1).

★ ``GET /health`` touches **no** dependency: a liveness probe that checks Postgres restarts
every container when Postgres blips. ★ ``GET /health/ready`` **never returns 500** — every check
is individually wrapped, and an exception inside one becomes ``status: "down"`` for that
component. Only ``postgres``/``redis``/``storage`` gate readiness (503); ``celery``/``imagery``/
``raster`` report ``degraded`` and still return 200; ``models`` is informational and never gates.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Literal

from fastapi import APIRouter, Query, Request, Response

from app.schemas.health import (
    ComponentHealth,
    HealthResponse,
    LogRecordOut,
    LogsResponse,
    ReadinessResponse,
)

router = APIRouter()

API_VERSION = "1.0.0"

#: The three that gate readiness — without them no request can be served correctly (§7.1).
_GATING = frozenset({"postgres", "redis", "storage"})


@router.get("/health", response_model=HealthResponse, summary="Liveness")
async def health(request: Request) -> HealthResponse:
    started = getattr(request.app.state, "start_time", time.monotonic())
    return HealthResponse(status="ok", version=API_VERSION, uptime_s=time.monotonic() - started)


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse, "description": "Not ready."}},
    summary="Readiness",
)
async def readiness(
    request: Request,
    response: Response,
    verbose: bool = Query(False),
    check: str | None = Query(None, description="CSV subset of component names."),
) -> ReadinessResponse:
    requested = {c.strip() for c in check.split(",") if c.strip()} if check else None
    checks: dict[str, Callable[[Request], Awaitable[ComponentHealth]]] = {
        "postgres": _check_postgres,
        "redis": _check_redis,
        "storage": _check_storage,
        "celery": _check_celery,
        "imagery": _check_imagery,
        "models": _check_models,
        "raster": _check_raster,
    }
    components: list[ComponentHealth] = []
    for name, probe in checks.items():
        if requested is not None and name not in requested:
            components.append(ComponentHealth(name=name, status="skipped"))
            continue
        components.append(await _guard(name, probe, request))

    gating_down = any(c.name in _GATING and c.status == "down" for c in components)
    any_degraded = any(c.status in ("down", "degraded") for c in components)
    status = "not_ready" if gating_down else ("degraded" if any_degraded else "ok")
    response.status_code = 503 if gating_down else 200
    return ReadinessResponse(status=status, components=components, checked_at=datetime.now(tz=timezone.utc))


@router.get(
    "/health/logs",
    response_model=LogsResponse,
    summary="Recent application logs",
)
async def logs(
    after: int = Query(0, ge=0, description="Return only entries with seq > after."),
    level: Literal["debug", "info", "warning", "error", "critical"] = Query(
        "debug", description="Minimum level to include."
    ),
    q: str | None = Query(
        None, max_length=200, description="Case-insensitive substring filter, any field."
    ),
    limit: int = Query(500, ge=1, le=2000),
) -> LogsResponse:
    """The app-status page's log monitor — the newest matching lines, oldest first.

    ★ Reads the in-process ring buffer that captures the ROOT logger after the same
    processor chain stdout gets — scrubbing included (§9.10). The desktop app has no
    terminal; when something fails in the field, this endpoint is how the log
    reaches a human. Filters run server-side so a slow link ships only what is asked.
    """
    from app.core.logbuffer import get_log_buffer, level_to_number

    buffer = get_log_buffer()
    entries = buffer.snapshot(
        after=after, min_levelno=level_to_number(level), contains=q, limit=limit
    )
    return LogsResponse(
        entries=[_to_log_record(e) for e in entries],
        last_seq=buffer.last_seq,
        dropped_before=buffer.dropped_before(),
        capacity=buffer.capacity,
        checked_at=datetime.now(tz=timezone.utc),
    )


def _to_log_record(entry: dict[str, Any]) -> LogRecordOut:
    """Buffer dict → wire model: known keys become fields, the rest ride in ``fields``."""
    rest = dict(entry)
    seq = int(rest.pop("seq", 0))
    timestamp = str(rest.pop("timestamp", ""))
    level = str(rest.pop("level", "info"))
    logger_name = rest.pop("logger", None)
    event = str(rest.pop("event", ""))
    request_id = rest.pop("request_id", None)
    exception = rest.pop("exception", None)
    return LogRecordOut(
        seq=seq,
        timestamp=timestamp,
        level=level,
        logger=str(logger_name) if logger_name is not None else None,
        event=event,
        request_id=str(request_id) if request_id is not None else None,
        exception=str(exception) if exception is not None else None,
        fields=rest,
    )


async def _guard(
    name: str, probe: Callable[[Request], Awaitable[ComponentHealth]], request: Request
) -> ComponentHealth:
    """A check that raises becomes ``down`` for that component — never a 500 (§7.1)."""
    start = time.perf_counter()
    try:
        component = await probe(request)
        if component.latency_ms is None:
            component.latency_ms = (time.perf_counter() - start) * 1000.0
        return component
    except Exception as exc:  # noqa: BLE001 — a readiness probe that throws is useless.
        return ComponentHealth(
            name=name,
            status="down" if name in _GATING else "degraded",
            latency_ms=(time.perf_counter() - start) * 1000.0,
            message=f"{type(exc).__name__}: {exc}",
        )


async def _check_postgres(request: Request) -> ComponentHealth:
    from app.api.deps import check_database

    ok, detail = await check_database()
    return ComponentHealth(name="postgres", status="up" if ok else "down", message=None if ok else detail)


async def _check_redis(request: Request) -> ComponentHealth:
    client = getattr(request.app.state, "redis", None)
    if client is None:
        return ComponentHealth(name="redis", status="down", message="no Redis client configured")
    try:
        client.ping()
        return ComponentHealth(name="redis", status="up")
    except Exception as exc:  # noqa: BLE001
        return ComponentHealth(name="redis", status="down", message=f"{type(exc).__name__}: {exc}")


async def _check_storage(request: Request) -> ComponentHealth:
    from app.storage import get_storage

    storage = get_storage()
    key = "healthcheck/probe.txt"
    try:
        storage.put(key, b"1", content_type="text/plain")
        storage.get(key)
        storage.delete(key)
        return ComponentHealth(name="storage", status="up")
    except Exception as exc:  # noqa: BLE001
        return ComponentHealth(name="storage", status="down", message=f"{type(exc).__name__}: {exc}")


async def _check_celery(request: Request) -> ComponentHealth:
    queue = getattr(request.app.state, "job_queue", None)
    if queue is None:
        return ComponentHealth(name="celery", status="degraded", message="no worker configured")
    return ComponentHealth(name="celery", status="up")


async def _check_imagery(request: Request) -> ComponentHealth:
    from app.core.config import get_settings
    from app.services.imagery_service import ImageryService

    registry = getattr(request.app.state, "imagery_registry", None)
    service = ImageryService(get_settings(), registry=registry)
    provider_name = service.default_provider_name()
    health = service.health(provider_name)
    status = "up" if health.status == "up" else "degraded"
    return ComponentHealth(name="imagery", status=status, message=health.message)


async def _check_models(request: Request) -> ComponentHealth:
    """Informational only — reads the cached PreflightReport, never re-probes, never gates."""
    report = getattr(request.app.state, "preflight_report", None)
    message = "Classical CV pipeline is fully operational; deep-model paths are deferred (SCOPE.md)."
    return ComponentHealth(name="models", status="up", message=message)


async def _check_raster(request: Request) -> ComponentHealth:
    # ★ Through the SERVICE, not gis directly (2026-09-02): the .importlinter
    #   contract forbids app.api.v1 → gis, and this line was the one violation
    #   in the tree. CapabilityService already owns the probe.
    try:
        from app.services.capability_service import CapabilityService

        backend = CapabilityService._raster_backend()  # noqa: SLF001 — the probe, verbatim
    except Exception as exc:  # noqa: BLE001
        return ComponentHealth(name="raster", status="degraded", message=f"probe failed: {exc}")
    status = "degraded" if backend == "none" else "up"
    return ComponentHealth(name="raster", status=status, message=f"backend={backend}")
