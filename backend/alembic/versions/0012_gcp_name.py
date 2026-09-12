"""Add a free-text ``name`` to GCPs.

A GCP already has ``code`` (a constrained Point ID, ``[A-Za-z0-9_-]{1,32}``). ``name`` is the
surveyor's own free-text label for the point — the "Name" column in the table — set when a
GCP is placed with no landmark to inherit a name from, and editable afterwards. Nullable; no
constraint beyond a sane length cap enforced at the API.
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("gcps", sa.Column("name", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("gcps", "name")
