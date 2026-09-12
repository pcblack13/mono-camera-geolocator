"""annotations and versioning

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-17

``project_revisions`` · ``annotations`` · ``annotation_versions`` — the hybrid
event-log + rolling-snapshot design (§5.6).

★ ``annotation_versions.annotation_id`` is **deliberately not an FK**. The log must
outlive the row: under an FK, a ``'create'`` event for an annotation a later hard-delete
removed would force us to either cascade-delete the audit trail (destroying history) or
block the delete. Tolerating dangling references is the normal and correct property of
an append-only ledger.
"""

from __future__ import annotations

from typing import Sequence

import geoalchemy2  # noqa: F401  # ★ see script.py.mako — never remove
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

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
_ANNOTATION_OP = postgresql.ENUM(
    "create", "update", "delete", "restore", name="annotation_op", create_type=False
)


def upgrade() -> None:
    op.create_table(
        "project_revisions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("actor_id", sa.Text(), nullable=True),
        sa.Column("is_checkpoint", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("annotation_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("event_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # ★ Biconditional: a checkpoint has a snapshot, a non-checkpoint has none.
        # "Snapshot present but not marked a checkpoint" is how a replay silently
        # starts from the wrong base.
        sa.CheckConstraint(
            "(is_checkpoint) = (snapshot IS NOT NULL)",
            name="ck_project_revisions_snapshot_iff_checkpoint",
        ),
        sa.CheckConstraint("seq > 0", name="ck_project_revisions_seq_pos"),
        sa.CheckConstraint(
            "annotation_count >= 0", name="ck_project_revisions_annotation_count_nonneg"
        ),
        sa.CheckConstraint(
            "event_count >= 0", name="ck_project_revisions_event_count_nonneg"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_project_revisions_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_project_revisions"),
        sa.UniqueConstraint(
            "project_id", "seq", name="uq_project_revisions_project_seq"
        ),
    )

    op.create_table(
        "annotations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("image_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "kind",
            _ANNOTATION_KIND,
            server_default=sa.text("'generic'::annotation_kind"),
            nullable=False,
        ),
        sa.Column("geom_type", _ANNOTATION_GEOM_TYPE, nullable=False),
        # ★ The representative point for ALL types, derived server-side at write time.
        sa.Column("pixel_x", sa.Double(), nullable=False),
        sa.Column("pixel_y", sa.Double(), nullable=False),
        # ★ The authoritative geometry. PIXELS, y-DOWN, SRID 0 = "unknown CRS", which is
        # exactly what image pixel space is — and PostGIS REFUSES ST_Transform on SRID
        # 0, which makes invariant I1 mechanical rather than aspirational.
        sa.Column(
            "pixel_geom",
            geoalchemy2.types.Geometry(
                geometry_type="GEOMETRY", srid=0, spatial_index=False
            ),
            nullable=False,
        ),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        # ★ 0–1. THE SURVEYOR'S OWN CERTAINTY. Not the algorithm's.
        sa.Column("confidence", sa.Double(), server_default=sa.text("1.0"), nullable=False),
        sa.Column("ordering", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "style",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("version_no", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("revision_seq", sa.BigInteger(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.Text(), nullable=True),
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
        # ★ THE guard that makes the single-table design safe.
        sa.CheckConstraint(
            "(geom_type = 'point' AND GeometryType(pixel_geom) = 'POINT')"
            " OR (geom_type = 'polyline' AND GeometryType(pixel_geom) = 'LINESTRING')"
            " OR (geom_type = 'polygon' AND GeometryType(pixel_geom) = 'POLYGON')",
            name="ck_annotations_geom_type_match",
        ),
        sa.CheckConstraint("ST_IsValid(pixel_geom)", name="ck_annotations_geom_valid"),
        sa.CheckConstraint("ST_NDims(pixel_geom) = 2", name="ck_annotations_geom_2d"),
        sa.CheckConstraint("ST_SRID(pixel_geom) = 0", name="ck_annotations_geom_srid"),
        sa.CheckConstraint(
            "geom_type <> 'polyline' OR ST_NPoints(pixel_geom) >= 2",
            name="ck_annotations_polyline_min",
        ),
        sa.CheckConstraint(
            "geom_type <> 'polygon' OR ST_NPoints(ST_ExteriorRing(pixel_geom)) >= 4",
            name="ck_annotations_polygon_min",
        ),
        sa.CheckConstraint("pixel_x >= 0 AND pixel_y >= 0", name="ck_annotations_pixel_nonneg"),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_annotations_confidence"),
        sa.CheckConstraint("version_no > 0", name="ck_annotations_version_pos"),
        sa.ForeignKeyConstraint(
            ["image_id"],
            ["images.id"],
            name="fk_annotations_image_id_images",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_annotations"),
    )

    op.create_table(
        "annotation_versions",
        # ★ BIGSERIAL, not UUID: append-only, high-row-count, never in a URL (§5.4).
        # Serialised as a JSON NUMBER, not a string.
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        # ★ Deliberately NOT an FK — see the module docstring.
        sa.Column("annotation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("image_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("op", _ANNOTATION_OP, nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "pixel_geom_after",
            geoalchemy2.types.Geometry(
                geometry_type="GEOMETRY", srid=0, spatial_index=False
            ),
            nullable=True,
        ),
        sa.Column("actor_id", sa.Text(), nullable=True),
        sa.Column("client_op_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # The biconditional binding `op` to before/after nullity. Events carry BOTH
        # sides, which is what makes undo O(1).
        sa.CheckConstraint(
            "(op = 'create' AND before IS NULL AND after IS NOT NULL)"
            " OR (op = 'delete' AND before IS NOT NULL AND after IS NULL)"
            " OR (op IN ('update', 'restore') AND before IS NOT NULL AND after IS NOT NULL)",
            name="ck_annotation_versions_payload",
        ),
        sa.CheckConstraint("version_no > 0", name="ck_annotation_versions_version_pos"),
        sa.ForeignKeyConstraint(
            ["image_id"],
            ["images.id"],
            name="fk_annotation_versions_image_id_images",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["project_revisions.id"],
            name="fk_annotation_versions_revision_id_project_revisions",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_annotation_versions"),
    )


def downgrade() -> None:
    op.drop_table("annotation_versions")
    op.drop_table("annotations")
    op.drop_table("project_revisions")
