"""``match_jobs`` · ``aux_jobs`` · ``batch_jobs`` · ``batch_job_items`` (CONTRACT.md §5.6).

★ SCOPE.md §4 rule 5: **the schema is not cut.** ``match_jobs`` is created exactly as
specified even though this build — a manual GCP surveying tool — writes no rows to it.
Schema churn later costs far more than an unused table now, and the automatic engine is
deferred, not cancelled.

★ The ``match_jobs`` ↔ ``batch_job_items`` FK cycle is deliberate: the batch progress
view scans items and needs the job (one index hit); a worker holding a ``match_job``
needs to report up to its item without a scan. **Both sides are ``ON DELETE SET NULL``,
so neither can create a cascade cycle.** Migration ``0005`` creates both tables without
the mutual FKs and adds them with ``op.create_foreign_key()`` at the end.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from geoalchemy2 import Geography
from geoalchemy2.elements import WKBElement
from sqlalchemy import (
    DDL,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    event,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import (
    FeatureExtractor,
    FeatureMatcher,
    ImageryProvider,
    JobStatus,
    JobType,
    RobustEstimator,
    pg_enum,
)
from app.models.mixins import TimestampMixin, UUIDPkMixin

if TYPE_CHECKING:
    from app.models.heatmap import ConfidenceHeatmap
    from app.models.image import Image
    from app.models.match import MatchResult
    from app.models.project import Project
    from app.models.suggestion import LandmarkSuggestion

__all__ = ["AuxJob", "BatchJob", "BatchJobItem", "MatchJob"]

#: §5.6 — the default score weights, stored **per job** so a stored result whose
#: confidence was computed under old weights remains explicable. Recomputing the
#: displayed number from today's config would silently rewrite history.
DEFAULT_SCORE_WEIGHTS = (
    '{"feature": 0.25, "geometric": 0.35, "landmark": 0.30, "semantic": 0.10}'
)

#: The four live states. Shared by the partial indexes on every job table so a worker
#: can find its queue without scanning the terminal rows, which are the vast majority.
_LIVE_STATUSES = "('pending', 'queued', 'running', 'retrying')"


class MatchJob(UUIDPkMixin, TimestampMixin, Base):
    """One automatic-matching run: its full, reproducible parameter set and outcome.

    ★ ``use_semantic`` vs ``semantic_available`` **is the graceful-degradation record**
    (L1 expressed as data). The user asks for SAM; the worker discovers the weights are
    absent, logs, and proceeds classically — **the job SUCCEEDS**. But the row must not
    lie about what produced the numbers: ``use_semantic=TRUE``,
    ``semantic_available=FALSE``, a line in ``warnings``, and
    ``match_results.semantic_similarity_score IS NULL``.
    """

    __tablename__ = "match_jobs"

    image_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )
    #: ★ The FK itself is added in migration ``0005`` *after* both tables exist — see
    #: the module docstring. ``use_alter=True`` tells Alembic/``create_all`` the same.
    batch_job_item_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "batch_job_items.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_match_jobs_batch_job_item_id_batch_job_items",
        ),
        nullable=True,
    )
    #: NULL between the INSERT and the ``.delay()``.
    celery_task_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[JobStatus] = mapped_column(
        pg_enum(JobStatus, "job_status"),
        nullable=False,
        server_default=text("'pending'::job_status"),
    )
    #: ★ Cooperative cancellation — the worker polls it; nothing kills a process.
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("3")
    )

    #: ★ The reproducibility record: what actually ran, not what config says today.
    provider: Mapped[ImageryProvider] = mapped_column(
        pg_enum(ImageryProvider, "imagery_provider"),
        nullable=False,
        server_default=text("'esri_world_imagery'::imagery_provider"),
    )
    extractor: Mapped[FeatureExtractor] = mapped_column(
        pg_enum(FeatureExtractor, "feature_extractor"),
        nullable=False,
        server_default=text("'sift'::feature_extractor"),
    )
    matcher: Mapped[FeatureMatcher] = mapped_column(
        pg_enum(FeatureMatcher, "feature_matcher"),
        nullable=False,
        server_default=text("'flann'::feature_matcher"),
    )
    estimator: Mapped[RobustEstimator] = mapped_column(
        pg_enum(RobustEstimator, "robust_estimator"),
        nullable=False,
        server_default=text("'usac_magsac'::robust_estimator"),
    )
    #: ★ Was SAM/DINOv2 **requested**?
    use_semantic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    #: ★ Was it **actually usable**?
    semantic_available: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    #: The RESOLVED hint, not the request.
    search_aoi: Mapped[WKBElement | None] = mapped_column(
        Geography(geometry_type="POLYGON", srid=4326, spatial_index=False),
        nullable=True,
    )
    search_radius_m: Mapped[float | None] = mapped_column(Double, nullable=True)
    search_zoom_levels: Mapped[list[int]] = mapped_column(
        PG_ARRAY(SmallInteger, dimensions=1),
        nullable=False,
        server_default=text("'{18}'::smallint[]"),
    )
    max_tiles: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("256")
    )
    max_candidates: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("25")
    )
    #: Extractor/matcher/RANSAC knobs.
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    score_weights: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text(f"'{DEFAULT_SCORE_WEIGHTS}'::jsonb")
    )
    #: ★ Pins the annotation set matched against.
    annotation_revision_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    #: Pins RANSAC's RNG → bit-reproducible.
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: **0–1** in the DB; ``JobProgress.percent`` is 0–100 on the wire.
    progress: Mapped[float] = mapped_column(
        Double, nullable=False, server_default=text("0.0")
    )
    progress_stage: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    tiles_fetched: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    tiles_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    candidates_evaluated: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    result_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    #: 0–100 — denormalised from the selected result.
    best_confidence: Mapped[float | None] = mapped_column(Double, nullable=True)

    error_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: ★ **Stored server-side only. NEVER serialised.**
    error_traceback: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: ``WarningItem[]``.
    warnings: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )

    #: Git sha of the worker image.
    code_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    worker_hostname: Mapped[str | None] = mapped_column(Text, nullable=True)
    used_gpu: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    #: ★ The L1 UX contract: a degraded run is a *successful* run that says so.
    degraded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    degradation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    queued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    image: Mapped[Image] = relationship(back_populates="match_jobs", lazy="raise")
    batch_job_item: Mapped[BatchJobItem | None] = relationship(
        back_populates="match_jobs",
        foreign_keys=lambda: [MatchJob.batch_job_item_id],
        lazy="raise",
    )
    results: Mapped[list[MatchResult]] = relationship(
        back_populates="match_job",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    heatmap: Mapped[ConfidenceHeatmap | None] = relationship(
        back_populates="match_job",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
        lazy="raise",
    )

    __table_args__ = (
        CheckConstraint("progress BETWEEN 0 AND 1", name="progress"),
        CheckConstraint("attempt >= 0 AND attempt <= max_attempts", name="attempt"),
        CheckConstraint(
            "best_confidence IS NULL OR best_confidence BETWEEN 0 AND 100",
            name="best_conf",
        ),
        CheckConstraint(
            "status <> 'failed' OR error_message IS NOT NULL", name="failed_has_error"
        ),
        # ★ A biconditional: it catches both "marked succeeded but never timestamped"
        # and "timestamped but still shows running" — the two states that make a
        # progress UI hang forever.
        CheckConstraint(
            "(status IN ('succeeded', 'failed', 'cancelled')) = (finished_at IS NOT NULL)",
            name="finished_iff_terminal",
        ),
        Index(
            "uq_match_jobs_celery_task_id",
            "celery_task_id",
            unique=True,
            postgresql_where=text("celery_task_id IS NOT NULL"),
        ),
        Index(
            "ix_match_jobs_status_created",
            "status",
            "created_at",
            postgresql_where=text(f"status IN {_LIVE_STATUSES}"),
        ),
        Index("ix_match_jobs_image_created", "image_id", text("created_at DESC")),
        Index("ix_match_jobs_batch_item", "batch_job_item_id"),
        Index(
            "ix_match_jobs_search_aoi",
            "search_aoi",
            postgresql_using="gist",
            postgresql_where=text("search_aoi IS NOT NULL"),
        ),
        Index(
            "ix_match_jobs_params",
            "params",
            postgresql_using="gin",
            postgresql_ops={"params": "jsonb_path_ops"},
        ),
    )


# Heavy `progress` UPDATE churn: keep HOT updates on-page and off the indexes.
# `fillfactor` is a table storage parameter, and SQLAlchemy's postgresql dialect accepts
# `with` only on Index, never on Table — so it is emitted as DDL rather than declared in
# __table_args__. Alembic 0005 carries the same ALTER; this listener exists so that
# `metadata.create_all()` (tests, throwaway DBs) matches a migrated database.
event.listen(
    MatchJob.__table__,
    "after_create",
    DDL("ALTER TABLE match_jobs SET (fillfactor = 70)").execute_if(dialect="postgresql"),
)


class AuxJob(UUIDPkMixin, TimestampMixin, Base):
    """``segment`` · ``suggest_landmarks`` · ``gcp_recompute`` · ``ingest``.

    The API promises ``202 → GET /jobs/{id}`` for these four; before §12 C-19 they had
    no home in the DB. ``match`` and ``batch`` and ``export`` each have their own table
    because each has its own columns; these four share one shape exactly.
    """

    __tablename__ = "aux_jobs"

    type: Mapped[JobType] = mapped_column(pg_enum(JobType, "job_type"), nullable=False)
    image_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )
    #: ``gcp_recompute`` only.
    match_result_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("match_results.id", ondelete="SET NULL"),
        nullable=True,
    )
    celery_task_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[JobStatus] = mapped_column(
        pg_enum(JobStatus, "job_status"),
        nullable=False,
        server_default=text("'pending'::job_status"),
    )
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("3")
    )
    #: The request body, verbatim.
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    progress: Mapped[float] = mapped_column(
        Double, nullable=False, server_default=text("0.0")
    )
    progress_stage: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    error_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_traceback: Mapped[str | None] = mapped_column(Text, nullable=True)
    warnings: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    degraded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    degradation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    code_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    worker_hostname: Mapped[str | None] = mapped_column(Text, nullable=True)
    queued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    image: Mapped[Image] = relationship(back_populates="aux_jobs", lazy="raise")
    match_result: Mapped[MatchResult | None] = relationship(
        back_populates="aux_jobs", lazy="raise"
    )
    suggestions: Mapped[list[LandmarkSuggestion]] = relationship(
        back_populates="aux_job", lazy="raise"
    )

    __table_args__ = (
        # ★ `match`, `export` and `batch` have their own tables; an aux_jobs row
        # claiming to be one of them would be a second, contradictory record of it.
        CheckConstraint(
            "type IN ('segment', 'suggest_landmarks', 'gcp_recompute', 'ingest')",
            name="type",
        ),
        CheckConstraint("progress BETWEEN 0 AND 1", name="progress"),
        CheckConstraint("attempt >= 0 AND attempt <= max_attempts", name="attempt"),
        CheckConstraint(
            "status <> 'failed' OR error_message IS NOT NULL", name="failed_has_error"
        ),
        CheckConstraint(
            "(status IN ('succeeded', 'failed', 'cancelled')) = (finished_at IS NOT NULL)",
            name="finished_iff_terminal",
        ),
        Index(
            "uq_aux_jobs_celery_task_id",
            "celery_task_id",
            unique=True,
            postgresql_where=text("celery_task_id IS NOT NULL"),
        ),
        Index(
            "ix_aux_jobs_status_created",
            "status",
            "created_at",
            postgresql_where=text(f"status IN {_LIVE_STATUSES}"),
        ),
        Index("ix_aux_jobs_image_type", "image_id", "type", text("created_at DESC")),
    )


class BatchJob(UUIDPkMixin, TimestampMixin, Base):
    """A fan-out over many images of one project.

    ★ SCOPE.md §3: batch **upload/metadata/export** is built; batch *matching* is not,
    because matching is not. The table's shape does not change for that.
    """

    __tablename__ = "batch_jobs"

    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    celery_group_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[JobStatus] = mapped_column(
        pg_enum(JobStatus, "job_status"),
        nullable=False,
        server_default=text("'pending'::job_status"),
    )
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    total_items: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    completed_items: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    failed_items: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    progress: Mapped[float] = mapped_column(
        Double, nullable=False, server_default=text("0.0")
    )
    provider: Mapped[ImageryProvider] = mapped_column(
        pg_enum(ImageryProvider, "imagery_provider"),
        nullable=False,
        server_default=text("'esri_world_imagery'::imagery_provider"),
    )
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    concurrency: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("4")
    )
    continue_on_error: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── the shared lifecycle columns migration 0008 adds (§5.5) ──────────────
    # They are real facts about a batch — a batch *does* retry and *does* have a
    # queued_at — and their absence in v1.0 was an oversight, not a design. Without
    # them `v_jobs` is unwritable, because `JobRead` requires all of them non-null.
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("3")
    )
    progress_stage: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    degraded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    degradation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    queued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warnings: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )

    project: Mapped[Project] = relationship(back_populates="batch_jobs", lazy="raise")
    items: Mapped[list[BatchJobItem]] = relationship(
        back_populates="batch_job",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )

    __table_args__ = (
        CheckConstraint("progress BETWEEN 0 AND 1", name="progress"),
        CheckConstraint(
            "completed_items + failed_items <= total_items", name="counts"
        ),
        CheckConstraint("concurrency BETWEEN 1 AND 64", name="concurrency"),
        CheckConstraint("attempt >= 0 AND attempt <= max_attempts", name="attempt"),
        Index(
            "uq_batch_jobs_celery_group_id",
            "celery_group_id",
            unique=True,
            postgresql_where=text("celery_group_id IS NOT NULL"),
        ),
        Index("ix_batch_jobs_project_created", "project_id", text("created_at DESC")),
        Index(
            "ix_batch_jobs_status",
            "status",
            "created_at",
            postgresql_where=text(f"status IN {_LIVE_STATUSES}"),
        ),
    )


class BatchJobItem(UUIDPkMixin, TimestampMixin, Base):
    """One image's slot in a batch."""

    __tablename__ = "batch_job_items"

    batch_job_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("batch_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    image_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )
    #: ★ The other half of the deliberate cycle — added in ``0005`` after both tables
    #: exist. ``SET NULL`` on both sides, so no cascade cycle is possible.
    match_job_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "match_jobs.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_batch_job_items_match_job_id_match_jobs",
        ),
        nullable=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        pg_enum(JobStatus, "job_status"),
        nullable=False,
        server_default=text("'pending'::job_status"),
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    batch_job: Mapped[BatchJob] = relationship(back_populates="items", lazy="raise")
    image: Mapped[Image] = relationship(back_populates="batch_job_items", lazy="raise")
    match_jobs: Mapped[list[MatchJob]] = relationship(
        back_populates="batch_job_item",
        foreign_keys=lambda: [MatchJob.batch_job_item_id],
        lazy="raise",
    )

    __table_args__ = (
        CheckConstraint("ordinal >= 0", name="ordinal_nonneg"),
        # ★ Prevents the double-click-submit bug IN THE DATABASE.
        Index("uq_batch_job_items_batch_image", "batch_job_id", "image_id", unique=True),
        Index(
            "uq_batch_job_items_batch_ordinal", "batch_job_id", "ordinal", unique=True
        ),
        Index("ix_batch_job_items_batch_status", "batch_job_id", "status"),
        Index("ix_batch_job_items_image", "image_id"),
    )
