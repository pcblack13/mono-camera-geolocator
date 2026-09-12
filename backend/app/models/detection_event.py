"""``detection_events`` — :class:`DetectionEvent`, one detection, durably recorded.

★ **The run's memory was a ring buffer; this table is its record.** A detection
session lives in memory (`detection_service.DetectionSession`) and its marks ring
drops the oldest past ``MAX_MARKS`` — fine for a live panel, useless as evidence.
Every detection the pipeline produces is also written here, batched from the run
thread over the sync engine, so "which cars did camera X see yesterday, and when"
is a query rather than an archaeology dig.

★ **Three attributes the product owner named (2026-08-31), spelled exactly:**
``detected_at`` — the instant of detection, timezone-aware UTC, the queryable
truth; ``detected_at_local`` — the same instant rendered in the server's LOCAL
zone with its offset, stored verbatim because "what time did that happen HERE" is
the operator's question and re-deriving it later would answer with the zone the
DB server has then, not the zone the detection happened in; ``track_id`` — the
tracker's id for the object (the ``#3`` the overlay shows), NULL for a box that
was never locked.

★ **No FK to a session table — there is none.** Sessions are in-memory by design
(a restart ends them); ``session_id`` is recorded as text so one run's rows group
together, and the row survives the session that wrote it.

★ ``lat``/``lon`` are NULLABLE: a run without a LUT still detects and counts — it
just cannot say where. The row is still evidence a car was seen.

★ **Provenance columns (0020, 2026-09-02).** ``kind`` says who saw it — this
machine's YOLO (``detection``) or an external data feed (``feed``; feeds were not
recorded before, which contradicted "this table is the record"). ``camera_id`` names
the registry row — deliberately **no FK**: removing a camera from the registry must
not erase what it saw. ``drift_status`` is the drift monitor's CONFIRMED verdict at
the instant of detection (``ok`` / ``moved`` / ``changed`` / ``degraded``,
``pending`` while a watch has no verdict yet, ``unwatched`` when nobody watched) —
a mark's coordinate is valid only while the camera has not moved, and this column
is where that claim is recorded rather than reconstructed from two logs.
``centre_offset_m`` is the opt-in ground-contact correction applied, in metres;
NULL means none was.
"""

from __future__ import annotations

from datetime import datetime

import uuid

from sqlalchemy import Boolean, CheckConstraint, DateTime, Double, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import UUIDPkMixin

__all__ = ["DetectionEvent"]


class DetectionEvent(UUIDPkMixin, Base):
    """One detected (or tracked) box on one frame of one detection run."""

    __tablename__ = "detection_events"

    #: ``detection`` (this machine's YOLO run) or ``feed`` (an external data feed).
    kind: Mapped[str] = mapped_column(
        Text, nullable=False, default="detection", server_default=text("'detection'")
    )
    #: The in-memory run (or feed) that wrote this row.
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    #: The registered camera (``cameras.id``) — no FK, see the module docstring.
    camera_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    #: What was watched: ``video:<uuid>``, a device path, or a stream URL.
    source: Mapped[str] = mapped_column(Text, nullable=False)
    #: Display name of the recording (clip filename or the source string).
    # ★ server_default matches migration 0019 exactly — `alembic check` flagged
    #   the mismatch as drift in the 2026-09-02 release verification.
    camera_name: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    #: The LUT bundle that placed the marks, when the run had one.
    lut_site: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: The tracker's id for this object — the ``#N`` the overlay shows. NULL when
    #: the box was YOLO's but no lock was taken on it.
    track_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cls_name: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[float] = mapped_column(Double, nullable=False)
    #: True = the tracker's estimate (drawn orange); False = YOLO's own sighting.
    predicted: Mapped[bool] = mapped_column(Boolean, nullable=False)

    frame_index: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Seconds since the run started (the clip clock for files).
    time_s: Mapped[float] = mapped_column(Double, nullable=False)
    #: The ground-contact pixel the map position was read from.
    u: Mapped[float | None] = mapped_column(Double, nullable=True)
    v: Mapped[float | None] = mapped_column(Double, nullable=True)
    #: NULL when the run had no LUT or the pixel fell outside mapped terrain.
    lat: Mapped[float | None] = mapped_column(Double, nullable=True)
    lon: Mapped[float | None] = mapped_column(Double, nullable=True)

    #: The instant of detection — timezone-aware, stored in UTC.
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: The same instant in the server's local zone, ISO-8601 with offset,
    #: rendered at write time (see the module docstring for why it is stored).
    detected_at_local: Mapped[str] = mapped_column(Text, nullable=False)

    #: The drift monitor's confirmed verdict at the instant of detection.
    drift_status: Mapped[str] = mapped_column(
        Text, nullable=False, default="unwatched", server_default=text("'unwatched'")
    )
    #: The drift reference whose watch said so; NULL when unwatched.
    drift_ref_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Metres the mark was pushed away from the camera (opt-in centre correction).
    centre_offset_m: Mapped[float | None] = mapped_column(Double, nullable=True)

    __table_args__ = (
        CheckConstraint("kind IN ('detection', 'feed')", name="kind"),
        CheckConstraint(
            "drift_status IN ('unwatched', 'pending', 'ok', 'moved', 'changed', 'degraded')",
            name="drift_status",
        ),
        Index("ix_detection_events_session_frame", "session_id", "frame_index"),
        Index("ix_detection_events_session_track", "session_id", "track_id"),
        Index("ix_detection_events_detected_at", "detected_at"),
        Index("ix_detection_events_camera_detected_at", "camera_id", "detected_at"),
    )
