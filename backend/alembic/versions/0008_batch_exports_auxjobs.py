"""batch exports auxjobs

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-17

``aux_jobs`` · ``exports`` · **the shared-job-column backfill that makes ``v_jobs``
expressible** (§5.5).

★ **Why the backfill exists.** ``JobRead`` requires ``attempt: int``,
``max_attempts: int``, ``degraded: bool``, ``warnings: list[WarningItem]`` and
``progress: JobProgress`` (with a **non-null** ``stage``) — all non-nullable — while
``exports`` had none of the lifecycle columns and ``batch_jobs`` had most of them
missing. The ``v_jobs`` view of v1.0 was **unwritable as specified**. The ruling takes
both halves of the fix: the genuinely *shared* facts become real columns here (an export
**does** retry and **does** have a ``queued_at``; their absence was an oversight, not a
design), and §5.5's SELECT list supplies a literal for the columns that are honestly
inapplicable per branch.

★ ``exports.finished_at`` is added alongside §5.5's enumerated list. The prose names
``started_at`` and omits ``finished_at``, but the ``v_jobs`` export branch — the
normative artefact — selects ``e.finished_at``, and ``JobRead.finished_at`` is part of
the read model. Flagged in the PR description.
"""

from __future__ import annotations

from typing import Sequence

import geoalchemy2  # noqa: F401  # ★ see script.py.mako — never remove
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JOB_STATUS = postgresql.ENUM(
    "pending", "queued", "running", "succeeded", "failed", "cancelled", "retrying",
    name="job_status",
    create_type=False,
)
_JOB_TYPE = postgresql.ENUM(
    "match", "export", "batch", "segment", "suggest_landmarks", "gcp_recompute", "ingest",
    name="job_type",
    create_type=False,
)
_EXPORT_FORMAT = postgresql.ENUM(
    "csv", "geojson", "shapefile", "kml", "kmz", "pdf", "gpkg", "dxf",
    name="export_format",
    create_type=False,
)


def upgrade() -> None:
    op.create_table(
        "aux_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("type", _JOB_TYPE, nullable=False),
        sa.Column("image_id", postgresql.UUID(as_uuid=True), nullable=False),
        # `gcp_recompute` only.
        sa.Column("match_result_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("celery_task_id", sa.Text(), nullable=True),
        sa.Column(
            "status",
            _JOB_STATUS,
            server_default=sa.text("'pending'::job_status"),
            nullable=False,
        ),
        sa.Column(
            "cancel_requested", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("attempt", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default=sa.text("3"), nullable=False),
        # The request body, verbatim.
        sa.Column(
            "params",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("progress", sa.Double(), server_default=sa.text("0.0"), nullable=False),
        sa.Column("progress_stage", sa.Text(), nullable=True),
        sa.Column("progress_message", sa.Text(), nullable=True),
        sa.Column("result_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error_type", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_traceback", sa.Text(), nullable=True),
        sa.Column(
            "warnings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("degraded", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("degradation_reason", sa.Text(), nullable=True),
        sa.Column("code_version", sa.Text(), nullable=True),
        sa.Column("worker_hostname", sa.Text(), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # ★ `match`, `batch` and `export` have their own tables; an aux_jobs row
        # claiming to be one of them would be a second, contradictory record of it —
        # and v_jobs would return the job twice.
        sa.CheckConstraint(
            "type IN ('segment', 'suggest_landmarks', 'gcp_recompute', 'ingest')",
            name="ck_aux_jobs_type",
        ),
        sa.CheckConstraint("progress BETWEEN 0 AND 1", name="ck_aux_jobs_progress"),
        sa.CheckConstraint(
            "attempt >= 0 AND attempt <= max_attempts", name="ck_aux_jobs_attempt"
        ),
        sa.CheckConstraint(
            "status <> 'failed' OR error_message IS NOT NULL",
            name="ck_aux_jobs_failed_has_error",
        ),
        sa.CheckConstraint(
            "(status IN ('succeeded', 'failed', 'cancelled')) = (finished_at IS NOT NULL)",
            name="ck_aux_jobs_finished_iff_terminal",
        ),
        sa.ForeignKeyConstraint(
            ["image_id"], ["images.id"], name="fk_aux_jobs_image_id_images", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["match_result_id"],
            ["match_results.id"],
            name="fk_aux_jobs_match_result_id_match_results",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_aux_jobs"),
    )

    # ── landmark_suggestions.aux_job_id: the column landed in 0007, the constraint
    #    lands here, because aux_jobs did not exist until three statements ago.
    op.create_foreign_key(
        "fk_landmark_suggestions_aux_job_id_aux_jobs",
        "landmark_suggestions",
        "aux_jobs",
        ["aux_job_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "exports",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        # NULL ⇒ a whole-project export.
        sa.Column("image_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("format", _EXPORT_FORMAT, nullable=False),
        sa.Column(
            "status",
            _JOB_STATUS,
            server_default=sa.text("'pending'::job_status"),
            nullable=False,
        ),
        sa.Column(
            "cancel_requested", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("celery_task_id", sa.Text(), nullable=True),
        sa.Column("storage_path", sa.Text(), nullable=True),
        sa.Column("filename", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("checksum_sha256", sa.CHAR(64), nullable=True),
        sa.Column("gcp_count", sa.Integer(), nullable=True),
        # ★ Exporter HINT — reprojection happens in GeoPandas, in memory (§5.2).
        sa.Column("target_srid", sa.Integer(), server_default=sa.text("4326"), nullable=False),
        sa.Column(
            "options",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        # ★ Persisted so "regenerate this export" is reproducible — and so a stale
        # export whose gcp_count disagrees with today's is DETECTABLE, which is exactly
        # the audit question a surveyor asks: "is the file I sent the client current?"
        sa.Column(
            "filter",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "warnings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        # ── the shared lifecycle columns (§5.5) ──────────────────────────────
        sa.Column("attempt", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default=sa.text("3"), nullable=False),
        sa.Column("progress", sa.Double(), server_default=sa.text("0.0"), nullable=False),
        sa.Column("progress_stage", sa.Text(), nullable=True),
        sa.Column("progress_message", sa.Text(), nullable=True),
        sa.Column("degraded", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("degradation_reason", sa.Text(), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("target_srid BETWEEN 1024 AND 32767", name="ck_exports_target_srid"),
        sa.CheckConstraint(
            "status <> 'succeeded' OR (storage_path IS NOT NULL AND size_bytes IS NOT NULL)",
            name="ck_exports_succeeded_has_path",
        ),
        sa.CheckConstraint(
            "status <> 'failed' OR error_message IS NOT NULL", name="ck_exports_failed_has_error"
        ),
        sa.CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="ck_exports_size"),
        sa.CheckConstraint("progress BETWEEN 0 AND 1", name="ck_exports_progress"),
        sa.CheckConstraint("attempt >= 0 AND attempt <= max_attempts", name="ck_exports_attempt"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_exports_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["image_id"], ["images.id"], name="fk_exports_image_id_images", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_exports"),
    )

    # ── the shared-job-column backfill on batch_jobs ─────────────────────────
    # `exports` got its columns at CREATE TABLE above (it is created here, so there is
    # nothing to backfill); `batch_jobs` was created in 0005 and is altered.
    op.add_column(
        "batch_jobs",
        sa.Column("attempt", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "batch_jobs",
        sa.Column("max_attempts", sa.Integer(), server_default=sa.text("3"), nullable=False),
    )
    op.add_column("batch_jobs", sa.Column("progress_stage", sa.Text(), nullable=True))
    op.add_column("batch_jobs", sa.Column("progress_message", sa.Text(), nullable=True))
    op.add_column(
        "batch_jobs",
        sa.Column("degraded", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("batch_jobs", sa.Column("degradation_reason", sa.Text(), nullable=True))
    op.add_column("batch_jobs", sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("batch_jobs", sa.Column("duration_ms", sa.Integer(), nullable=True))
    op.add_column(
        "batch_jobs",
        sa.Column(
            "warnings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_batch_jobs_attempt", "batch_jobs", "attempt >= 0 AND attempt <= max_attempts"
    )


def downgrade() -> None:
    op.drop_constraint("ck_batch_jobs_attempt", "batch_jobs", type_="check")
    for column in (
        "warnings",
        "duration_ms",
        "queued_at",
        "degradation_reason",
        "degraded",
        "progress_message",
        "progress_stage",
        "max_attempts",
        "attempt",
    ):
        op.drop_column("batch_jobs", column)
    op.drop_table("exports")
    op.drop_constraint(
        "fk_landmark_suggestions_aux_job_id_aux_jobs",
        "landmark_suggestions",
        type_="foreignkey",
    )
    op.drop_table("aux_jobs")
