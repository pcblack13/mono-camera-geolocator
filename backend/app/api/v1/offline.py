"""Offline Area Manager + imagery usage — the ``/imagery/offline/*`` endpoints.

★ Same layering as the other routers: this file holds NO logic and NO ``gis`` imports —
``OfflineCacheService`` owns enumeration, budgets, workers and manifests, and raises
``app.core.exceptions`` types that the global handlers map to HTTP outcomes
(``PRECACHE_BUDGET_EXCEEDED`` → 422, ``PRECACHE_OPERATION_NOT_FOUND`` → 404, …).

★ ``def``, not ``async def`` (§7.2.1): estimate/coverage walk the disk cache and belong
in the threadpool, exactly like the tile proxy.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from starlette.responses import Response

from app.api import deps
from app.core.config import Settings
from app.schemas.viewport_cache import AutoCacheStatus, AutoCacheToggle, ViewportReport
from app.schemas.offline import (
    OfflineAreaRequest,
    OfflineCoverage,
    OfflineEstimate,
    OfflineManifest,
    PrecacheOperation,
    PrecacheStartRequest,
)
from app.services.imagery_service import ImageryService
from app.services.offline_cache_service import OfflineCacheService

router = APIRouter()


def _service(request: Request, settings: Settings) -> OfflineCacheService:
    imagery = ImageryService(settings, registry=deps.get_imagery_registry(request))
    return OfflineCacheService(settings, imagery=imagery)


@router.post(
    "/imagery/offline/estimate",
    response_model=OfflineEstimate,
    summary="Estimate an offline area (tiles, requests, storage) without downloading",
)
def estimate_offline_area(
    body: OfflineAreaRequest,
    request: Request,
    settings: Settings = Depends(deps.get_settings),
) -> OfflineEstimate:
    return _service(request, settings).estimate(body)


@router.post(
    "/imagery/offline/coverage",
    response_model=OfflineCoverage,
    summary="How much of an AOI the tile cache already holds",
)
def offline_coverage(
    body: OfflineAreaRequest,
    request: Request,
    settings: Settings = Depends(deps.get_settings),
) -> OfflineCoverage:
    return _service(request, settings).coverage(body)


@router.post(
    "/imagery/offline/operations",
    response_model=PrecacheOperation,
    status_code=201,
    summary="Start downloading an offline area (budget-checked)",
)
def start_precache(
    body: PrecacheStartRequest,
    request: Request,
    settings: Settings = Depends(deps.get_settings),
) -> PrecacheOperation:
    return _service(request, settings).start(body)


@router.get(
    "/imagery/offline/operations",
    response_model=list[PrecacheOperation],
    summary="List pre-cache operations (this process)",
)
def list_precache_operations(
    request: Request,
    settings: Settings = Depends(deps.get_settings),
) -> list[PrecacheOperation]:
    return _service(request, settings).list_operations()


@router.get(
    "/imagery/offline/operations/{op_id}",
    response_model=PrecacheOperation,
    summary="One pre-cache operation's live progress",
)
def get_precache_operation(
    op_id: str,
    request: Request,
    settings: Settings = Depends(deps.get_settings),
) -> PrecacheOperation:
    return _service(request, settings).get_operation(op_id)


@router.post(
    "/imagery/offline/operations/{op_id}/pause",
    response_model=PrecacheOperation,
    summary="Pause a running download",
)
def pause_precache(
    op_id: str,
    request: Request,
    settings: Settings = Depends(deps.get_settings),
) -> PrecacheOperation:
    return _service(request, settings).pause(op_id)


@router.post(
    "/imagery/offline/operations/{op_id}/resume",
    response_model=PrecacheOperation,
    summary="Resume a paused download",
)
def resume_precache(
    op_id: str,
    request: Request,
    settings: Settings = Depends(deps.get_settings),
) -> PrecacheOperation:
    return _service(request, settings).resume(op_id)


@router.post(
    "/imagery/offline/operations/{op_id}/cancel",
    response_model=PrecacheOperation,
    summary="Cancel a download",
)
def cancel_precache(
    op_id: str,
    request: Request,
    settings: Settings = Depends(deps.get_settings),
) -> PrecacheOperation:
    return _service(request, settings).cancel(op_id)


@router.post(
    "/imagery/offline/operations/{op_id}/retry",
    response_model=PrecacheOperation,
    summary="Retry a stopped operation's failed tiles",
)
def retry_precache(
    op_id: str,
    request: Request,
    settings: Settings = Depends(deps.get_settings),
) -> PrecacheOperation:
    return _service(request, settings).retry_failed(op_id)


@router.get(
    "/imagery/offline/manifests",
    response_model=list[OfflineManifest],
    summary="List downloaded offline areas",
)
def list_offline_manifests(
    request: Request,
    settings: Settings = Depends(deps.get_settings),
) -> list[OfflineManifest]:
    return _service(request, settings).list_manifests()


@router.delete(
    "/imagery/offline/manifests/{manifest_id}",
    status_code=204,
    response_class=Response,
    summary="Forget an offline area (tiles stay until TTL/size GC reclaims them)",
)
def delete_offline_manifest(
    manifest_id: str,
    request: Request,
    settings: Settings = Depends(deps.get_settings),
) -> Response:
    _service(request, settings).delete_manifest(manifest_id)
    return Response(status_code=204)


# ── automatic viewport caching ────────────────────────────────────────────────


@router.post(
    "/imagery/cache/viewport",
    response_model=AutoCacheStatus,
    summary="Report a settled map viewport; queues automatic caching, returns coverage",
)
def report_viewport(
    body: ViewportReport,
    request: Request,
    settings: Settings = Depends(deps.get_settings),
) -> AutoCacheStatus:
    from app.services.viewport_cache_service import get_viewport_cache_manager

    imagery = ImageryService(settings, registry=deps.get_imagery_registry(request))
    return get_viewport_cache_manager(settings).report_viewport(imagery, body)


@router.get(
    "/imagery/cache/status",
    response_model=AutoCacheStatus,
    summary="Automatic-cache status: coverage, queue depth, session tallies",
)
def auto_cache_status(
    settings: Settings = Depends(deps.get_settings),
) -> AutoCacheStatus:
    from app.services.viewport_cache_service import get_viewport_cache_manager

    return get_viewport_cache_manager(settings).status()


@router.put(
    "/imagery/cache/enabled",
    response_model=AutoCacheStatus,
    summary="Turn automatic viewport caching on/off (cached tiles always keep serving)",
)
def set_auto_cache_enabled(
    body: AutoCacheToggle,
    settings: Settings = Depends(deps.get_settings),
) -> AutoCacheStatus:
    from app.services.viewport_cache_service import get_viewport_cache_manager

    manager = get_viewport_cache_manager(settings)
    manager.set_enabled(body.enabled)
    return manager.status()


@router.get(
    "/imagery/usage",
    summary="Application-level imagery usage statistics (NOT the provider's billing page)",
)
def imagery_usage(
    request: Request,
    settings: Settings = Depends(deps.get_settings),
) -> dict[str, object]:
    imagery = ImageryService(settings, registry=deps.get_imagery_registry(request))
    return imagery.usage_snapshot()
