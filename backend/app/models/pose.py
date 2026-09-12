"""``camera_poses`` — :class:`CameraPose` (CONTRACT.md §5.6).

★ SCOPE.md §4: camera pose estimation is **deferred** (ABC only). The table is created
exactly as specified regardless — §4 rule 5 — and simply holds no rows in this build.

★ **The angle conventions are written into CHECK constraints** because yaw/pitch/roll
conventions are the classic silent-disagreement bug between a CV module and a map
renderer. **The constraint is the documentation that cannot rot.**
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from geoalchemy2 import Geography
from geoalchemy2.elements import WKBElement
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Double,
    ForeignKey,
    Index,
    Integer,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import PoseMethod, pg_enum
from app.models.mixins import TimestampMixin, UUIDPkMixin

if TYPE_CHECKING:
    from app.models.image import Image
    from app.models.match import MatchResult

__all__ = ["CameraPose"]


class CameraPose(UUIDPkMixin, TimestampMixin, Base):
    """Where the photograph was taken from, and which way it was pointing.

    ★ ``yaw_deg`` here is **0 = TRUE North**. ``PoseResult.yaw_deg`` in ``ai_engine`` is
    0 = *up the window raster*. For a north-up EPSG:3857 window those coincide; for a
    rotated or UTM window they do **not**, and ``gis.pose.window_yaw_to_north_deg()``
    (§4.28) is the **only** thing permitted to convert. ``pose_service`` calls it; it
    never does frame math itself.
    """

    __tablename__ = "camera_poses"

    image_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )
    #: NULL for ``exif_gps_only`` / ``manual``.
    match_result_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("match_results.id", ondelete="CASCADE"),
        nullable=True,
    )

    position: Mapped[WKBElement] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False), nullable=False
    )
    altitude_m: Mapped[float | None] = mapped_column(Double, nullable=True)
    #: ★ 0 = North, clockwise, ``[0, 360)``.
    yaw_deg: Mapped[float | None] = mapped_column(Double, nullable=True)
    #: ★ 0 = horizon, + = up, ``[-90, 90]``.
    pitch_deg: Mapped[float | None] = mapped_column(Double, nullable=True)
    #: ★ + = clockwise, ``[-180, 180]``.
    roll_deg: Mapped[float | None] = mapped_column(Double, nullable=True)
    hfov_deg: Mapped[float | None] = mapped_column(Double, nullable=True)
    vfov_deg: Mapped[float | None] = mapped_column(Double, nullable=True)
    #: Drives the Leaflet view cone.
    footprint: Mapped[WKBElement | None] = mapped_column(
        Geography(geometry_type="POLYGON", srid=4326, spatial_index=False),
        nullable=True,
    )

    method: Mapped[PoseMethod] = mapped_column(
        pg_enum(PoseMethod, "pose_method"), nullable=False
    )
    #: **0–100.**
    confidence: Mapped[float] = mapped_column(Double, nullable=False)
    #: 9 elements, row-major, world→camera.
    rotation_matrix: Mapped[list[float] | None] = mapped_column(
        PG_ARRAY(Double, dimensions=1), nullable=True
    )
    #: 9 elements, row-major.
    intrinsics_k: Mapped[list[float] | None] = mapped_column(
        PG_ARRAY(Double, dimensions=1), nullable=True
    )
    #: ``exif|fov|vanishing_points|assumed|manual``.
    intrinsics_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    reproj_error_px: Mapped[float | None] = mapped_column(Double, nullable=True)
    inlier_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: ★ Honest error bars.
    sigma_yaw_deg: Mapped[float | None] = mapped_column(Double, nullable=True)
    sigma_pitch_deg: Mapped[float | None] = mapped_column(Double, nullable=True)
    sigma_roll_deg: Mapped[float | None] = mapped_column(Double, nullable=True)
    is_selected: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    image: Mapped[Image] = relationship(back_populates="camera_poses", lazy="raise")
    match_result: Mapped[MatchResult | None] = relationship(
        back_populates="camera_poses", lazy="raise"
    )

    __table_args__ = (
        CheckConstraint(
            "yaw_deg IS NULL OR (yaw_deg >= 0 AND yaw_deg < 360)", name="yaw"
        ),
        CheckConstraint(
            "pitch_deg IS NULL OR pitch_deg BETWEEN -90 AND 90", name="pitch"
        ),
        CheckConstraint(
            "roll_deg IS NULL OR roll_deg BETWEEN -180 AND 180", name="roll"
        ),
        CheckConstraint(
            "(hfov_deg IS NULL OR (hfov_deg > 0 AND hfov_deg < 180))"
            " AND (vfov_deg IS NULL OR (vfov_deg > 0 AND vfov_deg < 180))",
            name="fov",
        ),
        CheckConstraint("confidence BETWEEN 0 AND 100", name="confidence"),
        CheckConstraint(
            "rotation_matrix IS NULL OR array_length(rotation_matrix, 1) = 9",
            name="rotation_arity",
        ),
        CheckConstraint(
            "intrinsics_k IS NULL OR array_length(intrinsics_k, 1) = 9",
            name="intrinsics_arity",
        ),
        # ★ Zhang-plane needs K just as much as homography decomposition does; keying
        # only off the latter let the PRIMARY path write a pose with no intrinsics.
        CheckConstraint(
            "method NOT IN ('zhang_plane', 'homography_decomposition')"
            " OR intrinsics_k IS NOT NULL",
            name="decomp_needs_k",
        ),
        CheckConstraint(
            "method IN ('exif_gps_only', 'manual') OR match_result_id IS NOT NULL",
            name="method_needs_match",
        ),
        Index(
            "uq_camera_poses_image_selected",
            "image_id",
            unique=True,
            postgresql_where=text("is_selected"),
        ),
        Index("ix_camera_poses_image", "image_id", text("confidence DESC")),
        Index("ix_camera_poses_position", "position", postgresql_using="gist"),
        Index(
            "ix_camera_poses_footprint",
            "footprint",
            postgresql_using="gist",
            postgresql_where=text("footprint IS NOT NULL"),
        ),
        Index(
            "ix_camera_poses_match_result",
            "match_result_id",
            postgresql_where=text("match_result_id IS NOT NULL"),
        ),
    )
