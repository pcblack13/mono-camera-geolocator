"""``match_results`` — :class:`MatchResult` (CONTRACT.md §5.6).

One row per **candidate** the matcher scored. The winner is ``is_selected = TRUE``.
**Losers are kept** — the UI offers "other candidates", and a surveyor overruling the
algorithm is a first-class workflow.

★ SCOPE.md §4 rule 5: created exactly as specified though this build writes no rows.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from geoalchemy2 import Geography, Geometry
from geoalchemy2.elements import WKBElement
from sqlalchemy import (
    CHAR,
    Boolean,
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
from app.models.enums import (
    FeatureExtractor,
    FeatureMatcher,
    ImageryProvider,
    RobustEstimator,
    pg_enum,
)
from app.models.mixins import UUIDPkMixin

if TYPE_CHECKING:
    from app.models.gcp import GCP
    from app.models.job import AuxJob, MatchJob
    from app.models.pose import CameraPose
    from app.models.semantic import SemanticFeature

__all__ = ["MatchResult"]


class MatchResult(UUIDPkMixin, Base):
    """A scored candidate window, its transform chain, and the audit of its score.

    ★ **Six columns are nullable and one CHECK replaces them.** ``homography``,
    ``sat_geotransform``, ``satellite_image_path``, ``tile_z/x/y`` and the three
    ``*_used`` columns cannot always be supplied: §11.6 **requires** a rejected candidate
    be persisted **with its DegeneracyReport** so a reviewer can see *why*, and a
    rejected candidate has no homography and no estimator. Under NOT NULL, the row
    documenting the rejection could not be written. ``ck_match_results_selected_is_complete``
    is the honest expression of the real invariant: *a **selected** result is complete.*
    """

    __tablename__ = "match_results"

    match_job_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("match_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: Set by ``gcps/recompute`` — the result this one supersedes.
    parent_match_result_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("match_results.id", ondelete="SET NULL"),
        nullable=True,
    )
    #: 1 = best.
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    is_selected: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    #: Denormalised from the job.
    provider: Mapped[ImageryProvider] = mapped_column(
        pg_enum(ImageryProvider, "imagery_provider"), nullable=False
    )

    #: ★ **NULLABLE.** The window's ANCHOR tile — addressing metadata only. A 1024px
    #: window cropped at an arbitrary offset with overlap is not addressable by a single
    #: ``(z,x,y)``; ``local_orthophoto`` and Sentinel scenes are not tiles at all.
    #: **The transform is the transform** — see ``sat_geotransform``.
    tile_z: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    tile_x: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tile_y: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mosaic_cols: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("1")
    )
    mosaic_rows: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("1")
    )

    #: ★ **CANONICAL.**
    tile_bounds: Mapped[WKBElement] = mapped_column(
        Geography(geometry_type="POLYGON", srid=4326, spatial_index=False),
        nullable=False,
    )
    #: ★ Derived, denormalised **on purpose**: written by the same transaction from the
    #: same source arithmetic as ``tile_bounds`` — **not** a reprojection of it, so no
    #: round-trip error accumulates. If they ever disagree, ``tile_bounds`` wins.
    tile_bounds_3857: Mapped[WKBElement | None] = mapped_column(
        Geometry(geometry_type="POLYGON", srid=3857, spatial_index=False), nullable=True
    )

    #: ★ **NULLABLE** — written by ``app.tasks.matching`` via ``ObjectStorage`` from
    #: ``best.window.rgb``. A losing candidate's mosaic is not persisted.
    satellite_image_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    satellite_checksum: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    satellite_width_px: Mapped[int | None] = mapped_column(Integer, nullable=True)
    satellite_height_px: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: ★ 9 elements, **ROW-MAJOR** ``[h00,h01,h02,h10,h11,h12,h20,h21,h22]``. Maps
    #: **IMAGE PIXEL (x,y,1) → SATELLITE MOSAIC PIXEL (u,v,w)**, i.e.
    #: ``cv2.findHomography(src=image, dst=mosaic)``. It ends in **pixels** — not
    #: metres, not degrees. Feeding its output straight into a 4326 column is the
    #: catastrophic bug this schema is shaped to prevent (§5.8).
    homography: Mapped[list[float] | None] = mapped_column(
        PG_ARRAY(Double, dimensions=1), nullable=True
    )
    #: ★ 6 elements, GDAL order ``[c,a,b,f,d,e]``:
    #: ``X = c + a·(u+0.5) + b·(v+0.5)`` ; ``Y = f + d·(u+0.5) + e·(v+0.5)``.
    #: The ``+0.5`` pixel-centre convention is **not optional** (§4.18, §6.1).
    sat_geotransform: Mapped[list[float] | None] = mapped_column(
        PG_ARRAY(Double, dimensions=1), nullable=True
    )
    #: ★ The SRID ``sat_geotransform`` lands in — ``3857`` for every slippy provider,
    #: **a UTM code for ``local_orthophoto``**. Not hardcoded: reprojecting an
    #: orthophoto resamples it, throwing away the accuracy that is the entire reason to
    #: mount one. ``4326`` is the unused sentinel when there is no geotransform.
    sat_geotransform_srid: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("4326")
    )

    #: From ``CandidateWindow.captured_at``. Feeds the normative CSV column.
    imagery_captured_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: ★ Served on ``X-Imagery-Attribution`` and in every PDF **from THIS ROW**, never
    #: by re-resolving the provider — which may have been reconfigured since.
    attribution: Mapped[str] = mapped_column(Text, nullable=False)
    terms_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: ★ **TRUE ground metres** per mosaic pixel at centre, cos(φ)-corrected.
    gsd_m: Mapped[float | None] = mapped_column(Double, nullable=True)
    #: ★ The PROVIDER's own error. Never reducible by us.
    georef_ce90_m: Mapped[float | None] = mapped_column(Double, nullable=True)
    is_authoritative: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    #: ★ What **actually** ran — NULLABLE for the same reason as ``homography``.
    feature_extractor_used: Mapped[FeatureExtractor | None] = mapped_column(
        pg_enum(FeatureExtractor, "feature_extractor"), nullable=True
    )
    feature_matcher_used: Mapped[FeatureMatcher | None] = mapped_column(
        pg_enum(FeatureMatcher, "feature_matcher"), nullable=True
    )
    #: ★ The **METHOD** that ran (``RansacConfig.method``), not a registry key.
    estimator_used: Mapped[RobustEstimator | None] = mapped_column(
        pg_enum(RobustEstimator, "robust_estimator"), nullable=True
    )

    keypoints_query: Mapped[int | None] = mapped_column(Integer, nullable=True)
    keypoints_train: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_matches: Mapped[int | None] = mapped_column(Integer, nullable=True)
    good_matches: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inlier_count: Mapped[int] = mapped_column(Integer, nullable=False)
    inlier_ratio: Mapped[float | None] = mapped_column(Double, nullable=True)
    #: Symmetric transfer RMS over the inliers.
    ransac_reproj_error_px: Mapped[float | None] = mapped_column(Double, nullable=True)
    ransac_threshold_px: Mapped[float | None] = mapped_column(Double, nullable=True)
    ransac_iterations: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: ★ On the **Hartley-normalised** ``H̃``. Stored, not checked-and-discarded: "why
    #: did the algorithm reject this obviously-correct-looking tile?" is the single most
    #: common support question in this class of product, and persisting these two makes
    #: the answer a ``SELECT``.
    homography_condition_number: Mapped[float | None] = mapped_column(
        Double, nullable=True
    )
    #: ★ ``det(H̃)``. ``<= 0`` ⇒ reflection ⇒ reject.
    homography_determinant: Mapped[float | None] = mapped_column(Double, nullable=True)

    #: ``nadir|oblique_rectifiable|oblique_raw|ground_horizon|unknown``. Plain ``Text``
    #: on purpose: diagnostic provenance rather than a queried dimension, and the field
    #: most likely to gain members as the taxonomy is tuned against real oblique photos.
    view_regime: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: ``[0,1]``. ``0`` ⇒ rejected.
    degeneracy_gate: Mapped[float | None] = mapped_column(Double, nullable=True)
    degeneracy_report: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    #: The four sub-scores are **0–1 and NULLABLE** — invariant I3: no column requires a
    #: deep model to be populated, and a classical-only run produces a complete,
    #: exportable row set with renormalised weights.
    feature_similarity_score: Mapped[float | None] = mapped_column(Double, nullable=True)
    geometric_consistency_score: Mapped[float | None] = mapped_column(
        Double, nullable=True
    )
    landmark_consistency_score: Mapped[float | None] = mapped_column(
        Double, nullable=True
    )
    #: NULL when no semantics ran.
    semantic_similarity_score: Mapped[float | None] = mapped_column(Double, nullable=True)
    #: ★ **0–100**. A rejected candidate is legitimately ``0``.
    overall_confidence: Mapped[float] = mapped_column(
        Double, nullable=False, server_default=text("0.0")
    )
    #: ★ Audit of the exact arithmetic, incl. ``"renormalized": true``.
    score_breakdown: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    #: ★ Persisted so calibration can be refit offline.
    score_feature_vector: Mapped[list[float] | None] = mapped_column(
        PG_ARRAY(Double, dimensions=1), nullable=True
    )
    calibrated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    calibration_id: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'identity'")
    )

    #: ★ Result-level, not just job-level.
    degraded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    degradation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Advisory badges.
    quality_flags: Mapped[list[str]] = mapped_column(
        PG_ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    match_job: Mapped[MatchJob] = relationship(back_populates="results", lazy="raise")
    parent: Mapped[MatchResult | None] = relationship(
        back_populates="children", remote_side=lambda: [MatchResult.id], lazy="raise"
    )
    children: Mapped[list[MatchResult]] = relationship(
        back_populates="parent", lazy="raise"
    )
    gcps: Mapped[list[GCP]] = relationship(
        back_populates="match_result",
        # ★ `passive_deletes="all"` keeps SQLAlchemy from nulling the FK behind the
        # RESTRICT — the database is the authority on cascade behaviour (§5.4).
        passive_deletes="all",
        lazy="raise",
    )
    camera_poses: Mapped[list[CameraPose]] = relationship(
        back_populates="match_result",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    semantic_features: Mapped[list[SemanticFeature]] = relationship(
        back_populates="match_result",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    aux_jobs: Mapped[list[AuxJob]] = relationship(
        back_populates="match_result", lazy="raise"
    )

    __table_args__ = (
        CheckConstraint(
            "homography IS NULL OR array_length(homography, 1) = 9",
            name="homography_arity",
        ),
        CheckConstraint(
            "sat_geotransform IS NULL OR array_length(sat_geotransform, 1) = 6",
            name="geotransform_arity",
        ),
        CheckConstraint("tile_z IS NULL OR tile_z BETWEEN 0 AND 22", name="tile_z"),
        CheckConstraint(
            "tile_z IS NULL"
            " OR (tile_x >= 0 AND tile_x < (1 << tile_z)"
            "     AND tile_y >= 0 AND tile_y < (1 << tile_z))",
            name="tile_xy",
        ),
        CheckConstraint(
            "(tile_z IS NULL) = (tile_x IS NULL) AND (tile_z IS NULL) = (tile_y IS NULL)",
            name="tile_triple",
        ),
        CheckConstraint("mosaic_cols > 0 AND mosaic_rows > 0", name="mosaic"),
        CheckConstraint("rank >= 1", name="rank"),
        CheckConstraint("inlier_count >= 0", name="inliers"),
        CheckConstraint(
            "inlier_ratio IS NULL OR inlier_ratio BETWEEN 0 AND 1", name="inlier_ratio"
        ),
        CheckConstraint(
            "(feature_similarity_score IS NULL"
            "  OR feature_similarity_score BETWEEN 0 AND 1)"
            " AND (geometric_consistency_score IS NULL"
            "  OR geometric_consistency_score BETWEEN 0 AND 1)"
            " AND (landmark_consistency_score IS NULL"
            "  OR landmark_consistency_score BETWEEN 0 AND 1)"
            " AND (semantic_similarity_score IS NULL"
            "  OR semantic_similarity_score BETWEEN 0 AND 1)",
            name="subscores",
        ),
        CheckConstraint("overall_confidence BETWEEN 0 AND 100", name="overall"),
        CheckConstraint(
            "degeneracy_gate IS NULL OR degeneracy_gate BETWEEN 0 AND 1",
            name="degeneracy_gate",
        ),
        # ★ The SRID is meaningful **iff** the geotransform exists; when there is no
        # geotransform the column is the unused 4326 sentinel and must say so, rather
        # than naming a projection nothing was projected into.
        CheckConstraint(
            "(sat_geotransform IS NOT NULL) OR (sat_geotransform_srid = 4326)",
            name="srid_iff_gt",
        ),
        CheckConstraint(
            "sat_geotransform_srid BETWEEN 1024 AND 32767 OR sat_geotransform_srid = 4326",
            name="srid_range",
        ),
        # ★ A SELECTED result is complete. A losing candidate is allowed to be a scored
        # rejection and nothing more.
        CheckConstraint(
            "NOT is_selected OR ("
            " homography             IS NOT NULL AND"
            " sat_geotransform       IS NOT NULL AND"
            " sat_geotransform_srid  IS NOT NULL AND"
            " satellite_image_path   IS NOT NULL AND"
            " feature_extractor_used IS NOT NULL AND"
            " feature_matcher_used   IS NOT NULL AND"
            " estimator_used         IS NOT NULL)",
            name="selected_is_complete",
        ),
        Index("uq_match_results_job_rank", "match_job_id", "rank", unique=True),
        # ★ At most ONE selected per job, enforced by the database, not by hope.
        Index(
            "uq_match_results_job_selected",
            "match_job_id",
            unique=True,
            postgresql_where=text("is_selected"),
        ),
        Index(
            "ix_match_results_job_conf",
            "match_job_id",
            text("overall_confidence DESC"),
        ),
        Index("ix_match_results_tile", "provider", "tile_z", "tile_x", "tile_y"),
        Index("ix_match_results_tile_bounds", "tile_bounds", postgresql_using="gist"),
        Index(
            "ix_match_results_tile_bounds_3857",
            "tile_bounds_3857",
            postgresql_using="gist",
            postgresql_where=text("tile_bounds_3857 IS NOT NULL"),
        ),
        Index(
            "ix_match_results_score_breakdown",
            "score_breakdown",
            postgresql_using="gin",
            postgresql_ops={"score_breakdown": "jsonb_path_ops"},
        ),
        Index(
            "ix_match_results_parent",
            "parent_match_result_id",
            postgresql_where=text("parent_match_result_id IS NOT NULL"),
        ),
    )
