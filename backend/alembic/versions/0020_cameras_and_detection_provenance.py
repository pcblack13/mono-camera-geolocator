"""cameras_and_detection_provenance

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-02

Two things, one release (1.3):

1. ``cameras`` — the registered fixed cameras, SERVER-SIDE at last, with a ``desired``
   JSONB recording what each should be doing (watch / detect / feed) so the API can
   bring its threads back after a restart. Until now the registry lived in one
   browser's localStorage; a second machine saw nothing.

2. ``detection_events`` gains its provenance columns:
   ``kind`` (``'detection'`` from this machine's YOLO, ``'feed'`` from a serial/HTTP
   data feed — feeds were never recorded before, contradicting "the table is THE
   record"), ``camera_id`` (the registry row — NO FK, on purpose: a camera removed
   from the registry does not erase what it saw), ``drift_status`` (the drift
   monitor's confirmed verdict at the moment of detection: ok / moved / changed /
   degraded / pending / unwatched — so "was the camera trusted when this was seen"
   is a column, not a reconstruction from two logs), ``drift_ref_id`` (which
   reference said so) and ``centre_offset_m`` (the opt-in ground-contact correction
   applied, in metres; NULL = none applied).

★ Existing ``detection_events`` rows are backfilled ``kind='detection'`` and
``drift_status='unwatched'`` — both TRUE of every row written before this revision
(there was no feed writer and no stamp), so the backfill fabricates nothing.

★ ``cameras.updated_at`` gets the same ``tg_set_updated_at()`` trigger (0001) every
other ``updated_at`` table carries (0009): the ORM does not maintain it.
"""

from __future__ import annotations

from typing import Sequence

import geoalchemy2  # noqa: F401  # ★ see script.py.mako — never remove
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cameras",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("lat", sa.Double(), nullable=False),
        sa.Column("lon", sa.Double(), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("connection", sa.Text(), nullable=False, server_default=sa.text("'lan'")),
        sa.Column("provides", sa.Text(), nullable=False, server_default=sa.text("'camera'")),
        sa.Column("data_source", sa.Text(), nullable=True),
        sa.Column("heading_deg", sa.Double(), nullable=True),
        sa.Column("fov_deg", sa.Double(), nullable=True),
        sa.Column("fps", sa.Integer(), nullable=True),
        sa.Column(
            "tags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("lut_site", sa.Text(), nullable=True),
        sa.Column(
            "desired",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
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
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_cameras_name_nonblank"),
        sa.CheckConstraint("lat >= -90 AND lat <= 90", name="ck_cameras_lat_range"),
        sa.CheckConstraint("lon >= -180 AND lon <= 180", name="ck_cameras_lon_range"),
        sa.CheckConstraint(
            "connection IN ('lan', 'hdmi', 'serial', 'embedded')",
            name="ck_cameras_connection_known",
        ),
        sa.CheckConstraint(
            "provides IN ('camera', 'data', 'both')", name="ck_cameras_provides_known"
        ),
        sa.CheckConstraint(
            "connection <> 'serial' OR provides = 'data'", name="ck_cameras_serial_is_data"
        ),
        sa.CheckConstraint(
            "provides = 'data' OR (source IS NOT NULL AND length(btrim(source)) > 0)",
            name="ck_cameras_video_has_source",
        ),
        sa.CheckConstraint(
            "provides = 'camera' OR (data_source IS NOT NULL AND length(btrim(data_source)) > 0)",
            name="ck_cameras_data_has_source",
        ),
        sa.CheckConstraint(
            "heading_deg IS NULL OR (heading_deg >= 0 AND heading_deg <= 360)",
            name="ck_cameras_heading_range",
        ),
        sa.CheckConstraint(
            "fov_deg IS NULL OR (fov_deg > 0 AND fov_deg <= 180)", name="ck_cameras_fov_range"
        ),
        sa.CheckConstraint("fps IS NULL OR (fps >= 1 AND fps <= 30)", name="ck_cameras_fps_range"),
        sa.PrimaryKeyConstraint("id", name="pk_cameras"),
    )
    op.create_index("ix_cameras_name", "cameras", ["name"])
    op.execute(
        "CREATE TRIGGER tg_cameras_set_updated_at BEFORE UPDATE ON cameras"
        " FOR EACH ROW EXECUTE FUNCTION tg_set_updated_at()"
    )

    # ── detection_events: provenance ──────────────────────────────────────────
    op.add_column(
        "detection_events",
        sa.Column("kind", sa.Text(), nullable=False, server_default=sa.text("'detection'")),
    )
    op.add_column(
        "detection_events",
        sa.Column("camera_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "detection_events",
        sa.Column(
            "drift_status", sa.Text(), nullable=False, server_default=sa.text("'unwatched'")
        ),
    )
    op.add_column("detection_events", sa.Column("drift_ref_id", sa.Text(), nullable=True))
    op.add_column("detection_events", sa.Column("centre_offset_m", sa.Double(), nullable=True))
    op.create_check_constraint(
        "ck_detection_events_kind", "detection_events", "kind IN ('detection', 'feed')"
    )
    op.create_check_constraint(
        "ck_detection_events_drift_status",
        "detection_events",
        "drift_status IN ('unwatched', 'pending', 'ok', 'moved', 'changed', 'degraded')",
    )
    op.create_index(
        "ix_detection_events_camera_detected_at",
        "detection_events",
        ["camera_id", "detected_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_detection_events_camera_detected_at", table_name="detection_events")
    op.drop_constraint("ck_detection_events_drift_status", "detection_events", type_="check")
    op.drop_constraint("ck_detection_events_kind", "detection_events", type_="check")
    op.drop_column("detection_events", "centre_offset_m")
    op.drop_column("detection_events", "drift_ref_id")
    op.drop_column("detection_events", "drift_status")
    op.drop_column("detection_events", "camera_id")
    op.drop_column("detection_events", "kind")

    op.execute("DROP TRIGGER IF EXISTS tg_cameras_set_updated_at ON cameras")
    op.drop_index("ix_cameras_name", table_name="cameras")
    op.drop_table("cameras")
