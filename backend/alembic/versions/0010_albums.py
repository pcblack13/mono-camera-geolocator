"""albums

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-20

``albums`` and ``album_projects`` — a user-defined, **many-to-many** collection of
projects.

★ Unlike 0003–0008, this revision creates its own indexes and its own ``updated_at``
trigger rather than deferring them to a later "indexes" migration. 0009 exists because
the *original* access-path design was worth reviewing as one set; a feature added after
it has nowhere to defer to, and splitting one feature across two future revisions would
leave a released schema with an unindexed reverse lookup in between.

★ **Deleting an album never deletes a project.** Both FKs on the join table are
``ON DELETE CASCADE``, and what they cascade to is the *membership row* — the join table
is the only thing either side owns jointly. There is no FK anywhere that points from a
project at an album, so there is no path by which an album deletion could reach one.
"""

from __future__ import annotations

from typing import Sequence

import geoalchemy2  # noqa: F401  # ★ see script.py.mako — never remove
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "albums",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        # ★ A short hex/token for UI tinting. NULL = "no colour chosen", which is a real
        #   answer; a default would make every album look deliberately coloured.
        sa.Column("color", sa.Text(), nullable=True),
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
        # ★ Soft delete, matching ``projects``: an album is a second user-named root,
        #   not a child of one, and deleting one by accident must be recoverable.
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_albums_name_nonblank"),
        sa.CheckConstraint(
            "color IS NULL OR (length(btrim(color)) BETWEEN 1 AND 32)",
            name="ck_albums_color_short",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_albums"),
    )

    op.create_table(
        "album_projects",
        sa.Column("album_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["album_id"],
            ["albums.id"],
            name="fk_album_projects_album_id_albums",
            ondelete="CASCADE",
        ),
        # ★ CASCADE on the membership, never on the member. There is no FK from
        #   ``projects`` to ``albums``, so an album deletion has no path to a project.
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_album_projects_project_id_projects",
            ondelete="CASCADE",
        ),
        # ★ The pair IS the row. A composite PK makes "added twice" unrepresentable, so
        #   the idempotent add is an ON CONFLICT DO NOTHING rather than a read-then-write
        #   race.
        sa.PrimaryKeyConstraint("album_id", "project_id", name="pk_album_projects"),
    )

    # ★ The PK already serves "this album's projects" (album_id leads it). The reverse
    #   lookup — "which albums is this project in?", asked once per project list page —
    #   has no leading column there and would be a sequential scan.
    op.execute("CREATE INDEX ix_album_projects_project ON album_projects (project_id)")

    # ★ Case-insensitive uniqueness over LIVE album names only. Two albums differing
    #   only in case are a filing mistake; and scoping the index to live rows means
    #   deleting an album frees its name again, which is what the person who just
    #   deleted it expects.
    op.execute(
        "CREATE UNIQUE INDEX uq_albums_name_lower ON albums (lower(btrim(name)))"
        " WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_albums_active ON albums (updated_at DESC)"
        " WHERE deleted_at IS NULL"
    )

    # ★ ``updated_at`` is maintained by the trigger, not the ORM (§5.4) — the same
    #   ``tg_set_updated_at()`` created in 0001 and attached per table in 0009.
    #   ``album_projects`` gets none: it has no ``updated_at``, because a membership is
    #   created and destroyed, never edited.
    op.execute(
        "CREATE TRIGGER tg_albums_set_updated_at BEFORE UPDATE ON albums"
        " FOR EACH ROW EXECUTE FUNCTION tg_set_updated_at()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS tg_albums_set_updated_at ON albums")
    op.execute("DROP INDEX IF EXISTS ix_albums_active")
    op.execute("DROP INDEX IF EXISTS uq_albums_name_lower")
    op.execute("DROP INDEX IF EXISTS ix_album_projects_project")
    op.drop_table("album_projects")
    op.drop_table("albums")
