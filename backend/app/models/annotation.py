"""``annotations`` + ``annotation_versions`` (CONTRACT.md §5.6).

**One table for all three geometry types.** Point/polyline/polygon annotations are the
same entity with the same lifecycle, versioning, ordering, ``kind`` vocabulary and
consumers. Three tables would triple the versioning machinery, force ``UNION ALL`` on
every canvas load, and make ``gcps.landmark_id`` inexpressible — a GCP can derive from a
polygon's corner as easily as from a point. ``ck_annotations_geom_type_match`` is the
guard that makes the single-table design safe.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from geoalchemy2 import Geometry
from geoalchemy2.elements import WKBElement
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import AnnotationGeomType, AnnotationKind, AnnotationOp, pg_enum
from app.models.mixins import TimestampMixin, UUIDPkMixin

if TYPE_CHECKING:
    from app.models.gcp import GCP
    from app.models.image import Image
    from app.models.revision import ProjectRevision

__all__ = ["Annotation", "AnnotationVersion"]


class Annotation(UUIDPkMixin, TimestampMixin, Base):
    """A landmark the surveyor drew on the photograph, in **image pixel space**.

    ★ ``pixel_x``/``pixel_y`` are the **representative point of the annotation, whatever
    its type**, computed server-side at write time: identical to the vertex for points,
    ``ST_PointOnSurface`` for polygons, midpoint-along-arc for polylines. **Derived
    server-side, never accepted from the client** — accepting them would let the pair
    drift from ``pixel_geom``, and ``pixel_geom`` is what the label renderer and the GCP
    deriver read.
    """

    __tablename__ = "annotations"

    image_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[AnnotationKind] = mapped_column(
        pg_enum(AnnotationKind, "annotation_kind"),
        nullable=False,
        server_default=text("'generic'::annotation_kind"),
    )
    geom_type: Mapped[AnnotationGeomType] = mapped_column(
        pg_enum(AnnotationGeomType, "annotation_geom_type"), nullable=False
    )

    pixel_x: Mapped[float] = mapped_column(Double, nullable=False)
    pixel_y: Mapped[float] = mapped_column(Double, nullable=False)
    #: ★ The authoritative geometry. PIXELS, y-**DOWN**, origin top-left, SRID 0.
    #: PostGIS *refuses* ``ST_Transform`` on SRID 0, which is what makes invariant I1
    #: mechanical rather than aspirational.
    pixel_geom: Mapped[WKBElement] = mapped_column(
        Geometry(geometry_type="GEOMETRY", srid=0, spatial_index=False), nullable=False
    )

    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: ★ **0–1. The SURVEYOR'S OWN CERTAINTY.** Not the algorithm's.
    confidence: Mapped[float] = mapped_column(
        Double, nullable=False, server_default=text("1.0")
    )
    ordering: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    #: Konva render hints.
    style: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    #: Free-form user metadata.
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    #: ★ Tombstone. The row survives its own deletion so the ledger stays referential.
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    #: Optimistic-lock counter → ``ETag``.
    version_no: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    #: The project revision that last touched this annotation.
    revision_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)

    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by: Mapped[str | None] = mapped_column(Text, nullable=True)

    image: Mapped[Image] = relationship(back_populates="annotations", lazy="raise")
    gcps: Mapped[list[GCP]] = relationship(
        back_populates="landmark",
        foreign_keys="GCP.landmark_id",
        passive_deletes=True,
        lazy="raise",
    )

    __table_args__ = (
        # ★ THE guard of the single-table design: geom_type and the stored geometry
        # cannot disagree.
        CheckConstraint(
            "(geom_type = 'point' AND GeometryType(pixel_geom) = 'POINT')"
            " OR (geom_type = 'polyline' AND GeometryType(pixel_geom) = 'LINESTRING')"
            " OR (geom_type = 'polygon' AND GeometryType(pixel_geom) = 'POLYGON')",
            name="geom_type_match",
        ),
        CheckConstraint("ST_IsValid(pixel_geom)", name="geom_valid"),
        CheckConstraint("ST_NDims(pixel_geom) = 2", name="geom_2d"),
        CheckConstraint("ST_SRID(pixel_geom) = 0", name="geom_srid"),
        CheckConstraint(
            "geom_type <> 'polyline' OR ST_NPoints(pixel_geom) >= 2",
            name="polyline_min",
        ),
        CheckConstraint(
            "geom_type <> 'polygon' OR ST_NPoints(ST_ExteriorRing(pixel_geom)) >= 4",
            name="polygon_min",
        ),
        CheckConstraint("pixel_x >= 0 AND pixel_y >= 0", name="pixel_nonneg"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence"),
        CheckConstraint("version_no > 0", name="version_pos"),
        Index(
            "ix_annotations_image_order",
            "image_id",
            "ordering",
            "created_at",
            postgresql_where=text("is_deleted = FALSE"),
        ),
        Index("ix_annotations_pixel_geom", "pixel_geom", postgresql_using="gist"),
        Index(
            "ix_annotations_kind",
            "image_id",
            "kind",
            postgresql_where=text("is_deleted = FALSE"),
        ),
        Index(
            "ix_annotations_attributes",
            "attributes",
            postgresql_using="gin",
            postgresql_ops={"attributes": "jsonb_path_ops"},
        ),
        Index("ix_annotations_revision", "revision_seq"),
    )


class AnnotationVersion(Base):
    """One append-only event in the annotation ledger.

    ★ **``annotation_id`` is deliberately NOT a foreign key.** The log must outlive the
    row. Under an FK, a ``'create'`` event for an annotation a later hard-delete removed
    would force us to either cascade-delete the audit trail (destroying history —
    unacceptable) or block the delete. A plain indexed UUID makes this a genuine
    append-only ledger: **tolerating dangling references is the normal and correct
    property of an audit log.**

    ★ ``id`` is ``BIGSERIAL``, not a UUID (§5.4): append-only, high-row-count, never
    referenced by URL. It is **serialised as a JSON number**, not a string.
    """

    __tablename__ = "annotation_versions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    #: ★ Deliberately NOT an FK — see the class docstring.
    annotation_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    image_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )
    revision_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("project_revisions.id", ondelete="SET NULL"),
        nullable=True,
    )
    op: Mapped[AnnotationOp] = mapped_column(
        pg_enum(AnnotationOp, "annotation_op"), nullable=False
    )
    #: The resulting ``annotations.version_no``.
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    #: ★ NULL **iff** ``op = 'create'``.
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    #: ★ NULL **iff** ``op = 'delete'``. Carrying **both** sides is what makes undo
    #: O(1): a single indexed row read, no fold over the log.
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    #: Denormalised post-state, for canvas "ghost" rendering.
    pixel_geom_after: Mapped[WKBElement | None] = mapped_column(
        Geometry(geometry_type="GEOMETRY", srid=0, spatial_index=False), nullable=True
    )
    actor_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: ★ Client-minted idempotency key, one per user gesture.
    client_op_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    image: Mapped[Image] = relationship(
        back_populates="annotation_versions", lazy="raise"
    )
    revision: Mapped[ProjectRevision | None] = relationship(
        back_populates="annotation_versions", lazy="raise"
    )

    __table_args__ = (
        # The biconditional binding `op` to the nullity of `before`/`after`.
        CheckConstraint(
            "(op = 'create' AND before IS NULL AND after IS NOT NULL)"
            " OR (op = 'delete' AND before IS NOT NULL AND after IS NULL)"
            " OR (op IN ('update', 'restore') AND before IS NOT NULL AND after IS NOT NULL)",
            name="payload",
        ),
        CheckConstraint("version_no > 0", name="version_pos"),
        Index(
            "uq_annotation_versions_annotation_version",
            "annotation_id",
            "version_no",
            unique=True,
        ),
        Index(
            "uq_annotation_versions_client_op",
            "client_op_id",
            unique=True,
            postgresql_where=text("client_op_id IS NOT NULL"),
        ),
        # ★ This index is what makes undo O(1).
        Index(
            "ix_annotation_versions_annotation",
            "annotation_id",
            text("version_no DESC"),
        ),
        Index("ix_annotation_versions_image_time", "image_id", text("id DESC")),
        Index(
            "ix_annotation_versions_revision",
            "revision_id",
            postgresql_where=text("revision_id IS NOT NULL"),
        ),
        Index(
            "ix_annotation_versions_actor",
            "actor_id",
            text("id DESC"),
            postgresql_where=text("actor_id IS NOT NULL"),
        ),
        Index(
            "ix_annotation_versions_geom",
            "pixel_geom_after",
            postgresql_using="gist",
            postgresql_where=text("pixel_geom_after IS NOT NULL"),
        ),
        Index(
            "ix_annotation_versions_after",
            "after",
            postgresql_using="gin",
            postgresql_ops={"after": "jsonb_path_ops"},
        ),
    )
