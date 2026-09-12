"""``cameras`` — :class:`Camera`, a registered fixed camera and what it should be doing.

★ **WHY THIS TABLE EXISTS (2026-09-02).** Until now the camera registry lived in ONE
browser's ``localStorage`` (``le.cameras.v1``): a second machine saw no cameras, a
cleared browser lost them all, and a ``detection_events`` row named its camera by a
string that only ever existed client-side. The product pitch is *fixed cameras watched
over time*; that needs the server to know which cameras exist, and — the second half —
what each one is SUPPOSED to be doing, so an API restart can bring it back.

★ **``desired`` IS THE DESIRED STATE, NOT THE CURRENT ONE.** Detection sessions, drift
watches and data feeds are in-memory threads by design (a restart ends them). This
JSONB records what the operator asked for last — ``{"watch": {...} | null,
"detect": {...} | null, "feed": true|false}`` — and ``camera_service.reconcile_at_boot``
walks the table on startup and starts whatever is recorded. The routers write it
when a start or stop names a ``camera_id``; nothing here is ever inferred from what
happens to be running.

★ **Cross-field rules are CHECKs, not documentation**, mirroring the frontend's
``validateCamera``: a serial integration carries no picture (``provides = 'data'``);
a camera that provides video has a ``source``; one that provides data has a
``data_source``. A row the UI could not have created cannot be written by a script
either.

Hard delete: a camera is registry, not survey data — nothing FK-references it (the
``detection_events.camera_id`` column is deliberately unconstrained, see that model).
"""

from __future__ import annotations

import uuid  # noqa: TC003 — Mapped[] annotations are resolved at mapper time
from typing import Any

from sqlalchemy import CheckConstraint, Double, ForeignKey, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TimestampMixin, UUIDPkMixin

__all__ = ["CAMERA_CONNECTIONS", "CAMERA_PROVIDES", "DATA_ONLY_CONNECTIONS", "Camera"]

#: ``Text`` + CHECK rather than a PG enum, the ``gcps.source`` precedent: a
#: three-legged enum for a registry attribute buys nothing but a migration per value.
#: ★ Widened 2026-09-04 (0021), then NARROWED 2026-09-11 (0023) to the three things
#: that actually differ — an address on the network, a capture device on this
#: machine, a serial line. The eight kinds before it asked for exactly these three,
#: so ``stream``/``embedded`` folded into ``lan``, ``hdmi``/``bnc`` into ``usb`` and
#: ``uart`` into ``serial`` without any camera changing behaviour.
CAMERA_CONNECTIONS = ("lan", "usb", "serial")
#: The kind that carries DATA and no picture.
DATA_ONLY_CONNECTIONS = ("serial",)
CAMERA_PROVIDES = ("camera", "data", "both")


class Camera(UUIDPkMixin, TimestampMixin, Base):
    """One registered fixed camera (or data-only integration) and its desired state."""

    __tablename__ = "cameras"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    lat: Mapped[float] = mapped_column(Double, nullable=False)
    lon: Mapped[float] = mapped_column(Double, nullable=False)
    #: The video source: ``device:N`` / ``/dev/videoN``, an http(s) MJPEG URL, rtsp.
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    connection: Mapped[str] = mapped_column(
        Text, nullable=False, default="lan", server_default=text("'lan'")
    )
    provides: Mapped[str] = mapped_column(
        Text, nullable=False, default="camera", server_default=text("'camera'")
    )
    #: ``serial://<port>?baud=…`` or an http(s) line feed — see ``live_data_service``.
    data_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    heading_deg: Mapped[float | None] = mapped_column(Double, nullable=True)
    fov_deg: Mapped[float | None] = mapped_column(Double, nullable=True)
    fps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tags: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    #: The LUT bundle the operator last applied to this camera (a library site name).
    lut_site: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The desired state — see the module docstring.
    desired: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # ── the setup pipeline (0021, 2026-09-04) ───────────────────────────────
    #: The camera's BACKING PROJECT — where its DEM, its frame and its control
    #: points live, so the lookup table is built by the same machinery as any
    #: photograph's. SET NULL: a camera outlives a removed project and says so.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    #: The frame chosen from this camera — the photograph the control points sit on.
    frame_image_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("images.id", ondelete="SET NULL"), nullable=True
    )
    #: Optional intrinsics / mast / tilt entered on the camera itself
    #: (``schemas.camera.CameraCalibration``); a re-captured frame inherits them.
    calibration: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        CheckConstraint("length(btrim(name)) > 0", name="name_nonblank"),
        CheckConstraint("lat >= -90 AND lat <= 90", name="lat_range"),
        CheckConstraint("lon >= -180 AND lon <= 180", name="lon_range"),
        CheckConstraint(
            "connection IN ('lan', 'usb', 'serial')",
            name="connection_known",
        ),
        CheckConstraint("provides IN ('camera', 'data', 'both')", name="provides_known"),
        # a serial / UART line carries no picture
        CheckConstraint("connection <> 'serial' OR provides = 'data'", name="serial_is_data"),
        # video needs a source; data needs a data source
        CheckConstraint(
            "provides = 'data' OR (source IS NOT NULL AND length(btrim(source)) > 0)",
            name="video_has_source",
        ),
        CheckConstraint(
            "provides = 'camera' OR (data_source IS NOT NULL AND length(btrim(data_source)) > 0)",
            name="data_has_source",
        ),
        CheckConstraint(
            "heading_deg IS NULL OR (heading_deg >= 0 AND heading_deg <= 360)",
            name="heading_range",
        ),
        CheckConstraint("fov_deg IS NULL OR (fov_deg > 0 AND fov_deg <= 180)", name="fov_range"),
        CheckConstraint("fps IS NULL OR (fps >= 1 AND fps <= 30)", name="fps_range"),
        Index("ix_cameras_name", "name"),
    )
