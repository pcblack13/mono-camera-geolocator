"""Projects (§6.2) — endpoints 4–8."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import AliasChoices, Field, field_validator

from .common import (
    MAX_AOI_VERTICES,
    META_FIELD,
    AlbumRef,
    ApiModel,
    GeoJsonPolygon,
    ListParams,
    PatchModel,
)
from .enums import EstimatorName, ExtractorName, MatcherName, ProviderName

__all__ = [
    "PROJECT_SORT_FIELDS",
    "ProjectCounts",
    "ProjectCreate",
    "ProjectListParams",
    "ProjectRead",
    "ProjectSummary",
    "ProjectUpdate",
]

#: Free-text search + tag/bbox filtering. ★ Every sort is stabilised by the
#: repository with a trailing ``id ASC`` (§6.2).
PROJECT_SORT_FIELDS = frozenset({"name", "created_at", "updated_at", "image_count"})

#: ≤ 20 tags, each ≤ 50 chars.
Tag = Annotated[str, Field(min_length=1, max_length=50)]
TagList = Annotated[list[Tag], Field(max_length=20)]

#: 1–200, non-blank after strip. ``str_strip_whitespace`` on ``ApiModel`` runs
#: BEFORE ``min_length``, so ``"   "`` becomes ``""`` and fails the bound — the
#: non-blank rule needs no separate validator.
ProjectName = Annotated[str, Field(min_length=1, max_length=200)]


def _check_aoi_vertices(aoi: GeoJsonPolygon | None) -> GeoJsonPolygon | None:
    """≤ 1000 vertices for an AOI.

    ★ Tighter than ``GeoJsonPolygon``'s own 10 000-vertex ceiling, on purpose:
    an AOI is a search region, not a cadastral boundary. ``ProjectSummary``
    already omits ``aoi`` because 1000 vertices × 50 rows is a ~2 MB list
    response; permitting 10 000 would make ``ProjectRead`` alone a 400 KB payload
    for a rectangle someone drew badly.
    """
    if aoi is None:
        return None
    total = sum(len(ring) for ring in aoi.coordinates)
    if total > MAX_AOI_VERTICES:
        raise ValueError(f"AOI has {total} vertices; the limit is {MAX_AOI_VERTICES}.")
    return aoi


class ProjectCounts(ApiModel):
    """The rollup. Five aggregate subqueries — which is why ``ProjectSummary``
    omits it and only ``ProjectRead`` carries it.
    """

    images: int
    annotations: int
    gcps: int
    match_jobs: int
    exports: int


class ProjectExportRead(ApiModel):
    """``POST /projects/{id}/export`` — the self-contained folder just written.

    ★ One human-browsable folder in the visible LandExplorer directory gathering
    the project's photos, GCPs (as CSV), DEM and solve outputs — see
    ``project_export_service`` (2026-09-03, owner ask).
    """

    #: The folder name, and its absolute path on disk (the operator opens it).
    folder: str
    path: str
    #: The projects-export root the folder sits in.
    root: str
    images: int
    gcps: int
    gcp_solves: int
    luts: int
    videos: int
    has_dem: bool
    #: Pieces that were not present to copy (e.g. "project DEM (none built yet)").
    missing: list[str] = []


class ProjectCreate(ApiModel):
    """``POST /projects`` — endpoint 4.

    ★ Every default here is the **keyless, zero-config** one (L2, L10):
    ``Settings()`` with an empty environment never raises, and a project created
    with ``{"name": "x"}`` alone is fully functional against
    ``esri_world_imagery``.
    """

    name: ProjectName
    description: str | None = Field(default=None, max_length=4000)
    aoi: GeoJsonPolygon | None = Field(
        default=None,
        description=(
            "RFC 7946, EPSG:4326, [lon, lat]. <= 1000 vertices, ST_IsValid, area "
            "<= 10 000 km². ★ ST_IsValid and the area bound are checked "
            "server-side in the service layer — they need PostGIS, and "
            "app.schemas may not import it (§10.2)."
        ),
    )
    default_provider: ProviderName = ProviderName.ESRI_WORLD_IMAGERY  # ★ KEYLESS (L2)
    default_extractor: ExtractorName = ExtractorName.SIFT
    default_matcher: MatcherName = MatcherName.FLANN
    default_estimator: EstimatorName = EstimatorName.USAC_MAGSAC
    default_search_radius_m: float = Field(default=1000.0, ge=10.0, le=50_000.0)
    default_search_zoom: int = Field(default=18, ge=10, le=21)
    tags: TagList = Field(default_factory=list)
    metadata: dict[str, Any] = META_FIELD

    _check_aoi = field_validator("aoi")(_check_aoi_vertices)


class ProjectUpdate(PatchModel):
    """``PATCH /projects/{project_id}`` — endpoint 7. ★ UNSET semantics.

    ``{"aoi": null}`` **clears** the AOI. ``{}`` leaves everything untouched and
    is a ``400 EMPTY_PATCH`` raised by the router off :meth:`PatchModel.is_empty`
    — *without the sentinel, nullable fields are un-clearable through PATCH, a
    real and common bug* (§6.1).

    ★ Note which fields are ``T | None`` and which are just ``T``:
    ``default_provider`` is NOT nullable, because clearing it is meaningless —
    there is always a default provider. ``description`` and ``aoi`` are
    genuinely clearable. The type says which, and the service does not have to
    guess.
    """

    name: ProjectName | None = None
    description: str | None = Field(default=None, max_length=4000)
    aoi: GeoJsonPolygon | None = None
    default_provider: ProviderName | None = None
    default_extractor: ExtractorName | None = None
    default_matcher: MatcherName | None = None
    default_estimator: EstimatorName | None = None
    default_search_radius_m: float | None = Field(default=None, ge=10.0, le=50_000.0)
    default_search_zoom: int | None = Field(default=None, ge=10, le=21)
    tags: TagList | None = None
    metadata: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("meta", "metadata"),
        serialization_alias="metadata",
    )

    _check_aoi = field_validator("aoi")(_check_aoi_vertices)


class ProjectRead(ApiModel):
    """``ProjectRead`` — endpoints 4, 6, 7.

    ★ §13.1 (IU-17): ``ProjectRead.model_validate(project_orm).metadata ==
    project_orm.meta``. Without ``META_FIELD``'s ``meta`` validation alias this
    read returns SQLAlchemy's ``MetaData`` object on every project.
    """

    id: UUID
    name: str
    description: str | None
    aoi: GeoJsonPolygon | None
    aoi_area_km2: float | None
    default_provider: ProviderName
    default_extractor: ExtractorName
    default_matcher: MatcherName
    default_estimator: EstimatorName
    default_search_radius_m: float
    default_search_zoom: int
    tags: list[str]
    metadata: dict[str, Any] = META_FIELD
    current_revision_seq: int
    counts: ProjectCounts | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class ProjectSummary(ApiModel):
    """List projection — endpoint 5.

    ★ Deliberately **omits ``aoi`` and ``counts``**: a 1000-vertex polygon × 50
    rows is a ~2 MB list response for a screen that renders names, and the full
    rollup costs five aggregate subqueries per row. ``image_count`` alone is kept
    — one cheap correlated count.
    """

    id: UUID
    name: str
    description: str | None
    tags: list[str]
    aoi_area_km2: float | None
    image_count: int
    #: ★ The albums this project belongs to — MANY, because the relationship is
    #: many-to-many (a project is filed under as many collections as the surveyor
    #: likes). ``{id, name}`` only; loaded for the **whole page in one query** by
    #: ``AlbumRepository.albums_for_projects``, never through ``project.albums``
    #: (``lazy="raise"``, so the N+1 fails loudly rather than shipping).
    #:
    #: Defaults to ``[]`` so every existing construction site of this model — and there
    #: are several — keeps working unchanged; an empty list and "no albums" are the same
    #: fact here, so the default fabricates nothing.
    albums: list[AlbumRef] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ProjectListParams(ListParams):
    """``GET /projects`` — endpoint 5."""

    q: str | None = Field(default=None, description="Free-text over name + description.")
    tags: str | None = Field(default=None, description="CSV. Multiple tags AND. There is no OR.")
    bbox: str | None = Field(
        default=None,
        description=(
            '"minlon,minlat,maxlon,maxlat" — projects whose AOI intersects. '
            "Antimeridian-crossing -> 422 BBOX_CROSSES_ANTIMERIDIAN."
        ),
    )
    album_id: UUID | None = Field(
        default=None,
        description=(
            "Only projects filed in this album. ★ A FILTER, not a different resource: "
            "GET /albums/{id}/projects answers the same question from the album's side "
            "and both go through one repository query, so the two can never disagree "
            "about what an album contains."
        ),
    )
    include_deleted: bool = False
