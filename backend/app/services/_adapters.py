"""The boundary adapters — ★ **the ONLY place a wire type becomes a gis type** (§4.22).

Six names exist twice, with incompatible field shapes, because ``app.schemas`` may not
import ``gis`` (§10.2) and the OpenAPI-facing wire names must not leak an internal
concern into the generated client. Somebody must convert, and v1.0 assigned nobody
(§14 F-47). This module is that somebody, and it is the *only* module in
``app.services`` permitted to import ``gis.types`` / ``gis.imagery.base`` /
``ai_engine.types`` for the conversion.

Every adapter is a small, named, greppable function so the conversion is reviewable and
testable — in particular the ``LonLat``/``LatLon`` field-order flip, which is exactly the
kind of thing an inline ``**dict`` gets silently backwards.

★ ``gis_config_from_settings`` also lives here: it is the one place a backend ``Settings``
(pydantic, wire-adjacent) is turned into a framework-free ``gis.config.GisConfig``. That
is the same boundary — a backend concern crossing into ``gis`` — so it belongs with the
other converters rather than duplicated in every service that resolves a provider.
"""

from __future__ import annotations

from ai_engine.types.geometry import CameraIntrinsics as GisCameraIntrinsics
from gis.candidates.hint import SearchHint as GisSearchHint
from gis.config import (
    ElevationConfig,
    ExifConfig,
    GisConfig,
    ImageryConfig,
    SearchConfig,
    TileCacheConfig,
)
from gis.imagery.base import ProviderCapabilities as GisProviderCapabilities
from gis.imagery.base import ProviderHealth as GisProviderHealth
from gis.imagery.registry import ProviderListing
from gis.types import BBox as GisBBox
from gis.types import LonLat

from app.core.config import Settings
from app.schemas.common import BBox as WireBBox
from app.schemas.common import LatLon as WireLatLon
from app.schemas.imagery import ProviderAttribution, ProviderCoverage
from app.schemas.imagery import ProviderCapabilities as WireProviderCapabilities
from app.schemas.imagery import ProviderHealth as WireProviderHealth
from app.schemas.imagery import ProviderInfo, ProviderRateLimit, ProviderToS
from app.schemas.matching import SearchHint as WireSearchHint
from app.schemas.pose import CameraIntrinsics as WireCameraIntrinsics

__all__ = [
    "gis_config_from_settings",
    "to_engine_intrinsics",
    "to_gis_bbox",
    "to_gis_hint",
    "to_latlon",
    "to_lonlat",
    "to_provider_capabilities",
    "to_provider_health",
    "to_provider_info",
    "to_wire_bbox",
    "to_wire_intrinsics",
]


# ── LonLat / LatLon — ★ the field-order flip ──────────────────────────────────


def to_lonlat(p: WireLatLon) -> LonLat:
    """``schemas.common.LatLon(lat, lon)`` → ``gis.types.LonLat(lon, lat)``.

    ★ The order flips. This is the whole reason the conversion is a named function
    rather than an inline ``**dict``.
    """
    return LonLat(lon=p.lon, lat=p.lat)


def to_latlon(p: LonLat) -> WireLatLon:
    """``gis.types.LonLat(lon, lat)`` → ``schemas.common.LatLon(lat, lon)``."""
    return WireLatLon(lat=p.lat, lon=p.lon)


# ── BBox ──────────────────────────────────────────────────────────────────────


def to_gis_bbox(b: WireBBox) -> GisBBox:
    """``schemas.common.BBox(min_lon/min_lat/max_lon/max_lat)`` → ``gis.types.BBox``.

    The wire type has already rejected an antimeridian-crossing box (min_lon > max_lon)
    at validation, so ``west <= east`` holds and ``gis.types.BBox`` accepts it.
    """
    return GisBBox(west=b.min_lon, south=b.min_lat, east=b.max_lon, north=b.max_lat)


def to_wire_bbox(b: GisBBox) -> WireBBox:
    """``gis.types.BBox(west/south/east/north)`` → ``schemas.common.BBox``.

    An antimeridian-crossing gis ``BBox`` (west > east) cannot be represented on the wire
    and raises here rather than silently swapping the bounds into a box on the other side
    of the planet.
    """
    if b.crosses_antimeridian:
        raise ValueError(
            "a gis BBox that crosses the antimeridian has no wire representation; "
            "split it before converting"
        )
    return WireBBox(min_lon=b.west, min_lat=b.south, max_lon=b.east, max_lat=b.north)


def _polygon_to_bbox(polygon_coordinates: list[list[list[float]]]) -> GisBBox:
    """The bounding envelope of a GeoJSON polygon, in ``gis.types.BBox``.

    GeoJSON coordinates are ``[lon, lat]`` (RFC 7946), so the first ordinate is west/east
    and the second is south/north — the exact opposite of the ``LatLon`` wire type, and
    handled here so no caller has to remember which convention a given shape uses.
    """
    lons: list[float] = []
    lats: list[float] = []
    for ring in polygon_coordinates:
        for position in ring:
            lons.append(position[0])
            lats.append(position[1])
    return GisBBox(west=min(lons), south=min(lats), east=max(lons), north=max(lats))


# ── SearchHint ────────────────────────────────────────────────────────────────


def to_gis_hint(
    h: WireSearchHint,
    *,
    project_aoi: GisBBox | None = None,
    default_zoom_levels: tuple[int, ...] = (18,),
) -> GisSearchHint:
    """``schemas.matching.SearchHint`` → ``gis.candidates.hint.SearchHint``.

    The wire ``aoi`` is a ``GeoJsonPolygon``; the gis side wants a ``BBox``, so the
    polygon is reduced to its envelope (the search area only needs to *contain* the
    region — over-covering is safe, and ``resolve_hint`` treats an explicit ``aoi`` as
    authoritative). ``center`` flips through :func:`to_lonlat`. ``zoom_levels`` is a list
    on the wire and a non-empty tuple in gis; when the client sent none, the project /
    search default is substituted rather than passing an empty tuple, which
    ``gis.candidates.hint.SearchHint`` refuses.

    Args:
        h: The wire hint.
        project_aoi: The project's default AOI, offered as the ``aoi`` when the client
            supplied neither an ``aoi`` nor a ``center``. ``resolve_hint`` still applies
            the full precedence ladder downstream; this only ensures the gis hint carries
            whatever geometry was available.
        default_zoom_levels: What to use when the client sent no ``zoom_levels``.

    Returns:
        A ``gis.candidates.hint.SearchHint``.
    """
    aoi: GisBBox | None = None
    if h.aoi is not None:
        aoi = _polygon_to_bbox(h.aoi.coordinates)
    elif h.center is None and project_aoi is not None:
        aoi = project_aoi

    center = to_lonlat(h.center) if h.center is not None else None
    zoom_levels = tuple(h.zoom_levels) if h.zoom_levels else default_zoom_levels

    return GisSearchHint(
        aoi=aoi,
        center=center,
        radius_m=h.radius_m,
        zoom_levels=zoom_levels,
        use_image_gps=h.use_image_gps,
    )


# ── ProviderCapabilities ──────────────────────────────────────────────────────


def to_provider_capabilities(
    c: GisProviderCapabilities, *, min_zoom: int, max_zoom: int
) -> WireProviderCapabilities:
    """``gis.imagery.base.ProviderCapabilities`` → the wire twin.

    ``min_zoom``/``max_zoom`` are provider properties on the gis side (not on the
    capabilities dataclass) and are threaded in by the caller, which holds the provider.
    """
    return WireProviderCapabilities(
        supports_tiles=c.supports_tiles,
        supports_static_bbox=c.supports_static_bbox,
        supports_offline=c.supports_offline,
        native_crs=c.native_crs,
        kinds=[k.value for k in c.kinds],
        tile_size_px=c.tile_size_px,
        min_zoom=min_zoom,
        max_zoom=max_zoom,
        typical_gsd_m=c.typical_gsd_m,
        georef_ce90_m=c.georef_ce90_m,
        imagery_date_known=c.imagery_date_known,
        rate_limit_rps=c.rate_limit_rps,
        requires_attribution=c.requires_attribution,
        allows_caching=c.allows_caching,
        allows_derivative_export=c.allows_derivative_export,
        max_static_px=list(c.max_static_px) if c.max_static_px is not None else None,
        supports_multispectral=c.supports_multispectral,
        bands=list(c.bands),
        native_max_zoom=c.native_max_zoom,
        native_resolution_status=c.native_resolution_status,  # type: ignore[arg-type]  # same vocabulary
        gsd_status=c.gsd_status,  # type: ignore[arg-type]
        accuracy_status=c.accuracy_status,  # type: ignore[arg-type]
    )


# ── ProviderHealth ────────────────────────────────────────────────────────────


def to_provider_health(h: GisProviderHealth) -> WireProviderHealth:
    """``gis.imagery.base.ProviderHealth`` → the wire twin.

    ``checked_at`` is Unix epoch seconds on the gis side and a ``datetime`` on the wire.
    The status string is passed through unchanged — both sides use the same
    ``up``/``degraded``/``down`` vocabulary.
    """
    from datetime import datetime, timezone

    return WireProviderHealth(
        status=h.status,  # type: ignore[arg-type]  # up|degraded|down, same vocabulary
        configured=h.configured,
        latency_ms=h.latency_ms,
        message=h.message,
        checked_at=datetime.fromtimestamp(h.checked_at, tz=timezone.utc),
    )


# ── ProviderInfo (aggregate) ──────────────────────────────────────────────────


def to_provider_info(
    listing: ProviderListing,
    *,
    is_default: bool,
    tile_url_template: str,
    coverage: ProviderCoverage | None = None,
) -> ProviderInfo:
    """``gis.imagery.registry.ProviderListing`` + ``capabilities()`` + ``health()`` →
    ``schemas.imagery.ProviderInfo`` (the seventh row of §4.22's table).

    Args:
        listing: The registry status for one provider.
        is_default: Whether this is the resolved default provider (L2 keyless Esri on a
            bare machine).
        tile_url_template: The URL template the client should use — the proxy path by
            default, or the upstream URL for keyless providers under
            ``LE_IMAGERY_DIRECT_TILE_URLS``. Computed by the caller, which owns the
            Settings.
        coverage: Optional coverage note; ``None`` ⇒ global.
    """
    provider = listing.provider
    caps = provider.capabilities()
    health = provider.health()

    return ProviderInfo(
        name=provider.name,  # type: ignore[arg-type]  # a PROVIDER_NAMES member == ProviderName
        title=provider.name.replace("_", " ").title(),
        configured=listing.configured,
        allowed=listing.allowed,
        requires_key=provider.requires_api_key,
        is_default=is_default,
        capabilities=to_provider_capabilities(
            caps, min_zoom=provider.min_zoom, max_zoom=provider.max_zoom
        ),
        attribution=ProviderAttribution(text=provider.attribution, terms_url=provider.terms_url),
        tos=ProviderToS(
            terms_url=provider.terms_url,
            allows_caching=caps.allows_caching,
            allows_derivative_export=caps.allows_derivative_export,
        ),
        rate_limit=ProviderRateLimit(rps=caps.rate_limit_rps),
        coverage=coverage or ProviderCoverage(),
        health=to_provider_health(health),
        tile_url_template=tile_url_template,
    )


# ── CameraIntrinsics ──────────────────────────────────────────────────────────


def to_engine_intrinsics(k: WireCameraIntrinsics) -> GisCameraIntrinsics:
    """``schemas.pose.CameraIntrinsics`` → ``ai_engine.types.geometry.CameraIntrinsics``.

    The wire type carries the flattened ``k`` (9 floats, row-major) plus fx/fy/cx/cy; the
    engine type carries a ``(3,3)`` numpy ``K`` and a ``principal_point`` tuple. The
    reshape is the conversion.
    """
    import numpy as np

    matrix = np.asarray(k.k, dtype=np.float64).reshape(3, 3)
    return GisCameraIntrinsics(
        K=matrix,
        source=k.source,
        focal_px=float((k.fx + k.fy) / 2.0),
        principal_point=(float(k.cx), float(k.cy)),
        confidence=1.0,
    )


def to_wire_intrinsics(k: GisCameraIntrinsics) -> WireCameraIntrinsics:
    """``ai_engine.types.geometry.CameraIntrinsics`` → ``schemas.pose.CameraIntrinsics``."""
    matrix = k.K.reshape(9).tolist()
    return WireCameraIntrinsics(
        k=[float(v) for v in matrix],
        fx=float(k.K[0, 0]),
        fy=float(k.K[1, 1]),
        cx=float(k.principal_point[0]),
        cy=float(k.principal_point[1]),
        source=k.source,  # type: ignore[arg-type]  # same literal set on both sides
    )


# ── Settings → GisConfig ──────────────────────────────────────────────────────


def gis_config_from_settings(settings: Settings) -> GisConfig:
    """Build a framework-free ``gis.config.GisConfig`` from the backend ``Settings``.

    ★ The backend owns the pydantic ``Settings``; ``gis`` is a library that must import on
    numpy + stdlib alone, so it cannot depend on it. This is the one place the two are
    reconciled. Per-provider *secrets* are NOT copied here — every provider reads its own
    key from the environment at construction (``LE_MAPBOX_ACCESS_TOKEN`` etc.), and
    ``Settings`` reads the same ``LE_``-prefixed environment, so the two are consistent by
    construction. What this maps is the non-secret imagery/elevation/search/exif policy the
    registries actually branch on.
    """
    imagery = ImageryConfig(
        provider=settings.imagery_provider,
        fallback_chain=tuple(settings.imagery_fallback_chain),
        strict=settings.imagery_strict,
        offline=settings.imagery_offline,
        allowed_providers=tuple(settings.allowed_providers),
        direct_tile_urls=settings.imagery_direct_tile_urls,
        max_concurrent_fetches=settings.imagery_max_concurrent_fetches,
        rate_limit_rps=settings.imagery_rate_limit_rps,
        request_timeout_seconds=settings.imagery_request_timeout_seconds,
        max_retries=settings.imagery_max_retries,
        user_agent=settings.imagery_user_agent,
        local_ortho_dir=str(settings.local_ortho_dir),
        cache=TileCacheConfig(
            backend=settings.imagery_tile_cache_backend,
            directory=str(settings.imagery_tile_cache_dir),
            ttl_seconds=settings.imagery_tile_cache_ttl_seconds,
            max_bytes=settings.imagery_tile_cache_max_bytes,
        ),
    )
    elevation = ElevationConfig(
        provider=settings.elevation_provider,
        local_dem_dir=str(settings.local_dem_dir),
        copernicus_dem_url=settings.copernicus_dem_url,
        cache_ttl_seconds=settings.elevation_cache_ttl_seconds,
    )
    search = SearchConfig(
        default_zoom=settings.search_default_zoom,
        default_radius_m=settings.search_default_radius_m,
        max_radius_m=settings.search_max_radius_m,
        max_candidates=settings.search_max_candidates,
        window_size_px=settings.search_window_size_px,
        overlap_ratio=settings.search_overlap_ratio,
        target_gsd_m=settings.search_target_gsd_m,
        max_tiles_per_job=settings.max_tiles_per_job,
        max_static_tiles=settings.max_static_tiles,
        max_static_pixels=settings.max_static_pixels,
        max_bbox_area_km2=settings.search_max_bbox_area_km2,
    )
    exif = ExifConfig(
        radius_inflation=settings.exif_radius_inflation,
        min_radius_m=settings.exif_min_radius_m,
    )
    return GisConfig(
        imagery=imagery,
        elevation=elevation,
        search=search,
        exif=exif,
        gcp_consistency_tolerance_m=settings.gcp_consistency_tolerance_m,
    )
