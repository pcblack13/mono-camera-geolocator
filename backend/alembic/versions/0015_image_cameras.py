"""image_cameras

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-29

The manually entered camera moves from the PROJECT to the IMAGE. 0014 introduced
``project_cameras`` on the assumption of one fixed station per project; the product
moved to per-photograph setup — every photo brought into a project gets its own
setup page, so the calibration, position and tilt are attributes of the image.

★ ``image_cameras`` is ``project_cameras`` re-keyed: same columns, same CHECKs, PK =
``image_id`` FK ``images ON DELETE CASCADE``. ``project_cameras`` is DROPPED — its
rows are not migrated, because a project-level station names no image and inventing
the mapping ("the first image, probably") would silently attach a calibration to a
photograph it may not describe (L12). The setup pages re-collect it per photo.

★ ``downgrade()`` recreates ``project_cameras`` exactly as 0014 built it (empty, for
the same no-invented-mapping reason) and drops ``image_cameras``.
"""

from __future__ import annotations

from typing import Sequence

import geoalchemy2  # noqa: F401  # ★ see script.py.mako — never remove
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _camera_columns() -> list[sa.Column]:
    """The shared column set of both incarnations (everything but the key)."""
    return [
        # ★ Intrinsics — pixels, OpenCV pinhole; distortion consumed as [k1,k2,p1,p2,k3].
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
        # ★ WGS84 ground point; projected X/Y/Z stay derived (position + DEM), §5.2.
        sa.Column(
            "position",
            geoalchemy2.types.Geography(
                geometry_type="POINT", srid=4326, spatial_index=False
            ),
            nullable=True,
        ),
        sa.Column("mast_offset_m", sa.Double(), nullable=True),
        # ★ Degrees below horizontal, + = aimed down (tilt_deg = -pitch_deg).
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
    ]


def upgrade() -> None:
    op.create_table(
        "image_cameras",
        sa.Column("image_id", postgresql.UUID(as_uuid=True), nullable=False),
        *_camera_columns(),
        sa.CheckConstraint(
            "(fx IS NULL OR fx > 0) AND (fy IS NULL OR fy > 0)",
            name="ck_image_cameras_focal_positive",
        ),
        sa.CheckConstraint(
            "(img_w IS NULL OR img_w > 0) AND (img_h IS NULL OR img_h > 0)",
            name="ck_image_cameras_dims_positive",
        ),
        sa.CheckConstraint(
            "tilt_deg IS NULL OR tilt_deg BETWEEN -90 AND 90",
            name="ck_image_cameras_tilt_range",
        ),
        sa.ForeignKeyConstraint(
            ["image_id"],
            ["images.id"],
            name="fk_image_cameras_image_id_images",
            ondelete="CASCADE",
        ),
        # ★ The PK IS the FK: one entered camera per photograph.
        sa.PrimaryKeyConstraint("image_id", name="pk_image_cameras"),
    )
    op.execute(
        "CREATE TRIGGER tg_image_cameras_set_updated_at"
        " BEFORE UPDATE ON image_cameras"
        " FOR EACH ROW EXECUTE FUNCTION tg_set_updated_at()"
    )

    op.execute(
        "DROP TRIGGER IF EXISTS tg_project_cameras_set_updated_at ON project_cameras"
    )
    op.drop_table("project_cameras")


def downgrade() -> None:
    op.create_table(
        "project_cameras",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        *_camera_columns(),
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
        sa.PrimaryKeyConstraint("project_id", name="pk_project_cameras"),
    )
    op.execute(
        "CREATE TRIGGER tg_project_cameras_set_updated_at"
        " BEFORE UPDATE ON project_cameras"
        " FOR EACH ROW EXECUTE FUNCTION tg_set_updated_at()"
    )

    op.execute(
        "DROP TRIGGER IF EXISTS tg_image_cameras_set_updated_at ON image_cameras"
    )
    op.drop_table("image_cameras")
