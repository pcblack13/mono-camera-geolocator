"""enable extensions

Revision ID: 0001
Revises:
Create Date: 2026-07-17

The three extensions the schema cannot be created without, and the one function every
table's ``updated_at`` depends on.

★ ``postgis`` is **never dropped** in ``downgrade()`` (§5.7). It owns ``spatial_ref_sys``,
and dropping it on a database with any spatial column is destructive. Removing PostGIS
is a database-lifecycle decision, not a migration.
"""

from __future__ import annotations

from typing import Sequence

import geoalchemy2  # noqa: F401  # ★ see script.py.mako — never remove
import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # postgis      — geography/geometry, ST_*, GIST support. Everything.
    # btree_gist   — lets a GIST index mix a scalar with a geometry; the exclusion and
    #                composite spatial indexes in 0009 need it.
    # pg_trgm      — gin_trgm_ops for the `name`/`filename` search indexes (§5.6).
    # ★ No pgcrypto: gen_random_uuid() is core in PG 13+ (§5.4).
    # ★ No postgis_raster: deliberately not installed (§5.6) — it drags GDAL driver
    #   configuration into the database container and has a real CVE history around
    #   out-db rasters. The heatmap is vector.
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # ★ updated_at is maintained HERE, by a trigger, not by the ORM (§5.4). A Celery
    # bulk UPDATE must not be able to skip it. The triggers themselves are attached
    # per table in 0009, once every table exists.
    #
    # `search_path = pg_catalog` pins the function's name resolution: a SECURITY
    # DEFINER-adjacent habit that costs nothing and closes the trigger-hijack class.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION tg_set_updated_at() RETURNS trigger AS $$
        BEGIN
            NEW.updated_at := now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql SET search_path = pg_catalog
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS tg_set_updated_at()")
    # ★ postgis / btree_gist / pg_trgm are NOT dropped. See the module docstring.
