"""``exports`` — :class:`Export` (CONTRACT.md §5.6).

**``filter`` is persisted** so "regenerate this export" is reproducible — and so a stale
export whose ``gcp_count`` disagrees with today's GCP count is **detectable**, which is
exactly the audit question a surveyor asks: *"is the file I sent the client still
current?"*
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import ExportFormat, JobStatus, pg_enum
from app.models.mixins import TimestampMixin, UUIDPkMixin

if TYPE_CHECKING:
    from app.models.image import Image
    from app.models.project import Project

__all__ = ["Export"]


class Export(UUIDPkMixin, TimestampMixin, Base):
    """A rendered deliverable: CSV, GeoJSON, Shapefile, KML, KMZ, PDF, GPKG or DXF."""

    __tablename__ = "exports"

    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: NULL ⇒ a whole-project export.
    image_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("images.id", ondelete="CASCADE"), nullable=True
    )
    format: Mapped[ExportFormat] = mapped_column(
        pg_enum(ExportFormat, "export_format"), nullable=False
    )
    status: Mapped[JobStatus] = mapped_column(
        pg_enum(JobStatus, "job_status"),
        nullable=False,
        server_default=text("'pending'::job_status"),
    )
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    celery_task_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: NULL until succeeded.
    storage_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    gcp_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: ★ Exporter HINT — reprojection happens in GeoPandas, in memory. Nothing is
    #: *stored* in this SRID (§5.2).
    target_srid: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("4326")
    )
    options: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    filter: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    warnings: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── the shared lifecycle columns migration 0008 adds (§5.5) ──────────────
    # An export *does* retry and *does* have a queued_at; their absence in v1.0 was an
    # oversight, not a design, and without them `v_jobs` is unwritable because
    # `JobRead` requires attempt/max_attempts/degraded/progress non-null.
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("3")
    )
    progress: Mapped[float] = mapped_column(
        Double, nullable=False, server_default=text("0.0")
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
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: ★ Added alongside the §5.5 list: the ``v_jobs`` export branch selects
    #: ``e.finished_at`` and ``JobRead.finished_at`` is part of the job read model, so
    #: the view is unwritable without it. The §5.5 prose enumerates ``started_at`` but
    #: omits ``finished_at``; the SELECT list — which is the normative artefact — needs
    #: both. Flagged in the PR description.
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    project: Mapped[Project] = relationship(back_populates="exports", lazy="raise")
    image: Mapped[Image | None] = relationship(back_populates="exports", lazy="raise")

    __table_args__ = (
        CheckConstraint("target_srid BETWEEN 1024 AND 32767", name="target_srid"),
        CheckConstraint(
            "status <> 'succeeded' OR (storage_path IS NOT NULL AND size_bytes IS NOT NULL)",
            name="succeeded_has_path",
        ),
        CheckConstraint(
            "status <> 'failed' OR error_message IS NOT NULL", name="failed_has_error"
        ),
        CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="size"),
        CheckConstraint("progress BETWEEN 0 AND 1", name="progress"),
        CheckConstraint("attempt >= 0 AND attempt <= max_attempts", name="attempt"),
        Index(
            "uq_exports_celery_task_id",
            "celery_task_id",
            unique=True,
            postgresql_where=text("celery_task_id IS NOT NULL"),
        ),
        Index("ix_exports_project_created", "project_id", text("created_at DESC")),
        Index("ix_exports_image", "image_id", postgresql_where=text("image_id IS NOT NULL")),
        Index(
            "ix_exports_status",
            "status",
            "created_at",
            postgresql_where=text("status IN ('pending', 'queued', 'running')"),
        ),
        Index(
            "ix_exports_expires",
            "expires_at",
            postgresql_where=text("expires_at IS NOT NULL AND status = 'succeeded'"),
        ),
        Index(
            "ix_exports_options",
            "options",
            postgresql_using="gin",
            postgresql_ops={"options": "jsonb_path_ops"},
        ),
    )
