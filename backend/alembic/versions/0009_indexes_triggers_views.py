"""indexes triggers views

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-17

The non-implied indexes · the ``updated_at`` triggers · the ``v_jobs`` view · the one
statistics target that matters.

**Why every index is here and none is in 0003–0008.** Almost every index in §5.6 is a
*partial* index, a GIST, or a trigram GIN — none of which a column definition implies —
and ``spatial_index=False`` is set on every spatial column precisely so GeoAlchemy2 does
**not** create one behind our back with a name it chooses (§5.4). Declaring them
together makes the access-path design reviewable as a set instead of scattered across
six files.
"""

from __future__ import annotations

from typing import Sequence

import geoalchemy2  # noqa: F401  # ★ see script.py.mako — never remove
import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The live (non-terminal) job states. Every job table's "find me work" index is partial
#: on this set: the terminal rows are the overwhelming majority and a worker never
#: scans them.
_LIVE = "('pending', 'queued', 'running', 'retrying')"

#: Every table carrying ``updated_at``, and only those. The trigger — not the ORM —
#: maintains it, so a Celery bulk UPDATE cannot skip it (§5.4).
#:
#: Deliberately absent, because they have no ``updated_at`` to maintain: the five
#: append-only tables — ``project_revisions``, ``annotation_versions``,
#: ``match_results``, ``confidence_heatmaps``, ``confidence_heatmap_cells`` and
#: ``semantic_features``. They are written once and never amended; a row that could be
#: silently amended is not an audit record.
_UPDATED_AT_TABLES: tuple[str, ...] = (
    "projects",
    "images",
    "annotations",
    "match_jobs",
    "aux_jobs",
    "batch_jobs",
    "batch_job_items",
    "gcps",
    "camera_poses",
    "landmark_suggestions",
    "exports",
)

#: ``CREATE INDEX`` statements, in table order. Written as SQL rather than
#: ``op.create_index`` because half of them need ``DESC``, a partial ``WHERE``, an
#: operator class, or ``USING gist`` — and a list of literal DDL is what a reviewer of
#: an access-path design actually wants to read.
_INDEXES: tuple[str, ...] = (
    # ── projects ─────────────────────────────────────────────────────────────
    "CREATE INDEX ix_projects_owner_active ON projects (owner_id, updated_at DESC)"
    " WHERE deleted_at IS NULL",
    "CREATE INDEX ix_projects_name_trgm ON projects USING gin (name gin_trgm_ops)",
    "CREATE INDEX ix_projects_aoi ON projects USING gist (aoi)",
    "CREATE INDEX ix_projects_tags ON projects USING gin (tags)",
    # ── images ───────────────────────────────────────────────────────────────
    "CREATE UNIQUE INDEX uq_images_storage_path ON images (storage_path)",
    "CREATE UNIQUE INDEX uq_images_project_checksum ON images (project_id, checksum_sha256)"
    " WHERE deleted_at IS NULL",
    "CREATE INDEX ix_images_project_uploaded ON images (project_id, uploaded_at DESC)"
    " WHERE deleted_at IS NULL",
    "CREATE INDEX ix_images_filename_trgm ON images USING gin (filename gin_trgm_ops)",
    "CREATE INDEX ix_images_exif_gps ON images USING gist (exif_gps)"
    " WHERE exif_gps IS NOT NULL",
    "CREATE INDEX ix_images_bounds ON images USING gist (bounds) WHERE bounds IS NOT NULL",
    "CREATE INDEX ix_images_exif_gin ON images USING gin (exif jsonb_path_ops)",
    "CREATE INDEX ix_images_camera ON images (camera_make, camera_model)"
    " WHERE camera_make IS NOT NULL",
    "CREATE INDEX ix_images_status ON images (status) WHERE status <> 'ready'",
    # ── project_revisions ────────────────────────────────────────────────────
    "CREATE INDEX ix_project_revisions_project_seq ON project_revisions (project_id, seq DESC)",
    # ★ "nearest preceding checkpoint" in one backward index scan.
    "CREATE INDEX ix_project_revisions_checkpoints ON project_revisions (project_id, seq DESC)"
    " WHERE is_checkpoint",
    "CREATE INDEX ix_project_revisions_snapshot ON project_revisions"
    " USING gin (snapshot jsonb_path_ops) WHERE is_checkpoint",
    # ── annotations ──────────────────────────────────────────────────────────
    "CREATE INDEX ix_annotations_image_order ON annotations (image_id, ordering, created_at)"
    " WHERE is_deleted = FALSE",
    "CREATE INDEX ix_annotations_pixel_geom ON annotations USING gist (pixel_geom)",
    "CREATE INDEX ix_annotations_kind ON annotations (image_id, kind) WHERE is_deleted = FALSE",
    "CREATE INDEX ix_annotations_attributes ON annotations"
    " USING gin (attributes jsonb_path_ops)",
    "CREATE INDEX ix_annotations_revision ON annotations (revision_seq)",
    # ── annotation_versions ──────────────────────────────────────────────────
    "CREATE UNIQUE INDEX uq_annotation_versions_annotation_version ON annotation_versions"
    " (annotation_id, version_no)",
    "CREATE UNIQUE INDEX uq_annotation_versions_client_op ON annotation_versions (client_op_id)"
    " WHERE client_op_id IS NOT NULL",
    # ★ THIS index is what makes undo O(1).
    "CREATE INDEX ix_annotation_versions_annotation ON annotation_versions"
    " (annotation_id, version_no DESC)",
    "CREATE INDEX ix_annotation_versions_image_time ON annotation_versions (image_id, id DESC)",
    "CREATE INDEX ix_annotation_versions_revision ON annotation_versions (revision_id)"
    " WHERE revision_id IS NOT NULL",
    "CREATE INDEX ix_annotation_versions_actor ON annotation_versions (actor_id, id DESC)"
    " WHERE actor_id IS NOT NULL",
    "CREATE INDEX ix_annotation_versions_geom ON annotation_versions"
    " USING gist (pixel_geom_after) WHERE pixel_geom_after IS NOT NULL",
    "CREATE INDEX ix_annotation_versions_after ON annotation_versions"
    " USING gin (after jsonb_path_ops)",
    # ── match_jobs ───────────────────────────────────────────────────────────
    "CREATE UNIQUE INDEX uq_match_jobs_celery_task_id ON match_jobs (celery_task_id)"
    " WHERE celery_task_id IS NOT NULL",
    f"CREATE INDEX ix_match_jobs_status_created ON match_jobs (status, created_at)"
    f" WHERE status IN {_LIVE}",
    "CREATE INDEX ix_match_jobs_image_created ON match_jobs (image_id, created_at DESC)",
    "CREATE INDEX ix_match_jobs_batch_item ON match_jobs (batch_job_item_id)",
    "CREATE INDEX ix_match_jobs_search_aoi ON match_jobs USING gist (search_aoi)"
    " WHERE search_aoi IS NOT NULL",
    "CREATE INDEX ix_match_jobs_params ON match_jobs USING gin (params jsonb_path_ops)",
    # ── aux_jobs ─────────────────────────────────────────────────────────────
    "CREATE UNIQUE INDEX uq_aux_jobs_celery_task_id ON aux_jobs (celery_task_id)"
    " WHERE celery_task_id IS NOT NULL",
    f"CREATE INDEX ix_aux_jobs_status_created ON aux_jobs (status, created_at)"
    f" WHERE status IN {_LIVE}",
    "CREATE INDEX ix_aux_jobs_image_type ON aux_jobs (image_id, type, created_at DESC)",
    # ── batch_jobs / batch_job_items ─────────────────────────────────────────
    "CREATE UNIQUE INDEX uq_batch_jobs_celery_group_id ON batch_jobs (celery_group_id)"
    " WHERE celery_group_id IS NOT NULL",
    "CREATE INDEX ix_batch_jobs_project_created ON batch_jobs (project_id, created_at DESC)",
    f"CREATE INDEX ix_batch_jobs_status ON batch_jobs (status, created_at)"
    f" WHERE status IN {_LIVE}",
    # ★ Prevents the double-click-submit bug IN THE DATABASE.
    "CREATE UNIQUE INDEX uq_batch_job_items_batch_image ON batch_job_items"
    " (batch_job_id, image_id)",
    "CREATE UNIQUE INDEX uq_batch_job_items_batch_ordinal ON batch_job_items"
    " (batch_job_id, ordinal)",
    "CREATE INDEX ix_batch_job_items_batch_status ON batch_job_items (batch_job_id, status)",
    "CREATE INDEX ix_batch_job_items_image ON batch_job_items (image_id)",
    # ── match_results ────────────────────────────────────────────────────────
    "CREATE UNIQUE INDEX uq_match_results_job_rank ON match_results (match_job_id, rank)",
    # ★ At most ONE selected per job — enforced by the database, not by hope.
    "CREATE UNIQUE INDEX uq_match_results_job_selected ON match_results (match_job_id)"
    " WHERE is_selected",
    "CREATE INDEX ix_match_results_job_conf ON match_results"
    " (match_job_id, overall_confidence DESC)",
    "CREATE INDEX ix_match_results_tile ON match_results (provider, tile_z, tile_x, tile_y)",
    "CREATE INDEX ix_match_results_tile_bounds ON match_results USING gist (tile_bounds)",
    "CREATE INDEX ix_match_results_tile_bounds_3857 ON match_results"
    " USING gist (tile_bounds_3857) WHERE tile_bounds_3857 IS NOT NULL",
    "CREATE INDEX ix_match_results_score_breakdown ON match_results"
    " USING gin (score_breakdown jsonb_path_ops)",
    "CREATE INDEX ix_match_results_parent ON match_results (parent_match_result_id)"
    " WHERE parent_match_result_id IS NOT NULL",
    # ── gcps ─────────────────────────────────────────────────────────────────
    "CREATE UNIQUE INDEX uq_gcps_landmark_match ON gcps (landmark_id, match_result_id)"
    " WHERE landmark_id IS NOT NULL",
    "CREATE UNIQUE INDEX uq_gcps_image_code ON gcps (image_id, code) WHERE code IS NOT NULL",
    "CREATE INDEX ix_gcps_image ON gcps (image_id)",
    "CREATE INDEX ix_gcps_match_result ON gcps (match_result_id)",
    "CREATE INDEX ix_gcps_landmark ON gcps (landmark_id) WHERE landmark_id IS NOT NULL",
    # ★ The hottest spatial query in the product.
    "CREATE INDEX ix_gcps_geom ON gcps USING gist (geom)",
    "CREATE INDEX ix_gcps_export ON gcps (image_id, confidence DESC)"
    " WHERE is_included_in_export",
    "CREATE INDEX ix_gcps_adjusted ON gcps (adjusted_at DESC) WHERE manually_adjusted",
    "CREATE INDEX ix_gcps_stale ON gcps (image_id) WHERE is_stale",
    # ★ Added with the `source` column (SCOPE.md §5): every export and every GCP table
    # read filters or groups by it, because an observed coordinate and an inferred one
    # must never be presented as the same thing.
    "CREATE INDEX ix_gcps_source ON gcps (image_id, source)",
    # ── camera_poses ─────────────────────────────────────────────────────────
    "CREATE UNIQUE INDEX uq_camera_poses_image_selected ON camera_poses (image_id)"
    " WHERE is_selected",
    "CREATE INDEX ix_camera_poses_image ON camera_poses (image_id, confidence DESC)",
    "CREATE INDEX ix_camera_poses_position ON camera_poses USING gist (position)",
    "CREATE INDEX ix_camera_poses_footprint ON camera_poses USING gist (footprint)"
    " WHERE footprint IS NOT NULL",
    "CREATE INDEX ix_camera_poses_match_result ON camera_poses (match_result_id)"
    " WHERE match_result_id IS NOT NULL",
    # ── confidence_heatmaps / _cells ─────────────────────────────────────────
    "CREATE UNIQUE INDEX uq_confidence_heatmaps_job ON confidence_heatmaps (match_job_id)",
    "CREATE INDEX ix_confidence_heatmaps_image ON confidence_heatmaps"
    " (image_id, created_at DESC)",
    "CREATE INDEX ix_confidence_heatmaps_bbox ON confidence_heatmaps USING gist (bbox)",
    "CREATE INDEX ix_confidence_heatmaps_argmax ON confidence_heatmaps"
    " USING gist (argmax_geom) WHERE argmax_geom IS NOT NULL",
    "CREATE UNIQUE INDEX uq_confidence_heatmap_cells_grid ON confidence_heatmap_cells"
    ' (heatmap_id, col, "row")',
    "CREATE INDEX ix_confidence_heatmap_cells_geom ON confidence_heatmap_cells"
    " USING gist (geom)",
    "CREATE INDEX ix_confidence_heatmap_cells_heatmap_score ON confidence_heatmap_cells"
    " (heatmap_id, score DESC)",
    # ── semantic_features ────────────────────────────────────────────────────
    'CREATE INDEX ix_semantic_features_image_class ON semantic_features (image_id, "class")',
    "CREATE INDEX ix_semantic_features_pixel_geom ON semantic_features"
    " USING gist (pixel_geom) WHERE pixel_geom IS NOT NULL",
    "CREATE INDEX ix_semantic_features_geo_geom ON semantic_features USING gist (geo_geom)"
    " WHERE geo_geom IS NOT NULL",
    "CREATE INDEX ix_semantic_features_match_result ON semantic_features (match_result_id)"
    " WHERE match_result_id IS NOT NULL",
    "CREATE INDEX ix_semantic_features_attributes ON semantic_features"
    " USING gin (attributes jsonb_path_ops)",
    'CREATE INDEX ix_semantic_features_class_space_conf ON semantic_features'
    ' ("class", space, confidence DESC)',
    # ── landmark_suggestions ─────────────────────────────────────────────────
    "CREATE INDEX ix_landmark_suggestions_image_rank ON landmark_suggestions (image_id, rank)"
    " WHERE status = 'pending'",
    "CREATE INDEX ix_landmark_suggestions_job ON landmark_suggestions (aux_job_id)",
    "CREATE INDEX ix_landmark_suggestions_geom ON landmark_suggestions"
    " USING gist (pixel_geom)",
    # ── exports ──────────────────────────────────────────────────────────────
    "CREATE UNIQUE INDEX uq_exports_celery_task_id ON exports (celery_task_id)"
    " WHERE celery_task_id IS NOT NULL",
    "CREATE INDEX ix_exports_project_created ON exports (project_id, created_at DESC)",
    "CREATE INDEX ix_exports_image ON exports (image_id) WHERE image_id IS NOT NULL",
    "CREATE INDEX ix_exports_status ON exports (status, created_at)"
    " WHERE status IN ('pending', 'queued', 'running')",
    "CREATE INDEX ix_exports_expires ON exports (expires_at)"
    " WHERE expires_at IS NOT NULL AND status = 'succeeded'",
    "CREATE INDEX ix_exports_options ON exports USING gin (options jsonb_path_ops)",
)

#: §5.5, written out per branch. There are **no** common columns across the four job
#: tables — v1.0's "project the common JobRead columns" described a view that could not
#: be written — so each branch supplies its own joins and literals, and a literal is
#: clearer than a nullable column nobody writes.
_V_JOBS = """
CREATE VIEW v_jobs AS
-- ── match ────────────────────────────────────────────────────────────────────
SELECT j.id, 'match'::job_type AS type, j.status,
       j.image_id, i.project_id,                       -- ★ project_id via images
       bi.batch_job_id AS batch_id,                    -- ★ batch_id via batch_job_items
       j.cancel_requested, j.attempt, j.max_attempts,
       j.progress, COALESCE(j.progress_stage, 'pending') AS progress_stage,
       j.progress_message, j.tiles_fetched, j.tiles_total, j.candidates_evaluated,
       j.degraded, j.degradation_reason, j.warnings,
       j.error_type, j.error_message,
       j.queued_at, j.started_at, j.finished_at, j.duration_ms,
       j.created_at, j.updated_at
  FROM match_jobs j
  JOIN images i ON i.id = j.image_id
  LEFT JOIN batch_job_items bi ON bi.id = j.batch_job_item_id
UNION ALL
-- ── aux: segment | suggest_landmarks | gcp_recompute | ingest ────────────────
SELECT a.id, a.type, a.status,
       a.image_id, i.project_id, NULL::uuid AS batch_id,
       a.cancel_requested, a.attempt, a.max_attempts,
       a.progress, COALESCE(a.progress_stage, 'pending'), a.progress_message,
       NULL::int, NULL::int, NULL::int,
       a.degraded, a.degradation_reason, a.warnings,
       a.error_type, a.error_message,
       a.queued_at, a.started_at, a.finished_at, a.duration_ms,
       a.created_at, a.updated_at
  FROM aux_jobs a
  JOIN images i ON i.id = a.image_id
UNION ALL
-- ── batch ───────────────────────────────────────────────────────────────────
SELECT b.id, 'batch'::job_type, b.status,
       NULL::uuid AS image_id, b.project_id, b.id AS batch_id,
       b.cancel_requested, b.attempt, b.max_attempts,
       b.progress, COALESCE(b.progress_stage, 'pending'), NULL::text,
       NULL::int, NULL::int, b.completed_items AS candidates_evaluated,
       b.degraded, b.degradation_reason, b.warnings,
       NULL::text, b.error_message,
       b.queued_at, b.started_at, b.finished_at, b.duration_ms,
       b.created_at, b.updated_at
  FROM batch_jobs b
UNION ALL
-- ── export ──────────────────────────────────────────────────────────────────
SELECT e.id, 'export'::job_type, e.status,
       e.image_id, e.project_id, NULL::uuid AS batch_id,
       e.cancel_requested, e.attempt, e.max_attempts,
       e.progress, COALESCE(e.progress_stage, 'pending'), e.progress_message,
       NULL::int, NULL::int, e.gcp_count AS candidates_evaluated,
       e.degraded, e.degradation_reason, e.warnings,
       NULL::text, e.error_message,
       e.queued_at, e.started_at, e.finished_at, e.duration_ms,
       e.created_at, e.updated_at
  FROM exports e
"""


def upgrade() -> None:
    for statement in _INDEXES:
        op.execute(statement)

    # ── the updated_at triggers ──────────────────────────────────────────────
    # tg_set_updated_at() was created in 0001; it is attached here, once every table
    # exists. BEFORE UPDATE FOR EACH ROW: a bulk UPDATE from a Celery task gets the
    # same treatment as an ORM flush, which is the entire point (§5.4).
    for table in _UPDATED_AT_TABLES:
        op.execute(
            f"CREATE TRIGGER tg_{table}_set_updated_at BEFORE UPDATE ON {table}"
            f" FOR EACH ROW EXECUTE FUNCTION tg_set_updated_at()"
        )

    op.execute(_V_JOBS)

    # ★ PostGIS GIST selectivity depends on the sampled geometry histogram, and the
    # default (100) badly misestimates viewport queries on clustered survey data —
    # producing a seq scan on the hottest query in the product.
    op.execute("ALTER TABLE gcps ALTER COLUMN geom SET STATISTICS 1000")

    # §5.9 — annotation_versions is append-only and the fastest-growing table: its
    # stats matter and its dead tuples do not.
    op.execute(
        "ALTER TABLE annotation_versions SET ("
        " autovacuum_vacuum_scale_factor = 0.2,"
        " autovacuum_analyze_scale_factor = 0.02)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE annotation_versions RESET ("
               " autovacuum_vacuum_scale_factor, autovacuum_analyze_scale_factor)")
    op.execute("ALTER TABLE gcps ALTER COLUMN geom SET STATISTICS -1")
    op.execute("DROP VIEW IF EXISTS v_jobs")
    for table in _UPDATED_AT_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS tg_{table}_set_updated_at ON {table}")
    for statement in reversed(_INDEXES):
        name = statement.split(" ON ")[0].split()[-1]
        op.execute(f"DROP INDEX IF EXISTS {name}")
