"""``ApiModel`` and the shared wire vocabulary (§6.2).

★ **THE IMPORT DIRECTION IS ONE-WAY** (§6.2): ``common`` / ``enums`` / ``errors``
← everything else. This module imports **nothing** from the schema package. That
is what keeps the graph acyclic and lets any schema be imported into a Celery
worker without dragging in FastAPI.

★ **L9 IS ABSOLUTE.** snake_case on the wire, in Python, and in TypeScript. No
alias generator. No case-mapping layer. ``ApiModel`` therefore sets **no**
``alias_generator``, and the only aliases in the whole package are the two
single, deliberate ones that a Python-reserved word forced (``metadata`` in
``project.py``/``image.py``, ``class`` in ``semantic.py``). L9 forbids a
generator, not a named exemption — and the distinction is the point: a generator
renames every field invisibly and creates a second source of truth.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Final, Generic, Literal, Sequence, TypeVar
from uuid import UUID

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

__all__ = [
    "MAX_SORT_KEYS",
    "UNSET",
    "AlbumRef",
    "ApiModel",
    "BBox",
    "CountResponse",
    "DeletedResponse",
    "GeoJsonFeature",
    "GeoJsonFeatureCollection",
    "GeoJsonGeometry",
    "GeoJsonLineString",
    "GeoJsonMultiPolygon",
    "GeoJsonPoint",
    "GeoJsonPolygon",
    "IdResponse",
    "LatLon",
    "LatLonAlt",
    "ListParams",
    "META_FIELD",
    "Page",
    "PaginationParams",
    "PatchModel",
    "PixelBox",
    "PixelXY",
    "ResultRef",
    "RevisionSummary",
    "SortParams",
    "Unset",
    "WarningItem",
]


class ApiModel(BaseModel):
    """The base of **every** model in this package (§6).

    ``extra="forbid"`` is the load-bearing one: a typo'd field is a 422, never a
    silent no-op. A client that sends ``{"confidance": 80}`` and gets a 200 back
    believes it set the confidence. It did not.
    """

    model_config = ConfigDict(
        from_attributes=True,
        extra="forbid",  # ★ a typo'd field is a 422, never a silent no-op
        str_strip_whitespace=True,
        # ★ NO alias_generator. snake_case end to end (L9, §12 C-08).
    )


# ─────────────────────────────────────────────────────────────────────────────
# The `metadata` exemption (§6.2)
# ─────────────────────────────────────────────────────────────────────────────

#: ★ THE SINGLE DELIBERATE FIELD-LEVEL ALIAS, declared once and reused by the
#: exactly three schemas §6.2 permits it on: ``ProjectCreate``, ``ProjectRead``
#: and ``ImageRead`` (plus their ``*Update`` twins, which carry the same field).
#:
#: ``ApiModel`` sets ``from_attributes=True``, and those schemas declare a field
#: literally named ``metadata``. But §5.6 states the ORM **attribute** is ``meta``
#: and only the **column** is ``metadata`` — because ``metadata`` is reserved on
#: ``DeclarativeBase``. So ``ProjectRead.model_validate(project_orm)`` would do
#: ``getattr(project, "metadata")`` and receive **SQLAlchemy's ``MetaData``
#: object**, not the JSONB dict. Every project and image read would fail
#: validation.
#:
#: ``AliasChoices("meta", "metadata")`` accepts the ORM attribute AND the wire
#: key; ``serialization_alias="metadata"`` guarantees the wire name never
#: changes. FastAPI serialises response models with ``by_alias=True``, so the
#: emitted key is ``metadata`` — L9 intact.
#:
#: §13.1 (IU-17): ``ProjectRead.model_validate(project_orm).metadata ==
#: project_orm.meta``.
META_FIELD: Final = Field(
    default_factory=dict,
    # ★ BOTH choices are load-bearing, in opposite directions:
    #   "meta"     — the ORM attribute, for `model_validate(project_orm)`.
    #   "metadata" — the WIRE key, for `ProjectCreate(**body)`. Without it,
    #                `{"metadata": {...}}` hits extra="forbid" and 422s every
    #                create that sets metadata at all.
    # A single validation_alias would have silently broken one direction or the
    # other depending on which one it named.
    validation_alias=AliasChoices("meta", "metadata"),
    serialization_alias="metadata",
    description="Free-form client metadata. Max 16 KB serialised.",
)


# ─────────────────────────────────────────────────────────────────────────────
# UNSET — PATCH bodies only (§6.1)
# ─────────────────────────────────────────────────────────────────────────────


class Unset:
    """The "client omitted this key" marker for PATCH bodies.

    ★ **Nulls — RESPONSES** are never omitted: a nullable field is always
    present with value ``null``, and clients must not distinguish absent from
    null. **PATCH bodies are the ONE exception** (§6.1): ``{"aoi": null}``
    *clears*, ``{}`` leaves untouched. Without the distinction a nullable field
    is **un-clearable through PATCH** — a real, common bug.

    ★ **Why this is a sentinel and not a field default.** Pydantic v2 already
    records which keys the client actually sent, in ``model_fields_set``. Making
    ``UNSET`` a *validatable value* instead would put it in the JSON Schema and
    let a client literally send it — turning an internal marker into wire
    surface. So the sentinel never touches the wire: it is what
    :meth:`PatchModel.get` **returns** to the service layer, so that layer can
    branch on three cases explicitly (``UNSET`` / ``None`` / a value) instead of
    passing ``model_fields_set`` around by hand and getting it wrong once.

    The OpenAPI shape stays exactly what §6.1's TS note describes: every
    ``XxxUpdate`` field is optional and ``T | null``; the client omits the key
    (``JSON.stringify`` drops ``undefined``) for "leave untouched".
    """

    __slots__ = ()
    _instance: "Unset | None" = None

    def __new__(cls) -> "Unset":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __bool__(self) -> bool:
        """Falsy, so ``if value:`` treats "omitted" as "nothing to do"."""
        return False

    def __repr__(self) -> str:
        return "UNSET"

    def __copy__(self) -> "Unset":
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> "Unset":
        return self

    def __reduce__(self) -> str:
        return "UNSET"


#: The singleton. ``x is UNSET`` is the only sanctioned test.
UNSET: Final[Unset] = Unset()


class PatchModel(ApiModel):
    """Base for every ``XxxUpdate`` (PATCH) body. ★ UNSET semantics.

    Subclasses declare every field optional with a ``None`` default. This base
    supplies the three-way read that the services need and nothing else — it
    adds no fields and no wire surface.

    ★ **It does not raise ``EmptyPatch`` itself.** ``400 EMPTY_PATCH`` is a
    domain error from ``app.core.exceptions``, and §10.2 permits ``app.schemas``
    to import ``pydantic`` and ``app.core.constants`` — *not* ``core.exceptions``.
    Raising a bare ``ValueError`` here would surface as a **422**, and the
    contract says **400**. So this class exposes :meth:`is_empty` and the router
    or service raises the right typed error. Refusing to fake the status code is
    cheaper than a wrong one (L12).
    """

    def changed_fields(self) -> frozenset[str]:
        """The field names the client actually sent — including those sent as
        ``null``.
        """
        return frozenset(self.model_fields_set)

    def is_empty(self) -> bool:
        """``True`` for ``{}`` — the caller raises ``400 EMPTY_PATCH``.

        ``{"aoi": null}`` is **not** empty: it is an instruction to clear.
        """
        return not self.model_fields_set

    def get(self, name: str) -> Any:
        """The value for ``name``, or :data:`UNSET` when the client omitted it.

        ``None`` means "clear this field"; ``UNSET`` means "leave it alone".
        These are different instructions and this is the only place the
        difference is decided.
        """
        if name not in self.model_fields_set:
            return UNSET
        return getattr(self, name)

    def as_changes(self) -> dict[str, Any]:
        """Only the sent keys, as a plain dict — ready for an ORM update.

        Omitted keys are absent; keys sent as ``null`` are present with value
        ``None``. That is exactly the semantics a repository's ``UPDATE`` wants.
        """
        return self.model_dump(exclude_unset=True)


# ─────────────────────────────────────────────────────────────────────────────
# Pagination (§6.1, §6.2)
# ─────────────────────────────────────────────────────────────────────────────

ItemT = TypeVar("ItemT")

#: ``?sort=`` accepts at most three keys. Beyond that the index cannot help and
#: the intent is almost always a filter.
MAX_SORT_KEYS: Final = 3


class PaginationParams(ApiModel):
    """``?limit=&offset=``.

    ★ Out of range is a **422, never a silent clamp**. Silent clamping makes
    clients believe they read everything — the bug reports it produces are
    "some of my GCPs are missing", raised weeks later against an export.

    ★ **Offset, not cursor**, and the reason is scale: a project holds tens of
    images, an image tens to low-hundreds of annotations, a match ≤ 25 results.
    Offset over an indexed ``(id DESC)`` is free at those cardinalities, and
    ``total`` is what the UI actually renders. Cursor pagination cannot cheaply
    produce ``total``.
    """

    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class SortParams(ApiModel):
    """``?sort=`` — comma-separated, leading ``-`` = descending, max 3 keys."""

    raw: str | None = None

    def parse(
        self, allowed: frozenset[str], default: str
    ) -> list[tuple[str, Literal["asc", "desc"]]]:
        """Parse ``raw`` into ``(field, direction)`` pairs.

        Args:
            allowed: the endpoint's sort whitelist.
            default: the sort applied when ``raw`` is absent or blank. Must
                itself be expressed in the ``?sort=`` grammar (e.g.
                ``"-created_at"``).

        Returns:
            Up to :data:`MAX_SORT_KEYS` pairs, in the order given.

        Raises:
            ValueError: on an unknown field, a blank key, a duplicate key, or
                more than :data:`MAX_SORT_KEYS` keys. The router converts this
                to ``422 INVALID_SORT_FIELD`` with the allowed set in
                ``details`` — a sort silently ignored is a page of the wrong
                rows.

        Note:
            **Every sort is stabilised by the repository**, which appends
            ``id ASC`` as the final tiebreaker (§6.2). Without it, offset
            pagination over equal-valued rows — 40 GCPs all at
            ``confidence = 100`` — duplicates and drops rows across pages. It is
            invisible to the client, always applied, and deliberately NOT
            expressed here: this method parses what the client asked for, and
            the tiebreaker is not something the client asked for.
        """
        spec = self.raw if (self.raw and self.raw.strip()) else default
        keys: list[tuple[str, Literal["asc", "desc"]]] = []
        seen: set[str] = set()

        for token in spec.split(","):
            token = token.strip()
            if not token:
                raise ValueError("Empty sort key.")
            direction: Literal["asc", "desc"] = "asc"
            if token.startswith("-"):
                direction = "desc"
                token = token[1:].strip()
            if not token:
                raise ValueError("Empty sort key.")
            if token not in allowed:
                raise ValueError(f"Unknown sort field {token!r}.")
            if token in seen:
                raise ValueError(f"Duplicate sort field {token!r}.")
            seen.add(token)
            keys.append((token, direction))

        if len(keys) > MAX_SORT_KEYS:
            raise ValueError(f"At most {MAX_SORT_KEYS} sort keys are allowed.")
        return keys


class ListParams(PaginationParams):
    """Base for every ``XxxListParams`` query dependency.

    ★ ``extra="forbid"`` is inherited from ``ApiModel`` and is the whole point:
    an **unknown query param is a 422 ``UNKNOWN_QUERY_PARAM``, never ignored**.
    *A typo'd filter that silently returns unfiltered data is how a surveyor
    exports the wrong parcel.*
    """

    sort: str | None = None


class Page(ApiModel, Generic[ItemT]):
    """The envelope for **every** collection response.

    ★ Inherits ``ApiModel``, not ``BaseModel``. §6 says in bold that every model
    inherits ``ApiModel``, and v1.0 then defined ``Page(BaseModel, Generic[T])``
    — so ``Page`` alone lacked ``extra="forbid"``, ``from_attributes=True`` and
    ``str_strip_whitespace``, and IU-17's mandated introspection sweep ("every
    model sets ``extra='forbid'``") failed on it. Pydantic v2 supports generic
    models on any ``BaseModel`` subclass; the ``ConfigDict`` is inherited.

    ★ **Never a bare list.** A bare top-level JSON array is a hijacking footgun
    and makes adding pagination a breaking change.

    ★ Parameterised per route (``response_model=Page[ImageSummary]``), producing
    a distinct named OpenAPI component ``Page_ImageSummary_`` and therefore a
    clean generated TS type.
    """

    items: list[ItemT]
    total: int = Field(ge=0, description="Exact count matching the filter, ignoring limit/offset.")
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)
    has_more: bool = Field(description="offset + len(items) < total")

    @classmethod
    def of(cls, items: Sequence[ItemT], total: int, p: PaginationParams) -> "Page[ItemT]":
        """Build a page from a slice and its unfiltered total.

        ``has_more`` is derived, never passed in — it is a function of the other
        three, and letting a caller supply it is letting a caller get it wrong.
        """
        item_list = list(items)
        return cls(
            items=item_list,
            total=total,
            limit=p.limit,
            offset=p.offset,
            has_more=p.offset + len(item_list) < total,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Warnings — the NON-ERROR channel (§6.2)
# ─────────────────────────────────────────────────────────────────────────────


class WarningItem(ApiModel):
    """★ THE NON-ERROR CHANNEL. A missing SuperGlue weight is a successful match
    with a note (L11), not a failure.

    ★ The distinction that decides how a client renders this is
    ``requested is not None``: an **unrequested** fallback is INFORMATIONAL
    ("Matched with SIFT + FLANN"); a **requested-and-denied** one is a WARNING.
    Per SCOPE.md the classical path is the default state on a fresh machine —
    framing it as a degradation would be both wrong and demoralising.
    """

    code: str = Field(description="SCREAMING_SNAKE, e.g. MODEL_WEIGHTS_MISSING.")
    message: str
    field: str | None = None
    requested: str | None = Field(
        default=None,
        description="What the client explicitly asked for, or null if it did not ask.",
    )
    effective: str | None = Field(default=None, description="What it will actually get.")


# ─────────────────────────────────────────────────────────────────────────────
# Points, boxes, transforms (§6.1's conventions — load-bearing)
# ─────────────────────────────────────────────────────────────────────────────


class LatLon(ApiModel):
    """EPSG:4326 decimal degrees. ★ ``lat`` then ``lon``.

    This is **not** GeoJSON order — RFC 7946 mandates ``[x, y]`` i.e.
    ``[lon, lat]`` inside any GeoJSON ``coordinates``. Both conventions are
    right in their own place, and the field names are what disambiguate.
    """

    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)


class LatLonAlt(LatLon):
    """A :class:`LatLon` with an ellipsoidal height.

    ★ ``altitude_m`` is nullable and ``null`` is HONEST: no elevation provider
    resolved. ``0`` would be a fabrication at sea level (§4.27).
    """

    altitude_m: float | None = None


class PixelXY(ApiModel):
    """A point in image OR satellite-mosaic pixel space.

    ★ Which space is named by the FIELD that holds it (``image_px`` vs
    ``satellite_px``), never by this type. Origin top-left, y-down, float
    (sub-pixel).

    ★ **An integer coordinate is the pixel CENTRE** — the OpenCV/SIFT convention
    and what every keypoint we produce means. GDAL geotransform columns are
    pixel EDGES; the bridge is ``col_gdal = u_cv + 0.5`` and it is applied in
    ``gis.tiles``, not here (§6.1).
    """

    x: float
    y: float


class PixelBox(ApiModel):
    """An axis-aligned box in pixel space, y-down."""

    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @model_validator(mode="after")
    def _check_ordering(self) -> "PixelBox":
        if self.min_x > self.max_x or self.min_y > self.max_y:
            raise ValueError("min_x/min_y must not exceed max_x/max_y.")
        return self


class BBox(ApiModel):
    """A geographic bounding box, EPSG:4326.

    Wire form on a query string is the CSV ``"minlon,minlat,maxlon,maxlat"``;
    parsed to this. Wire form in a body is this object.
    """

    min_lon: float = Field(ge=-180.0, le=180.0)
    min_lat: float = Field(ge=-90.0, le=90.0)
    max_lon: float = Field(ge=-180.0, le=180.0)
    max_lat: float = Field(ge=-90.0, le=90.0)

    @model_validator(mode="after")
    def _check_ordering(self) -> "BBox":
        if self.min_lat > self.max_lat:
            raise ValueError("min_lat must not exceed max_lat.")
        if self.min_lon > self.max_lon:
            # ★ An antimeridian-crossing bbox is a 422 BBOX_CROSSES_ANTIMERIDIAN
            #   rather than silently mishandled (§6.2). The router maps this. We
            #   refuse rather than answer wrongly (L12): silently swapping the
            #   bounds would return the ENTIRE WORLD MINUS the requested strip —
            #   plausible-looking, and exactly inverted.
            raise ValueError(
                "min_lon exceeds max_lon: the bbox crosses the antimeridian, "
                "which is not supported. Split it into two boxes."
            )
        return self

    @classmethod
    def from_csv(cls, raw: str) -> "BBox":
        """Parse ``"minlon,minlat,maxlon,maxlat"``.

        Raises:
            ValueError: on the wrong arity or a non-numeric part. The router
                maps this to ``422 INVALID_BBOX``.
        """
        parts = [p.strip() for p in raw.split(",")]
        if len(parts) != 4:
            raise ValueError(
                "bbox must be 'minlon,minlat,maxlon,maxlat' — four comma-separated numbers."
            )
        try:
            min_lon, min_lat, max_lon, max_lat = (float(p) for p in parts)
        except ValueError as exc:
            raise ValueError("bbox parts must all be numbers.") from exc
        return cls(min_lon=min_lon, min_lat=min_lat, max_lon=max_lon, max_lat=max_lat)


# ─────────────────────────────────────────────────────────────────────────────
# GeoJSON (RFC 7946)
# ─────────────────────────────────────────────────────────────────────────────
#
# ★ THE TRAP, named here once so it cannot be fallen into: `AnnotationRead.
#   geometry` and `LandmarkSuggestionRead.pixel_geom` are GeoJSON-SHAPED but are
#   NOT geographic — their `coordinates` are IMAGE PIXELS, [x, y], y-down,
#   SRID 0. The shape is reused because every client library and Konva's
#   serializer already understand it, while the CRS is unambiguously declared by
#   the resource being image-scoped.
#
#   To make the trap impossible to fall into, the API REJECTS any `crs` member
#   on input (422 ANNOTATION_GEOMETRY_INVALID) and never emits one. `extra=
#   "forbid"` on these models is what mechanically enforces that: RFC 7946
#   removed `crs` from the spec, so a body carrying one is rejected by the base
#   config with no bespoke validator at all.
#
#   Geographic GeoJSON (`ProjectCreate.aoi`, `MatchResultRead.tile_bounds`,
#   `CameraPoseRead.footprint`) carries [lon, lat], in that order.

#: A single position. RFC 7946 permits a third (altitude) element; we do not —
#: every geometry on this wire is 2-D, the DDL CHECKs enforce it, and a silently
#: accepted third ordinate would reach PostGIS as a Z coordinate that no index
#: and no exporter here handles.
Position = Annotated[list[float], Field(min_length=2, max_length=2)]

#: Vertex budgets, mirroring the DDL CHECKs so a violation is a clean 422 rather
#: than a `23514` from Postgres.
MAX_POLYGON_VERTICES: Final = 10_000
MAX_AOI_VERTICES: Final = 1_000


class GeoJsonPoint(ApiModel):
    """RFC 7946 Point."""

    type: Literal["Point"] = "Point"
    coordinates: Position


class GeoJsonLineString(ApiModel):
    """RFC 7946 LineString. ≥ 2 positions."""

    type: Literal["LineString"] = "LineString"
    coordinates: Annotated[list[Position], Field(min_length=2, max_length=MAX_POLYGON_VERTICES)]


class GeoJsonPolygon(ApiModel):
    """RFC 7946 Polygon. Exterior ring first, then holes.

    Each ring must be **closed** (first position equals last) and carry ≥ 4
    positions — RFC 7946 §3.1.6. Validated here so a malformed ring is a clean
    422 rather than an ``ST_IsValid`` rejection surfacing as a 500.
    """

    type: Literal["Polygon"] = "Polygon"
    coordinates: Annotated[list[list[Position]], Field(min_length=1)]

    @field_validator("coordinates")
    @classmethod
    def _check_rings(cls, rings: list[list[Position]]) -> list[list[Position]]:
        total = 0
        for i, ring in enumerate(rings):
            if len(ring) < 4:
                raise ValueError(f"Ring {i} has {len(ring)} positions; a closed ring needs >= 4.")
            if ring[0] != ring[-1]:
                raise ValueError(f"Ring {i} is not closed: the first and last positions differ.")
            total += len(ring)
        if total > MAX_POLYGON_VERTICES:
            raise ValueError(f"Polygon has {total} vertices; the limit is {MAX_POLYGON_VERTICES}.")
        return rings


class GeoJsonMultiPolygon(ApiModel):
    """RFC 7946 MultiPolygon."""

    type: Literal["MultiPolygon"] = "MultiPolygon"
    coordinates: Annotated[list[list[list[Position]]], Field(min_length=1)]


#: ★ A DISCRIMINATED union on ``type``. Pydantic picks the member by the literal
#: rather than trying each in turn, so a malformed Polygon reports *"ring 0 is
#: not closed"* instead of *"did not match any of 4 variants"* — the second is
#: technically true and diagnostically useless.
GeoJsonGeometry = Annotated[
    GeoJsonPoint | GeoJsonLineString | GeoJsonPolygon | GeoJsonMultiPolygon,
    Field(discriminator="type"),
]


class GeoJsonFeature(ApiModel):
    """RFC 7946 Feature."""

    type: Literal["Feature"] = "Feature"
    geometry: GeoJsonGeometry
    properties: dict[str, Any] = Field(default_factory=dict)
    id: str | int | None = None


class GeoJsonFeatureCollection(ApiModel):
    """RFC 7946 FeatureCollection.

    ★ The one place a collection is not a :class:`Page`: ``GET /images/{id}/gcps
    ?format=geojson`` (endpoint 38) must emit a spec-conformant
    ``FeatureCollection`` or it is not GeoJSON and QGIS will not open it. The
    ``format=json`` branch of the same endpoint returns ``Page[GcpRead]``, so
    the pagination rule is not weakened — a second representation is offered,
    and the client names which one it wants.
    """

    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[GeoJsonFeature] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Misc shared value objects
# ─────────────────────────────────────────────────────────────────────────────


class ResultRef(ApiModel):
    """What a finished job produced. ``JobRead.result_ref``."""

    kind: str = Field(
        description='"match_result" | "export" | "batch" | "semantic_features" | "suggestions"'
    )
    id: str


class RevisionSummary(ApiModel):
    """★ MOVED HERE from ``revision.py``, and the move is what makes §6.2's
    acyclic rule TRUE rather than exempted.

    It is a shared value object: ``annotation.py``'s
    ``AnnotationBulkUpsertResponse.revision`` needs it, and endpoint 45
    (``suggestions.py``) returns that same response. §6.2 states the import
    direction is one-way — ``common``/``enums``/``errors`` ← everything else —
    and v1.0 then put ``RevisionSummary`` in ``revision.py`` and referenced it
    from ``annotation.py``, violating the rule on its first cross-reference.
    (§8.2's TS table had independently put it in ``common.ts``, so the frontend
    had already voted for this placement.)

    ``RevisionRead`` — the fat one, with snapshot/events/diff_summary — stays in
    ``revision.py``; nothing outside revisions needs it.
    """

    id: UUID
    project_id: UUID
    seq: int
    label: str | None
    is_checkpoint: bool
    annotation_count: int
    created_at: datetime


class AlbumRef(ApiModel):
    """An album named on something that is *in* it — ``ProjectSummary.albums``.

    ★ **Here rather than in ``album.py``, for the reason §6.2 gives for
    ``RevisionSummary``.** ``project.py`` needs this pair and ``album.py`` needs it, and
    the package's stated import direction is one-way — ``common``/``enums``/``errors`` ←
    everything else. Putting it in ``album.py`` would create a ``project → album`` edge
    (and, the moment an album response wanted to name its projects, a genuine cycle).
    The move is the contract already resolving this exact class of problem.

    ★ **``{id, name}`` and nothing more.** A project list row renders chips; it does not
    render descriptions or colours-per-chip, and every extra field here is a column
    fetched once per membership per row.
    """

    id: UUID
    name: str


class IdResponse(ApiModel):
    """A bare created/affected id."""

    id: UUID


class DeletedResponse(ApiModel):
    """A soft-delete acknowledgement."""

    id: UUID
    deleted: bool


class CountResponse(ApiModel):
    """A bare count."""

    count: int
