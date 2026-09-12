"""``confidence_heatmaps`` + ``confidence_heatmap_cells`` (CONTRACT.md §5.6).

★ SCOPE.md §4: the confidence heatmap is **deferred** (ABC only). The tables are created
exactly as specified regardless — §4 rule 5 — and hold no rows in this build.

**Vector, not raster. ``postgis_raster`` is deliberately NOT installed.** It drags GDAL
driver configuration into the *database* container and has a real CVE history around
out-db rasters; the interaction model is per-cell-with-attributes (hover → score
breakdown), which a raster band cannot hold; the volume is ~10k cells and raster's
advantage begins in the tens of millions; sparsity is free in vector (**absent ≠ score
0**); and a raster would force storage in 3857, reintroducing the Mercator distortion
§5.2 exists to avoid.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from geoalchemy2 import Geography
from geoalchemy2.elements import WKBElement
from sqlalchemy import (
    BigInteger,
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
from app.models.mixins import UUIDPkMixin

if TYPE_CHECKING:
    from app.models.image import Image
    from app.models.job import MatchJob

__all__ = ["ConfidenceHeatmap", "ConfidenceHeatmapCell"]


class ConfidenceHeatmap(UUIDPkMixin, Base):
    """The posterior over candidate camera locations for one match job."""

    __tablename__ = "confidence_heatmaps"

    match_job_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("match_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    image_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )
    bbox: Mapped[WKBElement] = mapped_column(
        Geography(geometry_type="POLYGON", srid=4326, spatial_index=False),
        nullable=False,
    )
    #: **True metres** — which is only meaningful because storage is ``geography``.
    cell_size_m: Mapped[float] = mapped_column(Double, nullable=False)
    grid_cols: Mapped[int] = mapped_column(Integer, nullable=False)
    grid_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    cell_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    min_score: Mapped[float | None] = mapped_column(Double, nullable=True)
    max_score: Mapped[float | None] = mapped_column(Double, nullable=True)
    mean_score: Mapped[float | None] = mapped_column(Double, nullable=True)
    argmax_geom: Mapped[WKBElement | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False), nullable=True
    )
    argmax_score: Mapped[float | None] = mapped_column(Double, nullable=True)
    colormap: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'viridis'")
    )
    render_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    match_job: Mapped[MatchJob] = relationship(back_populates="heatmap", lazy="raise")
    image: Mapped[Image] = relationship(back_populates="heatmaps", lazy="raise")
    cells: Mapped[list[ConfidenceHeatmapCell]] = relationship(
        back_populates="heatmap",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )

    __table_args__ = (
        CheckConstraint("grid_cols > 0 AND grid_rows > 0", name="grid"),
        CheckConstraint("cell_size_m > 0", name="cell_size"),
        # ★ Sparsity is queryable: `cell_count` vs `grid_cols*grid_rows`. Absent is not
        # score 0, and the difference is the honest one.
        CheckConstraint(
            "cell_count >= 0 AND cell_count <= grid_cols * grid_rows", name="cell_count"
        ),
        CheckConstraint(
            "(min_score IS NULL OR min_score BETWEEN 0 AND 1)"
            " AND (max_score IS NULL OR max_score BETWEEN 0 AND 1)"
            " AND (mean_score IS NULL OR mean_score BETWEEN 0 AND 1)"
            " AND (argmax_score IS NULL OR argmax_score BETWEEN 0 AND 1)"
            " AND (min_score IS NULL OR max_score IS NULL OR min_score <= max_score)",
            name="scores",
        ),
        Index("uq_confidence_heatmaps_job", "match_job_id", unique=True),
        Index(
            "ix_confidence_heatmaps_image", "image_id", text("created_at DESC")
        ),
        Index("ix_confidence_heatmaps_bbox", "bbox", postgresql_using="gist"),
        Index(
            "ix_confidence_heatmaps_argmax",
            "argmax_geom",
            postgresql_using="gist",
            postgresql_where=text("argmax_geom IS NOT NULL"),
        ),
    )


class ConfidenceHeatmapCell(Base):
    """One grid cell's aggregated score.

    ★ **Only the centroid is stored.** The cell polygon is
    ``centroid ± cell_size_m/2``, fully determined by the parent. Storing 10 000
    five-vertex polygons is ~5× the bytes and ~5× the GIST index **for zero
    information**.

    ``sample_count`` exists because a cell **aggregates** every candidate whose centre
    fell in it — a cell with ``sample_count = 1`` is far less trustworthy than one with
    12, and the UI dims it accordingly.
    """

    __tablename__ = "confidence_heatmap_cells"

    #: ★ BIGSERIAL (§5.4): append-only, high-row-count, never referenced by URL.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    heatmap_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("confidence_heatmaps.id", ondelete="CASCADE"),
        nullable=False,
    )
    col: Mapped[int] = mapped_column(Integer, nullable=False)
    row: Mapped[int] = mapped_column(Integer, nullable=False)
    #: ★ **CENTROID only.**
    geom: Mapped[WKBElement] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False), nullable=False
    )
    #: 0–1.
    score: Mapped[float] = mapped_column(Double, nullable=False)
    sample_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    components: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    heatmap: Mapped[ConfidenceHeatmap] = relationship(
        back_populates="cells", lazy="raise"
    )

    __table_args__ = (
        CheckConstraint("score BETWEEN 0 AND 1", name="score"),
        CheckConstraint("col >= 0 AND row >= 0", name="grid_pos"),
        CheckConstraint("sample_count >= 1", name="sample_count"),
        Index(
            "uq_confidence_heatmap_cells_grid",
            "heatmap_id",
            "col",
            "row",
            unique=True,
        ),
        Index("ix_confidence_heatmap_cells_geom", "geom", postgresql_using="gist"),
        Index(
            "ix_confidence_heatmap_cells_heatmap_score",
            "heatmap_id",
            text("score DESC"),
        ),
    )
