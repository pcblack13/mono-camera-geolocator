"""gcp_reference_imagery

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-07

``gcps.reference_imagery`` — the imagery-provenance record for a map-click GCP: which
provider and cache variant the surveyor was looking at, at what zoom, which tile, the
epistemic status of the GSD/accuracy figures, whether the imagery date is known, and
whether the tile came from the local cache.

★ NULLABLE, no default and no backfill: a pre-existing GCP's imagery provenance was not
recorded at click time, and inventing it now would be a fabricated provenance — the
exact thing the column exists to prevent. NULL reads as "not recorded", honestly.
"""

from __future__ import annotations

from typing import Sequence

import geoalchemy2  # noqa: F401  # ★ see script.py.mako — never remove
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("gcps", sa.Column("reference_imagery", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("gcps", "reference_imagery")
