"""Shared FastAPI dependencies — the composition root of the HTTP layer (§6.4).

★ **EXEMPT from ``api-not-db``** (§6.4, §10.4). The import-linter contract's ``source_modules``
is ``app.api.v1`` — the routers — and this module is ``app.api.deps``, named as the exemption.
``Depends(get_db)`` is *how a session enters a request at all*; pushing it into ``app.services``
would give services a FastAPI dependency (which ``services-no-fastapi`` forbids — the stronger
rule) or invent a parallel injection mechanism to dodge a lint rule. So this module reaches
``app.db``, ``app.models`` and ``gis`` (via services); **routers still may not**. They receive
already-loaded entities from here and call services.

``get_project`` / ``get_image`` / … **raise ``NotFoundError`` themselves**, so no route body
repeats the existence check and the 404 is guaranteed to precede any body validation.
"""

from __future__ import annotations

from typing import AsyncIterator
from uuid import UUID

from fastapi import Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings as _get_settings
from app.core.exceptions import (
    ConfirmationRequired,
    JobNotCancellable,
    PreconditionRequired,
    ReadOnlyMode,
    WorkerUnavailable,
)
from app.core.idempotency import (
    IDEMPOTENCY_HEADER,
    IdempotencyContext,
    NullIdempotencyStore,
    build_store,
    fingerprint_request,
)
from app.core.pagination import PaginationParams
from app.core.queue import JobQueue, NullJobQueue
from app.core.security import ANONYMOUS_PRINCIPAL, Principal, authenticate
from app.db.repositories.jobs import JobRepository, JobView
from app.db.session import check_database, get_session
# ★ Router-facing re-exports (2026-09-02): the importlinter contract forbids
#   app.api.v1 importing app.db directly; deps is the sanctioned doorway. These
#   two are pure helpers routers legitimately need — the DB liveness probe and
#   the PostGIS point→(lon, lat) reader.
from app.db.types import as_lonlat  # noqa: F401
from app.models.annotation import Annotation
from app.models.export import Export
from app.models.gcp import GCP
from app.models.image import Image
from app.models.project import Project
from app.models.video import Video
from app.services.annotation_service import AnnotationService
from app.services.batch_service import BatchService
from app.services.capability_service import CapabilityService
from app.services.dem_service import DemService
from app.services.elevation_service import ElevationService
from app.services.export_service import ExportService
from app.services.gcp_service import GcpService
from app.services.heatmap_service import HeatmapService
from app.services.image_service import ImageService
from app.services.imagery_service import ImageryService
from app.services.kml_import_service import KmlImportService
from app.services.match_service import MatchService
from app.services.pose_service import PoseService
from app.services.project_service import ProjectService
from app.services.result_service import ResultService
from app.services.revision_service import RevisionService
from app.services.semantic_service import SemanticService
from app.services.suggestion_service import SuggestionService
from app.services.video_service import VideoService
from app.storage import get_storage as _get_storage
from app.storage.base import ObjectStorage

__all__ = [
    "cancel_job",
    "get_annotation",
    "get_annotation_service",
    "get_batch_service",
    "get_capability_service",
    "get_db",
    "get_elevation_service",
    "get_export",
    "get_export_service",
    "get_gcp",
    "get_gcp_service",
    "get_heatmap_service",
    "get_idempotency",
    "get_image",
    "get_image_service",
    "get_imagery_registry",
    "get_imagery_service",
    "get_job",
    "get_job_queue",
    "get_kml_import_service",
    "get_match_service",
    "get_pagination",
    "get_pose_service",
    "get_principal",
    "get_project",
    "get_project_service",
    "get_result_service",
    "get_revision_service",
    "get_semantic_service",
    "get_settings",
    "get_sort",
    "get_storage",
    "get_suggestion_service",
    "get_video",
    "require_confirm_delete",
    "require_if_match",
    "require_worker",
    "require_writable",
]


# ── infrastructure ─────────────────────────────────────────────────────────────


async def get_db() -> AsyncIterator[AsyncSession]:
    """The request-scoped async session. Commits on success, rolls back on error (§6.4)."""
    async for session in get_session():
        yield session


def get_settings() -> Settings:
    """The process-wide settings singleton."""
    return _get_settings()


def get_storage() -> ObjectStorage:
    """The process-wide object storage backend."""
    return _get_storage()


def get_dem_service(
    settings: Settings = Depends(get_settings),
    storage: ObjectStorage = Depends(get_storage),
) -> DemService:
    """The DEM processing service.

    ★ No session: a DEM run is a stateless file transformation and owns no row
    (``app.services.dem_service``). It needs storage and the upload cap, nothing else.
    """
    return DemService(settings, storage)


def get_imagery_registry(request: Request):
    """The shared ``ProviderRegistry`` built once at boot and cached on ``app.state``.

    A new registry per request would rebuild every provider's connection pool and metadata
    cache; the composition root builds it once (§ imagery_service).
    """
    registry = getattr(request.app.state, "imagery_registry", None)
    if registry is None:  # a script or a test that skipped the lifespan — build a throwaway.
        from app.services.imagery_service import build_registry

        registry = build_registry(get_settings())
    return registry


def get_job_queue(request: Request) -> JobQueue:
    """The injected ``JobQueue``. ``NullJobQueue`` when no broker was wired (refuses loudly)."""
    queue = getattr(request.app.state, "job_queue", None)
    return queue if queue is not None else NullJobQueue()


# ── principal / auth ───────────────────────────────────────────────────────────


async def get_principal(request: Request, settings: Settings = Depends(get_settings)) -> Principal:
    """Resolve the caller. ``ANONYMOUS_PRINCIPAL`` when ``LE_AUTH_MODE=none`` (the default)."""
    if settings.auth_mode == "none":
        principal = ANONYMOUS_PRINCIPAL
    else:
        authorization = request.headers.get("authorization", "")
        bearer = authorization[7:].strip() if authorization.lower().startswith("bearer ") else None
        principal = authenticate(
            settings,
            api_key=request.headers.get("x-api-key"),
            bearer_token=bearer,
            cookie_token=request.cookies.get("session"),
        )
    request.state.principal = principal.subject
    return principal


# ── pagination / sorting ───────────────────────────────────────────────────────


def get_pagination(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> PaginationParams:
    """A validated ``?limit=&offset=`` pair. Out of range is a 422, never a silent clamp."""
    return PaginationParams(limit=limit, offset=offset)


def get_sort(sort: str | None = Query(None)) -> str | None:
    """The raw ``?sort=`` string.

    ★ Returned **unparsed**, deliberately. §6.4 types this ``-> SortParams``, but
    ``core.pagination.SortParams.parse`` needs the endpoint's field whitelist, which only the
    router knows. Each router calls ``SortParams.parse(raw, allowed=…, default=…)`` — one line,
    with the whitelist in view — rather than this dependency guessing which resource it serves.
    """
    return sort


# ── entity loaders — each raises NotFoundError itself (§6.4) ───────────────────


async def get_project(
    project_id: UUID,
    include_deleted: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> Project:
    return await ProjectService(db).get(project_id, include_deleted=include_deleted)


async def get_image(
    image_id: UUID,
    include_deleted: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> Image:
    return await ImageService(db, get_settings(), storage=_get_storage()).get(
        image_id, include_deleted=include_deleted
    )


async def get_video(
    video_id: UUID,
    include_deleted: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> Video:
    return await VideoService(db, get_settings(), storage=_get_storage()).get(
        video_id, include_deleted=include_deleted
    )


async def get_annotation(
    annotation_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> Annotation:
    return await AnnotationService(db).get(annotation_id)


async def get_gcp(
    gcp_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> GCP:
    from app.core.exceptions import GcpNotFound
    from app.db.repositories.gcps import GcpRepository

    gcp = await GcpRepository(db).get(gcp_id)
    if gcp is None:
        raise GcpNotFound(f"No GCP {gcp_id}.")
    return gcp


async def get_export(
    export_id: UUID,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Export:
    return await ExportService(db, settings).get(export_id)


async def get_job(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> JobView:
    """One job of any type, from the ``v_jobs`` union — or ``JobNotFound`` (§6.4)."""
    return await JobRepository(db).get_view_or_raise(job_id)


async def fetch_job_view(db: AsyncSession, job_id: UUID) -> JobView:
    """Read a job's ``v_jobs`` row inside a handler — for building a ``202`` body.

    The row is flushed by the service before this runs, so the union sees it. Not a
    dependency: it takes an id known only after the enqueue.
    """
    await db.flush()
    return await JobRepository(db).get_view_or_raise(job_id)


async def list_job_views(db: AsyncSession, **kwargs) -> tuple[list[JobView], int]:
    """``GET /jobs`` (31) — there is no ``JobService``; deps owns the ``v_jobs`` read."""
    return await JobRepository(db).list_views(**kwargs)


async def list_gcps_for_image(db: AsyncSession, image_id: UUID, **kwargs):
    """``GET /images/{id}/gcps`` (38) — the read path GcpService does not expose."""
    from app.db.repositories.gcps import GcpRepository

    return await GcpRepository(db).list_for_image(image_id, **kwargs)


async def list_gcps_for_match_result(db: AsyncSession, match_result_id: UUID, **kwargs):
    """``GET /match-results/{id}/gcps`` (64) — empty in this build (no match rows)."""
    from app.db.repositories.gcps import GcpRepository

    return await GcpRepository(db).list_for_match_result(match_result_id, **kwargs)


# ── service factories (routers construct nothing that touches the DB) ──────────


def get_project_service(db: AsyncSession = Depends(get_db)) -> ProjectService:
    return ProjectService(db)


def get_image_service(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    request: Request = None,  # type: ignore[assignment]
) -> ImageService:
    queue = get_job_queue(request) if request is not None else NullJobQueue()
    return ImageService(db, settings, storage=_get_storage(), queue=queue)


def get_annotation_service(db: AsyncSession = Depends(get_db)) -> AnnotationService:
    return AnnotationService(db)


def get_revision_service(db: AsyncSession = Depends(get_db)) -> RevisionService:
    return RevisionService(db)


def get_gcp_service(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    request: Request = None,  # type: ignore[assignment]
) -> GcpService:
    imagery = ImageryService(settings, registry=get_imagery_registry(request)) if request is not None else None
    return GcpService(db, settings, imagery=imagery)


def get_elevation_service(settings: Settings = Depends(get_settings)) -> ElevationService:
    """The project DEM sampler.

    ★ No session: an elevation sample reads a raster, owns no row, and is deliberately
    independent of the database — a project's Z source is a file on disk, keyed by
    project id (``ElevationService._project_provider``).
    """
    return ElevationService(settings)


def get_kml_import_service(db: AsyncSession = Depends(get_db)) -> KmlImportService:
    """The KML/KMZ placemark importer.

    ★ No imagery service and no settings: an import reads a file the operator supplied
    and moves existing points. It resolves no provider, samples no DEM, and derives no
    accuracy — so it needs nothing but the repository it writes through.
    """
    from app.db.repositories.gcps import GcpRepository

    return KmlImportService(GcpRepository(db))


def get_match_service(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    request: Request = None,  # type: ignore[assignment]
) -> MatchService:
    queue = get_job_queue(request) if request is not None else NullJobQueue()
    return MatchService(db, settings, queue=queue)


def get_result_service(db: AsyncSession = Depends(get_db)) -> ResultService:
    return ResultService(db)


def get_suggestion_service(db: AsyncSession = Depends(get_db)) -> SuggestionService:
    return SuggestionService(db)


def get_semantic_service(db: AsyncSession = Depends(get_db)) -> SemanticService:
    return SemanticService(db)


def get_pose_service(db: AsyncSession = Depends(get_db)) -> PoseService:
    return PoseService(db)


def get_heatmap_service(db: AsyncSession = Depends(get_db)) -> HeatmapService:
    return HeatmapService(db)


def get_batch_service(db: AsyncSession = Depends(get_db)) -> BatchService:
    return BatchService(db)


def get_export_service(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    request: Request = None,  # type: ignore[assignment]
) -> ExportService:
    queue = get_job_queue(request) if request is not None else NullJobQueue()
    return ExportService(db, settings, queue=queue)


def get_imagery_service(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> ImageryService:
    return ImageryService(settings, registry=get_imagery_registry(request))


def get_capability_service(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> CapabilityService:
    imagery = ImageryService(settings, registry=get_imagery_registry(request))
    report = getattr(request.app.state, "preflight_report", None)
    return CapabilityService(settings, imagery=imagery, preflight_report=report)


# ── guards / headers ───────────────────────────────────────────────────────────


def require_writable(settings: Settings = Depends(get_settings)) -> None:
    """403 ``READ_ONLY_MODE`` when ``LE_READ_ONLY=true``."""
    if settings.read_only:
        raise ReadOnlyMode("The server is in read-only mode; writes are refused.")


async def require_worker(request: Request) -> None:
    """503 ``WORKER_UNAVAILABLE`` when no job queue is wired.

    Reported precisely at the operation that needs a worker (§7.1), so a missing worker does
    not blanket-fail readiness.
    """
    queue = getattr(request.app.state, "job_queue", None)
    if queue is None or isinstance(queue, NullJobQueue):
        raise WorkerUnavailable(
            "No Celery worker is available to run this job. Check that the broker "
            "(LE_CELERY_BROKER_URL) is reachable and a worker is running."
        )


def require_if_match(request: Request) -> str:
    """The ``If-Match`` header value, unquoted — 428 ``PRECONDITION_REQUIRED`` when absent."""
    raw = request.headers.get("if-match")
    if not raw or not raw.strip():
        raise PreconditionRequired(
            "This operation requires an If-Match header carrying the resource's current "
            "ETag (optimistic concurrency)."
        )
    return raw.strip().strip('"').removeprefix("W/").strip('"')


def require_confirm_delete(request: Request) -> None:
    """428 ``CONFIRMATION_REQUIRED`` when a hard delete omits ``X-Confirm-Delete: true``."""
    value = request.headers.get("x-confirm-delete", "").strip().lower()
    if value not in ("true", "1", "yes"):
        raise ConfirmationRequired(
            "A destructive operation requires the header X-Confirm-Delete: true."
        )


async def get_idempotency(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> IdempotencyContext:
    """Build the per-request idempotency handle from the ``Idempotency-Key`` header (§ core)."""
    key = request.headers.get(IDEMPOTENCY_HEADER)
    redis = getattr(request.app.state, "redis", None)
    store = build_store(settings, redis) if key is not None else NullIdempotencyStore()
    try:
        body = await request.body()
    except Exception:  # noqa: BLE001 — a streamed multipart body is not re-readable here.
        body = b""
    fingerprint = fingerprint_request(method=request.method, path=request.url.path, body=body or None)
    return IdempotencyContext(key=key, fingerprint=fingerprint, store=store)


# ── job cancel (there is no JobService; deps owns the state transition) ────────


async def cancel_job(db: AsyncSession, job: JobView) -> tuple[JobView, int]:
    """``DELETE /jobs/{id}`` (33) — the cooperative-cancel state machine.

    * terminal              → ``409 JOB_NOT_CANCELLABLE``.
    * ``running``           → set ``cancel_requested`` (the worker unwinds itself) → **202**.
    * ``pending``/queued/…  → ``mark_cancelled`` immediately                       → **200**.

    Returns ``(refreshed_view, status_code)``.
    """
    if job.is_terminal:
        raise JobNotCancellable(
            f"Job {job.id} is already {job.status.value}; a finished job cannot be cancelled."
        )
    repo = JobRepository(db)
    model = job.model
    if job.status.value == "running":
        await repo.request_cancel(model, job.id)
        status_code = 202
    else:
        await repo.mark_cancelled(model, job.id)
        status_code = 200
    refreshed = await repo.get_view_or_raise(job.id)
    return refreshed, status_code
