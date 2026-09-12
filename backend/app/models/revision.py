"""``project_revisions`` — :class:`ProjectRevision` (CONTRACT.md §5.6)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.mixins import UUIDPkMixin

if TYPE_CHECKING:
    from app.models.annotation import AnnotationVersion
    from app.models.project import Project

__all__ = ["ProjectRevision"]


class ProjectRevision(UUIDPkMixin, Base):
    """A checkpoint or plain marker in a project's annotation history.

    The versioning design is a **hybrid event-log + rolling snapshot** (§5.6): events in
    ``annotation_versions`` carry both ``before`` and ``after`` — which is what makes
    undo O(1), a single indexed row read with no fold — and a checkpoint every
    ``LE_CHECKPOINT_EVERY_N_EVENTS`` bounds reconstruction.
    """

    __tablename__ = "project_revisions"

    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: Monotonic within the project; allocated from ``projects.current_revision_seq``.
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_checkpoint: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    #: ★ Populated **iff** ``is_checkpoint``.
    #: ``{"schema_version": 1, "images": {"<uuid>": [...]}}``
    snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    annotation_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    #: Events since the previous checkpoint.
    event_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    #: ``project_revisions`` is append-only: it has a ``created_at`` but no
    #: ``updated_at``, so it takes the column rather than :class:`TimestampMixin`.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    project: Mapped[Project] = relationship(back_populates="revisions", lazy="raise")
    annotation_versions: Mapped[list[AnnotationVersion]] = relationship(
        back_populates="revision", lazy="raise"
    )

    __table_args__ = (
        CheckConstraint(
            "(is_checkpoint) = (snapshot IS NOT NULL)",
            name="snapshot_iff_checkpoint",
        ),
        CheckConstraint("seq > 0", name="seq_pos"),
        CheckConstraint("annotation_count >= 0", name="annotation_count_nonneg"),
        CheckConstraint("event_count >= 0", name="event_count_nonneg"),
        UniqueConstraint("project_id", "seq", name="uq_project_revisions_project_seq"),
        Index("ix_project_revisions_project_seq", "project_id", text("seq DESC")),
        # ★ "nearest preceding checkpoint" in one backward index scan.
        Index(
            "ix_project_revisions_checkpoints",
            "project_id",
            text("seq DESC"),
            postgresql_where=text("is_checkpoint"),
        ),
        Index(
            "ix_project_revisions_snapshot",
            "snapshot",
            postgresql_using="gin",
            postgresql_ops={"snapshot": "jsonb_path_ops"},
            postgresql_where=text("is_checkpoint"),
        ),
    )
