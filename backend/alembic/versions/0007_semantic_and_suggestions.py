"""semantic and suggestions

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-17

``semantic_features`` · ``landmark_suggestions``.

★ SCOPE.md §4 rule 5: both are created exactly as specified though semantic detection
and automatic landmark suggestion are deferred and their endpoints return 501.

★ ``landmark_suggestions.aux_job_id`` is created here as a plain column; **its FK is
added in ``0008``**, which is where §2.4 places ``aux_jobs``. Splitting a column from
its constraint across two migrations is a wart, and the alternative — reordering the
tables against §2.4's named migration list — is a bigger one. Flagged in the PR
description. (This is not the ``0005`` situation: there is no cycle here, only an
ordering imposed by the migration titles.)
"""

from __future__ import annotations

from typing import Sequence

import geoalchemy2  # noqa: F401  # ★ see script.py.mako — never remove
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SEMANTIC_CLASS = postgresql.ENUM(
    "field_border", "road", "irrigation_canal", "tree", "tree_line", "greenhouse",
    "building", "water_body", "crop_row", "bare_soil", "vegetation", "shadow", "unknown",
    name="semantic_class",
    create_type=False,
)
_FEATURE_SPACE = postgresql.ENUM(
    "image_pixel", "satellite_geo", name="feature_space", create_type=False
)
_FEATURE_DETECTOR = postgresql.ENUM(
    "classical_cv", "sam", "dinov2", "manual", "other",
    name="feature_detector",
    create_type=False,
)
_ANNOTATION_KIND = postgresql.ENUM(
    "generic", "field_corner", "field_border", "road", "road_intersection",
    "irrigation_canal", "tree", "tree_line", "greenhouse", "building",
    "building_corner", "water_body", "pole_or_pylon", "fence_post", "crop_row", "other",
    name="annotation_kind",
    create_type=False,
)
_ANNOTATION_GEOM_TYPE = postgresql.ENUM(
    "point", "polyline", "polygon", name="annotation_geom_type", create_type=False
)
_SUGGESTION_STATUS = postgresql.ENUM(
    "pending", "accepted", "rejected", name="suggestion_status", create_type=False
)


def upgrade() -> None:
    op.create_table(
        "semantic_features",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("image_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("match_result_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_annotation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("class", _SEMANTIC_CLASS, nullable=False),
        sa.Column("space", _FEATURE_SPACE, nullable=False),
        sa.Column(
            "detector",
            _FEATURE_DETECTOR,
            server_default=sa.text("'classical_cv'::feature_detector"),
            nullable=False,
        ),
        sa.Column("model_version", sa.Text(), nullable=True),
        sa.Column(
            "pixel_geom",
            geoalchemy2.types.Geometry(
                geometry_type="GEOMETRY", srid=0, spatial_index=False
            ),
            nullable=True,
        ),
        sa.Column(
            "geo_geom",
            geoalchemy2.types.Geography(
                geometry_type="GEOMETRY", srid=4326, spatial_index=False
            ),
            nullable=True,
        ),
        sa.Column("confidence", sa.Double(), nullable=False),
        sa.Column("area_px", sa.Double(), nullable=True),
        sa.Column("area_m2", sa.Double(), nullable=True),
        sa.Column("length_m", sa.Double(), nullable=True),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        # ★ Paths to .npy/FAISS artifacts — never the vectors. pgvector is not in the
        # mandated stack and 768-D float32 × thousands of patches is a poor fit for a
        # row store. A future ADR adding pgvector adds a column here and backfills from
        # these paths; the schema does not change shape.
        sa.Column(
            "embedding_meta",
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
        # ★ THE constraint that makes invariant I1 mechanical for this table: a row
        # lives in image pixel space or in geographic space, never both, never neither.
        sa.CheckConstraint(
            "(space = 'image_pixel' AND pixel_geom IS NOT NULL AND geo_geom IS NULL)"
            " OR (space = 'satellite_geo' AND geo_geom IS NOT NULL AND pixel_geom IS NULL)",
            name="ck_semantic_features_space_xor",
        ),
        sa.CheckConstraint(
            "(space = 'satellite_geo') = (match_result_id IS NOT NULL)",
            name="ck_semantic_features_geo_needs_match",
        ),
        sa.CheckConstraint(
            "(detector = 'manual') = (source_annotation_id IS NOT NULL)",
            name="ck_semantic_features_manual_has_source",
        ),
        sa.CheckConstraint(
            "pixel_geom IS NULL OR ST_SRID(pixel_geom) = 0",
            name="ck_semantic_features_pixel_srid",
        ),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_semantic_features_confidence"),
        sa.CheckConstraint(
            "(area_px IS NULL OR area_px >= 0)"
            " AND (area_m2 IS NULL OR area_m2 >= 0)"
            " AND (length_m IS NULL OR length_m >= 0)",
            name="ck_semantic_features_area",
        ),
        sa.ForeignKeyConstraint(
            ["image_id"],
            ["images.id"],
            name="fk_semantic_features_image_id_images",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["match_result_id"],
            ["match_results.id"],
            name="fk_semantic_features_match_result_id_match_results",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_annotation_id"],
            ["annotations.id"],
            name="fk_semantic_features_source_annotation_id_annotations",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_semantic_features"),
    )

    op.create_table(
        "landmark_suggestions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("image_id", postgresql.UUID(as_uuid=True), nullable=False),
        # ★ The FK lands in 0008, once aux_jobs exists. See the module docstring.
        sa.Column("aux_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "kind",
            _ANNOTATION_KIND,
            server_default=sa.text("'generic'::annotation_kind"),
            nullable=False,
        ),
        sa.Column(
            "geom_type",
            _ANNOTATION_GEOM_TYPE,
            server_default=sa.text("'point'::annotation_geom_type"),
            nullable=False,
        ),
        sa.Column("pixel_x", sa.Double(), nullable=False),
        sa.Column("pixel_y", sa.Double(), nullable=False),
        sa.Column(
            "pixel_geom",
            geoalchemy2.types.Geometry(
                geometry_type="GEOMETRY", srid=0, spatial_index=False
            ),
            nullable=False,
        ),
        sa.Column("score", sa.Double(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column(
            "detector",
            _FEATURE_DETECTOR,
            server_default=sa.text("'classical_cv'::feature_detector"),
            nullable=False,
        ),
        sa.Column("model_version", sa.Text(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column(
            "status",
            _SUGGESTION_STATUS,
            server_default=sa.text("'pending'::suggestion_status"),
            nullable=False,
        ),
        # ★ Set on accept. A suggestion is a proposal; an annotation is an assertion by
        # a human. POST …/accept is the only door between them (ADR-014).
        sa.Column("accepted_annotation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decided_by", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("score BETWEEN 0 AND 1", name="ck_landmark_suggestions_score"),
        sa.CheckConstraint("rank >= 1", name="ck_landmark_suggestions_rank"),
        sa.CheckConstraint(
            "pixel_x >= 0 AND pixel_y >= 0", name="ck_landmark_suggestions_pixel_nonneg"
        ),
        sa.CheckConstraint(
            "status <> 'accepted' OR accepted_annotation_id IS NOT NULL",
            name="ck_landmark_suggestions_accepted",
        ),
        sa.CheckConstraint(
            "(geom_type = 'point' AND GeometryType(pixel_geom) = 'POINT')"
            " OR (geom_type = 'polyline' AND GeometryType(pixel_geom) = 'LINESTRING')"
            " OR (geom_type = 'polygon' AND GeometryType(pixel_geom) = 'POLYGON')",
            name="ck_landmark_suggestions_geom_type_match",
        ),
        sa.CheckConstraint("ST_SRID(pixel_geom) = 0", name="ck_landmark_suggestions_pixel_srid"),
        sa.ForeignKeyConstraint(
            ["image_id"],
            ["images.id"],
            name="fk_landmark_suggestions_image_id_images",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["accepted_annotation_id"],
            ["annotations.id"],
            name="fk_landmark_suggestions_accepted_annotation_id_annotations",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_landmark_suggestions"),
    )


def downgrade() -> None:
    op.drop_table("landmark_suggestions")
    op.drop_table("semantic_features")
