"""Automatic viewport caching — wire types for ``/imagery/cache/*``.

★ The report is a *settled* viewport (the frontend debounces `moveend`/`zoomend`);
the status is what the map's compact indicator renders: coverage of the visible area,
queue depth, the session's strictly-capped tallies, and why caching is paused when it
is (off / offline / yielding to a manual download / a limit was reached).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, model_validator

from .common import ApiModel
from .imagery import BasemapKind

__all__ = ["AutoCacheSession", "AutoCacheStatus", "AutoCacheToggle", "ViewportReport"]


class ViewportReport(ApiModel):
    """A settled map viewport, in PROVIDER zoom levels (the frontend removes the
    512 px ``zoomShift`` before reporting — tile addresses are provider-native)."""

    provider: str = Field(min_length=1)
    kind: BasemapKind = "satellite"
    west: float
    south: float = Field(ge=-90.0, le=90.0)
    east: float
    north: float = Field(ge=-90.0, le=90.0)
    zoom: int = Field(ge=0, le=24)
    project_id: str | None = None

    @model_validator(mode="after")
    def _ordered(self) -> "ViewportReport":
        if self.south > self.north:
            raise ValueError("south must not exceed north.")
        # west/east deliberately unconstrained: Leaflet reports unwrapped longitudes
        # across the dateline; the service wraps and splits.
        return self


class AutoCacheSession(ApiModel):
    """The automatic-caching session tallies (reset on restart/toggle/project switch)."""

    started_at: datetime
    project_id: str | None = None
    tiles_requested: int
    tiles_downloaded: int
    tiles_skipped_cached: int
    tiles_no_imagery: int
    tiles_failed: int
    bytes_downloaded: int
    limit_reached: str | None = Field(
        default=None, description="Which session limit stopped queueing, if any."
    )


class AutoCacheStatus(ApiModel):
    """What the map's cache indicator shows."""

    enabled: bool
    online: bool = Field(description="False in offline mode or during a network backoff.")
    active: bool = Field(description="Tiles are queued or downloading right now.")
    provider: str | None = None
    kind: BasemapKind = "satellite"
    zoom: int | None = None
    viewport_tiles: int
    cached_tiles: int
    missing_tiles: int
    coverage_percent: float | None = Field(
        default=None, ge=0.0, le=100.0, description="Visible-viewport coverage; null before any report."
    )
    queued_tiles: int
    truncated: bool = Field(
        default=False,
        description=(
            "★ More missing tiles remain beyond this chunk (full-detail mode fills "
            "progressively). The frontend re-reports when the queue drains, until false."
        ),
    )
    note: str | None = Field(
        default=None, description="Why caching is limited/paused, when it is."
    )
    session: AutoCacheSession


class AutoCacheToggle(ApiModel):
    enabled: bool
