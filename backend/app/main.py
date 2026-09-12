"""``create_app`` · lifespan · middleware · router mount · exception handlers (§2.4).

★ **Preflight runs ONCE, here, and the ``PreflightReport`` is cached on ``app.state``** (§11.1):
``GET /capabilities`` reads that cache and never re-resolves. The composition root also builds the
imagery registry, the Redis client, the job queue, the object storage — each **once** — and injects
them via ``app.state`` so ``deps`` can hand them to services.

★ ``Settings()`` with an empty environment NEVER raises (L10), so ``uvicorn app.main:app`` with no
``.env`` **starts** and ``/health/ready`` returns a 503 *diagnosis* rather than a boot traceback
(§9.13). Every dependency is built defensively: a missing Redis or worker degrades to a warning and
a null implementation, never a crash at boot (L11).
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from starlette.responses import Response

from app.api.errors import register_exception_handlers
from app.api.middleware import (
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
    RequestIdMiddleware,
    TimingMiddleware,
)
from app.api.v1.router import api_router, assert_no_duplicate_routes
from app.core.config import Settings, get_settings
from app.core.exceptions import NotFoundError
from app.core.logging import configure_logging, get_logger

__all__ = ["API_VERSION", "app", "create_app"]

API_VERSION = "1.0.0"

log = get_logger(__name__)

#: The browser-visible response headers CORS must expose. **Not optional detail** (§6.5): every
#: mechanism this API relies on is header-carried, and omitting one silently disables a feature in
#: the browser only — passing every curl-based test.
_EXPOSE_HEADERS = [
    "ETag",
    "Location",
    "Retry-After",
    "X-Request-ID",
    "X-API-Version",
    "X-RateLimit-Limit",
    "X-RateLimit-Remaining",
    "X-RateLimit-Reset",
    "X-Imagery-Attribution",
    "X-Imagery-Provider",
    "X-Cache",
    "X-Heatmap-BBox",
    "X-Heatmap-Score-Range",
    "X-Checksum-SHA256",
    "Content-Disposition",
    "Idempotency-Replayed",
    "X-Response-Time-ms",
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build every process-wide singleton once; tear them down on shutdown."""
    settings: Settings = app.state.settings
    app.state.start_time = time.monotonic()

    app.state.preflight_report = _run_preflight(settings)
    app.state.imagery_registry = _build_registry(settings)
    app.state.redis = _build_redis(settings)
    app.state.job_queue = _build_job_queue(settings)
    app.state.tile_cache_sweeper_stop = _start_tile_cache_sweeper(settings)
    _warm_detection_probe(settings)
    _schedule_camera_reconcile(settings)

    assert_no_duplicate_routes(app)  # ★ fail fast on a shadowed (method, path) (§7)
    log.info("api.started", version=API_VERSION, env=settings.env)
    try:
        yield
    finally:
        await _shutdown(app)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Construct the ASGI app. Pure — no I/O until the lifespan runs."""
    settings = settings or get_settings()
    configure_logging(settings)

    app = FastAPI(
        title=settings.app_name,
        version=API_VERSION,
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )
    app.state.settings = settings

    _add_middleware(app, settings)
    register_exception_handlers(app)
    app.include_router(api_router)
    _add_metrics_route(app, settings)
    _mount_frontend(app, settings)
    return app


# ── the built SPA, for desktop / single-origin deployments ──────────────────────


def _mount_frontend(app: FastAPI, settings: Settings) -> None:
    """Serve the built frontend when ``LE_SERVE_FRONTEND_DIR`` points at a dist.

    ★ Registered LAST, as a catch-all: every real route above wins first, so this can
    never shadow the API. Reserved prefixes still 404 as JSON — a typo'd API call
    must fail like an API call, not answer with HTML the client then JSON-parses.

    ★ Deep links work: ``/projects/abc`` is not a file, so it falls back to
    ``index.html`` and the client router takes over — the same contract nginx's
    ``try_files`` gives the web deployment.
    """
    root = settings.serve_frontend_dir
    if root is None:
        return
    root = root.resolve()
    index = root / "index.html"
    if not index.is_file():
        log.warning("LE_SERVE_FRONTEND_DIR=%s has no index.html; not serving a frontend", root)
        return
    log.info("serving frontend from %s", root)

    _reserved = ("api/", "docs", "redoc", "openapi.json", "metrics")

    @app.get("/{spa_path:path}", include_in_schema=False)
    async def spa(spa_path: str) -> FileResponse:  # pragma: no cover - exercised by desktop
        if spa_path.startswith(_reserved):
            raise NotFoundError(f"No such path: /{spa_path}")
        candidate = (root / spa_path).resolve() if spa_path else index
        # ★ Traversal-guarded: only real files INSIDE the dist are served as files.
        if candidate.is_file() and candidate.is_relative_to(root):
            # ★ THE SPA CACHING CONTRACT, stated explicitly because its absence shipped a
            #   stale app: with no Cache-Control, Chromium HEURISTICALLY caches (10% of
            #   time-since-Last-Modified), so after an upgrade the desktop window kept
            #   rendering the PREVIOUS build's index.html — new code on disk, old app on
            #   screen. Vite's /assets/* are content-hashed → immutable forever; anything
            #   unhashed must revalidate every load.
            headers = (
                {"Cache-Control": "public, max-age=31536000, immutable"}
                if spa_path.startswith("assets/")
                else {"Cache-Control": "no-cache"}
            )
            return FileResponse(candidate, headers=headers)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


# ── middleware ──────────────────────────────────────────────────────────────────


def _add_middleware(app: FastAPI, settings: Settings) -> None:
    """Wire the §6.5 stack. ``add_middleware`` makes the LAST-added the OUTERMOST, so this adds
    innermost-first: GZip → RateLimit → BodySizeLimit → Timing → CORS → RequestId (outermost).
    """
    # GZip — innermost (just above the router). minimum_size 1024, JSON-oriented.
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(RateLimitMiddleware, settings=settings)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.upload_max_bytes)
    app.add_middleware(TimingMiddleware)
    # ★ allow_origins=["*"] is NEVER used — incompatible with credentials, and the habit ships.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=_EXPOSE_HEADERS,
    )
    app.add_middleware(RequestIdMiddleware, header=settings.request_id_header)  # outermost


def _add_metrics_route(app: FastAPI, settings: Settings) -> None:
    """``GET /metrics`` — Prometheus, same port, **not** under ``/api/v1`` and excluded from OpenAPI."""
    if not settings.metrics_enabled:
        return

    @app.get(settings.metrics_path, include_in_schema=False)
    def metrics_endpoint() -> Response:  # pragma: no cover - trivial passthrough
        from app.observability.metrics import render_metrics

        body, content_type = render_metrics()
        return Response(content=body, media_type=content_type)


# ── singletons built at boot (each degrades to a safe default, never crashes) ──


def _run_preflight(settings: Settings) -> Any:
    """``ai_engine.models.preflight()`` — ONCE. Cached; ``/capabilities`` reads it (§11.1).

    Call-time import: ``ai_engine`` is heavy and its absence must not stop the API booting. In
    this build every deep path resolves to *deferred* (SCOPE.md §6); a failed or missing preflight
    degrades to ``None`` and ``/capabilities`` reports what it can read cheaply.
    """
    try:
        # ★ THE FUNCTION, NOT THE PACKAGE ATTRIBUTE (2026-08-30). `ai_engine.models`
        #   exposes `preflight` as its SUBMODULE, so the old `from ai_engine.models
        #   import preflight; preflight()` raised "'module' object is not callable"
        #   on every boot and the report was never produced — /capabilities has
        #   been answering from defaults since the day this was written. It also
        #   takes the engine config, defaulted on a zero-env boot, and the real
        #   per-kind component config so the resolution matches a real job's.
        from ai_engine.config import AiEngineConfig
        from ai_engine.models.preflight import preflight

        try:
            from ai_engine.pipeline.compose import component_config
        except Exception:  # noqa: BLE001 — the minimal builder is a documented fallback
            component_config = None

        config = AiEngineConfig()
        report = (
            preflight(config, component_config=component_config)
            if component_config is not None
            else preflight(config)
        )
        log.info("preflight.completed")
        return report
    except Exception as exc:  # noqa: BLE001 — preflight must never stop boot (L11).
        log.warning("preflight.unavailable", error=f"{type(exc).__name__}: {exc}")
        return None


def _build_registry(settings: Settings) -> Any:
    try:
        from app.services.imagery_service import build_registry

        return build_registry(settings)
    except Exception as exc:  # noqa: BLE001
        log.warning("imagery.registry_unavailable", error=f"{type(exc).__name__}: {exc}")
        return None


def _warm_detection_probe(settings: Settings) -> None:
    """Import the detection runtime in the background, so no page waits on it.

    Costs nothing on a machine with no model weights — see `warm_probe`.
    """
    try:
        from app.services import detection_service

        detection_service.warm_probe(settings.detection_model_dir)
    except Exception as exc:  # noqa: BLE001 — warming must never block startup
        log.warning("detection.warm_unavailable", error=f"{type(exc).__name__}: {exc}")


def _schedule_camera_reconcile(settings: Settings) -> None:
    """Bring back what the cameras were asked to do (2026-09-02).

    ★ Detection sessions, drift watches and data feeds are in-memory threads by
    design — a restart ends them. ``cameras.desired`` records the operator's intent
    for each registered camera, and this walks it a few seconds after boot and
    starts whatever it says. Never blocks startup, never raises; a camera that
    cannot come back (no weights, device unplugged) is one warning line and keeps
    its intent for the next boot. Skipped when there is no database to read.
    """
    if not settings.cameras_reconcile_at_boot:
        log.info("cameras.reconcile_disabled")
        return
    try:
        from app.services import camera_service

        camera_service.schedule_boot_reconcile(settings)
    except Exception as exc:  # noqa: BLE001 — must never block startup
        log.warning("cameras.reconcile_unavailable", error=f"{type(exc).__name__}: {exc}")


def _start_tile_cache_sweeper(settings: Settings) -> Any:
    """Desktop-friendly cache GC: a startup sweep + a periodic one, no Celery needed.

    ★ Server deployments keep the hourly beat task too — the sweep is idempotent and
    self-limiting, so firing from both is harmless.
    """
    try:
        from app.services.tile_cache_maintenance import start_periodic_sweeper

        return start_periodic_sweeper(settings)
    except Exception as exc:  # noqa: BLE001 — maintenance must never block startup
        log.warning("tile_cache.sweeper_unavailable", error=f"{type(exc).__name__}: {exc}")
        return None


def _build_redis(settings: Settings) -> Any:
    """A shared Redis client, or None. Powers idempotency, the rate limiter and job long-poll.

    Call-time import (``redis`` is optional) and defensive connect: a missing or unreachable Redis
    degrades every consumer to fail-open, never a boot crash (§6.5, L11).
    """
    try:
        import redis  # type: ignore[import-not-found]

        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2)
        client.ping()
        log.info("redis.connected", url=settings.redacted_redis_url())
        return client
    except Exception as exc:  # noqa: BLE001
        log.warning("redis.unavailable", url=settings.redacted_redis_url(), error=f"{type(exc).__name__}: {exc}")
        return None


def _build_job_queue(settings: Settings) -> Any:
    """The ``JobQueue`` implementation (Celery), or ``NullJobQueue`` when tasks are unavailable.

    ``app.tasks.queue.CeleryJobQueue`` is IU-20's; it may not be present in this build. A
    ``NullJobQueue`` refuses loudly at submit time rather than dropping work silently.
    """
    from app.core.queue import NullJobQueue

    try:
        from app.tasks.queue import CeleryJobQueue  # type: ignore[import-not-found]

        # ★ CeleryJobQueue takes the CELERY APP (or none → the process-wide app built from
        #   settings via get_celery_app()), NOT the Settings object. Passing `settings` here
        #   set `self._app = settings`, so `self._app.send_task(...)` raised
        #   `'Settings' object has no attribute 'send_task'` — caught and reported as
        #   WORKER_UNAVAILABLE, making EVERY enqueue (ingest, export, …) 503 even with a live
        #   broker and worker. No argument = the correctly-configured process app.
        return CeleryJobQueue()
    except Exception as exc:  # noqa: BLE001
        log.warning("job_queue.null", reason=f"{type(exc).__name__}: {exc}")
        return NullJobQueue()


async def _shutdown(app: FastAPI) -> None:
    from app.db.session import dispose_engines

    sweeper_stop = getattr(app.state, "tile_cache_sweeper_stop", None)
    if sweeper_stop is not None:
        try:
            sweeper_stop.set()
        except Exception:  # noqa: BLE001
            pass
    try:
        await dispose_engines()
    except Exception as exc:  # noqa: BLE001
        log.warning("db.dispose_failed", error=str(exc))
    client = getattr(app.state, "redis", None)
    if client is not None:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass
    log.info("api.stopped")


#: The ASGI application. ``uvicorn app.main:app``.
app = create_app()
