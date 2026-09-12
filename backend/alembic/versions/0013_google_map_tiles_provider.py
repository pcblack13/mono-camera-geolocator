"""Add ``google_map_tiles`` to the ``imagery_provider`` enum.

★ WHY A MIGRATION AT ALL. ``models.enums.ImageryProvider`` and the PostgreSQL
``imagery_provider`` type are two declarations of one fact, and a contract test asserts
they are equal (and that both equal ``gis.imagery.base.PROVIDER_NAMES``). Adding the
Python member alone turns that test red and, worse, makes any INSERT naming the new
provider fail at the database with a type error at run time.

★ WHY ``ADD VALUE IF NOT EXISTS`` AND NO DOWNGRADE. PostgreSQL cannot drop a value from an
enum type — the only route is to recreate the type and rewrite every column that uses it,
which for a value that may already be persisted in ``projects.imagery_provider`` would
mean destroying rows. A downgrade that silently discarded a surveyor's provider selection
is worse than one that refuses, so this refuses.

Revision ID: 0013
Revises: 0012
"""

from __future__ import annotations

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Add the new enum value.

    ★ ``ADD VALUE`` cannot run inside a transaction block on PostgreSQL < 12, and Alembic
    wraps migrations in one. ``IF NOT EXISTS`` additionally makes this idempotent, so a
    re-run against a database that already has the value is a no-op rather than an error.
    """
    op.execute("COMMIT")
    op.execute("ALTER TYPE imagery_provider ADD VALUE IF NOT EXISTS 'google_map_tiles'")


def downgrade() -> None:
    """★ Leave the label in place — refuse only when data actually references it.

    PostgreSQL cannot drop an enum value, and an unreferenced extra label is INERT: a
    0012 database with it behaves identically to one without. So the downgrade succeeds
    (keeping the whole chain below reversible) unless a row actually persists
    ``google_map_tiles`` — a 0012-era app would misread that row, and destroying it is
    not this migration's call to make.
    """
    conn = op.get_bind()
    columns = conn.exec_driver_sql(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE udt_name = 'imagery_provider' AND table_schema = 'public'"
    ).fetchall()
    for table, column in columns:
        used = conn.exec_driver_sql(
            f'SELECT count(*) FROM "{table}" WHERE "{column}" = \'google_map_tiles\''
        ).scalar()
        if used:
            raise RuntimeError(
                f"{used} row(s) in {table}.{column} reference 'google_map_tiles'; a "
                "pre-0013 schema cannot represent them. Reassign those rows first."
            )
    # The enum label itself stays: unreferenced, it is invisible to a 0012 app.
