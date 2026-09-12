"""structlog configuration — JSON logs, contextvar binding, and secret scrubbing.

CONTRACT.md §9.10: *"Structured JSON logs; ``request_id``, ``principal``, ``route``,
``status``, ``duration_ms``, ``job_id`` bound via contextvars. **Keys, tokens, and
``Authorization`` values are scrubbed by a logging filter before emission.**"*

The scrubber is not politeness. A traceback in this system carries connection
strings, storage paths and provider keys (§6.3), and logs get shipped to somewhere
with a much broader audience than the database ever had. Scrubbing at emission —
rather than trusting every call site to remember — is the only version of this that
holds up over time.
"""

from __future__ import annotations

import logging
import re
import sys
from contextlib import contextmanager
from typing import Any, Final, Iterator, MutableMapping

import structlog

from app.core.config import Settings, redact_url

__all__ = [
    "REDACTED",
    "bind_job_context",
    "bind_request_context",
    "clear_context",
    "configure_logging",
    "get_logger",
    "scrub_secrets",
]

REDACTED: Final = "***"

#: Key names whose *values* are dropped wholesale, matched case-insensitively on a
#: substring. Substring, not equality, because the field is `authorization` in one
#: place, `http.request.header.authorization` in another, and `auth_header` in a
#: third — and an exact-match list is a list somebody will forget to extend.
#:
#: ★ Note what is NOT here: a bare `key`. Every §-secret in §9 whose name contains
#: "key" is spelled out below instead (`bing_maps_key`, `google_maps_static_key`,
#: `storage_s3_access_key_id`, `secret_key`, `api_keys`), because a bare `key` would
#: also redact `storage.key`, `cache_key` and `idempotency_key` — none of which are
#: secrets, and all of which are exactly the field you need in the log line when
#: something has gone wrong with them. Over-redaction is not free: it costs the
#: diagnostic the line existed to carry.
_SECRET_KEY_PATTERN: Final = re.compile(
    r"(authorization|bearer|jwt|signature|session|cookie|credential"
    r"|secret|password|passwd|sentry[_-]?dsn"
    r"|token"  # access_token, refresh_token, mapbox_access_token
    r"|(?:api|access|maps|static|private|client|provider|license|subscription)[_-]?keys?"
    # client_id: an OAuth client id is a § secret in §9.6 (LE_COPERNICUS_CLIENT_ID),
    # even though "id" reads as innocuous — half of a credential pair is a credential.
    r"|client[_-]?id"
    r")",
    re.IGNORECASE,
)

#: Keys holding URLs that may embed credentials. The value is not dropped — knowing
#: *which* database was unreachable is the entire diagnostic value of the line — but
#: the password inside it is.
_URL_KEY_PATTERN: Final = re.compile(
    r"(database_url|db_url|redis_url|broker_url|result_backend|dsn|endpoint_url|url)$",
    re.IGNORECASE,
)

#: Secrets that arrive inside a *message string* rather than as a field.
_INLINE_PATTERNS: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    # Authorization: Bearer eyJ... / Basic dXNlcjpwYXNz
    (re.compile(r"(?i)\b(bearer|basic|apikey)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 " + REDACTED),
    # ?key=..., &access_token=..., token=... in a URL or a log line
    (
        re.compile(r"(?i)([?&](?:key|api_key|access_token|token|signature|sig)=)[^&\s\"']+"),
        r"\1" + REDACTED,
    ),
    # scheme://user:password@host — including scheme://:password@host (a Redis URL
    # with a password has an empty username) and passwords containing an unencoded
    # '@'. See config._URL_CREDENTIALS_RE for why each quantifier is what it is.
    (re.compile(r"(?<=://)([^/@\s:]*):([^/\s]*)@"), r"\1:" + REDACTED + "@"),
)

_MAX_SCRUB_DEPTH: Final = 6


def _scrub_value(key: str, value: Any, depth: int) -> Any:
    if depth > _MAX_SCRUB_DEPTH:
        # Bounded on purpose: a log processor that recurses without a limit turns a
        # deep or cyclic payload into a RecursionError *inside logging*, which
        # typically takes the request down with it.
        return value

    if _SECRET_KEY_PATTERN.search(key):
        return REDACTED

    if isinstance(value, str):
        if _URL_KEY_PATTERN.search(key):
            return _scrub_text(redact_url(value))
        return _scrub_text(value)

    if isinstance(value, MutableMapping):
        return {k: _scrub_value(str(k), v, depth + 1) for k, v in value.items()}

    if isinstance(value, (list, tuple)):
        scrubbed = [_scrub_value(key, item, depth + 1) for item in value]
        return type(value)(scrubbed) if isinstance(value, tuple) else scrubbed

    return value


def _scrub_text(text: str) -> str:
    for pattern, replacement in _INLINE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def scrub_secrets(
    _logger: Any, _method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor: redact secrets from every field before emission.

    Runs last-but-one in the chain, after everything that might *add* a field
    (contextvars, the exception formatter, the stdlib bridge) and before the
    renderer. Anything added after this point is not scrubbed, so nothing is.
    """
    return {str(k): _scrub_value(str(k), v, 0) for k, v in event_dict.items()}


def configure_logging(settings: Settings) -> None:
    """Configure structlog and the stdlib root logger. Idempotent.

    Called once from ``main.py``'s lifespan and once from the Celery worker bootstrap
    — the two entry points into this codebase. Everything else calls ``get_logger``.

    The stdlib root logger is routed through the same processor chain so that
    uvicorn's, SQLAlchemy's and Celery's log lines land in the same JSON shape and get
    the same scrubbing. A third-party library logging a connection string at DEBUG is
    a real thing that happens, and it must not be the one line that escapes.
    """
    level = getattr(logging, settings.log_level, logging.INFO)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if settings.log_format == "json":
        renderer: Any = structlog.processors.JSONRenderer()
        # format_exc_info turns exc_info into an `exception` string field. Only for
        # JSON: ConsoleRenderer renders tracebacks itself, and running both would
        # print the traceback twice.
        #
        # ★ It MUST come before scrub_secrets. A traceback is the single richest
        # source of secrets in this system — §6.3 is explicit that it carries storage
        # paths, connection strings and provider keys — and it does not exist as a
        # field until this processor materialises it. Appending it after the scrubber
        # means the one string most worth scrubbing is the one string never scrubbed.
        shared_processors.append(structlog.processors.format_exc_info)
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    # LAST. Everything that can add a field has now run; nothing added after this
    # point would be scrubbed, so nothing is added after this point.
    shared_processors.append(scrub_secrets)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    # Replace rather than append: configure_logging is idempotent, and uvicorn
    # installs its own handlers before our lifespan runs. Without this, every line is
    # emitted twice — once as JSON and once as uvicorn's default format.
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)

    # ★ The ring buffer behind ``GET /health/logs`` — the app-status page's log
    # monitor. Same root, same pre-chain, same scrubbing as stdout; the handler is
    # rebuilt on every (idempotent) call but the BUFFER is a singleton, so the
    # lines survive a reconfigure. Import here, not at module top: logbuffer must
    # stay importable without this module to avoid a cycle.
    from app.core.logbuffer import install_ring_buffer_handler

    root.addHandler(install_ring_buffer_handler(shared_processors, scrub_secrets))
    root.setLevel(level)

    # uvicorn.access duplicates what TimingMiddleware already records, with none of
    # the request_id binding. Silence it and keep the one that carries the context.
    logging.getLogger("uvicorn.access").handlers = []
    logging.getLogger("uvicorn.access").propagate = False
    logging.getLogger("uvicorn.error").propagate = True

    # SQLAlchemy echoes full statements at INFO when db_echo is on; at anything less
    # it is noise. LE_DB_ECHO is the switch, not the log level.
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.db_echo else logging.WARNING
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """A bound logger. Safe to call at module scope, before ``configure_logging``.

    structlog defers configuration until first use, so a module-level
    ``log = get_logger(__name__)`` picks up whatever configuration lands later.
    """
    return structlog.stdlib.get_logger(name)  # type: ignore[no-any-return]


def bind_request_context(
    *,
    request_id: str,
    route: str | None = None,
    method: str | None = None,
    principal: str | None = None,
) -> None:
    """Bind per-request fields to every log line emitted from this task/thread.

    contextvars, so it survives ``await`` and does not leak across concurrent
    requests. ``RequestIdMiddleware`` (IU-21, outermost) calls this so that *every*
    response — including the rejections from the middleware below it — carries a
    request id: the string a user pastes into a bug report.
    """
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        **{k: v for k, v in (("route", route), ("method", method), ("principal", principal)) if v is not None},
    )


def bind_job_context(*, job_id: str, job_type: str | None = None, attempt: int | None = None) -> None:
    """Bind per-job fields, the worker-side analogue of ``bind_request_context``."""
    structlog.contextvars.bind_contextvars(
        job_id=job_id,
        **{k: v for k, v in (("job_type", job_type), ("attempt", attempt)) if v is not None},
    )


def clear_context() -> None:
    """Drop all bound contextvars.

    Celery reuses worker processes across tasks, so without an explicit clear at the
    task boundary, job N+1's log lines inherit job N's ``job_id`` — which is worse
    than no context at all, because it is confidently wrong.
    """
    structlog.contextvars.clear_contextvars()


@contextmanager
def log_context(**fields: Any) -> Iterator[None]:
    """Bind fields for the duration of a block, then restore what was there before."""
    tokens = structlog.contextvars.bind_contextvars(**fields)
    try:
        yield
    finally:
        structlog.contextvars.reset_contextvars(**tokens)
