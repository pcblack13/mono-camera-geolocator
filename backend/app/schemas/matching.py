"""Matching (§6.2) — endpoints 30, 34–37.

★★ **SCOPE.md §1: THE AUTOMATIC MATCHING ENGINE IS DEFERRED.** These types are
complete and honest, and ``POST /images/{image_id}/match`` is **registered and
documented** but returns ``501`` with the uniform envelope and a
``feature: "deferred"`` marker (SCOPE.md §4 rule 3). It must not 404 — the
feature is planned, not absent — and must not fake a result.

They stay complete because the seam must be real, not decorative: re-enabling the
engine must require **zero changes outside ``ai_engine/``** plus flipping the
endpoints from 501 to live (SCOPE.md §7). And ``MatchResultRead`` is **live in
this build regardless** — it is the shape a GeoTIFF short-circuit produces
(SCOPE.md §3), and, per SCOPE.md §5, the shape a **manual correspondence**
produces: ``gcps.match_result_id`` is ``NOT NULL`` with ``ON DELETE RESTRICT``
(§5.6), so every manual GCP hangs off a ``match_results`` row that records the
provider, the tile, the GSD and the georeferencing error its accuracy was
computed from. ``homography`` is nullable precisely so that row is expressible
with no homography behind it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Final
from uuid import UUID

from pydantic import Field, model_validator

from .common import (
    MAX_AOI_VERTICES,
    ApiModel,
    GeoJsonPolygon,
    LatLon,
    ListParams,
    WarningItem,
)
from .enums import (
    EstimatorName,
    ExtractorName,
    ImageFormat,
    MatcherName,
    ProviderName,
    QualityFlag,
    ViewRegime,
)

__all__ = [
    "MATCH_RESULT_SORT_FIELDS",
    "MAX_TIMEOUT_S_ABSOLUTE",
    "MIN_TIMEOUT_S",
    "MatchOptions",
    "MatchRequest",
    "MatchResultListParams",
    "MatchResultRead",
    "MatchResultSelectRequest",
    "MatchResultSummary",
    "MatchScores",
    "MatchStats",
    "MatchTileRef",
    "SatelliteImageParams",
    "ScoreWeights",
    "SearchHint",
    "TRANSFORM_NOTE",
]

MATCH_RESULT_SORT_FIELDS = frozenset({"rank", "overall_confidence", "created_at"})

#: ★ The schema's ABSOLUTE bound on ``timeout_s``. **Not** the real ceiling.
#:
#: §6.2 is explicit: ``timeout_s`` is ``30 .. LE_CELERY_TASK_SOFT_TIME_LIMIT``
#: (default 600), *"Validated in the pre-flight ladder; over the cap -> 422
#: TIMEOUT_EXCEEDS_LIMIT with details.max_timeout_s"*, and *"the ceiling is a
#: Settings value the validator reads, so raising the worker's limit raises the
#: API's in the same breath."*
#:
#: **This module cannot read Settings.** §10.2 permits ``app.schemas`` to import
#: ``pydantic`` and ``app.core.constants`` — not ``app.core.config``. So the
#: static bound here is a sanity range, and the authoritative check is
#: :meth:`MatchOptions.check_timeout_against` called from ``match_service``'s
#: pre-flight ladder with the live ``Settings`` value.
#:
#: Hard-coding 600 here instead would look like it satisfied §13.1's *"timeout_s
#: > LE_CELERY_TASK_SOFT_TIME_LIMIT -> 422"* and would in fact break the stated
#: guarantee: an operator who raises the worker's soft limit to 900 would get a
#: 422 at 601 from a schema that had never heard of their configuration. A bound
#: that ignores the setting it claims to enforce is worse than an honest sanity
#: range plus a real check.
MAX_TIMEOUT_S_ABSOLUTE: Final = 3600
MIN_TIMEOUT_S: Final = 30

#: ★ Ships in every ``MatchResultRead`` payload, deliberately (§6.2).
#:
#: The image-pixel -> world chain is two composed transforms with two different
#: memory-layout conventions, and getting either backwards yields coordinates
#: that look plausible and are wrong by hundreds of metres. **A one-line
#: statement of the chain costs 200 bytes and prevents the single most expensive
#: mistake a consumer of this API can make.**
TRANSFORM_NOTE: Final = (
    "image_px --homography--> mosaic_px --sat_geotransform--> EPSG:{srid} --> "
    "EPSG:4326. Row-major H. GDAL-order geotransform. Pixel CENTRES: apply +0.5 "
    "to (u,v) before the geotransform. sat_geotransform_srid is authoritative "
    "and is NOT always 3857. See CONTRACT.md §5.8."
)


#: 1–3 zoom levels. Declared as a named alias rather than inline so the `| None`
#: union carries the constraints on the LIST rather than on the union — pydantic
#: cannot apply `max_length` to a `None` branch.
ZoomLevels = Annotated[list[int], Field(min_length=1, max_length=3)]


class SearchHint(ApiModel):
    """Where to search.

    ★ **Resolution order — normative** (§6.2), first that yields a geometry wins;
    recorded in ``match_jobs.search_aoi`` and echoed in the response:
    ``aoi`` -> ``center + radius_m`` -> ``use_image_gps`` + ``exif_gps`` ->
    ``use_image_gps`` + GeoTIFF ``bounds`` -> project ``aoi`` ->
    **422 SEARCH_HINT_REQUIRED**.

    ★ **Never a global search.** A worldwide SIFT search is not a slow feature;
    it is a nonexistent one — 2¹⁸² ≈ 6.87×10¹⁰ tiles ≈ 1 PB per photo. There is
    no budget in which it terminates. That is why the terminal case is a 422 and
    not a default.
    """

    center: LatLon | None = None
    radius_m: float = Field(
        default=1000.0,
        ge=50.0,
        le=50_000.0,
        description="★ 50..50000. Above 50 km the tile count is absurd at any useful zoom.",
    )
    zoom_levels: ZoomLevels | None = Field(
        default=None,
        description=(
            "1-3 entries, each within the provider's min..max -> else 422 "
            "ZOOM_OUT_OF_RANGE (checked in the pre-flight ladder, which is the "
            "only layer that knows the provider). Sorted and deduped here."
        ),
    )
    use_image_gps: bool = True
    aoi: GeoJsonPolygon | None = Field(
        default=None, description="Valid, <= 1000 vertices, area <= 2500 km²."
    )

    @model_validator(mode="after")
    def _normalise(self) -> "SearchHint":
        if self.zoom_levels is not None:
            deduped = sorted(set(self.zoom_levels))
            if len(deduped) > 3:
                raise ValueError("zoom_levels accepts at most 3 distinct levels.")
            self.zoom_levels = deduped
        if self.aoi is not None:
            total = sum(len(ring) for ring in self.aoi.coordinates)
            if total > MAX_AOI_VERTICES:
                raise ValueError(f"aoi has {total} vertices; the limit is {MAX_AOI_VERTICES}.")
        return self


class MatchOptions(ApiModel):
    """The pipeline's knobs. Every default is the one L1 makes the tested path."""

    max_tiles: int = Field(default=256, ge=1, le=1024)
    max_candidates: int = Field(default=25, ge=1, le=100)
    min_confidence: float = Field(
        default=40.0, ge=0.0, le=100.0, description="★ 0-100. Candidates below are dropped."
    )
    ratio_test: float = Field(default=0.75, gt=0.0, lt=1.0)
    cross_check: bool = True
    ransac_threshold_px: float = Field(default=3.0, gt=0.0)
    ransac_max_iters: int = Field(default=10_000, ge=1)
    ransac_confidence: float = Field(default=0.999, gt=0.0, lt=1.0)
    min_inliers: int = Field(default=12, ge=4)
    max_keypoints: int = Field(default=8000, ge=1)
    window_size_px: int = Field(default=1024, ge=64)
    overlap_ratio: float = Field(
        default=0.5,
        ge=0.0,
        lt=1.0,
        description="★ 0.5 — the 512px footprint guarantee (§4.19).",
    )
    seed: int | None = Field(
        default=42, description="★ Pins RANSAC's RNG -> bit-reproducible. Null = nondeterministic."
    )
    timeout_s: int = Field(
        default=600,
        ge=MIN_TIMEOUT_S,
        le=MAX_TIMEOUT_S_ABSOLUTE,
        description=(
            "★ 30 .. LE_CELERY_TASK_SOFT_TIME_LIMIT (default 600). The bound "
            "here is an absolute sanity range; the REAL ceiling is checked in "
            "the pre-flight ladder against Settings -> 422 TIMEOUT_EXCEEDS_LIMIT "
            "with details.max_timeout_s. See MAX_TIMEOUT_S_ABSOLUTE."
        ),
    )

    def check_timeout_against(self, max_timeout_s: int) -> None:
        """★ The authoritative ``timeout_s`` check. Called by ``match_service``'s
        pre-flight ladder with ``settings.celery_task_soft_time_limit``.

        v1.0 accepted ``timeout_s: int = 900  # 30..3600`` against
        ``LE_CELERY_TASK_SOFT_TIME_LIMIT=600``. So a client's **accepted**
        ``timeout_s=900`` was killed at 600 s with ``error.code=TIMEOUT``, and
        ``timeout_s=3600`` validated as legal but was **unreachable** — the API
        accepting a promise the worker cannot keep. Validating against the real
        ceiling is the honest half of the fix; the other half is that the ceiling
        is a Settings value, so raising the worker's limit raises the API's in
        the same breath.

        Args:
            max_timeout_s: the live ``LE_CELERY_TASK_SOFT_TIME_LIMIT``.

        Raises:
            ValueError: when ``timeout_s`` exceeds the worker's soft limit. The
                service wraps this as ``422 TIMEOUT_EXCEEDS_LIMIT`` with
                ``details.max_timeout_s``.
        """
        if self.timeout_s > max_timeout_s:
            raise ValueError(
                f"timeout_s={self.timeout_s} exceeds the worker's soft time limit "
                f"of {max_timeout_s}s. The job would be killed at {max_timeout_s}s "
                f"regardless."
            )


class ScoreWeights(ApiModel):
    """The composite score's mixture. ★ Keys fixed, values >= 0, **MUST sum to
    1.0 ± 1e-6** -> else 422 (§13.1).

    ★ Why the sum is enforced rather than normalised for you: a weight set that
    sums to 1.4 is not a rescaled preference, it is a mistake, and silently
    normalising it produces a confidence number the caller did not ask for and
    cannot reproduce. ``MatchScores.renormalized`` exists for the one case where
    the *server* legitimately redistributes weight (a null sub-score), and it
    says so on the wire.
    """

    feature: float = Field(default=0.25, ge=0.0)
    geometric: float = Field(default=0.35, ge=0.0)
    landmark: float = Field(default=0.30, ge=0.0)
    semantic: float = Field(default=0.10, ge=0.0)

    @model_validator(mode="after")
    def _sum_to_one(self) -> "ScoreWeights":
        total = self.feature + self.geometric + self.landmark + self.semantic
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"score_weights must sum to 1.0 ± 1e-6; got {total!r}. "
                "(feature + geometric + landmark + semantic)"
            )
        return self


class MatchRequest(ApiModel):
    """``POST /images/{image_id}/match`` — endpoint 30.

    ★★ **DEFERRED** (SCOPE.md §1): returns ``501`` + ``feature: "deferred"``.

    ★ **Any enum value is accepted here, including unavailable ones.** An
    explicitly requested missing weight (``matcher: "superglue"``) is a ``202`` +
    fallback + ``WarningItem``, never an error (L11). Only an explicitly
    requested unconfigured **provider** is refusable (``503``) — imagery changes
    the answer's *provenance*; a matcher changes only its *accuracy*. Both are
    reported; only one is refusable.
    """

    search_hint: SearchHint = Field(default_factory=SearchHint)
    provider: ProviderName | None = Field(default=None, description="Null -> the project default.")
    extractor: ExtractorName | None = None
    matcher: MatcherName | None = None
    estimator: EstimatorName | None = None
    use_semantic: bool = False
    annotation_revision_seq: int | None = Field(
        default=None, description="Pins the annotation set matched against."
    )
    annotation_ids: list[UUID] | None = Field(
        default=None, description="Subset to match against."
    )
    options: MatchOptions = Field(default_factory=MatchOptions)
    score_weights: ScoreWeights = Field(default_factory=ScoreWeights)


# ─────────────────────────────────────────────────────────────────────────────
# Results
# ─────────────────────────────────────────────────────────────────────────────


class MatchTileRef(ApiModel):
    """The slippy tile a result came from. Null for ``local_orthophoto``, which
    has no tile grid.
    """

    z: int
    x: int
    y: int
    quadkey: str | None = None


class MatchStats(ApiModel):
    """What the pipeline actually did. ★ Diagnostics, never a gate."""

    query_keypoints: int
    train_keypoints: int
    raw_matches: int
    good_matches: int
    inlier_count: int
    inlier_ratio: float = Field(ge=0.0, le=1.0)
    reproj_error_px: float | None
    tiles_fetched: int
    placeholder_fraction: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Fraction of the mosaic that was a placeholder because a tile was "
            "unavailable. A TileNotAvailableError is not an error — the window is "
            "skipped and this is incremented (§6.3)."
        ),
    )
    elapsed_ms: int


class MatchScores(ApiModel):
    """The confidence breakdown.

    ★ **Score renormalisation is explicit.** With no deep models,
    ``semantic_similarity_score`` is ``null`` and its weight is redistributed
    over the remaining three. **Without ``renormalized: true``, an 87.3 on a
    weightless box and an 87.3 on a GPU box would be quietly incomparable.**
    Stating it makes the number's meaning inspectable.
    """

    feature_similarity_score: float | None = Field(default=None, ge=0.0, le=1.0)
    geometric_consistency_score: float | None = Field(default=None, ge=0.0, le=1.0)
    landmark_consistency_score: float | None = Field(default=None, ge=0.0, le=1.0)
    semantic_similarity_score: float | None = Field(default=None, ge=0.0, le=1.0)
    overall_confidence: float = Field(ge=0.0, le=100.0, description="★ 0-100.")
    weights_used: ScoreWeights
    renormalized: bool
    renormalization_note: str | None = None
    calibrated: bool = Field(
        description=(
            "False when the shipped identity calibration is in force — the "
            "default. A confidence that claims to be calibrated when it is not is "
            "the worst number in this payload."
        )
    )
    calibration_id: str


class MatchResultRead(ApiModel):
    """One candidate. ★ **Live in this build** — see the module docstring: a
    manual correspondence and a GeoTIFF short-circuit both produce one of these.
    """

    id: UUID
    match_job_id: UUID
    image_id: UUID
    rank: int
    is_selected: bool
    parent_match_result_id: UUID | None = Field(
        default=None,
        description=(
            "★ A recompute writes a NEW row rather than mutating the old one — "
            "keeping the RESTRICT provenance chain intact and the original "
            "algorithmic answer inspectable forever."
        ),
    )

    provider: ProviderName
    tile: MatchTileRef | None
    tile_bounds: GeoJsonPolygon = Field(description="★ EPSG:4326, [lon, lat].")
    center: LatLon
    satellite_image_url: str | None
    satellite_checksum: str | None
    satellite_size_px: list[int] | None = Field(default=None, min_length=2, max_length=2)
    gsd_m: float | None = Field(
        default=None,
        description=(
            "★ TRUE ground metres per pixel, cos(φ)-corrected — never a raw 3857 "
            "metre. SCOPE.md §5: this is one of the two inputs to a manual GCP's "
            "reported accuracy."
        ),
    )
    georef_ce90_m: float | None = Field(
        default=None, description="The provider's absolute georeferencing error, CE90 metres."
    )
    is_authoritative: bool = Field(
        description="True => survey-grade georeferencing (i.e. local_orthophoto)."
    )

    homography: list[float] | None = Field(
        default=None,
        min_length=9,
        max_length=9,
        description=(
            "9 floats, ★ ROW-MAJOR, image pixel -> satellite mosaic pixel. "
            "**Null for a manual or GeoTIFF result — there is no homography, and "
            "null is the honest value.**"
        ),
    )
    sat_geotransform: list[float] | None = Field(
        default=None,
        min_length=6,
        max_length=6,
        description="6 floats, ★ GDAL order [c, a, b, f, d, e].",
    )
    sat_geotransform_srid: int = Field(
        description=(
            "★ AUTHORITATIVE, and **NOT always 3857** — it is a UTM code for "
            "local_orthophoto, the highest-accuracy provider."
        )
    )
    transform_note: str = Field(description="★ See TRANSFORM_NOTE. Ships in the payload.")

    imagery_captured_at: datetime | None
    attribution: str = Field(description="★ NOT optional — a ToS obligation.")
    terms_url: str | None

    stats: MatchStats
    scores: MatchScores
    view_regime: ViewRegime
    degeneracy_gate: float
    degeneracy_report: dict[str, Any] = Field(default_factory=dict)

    degraded: bool = Field(
        description=(
            "★ degraded/warnings live at the RESULT level, not just the job "
            "level. Results outlive jobs in the UI; a candidate reviewed a week "
            "later must still say it came from the fallback path."
        )
    )
    degradation_reason: str | None
    warnings: list[WarningItem] = Field(default_factory=list)

    gcp_count: int
    gcps_url: str = Field(description="★ /api/v1/match-results/{id}/gcps — endpoint 64.")
    quality_flags: list[QualityFlag] = Field(default_factory=list)
    created_at: datetime


class MatchResultSummary(ApiModel):
    """List projection — endpoint 34."""

    id: UUID
    match_job_id: UUID
    image_id: UUID
    rank: int
    is_selected: bool
    provider: ProviderName
    center: LatLon
    overall_confidence: float = Field(ge=0.0, le=100.0)
    gcp_count: int
    degraded: bool
    quality_flags: list[QualityFlag] = Field(default_factory=list)
    created_at: datetime


class MatchResultListParams(ListParams):
    """``GET /images/{image_id}/match-results`` — endpoint 34."""

    match_job_id: UUID | None = None
    is_selected: bool | None = None
    confidence__gte: float | None = Field(default=None, ge=0.0, le=100.0)
    confidence__lte: float | None = Field(default=None, ge=0.0, le=100.0)


class MatchResultSelectRequest(ApiModel):
    """``POST /match-results/{match_result_id}/select`` — endpoint 37.

    ★ Selecting a different candidate marks the image's GCPs **stale**; it never
    recomputes them.
    """

    confirm: bool = Field(
        default=True,
        description="Selecting a different candidate marks existing GCPs stale.",
    )


class SatelliteImageParams(ApiModel):
    """``GET /match-results/{match_result_id}/satellite-image`` — endpoint 36."""

    overlay: bool = Field(
        default=False, description="Burn the correspondence markers into the raster."
    )
    format: ImageFormat = ImageFormat.PNG
    width: int | None = Field(default=None, ge=1, le=4096)
    height: int | None = Field(default=None, ge=1, le=4096)
