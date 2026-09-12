"""Annotations (§6.2) — endpoints 16–22.

★ **SCOPE.md §5 makes this module load-bearing.** The surveyor marks a landmark
in the photo; that landmark is an ``Annotation``, and it is the photo endpoint of
every manual correspondence. ``gcps.landmark_id → annotations.id``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field, model_validator

from .common import (
    ApiModel,
    GeoJsonGeometry,
    ListParams,
    PatchModel,
    RevisionSummary,
    WarningItem,
)
from .enums import AnnotationGeomType, AnnotationKind, AnnotationOp

__all__ = [
    "ANNOTATION_SORT_FIELDS",
    "MAX_ANNOTATIONS_PER_IMAGE",
    "AnnotationApplyCounts",
    "AnnotationBulkUpsertItem",
    "AnnotationBulkUpsertRequest",
    "AnnotationBulkUpsertResponse",
    "AnnotationBulkUpsertResultItem",
    "AnnotationCreate",
    "AnnotationListParams",
    "AnnotationRead",
    "AnnotationStyle",
    "AnnotationSummary",
    "AnnotationUpdate",
]

ANNOTATION_SORT_FIELDS = frozenset({"ordering", "created_at", "updated_at", "kind", "confidence"})

#: ``LE_MAX_ANNOTATIONS_PER_IMAGE``. Mirrored as the bulk-upsert batch ceiling so
#: a single request cannot exceed the per-image cap it is about to violate.
MAX_ANNOTATIONS_PER_IMAGE = 2000

#: ★ **0–1** — the SURVEYOR'S OWN certainty, typed into the annotation tool.
#:
#: ★ THE TWO CONFIDENCE SCALES ARE DELIBERATE AND MUST NOT BE UNIFIED (§6.1).
#: This is 0–1 and is a human assertion about a mark on a photograph.
#: ``GcpRead.confidence`` is 0–100. They mean different things, are produced by
#: different actors, and are **never compared**. The DB enforces both ranges with
#: CHECK constraints. Any client rendering a "confidence" bar must read the
#: field's scale from the field, not guess.
AnnotationConfidence = Annotated[float, Field(ge=0.0, le=1.0)]


def _reject_crs_member(value: Any) -> Any:
    """★ §13.1 (IU-17): ``AnnotationCreate`` REJECTS a ``crs`` member in
    ``geometry``.

    ``geometry`` is GeoJSON-**shaped** but is NOT geographic: its
    ``coordinates`` are IMAGE PIXELS, ``[x, y]``, y-down, SRID 0 — not
    ``[lon, lat]``. The shape is reused because every client library and Konva's
    serializer already understand it, while the CRS is unambiguously declared by
    the resource being image-scoped.

    **To make the trap impossible to fall into, the API rejects any ``crs``
    member on input and never emits one.** A reader must not feed this into
    Leaflet expecting degrees, and a writer must not believe declaring a CRS here
    will do anything.

    This runs ``mode="before"``: ``GeoJsonGeometry``'s own ``extra="forbid"``
    would already reject ``crs`` — RFC 7946 removed it from the spec — but with a
    generic *"Extra inputs are not permitted"*. On the one field where the whole
    point is that a plausible-looking member is a category error, the message has
    to say so. Rejecting it in two places is not redundancy; the second one is
    the documentation.
    """
    if isinstance(value, dict) and "crs" in value:
        raise ValueError(
            "geometry must not carry a 'crs' member: these coordinates are IMAGE "
            "PIXELS ([x, y], y-down, SRID 0), not geographic degrees. RFC 7946 "
            "removed 'crs' from GeoJSON, and declaring one here would be ignored "
            "— which is worse than refused."
        )
    return value


def _reject_crs_geometry(data: Any) -> Any:
    """Apply :func:`_reject_crs_member` to a body's ``geometry`` before parsing."""
    if isinstance(data, dict):
        _reject_crs_member(data.get("geometry"))
    return data


class AnnotationStyle(ApiModel):
    """Presentation hints. Stored verbatim; the server never interprets them."""

    color: str | None = None
    fill_opacity: float | None = Field(default=None, ge=0.0, le=1.0)
    stroke_width: float | None = Field(default=None, ge=0.0)


class AnnotationCreate(ApiModel):
    """``POST /images/{image_id}/annotations`` — endpoint 17.

    Validation mirrors the DDL CHECKs so a violation is a clean 422, not a
    ``23514``: ``geom_type`` matches ``geometry.type`` · polyline ≥ 2 pts ·
    polygon exterior ring ≥ 4 pts and closed · 2D only · ≤ 10 000 vertices —
    all enforced here. ``ST_IsValid``, the ``[0, width] × [0, height]`` bounds
    check (``422 ANNOTATION_OUT_OF_BOUNDS``) and the ≤ 2000-per-image cap need
    PostGIS or a row count, so they live in ``annotation_service`` — a schema
    cannot know how wide the image is.

    ★ ``pixel_x``/``pixel_y`` are **derived server-side, never accepted from the
    client** (§5.6) — they are the *representative point* of the annotation
    whatever its type: identical to the vertex for points,
    ``ST_PointOnSurface`` for polygons, midpoint-along-arc for polylines.
    Accepting them would let the column drift from ``pixel_geom``, and that
    column is what the label renderer and the GCP deriver read. They are absent
    from this schema for exactly that reason.
    """

    kind: AnnotationKind = AnnotationKind.GENERIC
    geom_type: AnnotationGeomType
    geometry: GeoJsonGeometry
    label: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    confidence: AnnotationConfidence = 1.0
    ordering: int = 0
    style: dict[str, Any] = Field(default_factory=dict)
    attributes: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _no_crs(cls, data: Any) -> Any:
        return _reject_crs_geometry(data)

    @model_validator(mode="after")
    def _geom_type_matches_geometry(self) -> "AnnotationCreate":
        _check_geom_type_match(self)
        return self


#: ``geom_type`` ↔ the GeoJSON ``type`` it must agree with. A MultiPolygon is a
#: ``polygon`` annotation: the DDL stores ``pixel_geom`` as a generic GEOMETRY
#: and the kind vocabulary does not distinguish them.
_GEOM_TYPE_TO_GEOJSON: dict[AnnotationGeomType, frozenset[str]] = {
    AnnotationGeomType.POINT: frozenset({"Point"}),
    AnnotationGeomType.POLYLINE: frozenset({"LineString"}),
    AnnotationGeomType.POLYGON: frozenset({"Polygon", "MultiPolygon"}),
}


def _check_geom_type_match(model: Any) -> Any:
    """``geom_type`` must agree with ``geometry.type``.

    Two fields carrying one fact is a drift generator, and this is the one place
    it is caught. The DDL has the same CHECK; catching it here makes it a clean
    422 with a ``loc`` instead of a ``23514`` surfacing as a 500.
    """
    geom_type = getattr(model, "geom_type", None)
    geometry = getattr(model, "geometry", None)
    if geom_type is None or geometry is None:
        return model  # a partial patch item; nothing to cross-check
    expected = _GEOM_TYPE_TO_GEOJSON[geom_type]
    actual = geometry.type
    if actual not in expected:
        raise ValueError(
            f"geom_type={geom_type.value!r} requires geometry.type in "
            f"{sorted(expected)}, got {actual!r}."
        )
    return model


class AnnotationUpdate(PatchModel):
    """``PATCH /annotations/{annotation_id}`` — endpoint 21.
    ★ ``If-Match`` is **REQUIRED** (428 when absent, 412 on a stale
    ``version_no``).

    ★ SCOPE.md §5: editing the annotation is how the **photo endpoint** of a
    manual correspondence is re-committed. It marks any derived GCP **stale**
    (§6.2) rather than silently moving the coordinate — *"the algorithm put the
    coordinate in the wrong place"* and *"I marked the wrong pixel"* are two
    different claims and they get two different endpoints.
    """

    kind: AnnotationKind | None = None
    geom_type: AnnotationGeomType | None = None
    geometry: GeoJsonGeometry | None = None
    label: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    confidence: AnnotationConfidence | None = None
    ordering: int | None = None
    style: dict[str, Any] | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="before")
    @classmethod
    def _no_crs(cls, data: Any) -> Any:
        return _reject_crs_geometry(data)

    @model_validator(mode="after")
    def _geom_type_matches_geometry(self) -> "AnnotationUpdate":
        # ★ Only cross-checks when BOTH were sent. Patching `geometry` alone
        #   against a stored `geom_type` is the service's join to make — it is
        #   the only party that knows the stored value.
        if "geom_type" in self.model_fields_set and "geometry" in self.model_fields_set:
            _check_geom_type_match(self)
        return self


class AnnotationRead(ApiModel):
    """``AnnotationRead`` — endpoints 16, 17, 20, 21, 22."""

    id: UUID
    image_id: UUID
    kind: AnnotationKind
    geom_type: AnnotationGeomType
    pixel_x: float = Field(
        description="Representative point; == the point for geom_type=point."
    )
    pixel_y: float
    geometry: GeoJsonGeometry = Field(
        description=(
            "★ GeoJSON-SHAPED but IMAGE PIXELS: [x, y], y-down, SRID 0 — NOT "
            "[lon, lat]. Do not feed this to Leaflet expecting degrees. The API "
            "rejects any 'crs' member on input and never emits one."
        )
    )
    label: str | None
    description: str | None
    confidence: AnnotationConfidence = Field(
        description="★ 0-1, the SURVEYOR'S certainty. NOT the 0-100 GCP scale."
    )
    ordering: int
    style: dict[str, Any]
    attributes: dict[str, Any]
    version_no: int = Field(description="-> ETag. Required on update/delete for If-Match.")
    revision_seq: int
    is_deleted: bool
    is_gcp_candidate: bool = Field(
        description=(
            "★ Derived: kind in {field_corner, road_intersection, "
            "building_corner}. There is deliberately NO `geom_type == point` "
            "clause: the representative point IS the candidate location for any "
            "geometry type — that is what it is for — and gcps.landmark_id is "
            "FK'd to the general annotations table precisely so 'a polygon "
            "corner can be a GCP' works."
        )
    )
    gcp_ids: list[UUID] = Field(
        default_factory=list,
        description=(
            "★ ALL GCPs derived from this annotation, ordered by "
            "match_results.rank ASC. Empty when none. It is a ONE-TO-MANY: "
            "uq_gcps_landmark_match permits one GCP per landmark PER MATCH "
            "RESULT, losing candidates are kept, and a recompute writes a NEW "
            "match_results row. A scalar `gcp_id` over a one-to-many had no "
            "defined answer — the repository would have picked arbitrarily and "
            "the canvas would have linked to a stale candidate."
        ),
    )
    gcp_id: UUID | None = Field(
        default=None,
        description=(
            "★ The GCP whose match_result has is_selected = TRUE, else null. It "
            "is what the canvas link actually wants. Two fields because there are "
            "genuinely two questions: 'which one is live?' and 'what else "
            "exists?'."
        ),
    )
    created_by: str | None
    updated_by: str | None
    created_at: datetime
    updated_at: datetime


class AnnotationSummary(ApiModel):
    """List projection."""

    id: UUID
    image_id: UUID
    kind: AnnotationKind
    geom_type: AnnotationGeomType
    pixel_x: float
    pixel_y: float
    label: str | None
    confidence: AnnotationConfidence
    is_gcp_candidate: bool
    gcp_id: UUID | None
    version_no: int


class AnnotationListParams(ListParams):
    """``GET /images/{image_id}/annotations`` — endpoint 16."""

    kind: str | None = Field(default=None, description="CSV of AnnotationKind.")
    geom_type: str | None = Field(default=None, description="CSV of AnnotationGeomType.")
    is_gcp_candidate: bool | None = None
    include_deleted: bool = False
    revision_seq: int | None = Field(
        default=None, description="Read the annotation set as of this revision."
    )
    q: str | None = Field(default=None, description="Free-text over label + description.")


# ─────────────────────────────────────────────────────────────────────────────
# Bulk upsert — the ONE write path for the canvas (§6.2, endpoint 18)
# ─────────────────────────────────────────────────────────────────────────────


class AnnotationBulkUpsertItem(ApiModel):
    """One desired change.

    ★ ``id`` must be **null for ``create``** and non-null otherwise;
    ``version_no`` is **required for update/delete/restore** — optimistic
    locking is not optional on a survey annotation set. Both are enforced below
    rather than left to the service, because they are statements about *this
    body* and a body that cannot be applied should never reach a transaction.
    """

    id: UUID | None = None
    op: AnnotationOp
    version_no: int | None = None
    client_ref: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "Temp id echoed back so the store can swap `tmp-17` -> the real UUID."
        ),
    )
    kind: AnnotationKind | None = None
    geom_type: AnnotationGeomType | None = None
    geometry: GeoJsonGeometry | None = None
    label: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    confidence: AnnotationConfidence | None = None
    ordering: int | None = None
    style: dict[str, Any] | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="before")
    @classmethod
    def _no_crs(cls, data: Any) -> Any:
        return _reject_crs_geometry(data)

    @model_validator(mode="after")
    def _check_op_shape(self) -> "AnnotationBulkUpsertItem":
        if self.op is AnnotationOp.CREATE:
            if self.id is not None:
                raise ValueError("op='create' requires id to be null.")
            if self.geom_type is None or self.geometry is None:
                raise ValueError("op='create' requires geom_type and geometry.")
        else:
            if self.id is None:
                raise ValueError(f"op={self.op.value!r} requires id.")
            if self.version_no is None:
                raise ValueError(
                    f"op={self.op.value!r} requires version_no — a blind write to a "
                    "survey annotation set is how two surveyors silently overwrite "
                    "each other."
                )
        if self.geom_type is not None and self.geometry is not None:
            _check_geom_type_match(self)
        return self


class AnnotationBulkUpsertRequest(ApiModel):
    """``PUT /images/{image_id}/annotations`` — endpoint 18.

    ★ **``PUT`` on the collection is correct here.** The request declares the
    desired state of the image's annotation set; it is idempotent. Six separate
    PATCHes would produce six revisions (making undo useless), six round trips,
    and a partially-saved canvas if the fourth fails.

    ★ **Atomicity: all-or-nothing.** One transaction, ``SELECT … FOR UPDATE`` on
    the project row (which also serialises ``current_revision_seq`` allocation).
    *A partial save on a survey annotation set is worse than no save: the
    surveyor believes the canvas matches the database when it does not.*
    """

    mode: Literal["merge", "replace"] = "merge"
    base_revision_seq: int | None = Field(
        default=None,
        description="Optimistic concurrency for the SET. Stale -> 409 REVISION_CONFLICT.",
    )
    revision_label: str | None = Field(default=None, max_length=200)
    client_op_id: str | None = Field(
        default=None, max_length=64, description="Client-side idempotency for a retried save."
    )
    items: Annotated[
        list[AnnotationBulkUpsertItem],
        Field(min_length=1, max_length=MAX_ANNOTATIONS_PER_IMAGE),
    ]


class AnnotationBulkUpsertResultItem(ApiModel):
    """What happened to one item."""

    id: UUID
    client_ref: str | None
    op: AnnotationOp
    status: Literal["created", "updated", "deleted", "restored", "unchanged"] = Field(
        description=(
            "★ 'unchanged' is returned when an update is byte-identical to "
            "current state, and NO revision event is written. Without this, an "
            "idle canvas auto-saving every 30 s inflates the undo stack with "
            "thousands of no-op events."
        )
    )
    version_no: int


class AnnotationApplyCounts(ApiModel):
    """The rollup of one bulk apply."""

    created: int
    updated: int
    deleted: int
    restored: int
    unchanged: int


class AnnotationBulkUpsertResponse(ApiModel):
    """Endpoints 18, 19 — and **45** (suggestion accept), which is why
    :class:`RevisionSummary` lives in ``common``.
    """

    revision: RevisionSummary
    applied: AnnotationApplyCounts
    items: list[AnnotationBulkUpsertResultItem]
    annotations: list[AnnotationRead] = Field(
        description=(
            "★ THE FULL RESULTING LIVE SET. Costs one query and removes an entire "
            "class of desync — the client replaces its store wholesale instead of "
            "reconciling deltas."
        )
    )
    warnings: list[WarningItem] = Field(default_factory=list)
