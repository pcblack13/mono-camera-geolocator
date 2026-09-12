"""jobs and matching

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-17

``batch_jobs`` · ``match_jobs`` · ``batch_job_items`` · ``match_results``.

★ **The match_jobs ↔ batch_job_items mutual FK cycle-break.** The cycle is deliberate:
the batch progress view scans items and needs the job (one index hit); a worker holding
a ``match_job`` needs to report up to its item without a scan. **Both sides are
``ON DELETE SET NULL``, so neither can create a cascade cycle.** Both tables are created
here *without* the mutual FKs, and the two constraints are added with
``op.create_foreign_key()`` at the end — the standard cycle-breaking pattern, and the
reason this migration exists as one unit rather than two.

★ ``batch_jobs`` is created here, not in ``0008``, because ``batch_job_items`` cannot
reference a table that does not exist. ``0008`` **alters** it (the shared lifecycle
columns) — which is what §2.4's "batch" in the 0008 title refers to.

★ SCOPE.md §4 rule 5: every table here is created exactly as specified even though this
build — a manual GCP surveying tool — writes no rows to ``match_jobs`` or
``match_results``. Schema churn later costs far more than unused tables now.
"""

from __future__ import annotations

from typing import Sequence

import geoalchemy2  # noqa: F401  # ★ see script.py.mako — never remove
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JOB_STATUS = postgresql.ENUM(
    "pending", "queued", "running", "succeeded", "failed", "cancelled", "retrying",
    name="job_status",
    create_type=False,
)
_IMAGERY_PROVIDER = postgresql.ENUM(
    "esri_world_imagery", "local_orthophoto", "fixture", "mapbox_satellite",
    "bing_aerial", "sentinel_copernicus", "google_maps_static",
    name="imagery_provider",
    create_type=False,
)
_FEATURE_EXTRACTOR = postgresql.ENUM(
    "sift", "orb", "akaze", "brisk", "asift", "superpoint", "dinov2",
    name="feature_extractor",
    create_type=False,
)
_FEATURE_MATCHER = postgresql.ENUM(
    "bf", "flann", "superglue", "lightglue", "loftr",
    name="feature_matcher",
    create_type=False,
)
_ROBUST_ESTIMATOR = postgresql.ENUM(
    "ransac", "usac_magsac", "lmeds", "prosac", "usac_accurate", "lsq",
    name="robust_estimator",
    create_type=False,
)

_DEFAULT_SCORE_WEIGHTS = (
    '{"feature": 0.25, "geometric": 0.35, "landmark": 0.30, "semantic": 0.10}'
)


def upgrade() -> None:
    op.create_table(
        "batch_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("celery_group_id", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column(
            "status",
            _JOB_STATUS,
            server_default=sa.text("'pending'::job_status"),
            nullable=False,
        ),
        sa.Column(
            "cancel_requested", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("total_items", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("completed_items", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("failed_items", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("progress", sa.Double(), server_default=sa.text("0.0"), nullable=False),
        sa.Column(
            "provider",
            _IMAGERY_PROVIDER,
            server_default=sa.text("'esri_world_imagery'::imagery_provider"),
            nullable=False,
        ),
        sa.Column(
            "params",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("concurrency", sa.SmallInteger(), server_default=sa.text("4"), nullable=False),
        sa.Column(
            "continue_on_error", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("progress BETWEEN 0 AND 1", name="ck_batch_jobs_progress"),
        sa.CheckConstraint(
            "completed_items + failed_items <= total_items", name="ck_batch_jobs_counts"
        ),
        sa.CheckConstraint("concurrency BETWEEN 1 AND 64", name="ck_batch_jobs_concurrency"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_batch_jobs_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_batch_jobs"),
    )

    op.create_table(
        "match_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("image_id", postgresql.UUID(as_uuid=True), nullable=False),
        # ★ FK added at the end of this migration — see the module docstring.
        sa.Column("batch_job_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("celery_task_id", sa.Text(), nullable=True),
        sa.Column(
            "status",
            _JOB_STATUS,
            server_default=sa.text("'pending'::job_status"),
            nullable=False,
        ),
        # ★ Cooperative cancellation — the worker polls it; nothing kills a process.
        sa.Column(
            "cancel_requested", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("attempt", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default=sa.text("3"), nullable=False),
        # ★ The reproducibility record.
        sa.Column(
            "provider",
            _IMAGERY_PROVIDER,
            server_default=sa.text("'esri_world_imagery'::imagery_provider"),
            nullable=False,
        ),
        sa.Column(
            "extractor",
            _FEATURE_EXTRACTOR,
            server_default=sa.text("'sift'::feature_extractor"),
            nullable=False,
        ),
        sa.Column(
            "matcher",
            _FEATURE_MATCHER,
            server_default=sa.text("'flann'::feature_matcher"),
            nullable=False,
        ),
        sa.Column(
            "estimator",
            _ROBUST_ESTIMATOR,
            server_default=sa.text("'usac_magsac'::robust_estimator"),
            nullable=False,
        ),
        # ★ Requested vs actually usable: the graceful-degradation record (L1 as data).
        sa.Column("use_semantic", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "semantic_available", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "search_aoi",
            geoalchemy2.types.Geography(
                geometry_type="POLYGON", srid=4326, spatial_index=False
            ),
            nullable=True,
        ),
        sa.Column("search_radius_m", sa.Double(), nullable=True),
        sa.Column(
            "search_zoom_levels",
            postgresql.ARRAY(sa.SmallInteger(), dimensions=1),
            server_default=sa.text("'{18}'::smallint[]"),
            nullable=False,
        ),
        sa.Column("max_tiles", sa.Integer(), server_default=sa.text("256"), nullable=False),
        sa.Column("max_candidates", sa.Integer(), server_default=sa.text("25"), nullable=False),
        sa.Column(
            "params",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        # ★ Stored per job, not read from config at display time. Weights will be
        # retuned; a stored result must remain explicable under the weights that
        # produced it.
        sa.Column(
            "score_weights",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text(f"'{_DEFAULT_SCORE_WEIGHTS}'::jsonb"),
            nullable=False,
        ),
        sa.Column("annotation_revision_seq", sa.BigInteger(), nullable=True),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("progress", sa.Double(), server_default=sa.text("0.0"), nullable=False),
        sa.Column("progress_stage", sa.Text(), nullable=True),
        sa.Column("progress_message", sa.Text(), nullable=True),
        sa.Column("tiles_fetched", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("tiles_total", sa.Integer(), nullable=True),
        sa.Column(
            "candidates_evaluated", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("result_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("best_confidence", sa.Double(), nullable=True),
        sa.Column("error_type", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        # ★ Stored server-side only. NEVER serialised.
        sa.Column("error_traceback", sa.Text(), nullable=True),
        sa.Column(
            "warnings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("code_version", sa.Text(), nullable=True),
        sa.Column("worker_hostname", sa.Text(), nullable=True),
        sa.Column("used_gpu", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("degraded", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("degradation_reason", sa.Text(), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "timings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("progress BETWEEN 0 AND 1", name="ck_match_jobs_progress"),
        sa.CheckConstraint(
            "attempt >= 0 AND attempt <= max_attempts", name="ck_match_jobs_attempt"
        ),
        sa.CheckConstraint(
            "best_confidence IS NULL OR best_confidence BETWEEN 0 AND 100",
            name="ck_match_jobs_best_conf",
        ),
        sa.CheckConstraint(
            "status <> 'failed' OR error_message IS NOT NULL",
            name="ck_match_jobs_failed_has_error",
        ),
        # ★ A biconditional: it catches both "marked succeeded but never timestamped"
        # and "timestamped but still shows running" — the two states that make a
        # progress UI hang forever.
        sa.CheckConstraint(
            "(status IN ('succeeded', 'failed', 'cancelled')) = (finished_at IS NOT NULL)",
            name="ck_match_jobs_finished_iff_terminal",
        ),
        sa.ForeignKeyConstraint(
            ["image_id"],
            ["images.id"],
            name="fk_match_jobs_image_id_images",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_match_jobs"),
    )
    # Heavy `progress` UPDATE churn: keep HOT updates on-page and off the indexes.
    # `fillfactor` is a table storage parameter; SQLAlchemy's postgresql dialect accepts
    # `with` only on Index, never on Table, so it is emitted as explicit DDL.
    op.execute("ALTER TABLE match_jobs SET (fillfactor = 70)")

    op.create_table(
        "batch_job_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("batch_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("image_id", postgresql.UUID(as_uuid=True), nullable=False),
        # ★ FK added at the end of this migration — the other half of the cycle.
        sa.Column("match_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            _JOB_STATUS,
            server_default=sa.text("'pending'::job_status"),
            nullable=False,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("ordinal >= 0", name="ck_batch_job_items_ordinal_nonneg"),
        sa.ForeignKeyConstraint(
            ["batch_job_id"],
            ["batch_jobs.id"],
            name="fk_batch_job_items_batch_job_id_batch_jobs",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["image_id"],
            ["images.id"],
            name="fk_batch_job_items_image_id_images",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_batch_job_items"),
    )

    # ── the cycle-break ──────────────────────────────────────────────────────
    op.create_foreign_key(
        "fk_match_jobs_batch_job_item_id_batch_job_items",
        "match_jobs",
        "batch_job_items",
        ["batch_job_item_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_batch_job_items_match_job_id_match_jobs",
        "batch_job_items",
        "match_jobs",
        ["match_job_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "match_results",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("match_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_match_result_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("is_selected", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("provider", _IMAGERY_PROVIDER, nullable=False),
        # ★ NULLABLE: the window's ANCHOR tile — addressing metadata only. A window
        # cropped at an arbitrary offset is not addressable by a single (z,x,y), and
        # local_orthophoto / Sentinel scenes are not tiles at all.
        sa.Column("tile_z", sa.SmallInteger(), nullable=True),
        sa.Column("tile_x", sa.Integer(), nullable=True),
        sa.Column("tile_y", sa.Integer(), nullable=True),
        sa.Column("mosaic_cols", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("mosaic_rows", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
        # ★ CANONICAL.
        sa.Column(
            "tile_bounds",
            geoalchemy2.types.Geography(
                geometry_type="POLYGON", srid=4326, spatial_index=False
            ),
            nullable=False,
        ),
        # ★ Derived, denormalised on purpose — written by the SAME transaction from the
        # SAME source arithmetic, not reprojected from tile_bounds, so no round-trip
        # error accumulates. If they ever disagree, tile_bounds wins.
        sa.Column(
            "tile_bounds_3857",
            geoalchemy2.types.Geometry(
                geometry_type="POLYGON", srid=3857, spatial_index=False
            ),
            nullable=True,
        ),
        sa.Column("satellite_image_path", sa.Text(), nullable=True),
        sa.Column("satellite_checksum", sa.CHAR(64), nullable=True),
        sa.Column("satellite_width_px", sa.Integer(), nullable=True),
        sa.Column("satellite_height_px", sa.Integer(), nullable=True),
        # ★ 9 elems, ROW-MAJOR. IMAGE PIXEL → SATELLITE MOSAIC PIXEL. It ends in
        # PIXELS: not metres, not degrees (§5.8 rule 1).
        sa.Column("homography", postgresql.ARRAY(sa.Double(), dimensions=1), nullable=True),
        # ★ 6 elems, GDAL order. MOSAIC PIXEL → sat_geotransform_srid. The +0.5
        # pixel-centre convention is not optional (§4.18).
        sa.Column("sat_geotransform", postgresql.ARRAY(sa.Double(), dimensions=1), nullable=True),
        # ★ 3857 for slippy providers; a UTM code for local_orthophoto. Reprojecting an
        # orthophoto resamples it — throwing away the accuracy that is the entire
        # reason to mount one.
        sa.Column(
            "sat_geotransform_srid", sa.Integer(), server_default=sa.text("4326"), nullable=False
        ),
        sa.Column("imagery_captured_at", sa.DateTime(timezone=True), nullable=True),
        # ★ Served from THIS ROW, never by re-resolving the provider — which may have
        # been reconfigured since.
        sa.Column("attribution", sa.Text(), nullable=False),
        sa.Column("terms_url", sa.Text(), nullable=True),
        sa.Column("gsd_m", sa.Double(), nullable=True),
        sa.Column("georef_ce90_m", sa.Double(), nullable=True),
        sa.Column(
            "is_authoritative", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("feature_extractor_used", _FEATURE_EXTRACTOR, nullable=True),
        sa.Column("feature_matcher_used", _FEATURE_MATCHER, nullable=True),
        sa.Column("estimator_used", _ROBUST_ESTIMATOR, nullable=True),
        sa.Column("keypoints_query", sa.Integer(), nullable=True),
        sa.Column("keypoints_train", sa.Integer(), nullable=True),
        sa.Column("raw_matches", sa.Integer(), nullable=True),
        sa.Column("good_matches", sa.Integer(), nullable=True),
        sa.Column("inlier_count", sa.Integer(), nullable=False),
        sa.Column("inlier_ratio", sa.Double(), nullable=True),
        sa.Column("ransac_reproj_error_px", sa.Double(), nullable=True),
        sa.Column("ransac_threshold_px", sa.Double(), nullable=True),
        sa.Column("ransac_iterations", sa.Integer(), nullable=True),
        # ★ Stored rather than checked-and-discarded: "why did the algorithm reject
        # this obviously-correct-looking tile?" becomes a SELECT.
        sa.Column("homography_condition_number", sa.Double(), nullable=True),
        sa.Column("homography_determinant", sa.Double(), nullable=True),
        sa.Column("view_regime", sa.Text(), nullable=True),
        sa.Column("degeneracy_gate", sa.Double(), nullable=True),
        sa.Column(
            "degeneracy_report",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        # Every sub-score nullable: invariant I3 — no column requires a deep model.
        sa.Column("feature_similarity_score", sa.Double(), nullable=True),
        sa.Column("geometric_consistency_score", sa.Double(), nullable=True),
        sa.Column("landmark_consistency_score", sa.Double(), nullable=True),
        sa.Column("semantic_similarity_score", sa.Double(), nullable=True),
        sa.Column(
            "overall_confidence", sa.Double(), server_default=sa.text("0.0"), nullable=False
        ),
        sa.Column(
            "score_breakdown",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "score_feature_vector", postgresql.ARRAY(sa.Double(), dimensions=1), nullable=True
        ),
        sa.Column("calibrated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "calibration_id", sa.Text(), server_default=sa.text("'identity'"), nullable=False
        ),
        sa.Column("degraded", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("degradation_reason", sa.Text(), nullable=True),
        sa.Column(
            "quality_flags",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "homography IS NULL OR array_length(homography, 1) = 9",
            name="ck_match_results_homography_arity",
        ),
        sa.CheckConstraint(
            "sat_geotransform IS NULL OR array_length(sat_geotransform, 1) = 6",
            name="ck_match_results_geotransform_arity",
        ),
        sa.CheckConstraint(
            "tile_z IS NULL OR tile_z BETWEEN 0 AND 22", name="ck_match_results_tile_z"
        ),
        sa.CheckConstraint(
            "tile_z IS NULL"
            " OR (tile_x >= 0 AND tile_x < (1 << tile_z)"
            "     AND tile_y >= 0 AND tile_y < (1 << tile_z))",
            name="ck_match_results_tile_xy",
        ),
        sa.CheckConstraint(
            "(tile_z IS NULL) = (tile_x IS NULL) AND (tile_z IS NULL) = (tile_y IS NULL)",
            name="ck_match_results_tile_triple",
        ),
        sa.CheckConstraint(
            "mosaic_cols > 0 AND mosaic_rows > 0", name="ck_match_results_mosaic"
        ),
        sa.CheckConstraint("rank >= 1", name="ck_match_results_rank"),
        sa.CheckConstraint("inlier_count >= 0", name="ck_match_results_inliers"),
        sa.CheckConstraint(
            "inlier_ratio IS NULL OR inlier_ratio BETWEEN 0 AND 1",
            name="ck_match_results_inlier_ratio",
        ),
        sa.CheckConstraint(
            "(feature_similarity_score IS NULL"
            "  OR feature_similarity_score BETWEEN 0 AND 1)"
            " AND (geometric_consistency_score IS NULL"
            "  OR geometric_consistency_score BETWEEN 0 AND 1)"
            " AND (landmark_consistency_score IS NULL"
            "  OR landmark_consistency_score BETWEEN 0 AND 1)"
            " AND (semantic_similarity_score IS NULL"
            "  OR semantic_similarity_score BETWEEN 0 AND 1)",
            name="ck_match_results_subscores",
        ),
        sa.CheckConstraint(
            "overall_confidence BETWEEN 0 AND 100", name="ck_match_results_overall"
        ),
        sa.CheckConstraint(
            "degeneracy_gate IS NULL OR degeneracy_gate BETWEEN 0 AND 1",
            name="ck_match_results_degeneracy_gate",
        ),
        # ★ The SRID is meaningful IFF the geotransform exists.
        sa.CheckConstraint(
            "(sat_geotransform IS NOT NULL) OR (sat_geotransform_srid = 4326)",
            name="ck_match_results_srid_iff_gt",
        ),
        sa.CheckConstraint(
            "sat_geotransform_srid BETWEEN 1024 AND 32767 OR sat_geotransform_srid = 4326",
            name="ck_match_results_srid_range",
        ),
        # ★ A SELECTED result is complete. A losing candidate is allowed to be a scored
        # rejection and nothing more — §11.6 REQUIRES that rejections be persisted with
        # their DegeneracyReport, and a rejection has no homography and no estimator.
        sa.CheckConstraint(
            "NOT is_selected OR ("
            " homography             IS NOT NULL AND"
            " sat_geotransform       IS NOT NULL AND"
            " sat_geotransform_srid  IS NOT NULL AND"
            " satellite_image_path   IS NOT NULL AND"
            " feature_extractor_used IS NOT NULL AND"
            " feature_matcher_used   IS NOT NULL AND"
            " estimator_used         IS NOT NULL)",
            name="ck_match_results_selected_is_complete",
        ),
        sa.ForeignKeyConstraint(
            ["match_job_id"],
            ["match_jobs.id"],
            name="fk_match_results_match_job_id_match_jobs",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_match_result_id"],
            ["match_results.id"],
            name="fk_match_results_parent_match_result_id_match_results",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_match_results"),
    )


def downgrade() -> None:
    op.drop_table("match_results")
    # Drop one side of the cycle before the tables, or PostgreSQL refuses both.
    op.drop_constraint(
        "fk_batch_job_items_match_job_id_match_jobs",
        "batch_job_items",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_match_jobs_batch_job_item_id_batch_job_items",
        "match_jobs",
        type_="foreignkey",
    )
    op.drop_table("batch_job_items")
    op.drop_table("match_jobs")
    op.drop_table("batch_jobs")
