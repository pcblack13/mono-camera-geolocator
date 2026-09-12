"""videos_optional_project

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-27

``videos.project_id`` becomes NULLABLE. A clip uploaded to run detection or the drift
monitor on has no natural survey project; forcing one at upload time made surveyors pick
a project the clip did not belong to. The library lists every clip regardless; a frame
captured from a project-less clip asks for its project at capture time.

★ No backfill: every existing row keeps its project. Downgrade refuses if any row has
no project — silently attaching clips to a project would be a fabricated provenance.
"""

from __future__ import annotations

from typing import Sequence

import geoalchemy2  # noqa: F401  # ★ see script.py.mako — never remove
import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("videos", "project_id", existing_type=sa.dialects.postgresql.UUID(), nullable=True)


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM videos WHERE project_id IS NULL) THEN "
        "RAISE EXCEPTION 'videos without a project exist; assign or delete them before downgrading'; "
        "END IF; END $$;"
    )
    op.alter_column("videos", "project_id", existing_type=sa.dialects.postgresql.UUID(), nullable=False)
