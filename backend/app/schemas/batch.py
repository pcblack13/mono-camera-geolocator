"""Batch processing (§6.2) — endpoints 54–57.

★ **SCOPE.md §3: batch upload / metadata / export are BUILT. Batch MATCHING is
not** — *"batch upload/metadata/export only; no batch matching"*.

A batch fans out to child jobs. When those children would be ``match`` jobs, the
batch returns ``501`` + ``feature: "deferred"`` **at creation**, rather than
fanning out into forty jobs that would each 501 on their own. Refusing up front
is the honest half (L12): a batch that reports "40 failed" tells the surveyor
their photos are bad. They are not; the feature is not built.

★ **This module imports ``matching.py``** for ``SearchHint`` and ``MatchOptions``
— a batch's parameters *are* a match request's parameters, and duplicating them
here would be two sources of truth for one set of defaults. The edge is
``batch → matching``, never back. See the DAG in ``schemas/__init__.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import Field

from .common import ApiModel, ListParams, WarningItem
from .enums import BatchOnError, JobStatus, ProviderName
from .matching import MatchOptions, SearchHint

__all__ = [
    "BATCH_SORT_FIELDS",
    "MAX_BATCH_ITEMS",
    "BatchCounts",
    "BatchCreate",
    "BatchImageFilter",
    "BatchItemRead",
    "BatchListParams",
    "BatchRead",
    "BatchRollup",
    "BatchSummary",
    "BatchUploadForm",
]

BATCH_SORT_FIELDS = frozenset({"created_at", "finished_at", "status"})

#: ``LE_MAX_BATCH_FILES``.
MAX_BATCH_ITEMS = 100


class BatchImageFilter(ApiModel):
    """Select images declaratively instead of by id list.

    ★ Exists so "match every GeoTIFF in this project" survives a new upload: an
    id list is a snapshot, a filter is an intent.
    """

    status: list[str] | None = None
    is_geotiff: bool | None = None
    has_gps: bool | None = None
    tags: list[str] | None = None


class BatchCreate(ApiModel):
    """``POST /batch`` — endpoint 54, JSON branch.

    ★★ **DEFERRED when it fans out to ``match``** (SCOPE.md §3/§4) — returns
    ``501`` + ``feature: "deferred"`` at creation.
    """

    project_id: UUID
    name: str | None = Field(default=None, max_length=200)
    image_ids: list[UUID] | None = Field(
        default=None, description="Null/empty => every ready image in the project."
    )
    filter: BatchImageFilter | None = None
    provider: ProviderName | None = Field(default=None, description="Null -> the project default.")
    search_hint: SearchHint = Field(default_factory=SearchHint)
    options: MatchOptions = Field(default_factory=MatchOptions)
    concurrency: int = Field(
        default=4,
        ge=1,
        le=64,
        description=(
            "★ Bounded because the children share ONE per-provider rate-limit "
            "bucket: raising this does not buy throughput past the provider's "
            "budget, it only buys 429s."
        ),
    )
    on_error: BatchOnError = BatchOnError.CONTINUE


class BatchUploadForm(ApiModel):
    """``POST /batch`` — endpoint 54, **multipart** branch: upload N images and
    batch them in one call.

    ★ As with ``ImageUploadForm``, the file parts are ``list[UploadFile]`` on the
    route signature and are **streamed**, not modelled here.
    """

    project_id: UUID
    name: str | None = Field(default=None, max_length=200)
    provider: ProviderName | None = None
    concurrency: int = Field(default=4, ge=1, le=64)
    on_error: BatchOnError = BatchOnError.CONTINUE


class BatchCounts(ApiModel):
    """Child-job tallies. ``total == pending + running + succeeded + failed +
    cancelled``.
    """

    total: int = Field(ge=0)
    pending: int = Field(ge=0)
    running: int = Field(ge=0)
    succeeded: int = Field(ge=0)
    failed: int = Field(ge=0)
    cancelled: int = Field(ge=0)


class BatchRollup(ApiModel):
    """Aggregate outcome across the batch's children.

    ★ ``images_without_results`` is reported alongside ``images_with_results``
    rather than left to be inferred: "no match found" is a *successful* job
    (§11.6), so a batch can be 40/40 succeeded with 12 images located. Those are
    two different numbers and a surveyor needs both.
    """

    gcp_count: int = Field(ge=0)
    mean_confidence: float | None = Field(default=None, ge=0.0, le=100.0)
    images_with_results: int = Field(ge=0)
    images_without_results: int = Field(ge=0)


class BatchItemRead(ApiModel):
    """One child."""

    id: UUID
    batch_job_id: UUID
    image_id: UUID
    match_job_id: UUID | None = Field(default=None, description="Null until submitted.")
    ordinal: int
    status: JobStatus
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class BatchRead(ApiModel):
    """``BatchRead`` — endpoints 54, 56, 57."""

    id: UUID
    project_id: UUID
    name: str | None
    status: JobStatus
    cancel_requested: bool
    counts: BatchCounts
    progress: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "★ **0-1 here** — the batch_jobs.progress column — NOT the 0-100 "
            "JobProgress.percent. Two scales, and the field name is all that "
            "distinguishes them, so it is stated on both."
        ),
    )
    rollup: BatchRollup | None = Field(default=None, description="Null until finished.")
    provider: ProviderName
    params: dict[str, Any] = Field(
        default_factory=dict, description="The frozen MatchRequest the children were built from."
    )
    concurrency: int
    continue_on_error: bool
    items: list[BatchItemRead] = Field(default_factory=list)
    warnings: list[WarningItem] = Field(default_factory=list)
    error_message: str | None
    requested_by: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class BatchSummary(ApiModel):
    """List projection — endpoint 55. Omits ``items``, which is the payload."""

    id: UUID
    project_id: UUID
    name: str | None
    status: JobStatus
    counts: BatchCounts
    progress: float = Field(ge=0.0, le=1.0)
    created_at: datetime
    finished_at: datetime | None


class BatchListParams(ListParams):
    """``GET /batch`` — endpoint 55."""

    project_id: UUID | None = None
    status: str | None = Field(default=None, description="CSV of JobStatus.")


#: Re-exported so IU-21 can bound the multipart part count without importing
#: ``matching``.
BatchItemIds = Annotated[list[UUID], Field(max_length=MAX_BATCH_ITEMS)]
