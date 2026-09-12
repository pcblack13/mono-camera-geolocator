"""Semantic features (§6.2) — endpoints 46, 47.

★★ **DEFERRED** (SCOPE.md §4): semantic detection — field borders, roads, canals,
trees, greenhouses, buildings, water, crop rows — is an ABC only.
``POST /images/{image_id}/segment`` is **registered and documented** and returns
``501`` + ``feature: "deferred"``. The ``semantic_features`` table IS created
exactly as specified (rule 5) — it simply holds no rows, so endpoint 46 returns
an empty ``Page``.

★ **``class`` is a Python keyword.** The wire key is ``class`` (§5.6's column
name and IU-23's ``SemanticFeatureRead.class``), and no Python identifier can
spell it. This is the **second and last** of the package's two deliberate
field-level aliases — the same shape as ``metadata`` in ``common.META_FIELD``,
for the same reason, and L9 forbids an alias *generator*, not a named exemption
forced by the language. See :data:`CLASS_FIELD`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from pydantic import AliasChoices, Field

from .common import ApiModel, GeoJsonGeometry, ListParams
from .enums import (
    AnnotationKind,
    FeatureDetectorName,
    FeatureSpace,
    SegmentBackend,
    SemanticClass,
)

__all__ = [
    "SEMANTIC_SORT_FIELDS",
    "CLASS_FIELD",
    "MaskRle",
    "SegmentPoint",
    "SegmentRequest",
    "SemanticFeatureDeleteParams",
    "SemanticFeatureListParams",
    "SemanticFeatureRead",
    "SemanticFeatureSummary",
]

SEMANTIC_SORT_FIELDS = frozenset({"created_at", "confidence", "area_m2", "class"})

#: ★ THE SECOND (AND LAST) DELIBERATE FIELD-LEVEL ALIAS. See the module
#: docstring.
#:
#: The Python attribute is ``class_`` (PEP 8's trailing underscore for a keyword
#: clash); the wire key is ``class`` in both directions.
#: ``AliasChoices("class_", "class")`` accepts the ORM attribute **and** the wire
#: key on input — IU-16's ORM cannot name its attribute ``class`` either, so it
#: will be ``class_`` or similar, and accepting both is what makes
#: ``model_validate(orm_row)`` work without knowing which IU-16 chose.
#: ``serialization_alias="class"`` guarantees the emitted key never changes.
CLASS_FIELD: Final = Field(
    validation_alias=AliasChoices("class_", "class"),
    serialization_alias="class",
    description="The detected class. Wire key is `class`; the Python attribute is `class_`.",
)


class MaskRle(ApiModel):
    """Run-length encoding of a binary mask, row-major.

    ★ RLE rather than a raster: a mask is transported, never stored in Postgres
    (§5.6), and an uncompressed 4000×3000 boolean is 12 MB of JSON.
    """

    size: Annotated[list[int], Field(min_length=2, max_length=2)] = Field(
        description="[height, width]."
    )
    counts: list[int]
    order: Literal["row_major"] = "row_major"


class SegmentPoint(ApiModel):
    """A user click that seeds an interactive segmentation (SAM's prompt model).

    ★ IMAGE PIXELS, original space — the same coordinate discipline as every
    other pixel on this wire.
    """

    x: float
    y: float
    is_positive: bool = Field(
        description="true = 'include this'; false = 'exclude this'."
    )


class SegmentRequest(ApiModel):
    """``POST /images/{image_id}/segment`` — endpoint 47.

    ★★ **DEFERRED** — returns ``501``. Complete anyway: the seam must be real.
    """

    backend: SegmentBackend = SegmentBackend.CLASSICAL
    classes: list[SemanticClass] | None = Field(
        default=None, description="Restrict to these classes. Null -> everything the backend does."
    )
    space: FeatureSpace = FeatureSpace.IMAGE_PIXEL
    match_result_id: UUID | None = Field(
        default=None,
        description=(
            "Required when space='satellite_geo' — there is no geography without "
            "a georeferenced mosaic to read it from "
            "(ck_semantic_features_geo_needs_match)."
        ),
    )
    points: list[SegmentPoint] | None = Field(
        default=None, description="SAM-style prompts. Null -> unprompted segmentation."
    )
    min_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    as_annotation_kind: AnnotationKind | None = Field(
        default=None,
        description=(
            "Convert the detected feature into an annotation of this kind on "
            "accept. Null -> the feature stays a feature. Same proposal-vs-"
            "assertion boundary as landmark suggestions."
        ),
    )


class SemanticFeatureRead(ApiModel):
    """One detected feature. ★ No row carries this in this build."""

    id: UUID
    image_id: UUID
    match_result_id: UUID | None = Field(
        default=None, description="Set IFF space='satellite_geo'."
    )
    source_annotation_id: UUID | None = Field(
        default=None, description="Set IFF detector='manual'."
    )
    class_: SemanticClass = CLASS_FIELD
    space: FeatureSpace
    detector: FeatureDetectorName
    model_version: str | None
    pixel_geom: GeoJsonGeometry | None = Field(
        default=None,
        description=(
            "★ IMAGE PIXELS, [x, y], y-down, SRID 0 — the same GeoJSON-shaped-"
            "but-not-geographic trap as AnnotationRead.geometry. Non-null IFF "
            "space='image_pixel'."
        ),
    )
    geo_geom: GeoJsonGeometry | None = Field(
        default=None,
        description="EPSG:4326, [lon, lat]. Non-null IFF space='satellite_geo'.",
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="★ 0-1 — note: NOT the 0-100 GCP scale."
    )
    area_px: float | None = None
    area_m2: float | None = Field(default=None, description="★ TRUE ground metres².")
    length_m: float | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    embedding_meta: dict[str, Any] | None = Field(
        default=None,
        description=(
            "★ Embeddings are NOT stored in Postgres — pgvector is not in the "
            "mandated stack and DINOv2 descriptors (768-D float32 × thousands of "
            "patches) are a poor fit for a row store. They are written as "
            ".npy/FAISS artifacts and referenced BY PATH here."
        ),
    )
    created_at: datetime


class SemanticFeatureSummary(ApiModel):
    """List projection — endpoint 46. Omits the geometries, which are the payload."""

    id: UUID
    image_id: UUID
    class_: SemanticClass = CLASS_FIELD
    space: FeatureSpace
    detector: FeatureDetectorName
    confidence: float = Field(ge=0.0, le=1.0)
    area_px: float | None
    area_m2: float | None


class SemanticFeatureListParams(ListParams):
    """``GET /images/{image_id}/semantic-features`` — endpoint 46.

    ★ Returns an empty ``Page`` in this build, not a 501 — the read succeeds and
    the collection is genuinely empty. Only the producer (endpoint 47) is
    deferred.
    """

    class_: str | None = Field(
        default=None,
        validation_alias="class",
        serialization_alias="class",
        description="CSV of SemanticClass. Query key is `class`.",
    )
    space: FeatureSpace | None = None
    detector: FeatureDetectorName | None = None
    confidence__gte: float | None = Field(default=None, ge=0.0, le=1.0)
    match_result_id: UUID | None = None


class SemanticFeatureDeleteParams(ApiModel):
    """``DELETE /images/{image_id}/semantic-features`` — bulk clear."""

    class_: str | None = Field(
        default=None,
        validation_alias="class",
        serialization_alias="class",
        description="CSV of SemanticClass. Null -> every feature on the image.",
    )
    space: FeatureSpace | None = None
    detector: FeatureDetectorName | None = None
