"""KML/KMZ placemark import — the wire contract for ``/projects/{id}/gcps/import/kml``.

★ **PREVIEW THEN APPLY, always two calls.** An import moves coordinates in the
deliverable, and the surveyor has to see *what* moves and *how far* before it happens.
The preview is a pure read: it parses the upload, matches placemarks against existing
GCPs, and reports the deltas without writing anything. The apply call re-parses the same
file and commits. Nothing is stored between the two — see :class:`KmlImportApplyRequest`
for why that is deliberate rather than lazy.

★ **THE PREVIEW NEVER HIDES A ROW.** Every placemark in the file lands in exactly one of
``matched`` or ``unmatched``, and every GCP that the file did not mention lands in
``untouched_gcp_count``. A surveyor who exported 30 points and gets 28 back must be able
to see which two went missing and why; an import UI that silently drops rows has changed
the deliverable without telling anyone.

★ **WHAT THE SERVER WILL NOT ASSERT ABOUT AN IMPORTED COORDINATE.** The file came from
somewhere this system cannot see. It does not know which program wrote it, which imagery
that program displayed, or how carefully the operator placed the marker — so it does not
compute a new horizontal accuracy from provider GSD (the existing CE90 belongs to the
original observation and is left alone), and it records an imported altitude with a NULL
vertical error bar. What it *can* state precisely is how far each point moved, which is
why ``offset_m`` is the number the preview leads with.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import ConfigDict, Field

from app.schemas.common import ApiModel

__all__ = [
    "KmlImportApplyRequest",
    "KmlImportApplyResponse",
    "KmlImportMatch",
    "KmlImportPreview",
    "KmlImportSkipped",
    "KmlImportUnmatched",
    "MATCH_STRATEGIES",
]

#: How a placemark was tied to an existing GCP, most trustworthy first.
#:
#: ``gcp_id`` is an exact round trip: the file carries the very id we exported, so the
#: match is a fact rather than a guess. ``code`` and ``name`` are the operator's own
#: labels and are matched only when they are **unambiguous within the project** — a
#: duplicate label produces an unmatched row with the reason, never an arbitrary pick.
MATCH_STRATEGIES = ("gcp_id", "code", "name")


class KmlImportMatch(ApiModel):
    """One placemark that resolved to an existing GCP, with the movement it implies."""

    model_config = ConfigDict(extra="forbid")

    gcp_id: UUID = Field(description="The GCP this placemark will adjust.")
    placemark_name: str | None = Field(
        default=None, description="The `<name>` from the file, for identification."
    )
    code: str | None = Field(default=None, description="The GCP's code, e.g. `GCP01`.")
    matched_by: str = Field(
        description="Which strategy tied them together: `gcp_id`, `code`, or `name`."
    )

    current_lat: float = Field(description="Where the GCP is now, EPSG:4326.")
    current_lon: float
    new_lat: float = Field(description="Where the file says it should be, EPSG:4326.")
    new_lon: float

    offset_m: float = Field(
        ge=0.0,
        description=(
            "Ground distance from the current position to the new one, TRUE metres "
            "(PostGIS `ST_Distance` on geography). **The number to read first.**"
        ),
    )
    current_total_ce90_m: float | None = Field(
        default=None,
        description="The GCP's existing horizontal CE90, for comparison with `offset_m`.",
    )
    exceeds_accuracy: bool = Field(
        description=(
            "True when `offset_m` is larger than the GCP's own CE90 — the move is bigger "
            "than the error bar that justified the original position. ★ NOT an error and "
            "not blocked: refining a point beyond its stated accuracy is a legitimate "
            "reason to import. It is flagged so the operator confirms it deliberately."
        )
    )

    current_elevation_m: float | None = Field(
        default=None, description="Current Z, or null when the project has no DEM."
    )
    new_elevation_m: float | None = Field(
        default=None,
        description=(
            "Z carried by the placemark, or null when the file gave none. ★ A 2-ordinate "
            "`<coordinates>` yields null, never 0 — absent altitude and sea level are "
            "different claims."
        ),
    )
    elevation_note: str | None = Field(
        default=None,
        description=(
            "Why an altitude present in the file will not be applied — e.g. a "
            "`clampToGround` altitudeMode, under which the value is display decoration "
            "rather than an asserted height."
        ),
    )


class KmlImportUnmatched(ApiModel):
    """A placemark that parsed cleanly but ties to no GCP in this project.

    ★ **Never becomes a new GCP, and the reason is structural.** ``gcps.pixel_x`` and
    ``pixel_y`` are ``NOT NULL``: a GCP is a *pairing* between an image pixel and a ground
    coordinate, and a placemark carries only the ground half. Inventing pixel coordinates
    to satisfy the column would fabricate the very observation the record exists to
    attest. To add a point, pair it in the workspace against the photo it belongs to.
    """

    model_config = ConfigDict(extra="forbid")

    placemark_name: str | None = None
    lat: float
    lon: float
    elevation_m: float | None = None
    reason: str = Field(description="Why it matched nothing, in the operator's terms.")


class KmlImportSkipped(ApiModel):
    """A placemark the reader could not turn into a point at all."""

    model_config = ConfigDict(extra="forbid")

    placemark_name: str | None = None
    reason: str = Field(description="Parse-level cause, verbatim from the reader.")


class KmlImportPreview(ApiModel):
    """``POST …/import/kml/preview`` — what an apply would do. **Writes nothing.**"""

    model_config = ConfigDict(extra="forbid")

    filename: str | None = Field(default=None, description="The uploaded file's name.")
    document_name: str | None = Field(
        default=None,
        description="The KML `<Document><name>`, echoed so the operator can confirm the file.",
    )

    matched: list[KmlImportMatch] = Field(
        default_factory=list, description="Placemarks that will adjust a GCP."
    )
    unmatched: list[KmlImportUnmatched] = Field(
        default_factory=list, description="Placemarks tied to no GCP. Never auto-created."
    )
    skipped: list[KmlImportSkipped] = Field(
        default_factory=list, description="Placemarks that did not parse as points."
    )

    untouched_gcp_count: int = Field(
        ge=0,
        description=(
            "GCPs in this project that the file did not mention. They are left exactly as "
            "they are — an import is a patch, never a replace."
        ),
    )
    moved_count: int = Field(
        ge=0,
        description=(
            "Matches whose `offset_m` is above the no-op threshold. The rest resolved to "
            "the same position and will not be written, so a re-import is a no-op."
        ),
    )
    exceeds_accuracy_count: int = Field(
        ge=0, description="Matches whose movement exceeds the GCP's own CE90."
    )


class KmlImportApplyRequest(ApiModel):
    """The confirm half of the two-step. Sent as form fields beside the same file.

    ★ **The file is uploaded again rather than cached server-side between the calls.**
    A cached preview would need a handle, a TTL, and a store, and it would introduce a
    window in which the thing being applied is not the thing the operator looked at. Re-
    reading the bytes makes the apply self-contained; ``expected_match_count`` is what
    closes the loop, so a file that changed under the operator is refused rather than
    quietly applied.
    """

    model_config = ConfigDict(extra="forbid")

    expected_match_count: int | None = Field(
        default=None,
        ge=0,
        description=(
            "The `matched` length the operator confirmed. When it disagrees with what "
            "this call parses, the import is refused with 409 — the file is not the one "
            "that was previewed. Omit to skip the check."
        ),
    )
    apply_elevation: bool = Field(
        default=True,
        description=(
            "Write altitudes carried by the file. Recorded as `elevation_source='manual'` "
            "with a **NULL** `elevation_ce90_m`: the operator asserted the height and this "
            "system cannot say how wrong it is. Set false to move points horizontally and "
            "leave Z to the project's DEM."
        ),
    )
    note: str | None = Field(
        default=None,
        max_length=500,
        description=(
            "Stored on every adjusted GCP as its `adjustment_note`. Defaults to naming "
            "the source file, so the provenance of the move survives in the record."
        ),
    )


class KmlImportApplyResponse(ApiModel):
    """``POST …/import/kml/apply`` — what actually changed."""

    model_config = ConfigDict(extra="forbid")

    adjusted_gcp_ids: list[UUID] = Field(
        default_factory=list, description="GCPs whose position was written."
    )
    elevation_written_count: int = Field(
        ge=0, description="How many of those also had an altitude written from the file."
    )
    unchanged_count: int = Field(
        ge=0,
        description=(
            "Matches that resolved to the same position and were not written. A second "
            "apply of the same file reports everything here and adjusts nothing."
        ),
    )
    unmatched_count: int = Field(ge=0, description="Placemarks that tied to no GCP.")
    skipped_count: int = Field(ge=0, description="Placemarks that did not parse as points.")
