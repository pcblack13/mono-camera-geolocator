"""``GET /capabilities`` (§6.2) — endpoint 3.

★ The ``PreflightReport`` behind this is computed **ONCE** in ``main.py``'s
lifespan and cached on ``app.state`` (§11.1). This endpoint READS the cache and
never re-resolves — re-sha256'ing a 2.4 GB SAM checkpoint per request is not a
health check, it is an outage.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from .common import ApiModel
from .enums import EstimatorName, ExportFormat, ExtractorName, MatcherName, ProviderName

__all__ = [
    "CapabilitiesResponse",
    "CapabilityItem",
    "CapabilityStatus",
    "ComputeInfo",
    "DefaultsInfo",
    "ExportCapability",
    "LimitsInfo",
]

#: ★ ``deferred`` is a FIRST-CLASS status, distinct from ``unavailable``
#: (SCOPE.md §4). The three are genuinely different facts and collapsing any two
#: produces a lying UI:
#:   - ``available``   — resolves and runs.
#:   - ``unavailable`` — a weight/key/dep is missing; you get ``fallback``
#:     instead, and the request still succeeds (L11).
#:   - ``deferred``    — NOT IMPLEMENTED IN THIS BUILD. The interface exists; the
#:     body raises ``NotImplementedDeferred``. **There is no fallback, because
#:     the fallback is deferred too** (SCOPE.md §6). Offering a substitute that
#:     also will not run is the one thing worse than saying so plainly.
CapabilityStatus = Literal["available", "unavailable", "deferred"]


class CapabilityItem(ApiModel):
    """One component's resolvability.

    ★ ``available: false`` **never** means "you may not request it". The API
    accepts ``matcher: "superglue"`` on a weightless box and returns a job that
    warns and falls back. It means *"if you pick this, you will get ``fallback``
    instead."* The frontend renders such options disabled with ``reason`` as the
    tooltip.

    ★ The deliberate asymmetry, restated so nobody "fixes" it: an explicitly
    requested unconfigured **provider** is a ``503 PROVIDER_NOT_CONFIGURED``,
    but an explicitly requested missing **weight** is a ``202`` + fallback +
    ``WarningItem``. **Imagery changes the answer's provenance; a matcher changes
    only its accuracy.** Both are reported; only one is refusable (L11).
    """

    name: str
    available: bool = Field(
        description=(
            "Convenience mirror of `status == 'available'`. Kept because every "
            "client renders a boolean; `status` is what carries the reason."
        )
    )
    kind: Literal["classical", "deep"]
    requires_weights: bool
    status: CapabilityStatus
    reason: str | None = Field(
        default=None,
        description=(
            'Why, when not available: "Weights not found at '
            '/models/superpoint_v1.pth" — or, when deferred, a pointer to '
            "SCOPE.md."
        ),
    )
    fallback: str | None = Field(
        default=None,
        description=(
            "★ What you WILL get if you pick this anyway. **Null when "
            "status == 'deferred'** — there is nothing behind it to fall back "
            "to, and naming one would be a fabrication."
        ),
    )


class ExportCapability(ApiModel):
    """Whether an export format can actually be written right now.

    ★ SCOPE.md §3: exports are BUILT, in full. But four writers degrade on a
    missing optional dep (geopandas/fiona/ezdxf/reportlab), and a format that
    silently 500s at job time is worse than one greyed out at menu time.
    """

    format: ExportFormat
    available: bool
    reason: str | None = Field(default=None, description='e.g. "geopandas is not installed".')
    requires_extra: str | None = Field(
        default=None, description='The pip extra that would enable it, e.g. "gis[exports]".'
    )


class ComputeInfo(ApiModel):
    """What this process can actually run on."""

    device: Literal["cpu", "cuda"] = Field(
        description=(
            "★ NEVER inferred from a build name. torch 2.11.0+cu130 with "
            "torch.cuda.is_available() == False is `cpu`, and LE_AI_DEVICE=auto "
            "resolves to `cpu` here (§0.1)."
        )
    )
    torch_available: bool
    torch_version: str | None
    cuda_available: bool
    gpu_name: str | None
    opencv_version: str
    numpy_version: str
    raster_backend: str = Field(
        description=(
            "★ Which backend gis.rasterio_shim.probe() bound: 'rasterio' | "
            "'gdal' | 'none'. Surfaced because 'degrades gracefully' can degrade "
            "to NOTHING silently: with neither backend, local_orthophoto is dead, "
            "GeoTIFF ingest cannot populate crs_epsg/bounds/geotransform, and "
            "total_ce90_m is uncomputable (§7.1)."
        )
    )
    worker_count: int


class LimitsInfo(ApiModel):
    """The server's caps. ★ The frontend NEVER hard-codes these (§8.7).

    A client-side constant that disagrees with the server produces the worst
    upload UX there is: a dropzone that accepts a 400 MB orthophoto and a 413
    twenty minutes later.
    """

    upload_max_bytes: int
    async_ingest_threshold_bytes: int
    max_image_pixels: int
    max_image_dimension: int
    max_annotations_per_image: int
    max_tiles_per_match: int
    max_search_radius_m: float
    max_timeout_s: int = Field(
        description=(
            "★ = LE_CELERY_TASK_SOFT_TIME_LIMIT. The ceiling MatchOptions."
            "timeout_s is validated against in the pre-flight ladder, published "
            "so a client can bound its own input rather than discover the cap by "
            "422. Raising the worker's limit raises this in the same breath."
        )
    )
    max_replay_events: int
    max_batch_items: int


class DefaultsInfo(ApiModel):
    """What the server will pick when the client picks nothing.

    ★ ``provider`` is **keyless** (L2): ``docker compose up`` with an empty
    ``.env`` yields a working satellite search via ``esri_world_imagery``.
    """

    provider: ProviderName
    extractor: ExtractorName
    matcher: MatcherName
    estimator: EstimatorName
    search_radius_m: float
    search_zoom: int
    min_confidence: float


class CapabilitiesResponse(ApiModel):
    """``GET /capabilities`` — the whole honest picture, in one read."""

    version: str
    engine_version: str
    extractors: list[CapabilityItem]
    matchers: list[CapabilityItem]
    estimators: list[CapabilityItem]
    segmenters: list[CapabilityItem]
    suggesters: list[CapabilityItem]
    providers: list[CapabilityItem]
    elevation_providers: list[CapabilityItem]
    exports: list[ExportCapability]
    compute: ComputeInfo
    limits: LimitsInfo
    defaults: DefaultsInfo
    deferred_features: list[str] = Field(
        default_factory=list,
        description=(
            "★ SCOPE.md §1. The names of the features this build defers, so the "
            "UI gates controls off ONE server-provided list rather than a "
            "hard-coded constant that must be edited when the engine lands "
            "(SCOPE.md §7: re-enabling must not require changes outside "
            "ai_engine/ plus flipping the endpoints from 501 to live). Each name "
            "matches a DeferredFeature.name in a 501 body. In this build: "
            "matching, feature extraction, RANSAC, camera pose, heatmap, "
            "segmentation, landmark suggestion."
        ),
    )
    checked_at: datetime
