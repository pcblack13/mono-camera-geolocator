"""Exception handlers — the exception hierarchy → :class:`ErrorEnvelope` (§6.3).

★ **A SINGLE handler for the whole ``LandExplorerError`` hierarchy.** It reads
``exc.status`` / ``exc.code`` / ``exc.details`` / ``exc.headers`` and builds the envelope —
there is **no per-exception if-ladder** (§6.3), which is the entire reason ``code`` and
``status`` are ClassVars.

★ **``FeatureDeferredError`` → HTTP 501 with a ``feature: "deferred"`` marker** (SCOPE.md §4
rule 3), never 404 and never a fabricated result. The one canonical 501 body is built by
``schemas.errors.deferred_envelope`` so five deferred endpoints cannot drift.

Four handlers are registered on the app in :func:`register_exception_handlers`:

* ``LandExplorerError`` — every domain error, including the 501 surface.
* ``RequestValidationError`` — FastAPI's body/query validation → ``422 VALIDATION_ERROR``,
  in the **same envelope** so a client parses one shape everywhere.
* ``StarletteHTTPException`` — a route-not-found (404) or method-not-allowed (405) FastAPI
  raises itself, wrapped into the envelope so ``openapi.json``'s promise (every non-2xx is an
  ``ErrorEnvelope``) holds even for framework errors.
* ``Exception`` — the last-resort 500. Logs ``exc_info`` with ``request_id``/route/principal,
  increments ``unhandled_exceptions_total``, and returns a **generic** body — never the
  exception string, which carries storage paths, connection strings and provider keys.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Final, Mapping

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import Settings
from app.core.constants import docs_url_for
from app.core.exceptions import FeatureDeferredError, LandExplorerError
from app.core.logging import get_logger
from app.observability import metrics
from app.schemas.errors import (
    DeferredFeature,
    ErrorBody,
    ErrorDetail,
    ErrorEnvelope,
    deferred_envelope,
)

__all__ = [
    "COMMON_ERROR_RESPONSES",
    "REQUEST_ID_STATE_KEY",
    "register_exception_handlers",
]

log = get_logger(__name__)

#: Where :meth:`Request.state` carries the ULID minted by ``RequestIdMiddleware``. Read here
#: so every error body and the ``X-Request-ID`` echo agree on one id.
REQUEST_ID_STATE_KEY: Final = "request_id"

#: The generic 500 message. **Never the exception string** (§6.3).
_INTERNAL_MESSAGE: Final = "An unexpected error occurred."

#: The shared OpenAPI ``responses`` block put on **every** route so ``openapi.json`` documents
#: the envelope everywhere rather than on a lucky few — *a missing 404 in the spec becomes an
#: untyped ``any`` in the generated client* (§6.2).
COMMON_ERROR_RESPONSES: Final[dict[int | str, dict[str, Any]]] = {
    400: {"model": ErrorEnvelope, "description": "Bad request."},
    401: {"model": ErrorEnvelope, "description": "Unauthorized."},
    403: {"model": ErrorEnvelope, "description": "Forbidden."},
    404: {"model": ErrorEnvelope, "description": "Not found."},
    409: {"model": ErrorEnvelope, "description": "Conflict."},
    422: {"model": ErrorEnvelope, "description": "Validation error."},
    429: {"model": ErrorEnvelope, "description": "Rate limited."},
    500: {"model": ErrorEnvelope, "description": "Internal error."},
    501: {
        "model": ErrorEnvelope,
        "description": (
            "Feature deferred in this build (SCOPE.md). Carries a `feature: \"deferred\"` "
            "marker; the feature is planned, not absent."
        ),
    },
    503: {"model": ErrorEnvelope, "description": "Dependency unavailable."},
}

#: A deferred error names a ``component`` (``ai_engine.pipeline.orchestrator``); the wire
#: ``feature`` name is the capability a client gates its UI off — a member of
#: ``CapabilitiesResponse.deferred_features``. This maps one to the other so the 501 body and
#: ``/capabilities`` agree on the spelling.
_COMPONENT_TO_FEATURE: Final[Mapping[str, str]] = {
    "ai_engine.pipeline.orchestrator": "matching",
    "ai_engine.geometry.homography": "matching",
    "ai_engine.geometry.pose": "camera_pose",
    "ai_engine.heatmap.posterior": "heatmap",
    "ai_engine.semantics": "segmentation",
    "ai_engine.landmarks.suggest": "landmark_suggestion",
}

#: For a matching-family 501, the honest thing to do instead. Null for the rest — an invented
#: alternative is worse than none (§ schemas.errors).
_FEATURE_ALTERNATIVE: Final[Mapping[str, str]] = {
    "matching": "Place GCPs manually: mark a landmark in the photo and click the same point on the map.",
    "landmark_suggestion": "Mark landmarks manually in the photograph.",
}


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _request_id(request: Request) -> str:
    return str(getattr(request.state, REQUEST_ID_STATE_KEY, "") or "unknown")


def _route(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", request.url.path)


def _json_response(envelope: ErrorEnvelope, *, status: int, headers: Mapping[str, str] | None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content=envelope.model_dump(mode="json", by_alias=True),
        headers=dict(headers) if headers else None,
    )


def _feature_for(exc: FeatureDeferredError) -> str:
    return _COMPONENT_TO_FEATURE.get(exc.component, exc.component.rsplit(".", 1)[-1])


async def landexplorer_exception_handler(request: Request, exc: LandExplorerError) -> JSONResponse:
    """The single domain-error handler (§6.3). Reads the ClassVars; no if-ladder."""
    request_id = _request_id(request)

    if isinstance(exc, FeatureDeferredError):
        feature = _feature_for(exc)
        envelope = deferred_envelope(
            feature=feature,
            reason=exc.message,
            request_id=request_id,
            timestamp=_now(),
            message=exc.message,
            alternative=_FEATURE_ALTERNATIVE.get(feature),
        )
        log.info("api.feature_deferred", route=_route(request), component=exc.component, feature=feature)
        return _json_response(envelope, status=exc.status, headers=exc.headers)

    envelope = ErrorEnvelope(
        error=ErrorBody(
            code=exc.code,
            message=exc.message,
            status=exc.status,
            details=list(exc.details) or None,
            request_id=request_id,
            timestamp=_now(),
            docs_url=exc.docs_url,
            feature=None,
        )
    )
    # 5xx domain errors are worth a WARN with context; 4xx are the client's business.
    if exc.status >= 500:
        log.warning("api.domain_error", route=_route(request), code=exc.code, status=exc.status)
    return _json_response(envelope, status=exc.status, headers=exc.headers)


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """FastAPI body/query validation → ``422 VALIDATION_ERROR``, same envelope."""
    details = [
        ErrorDetail(
            loc=[str(part) if not isinstance(part, int) else part for part in err.get("loc", ())],
            msg=str(err.get("msg", "")),
            type=str(err.get("type", "validation_error")),
            input=err.get("input"),
        )
        for err in exc.errors()
    ]
    envelope = ErrorEnvelope(
        error=ErrorBody(
            code="VALIDATION_ERROR",
            message="Request validation failed.",
            status=422,
            details=details or None,
            request_id=_request_id(request),
            timestamp=_now(),
            docs_url=docs_url_for("VALIDATION_ERROR"),
            feature=None,
        )
    )
    return _json_response(envelope, status=422, headers=None)


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """A framework ``HTTPException`` (404 route miss, 405) → the uniform envelope."""
    code = _STATUS_CODE.get(exc.status_code, "HTTP_ERROR")
    envelope = ErrorEnvelope(
        error=ErrorBody(
            code=code,
            message=str(exc.detail) if exc.detail else _STATUS_MESSAGE.get(exc.status_code, "Error."),
            status=exc.status_code,
            details=None,
            request_id=_request_id(request),
            timestamp=_now(),
            docs_url=docs_url_for(code),
            feature=None,
        )
    )
    return _json_response(envelope, status=exc.status_code, headers=getattr(exc, "headers", None))


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """The last-resort 500. Generic body; the exception string never reaches the client."""
    settings: Settings | None = getattr(request.app.state, "settings", None)
    try:
        metrics.unhandled_exceptions_total.labels(route=_route(request)).inc()
    except Exception:  # noqa: BLE001 — a metrics failure must never mask the real error.
        pass
    log.error(
        "api.unhandled_exception",
        route=_route(request),
        request_id=_request_id(request),
        principal=str(getattr(request.state, "principal", "")) or None,
        exc_info=exc,
    )
    details: list[ErrorDetail] | None = None
    if settings is not None and settings.debug:
        details = [ErrorDetail(loc=[], msg=repr(exc), type="debug.traceback", input=None)]
    envelope = ErrorEnvelope(
        error=ErrorBody(
            code="INTERNAL_ERROR",
            message=_INTERNAL_MESSAGE,
            status=500,
            details=details,
            request_id=_request_id(request),
            timestamp=_now(),
            docs_url=None,
            feature=None,
        )
    )
    return _json_response(envelope, status=500, headers=None)


#: Framework HTTP status → the stable error code the client switches on.
_STATUS_CODE: Final[Mapping[int, str]] = {
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    406: "NOT_ACCEPTABLE",
    415: "UNSUPPORTED_MEDIA_TYPE",
}
_STATUS_MESSAGE: Final[Mapping[int, str]] = {
    404: "The requested resource was not found.",
    405: "That method is not allowed on this resource.",
}


def register_exception_handlers(app: FastAPI) -> None:
    """Wire every handler onto the app. Called from ``main.create_app``."""
    app.add_exception_handler(FeatureDeferredError, landexplorer_exception_handler)  # subclass first
    app.add_exception_handler(LandExplorerError, landexplorer_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
