"""``landmark_suggestions`` — :class:`LandmarkSuggestion` (CONTRACT.md §5.6).

★ SCOPE.md §4: automatic landmark suggestion is **deferred** (ABC only), and
``POST /images/{id}/suggest-landmarks`` returns 501. The table is created exactly as
specified regardless — §4 rule 5 — and holds no rows in this build.

**Why suggestions are a separate resource.** Writing AI guesses straight into
``annotations`` would put unreviewed machine output into the surveyor's revision
history, the undo stack, and — via ``is_gcp_candidate`` — the GCP deriver. **A
suggestion is a proposal; an annotation is an assertion by a human.** The boundary
between them is ``POST …/accept``, and it is the only door. (ADR-014.)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from geoalchemy2 import Geometry
from geoalchemy2.elements import WKBElement
from sqlalchemy import (
    CheckConstraint,
    DateTime,
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
from app.models.enums import (
    AnnotationGeomType,
    AnnotationKind,
    FeatureDetector,
    SuggestionStatus,
    pg_enum,
)
from app.models.mixins import TimestampMixin, UUIDPkMixin

if TYPE_CHECKING:
    from app.models.annotation import Annotation
    from app.models.image import Image
    from app.models.job import AuxJob

__all__ = ["LandmarkSuggestion"]


class LandmarkSuggestion(UUIDPkMixin, TimestampMixin, Base):
    """A proposed landmark, pending a human decision."""

    __tablename__ = "landmark_suggestions"

    image_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )
    #: Which ``suggest_landmarks`` job produced it.
    aux_job_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("aux_jobs.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[AnnotationKind] = mapped_column(
        pg_enum(AnnotationKind, "annotation_kind"),
        nullable=False,
        server_default=text("'generic'::annotation_kind"),
    )
    geom_type: Mapped[AnnotationGeomType] = mapped_column(
        pg_enum(AnnotationGeomType, "annotation_geom_type"),
        nullable=False,
        server_default=text("'point'::annotation_geom_type"),
    )
    pixel_x: Mapped[float] = mapped_column(Double, nullable=False)
    pixel_y: Mapped[float] = mapped_column(Double, nullable=False)
    pixel_geom: Mapped[WKBElement] = mapped_column(
        Geometry(geometry_type="GEOMETRY", srid=0, spatial_index=False), nullable=False
    )
    #: **0–1** — the detector's own, never shown as a survey confidence.
    score: Mapped[float] = mapped_column(Double, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    detector: Mapped[FeatureDetector] = mapped_column(
        pg_enum(FeatureDetector, "feature_detector"),
        nullable=False,
        server_default=text("'classical_cv'::feature_detector"),
    )
    model_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Human-readable "why".
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[SuggestionStatus] = mapped_column(
        pg_enum(SuggestionStatus, "suggestion_status"),
        nullable=False,
        server_default=text("'pending'::suggestion_status"),
    )
    #: Set on accept — the door between a proposal and an assertion.
    accepted_annotation_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("annotations.id", ondelete="SET NULL"),
        nullable=True,
    )
    decided_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    image: Mapped[Image] = relationship(
        back_populates="landmark_suggestions", lazy="raise"
    )
    aux_job: Mapped[AuxJob | None] = relationship(
        back_populates="suggestions", lazy="raise"
    )
    accepted_annotation: Mapped[Annotation | None] = relationship(lazy="raise")

    __table_args__ = (
        CheckConstraint("score BETWEEN 0 AND 1", name="score"),
        CheckConstraint("rank >= 1", name="rank"),
        CheckConstraint("pixel_x >= 0 AND pixel_y >= 0", name="pixel_nonneg"),
        CheckConstraint(
            "status <> 'accepted' OR accepted_annotation_id IS NOT NULL",
            name="accepted",
        ),
        CheckConstraint(
            "(geom_type = 'point' AND GeometryType(pixel_geom) = 'POINT')"
            " OR (geom_type = 'polyline' AND GeometryType(pixel_geom) = 'LINESTRING')"
            " OR (geom_type = 'polygon' AND GeometryType(pixel_geom) = 'POLYGON')",
            name="geom_type_match",
        ),
        CheckConstraint("ST_SRID(pixel_geom) = 0", name="pixel_srid"),
        Index(
            "ix_landmark_suggestions_image_rank",
            "image_id",
            "rank",
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_landmark_suggestions_job", "aux_job_id"),
        Index("ix_landmark_suggestions_geom", "pixel_geom", postgresql_using="gist"),
    )
