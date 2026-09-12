"""detection_events

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-31

``detection_events`` — every box a detection run produced, durably recorded (product
owner request, 2026-08-31): the instant of detection in UTC (``detected_at``), the same
instant rendered in the server's local zone (``detected_at_local``, ISO-8601 with offset,
stored verbatim so it survives zone changes), and the tracker's id for the object
(``track_id`` — the ``#N`` the overlay shows).

★ No FK anywhere: sessions are in-memory by design and rows must outlive them; a run on
a clip that is later deleted keeps its evidence. ``lat``/``lon`` are nullable — a run
without a LUT still detects, it just cannot say where.

★ Plain ``created_at``-style trigger is NOT installed: rows are immutable facts written
once by the run thread; there is no ``updated_at`` to maintain.
"""

from __future__ import annotations

from typing import Sequence

import geoalchemy2  # noqa: F401  # ★ see script.py.mako — never remove
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "detection_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("camera_name", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("lut_site", sa.Text(), nullable=True),
        sa.Column("track_id", sa.Integer(), nullable=True),
        sa.Column("cls_name", sa.Text(), nullable=False),
        sa.Column("score", sa.Double(), nullable=False),
        sa.Column("predicted", sa.Boolean(), nullable=False),
        sa.Column("frame_index", sa.Integer(), nullable=False),
        sa.Column("time_s", sa.Double(), nullable=False),
        sa.Column("u", sa.Double(), nullable=True),
        sa.Column("v", sa.Double(), nullable=True),
        sa.Column("lat", sa.Double(), nullable=True),
        sa.Column("lon", sa.Double(), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detected_at_local", sa.Text(), nullable=False),
        sa.CheckConstraint("score >= 0 AND score <= 1", name="ck_detection_events_score"),
        sa.CheckConstraint("frame_index >= 0", name="ck_detection_events_frame_nonneg"),
        sa.PrimaryKeyConstraint("id", name="pk_detection_events"),
    )
    op.create_index(
        "ix_detection_events_session_frame", "detection_events", ["session_id", "frame_index"]
    )
    op.create_index(
        "ix_detection_events_session_track", "detection_events", ["session_id", "track_id"]
    )
    op.create_index("ix_detection_events_detected_at", "detection_events", ["detected_at"])


def downgrade() -> None:
    op.drop_index("ix_detection_events_detected_at", table_name="detection_events")
    op.drop_index("ix_detection_events_session_track", table_name="detection_events")
    op.drop_index("ix_detection_events_session_frame", table_name="detection_events")
    op.drop_table("detection_events")
