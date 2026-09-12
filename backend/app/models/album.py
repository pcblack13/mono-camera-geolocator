"""``albums`` + ``album_projects`` — :class:`Album` and the join table.

★★ **MANY-TO-MANY, deliberately.** An album is a user-defined *collection* of projects,
like a tag or a playlist: one project belongs to as many albums as the surveyor likes,
and one album holds as many projects as they like. This is **not** a ``projects.album_id``
one-to-many — that shape would silently make "add to album" a *move*, and the surveyor
who filed a project under both "2026 season" and "Canal survey" would find it had
quietly left the first.

★ **The two cascades are different questions with the same answer, and it matters why.**
``album_projects.album_id ON DELETE CASCADE`` — deleting an album destroys the
*memberships*, never the members: an album is a view over projects, and a view does not
own what it shows. ``album_projects.project_id ON DELETE CASCADE`` — a hard-deleted
project leaves no dangling membership behind. **Nothing in this file can delete a
project**, which is the invariant the join table exists to keep.

★ :class:`Album` carries :class:`~app.models.mixins.SoftDeleteMixin`, matching
``projects``. ``mixins`` records that §5.4 gave ``deleted_at`` to ``projects`` and
``images`` only, because everything *below* them hard-cascades; an album is not below
them — it is a second root the user names, renames and can delete by accident, and the
brief asks it to mirror ``projects``. Flagged in the report as a deliberate extension.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    Table,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.mixins import SoftDeleteMixin, TimestampMixin, UUIDPkMixin

if TYPE_CHECKING:
    from app.models.project import Project

__all__ = ["Album", "album_projects"]


#: The join. A Core :class:`~sqlalchemy.Table` rather than a mapped class: it has no
#: identity of its own — the pair ``(album_id, project_id)`` **is** the row — and the
#: repository's idempotent add is an ``INSERT … ON CONFLICT DO NOTHING``, which is Core
#: SQL either way. Giving it a surrogate ``id`` would permit two rows saying the same
#: thing, which is precisely what the composite primary key forbids.
album_projects = Table(
    "album_projects",
    Base.metadata,
    Column(
        "album_id",
        PGUUID(as_uuid=True),
        ForeignKey("albums.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "project_id",
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "added_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    PrimaryKeyConstraint("album_id", "project_id", name="pk_album_projects"),
    # ★ The PK indexes ``(album_id, project_id)`` and therefore serves "this album's
    #   projects" for free. The **reverse** lookup — "which albums is this project in?",
    #   which every project list row asks — has no leading column in that index and
    #   would be a sequential scan without this one.
    Index("ix_album_projects_project", "project_id"),
)


class Album(UUIDPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A user-defined collection of projects. Holds many; owns none."""

    __tablename__ = "albums"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: A short hex/token for UI tinting (``"#3B82F6"``, ``"amber"``). Nullable, because
    #: "no colour chosen" is a real answer and a fabricated default would make every
    #: album look deliberately coloured.
    color: Mapped[str | None] = mapped_column(Text, nullable=True)

    projects: Mapped[list[Project]] = relationship(
        secondary=album_projects,
        back_populates="albums",
        # ★ ``lazy="raise"`` like every other relationship in this package: an album
        #   list renders a project *count*, and a lazy load here would be one query per
        #   row. The repository batches it instead.
        lazy="raise",
        # ★ No cascade to the members. Deleting an album deletes the join rows (the FK's
        #   ON DELETE CASCADE does it in the database) and never a project.
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint("length(btrim(name)) > 0", name="name_nonblank"),
        CheckConstraint(
            "color IS NULL OR (length(btrim(color)) BETWEEN 1 AND 32)", name="color_short"
        ),
        # ★ Case-insensitive uniqueness over the LIVE rows only. Two albums called
        #   "Canal survey" and "canal survey" are a filing mistake, not a feature; and
        #   restricting the index to ``deleted_at IS NULL`` means deleting an album frees
        #   its name again, which is what a user who just deleted it expects.
        Index(
            "uq_albums_name_lower",
            text("lower(btrim(name))"),
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_albums_active",
            text("updated_at DESC"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )
