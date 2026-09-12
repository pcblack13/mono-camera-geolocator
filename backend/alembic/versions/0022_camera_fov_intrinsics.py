"""camera_fov_intrinsics

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-03

GEO-DRIFT-UPDATE C2 — a calibration becomes OPTIONAL, end to end.

``image_cameras`` gains ``no_calibration``, ``fov_h_deg`` and ``fov_v_deg``. When the
flag is set the build derives ``fx, fy, cx, cy`` from the field of view instead of
reading an entered calibration — the geolocation GUI's own model:

    fx = W / (2 tan(fov_h/2))   cx = W/2
    fy = H / (2 tan(fov_v/2))   cy = H/2   and no distortion at all

★ WHY A FLAG AND NOT JUST "fx IS NULL". A derived K assumes a centred principal point
and a perfect pinhole; neither is true of a real lens. Writing the derived numbers into
``fx..cy`` and leaving it there would make a *guess* indistinguishable from a
*measurement* the moment anyone reads the row back. The flag is the provenance, and it
travels into the LUT manifest and from there into every drift reference and field-unit
bundle built on it.

★ ``fov_v_deg`` NULL with the flag on means SQUARE PIXELS — fy = fx, and the vertical
angle is whatever that implies (``2·atan(H/2fy)``). It is stored only when a surveyor
overrides that for a non-square sensor.

★ No backfill and no default beyond ``false``: every existing camera keeps its entered
calibration and its behaviour is unchanged.
"""

from __future__ import annotations

from typing import Sequence

import geoalchemy2  # noqa: F401  # ★ see script.py.mako — never remove
import sqlalchemy as sa
from alembic import op

# ★ Renumbered 0019 → 0022 on integration (2026-09-04): this checkout already had
#   0019 (detection_events), 0020 (cameras) and 0021 (camera setup pipeline).
revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "image_cameras",
        sa.Column(
            "no_calibration",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column("image_cameras", sa.Column("fov_h_deg", sa.Double(), nullable=True))
    op.add_column("image_cameras", sa.Column("fov_v_deg", sa.Double(), nullable=True))
    # ★ A field of view outside (0, 180) is not a wide lens, it is a typo — and it
    #   would make tan(fov/2) zero or negative, i.e. an infinite or mirrored focal.
    op.create_check_constraint(
        "fov_sane",
        "image_cameras",
        "(fov_h_deg IS NULL OR (fov_h_deg > 0 AND fov_h_deg < 180)) AND "
        "(fov_v_deg IS NULL OR (fov_v_deg > 0 AND fov_v_deg < 180))",
    )


def downgrade() -> None:
    # ★ Refuse rather than silently discard. A camera standing on a field of view has
    #   NO entered calibration to fall back on: dropping the columns would leave a row
    #   that looks like an un-filled camera, and every LUT built from it would fail
    #   with "no intrinsics" long after the cause was removed.
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM image_cameras WHERE no_calibration) THEN "
        "RAISE EXCEPTION 'cameras using field-of-view intrinsics exist; enter a real "
        "calibration for them before downgrading'; END IF; END $$;"
    )
    # ★ THE RESOLVED NAME, NOT THE LOGICAL ONE. `create_check_constraint("fov_sane")`
    #   goes through the metadata's naming convention (`ck_%(table_name)s_...`) and
    #   lands in Postgres as `ck_image_cameras_fov_sane`; dropping "fov_sane"
    #   would raise "constraint does not exist". Verified against pg_constraint.
    op.drop_constraint("ck_image_cameras_fov_sane", "image_cameras", type_="check")
    op.drop_column("image_cameras", "fov_v_deg")
    op.drop_column("image_cameras", "fov_h_deg")
    op.drop_column("image_cameras", "no_calibration")
