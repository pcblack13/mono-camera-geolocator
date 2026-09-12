"""Offline area pre-caching — the wire types for ``/imagery/offline/*`` (Offline Area Manager).

★ **The pre-cache and the map share ONE cache.** These endpoints drive the same
read-through tile cache the proxy writes; "download an area" is enumerating its XYZ tiles
and pulling each one through the normal path. The estimate/coverage answers therefore
describe the exact bytes the offline map will later read.

★ Estimates are labelled with their PROVENANCE (``average_tile_size_source``): a measured
mean from this operator's own cache beats any constant, but when nothing is cached yet the
default is stated as a default — never presented as a measurement.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import ApiModel
from .imagery import BasemapKind

__all__ = [
    "OfflineAreaRequest",
    "OfflineCoverage",
    "OfflineEstimate",
    "OfflineManifest",
    "PrecacheBudget",
    "PrecacheOperation",
    "PrecacheStartRequest",
]

#: One polygon vertex, ``(lon, lat)`` — GeoJSON axis order, like ``BBox``.
LonLat = Annotated[list[float], Field(min_length=2, max_length=2)]


class OfflineAreaRequest(ApiModel):
    """An AOI + zoom band + provider — the input to estimate/coverage/start."""

    provider: str = Field(min_length=1, description="Registry key, e.g. mapbox_satellite.")
    kind: BasemapKind = "satellite"
    polygon: Annotated[list[LonLat], Field(min_length=3)] = Field(
        description="AOI ring as (lon, lat) vertices; a bounding box is its 4 corners."
    )
    zoom_min: int = Field(ge=0, le=24)
    zoom_max: int = Field(ge=0, le=24)
    project_id: str | None = Field(
        default=None, description="Optional project this offline area belongs to."
    )

    @model_validator(mode="after")
    def _zoom_ordering(self) -> "OfflineAreaRequest":
        if self.zoom_min > self.zoom_max:
            raise ValueError("zoom_min must not exceed zoom_max.")
        return self


class PrecacheStartRequest(OfflineAreaRequest):
    """Start a download. Identical to the estimate input — what you saw is what runs."""


class PrecacheBudget(ApiModel):
    """The configured request budgets, evaluated against this request."""

    per_operation_limit: int | None = Field(
        default=None, description="LE_*_MAX_TILE_REQUESTS_PER_OPERATION; null = unlimited."
    )
    max_prefetch_tiles: int | None = Field(
        default=None, description="LE_*_MAX_PREFETCH_TILES; null = unlimited."
    )
    per_day_limit: int | None = Field(
        default=None, description="LE_*_MAX_TILE_REQUESTS_PER_DAY; null = unlimited."
    )
    per_day_used: int = Field(
        default=0, description="Upstream requests already recorded today (persisted)."
    )
    within_budget: bool
    reason: str | None = Field(
        default=None, description="Why the request exceeds a budget, naming the setting."
    )


class OfflineEstimate(ApiModel):
    """What a pre-cache run would cost — tiles, upstream requests, storage."""

    provider: str
    zoom_min: int
    zoom_max: int
    total_tiles: int
    cached_tiles: int = Field(description="Already present (fresh) in the tile cache.")
    missing_tiles: int = Field(description="What a download would actually fetch.")
    estimated_upstream_requests: int = Field(
        description="= missing_tiles: one request per tile (@2x tiles are ONE request)."
    )
    average_tile_size_bytes: int
    average_tile_size_source: Literal["measured", "default"] = Field(
        description="measured = sampled from this cache; default = stated constant."
    )
    estimated_storage_bytes: int
    capped: bool = Field(
        description="True when enumeration stopped at the hard cap — shrink the AOI."
    )
    budget: PrecacheBudget


class PrecacheOperation(ApiModel):
    """One pre-cache run's live status."""

    id: str
    state: Literal["pending", "running", "paused", "completed", "cancelled", "failed"]
    provider: str
    kind: BasemapKind
    zoom_min: int
    zoom_max: int
    project_id: str | None = None
    total_tiles: int
    completed_tiles: int
    skipped_cached: int = Field(description="Already in cache — never went upstream.")
    no_imagery_tiles: int = Field(description="Provider has nothing there (ocean/gap).")
    failed_tiles: int
    remaining_tiles: int
    downloaded_bytes: int
    percent: float = Field(ge=0.0, le=100.0)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    note: str | None = Field(
        default=None, description="Why the run paused/failed, when it did."
    )
    manifest_id: str | None = Field(
        default=None, description="Set once the manifest is written (completed runs)."
    )


class OfflineManifest(ApiModel):
    """A durable record of a downloaded offline area.

    ★ Enough to answer, later and offline: which provider and configuration produced
    these tiles, over what AOI and zoom band, how complete the area is, and when the
    cached imagery expires. ``cache_variant`` is the provider's config fingerprint — the
    same string in the tile cache key, so a config change is visible as a mismatch.
    """

    id: str
    project_id: str | None = None
    provider: str
    kind: BasemapKind
    cache_variant: str
    polygon: list[LonLat]
    bbox: Annotated[list[float], Field(min_length=4, max_length=4)] = Field(
        description="(min_lon, min_lat, max_lon, max_lat) of the AOI."
    )
    zoom_min: int
    zoom_max: int
    tile_size_px: int
    tile_count: int
    completed_tiles: int
    no_imagery_tiles: int
    missing_tiles: int
    downloaded_bytes: int
    created_at: datetime
    expires_at: datetime | None = Field(
        default=None,
        description="created_at + the provider's effective cache TTL; null = no expiry.",
    )


class OfflineCoverage(ApiModel):
    """How much of an AOI the cache currently holds, per zoom and overall."""

    provider: str
    total_tiles: int
    cached_tiles: int
    coverage_ratio: float = Field(ge=0.0, le=1.0)
    by_zoom: dict[str, dict[str, int]] = Field(
        default_factory=dict,
        description='Per zoom: {"15": {"total": n, "cached": m}, ...}.',
    )
    capped: bool = False
