"""Imagery providers and the tile proxy (§6.2) — endpoints 50–53.

★ **SCOPE.md §3: all of this is BUILT, in full.** The provider abstraction, Esri
(keyless default), Mapbox, Bing, Sentinel, Google Static and local GeoTIFF, and
the server-side tile proxy, are the manual surveyor's satellite pane — which,
with matching deferred, is *half the product*.

★ **These schemas are the WIRE twin of ``gis.imagery``'s dataclasses, not the
same objects.** ``ProviderCapabilities``, ``ProviderHealth`` and ``BBox`` exist
on both sides of the boundary with different shapes, and ``app.schemas`` may not
import ``gis`` (§10.2). ``app.services._adapters`` (IU-19) is the **only** place
one becomes the other (§4.22) — the contract assigned that conversion to nobody
in v1.0, and it is exactly the seam where two plausible types silently disagree.

★ **L2 — the default imagery provider is KEYLESS.** ``docker compose up`` with an
empty ``.env`` yields a working satellite search via ``esri_world_imagery``.
Keyed providers are strictly opt-in.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import ApiModel, BBox, ListParams
from .enums import ImageFormat, ProviderName

__all__ = [
    "BasemapKind",
    "ProviderAttribution",
    "ProviderCapabilities",
    "ProviderCoverage",
    "ProviderHealth",
    "ProviderInfo",
    "ProviderListParams",
    "ProviderRateLimit",
    "ProviderToS",
    "StaticImageParams",
    "TileParams",
]

#: ★ The mandated "2D map with satellite / hybrid / terrain".
#:
#: ★ **MATCHING ALWAYS USES ``satellite``, normatively** (invariant I4). Labels
#: and hillshade are for human eyes only; feeding a label-burned tile to SIFT
#: would be a genuine accuracy regression. The surveyor may *look* at hybrid —
#: and in manual mode they often should, because road names help them recognise
#: the place — but what a coordinate is measured against is the unlabelled
#: raster.
BasemapKind = Literal["satellite", "hybrid", "terrain"]


class ProviderCapabilities(ApiModel):
    """What a provider can do. ★ Read by the client to configure the map pane;
    read by the server to compute accuracy.
    """

    supports_tiles: bool
    supports_static_bbox: bool
    supports_offline: bool = Field(description="Works with the NIC unplugged.")
    native_crs: str = Field(
        description=(
            "★ Authority string of the geotransform this provider returns. **NOT "
            "fixed at 3857** — local_orthophoto returns a UTM code, and it is the "
            "highest-accuracy provider in the product."
        )
    )
    kinds: list[BasemapKind] = Field(
        description="What the BasemapSwitcher may offer for this provider."
    )
    tile_size_px: int = Field(gt=0)
    min_zoom: int = Field(ge=0, le=24)
    max_zoom: int = Field(ge=0, le=24)
    typical_gsd_m: float | None = Field(
        default=None, gt=0.0, description="Best-case GSD at max_zoom, TRUE ground metres."
    )
    georef_ce90_m: float = Field(
        ge=0.0,
        description=(
            "★ The provider's absolute georeferencing error, CE90 metres. "
            "**Mandatory** — always knowable, and it is a non-null leg of every "
            "GcpAccuracy. SCOPE.md §5 makes it one of the two inputs to a MANUAL "
            "GCP's reported accuracy: with no homography to propagate, the "
            "basemap's own error is often the dominant term."
        ),
    )
    imagery_date_known: bool = Field(
        description="Gates whether MatchResultRead.imagery_captured_at is meaningful."
    )
    rate_limit_rps: float | None = Field(default=None, gt=0.0)
    requires_attribution: bool
    allows_caching: bool = Field(
        description="★ Per-provider TERMS — gates the disk/redis tile caches. Not a preference."
    )
    allows_derivative_export: bool = Field(
        description="★ May a rendered chip go into a PDF deliverable? A ToS question."
    )
    max_static_px: Annotated[list[int], Field(min_length=2, max_length=2)] | None = None
    supports_multispectral: bool
    bands: list[str] = Field(default_factory=list)
    native_max_zoom: int | None = Field(
        default=None,
        ge=0,
        le=24,
        description=(
            "★ Where NATIVE detail typically ends — distinct from max_zoom (what is "
            "SERVED). Above this the imagery is upsampled; the UI warns before a GCP is "
            "placed on interpolated pixels. Null = unknown."
        ),
    )
    native_resolution_status: Literal["known", "estimated", "unknown"] = Field(
        default="unknown",
        description="How native_max_zoom was obtained — never an estimate posing as fact.",
    )
    gsd_status: Literal["vendor_certified", "estimated", "unknown"] = Field(
        default="estimated", description="Epistemic status of typical_gsd_m."
    )
    accuracy_status: Literal["vendor_certified", "estimated", "unknown"] = Field(
        default="estimated", description="Epistemic status of georef_ce90_m."
    )

    @model_validator(mode="after")
    def _zoom_ordering(self) -> "ProviderCapabilities":
        if self.min_zoom > self.max_zoom:
            raise ValueError("min_zoom must not exceed max_zoom.")
        return self


class ProviderAttribution(ApiModel):
    """★ **NOT optional — a ToS obligation.** The text travels with the pixels
    (§4.17), which is why it is also on ``MatchResultRead`` and on the
    ``X-Imagery-Attribution`` response header rather than only here.
    """

    text: str
    terms_url: str | None = None
    logo_url: str | None = None


class ProviderToS(ApiModel):
    """The terms a provider imposes, as facts the server enforces."""

    terms_url: str | None = None
    requires_acknowledgement: bool = Field(
        default=False,
        description=(
            "★ google_maps_static requires LE_GOOGLE_TOS_ACKNOWLEDGED=true in "
            "addition to a key, and is never a default."
        ),
    )
    acknowledged: bool = Field(
        default=False, description="Whether this deployment has acknowledged them."
    )
    allows_caching: bool = True
    allows_derivative_export: bool = True
    note: str | None = None


class ProviderRateLimit(ApiModel):
    """The budget, as configured. One Redis-backed bucket per provider, counted
    across all users — which is reason 4 the tile proxy exists (§7.2).
    """

    rps: float | None = Field(default=None, gt=0.0)
    burst: int | None = Field(default=None, ge=1)
    daily_quota: int | None = Field(default=None, ge=1)
    remaining_today: int | None = Field(default=None, ge=0)


class ProviderHealth(ApiModel):
    """★ Served from the **30 s cache** (§7.1/§7.2.1), never a live probe.

    Endpoint 51's "live self-check" is deleted: an endpoint that does a network
    round trip per call is a denial-of-service amplifier pointed at a provider
    whose rate limit we are contractually obliged to respect.
    """

    status: Literal["up", "degraded", "down"]
    configured: bool
    latency_ms: float | None = None
    message: str | None = None
    checked_at: datetime | None = None


class ProviderCoverage(ApiModel):
    """Where a provider has imagery at all."""

    bbox: BBox | None = Field(default=None, description="Null => global.")
    note: str | None = None


class ProviderInfo(ApiModel):
    """``GET /imagery/providers/{provider}`` — endpoints 50, 51."""

    name: ProviderName
    title: str
    configured: bool = Field(
        description=(
            "★ For a MATCHER, `available: false` never means 'you may not request "
            "it'. For a PROVIDER it does: an explicitly requested unconfigured "
            "provider is a 503 PROVIDER_NOT_CONFIGURED (L11 exception (a)). "
            "**Imagery changes the answer's PROVENANCE; a matcher changes only "
            "its ACCURACY.** Both are reported; only one is refusable."
        )
    )
    allowed: bool = Field(
        default=True,
        description=(
            "★ The OPERATOR'S verdict, distinct from `configured` (the provider's own). "
            "false ⇒ LE_ALLOWED_PROVIDERS (or LE_IMAGERY_OFFLINE) excludes this provider "
            "on this server; requesting it anyway is a 403 PROVIDER_TOS_FORBIDDEN. The "
            "UI hides disallowed providers outright — unlike a missing key, which is a "
            "config action a surveyor might take, a ban is a decision already made."
        ),
    )
    requires_key: bool
    is_default: bool
    capabilities: ProviderCapabilities
    attribution: ProviderAttribution
    tos: ProviderToS
    rate_limit: ProviderRateLimit
    coverage: ProviderCoverage
    health: ProviderHealth
    tile_url_template: str = Field(
        description=(
            "★ By DEFAULT the proxy path /api/v1/imagery/tiles/{provider}/{z}/{x}/"
            "{y} for EVERY provider, keyed or keyless. LE_IMAGERY_DIRECT_TILE_URLS"
            "=true makes KEYLESS providers return their upstream URL instead, "
            "saving bandwidth at a stated ToS cost (§7.2).\n\n"
            "v1.0's rule ('upstream for keyless, proxy for keyed') routed the "
            "DEFAULT provider around the proxy and thereby around ToS "
            "enforcement, the shared rate-limit bucket, and worker/browser cache "
            "identity — on every zero-config machine. Making the bypass opt-in "
            "keeps every stated reason true by default."
        )
    )


class ProviderListParams(ListParams):
    """``GET /imagery/providers`` — endpoint 50."""

    configured: bool | None = None
    supports_offline: bool | None = None
    kind: str | None = Field(default=None, description="Filter by supported BasemapKind.")


class TileParams(ApiModel):
    """``GET /imagery/tiles/{provider}/{z}/{x}/{y}`` — endpoint 52.

    ★ **204 on a valid tile address with no imagery** (ocean, gap) is deliberate:
    it is not an error, and Leaflet renders nothing. A 404 would put a red tile
    on the map and an error in the console for the Atlantic.

    ★ This route is declared ``def``, not ``async def`` (§7.2.1). ``ImageryProvider``
    is synchronous by design, and a synchronous ``httpx`` call inside an
    ``async def`` blocks the event loop for the **entire worker process** —
    taking ``/health`` down alongside it, which is the failure mode most likely
    to be misdiagnosed as "the API is down" when it is one slow tile.
    """

    kind: BasemapKind = "satellite"
    retina: bool = Field(default=False, description="Request the @2x tile where supported.")


class StaticImageParams(ApiModel):
    """``GET /imagery/static`` — endpoint 53.

    ★ **The budget is request-scale, not job-scale** (§7.2.1):
    ``LE_MAX_STATIC_TILES`` 16 and ``LE_MAX_STATIC_PIXELS`` 4 MP. At the old
    budget (256 tiles / 64 MP) one GET could trigger 256 tile fetches, a
    64-megapixel NumPy stitch, a crop and a PNG encode — that is not "tile
    proxying", it is precisely the *"OpenCV/NumPy operation heavier than one
    thumbnail downsample"* that **L5 forbids**, wearing a GET. Over budget ->
    ``422 STATIC_IMAGE_TOO_LARGE``, pointing at the ``202 -> GET /jobs/{id}``
    pattern every other heavy operation already uses.
    """

    provider: ProviderName | None = Field(default=None, description="Null -> the default (L2).")
    bbox: str = Field(description='"minlon,minlat,maxlon,maxlat".')
    zoom: int | None = Field(default=None, ge=0, le=24)
    width: int | None = Field(default=None, ge=1, le=4096)
    height: int | None = Field(default=None, ge=1, le=4096)
    kind: BasemapKind = "satellite"
    format: ImageFormat = ImageFormat.PNG
    georeferenced: bool = Field(
        default=False,
        description="Emit a GeoTIFF instead of a flat raster. Ignored for webp/jpeg.",
    )


class GeocodeResult(ApiModel):
    """One place-name search hit — ``GET /imagery/geocode``.

    ★ ``lat``/``lon`` are the point to fly to; ``bbox`` (when the geocoder supplies one)
    lets the map frame a whole town or field rather than a single pin. Coordinates are
    WGS 84, lat-first everywhere but inside a GeoJSON geometry (§6.1).
    """

    display_name: str = Field(description="Human-readable label, e.g. 'Yammouneh, Baalbek, Lebanon'.")
    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)
    category: str | None = Field(default=None, description="Geocoder class, e.g. 'place', 'village'.")
    bbox: BBox | None = Field(
        default=None, description="Suggested framing bounds, when the geocoder returns one."
    )
