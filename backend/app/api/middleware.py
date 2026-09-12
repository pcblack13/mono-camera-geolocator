"""HTTP middleware (§6.5) — RequestId · Timing · BodySizeLimit · RateLimit.

Middleware order, **outermost → innermost** (§6.5): RequestId, CORS, Timing, BodySizeLimit,
RateLimit, GZip, Router. CORS and GZip are Starlette built-ins wired in :mod:`app.main`; the
four here are custom. Because ``add_middleware`` stacks last-added-outermost, ``main`` adds
them innermost-first — the ordering rationale is recorded there.

★ **RequestId is outermost so *every* response carries one** — including the rejections the
middleware below it emits. The id is the string a user pastes into a bug report, and a
rejection without one is unreportable.

★ **The rate limiter fails OPEN when Redis is unreachable** (§6.5). Rate limiting is a
protection mechanism, not a correctness one; failing closed converts a Redis blip into a
total outage, and ``/health/ready`` already pulls the instance from rotation. It logs and
increments ``ratelimit_failopen_total`` so the lapse is never silent.
"""

from __future__ import annotations

import secrets
import time
from datetime import datetime, timezone
from typing import Awaitable, Callable, Final

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import Settings
from app.core.constants import docs_url_for
from app.core.logging import bind_request_context, clear_context, get_logger
from app.observability import metrics
from app.schemas.errors import ErrorBody, ErrorEnvelope

__all__ = [
    "BodySizeLimitMiddleware",
    "RateLimitMiddleware",
    "RequestIdMiddleware",
    "TimingMiddleware",
    "new_request_id",
]

log = get_logger(__name__)

#: Paths exempt from rate limiting and body-size checks — the liveness/readiness probes and
#: the metrics scrape. Rate-limiting your own health probe makes the orchestrator kill
#: healthy containers under load (§6.5).
_PROBE_PATHS: Final = frozenset({"/health", "/metrics"})

_CROCKFORD: Final = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_request_id() -> str:
    """A ULID: 48 bits of millisecond time + 80 bits of randomness, Crockford base32.

    Lexicographically sortable by creation time and dependency-free — a request id does not
    warrant pulling in a ULID package, and this is the one call site.
    """
    ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand = int.from_bytes(secrets.token_bytes(10), "big")
    value = (ms << 80) | rand
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def _error_response(*, request: Request, status: int, code: str, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    """Build the uniform envelope for a middleware-level rejection."""
    envelope = ErrorEnvelope(
        error=ErrorBody(
            code=code,
            message=message,
            status=status,
            details=None,
            request_id=str(getattr(request.state, "request_id", "") or "unknown"),
            timestamp=datetime.now(tz=timezone.utc),
            docs_url=docs_url_for(code),
            feature=None,
        )
    )
    return JSONResponse(
        status_code=status,
        content=envelope.model_dump(mode="json", by_alias=True),
        headers=headers,
    )


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Mint or propagate a request id, bind it to the logging context, echo the header."""

    def __init__(self, app, *, header: str = "X-Request-ID") -> None:
        super().__init__(app)
        self._header = header

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        incoming = request.headers.get(self._header)
        request_id = incoming if incoming else new_request_id()
        request.state.request_id = request_id
        bind_request_context(request_id=request_id, method=request.method, route=request.url.path)
        try:
            response = await call_next(request)
        finally:
            # Celery-style leakage guard: contextvars survive the task/thread otherwise.
            clear_context()
        response.headers[self._header] = request_id
        return response


#: Advertised on every response so a client and its generated types agree on the wire version.
API_VERSION_HEADER_VALUE: Final = "1.0.0"


class TimingMiddleware(BaseHTTPMiddleware):
    """``X-Response-Time-ms`` and ``X-API-Version`` headers, plus the request/latency metrics."""

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        response.headers["X-Response-Time-ms"] = f"{elapsed_ms:.1f}"
        response.headers["X-API-Version"] = API_VERSION_HEADER_VALUE

        route = request.scope.get("route")
        template = getattr(route, "path", request.url.path)
        try:
            metrics.http_requests_total.labels(
                route=template, method=request.method, status=str(response.status_code)
            ).inc()
            metrics.http_request_duration_seconds.labels(route=template).observe(elapsed_ms / 1000.0)
        except Exception:  # noqa: BLE001 — telemetry never breaks a request.
            pass
        return response


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject an over-cap body by its ``Content-Length`` before it reaches a route.

    ★ A coarse guard on the declared length. The authoritative check is the streaming byte
    count in ``image_service`` (a chunked upload may omit ``Content-Length``), but rejecting
    a declared 2 GB up front saves reading it.
    """

    def __init__(self, app, *, max_bytes: int) -> None:
        super().__init__(app)
        self._max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if request.url.path not in _PROBE_PATHS:
            declared = request.headers.get("content-length")
            if declared is not None:
                try:
                    length = int(declared)
                except ValueError:
                    length = 0
                if length > self._max_bytes:
                    return _error_response(
                        request=request,
                        status=413,
                        code="PAYLOAD_TOO_LARGE",
                        message=(
                            f"Request body of {length} bytes exceeds the {self._max_bytes}-byte "
                            "limit (LE_UPLOAD_MAX_BYTES)."
                        ),
                    )
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """A per-principal fixed-window limiter over Redis. **Fails open** (§6.5).

    The Redis client is read off ``app.state.redis`` — None when no broker is configured or
    the connection failed at boot. With no client, or on any Redis error, the request is
    allowed, a warning is logged, and ``ratelimit_failopen_total`` is incremented.
    """

    def __init__(self, app, *, settings: Settings) -> None:
        super().__init__(app)
        self._settings = settings

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if not self._settings.rate_limit_enabled or request.url.path in _PROBE_PATHS:
            return await call_next(request)

        client = getattr(request.app.state, "redis", None)
        if client is None:
            self._fail_open("no_redis")
            return await call_next(request)

        principal = self._principal_key(request)
        window = int(time.time() // 60)
        key = f"ratelimit:{principal}:{window}"
        limit = self._settings.rate_limit_per_minute
        try:
            count = client.incr(key)
            if count == 1:
                client.expire(key, 70)
        except Exception as exc:  # noqa: BLE001 — fail open on any backend trouble.
            self._fail_open(type(exc).__name__)
            return await call_next(request)

        if count > limit:
            try:
                metrics.ratelimit_rejections_total.labels(scope="per_principal").inc()
            except Exception:  # noqa: BLE001
                pass
            return _error_response(
                request=request,
                status=429,
                code="RATE_LIMIT_EXCEEDED",
                message=f"Rate limit of {limit} requests/minute exceeded.",
                headers={"Retry-After": "60"},
            )
        return await call_next(request)

    def _fail_open(self, reason: str) -> None:
        log.warning("ratelimit.fail_open", reason=reason)
        try:
            metrics.ratelimit_failopen_total.inc()
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _principal_key(request: Request) -> str:
        api_key = request.headers.get("x-api-key")
        if api_key:
            return "k:" + str(hash(api_key) & 0xFFFFFFFF)
        client = request.client
        return "ip:" + (client.host if client else "unknown")
