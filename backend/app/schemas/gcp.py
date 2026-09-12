"""Ground Control Points — ★ **THE DELIVERABLE** (§6.2) — endpoints 38–42, 64.

★★ **SCOPE.md §5 makes this module the product.** With the automatic engine
deferred, a GCP is created by a **manual correspondence**: the surveyor marks a
landmark in the photo, clicks the same physical spot on the satellite map, and
the coordinate is recorded. **It is a DIRECT OBSERVATION, not an inference.**

Three schemas here are ADDED by SCOPE.md §5 and are flagged in IU-17's report,
because §6 has none of them — it assumed every GCP came out of a homography:

- :class:`GcpManualCreate`  — endpoint **65** (new), ``POST /images/{id}/gcps``.
- :class:`GcpCorrespondenceUpdate` — endpoint **66** (new),
  ``PUT /gcps/{id}/correspondence``.
- ``source`` / ``declared_confidence`` on :class:`GcpRead` and
  :class:`GcpSummary`.

★ **A GCP is a survey coordinate someone may dig, build, or file against**
(L12). Every honesty mechanism in this file exists for that sentence.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from .common import ApiModel, ListParams, PatchModel, PixelXY
from .enums import (
    EstimatorName,
    GcpSource,
    GcpStaleReason,
    ProviderName,
    SurveyorConfidence,
)

__all__ = [
    "GCP_CODE_PATTERN",
    "GCP_SORT_FIELDS",
    "SURVEYOR_CONFIDENCE_TO_SCORE",
    "GcpAccuracy",
    "GcpCorrespondenceUpdate",
    "GcpLandmarkRef",
    "GcpListParams",
    "GcpManualCreate",
    "GcpCopyResult",
    "GcpOriginal",
    "GcpOverview",
    "GcpOverviewListParams",
    "GcpRead",
    "GcpRecomputeDelta",
    "GcpRecomputeDryRun",
    "GcpRecomputeFitStats",
    "GcpRecomputeRequest",
    "GcpResetRequest",
    "GcpSummary",
    "GcpUpdate",
]

GCP_SORT_FIELDS = frozenset(
    {"code", "confidence", "created_at", "updated_at", "lat", "lon", "total_ce90_m"}
)

#: ``'GCP01'``. Mirrors the DDL's ``ck_gcps_code`` so a violation is a clean 422.
GCP_CODE_PATTERN = r"^[A-Za-z0-9_\-]{1,32}$"

#: ★ SCOPE.md §5. The surveyor's 1–5 judgement -> the 0–100 ``confidence``
#: column.
#:
#: ★ **Why the mapping exists at all, and why it is here.** ``gcps.confidence``
#: is ``F8 NOT NULL`` with ``ck_gcps_confidence BETWEEN 0 AND 100`` (§5.6), and
#: SCOPE.md §4 rule 5 says the schema is **not cut**. So a manual GCP must write
#: *something* to that column, and the export column, the ``?confidence__gte=``
#: filter and the sort order all keep working only if it writes a number.
#:
#: ★ **Why these numbers.** They are the midpoints of the five bands a 0–100
#: scale divides into, aligned to the ``ConfidenceBand`` thresholds the UI
#: already uses (high ≥ 80, moderate ≥ 60, low ≥ 40, unreliable < 40 — §8.7).
#: So a surveyor's "4" lands in `high`, their "3" in `moderate`, and their "1"
#: in `unreliable`, which is what those words mean to the person who typed the
#: number.
#:
#: ★ **What it is NOT.** It is not a measurement and it does not become one by
#: being a float. ``declared_confidence`` is the field to read and to edit;
#: ``confidence`` is its representative, kept so the DB CHECK and the exports
#: keep working. ``GcpRead.confidence``'s docstring says which is which, and
#: ``source`` is what tells a downstream consumer that this number is a human
#: judgement rather than a pipeline score. **That is the entire reason SCOPE.md
#: §5 requires ``source``.**
#:
#: The mapping lives in the schema layer, not the service, because it is part of
#: the wire's meaning: a client that renders `confidence` must be able to know
#: exactly how it was derived, and IU-23's `theme/confidence.ts` mirrors this
#: table.
SURVEYOR_CONFIDENCE_TO_SCORE: dict[int, float] = {
    1: 20.0,  # unreliable — "I am guessing"
    2: 45.0,  # low
    3: 65.0,  # moderate
    4: 85.0,  # high
    5: 95.0,  # high — "this is unambiguously the same object"
}


class GcpAccuracy(ApiModel):
    """★ **TWO ACCURACIES, ALWAYS.** Reporting only the relative figure would
    tell a surveyor they have 0.3 m GCPs when they have 3 m GCPs.

    ★ **EVERY NUMBER HERE IS CE90** — a 2-D 90% radius (``2.146σ``) (§4.20). No
    field mixes levels; ``confidence_level`` ships on the wire so it cannot be
    misread.

    ★ SCOPE.md §5: in manual mode these come from the imagery's
    ground-sample-distance and the click precision at the map's zoom level —
    **a real, defensible number** — not from a match score. There is no
    homography, so there is nothing to propagate, and ``dominant_term`` reads
    ``landmark_click`` or ``georeference`` rather than ``match``. This is the
    field that tells a surveyor what to *fix*: *"your accuracy is limited by the
    basemap, not by your click."*
    """

    confidence_level: Literal["ce90"] = "ce90"
    relative_ce90_m: float = Field(
        ge=0.0, description="★ Our own fit / click, CE90, TRUE ground metres."
    )
    georef_ce90_m: float = Field(
        ge=0.0,
        description=(
            "The imagery provider's absolute georeferencing error. Always "
            "knowable — ProviderCapabilities.georef_ce90_m is mandatory."
        ),
    )
    total_ce90_m: float = Field(
        ge=0.0, description="★ sqrt(relative² + georef²). **THE headline number.**"
    )
    semi_major_ce90_m: float | None = Field(default=None, ge=0.0)
    semi_minor_ce90_m: float | None = Field(default=None, ge=0.0)
    azimuth_deg: float | None = Field(
        default=None, description="Major axis, 0 = North, clockwise."
    )
    dominant_term: Literal["match", "georeference", "landmark_click", "rectification"]

    @model_validator(mode="after")
    def _total_ge_parts(self) -> "GcpAccuracy":
        # ★ Mirrors ck_gcps_accuracy_total_ge_parts. A quadrature can never be
        #   smaller than either leg, and this catches a unit or sign slip in
        #   combine_accuracy before it reaches a survey report — not after.
        floor = max(self.relative_ce90_m, self.georef_ce90_m)
        if self.total_ce90_m + 1e-9 < floor:
            raise ValueError(
                f"total_ce90_m={self.total_ce90_m!r} is smaller than "
                f"max(relative_ce90_m, georef_ce90_m)={floor!r}; a quadrature "
                "cannot be smaller than either leg."
            )
        return self


class GcpOriginal(ApiModel):
    """The pre-adjustment answer, **kept forever**. Written once and never again.

    ★ For a manual GCP this is the surveyor's *first* committed click — so
    ``adjustment_offset_m`` measures how far they moved their own mark, which is
    exactly the audit trail a reviewer wants.
    """

    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)
    satellite_px: PixelXY
    confidence: float = Field(ge=0.0, le=100.0)


class GcpLandmarkRef(ApiModel):
    """The annotation this GCP was derived from, denormalised for the canvas link."""

    id: UUID
    label: str | None
    kind: str
    pixel_x: float
    pixel_y: float


class GcpRead(ApiModel):
    """``GcpRead`` — endpoints 38, 39, 40, 41, 64."""

    id: UUID
    image_id: UUID
    match_result_id: UUID | None = Field(
        default=None,
        description=(
            "★ provenance. A GCP is a *claim about the world*; a match_results row is the "
            "*evidence*. An AUTOMATIC GCP always has one. ★ SCOPE.md §5: a MANUAL GCP placed "
            "by a surveyor click carries NO match_results row in this build (the column "
            "`gcps.match_result_id` is nullable), so this is `null` for manual observations — "
            "the presenter passes the true value through and never fabricates evidence."
        ),
    )
    landmark_id: UUID | None = Field(
        default=None,
        description=(
            "★ ON DELETE SET NULL: the surveyor may tidy up annotations after "
            "the fact, and **the coordinate they already exported must survive**, "
            "orphaned but intact. image_px is copied onto the GCP precisely so it "
            "remains self-describing after the landmark is gone."
        ),
    )
    code: str | None = Field(default=None, pattern=GCP_CODE_PATTERN)
    name: str | None = Field(default=None, description="Free-text point name (the 'Name' column).")

    image_px: PixelXY = Field(
        description=(
            "★ ORIGINAL image pixel space — independent of viewer zoom, pan, or "
            "brightness/contrast. Sub-pixel: NEVER rounded for storage, rounded "
            "only for display. SCOPE.md §5 calls this conversion normative and "
            "correctness-critical."
        )
    )
    satellite_px: PixelXY | None = Field(
        default=None,
        description=(
            "Mosaic pixel space, origin top-left of the candidate mosaic, y-down. ★ `null` "
            "for a manual GCP that carries no satellite-mosaic fix (SCOPE.md §5): the "
            "coordinate is the surveyor's map click in lat/lon, not a pixel in a matched tile."
        ),
    )

    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)
    crs: Literal["EPSG:4326"] = Field(
        default="EPSG:4326", description="★ Always. Present so nobody has to assume."
    )

    elevation_m: float | None = Field(
        default=None,
        ge=-500.0,
        le=9000.0,
        description=(
            "★ Null is HONEST when no elevation provider resolved; 0 would not "
            "be. Bound to elevation_source by ck_gcps_elevation_source_consistent "
            "— **the source may never name a producer that did not run** — and "
            "the job emits an ELEVATION_UNAVAILABLE warning (§4.27)."
        ),
    )
    elevation_source: str | None = Field(
        default=None, description="local_dem | copernicus_dem | srtm | exif | manual | null."
    )

    source: GcpSource = Field(
        description=(
            "★★ SCOPE.md §5: 'The GCP records source = \"manual\" so an automatic "
            "GCP can never be confused with an observed one downstream or in an "
            "export.' `manual` for every GCP in this build."
        )
    )

    confidence: float = Field(
        ge=0.0,
        le=100.0,
        description=(
            "★ 0-100.\n\n"
            "★ WHAT THIS NUMBER MEANS DEPENDS ON `source`:\n"
            "  - source='manual'    -> the numeric representative of "
            "declared_confidence (see SURVEYOR_CONFIDENCE_TO_SCORE). A HUMAN "
            "JUDGEMENT rendered as a number so the DB CHECK, the export column "
            "and the sort order keep working. It is **not measured**, and "
            "declared_confidence is the field to read and to edit.\n"
            "  - source='automatic' -> the pipeline's computed score. DEFERRED "
            "(SCOPE.md §1); no row carries this in this build.\n\n"
            "★ This is 0-100 while AnnotationRead.confidence is 0-1. The two "
            "scales are deliberate and MUST NOT be unified (§6.1)."
        ),
    )
    declared_confidence: SurveyorConfidence | None = Field(
        default=None,
        description=(
            "★★ SCOPE.md §5. The surveyor's declared judgement, 1-5. Non-null IFF "
            "source='manual' — which, in this build, is always. Null when "
            "source='automatic': an algorithm does not have a judgement, it has a "
            "score, and that is `confidence`."
        ),
    )

    horizontal_accuracy_m: float | None = Field(
        default=None,
        description=(
            "★ An ALIAS of accuracy.total_ce90_m: serialised, never stored "
            "(§5.6). Kept because it is in GcpRecord and the CSV; the *column* "
            "was dropped, which is the drift that mattered."
        ),
    )
    accuracy: GcpAccuracy
    residual_px: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "★ ||H·image_px - satellite_px|| for THIS point. A job-level RMSE "
            "hides *the one bad correspondence* in an otherwise good match; this "
            "is how a surveyor finds it.\n\n"
            "★ **Null in manual mode** — there is no H, so there is no residual. "
            "Null is the honest value; 0 would falsely claim a perfect fit. "
            "(ck_gcps_residual_iff_direct_fix and the has_direct_fix column are "
            "what make null distinguishable from 0 in SQL.)"
        ),
    )

    pixel_accuracy_ceiling_px: float = Field(
        default=1.0,
        gt=0.0,
        description=(
            "★ THE landmark pixel-accuracy ceiling (`top = 1 px`). The largest per-point "
            "pixel error the product vouches for; a clean landmark round-trips well under "
            "half of it. Carried on every GCP so a client shows the bar it is judged against."
        ),
    )
    pixel_accuracy_within_ceiling: bool = Field(
        default=True,
        description=(
            "★ Whether this GCP's MEASURED pixel error (`residual_px`) is within "
            "`pixel_accuracy_ceiling_px`. True when there is no residual to judge (manual "
            "mode — the pixel is the surveyor's own observation, not a fit). False only when "
            "a direct/automatic fit's residual exceeds the ceiling — the one point to re-check."
        ),
    )

    manually_adjusted: bool = Field(
        description=(
            "★ A manual ADJUSTMENT is distinct from a manual SOURCE. `source` "
            "says where the coordinate came from; `manually_adjusted` says it was "
            "moved after being placed. A manual GCP starts with "
            "manually_adjusted=false."
        )
    )
    original: GcpOriginal | None = Field(
        default=None, description="Non-null IFF manually_adjusted."
    )
    adjustment_offset_m: float | None = Field(
        default=None,
        ge=0.0,
        description="ST_Distance(original_geom, geom) — geodesic, REAL metres.",
    )
    adjusted_by: str | None = None
    adjusted_at: datetime | None = None
    adjustment_note: str | None = None

    is_included_in_export: bool

    is_stale: bool = Field(
        description=(
            "★ Staleness is a FLAG and never an auto-recompute. A GCP is a "
            "coordinate that may already be in a survey report, a contract, or a "
            "machine-control file. **It changes when a human decides it changes.** "
            "Every path that could invalidate it marks it stale and says so; "
            "nothing recomputes it implicitly."
        )
    )
    stale_reason: GcpStaleReason | None = None

    landmark: GcpLandmarkRef | None = None
    reference_imagery: dict[str, object] | None = Field(
        default=None,
        description=(
            "★ IMAGERY PROVENANCE, recorded at click time or not at all: provider, "
            "cache variant (config fingerprint), zoom, tile address, GSD/accuracy "
            "epistemic statuses (estimated/vendor_certified/unknown), whether the "
            "imagery date is knowable (never fabricated), whether the click was beyond "
            "the provider's native resolution, and whether the tile came from the "
            "local cache. Null = not recorded (pre-existing rows, GeoTIFF path)."
        ),
    )
    created_at: datetime
    updated_at: datetime


class GcpSummary(ApiModel):
    """List projection. ★ Flattens ``accuracy.total_ce90_m`` because that is the
    error-radius **column of the mandated GCP table** — never
    ``relative_ce90_m``.
    """

    id: UUID
    image_id: UUID
    code: str | None
    image_px: PixelXY
    lat: float
    lon: float
    source: GcpSource
    confidence: float = Field(ge=0.0, le=100.0)
    declared_confidence: SurveyorConfidence | None = None
    total_ce90_m: float = Field(ge=0.0)
    manually_adjusted: bool
    is_stale: bool
    is_included_in_export: bool


# ─────────────────────────────────────────────────────────────────────────────
# ★★ SCOPE.md §5 — MANUAL CORRESPONDENCE. The core interaction of this build.
# ─────────────────────────────────────────────────────────────────────────────


class GcpCopyResult(ApiModel):
    """``POST /images/{image_id}/gcps/copy-from/{source_image_id}`` — the control
    points now on the target frame (2026-09-09: a camera that adopts a NEW frame
    with the SAME aim carries its points over instead of re-placing them)."""

    copied: int
    items: list["GcpRead"]


class GcpManualCreate(ApiModel):
    """★★ **ADDED BY SCOPE.md §5** — flagged in IU-17's report. ``POST
    /images/{image_id}/gcps``, proposed **endpoint 65**.

    §6 has no GCP create schema at all, because the contract assumed every GCP
    fell out of a homography. SCOPE.md §1 deferred that engine and §5 replaced it
    with this: *"the surveyor marks a landmark in the photo, clicks the
    corresponding spot on the satellite map, and the geographic coordinate is
    recorded directly."* **That interaction needs a request body, and this is
    it.** Without it the product has no way to create its own deliverable.

    ★ **The commit is atomic and it is the whole pairing.** SCOPE.md §5:
    *"Uncommitted correspondences must never appear in the GCP table or an
    export."* So there is no "create a half-GCP and fill in the other endpoint
    later" — both endpoints and the declared confidence arrive together or
    nothing is written. The open, uncommitted correspondence lives in the
    frontend's Zustand store (L7: browser-only state), never here.

    ★ **``declared_confidence`` is required, not defaulted.** A default would be
    the server inventing the surveyor's judgement — the exact fabrication
    SCOPE.md §5 forbids when it says confidence is *"never a computed number"*.
    Making them choose costs one click and is the only honest option (L12).

    ★ **``image_px`` vs ``landmark_id``.** Exactly one path must establish the
    photo endpoint:
      - ``landmark_id`` — the surveyor picked an existing annotation. The server
        copies that annotation's *representative point* into ``image_px``
        (§5.6: identical to the vertex for points, ``ST_PointOnSurface`` for
        polygons), so a polygon corner can be a GCP.
      - ``image_px`` — a bare click with no annotation. ``gcps.landmark_id`` is
        nullable, so this is representable and the GCP stays self-describing.
    Sending both is a 422: they are two claims about one fact, and if they
    disagree there is no defensible answer to which one wins.
    """

    landmark_id: UUID | None = Field(
        default=None,
        description=(
            "An existing annotation to hang this GCP off. The server derives "
            "image_px from its representative point. Mutually exclusive with "
            "image_px."
        ),
    )
    image_px: PixelXY | None = Field(
        default=None,
        description=(
            "★ ORIGINAL image pixel space — independent of viewer zoom, pan and "
            "brightness/contrast (SCOPE.md §5). Required when landmark_id is "
            "null. Sub-pixel; never round it before sending."
        ),
    )

    lat: float = Field(
        ge=-90.0, le=90.0, description="★ The map click, EPSG:4326. Stored as geography(Point)."
    )
    lon: float = Field(ge=-180.0, le=180.0)

    declared_confidence: SurveyorConfidence = Field(
        description=(
            "★★ SCOPE.md §5: a SURVEYOR-DECLARED 1-5 judgement, NEVER computed. "
            "Required — the server does not get to guess how sure a human is."
        )
    )

    map_zoom: int = Field(
        ge=0,
        le=24,
        description=(
            "★ The satellite map's zoom level AT THE MOMENT OF THE CLICK. "
            "SCOPE.md §5: 'Reported positional accuracy comes from imagery "
            "ground-sample-distance and click precision at the map's zoom level "
            "— a real, defensible number.' This is the second input, and the "
            "client is the only party that knows it. Without it the server would "
            "have to assume a zoom, and an assumed zoom is an invented accuracy."
        ),
    )
    provider: ProviderName | None = Field(
        default=None,
        description=(
            "The basemap the surveyor was actually looking at. Null -> the "
            "project default. It determines georef_ce90_m and gsd_m, so it is "
            "provenance, not preference — a click on Esri and a click on a local "
            "orthophoto are not equally accurate and must not report as if they "
            "were."
        ),
    )
    match_result_id: UUID | None = Field(
        default=None,
        description=(
            "Attach to an existing manual match_results row (one per image per "
            "provider/zoom session). Null -> the service finds or creates one. "
            "Exposed because a batch of clicks in one session should share one "
            "provenance row rather than mint a dozen."
        ),
    )

    code: str | None = Field(
        default=None,
        pattern=GCP_CODE_PATTERN,
        description="'GCP01'. Unique per image -> else 409 GCP_CODE_CONFLICT.",
    )
    name: str | None = Field(
        default=None,
        max_length=200,
        description="Free-text point name (the 'Name' column). Used when there is no landmark "
        "to inherit a name from.",
    )
    is_included_in_export: bool = True
    note: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def _exactly_one_photo_endpoint(self) -> "GcpManualCreate":
        if (self.landmark_id is None) == (self.image_px is None):
            raise ValueError(
                "Send exactly one of landmark_id or image_px. landmark_id derives "
                "the photo endpoint from an existing annotation; image_px states "
                "it directly. Sending both makes two claims about one fact."
            )
        return self


class GcpCorrespondenceUpdate(ApiModel):
    """★★ **ADDED BY SCOPE.md §5** — flagged in IU-17's report.
    ``PUT /gcps/{gcp_id}/correspondence``, proposed **endpoint 66**.
    ``If-Match`` **REQUIRED**.

    SCOPE.md §5: *"The pairing is editable and re-openable: either endpoint can
    be dragged and re-committed."*

    ★ **Why ``PUT`` and why the whole pairing.** A correspondence is a *pair*,
    and committing half of it is exactly how the photo mark and the map mark
    drift apart. This declares the desired state of the pairing and is
    idempotent — the same reason §6.2 gives for ``PUT`` on the annotation
    collection.

    ★ **Why this is not just ``GcpUpdate``.** §6.2 rules that ``image_px`` is
    **not** adjustable via ``PATCH /gcps/{id}``, and the reason is sound and
    survives the scope cut: for a GCP with a ``landmark_id``, moving the point
    *on the photograph* is editing the annotation, and allowing it here would
    silently fork ``gcps.pixel_x`` from ``annotations.pixel_x`` with **no
    revision record**. That rule is kept: ``image_px`` here is accepted **only**
    when ``landmark_id is null`` — the bare-click case, which has no annotation
    to fork from and therefore no record to lose. A landmark-backed GCP still
    re-commits its photo endpoint through ``PATCH /annotations/{id}`` (422 with
    that pointer otherwise).
    """

    image_px: PixelXY | None = Field(
        default=None,
        description=(
            "★ Accepted ONLY when the GCP has no landmark_id -> else 422, "
            "pointing at PATCH /annotations/{id}. See the class docstring."
        ),
    )
    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)
    declared_confidence: SurveyorConfidence = Field(
        description="★ Re-declared with the pairing. The surveyor may revise their judgement."
    )
    map_zoom: int = Field(
        ge=0, le=24, description="★ The zoom of the NEW click — the accuracy is recomputed from it."
    )
    note: str | None = Field(default=None, max_length=4000)


# ─────────────────────────────────────────────────────────────────────────────
# Adjustment (§6.2)
# ─────────────────────────────────────────────────────────────────────────────


class GcpUpdate(PatchModel):
    """``PATCH /gcps/{gcp_id}`` — endpoint 40. ★ ``If-Match`` **REQUIRED**.

    ★ **THE TWO ADJUSTMENT MODES, and the server closes the loop** (§6.2):

    ===========================  ==============================================
    Client sends                 Server does
    ===========================  ==============================================
    ``lat``/``lon`` only         Sets ``geom``. Derives ``satellite_px`` by the
                                 **inverse** chain.
    ``satellite_px`` only        Sets the pixel columns. Derives ``lat``/``lon``
                                 by the **forward** chain.
    **both**                     Forward-projects and compares. Within
                                 ``LE_GCP_CONSISTENCY_TOLERANCE_M`` (0.5 m) ->
                                 accept, ``lat``/``lon`` authoritative. Beyond ->
                                 **422 GCP_ADJUSTMENT_AMBIGUOUS**.
    neither (code/note/flags)    Metadata-only edit. **Does not** set
                                 ``manually_adjusted``. *Renaming a GCP is not
                                 adjusting it.*
    ===========================  ==============================================

    ★ **Why the server derives the other representation instead of storing one.**
    ``satellite_px`` and ``lat``/``lon`` are two views of one fact and the DDL
    stores both. If a PATCH updated only what the client sent, the two would
    diverge — **the map would show the marker in one place and the CSV would
    export another, with no indication which is right.** Deriving is not
    redundant work; it is the invariant.

    ★ **A manual adjustment does NOT set ``confidence = 100``.** Tempting, and
    wrong. Overwriting it destroys the only record of how well the algorithm
    did, makes ``?confidence__gte=70`` meaningless (every adjusted point passes),
    and **asserts a certainty the human never claimed** — a surveyor nudging a
    marker 3 m is *guessing better*, not measuring. Human certainty is carried by
    ``manually_adjusted`` + ``adjustment_offset_m`` + ``adjusted_by`` + the note,
    and — in manual mode — by ``declared_confidence``, which the surveyor may
    revise here because it was theirs to begin with.

    ★ ``image_px`` (1.2.6) — the PHOTO endpoint, movable in the SAME edit for a
    **bare** manual GCP only. It was originally absent ("moving the photo mark is
    editing the annotation") — true for a landmark-backed GCP, whose pixel lives on
    the annotation row, but a bare-click GCP's pixel lives on ``gcps.pixel_x/pixel_y``
    and nowhere else; refusing it left the manual flow's own photo marks immovable
    (field report: "on the image it doesn't move"). Landmark-backed → still a 422
    pointing at ``PATCH /annotations/{id}``.
    """

    lat: float | None = Field(default=None, ge=-90.0, le=90.0)
    lon: float | None = Field(default=None, ge=-180.0, le=180.0)
    satellite_px: PixelXY | None = None
    image_px: PixelXY | None = Field(
        default=None,
        description=(
            "★ Move the photo endpoint of a BARE manual GCP (no linked landmark), in "
            "ORIGINAL image pixel space, alongside lat/lon. 422 for a landmark-backed "
            "GCP (move its annotation instead) or when sent without lat/lon."
        ),
    )
    code: str | None = Field(default=None, pattern=GCP_CODE_PATTERN)
    name: str | None = Field(
        default=None, max_length=200, description="Free-text point name (the 'Name' column)."
    )
    declared_confidence: SurveyorConfidence | None = Field(
        default=None,
        description=(
            "★★ SCOPE.md §5: the surveyor may revise their own declared "
            "judgement. Rejected when source='automatic' (422) — an algorithm's "
            "score is not a judgement to revise."
        ),
    )
    is_included_in_export: bool | None = None
    adjustment_note: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def _lat_lon_together(self) -> "GcpUpdate":
        # ★ §13.1 (IU-17): GcpUpdate rejects `lat` without `lon`.
        #   A half-coordinate is not a partial update, it is a broken one: the
        #   server would have to pair a new latitude with the stored longitude
        #   and write a point the client never asked for — somewhere on a line
        #   between the old position and the intended one, plausible and wrong.
        sent = self.model_fields_set
        if ("lat" in sent) != ("lon" in sent):
            raise ValueError(
                "lat and lon must be sent together: a latitude paired with the "
                "stored longitude is a coordinate nobody chose."
            )
        return self


class GcpResetRequest(ApiModel):
    """``POST /gcps/{gcp_id}/reset`` — endpoint 41. ★ **Idempotent**.

    Restores ``original_geom`` — the answer as first committed — and clears the
    adjustment metadata. ``409 GCP_ORIGINAL_UNAVAILABLE`` when the GCP was never
    adjusted and therefore has no original to return to.
    """

    confirm: bool = Field(description="Must be true. A reset discards the surveyor's adjustment.")

    @model_validator(mode="after")
    def _require_confirm(self) -> "GcpResetRequest":
        if not self.confirm:
            raise ValueError("confirm must be true: a reset discards the current adjustment.")
        return self


class GcpRecomputeRequest(ApiModel):
    """``POST /images/{image_id}/gcps/recompute`` — endpoint 42.

    ★★ **DEFERRED** (SCOPE.md §4): **both** modes need the deferred engine —
    ``rederive`` runs the full pipeline and ``refit`` re-fits a homography, and
    *"RANSAC homography estimation"* is an ABC only. The endpoint is registered
    and documented and returns ``501`` + ``feature: "deferred"``. The request
    type is complete so the seam is real and re-enabling costs no caller a change
    (SCOPE.md §7).

    ★ **``dry_run`` is not a nicety.** "Recompute" moves coordinates the surveyor
    may have already reported; they get to see how far, and for which points,
    **before** committing. ``dry_run=true`` -> synchronous ``200
    GcpRecomputeDryRun``; otherwise ``202 JobRead``.
    """

    match_result_id: UUID | None = None
    mode: Literal["refit", "rederive"] = "refit"
    anchor_weight: float = Field(
        default=10.0,
        ge=1.0,
        le=1000.0,
        description="How hard manually-adjusted GCPs pull the refit toward themselves.",
    )
    preserve_adjusted: bool = True
    estimator: EstimatorName | None = None
    dry_run: bool = False


class GcpRecomputeDelta(ApiModel):
    """How far one point would move. ★ In **real ground metres**."""

    gcp_id: UUID
    code: str | None
    offset_m: float = Field(ge=0.0)
    lat_before: float
    lon_before: float
    lat_after: float
    lon_after: float
    confidence_before: float = Field(ge=0.0, le=100.0)
    confidence_after: float = Field(ge=0.0, le=100.0)


class GcpRecomputeFitStats(ApiModel):
    """The refit's quality."""

    inlier_count: int
    inlier_ratio: float = Field(ge=0.0, le=1.0)
    rmse_px: float = Field(ge=0.0)
    anchor_count: int


class GcpRecomputeDryRun(ApiModel):
    """``200`` from endpoint 42 when ``dry_run=true``."""

    deltas: list[GcpRecomputeDelta]
    fit: GcpRecomputeFitStats
    max_offset_m: float = Field(ge=0.0)
    mean_offset_m: float = Field(ge=0.0)
    affected_count: int


class GcpOverview(ApiModel):
    """★ **CROSS-PROJECT** list projection — ``GET /gcps``. Powers the dashboard map.

    Until this existed there was no way to see a GCP outside the image that owns it:
    every read was ``/images/{id}/gcps``. A surveyor with forty photographs across six
    projects could not answer *"where are all my control points?"* without forty
    requests.

    ★ **Every name on this row is resolved in the REPOSITORY, by a join.** ``project_name``,
    ``image_filename`` and ``landmark_name`` come from one statement — not from
    ``gcp.image.project.name``, which every relationship on every model makes impossible
    on purpose (``lazy="raise"``). This endpoint may return thousands of points for one
    map render; an N+1 here is thousands of round trips per pan.

    ★ **Flat and thin, deliberately.** No ``accuracy`` object, no ``original``, no
    ``landmark`` sub-object — a map marker needs a position, an identity and a quality
    hint. ``GcpRead`` remains the full record, one fetch away by ``id``.
    """

    id: UUID
    project_id: UUID
    project_name: str
    image_id: UUID
    image_filename: str
    code: str | None = Field(default=None, description="'GCP01'. Null when unnamed.")
    landmark_name: str | None = Field(
        default=None,
        description=(
            "The linked annotation's ``label``. ★ Null is HONEST and common: a GCP may "
            "be a bare map click with no annotation at all, the annotation may be "
            "unlabelled, or it may have been tidied away (``landmark_id`` is ON DELETE "
            "SET NULL — the exported coordinate survives its landmark)."
        ),
    )
    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)
    confidence: float = Field(
        ge=0.0,
        le=100.0,
        description="0-100. ★ In this build always a surveyor judgement — see GcpRead.confidence.",
    )
    source: GcpSource = Field(
        description="★ 'manual' = observed, 'automatic' = inferred. Never confusable (SCOPE.md §5)."
    )
    total_ce90_m: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "★ THE headline error radius, real ground metres. Declared nullable so the "
            "wire never has to invent a number for a row that lacks one."
        ),
    )


class GcpOverviewListParams(ListParams):
    """``GET /gcps`` — the cross-project list. Newest first by default.

    ★ Every filter here narrows the map, and each one is a different question the
    dashboard asks: one project, one photograph, one album's worth of projects, "only
    the points I trust", or "only what is on screen".
    """

    project_id: UUID | None = None
    image_id: UUID | None = None
    album_id: UUID | None = Field(
        default=None, description="Every GCP in every project of this album."
    )
    min_confidence: float | None = Field(default=None, ge=0.0, le=100.0)
    bbox: str | None = Field(
        default=None,
        description=(
            '"minlon,minlat,maxlon,maxlat" — EPSG:4326. Antimeridian-crossing -> 422 '
            "BBOX_CROSSES_ANTIMERIDIAN."
        ),
    )


class GcpListParams(ListParams):
    """``GET /images/{image_id}/gcps`` (38) · ``GET /match-results/{id}/gcps`` (64).

    ★ ``format=geojson`` returns a :class:`~app.schemas.common.
    GeoJsonFeatureCollection`; ``format=json`` returns ``Page[GcpRead]``.
    """

    format: Literal["json", "geojson"] = "json"
    match_result_id: UUID | None = None
    source: GcpSource | None = Field(
        default=None,
        description=(
            "★★ SCOPE.md §5. The filter that keeps an observed coordinate from "
            "being confused with an inferred one in an export."
        ),
    )
    confidence__gte: float | None = Field(default=None, ge=0.0, le=100.0)
    confidence__lte: float | None = Field(default=None, ge=0.0, le=100.0)
    manually_adjusted: bool | None = None
    is_stale: bool | None = None
    is_included_in_export: bool | None = None
    q: str | None = Field(default=None, description="Free-text over code + landmark label.")
