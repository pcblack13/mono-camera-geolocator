"""``semantic_features`` — :class:`SemanticFeature` (CONTRACT.md §5.6).

★ SCOPE.md §4: semantic detection is **deferred** (ABC only). The table is created
exactly as specified regardless — §4 rule 5.

**This table is entirely optional even when the engine exists.** Empty →
``semantic_similarity_score IS NULL`` → renormalised weights → **the system works.**
Nothing downstream requires a row here (invariant I3).

**Embeddings are NOT stored in Postgres.** ``pgvector`` is not in the mandated stack and
DINOv2 descriptors (768-D float32 × thousands of patches) are a poor fit for a row
store. They are written as ``.npy``/FAISS artifacts and referenced by path in
``embedding_meta``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from geoalchemy2 import Geography, Geometry
from geoalchemy2.elements import WKBElement
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import FeatureDetector, FeatureSpace, SemanticClass, pg_enum
from app.models.mixins import UUIDPkMixin

if TYPE_CHECKING:
    from app.models.annotation import Annotation
    from app.models.image import Image
    from app.models.match import MatchResult

__all__ = ["SemanticFeature"]


class SemanticFeature(UUIDPkMixin, Base):
    """A detected (or hand-drawn) semantic region, in exactly one of the two spaces.

    ★ ``ck_semantic_features_space_xor`` is **the constraint that makes invariant I1
    mechanical for this table**: a row lives in image pixel space or in geographic
    space, never both and never neither, and the two are physically different column
    types so PostGIS itself refuses to confuse them.
    """

    __tablename__ = "semantic_features"

    image_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )
    #: Set **iff** ``space = 'satellite_geo'``.
    match_result_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("match_results.id", ondelete="CASCADE"),
        nullable=True,
    )
    #: Set **iff** ``detector = 'manual'``.
    source_annotation_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("annotations.id", ondelete="SET NULL"),
        nullable=True,
    )

    #: ``class`` is not a legal Python attribute name; the column is ``class``.
    class_: Mapped[SemanticClass] = mapped_column(
        "class", pg_enum(SemanticClass, "semantic_class"), nullable=False
    )
    space: Mapped[FeatureSpace] = mapped_column(
        pg_enum(FeatureSpace, "feature_space"), nullable=False
    )
    detector: Mapped[FeatureDetector] = mapped_column(
        pg_enum(FeatureDetector, "feature_detector"),
        nullable=False,
        server_default=text("'classical_cv'::feature_detector"),
    )
    model_version: Mapped[str | None] = mapped_column(Text, nullable=True)

    pixel_geom: Mapped[WKBElement | None] = mapped_column(
        Geometry(geometry_type="GEOMETRY", srid=0, spatial_index=False), nullable=True
    )
    geo_geom: Mapped[WKBElement | None] = mapped_column(
        Geography(geometry_type="GEOMETRY", srid=4326, spatial_index=False),
        nullable=True,
    )

    #: **0–1.**
    confidence: Mapped[float] = mapped_column(Double, nullable=False)
    area_px: Mapped[float | None] = mapped_column(Double, nullable=True)
    area_m2: Mapped[float | None] = mapped_column(Double, nullable=True)
    length_m: Mapped[float | None] = mapped_column(Double, nullable=True)
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    #: Paths to the ``.npy``/FAISS artifacts — never the vectors themselves.
    embedding_meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    image: Mapped[Image] = relationship(
        back_populates="semantic_features", lazy="raise"
    )
    match_result: Mapped[MatchResult | None] = relationship(
        back_populates="semantic_features", lazy="raise"
    )
    source_annotation: Mapped[Annotation | None] = relationship(lazy="raise")

    __table_args__ = (
        CheckConstraint(
            "(space = 'image_pixel' AND pixel_geom IS NOT NULL AND geo_geom IS NULL)"
            " OR (space = 'satellite_geo' AND geo_geom IS NOT NULL AND pixel_geom IS NULL)",
            name="space_xor",
        ),
        CheckConstraint(
            "(space = 'satellite_geo') = (match_result_id IS NOT NULL)",
            name="geo_needs_match",
        ),
        CheckConstraint(
            "(detector = 'manual') = (source_annotation_id IS NOT NULL)",
            name="manual_has_source",
        ),
        CheckConstraint(
            "pixel_geom IS NULL OR ST_SRID(pixel_geom) = 0", name="pixel_srid"
        ),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence"),
        CheckConstraint(
            "(area_px IS NULL OR area_px >= 0)"
            " AND (area_m2 IS NULL OR area_m2 >= 0)"
            " AND (length_m IS NULL OR length_m >= 0)",
            name="area",
        ),
        Index("ix_semantic_features_image_class", "image_id", "class"),
        Index(
            "ix_semantic_features_pixel_geom",
            "pixel_geom",
            postgresql_using="gist",
            postgresql_where=text("pixel_geom IS NOT NULL"),
        ),
        Index(
            "ix_semantic_features_geo_geom",
            "geo_geom",
            postgresql_using="gist",
            postgresql_where=text("geo_geom IS NOT NULL"),
        ),
        Index(
            "ix_semantic_features_match_result",
            "match_result_id",
            postgresql_where=text("match_result_id IS NOT NULL"),
        ),
        Index(
            "ix_semantic_features_attributes",
            "attributes",
            postgresql_using="gin",
            postgresql_ops={"attributes": "jsonb_path_ops"},
        ),
        Index(
            "ix_semantic_features_class_space_conf",
            "class",
            "space",
            text("confidence DESC"),
        ),
    )
