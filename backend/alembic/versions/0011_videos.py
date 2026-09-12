"""videos

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-22

``videos`` — a field VIDEO uploaded as a FRAME SOURCE, plus two provenance columns on
``images`` for a CAPTURED FRAME.

★ A video is not imagery; it is a source of imagery. The table carries only the
container's facts (duration, fps, dimensions, codec) read synchronously at upload by
OpenCV's FFMPEG backend — **no geometry**. When the surveyor captures a second, the frame
becomes a normal ``images`` row that records ``source_video_id`` + ``source_video_time_s``
and flows into the existing annotation/GCP pipeline unchanged.

★ Like ``0010``, this revision creates its own indexes and its own ``updated_at`` trigger
(the same ``tg_set_updated_at()`` from ``0001``) rather than deferring to a later
"indexes" migration — a feature added after ``0009`` has nowhere to defer to.

★ ``images.source_video_id`` is ``ON DELETE SET NULL``: hard-deleting a video orphans the
frames a surveyor already annotated but never destroys them. The frames are ordinary
images and outlive their source.
"""

from __future__ import annotations

from typing import Sequence

import geoalchemy2  # noqa: F401  # ★ see script.py.mako — never remove
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "videos",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("checksum_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("duration_s", sa.Double(), nullable=False),
        sa.Column("fps", sa.Double(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("frame_count", sa.Integer(), nullable=True),
        sa.Column("codec", sa.Text(), nullable=True),
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
        # ★ Soft delete, matching ``images`` — a video is a user-named upload and deleting
        #   one by accident must be recoverable.
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("width > 0 AND height > 0", name="ck_videos_dims"),
        sa.CheckConstraint("size_bytes > 0", name="ck_videos_size"),
        sa.CheckConstraint("duration_s >= 0", name="ck_videos_duration_nonneg"),
        sa.CheckConstraint("fps >= 0", name="ck_videos_fps_nonneg"),
        sa.CheckConstraint(
            "checksum_sha256 ~ '^[0-9a-f]{64}$'", name="ck_videos_checksum_hex"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_videos_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_videos"),
    )

    op.execute(
        "CREATE UNIQUE INDEX uq_videos_storage_path ON videos (storage_path)"
    )
    op.execute(
        "CREATE INDEX ix_videos_project_created ON videos (project_id, created_at DESC)"
        " WHERE deleted_at IS NULL"
    )

    # ★ ``updated_at`` is maintained by the trigger, not the ORM (§5.4) — the same
    #   ``tg_set_updated_at()`` created in 0001 and attached per table since 0009/0010.
    op.execute(
        "CREATE TRIGGER tg_videos_set_updated_at BEFORE UPDATE ON videos"
        " FOR EACH ROW EXECUTE FUNCTION tg_set_updated_at()"
    )

    # ── images: provenance of a captured frame ────────────────────────────────────
    op.add_column(
        "images",
        sa.Column("source_video_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "images",
        sa.Column("source_video_time_s", sa.Double(), nullable=True),
    )
    op.create_foreign_key(
        "fk_images_source_video_id_videos",
        "images",
        "videos",
        ["source_video_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        "CREATE INDEX ix_images_source_video ON images (source_video_id)"
        " WHERE source_video_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_images_source_video")
    op.drop_constraint("fk_images_source_video_id_videos", "images", type_="foreignkey")
    op.drop_column("images", "source_video_time_s")
    op.drop_column("images", "source_video_id")

    op.execute("DROP TRIGGER IF EXISTS tg_videos_set_updated_at ON videos")
    op.execute("DROP INDEX IF EXISTS ix_videos_project_created")
    op.execute("DROP INDEX IF EXISTS uq_videos_storage_path")
    op.drop_table("videos")
