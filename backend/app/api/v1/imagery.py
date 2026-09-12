"""Imagery providers and the tile proxy — endpoints 50–53 (§7.2).

★ SCOPE.md §3: the provider abstraction, the keyless Esri default and the server-side tile proxy
are BUILT in full — the surveyor's satellite pane, half the product with matching deferred.

★ **Endpoints 51, 52, 53 are declared ``def``, not ``async def``** (§7.2.1): ``ImageryProvider``
is synchronous, and a sync ``httpx`` call inside an ``async def`` blocks the event loop for the
whole worker process — taking ``/health`` down with it. Starlette runs ``def`` routes in the
threadpool. The ``gis``-error translation lives in :mod:`app.api.tileproxy` (a router may not
import ``gis``).
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, Query, Request
from starlette.responses import Response

from app.api import deps, tileproxy
from app.core.config import Settings
from app.core.exceptions import InvalidBBox, ProviderUpstreamError
from app.schemas.common import BBox, Page
from app.schemas.imagery import GeocodeResult, ProviderInfo
from app.services.imagery_service import ImageryService

router = APIRouter()


def _geocode(settings: Settings, query: str, limit: int) -> list[GeocodeResult]:
    """Resolve a place name to coordinates through the configured geocoder (Nominatim).

    ★ Sync ``httpx`` on purpose: this route is ``def`` (threadpool), for the very reason
    the tile proxy is — a blocking call inside ``async def`` would stall the event loop.
    Offline surveying is a first-class mode here, so a network failure (or ``imagery_offline``)
    is a clean 502 the UI can explain, never a 500.
    """
    if settings.imagery_offline:
        raise ProviderUpstreamError(
            "Place-name search needs an internet connection, and imagery is in offline mode. "
            "Type latitude/longitude directly instead."
        )
    params = {
        "q": query,
        "format": "jsonv2",
        "limit": str(limit),
        "addressdetails": "0",
    }
    headers = {"User-Agent": settings.imagery_user_agent, "Accept": "application/json"}
    try:
        resp = httpx.get(
            settings.geocode_url,
            params=params,
            headers=headers,
            timeout=settings.imagery_request_timeout_seconds,
            follow_redirects=True,
        )
        resp.raise_for_status()
        rows = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ProviderUpstreamError(
            f"The geocoder could not be reached: {exc}. Check the connection, or type "
            "latitude/longitude directly."
        ) from exc

    results: list[GeocodeResult] = []
    for row in rows if isinstance(rows, list) else []:
        try:
            lat = float(row["lat"])
            lon = float(row["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        bbox = None
        bb = row.get("boundingbox")
        # Nominatim order is [south, north, west, east]; BBox is (min_lon, min_lat, max_lon, max_lat).
        if isinstance(bb, (list, tuple)) and len(bb) == 4:
            try:
                south, north, west, east = (float(v) for v in bb)
                bbox = BBox(min_lon=west, min_lat=south, max_lon=east, max_lat=north)
            except (ValueError, TypeError):
                bbox = None
        results.append(
            GeocodeResult(
                display_name=str(row.get("display_name") or query),
                lat=lat,
                lon=lon,
                category=row.get("type") or row.get("category"),
                bbox=bbox,
            )
        )
    return results


@router.get("/imagery/geocode", response_model=list[GeocodeResult], summary="Search for a place by name")
def geocode(
    q: str = Query(..., min_length=1, max_length=200, description="A place name, address, or landmark."),
    limit: int | None = Query(None, ge=1, le=25),
    settings: Settings = Depends(deps.get_settings),
) -> list[GeocodeResult]:
    """Turn a typed place name into coordinates the map can fly to.

    ★ A server-side proxy for the same reason the tile fetch is one: it keeps the outbound
    call (and its User-Agent / rate-limit obligations) on the backend, and it lets an
    offline deployment answer with a clear 502 instead of a browser CORS failure.
    """
    n = limit if limit is not None else settings.geocode_max_results
    return _geocode(settings, q.strip(), n)


@router.get("/imagery/providers", response_model=Page[ProviderInfo], summary="List imagery providers")
def list_providers(
    request: Request,
    pagination=Depends(deps.get_pagination),
    configured: bool | None = Query(None),
    supports_offline: bool | None = Query(None),
    kind: str | None = Query(None),
    settings: Settings = Depends(deps.get_settings),
) -> Page[ProviderInfo]:
    service = ImageryService(settings, registry=deps.get_imagery_registry(request))
    infos = service.list_provider_info()
    if configured is not None:
        infos = [i for i in infos if i.configured == configured]
    if supports_offline is not None:
        infos = [i for i in infos if i.capabilities.supports_offline == supports_offline]
    if kind is not None:
        infos = [i for i in infos if kind in i.capabilities.kinds]
    total = len(infos)
    window = infos[pagination.offset : pagination.offset + pagination.limit]
    return Page.of(window, total, pagination)


@router.get("/imagery/providers/{provider}", response_model=ProviderInfo, summary="Get a provider")
def get_provider(
    provider: str,
    request: Request,
    settings: Settings = Depends(deps.get_settings),
) -> ProviderInfo:
    service = ImageryService(settings, registry=deps.get_imagery_registry(request))
    return service.get_provider_info(provider)  # UnknownProvider → 404


@router.get("/imagery/tiles/{provider}/{z}/{x}/{y}", summary="Tile proxy (keeps keys server-side)")
def get_tile(
    provider: str,
    z: int,
    x: int,
    y: int,
    request: Request,
    kind: str = Query("satellite", pattern="^(satellite|hybrid|terrain)$"),
    settings: Settings = Depends(deps.get_settings),
) -> Response:
    service = ImageryService(settings, registry=deps.get_imagery_registry(request))
    return tileproxy.serve_tile(service, provider, z, x, y, kind=kind)


@router.get("/imagery/static", summary="Stitched static satellite image")
def get_static(
    request: Request,
    bbox: str = Query(..., description='"minlon,minlat,maxlon,maxlat".'),
    provider: str | None = Query(None),
    zoom: int | None = Query(None, ge=0, le=24),
    kind: str = Query("satellite", pattern="^(satellite|hybrid|terrain)$"),
    format: str = Query("png", pattern="^(png|jpeg|webp)$"),
    settings: Settings = Depends(deps.get_settings),
) -> Response:
    try:
        parsed = BBox.from_csv(bbox)
    except ValueError as exc:
        raise InvalidBBox(str(exc)) from exc
    if zoom is None:
        zoom = settings.search_default_zoom
    service = ImageryService(settings, registry=deps.get_imagery_registry(request))
    return tileproxy.serve_static(
        service,
        provider=provider,
        bbox=(parsed.min_lon, parsed.min_lat, parsed.max_lon, parsed.max_lat),
        zoom=zoom,
        kind=kind,
        image_format=format,
    )
