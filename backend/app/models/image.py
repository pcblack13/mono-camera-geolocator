"""``images`` — :class:`Image` (CONTRACT.md §5.6)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from geoalchemy2 import Geography
from geoalchemy2.elements import WKBElement
from sqlalchemy import (
    BigInteger,
    Boolean,
    CHAR,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import ImageStatus, pg_enum
from app.models.mixins import SoftDeleteMixin, TimestampMixin, UUIDPkMixin

if TYPE_CHECKING:
    from app.models.annotation import Annotation, AnnotationVersion
    from app.models.export import Export
    from app.models.gcp import GCP
    from app.models.heatmap import ConfidenceHeatmap
    from app.models.image_camera import ImageCamera
    from app.models.job import AuxJob, BatchJobItem, MatchJob
    from app.models.pose import CameraPose
    from app.models.project import Project
    from app.models.semantic import SemanticFeature
    from app.models.suggestion import LandmarkSuggestion

__all__ = ["Image"]


class Image(UUIDPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    """An uploaded photograph or GeoTIFF, and everything ingest discovered about it.

    ★ **Why full EXIF as JSONB *and* promoted columns.** The promoted columns are what
    the pipeline reads on every job — fixed columns, real types, real indexes. The
    ``exif`` JSONB is the **forensic record**: a surveying deliverable may be challenged
    years later and "what did the camera actually report" must be answerable
    byte-for-byte. The promoted columns are formally a *cache*. **If they ever disagree,
    ``exif`` wins and it is an ingest bug.**
    """

    __tablename__ = "images"

    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: Original client filename — **untrusted**.
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    #: Server-controlled. ★ **NEVER serialised to the wire.**
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    thumbnail_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)

    status: Mapped[ImageStatus] = mapped_column(
        pg_enum(ImageStatus, "image_status"),
        nullable=False,
        server_default=text("'uploaded'::image_status"),
    )

    #: ★ **Post EXIF-orientation normalisation** — the stored orientation is the only
    #: orientation, and every pixel coordinate in the system refers to it (§5.2).
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    band_count: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("3")
    )
    #: EXIF XResolution — informational only.
    resolution_dpi: Mapped[float | None] = mapped_column(Double, nullable=True)
    #: GeoTIFF only.
    gsd_m: Mapped[float | None] = mapped_column(Double, nullable=True)

    #: ★ FULL EXIF, **verbatim**. The forensic record.
    exif: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    exif_gps: Mapped[WKBElement | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False), nullable=True
    )
    exif_gps_altitude_m: Mapped[float | None] = mapped_column(Double, nullable=True)
    #: GPSImgDirection; seeds the pose prior. ``[0, 360)``.
    exif_gps_direction_deg: Mapped[float | None] = mapped_column(Double, nullable=True)
    #: GPSHPositioningError → search radius inflation.
    exif_gps_hpe_m: Mapped[float | None] = mapped_column(Double, nullable=True)
    #: ``exif`` | ``manual`` | ``NULL``.
    gps_source: Mapped[str | None] = mapped_column(Text, nullable=True)

    camera_make: Mapped[str | None] = mapped_column(Text, nullable=True)
    camera_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    lens_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    focal_length_mm: Mapped[float | None] = mapped_column(Double, nullable=True)
    focal_length_35mm: Mapped[float | None] = mapped_column(Double, nullable=True)
    #: ★ Resolved from a bundled camera DB on ``(make, model)`` — required for ``K``.
    sensor_width_mm: Mapped[float | None] = mapped_column(Double, nullable=True)
    f_number: Mapped[float | None] = mapped_column(Double, nullable=True)

    #: ★ A property **discovered** at ingest, never a declared type.
    is_geotiff: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    #: The **NATIVE** CRS of the GeoTIFF.
    crs_epsg: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Full WKT2, for exotic CRS.
    crs_wkt: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Footprint, **reprojected at ingest** — the DB performs no reprojection on write.
    bounds: Mapped[WKBElement | None] = mapped_column(
        Geography(geometry_type="POLYGON", srid=4326, spatial_index=False),
        nullable=True,
    )
    #: 6 elements, GDAL order, in the **NATIVE** CRS.
    geotransform: Mapped[list[float] | None] = mapped_column(
        PG_ARRAY(Double, dimensions=1), nullable=True
    )
    nodata_value: Mapped[float | None] = mapped_column(Double, nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: ★ attribute ``meta``, column ``metadata``.
    meta: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    #: EXIF DateTimeOriginal.
    captured_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    #: ★ Provenance for a CAPTURED FRAME. When this image is a frame captured from a
    #: video (``POST /videos/{id}/frames``), these record which video and at what second
    #: it came from. Both NULL for a normally-uploaded photo. Added by the VIDEO feature
    #: (migration 0011); ``ON DELETE SET NULL`` so deleting a video orphans but never
    #: destroys the frames a surveyor already annotated. Defaults are None so every
    #: existing ``Image(...)`` construction site is unaffected.
    source_video_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("videos.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_video_time_s: Mapped[float | None] = mapped_column(Double, nullable=True)

    project: Mapped[Project] = relationship(back_populates="images", lazy="raise")
    annotations: Mapped[list[Annotation]] = relationship(
        back_populates="image",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    annotation_versions: Mapped[list[AnnotationVersion]] = relationship(
        back_populates="image",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    match_jobs: Mapped[list[MatchJob]] = relationship(
        back_populates="image",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    aux_jobs: Mapped[list[AuxJob]] = relationship(
        back_populates="image",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    batch_job_items: Mapped[list[BatchJobItem]] = relationship(
        back_populates="image",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    gcps: Mapped[list[GCP]] = relationship(
        back_populates="image",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    camera_poses: Mapped[list[CameraPose]] = relationship(
        back_populates="image",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    #: ★ 1:1 — the manually ENTERED camera for this photograph (intrinsics, position,
    #: tilt), captured on its setup page. Distinct from ``camera_poses``: that list is
    #: match-derived estimates (deferred); this row is what the surveyor typed.
    camera: Mapped[ImageCamera | None] = relationship(
        back_populates="image",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    heatmaps: Mapped[list[ConfidenceHeatmap]] = relationship(
        back_populates="image",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    semantic_features: Mapped[list[SemanticFeature]] = relationship(
        back_populates="image",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    landmark_suggestions: Mapped[list[LandmarkSuggestion]] = relationship(
        back_populates="image",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    exports: Mapped[list[Export]] = relationship(
        back_populates="image",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )

    __table_args__ = (
        CheckConstraint("width > 0 AND height > 0", name="dims"),
        CheckConstraint("size_bytes > 0", name="size"),
        CheckConstraint("band_count > 0", name="band_count"),
        CheckConstraint(
            r"checksum_sha256 ~ '^[0-9a-f]{64}$'", name="checksum_hex"
        ),
        # ★ A GeoTIFF is only usable if it carries the FULL georeferencing triple.
        # Half-georeferenced is worse than not georeferenced: it looks trustworthy.
        CheckConstraint(
            "NOT is_geotiff OR ("
            " crs_epsg IS NOT NULL"
            " AND bounds IS NOT NULL"
            " AND geotransform IS NOT NULL"
            " AND array_length(geotransform, 1) = 6)",
            name="geotiff_complete",
        ),
        CheckConstraint(
            "geotransform IS NULL OR array_length(geotransform, 1) = 6",
            name="geotransform_arity",
        ),
        CheckConstraint(
            "exif_gps_direction_deg IS NULL"
            " OR (exif_gps_direction_deg >= 0 AND exif_gps_direction_deg < 360)",
            name="gps_direction_range",
        ),
        CheckConstraint(
            "gps_source IS NULL OR gps_source IN ('exif', 'manual')",
            name="gps_source",
        ),
        Index("uq_images_storage_path", "storage_path", unique=True),
        Index(
            "uq_images_project_checksum",
            "project_id",
            "checksum_sha256",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_images_project_uploaded",
            "project_id",
            text("uploaded_at DESC"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_images_filename_trgm",
            "filename",
            postgresql_using="gin",
            postgresql_ops={"filename": "gin_trgm_ops"},
        ),
        Index(
            "ix_images_exif_gps",
            "exif_gps",
            postgresql_using="gist",
            postgresql_where=text("exif_gps IS NOT NULL"),
        ),
        Index(
            "ix_images_bounds",
            "bounds",
            postgresql_using="gist",
            postgresql_where=text("bounds IS NOT NULL"),
        ),
        Index(
            "ix_images_exif_gin",
            "exif",
            postgresql_using="gin",
            postgresql_ops={"exif": "jsonb_path_ops"},
        ),
        Index(
            "ix_images_camera",
            "camera_make",
            "camera_model",
            postgresql_where=text("camera_make IS NOT NULL"),
        ),
        Index(
            "ix_images_status",
            "status",
            postgresql_where=text("status <> 'ready'"),
        ),
        # ★ "which frames came from this video?" — the reverse lookup a video detail page
        #   asks, and the scan the FK would otherwise be on delete. Partial: almost every
        #   image is a normal upload with a NULL source.
        Index(
            "ix_images_source_video",
            "source_video_id",
            postgresql_where=text("source_video_id IS NOT NULL"),
        ),
    )
