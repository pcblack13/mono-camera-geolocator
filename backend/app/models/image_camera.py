"""``image_cameras`` — :class:`ImageCamera`, the photograph's manually entered camera.

★ **One row per image, keyed on ``image_id``.** The workflow is one *photograph* at a
time: each photo a surveyor brings in may come from a different station, a different
mast height, a different aim — so the calibration (OpenCV pinhole + Brown–Conrady
distortion), the ground position, the mast offset and the tilt below horizontal are
attributes of the **image**, entered on its setup page. (They began life per-project;
the product moved to per-photo setup, and the ``project_cameras`` table was replaced
by this one in migration 0015.)

This is still not a row in ``camera_poses``: that table is per-image too, but holds
*match-derived estimates* (deferred, empty in this build). This one holds what the
surveyor **typed** — reference data, never a solver's output.

★ **Every field is nullable, deliberately.** Setup is incremental: the calibration CSV
may arrive before the position is known. A NULL is "not entered yet" — never coerced
to ``0``, because ``fx = 0`` and "fx unknown" are different answers (L12).

★ **Vocabulary bridge.** ``camera_poses`` speaks ``pitch_deg`` (0 = horizon, + = up).
The field tool speaks *tilt below horizontal* (+ = aimed down). This table stores
``tilt_deg`` in the field-tool convention; the relation is ``tilt_deg = -pitch_deg``.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from geoalchemy2 import Geography
from geoalchemy2.elements import WKBElement
from sqlalchemy import Boolean, CheckConstraint, Double, ForeignKey, Integer, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.image import Image

__all__ = ["ImageCamera"]


class ImageCamera(TimestampMixin, Base):
    """The manually entered camera for one photograph: intrinsics + position + tilt."""

    __tablename__ = "image_cameras"

    #: ★ The PK **is** the FK — 1:1 with ``images``, unrepresentable to duplicate.
    image_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("images.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # ── intrinsics — OpenCV pinhole K + Brown–Conrady distortion ──────────────
    #: Focal lengths in **pixels** (not mm — the EXIF mm reading lives on ``images``).
    fx: Mapped[float | None] = mapped_column(Double, nullable=True)
    fy: Mapped[float | None] = mapped_column(Double, nullable=True)
    #: Principal point in pixels; the UI defaults it to the image centre.
    cx: Mapped[float | None] = mapped_column(Double, nullable=True)
    cy: Mapped[float | None] = mapped_column(Double, nullable=True)
    #: ★ Stored individually but *consumed* in the OpenCV vector order
    #: ``[k1, k2, p1, p2, k3]`` — radial, radial, tangential, tangential, radial.
    k1: Mapped[float | None] = mapped_column(Double, nullable=True)
    k2: Mapped[float | None] = mapped_column(Double, nullable=True)
    p1: Mapped[float | None] = mapped_column(Double, nullable=True)
    p2: Mapped[float | None] = mapped_column(Double, nullable=True)
    k3: Mapped[float | None] = mapped_column(Double, nullable=True)
    #: The calibration's frame size in pixels. Metadata, not geometry: kept so a
    #: mismatch against the photograph can be *flagged*, never silently rescaled.
    img_w: Mapped[int | None] = mapped_column(Integer, nullable=True)
    img_h: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # >>> GEO-DRIFT-UPDATE C2 BEGIN — a calibration is optional >>>
    #: ★ THE PROVENANCE, NOT A CONVENIENCE. When set, ``fx..cy`` are DERIVED from
    #: the field of view at build time rather than measured, which assumes a
    #: centred principal point and a perfect pinhole. Writing derived numbers into
    #: ``fx..cy`` and leaving it at that would make a guess indistinguishable from
    #: a measurement; this flag is what keeps them apart, and it travels into the
    #: LUT manifest and every drift reference built on it.
    no_calibration: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    #: The camera's TRUE horizontal angle of view, degrees. Not a spec sheet's
    #: DIAGONAL figure (always larger), and not EXIF's rounded 35 mm focal.
    fov_h_deg: Mapped[float | None] = mapped_column(Double, nullable=True)
    #: NULL means SQUARE PIXELS: fy = fx, and the vertical angle is whatever that
    #: implies. Stored only to override that for a non-square sensor.
    fov_v_deg: Mapped[float | None] = mapped_column(Double, nullable=True)
    # <<< GEO-DRIFT-UPDATE C2 END <<<

    # ── position — WGS84 ground point + mast height ───────────────────────────
    #: Where the camera stood, EPSG:4326. Projected X/Y/Z are *derived* from this
    #: plus the project DEM at solve time — storing both would be two chances to
    #: disagree (§5.2).
    position: Mapped[WKBElement | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False),
        nullable=True,
    )
    #: Metres the optical centre sat **above the bare-earth DEM** at ``position`` —
    #: the mast/tower height. Effective camera Z = DEM(position) + this.
    mast_offset_m: Mapped[float | None] = mapped_column(Double, nullable=True)

    # ── orientation ───────────────────────────────────────────────────────────
    #: ★ Degrees below horizontal, **+ = aimed down** (``tilt_deg = -pitch_deg``).
    tilt_deg: Mapped[float | None] = mapped_column(Double, nullable=True)

    # ── auto GCP picking ──────────────────────────────────────────────────────
    #: ★ INTENT ONLY. The surveyor turned the tool on for this photograph; it
    #: additionally requires four located GCPs before it activates, and that count
    #: is read live from ``gcps`` — never cached here (§5.2).
    auto_gcp_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    image: Mapped[Image] = relationship(back_populates="camera", lazy="raise")

    __table_args__ = (
        # ★ A zero or negative focal length is not a calibration, it is a typo; NULL
        #   ("not entered") remains a legal answer.
        CheckConstraint(
            "(fx IS NULL OR fx > 0) AND (fy IS NULL OR fy > 0)", name="focal_positive"
        ),
        CheckConstraint(
            "(img_w IS NULL OR img_w > 0) AND (img_h IS NULL OR img_h > 0)",
            name="dims_positive",
        ),
        # ★ GEO-DRIFT-UPDATE C2 — a field of view outside (0, 180) is a typo, not a
        #   wide lens: tan(fov/2) would be zero or negative, i.e. an infinite or
        #   mirrored focal length.
        CheckConstraint(
            "(fov_h_deg IS NULL OR (fov_h_deg > 0 AND fov_h_deg < 180)) AND "
            "(fov_v_deg IS NULL OR (fov_v_deg > 0 AND fov_v_deg < 180))",
            name="fov_sane",
        ),
        CheckConstraint(
            "tilt_deg IS NULL OR tilt_deg BETWEEN -90 AND 90", name="tilt_range"
        ),
    )
