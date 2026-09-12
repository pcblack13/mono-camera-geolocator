"""``videos`` — :class:`Video`, a field VIDEO uploaded as a FRAME SOURCE.

★ **A video is not imagery; it is a source of imagery.** The surveyor uploads a field
video, scrubs it in the browser, and at a chosen second *captures that frame* — the frame
becomes a normal ``images`` row (with ``source_video_id`` / ``source_video_time_s`` set)
and flows into the existing annotation/GCP pipeline unchanged. So this table carries only
the container's facts — duration, fps, dimensions, codec — and **no geometry**: a video
has no footprint, no GCPs, no bounds. Everything geographic happens on the captured frame.

The shape deliberately mirrors :class:`~app.models.image.Image`'s file half: the same
``UUIDPkMixin``/``TimestampMixin``/``SoftDeleteMixin``, the same server-controlled
``storage_path`` (never serialised), the same ``checksum_sha256`` + ``size_bytes``, the
same soft-delete-frees-the-slot discipline.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CHAR,
    CheckConstraint,
    Double,
    ForeignKey,
    Index,
    Integer,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.mixins import SoftDeleteMixin, TimestampMixin, UUIDPkMixin

if TYPE_CHECKING:
    from app.models.project import Project

__all__ = ["Video"]


class Video(UUIDPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    """An uploaded field video — a source from which frames become normal images."""

    __tablename__ = "videos"

    #: ★ NULLABLE (0018): a clip uploaded for detection or drift work need not belong
    #: to a survey project. It lives in the library; a frame captured from it asks for
    #: the project at capture time (``VideoFrameCapture.project_id``).
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
    )

    #: Original client filename — **untrusted**, display only.
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    #: Server-controlled. ★ **NEVER serialised to the wire.**
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)

    #: Read synchronously at upload by the OpenCV/FFMPEG extractor (``read_metadata``).
    duration_s: Mapped[float] = mapped_column(Double, nullable=False)
    fps: Mapped[float] = mapped_column(Double, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    #: ``CAP_PROP_FRAME_COUNT`` is an estimate for some containers — nullable.
    frame_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: FourCC, e.g. ``avc1`` / ``mp4v``. Nullable — not every container reports it.
    codec: Mapped[str | None] = mapped_column(Text, nullable=True)

    project: Mapped[Project | None] = relationship(lazy="raise")

    __table_args__ = (
        CheckConstraint("width > 0 AND height > 0", name="dims"),
        CheckConstraint("size_bytes > 0", name="size"),
        CheckConstraint("duration_s >= 0", name="duration_nonneg"),
        CheckConstraint("fps >= 0", name="fps_nonneg"),
        CheckConstraint(
            r"checksum_sha256 ~ '^[0-9a-f]{64}$'", name="checksum_hex"
        ),
        Index("uq_videos_storage_path", "storage_path", unique=True),
        Index(
            "ix_videos_project_created",
            "project_id",
            text("created_at DESC"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )
