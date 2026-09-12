"""camera_setup_pipeline

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-04

★ THE CAMERA OWNS ITS SETUP (2026-09-04, owner ask). The "Server of cameras" page
adds a camera through ONE pipeline — name, connection, DEM, calibration, position,
a frame, its control points, its lookup table — and the registry row has to
remember where each of those lives:

* ``project_id`` — the camera's BACKING PROJECT. A lookup table is built from an
  image inside a project (its intrinsics, its GCPs, the project's DEM); giving
  every camera a project of its own lets the existing DEM, editor and LUT
  machinery serve the camera unchanged. SET NULL on delete: the camera outlives a
  project someone removed, and says so.
* ``frame_image_id`` — the frame chosen from this camera, the photograph the
  control points are placed on. SET NULL when the image goes.
* ``calibration`` — the optional intrinsics / mast / tilt the operator entered on
  the camera itself, kept here so a re-captured frame inherits them.

And the connection vocabulary widens to what the field actually plugs in:
UTP/LAN (``lan``), a stream URL (``stream``), HDMI / USB / BNC capture, serial /
UART data lines, and an embedded board. A UART line, like a serial one, carries
data and no picture.
"""

from __future__ import annotations

from collections.abc import Sequence

import geoalchemy2  # noqa: F401  # ★ see script.py.mako — never remove
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_CONNECTIONS = "connection IN ('lan', 'hdmi', 'serial', 'embedded')"
_NEW_CONNECTIONS = (
    "connection IN ('lan', 'stream', 'hdmi', 'usb', 'bnc', 'serial', 'uart', 'embedded')"
)
_OLD_SERIAL_IS_DATA = "connection <> 'serial' OR provides = 'data'"
_NEW_SERIAL_IS_DATA = "connection NOT IN ('serial', 'uart') OR provides = 'data'"


def upgrade() -> None:
    op.add_column(
        "cameras",
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="SET NULL", name="fk_cameras_project_id"),
            nullable=True,
        ),
    )
    op.add_column(
        "cameras",
        sa.Column(
            "frame_image_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("images.id", ondelete="SET NULL", name="fk_cameras_frame_image_id"),
            nullable=True,
        ),
    )
    op.add_column(
        "cameras",
        sa.Column("calibration", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.drop_constraint("ck_cameras_connection_known", "cameras", type_="check")
    op.create_check_constraint("ck_cameras_connection_known", "cameras", _NEW_CONNECTIONS)
    op.drop_constraint("ck_cameras_serial_is_data", "cameras", type_="check")
    op.create_check_constraint("ck_cameras_serial_is_data", "cameras", _NEW_SERIAL_IS_DATA)


def downgrade() -> None:
    # ★ Rows using the new kinds cannot satisfy the old CHECK: fold them back to the
    #   nearest old vocabulary before the constraint returns.
    op.execute("UPDATE cameras SET connection = 'lan' WHERE connection = 'stream'")
    op.execute("UPDATE cameras SET connection = 'hdmi' WHERE connection IN ('usb', 'bnc')")
    op.execute("UPDATE cameras SET connection = 'serial' WHERE connection = 'uart'")
    op.drop_constraint("ck_cameras_serial_is_data", "cameras", type_="check")
    op.create_check_constraint("ck_cameras_serial_is_data", "cameras", _OLD_SERIAL_IS_DATA)
    op.drop_constraint("ck_cameras_connection_known", "cameras", type_="check")
    op.create_check_constraint("ck_cameras_connection_known", "cameras", _OLD_CONNECTIONS)
    op.drop_column("cameras", "calibration")
    op.drop_column("cameras", "frame_image_id")
    op.drop_column("cameras", "project_id")
