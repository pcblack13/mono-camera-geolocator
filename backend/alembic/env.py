"""Alembic environment (CONTRACT.md §5.7).

Four things this file exists to get right, each of which is a known way to lose a
PostGIS schema:

1. **``target_metadata`` is ``Base.metadata`` reached through ``app.models``**, never
   through an individual module. ``app/models/__init__.py`` imports all seventeen; an
   unimported model module autogenerates to an **empty diff**, silently (§5.5).
2. **``include_object`` excludes PostGIS's own tables.** ``spatial_ref_sys`` et al. are
   owned by the extension. Without this, the first ``--autogenerate`` proposes dropping
   ``spatial_ref_sys`` — 8500 rows the entire spatial stack depends on.
3. **GeoAlchemy2's alembic helpers are installed** (``include_object``, ``render_item``,
   ``writer``): they teach Alembic to render ``geoalchemy2.types.Geography`` instead of
   ``NullType``, and to drop the implicit spatial indexes/columns PostGIS manages.
   ``include_object`` below delegates to GeoAlchemy2's after applying our own exclusions.
4. **The naming convention is re-applied here.** It lives on ``Base.metadata`` already;
   Alembic compares against the *database's* reflected names, and without the
   convention on the migration context every autogenerate proposes renaming every
   constraint it did not name itself.

The URL comes from ``Settings`` (§9.3 names ``alembic/env`` as the consumer of
``LE_DATABASE_URL`` / ``LE_MIGRATION_DATABASE_URL``), which has a working default and
never raises on an empty environment (L10). ``alembic.ini`` deliberately carries no
``sqlalchemy.url``: a URL there is a credential in a committed file and a second source
of truth for the one thing the whole app must agree on.
"""

from __future__ import annotations

import asyncio
import sys
from logging.config import fileConfig
from typing import Any

# ★ WINDOWS: async psycopg refuses the Proactor loop — Python's DEFAULT loop there
#   since 3.8 — with "Psycopg cannot use the 'ProactorEventLoop' to run in async
#   mode". This killed EVERY Windows desktop boot at the migrations step (the 1.2.3
#   installer's splash error). The selector policy must be set BEFORE asyncio.run()
#   below creates the loop. The API process has the same need — app/serve.py.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from alembic import context
from geoalchemy2 import alembic_helpers
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import Settings
from app.models import Base, NAMING_CONVENTION

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

#: ★ Owned by the PostGIS / topology extensions, not by us. Alembic reflects them and,
#: finding no model, proposes dropping them. ``spatial_ref_sys`` alone is 8500 rows the
#: entire spatial stack reads on every ``ST_Transform``.
EXCLUDED_TABLES: frozenset[str] = frozenset(
    {
        "spatial_ref_sys",
        "geography_columns",
        "geometry_columns",
        "raster_columns",
        "raster_overviews",
        "topology",
        "layer",
    }
)


def include_object(
    obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any
) -> bool:
    """Exclude the extension-owned objects from autogenerate (§5.7)."""
    if type_ == "table" and name in EXCLUDED_TABLES:
        return False
    if type_ == "column" and getattr(obj.table, "name", None) in EXCLUDED_TABLES:
        return False
    # GeoAlchemy2 knows which indexes/columns PostGIS manages behind our back.
    return bool(alembic_helpers.include_object(obj, name, type_, reflected, compare_to))


def _migration_url() -> str:
    """The URL to migrate against.

    ``LE_MIGRATION_DATABASE_URL`` exists so production can migrate as a distinct,
    higher-privileged role than the one the API runs as; ``Settings`` resolves it to
    ``database_url`` when unset (§9.3).
    """
    return Settings().migration_database_url


def _compare_type(context, inspected_column, metadata_column, inspected_type, metadata_type):
    """Type comparison: default rules, EXCEPT Geometry-vs-Geometry is never a diff.

    ★ GeoAlchemy2's reflection decorates Geometry with ``_spatial_index_reflected`` and
    drops/renames kwargs (``srid=0`` / ``spatial_index=False`` on the pixel-space
    columns), so alembic's default comparator reports a ``modify_type`` on columns that
    are byte-for-byte what the models declare — `alembic check` then fails on drift
    that does not exist. Real geometry re-typing goes through a hand-written migration
    anyway; autogenerate has never been able to emit a correct one for PostGIS.
    """
    from geoalchemy2 import Geometry  # noqa: PLC0415 — alembic-only path

    if isinstance(inspected_type, Geometry) and isinstance(metadata_type, Geometry):
        return False  # "not different"
    return None  # fall back to alembic's default comparison


def _context_kwargs() -> dict[str, Any]:
    """The options shared by the offline and online paths — declared once.

    Two configurations of one migration context is two migration contexts, and the one
    that drifts is always the one nobody runs.
    """
    return {
        "target_metadata": target_metadata,
        # `include_object` already chains to GeoAlchemy2's own filter. GeoAlchemy2
        # exposes no `include_name`; there is nothing further to install here.
        "include_object": include_object,
        "render_item": alembic_helpers.render_item,
        "process_revision_directives": alembic_helpers.writer,
        "compare_type": _compare_type,
        "compare_server_default": True,
        # ★ Per-migration transactions: 0002 creates types that 0003 references. A
        # single wrapping transaction would also make a failed migration roll back a
        # successful earlier one in the same `upgrade head`.
        "transaction_per_migration": True,
        "version_table_schema": target_metadata.schema,
    }


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a DBAPI connection (``alembic upgrade --sql``)."""
    context.configure(
        url=_migration_url(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_context_kwargs(),
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run the migrations on an already-open sync-style connection."""
    connection.dialect.ischema_names["geometry"] = alembic_helpers.Geometry
    connection.dialect.ischema_names["geography"] = alembic_helpers.Geography
    context.configure(connection=connection, **_context_kwargs())
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Open the async engine and run the migrations inside it."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _migration_url()
    connectable = async_engine_from_config(
        section, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for a live migration.

    The app is async end to end and ``LE_DATABASE_URL`` names an async driver
    (``postgresql+psycopg``), so the engine here is async too and the (synchronous)
    Alembic body runs inside ``connection.run_sync``. Building a second, sync URL by
    string surgery would be one more place for the two to disagree.
    """
    asyncio.run(run_async_migrations())


# The naming convention must be on the metadata Alembic compares with; it is set in
# `models/base.py`, and this assertion is here because a silent mismatch shows up only
# as a churn of rename operations in a much later autogenerate.
assert target_metadata.naming_convention == NAMING_CONVENTION

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
