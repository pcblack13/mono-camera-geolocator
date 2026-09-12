"""project_cameras

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-29

``project_cameras`` — the project's fixed camera station, entered at setup time:
OpenCV intrinsics (fx fy cx cy · k1 k2 p1 p2 k3 · img_w img_h), the WGS84 ground
position plus mast height, and the tilt below horizontal in degrees.

★ **1:1 with ``projects`` via a PK-that-is-the-FK.** This is *entered reference
data*, not a match-derived estimate — ``camera_poses`` (per-image, produced by the
deferred matcher) is a different thing and stays untouched. ``ON DELETE CASCADE``:
the station describes exactly one project and has no meaning beyond it.

★ **Every data column is nullable.** Setup is incremental (calibration CSV today,
position tomorrow); NULL means "not entered yet" and is never coerced to 0.
"""

from __future__ import annotations

from typing import Sequence

import geoalchemy2  # noqa: F401  # ★ see script.py.mako — never remove
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_cameras",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        # ★ Intrinsics — pixels, OpenCV pinhole. Consumed as K = [[fx,0,cx],[0,fy,cy],[0,0,1]]
        #   with the distortion vector in OpenCV order [k1, k2, p1, p2, k3].
        sa.Column("fx", sa.Double(), nullable=True),
        sa.Column("fy", sa.Double(), nullable=True),
        sa.Column("cx", sa.Double(), nullable=True),
        sa.Column("cy", sa.Double(), nullable=True),
        sa.Column("k1", sa.Double(), nullable=True),
        sa.Column("k2", sa.Double(), nullable=True),
        sa.Column("p1", sa.Double(), nullable=True),
        sa.Column("p2", sa.Double(), nullable=True),
        sa.Column("k3", sa.Double(), nullable=True),
        sa.Column("img_w", sa.Integer(), nullable=True),
        sa.Column("img_h", sa.Integer(), nullable=True),
        # ★ WGS84 ground point. Projected coordinates are derived (position + project
        #   DEM), never stored — two stored copies are two chances to disagree (§5.2).
        sa.Column(
            "position",
            geoalchemy2.types.Geography(
                geometry_type="POINT", srid=4326, spatial_index=False
            ),
            nullable=True,
        ),
        # Metres above the bare-earth DEM at ``position`` (mast/tower height).
        sa.Column("mast_offset_m", sa.Double(), nullable=True),
        # ★ Degrees below horizontal, + = aimed down (field-tool convention;
        #   tilt_deg = -pitch_deg in ``camera_poses`` vocabulary).
        sa.Column("tilt_deg", sa.Double(), nullable=True),
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
        sa.CheckConstraint(
            "(fx IS NULL OR fx > 0) AND (fy IS NULL OR fy > 0)",
            name="ck_project_cameras_focal_positive",
        ),
        sa.CheckConstraint(
            "(img_w IS NULL OR img_w > 0) AND (img_h IS NULL OR img_h > 0)",
            name="ck_project_cameras_dims_positive",
        ),
        sa.CheckConstraint(
            "tilt_deg IS NULL OR tilt_deg BETWEEN -90 AND 90",
            name="ck_project_cameras_tilt_range",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_project_cameras_project_id_projects",
            ondelete="CASCADE",
        ),
        # ★ The PK IS the FK: one station per project, duplicates unrepresentable.
        sa.PrimaryKeyConstraint("project_id", name="pk_project_cameras"),
    )

    # ★ ``updated_at`` is maintained by the trigger, not the ORM (§5.4) — the same
    #   ``tg_set_updated_at()`` created in 0001 and attached per table since 0009.
    op.execute(
        "CREATE TRIGGER tg_project_cameras_set_updated_at"
        " BEFORE UPDATE ON project_cameras"
        " FOR EACH ROW EXECUTE FUNCTION tg_set_updated_at()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS tg_project_cameras_set_updated_at ON project_cameras"
    )
    op.drop_table("project_cameras")
