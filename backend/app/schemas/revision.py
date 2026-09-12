"""Revisions and annotation version history (§6.2) — endpoints 23–29.

★ **This module imports ``annotation.py``** for ``AnnotationRead`` — see the DAG
note in ``schemas/__init__.py``. The edge points ``revision → annotation`` and
never back: ``annotation.py`` reads :class:`~app.schemas.common.RevisionSummary`
from ``common``, which is exactly why §6.2 moved it there.

★ ``RevisionSummary`` itself lives in ``common`` and is re-exported here so
``from app.schemas.revision import RevisionSummary`` reads naturally at the
endpoints that return it. It is a re-export, not a second declaration.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, model_validator

from .annotation import AnnotationRead
from .common import ApiModel, GeoJsonGeometry, ListParams, RevisionSummary, WarningItem
from .enums import AnnotationOp

__all__ = [
    "ANNOTATION_VERSION_SORT_FIELDS",
    "MAX_REPLAY_EVENTS",
    "REVISION_SORT_FIELDS",
    "AnnotationVersionChangeSummary",
    "AnnotationVersionListParams",
    "AnnotationVersionRead",
    "AnnotationVersionSummary",
    "RevisionCreate",
    "RevisionDiffSummary",
    "RevisionListParams",
    "RevisionRead",
    "RevisionRestoreRequest",
    "RevisionRestoreResponse",
    "RevisionSnapshot",
    "RevisionSummary",
]

REVISION_SORT_FIELDS = frozenset({"seq", "created_at"})
ANNOTATION_VERSION_SORT_FIELDS = frozenset({"id", "created_at", "version_no"})

#: ``LE_MAX_REPLAY_EVENTS``. Beyond this a replay is refused with
#: ``422 REVISION_REPLAY_TOO_EXPENSIVE`` and ``details.nearest_checkpoint_seq``.
#: *A history endpoint that can spin for 40 s is a DoS on your own database.*
MAX_REPLAY_EVENTS = 5000


class RevisionCreate(ApiModel):
    """``POST /projects/{project_id}/revisions`` — endpoint 24."""

    label: str | None = Field(default=None, max_length=200)
    is_checkpoint: bool = Field(
        default=False,
        description=(
            "A checkpoint stores a full snapshot, so replays start from here "
            "rather than from the beginning of the log."
        ),
    )


class RevisionSnapshot(ApiModel):
    """The materialised annotation set at a revision."""

    annotations: list[AnnotationRead]
    seq: int


class RevisionDiffSummary(ApiModel):
    """What this revision changed."""

    created: int
    updated: int
    deleted: int
    restored: int


class RevisionRead(ApiModel):
    """``RevisionRead`` — endpoints 24, 25.

    ★ Deliberately does NOT inherit :class:`RevisionSummary`, even though it is
    a superset of it. Pydantic would emit ``RevisionRead`` as a standalone
    component either way, but inheritance would make ``response_model=
    RevisionSummary`` silently accept a ``RevisionRead`` and serialise the fat
    fields away — which is the behaviour you want right up until the list
    endpoint starts replaying snapshots for fifty rows. Two flat models, one
    obvious cost each. (IU-23's TS mirrors this with ``extends``, which is
    structural and carries no such runtime hazard.)
    """

    id: UUID
    project_id: UUID
    seq: int
    label: str | None
    is_checkpoint: bool
    annotation_count: int
    created_at: datetime
    snapshot: RevisionSnapshot | None
    snapshot_source: Literal["stored", "replayed"] = Field(
        description=(
            "★ Tells the truth about cost: 'stored' = read straight from "
            "project_revisions.snapshot; 'replayed' = materialised from the "
            "nearest preceding checkpoint."
        )
    )
    events: list["AnnotationVersionSummary"]
    diff_summary: RevisionDiffSummary
    restorable: bool


class RevisionListParams(ListParams):
    """``GET /projects/{project_id}/revisions`` — endpoint 23."""

    is_checkpoint: bool | None = None
    seq__gte: int | None = None
    seq__lte: int | None = None


class RevisionRestoreRequest(ApiModel):
    """``POST /revisions/{revision_id}/restore`` — endpoint 26.

    ★ **Restore is forward-only.** It computes the delta from current state to
    the target and applies it as a **new** revision, emitting normal events — so
    a restore is itself undoable. Rewinding ``current_revision_seq`` (the obvious
    alternative) would orphan every event above it and make the log lie. *An
    append-only log that gets rewound is not an audit log.*

    ★ **Restore never touches GCPs**, only annotations. It warns
    ``GCPS_NOW_STALE`` and leaves them — a GCP changes when a human decides it
    changes.
    """

    confirm: bool = Field(description="Must be true. A restore rewrites the canvas.")
    label: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _require_confirm(self) -> "RevisionRestoreRequest":
        if not self.confirm:
            raise ValueError(
                "confirm must be true: a restore rewrites the live annotation set."
            )
        return self


class RevisionRestoreResponse(ApiModel):
    """Endpoint 26's body."""

    revision: RevisionSummary
    annotations: list[AnnotationRead]
    warnings: list[WarningItem] = Field(
        default_factory=list, description="Carries GCPS_NOW_STALE when GCPs were affected."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Annotation version history — endpoints 27–29
# ─────────────────────────────────────────────────────────────────────────────


class AnnotationVersionChangeSummary(ApiModel):
    """A cheap, renderable description of one event.

    Exists so the undo-stack list does not have to diff ``before``/``after``
    client-side for every row it paints.
    """

    fields_changed: list[str]
    vertex_delta: int | None
    moved_px: float | None


class AnnotationVersionSummary(ApiModel):
    """One append-only event.

    ★ ``id`` is a JSON **number**, not a UUID string. ``annotation_versions.id``
    is ``BIGSERIAL`` — **the one resource-id asymmetry in the API** (§6.1),
    called out in every schema that touches it. It is append-only, high-row-count
    and never referenced by URL, so BIGSERIAL keeps the index tight and the
    inserts sequential.
    """

    id: int
    annotation_id: UUID
    image_id: UUID
    revision_id: UUID | None
    op: AnnotationOp
    version_no: int
    actor_id: str | None
    client_op_id: str | None
    created_at: datetime
    summary: AnnotationVersionChangeSummary
    before: dict[str, Any] | None = Field(
        default=None, description="Null unless include_payloads=true."
    )
    after: dict[str, Any] | None = Field(
        default=None, description="Null unless include_payloads=true."
    )


class AnnotationVersionRead(ApiModel):
    """``GET /annotation-versions/{version_id}`` — endpoint 29. Always includes
    ``before``/``after`` in full.

    ★ Per the DDL CHECK: **``before`` is null iff ``op='create'``; ``after`` is
    null iff ``op='delete'``.** The invariant is stated here and in the OpenAPI
    description so client code can rely on it rather than defensively coding both
    branches for every op.
    """

    id: int
    annotation_id: UUID
    image_id: UUID
    revision_id: UUID | None
    op: AnnotationOp
    version_no: int
    actor_id: str | None
    client_op_id: str | None
    created_at: datetime
    summary: AnnotationVersionChangeSummary
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    diff: list[dict[str, Any]] = Field(description="RFC 6902 JSON Patch.")
    pixel_geom_after: GeoJsonGeometry | None = Field(
        default=None,
        description=(
            "★ IMAGE PIXELS, [x, y], y-down, SRID 0 — the same GeoJSON-shaped-"
            "but-not-geographic form as AnnotationRead.geometry."
        ),
    )


class AnnotationVersionListParams(ListParams):
    """``GET /images/{image_id}/annotation-versions`` (27) ·
    ``GET /annotations/{annotation_id}/versions`` (28).

    ★ **THE ONE keyset exception** to offset pagination (§6.2). ``before_id``
    switches endpoint 27 to keyset mode for the undo stack's infinite scroll,
    where ``offset`` would skip events as new ones land — the classic
    append-heavy-collection paging bug, and the one collection here that is
    genuinely append-heavy.

    ★ ``offset`` + ``before_id`` together -> **422 PARAM_CONFLICT**. Not
    "``before_id`` wins": two paging modes in one request means the client
    believes something about the result that is false, and picking one silently
    is how that belief survives to production.
    """

    annotation_id: UUID | None = None
    op: str | None = Field(default=None, description="CSV of AnnotationOp.")
    include_payloads: bool = False
    before_id: int | None = Field(
        default=None, description="Keyset cursor: return events with id < this."
    )

    @model_validator(mode="after")
    def _offset_xor_before_id(self) -> "AnnotationVersionListParams":
        # `offset` has a default of 0, so "was it sent?" is the only honest test —
        # `offset=0` explicitly sent alongside before_id is still a conflict.
        if self.before_id is not None and "offset" in self.model_fields_set:
            raise ValueError(
                "offset and before_id are two different paging modes; send one. "
                "(Use before_id for the undo stack, offset for everything else.)"
            )
        return self
