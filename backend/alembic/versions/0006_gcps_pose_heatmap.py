"""gcps pose heatmap

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-17

``gcps`` · ``camera_poses`` · ``confidence_heatmaps`` · ``confidence_heatmap_cells``.

★ ``gcps`` is **the deliverable**. ``gcps.geom`` is the canonical truth of the entire
system (§5.8 step [7]); everything after it is serialisation and nothing before it is
stored as a coordinate.

★ **Three deviations from §5.6, all forced by SCOPE.md §5 (manual GCP mode), all
widening rather than narrowing** — see ``app/models/gcp.py`` for the full argument:
``source`` is added (Text + CHECK, not an 18th enum, because §5.3 is normative that
there are exactly seventeen); ``match_result_id`` and ``satellite_pixel_x/y`` become
nullable because a manual GCP has no homography and no mosaic, and
``ck_gcps_automatic_has_provenance`` re-imposes invariant I2 exactly where it applies.
Without this, the product's core interaction is unwritable.

★ SCOPE.md §4 rule 5: ``camera_poses`` and the heatmap tables are created exactly as
specified though pose estimation and the heatmap are deferred.
"""

from __future__ import annotations

from typing import Sequence

import geoalchemy2  # noqa: F401  # ★ see script.py.mako — never remove
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GCP_STALE_REASON = postgresql.ENUM(
    "landmark_moved", "landmark_deleted", "homography_superseded", "annotations_restored",
    name="gcp_stale_reason",
    create_type=False,
)
_POSE_METHOD = postgresql.ENUM(
    "zhang_plane", "homography_decomposition", "pnp", "exif_gps_only", "manual",
    "heatmap_argmax",
    name="pose_method",
    create_type=False,
)


def upgrade() -> None:
    op.create_table(
        "gcps",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("image_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("landmark_id", postgresql.UUID(as_uuid=True), nullable=True),
        # ★ Nullable ONLY for source='manual'; RESTRICT unchanged. See the docstring.
        sa.Column("match_result_id", postgresql.UUID(as_uuid=True), nullable=True),
        # ★ SCOPE.md §5: an observed coordinate can never be confused with an inferred
        # one, downstream or in an export.
        sa.Column("source", sa.Text(), server_default=sa.text("'manual'"), nullable=False),
        sa.Column("code", sa.Text(), nullable=True),
        sa.Column("pixel_x", sa.Double(), nullable=False),
        sa.Column("pixel_y", sa.Double(), nullable=False),
        sa.Column("satellite_pixel_x", sa.Double(), nullable=True),
        sa.Column("satellite_pixel_y", sa.Double(), nullable=True),
        # ★ Makes `residual_px IS NULL` distinguishable from `residual_px = 0`.
        sa.Column("has_direct_fix", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        # ★ THE CANONICAL TRUTH.
        sa.Column(
            "geom",
            geoalchemy2.types.Geography(
                geometry_type="POINT", srid=4326, spatial_index=False
            ),
            nullable=False,
        ),
        sa.Column("elevation_m", sa.Double(), nullable=True),
        sa.Column("elevation_source", sa.Text(), nullable=True),
        sa.Column("elevation_ce90_m", sa.Double(), nullable=True),
        # ★ 0–100. In manual mode: SURVEYOR-DECLARED, never computed (SCOPE.md §5).
        sa.Column("confidence", sa.Double(), nullable=False),
        sa.Column("accuracy_relative_ce90_m", sa.Double(), nullable=False),
        sa.Column("georef_ce90_m", sa.Double(), nullable=False),
        # ★ THE headline number.
        sa.Column("accuracy_total_ce90_m", sa.Double(), nullable=False),
        sa.Column("accuracy_semi_major_ce90_m", sa.Double(), nullable=True),
        sa.Column("accuracy_semi_minor_ce90_m", sa.Double(), nullable=True),
        sa.Column("accuracy_azimuth_deg", sa.Double(), nullable=True),
        sa.Column("accuracy_dominant_term", sa.Text(), nullable=False),
        sa.Column("residual_px", sa.Double(), nullable=True),
        sa.Column(
            "manually_adjusted", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        # ★ The algorithm's answer, kept forever.
        sa.Column(
            "original_geom",
            geoalchemy2.types.Geography(
                geometry_type="POINT", srid=4326, spatial_index=False
            ),
            nullable=True,
        ),
        sa.Column("original_satellite_pixel_x", sa.Double(), nullable=True),
        sa.Column("original_satellite_pixel_y", sa.Double(), nullable=True),
        sa.Column("original_confidence", sa.Double(), nullable=True),
        sa.Column("adjustment_offset_m", sa.Double(), nullable=True),
        sa.Column("adjusted_by", sa.Text(), nullable=True),
        sa.Column("adjusted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("adjustment_note", sa.Text(), nullable=True),
        sa.Column("is_stale", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("stale_reason", _GCP_STALE_REASON, nullable=True),
        sa.Column(
            "is_included_in_export", sa.Boolean(), server_default=sa.text("true"), nullable=False
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
        sa.CheckConstraint("source IN ('manual', 'automatic')", name="ck_gcps_source"),
        # ★ Invariant I2 (provenance is total), expressed exactly where it applies: an
        # INFERRED coordinate cannot exist without the evidence that inferred it. An
        # OBSERVED one needs no homography, because nothing was inferred.
        sa.CheckConstraint(
            "source <> 'automatic' OR ("
            " match_result_id   IS NOT NULL AND"
            " satellite_pixel_x IS NOT NULL AND"
            " satellite_pixel_y IS NOT NULL)",
            name="ck_gcps_automatic_has_provenance",
        ),
        sa.CheckConstraint("confidence BETWEEN 0 AND 100", name="ck_gcps_confidence"),
        sa.CheckConstraint("pixel_x >= 0 AND pixel_y >= 0", name="ck_gcps_pixel_nonneg"),
        sa.CheckConstraint(
            "code IS NULL OR code ~ '^[A-Za-z0-9_\\-]{1,32}$'", name="ck_gcps_code_format"
        ),
        sa.CheckConstraint(
            "elevation_m IS NULL OR elevation_m BETWEEN -500 AND 9000",
            name="ck_gcps_elevation_sane",
        ),
        # ★ The source may never name a producer that did not run (§4.27).
        sa.CheckConstraint(
            "(elevation_m IS NULL) = (elevation_source IS NULL)",
            name="ck_gcps_elevation_source_consistent",
        ),
        sa.CheckConstraint(
            "accuracy_relative_ce90_m >= 0"
            " AND georef_ce90_m >= 0"
            " AND accuracy_total_ce90_m >= 0"
            " AND (accuracy_semi_major_ce90_m IS NULL OR accuracy_semi_major_ce90_m >= 0)"
            " AND (accuracy_semi_minor_ce90_m IS NULL OR accuracy_semi_minor_ce90_m >= 0)",
            name="ck_gcps_accuracy_nonneg",
        ),
        # ★ A quadrature can never be smaller than either leg. Catches a unit or sign
        # slip in combine_accuracy at write time, not in a deliverable.
        sa.CheckConstraint(
            "accuracy_total_ce90_m >= greatest(accuracy_relative_ce90_m, georef_ce90_m)",
            name="ck_gcps_accuracy_total_ge_parts",
        ),
        sa.CheckConstraint(
            "accuracy_dominant_term IN"
            " ('match', 'georeference', 'landmark_click', 'rectification')",
            name="ck_gcps_accuracy_dominant_term",
        ),
        sa.CheckConstraint(
            "has_direct_fix OR residual_px IS NULL", name="ck_gcps_residual_iff_direct_fix"
        ),
        sa.CheckConstraint(
            "NOT manually_adjusted OR (adjusted_at IS NOT NULL AND original_geom IS NOT NULL)",
            name="ck_gcps_adjustment_complete",
        ),
        sa.CheckConstraint(
            "manually_adjusted OR ("
            " original_geom IS NULL AND"
            " original_satellite_pixel_x IS NULL AND"
            " original_satellite_pixel_y IS NULL AND"
            " original_confidence IS NULL AND"
            " adjustment_offset_m IS NULL AND"
            " adjusted_by IS NULL AND"
            " adjusted_at IS NULL AND"
            " adjustment_note IS NULL)",
            name="ck_gcps_no_adjustment_metadata_unless_adjusted",
        ),
        sa.CheckConstraint("(is_stale) = (stale_reason IS NOT NULL)", name="ck_gcps_stale_reason"),
        # ★ CASCADE: deleting the photo deletes everything derived from it.
        sa.ForeignKeyConstraint(
            ["image_id"], ["images.id"], name="fk_gcps_image_id_images", ondelete="CASCADE"
        ),
        # ★ SET NULL: the surveyor may tidy up annotations; the coordinate they already
        # exported must survive, orphaned but intact. pixel_x/pixel_y are copied onto
        # the GCP precisely so it stays self-describing afterwards.
        sa.ForeignKeyConstraint(
            ["landmark_id"],
            ["annotations.id"],
            name="fk_gcps_landmark_id_annotations",
            ondelete="SET NULL",
        ),
        # ★ RESTRICT — the load-bearing one. A GCP is a claim about the world; the
        # homography is the evidence. Letting the evidence be deleted while the claim
        # persists would let LandExplorer emit a coordinate it cannot justify. It also
        # means the 30-day retention job that prunes losing candidates does not need to
        # know about GCPs — the FK protects them.
        sa.ForeignKeyConstraint(
            ["match_result_id"],
            ["match_results.id"],
            name="fk_gcps_match_result_id_match_results",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_gcps"),
    )

    op.create_table(
        "camera_poses",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("image_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("match_result_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "position",
            geoalchemy2.types.Geography(
                geometry_type="POINT", srid=4326, spatial_index=False
            ),
            nullable=False,
        ),
        sa.Column("altitude_m", sa.Double(), nullable=True),
        # ★ 0 = TRUE North, clockwise. PoseResult.yaw_deg is 0 = up the window raster;
        # only gis.pose.window_yaw_to_north_deg() may convert (§4.28).
        sa.Column("yaw_deg", sa.Double(), nullable=True),
        sa.Column("pitch_deg", sa.Double(), nullable=True),
        sa.Column("roll_deg", sa.Double(), nullable=True),
        sa.Column("hfov_deg", sa.Double(), nullable=True),
        sa.Column("vfov_deg", sa.Double(), nullable=True),
        sa.Column(
            "footprint",
            geoalchemy2.types.Geography(
                geometry_type="POLYGON", srid=4326, spatial_index=False
            ),
            nullable=True,
        ),
        sa.Column("method", _POSE_METHOD, nullable=False),
        sa.Column("confidence", sa.Double(), nullable=False),
        sa.Column("rotation_matrix", postgresql.ARRAY(sa.Double(), dimensions=1), nullable=True),
        sa.Column("intrinsics_k", postgresql.ARRAY(sa.Double(), dimensions=1), nullable=True),
        sa.Column("intrinsics_source", sa.Text(), nullable=True),
        sa.Column("reproj_error_px", sa.Double(), nullable=True),
        sa.Column("inlier_count", sa.Integer(), nullable=True),
        sa.Column("sigma_yaw_deg", sa.Double(), nullable=True),
        sa.Column("sigma_pitch_deg", sa.Double(), nullable=True),
        sa.Column("sigma_roll_deg", sa.Double(), nullable=True),
        sa.Column("is_selected", sa.Boolean(), server_default=sa.text("false"), nullable=False),
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
        # ★ The angle conventions are written into the CHECKs because yaw/pitch/roll
        # conventions are the classic silent-disagreement bug between a CV module and a
        # map renderer. The constraint is the documentation that cannot rot.
        # yaw: 0 = North, clockwise, [0,360).
        sa.CheckConstraint(
            "yaw_deg IS NULL OR (yaw_deg >= 0 AND yaw_deg < 360)", name="ck_camera_poses_yaw"
        ),
        # pitch: 0 = horizon, + = up, [-90,90].
        sa.CheckConstraint(
            "pitch_deg IS NULL OR pitch_deg BETWEEN -90 AND 90", name="ck_camera_poses_pitch"
        ),
        # roll: + = clockwise, [-180,180].
        sa.CheckConstraint(
            "roll_deg IS NULL OR roll_deg BETWEEN -180 AND 180", name="ck_camera_poses_roll"
        ),
        sa.CheckConstraint(
            "(hfov_deg IS NULL OR (hfov_deg > 0 AND hfov_deg < 180))"
            " AND (vfov_deg IS NULL OR (vfov_deg > 0 AND vfov_deg < 180))",
            name="ck_camera_poses_fov",
        ),
        sa.CheckConstraint("confidence BETWEEN 0 AND 100", name="ck_camera_poses_confidence"),
        sa.CheckConstraint(
            "rotation_matrix IS NULL OR array_length(rotation_matrix, 1) = 9",
            name="ck_camera_poses_rotation_arity",
        ),
        sa.CheckConstraint(
            "intrinsics_k IS NULL OR array_length(intrinsics_k, 1) = 9",
            name="ck_camera_poses_intrinsics_arity",
        ),
        # ★ Zhang-plane needs K just as much as homography decomposition does; keying
        # only off the latter let the PRIMARY path write a pose with no intrinsics.
        sa.CheckConstraint(
            "method NOT IN ('zhang_plane', 'homography_decomposition')"
            " OR intrinsics_k IS NOT NULL",
            name="ck_camera_poses_decomp_needs_k",
        ),
        sa.CheckConstraint(
            "method IN ('exif_gps_only', 'manual') OR match_result_id IS NOT NULL",
            name="ck_camera_poses_method_needs_match",
        ),
        sa.ForeignKeyConstraint(
            ["image_id"], ["images.id"], name="fk_camera_poses_image_id_images", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["match_result_id"],
            ["match_results.id"],
            name="fk_camera_poses_match_result_id_match_results",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_camera_poses"),
    )

    op.create_table(
        "confidence_heatmaps",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("match_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("image_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "bbox",
            geoalchemy2.types.Geography(
                geometry_type="POLYGON", srid=4326, spatial_index=False
            ),
            nullable=False,
        ),
        # True metres — only meaningful because storage is geography (§5.2).
        sa.Column("cell_size_m", sa.Double(), nullable=False),
        sa.Column("grid_cols", sa.Integer(), nullable=False),
        sa.Column("grid_rows", sa.Integer(), nullable=False),
        sa.Column("cell_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("min_score", sa.Double(), nullable=True),
        sa.Column("max_score", sa.Double(), nullable=True),
        sa.Column("mean_score", sa.Double(), nullable=True),
        sa.Column(
            "argmax_geom",
            geoalchemy2.types.Geography(
                geometry_type="POINT", srid=4326, spatial_index=False
            ),
            nullable=True,
        ),
        sa.Column("argmax_score", sa.Double(), nullable=True),
        sa.Column("colormap", sa.Text(), server_default=sa.text("'viridis'"), nullable=False),
        sa.Column("render_path", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("grid_cols > 0 AND grid_rows > 0", name="ck_confidence_heatmaps_grid"),
        sa.CheckConstraint("cell_size_m > 0", name="ck_confidence_heatmaps_cell_size"),
        # Sparsity is queryable: absent ≠ score 0, and cell_count vs cols*rows says so.
        sa.CheckConstraint(
            "cell_count >= 0 AND cell_count <= grid_cols * grid_rows",
            name="ck_confidence_heatmaps_cell_count",
        ),
        sa.CheckConstraint(
            "(min_score IS NULL OR min_score BETWEEN 0 AND 1)"
            " AND (max_score IS NULL OR max_score BETWEEN 0 AND 1)"
            " AND (mean_score IS NULL OR mean_score BETWEEN 0 AND 1)"
            " AND (argmax_score IS NULL OR argmax_score BETWEEN 0 AND 1)"
            " AND (min_score IS NULL OR max_score IS NULL OR min_score <= max_score)",
            name="ck_confidence_heatmaps_scores",
        ),
        sa.ForeignKeyConstraint(
            ["match_job_id"],
            ["match_jobs.id"],
            name="fk_confidence_heatmaps_match_job_id_match_jobs",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["image_id"],
            ["images.id"],
            name="fk_confidence_heatmaps_image_id_images",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_confidence_heatmaps"),
    )

    op.create_table(
        "confidence_heatmap_cells",
        # ★ BIGSERIAL (§5.4).
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("heatmap_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("col", sa.Integer(), nullable=False),
        sa.Column("row", sa.Integer(), nullable=False),
        # ★ CENTROID only. The cell polygon is centroid ± cell_size_m/2, fully
        # determined by the parent; storing 10 000 five-vertex polygons is ~5× the
        # bytes and ~5× the GIST index for zero information.
        sa.Column(
            "geom",
            geoalchemy2.types.Geography(
                geometry_type="POINT", srid=4326, spatial_index=False
            ),
            nullable=False,
        ),
        sa.Column("score", sa.Double(), nullable=False),
        # A cell AGGREGATES every candidate whose centre fell in it: sample_count = 1 is
        # far less trustworthy than 12, and the UI dims it accordingly.
        sa.Column("sample_count", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "components",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint("score BETWEEN 0 AND 1", name="ck_confidence_heatmap_cells_score"),
        sa.CheckConstraint("col >= 0 AND row >= 0", name="ck_confidence_heatmap_cells_grid_pos"),
        sa.CheckConstraint(
            "sample_count >= 1", name="ck_confidence_heatmap_cells_sample_count"
        ),
        sa.ForeignKeyConstraint(
            ["heatmap_id"],
            ["confidence_heatmaps.id"],
            name="fk_confidence_heatmap_cells_heatmap_id_confidence_heatmaps",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_confidence_heatmap_cells"),
    )


def downgrade() -> None:
    op.drop_table("confidence_heatmap_cells")
    op.drop_table("confidence_heatmaps")
    op.drop_table("camera_poses")
    op.drop_table("gcps")
