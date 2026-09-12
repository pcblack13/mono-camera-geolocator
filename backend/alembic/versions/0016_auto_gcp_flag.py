"""auto_gcp_flag

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-29

``image_cameras.auto_gcp_enabled`` — has the surveyor turned on auto GCP picking for
this photograph?

★ The flag is part of the photo's SETUP, so it lives on the setup row: the toggle sits
on the image setup page next to the intrinsics it depends on. It records intent only —
the tool itself additionally requires four located GCPs before it activates, and that
count is read live from ``gcps``, never cached here (a second copy of a count is a
second chance to disagree, §5.2).

``NOT NULL DEFAULT false``: an unasked question is honestly "off", and existing rows
gain the answer they already had.
"""

from __future__ import annotations

from typing import Sequence

import geoalchemy2  # noqa: F401  # ★ see script.py.mako — never remove
import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "image_cameras",
        sa.Column(
            "auto_gcp_enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("image_cameras", "auto_gcp_enabled")
