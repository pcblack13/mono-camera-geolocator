"""Landmark suggestions (§6.2) — endpoints 43–45.

★★ **DEFERRED** (SCOPE.md §4): *"Automatic landmark suggestions"* is an ABC only.
``POST /images/{image_id}/suggest-landmarks`` is **registered and documented** and
returns ``501`` + ``feature: "deferred"``. The ``landmark_suggestions`` table IS
created exactly as specified (rule 5) — it simply holds no rows, so endpoint 44
returns an empty ``Page`` and endpoint 45 has nothing to accept.

★ **Why suggestions are a separate resource** (ADR-014, and it survives the cut):
writing machine guesses straight into ``annotations`` would put unreviewed output
into the surveyor's revision history, their undo stack, and — via
``is_gcp_candidate`` — the GCP deriver. **A suggestion is a proposal; an
annotation is an assertion by a human.** The boundary between them is
``POST …/accept``, and it is the only door.

★ Endpoint 45 returns ``annotation.AnnotationBulkUpsertResponse`` — accepting a
suggestion IS an annotation write, and it must produce the same revision event
any other write does. This module does not import ``annotation``; the router
names that response model directly, which keeps the edge out of the schema DAG.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import Field

from .common import ApiModel, GeoJsonGeometry, ListParams
from .enums import (
    AnnotationGeomType,
    AnnotationKind,
    FeatureDetectorName,
    SuggestionStatus,
    SuggestionStrategy,
)

__all__ = [
    "SUGGESTION_SORT_FIELDS",
    "LandmarkSuggestionRead",
    "SuggestLandmarksRequest",
    "SuggestionAcceptRequest",
    "SuggestionAcceptedRef",
    "SuggestionListParams",
    "SuggestionRejectRequest",
    "SuggestionRejectResponse",
]

SUGGESTION_SORT_FIELDS = frozenset({"rank", "score", "created_at", "kind"})


class SuggestLandmarksRequest(ApiModel):
    """``POST /images/{image_id}/suggest-landmarks`` — endpoint 43.

    ★★ **DEFERRED** — returns ``501``.
    """

    strategy: SuggestionStrategy = SuggestionStrategy.HYBRID
    max_suggestions: int = Field(default=25, ge=1, le=200)
    min_score: float = Field(default=0.3, ge=0.0, le=1.0)
    kinds: list[AnnotationKind] | None = Field(
        default=None, description="Restrict to these kinds. Null -> the strategy decides."
    )


class LandmarkSuggestionRead(ApiModel):
    """One proposal. ★ No row carries this in this build."""

    id: UUID
    image_id: UUID
    aux_job_id: UUID | None = Field(default=None, description="Which suggest job produced it.")
    kind: AnnotationKind
    geom_type: AnnotationGeomType
    pixel_x: float
    pixel_y: float
    pixel_geom: GeoJsonGeometry = Field(
        description=(
            "★ IMAGE PIXELS, [x, y], y-down, SRID 0 — the same GeoJSON-shaped-"
            "but-not-geographic form as AnnotationRead.geometry. Not degrees."
        )
    )
    score: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "★ 0-1, the DETECTOR'S own score — a third scale, and deliberately "
            "neither the 0-1 human `AnnotationRead.confidence` nor the 0-100 "
            "`GcpRead.confidence`. A machine's belief about a pixel patch is not "
            "a surveyor's certainty and is never compared to one."
        ),
    )
    rank: int = Field(ge=1, description="1 = best.")
    detector: FeatureDetectorName
    model_version: str | None
    rationale: str | None = Field(
        default=None,
        description=(
            "★ Human-readable 'why'. A proposal a surveyor cannot interrogate is "
            "noise — they have to be able to disagree with it for the review step "
            "to mean anything."
        ),
    )
    status: SuggestionStatus
    accepted_annotation_id: UUID | None = Field(default=None, description="Set on accept.")
    decided_by: str | None
    decided_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SuggestionAcceptedRef(ApiModel):
    """One proposal -> the annotation it became."""

    suggestion_id: UUID
    annotation_id: UUID
    client_ref: str | None = None


class SuggestionAcceptRequest(ApiModel):
    """``POST /images/{image_id}/landmark-suggestions/accept`` — endpoint 45.

    Returns ``AnnotationBulkUpsertResponse``. ★ **The only door** from proposal
    to assertion.
    """

    suggestion_ids: Annotated[list[UUID], Field(min_length=1, max_length=500)]
    kind: AnnotationKind | None = Field(
        default=None, description="Override the proposed kind at accept time."
    )
    label_prefix: str | None = Field(default=None, max_length=64)
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description=(
            "★ The SURVEYOR'S own certainty, 0-1 — NOT the detector's `score`. "
            "Accepting a proposal is making it your own assertion, and the "
            "confidence recorded is yours."
        ),
    )


class SuggestionRejectRequest(ApiModel):
    """``POST …/landmark-suggestions/reject``.

    ★ Rejection is recorded rather than deleted: ``decided_by``/``decided_at``
    plus the reason are the training signal a future engine is evaluated against,
    and SCOPE.md §2 names exactly that dataset as the reason for building manual
    mode first.
    """

    suggestion_ids: Annotated[list[UUID], Field(min_length=1, max_length=500)]
    reason: str | None = Field(default=None, max_length=1000)


class SuggestionRejectResponse(ApiModel):
    """The reject acknowledgement."""

    rejected_ids: list[UUID]
    count: int


class SuggestionListParams(ListParams):
    """``GET /images/{image_id}/landmark-suggestions`` — endpoint 44.

    ★ Returns an empty ``Page`` in this build, **not a 501**: the collection
    genuinely exists and is genuinely empty, and 501 would be a lie about a read
    that succeeded. Only the *producer* (endpoint 43) is deferred.
    """

    status: str | None = Field(default=None, description="CSV of SuggestionStatus.")
    kind: str | None = Field(default=None, description="CSV of AnnotationKind.")
    score__gte: float | None = Field(default=None, ge=0.0, le=1.0)
    detector: FeatureDetectorName | None = None
