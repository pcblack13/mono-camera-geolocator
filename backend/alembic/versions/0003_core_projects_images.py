"""core projects images

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-17

``projects`` and ``images`` — the two roots. Everything below them hard-cascades; these
two are the only tables with a ``deleted_at`` (§5.4).

Indexes are **not** created here. Every index in §5.6 is non-implied (a partial GIST, a
trigram GIN, a partial unique) and they are all declared together in
``0009_indexes_triggers_views.py``, where they can be reviewed as a set. Only the
constraint-implied indexes (PK, UNIQUE constraints) arrive with the table.
"""

from __future__ import annotations

from typing import Sequence

import geoalchemy2  # noqa: F401  # ★ see script.py.mako — never remove
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ★ create_type=False on every reference: the seventeen types were created ONCE, in
# 0002. A second CREATE TYPE is an error, and a silently skipped one is a type that
# does not match its Python mirror.
_IMAGERY_PROVIDER = postgresql.ENUM(
    "esri_world_imagery",
    "local_orthophoto",
    "fixture",
    "mapbox_satellite",
    "bing_aerial",
    "sentinel_copernicus",
    "google_maps_static",
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
_IMAGE_STATUS = postgresql.ENUM(
    "uploaded", "processing", "ready", "failed", name="image_status", create_type=False
)


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_id", sa.Text(), nullable=True),
        sa.Column(
            "aoi",
            geoalchemy2.types.Geography(
                geometry_type="POLYGON", srid=4326, spatial_index=False
            ),
            nullable=True,
        ),
        # ★ Exporter HINT ONLY, never storage (§5.2).
        sa.Column("working_srid", sa.Integer(), nullable=True),
        # ★ Keyless at the DATA layer — a fresh row is runnable with an empty .env (L2).
        sa.Column(
            "default_provider",
            _IMAGERY_PROVIDER,
            server_default=sa.text("'esri_world_imagery'::imagery_provider"),
            nullable=False,
        ),
        sa.Column(
            "default_extractor",
            _FEATURE_EXTRACTOR,
            server_default=sa.text("'sift'::feature_extractor"),
            nullable=False,
        ),
        sa.Column(
            "default_matcher",
            _FEATURE_MATCHER,
            server_default=sa.text("'flann'::feature_matcher"),
            nullable=False,
        ),
        sa.Column(
            "default_estimator",
            _ROBUST_ESTIMATOR,
            server_default=sa.text("'usac_magsac'::robust_estimator"),
            nullable=False,
        ),
        sa.Column(
            "default_search_radius_m",
            sa.Double(),
            server_default=sa.text("1000.0"),
            nullable=False,
        ),
        sa.Column(
            "default_search_zoom",
            sa.SmallInteger(),
            server_default=sa.text("18"),
            nullable=False,
        ),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        # ★ attribute `meta`, column `metadata` — reserved on DeclarativeBase.
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "current_revision_seq",
            sa.BigInteger(),
            server_default=sa.text("0"),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_projects_name_nonblank"),
        sa.CheckConstraint(
            "working_srid IS NULL OR (working_srid BETWEEN 1024 AND 32767)",
            name="ck_projects_working_srid",
        ),
        # ★ 50..50000 — matches schemas.matching.SearchHint.radius_m, so a project can
        # never store a default its own API would 422.
        sa.CheckConstraint(
            "default_search_radius_m BETWEEN 50 AND 50000",
            name="ck_projects_search_radius",
        ),
        sa.CheckConstraint(
            "default_search_zoom BETWEEN 10 AND 21", name="ck_projects_search_zoom"
        ),
        sa.CheckConstraint(
            "array_length(tags, 1) IS NULL OR array_length(tags, 1) <= 20",
            name="ck_projects_tags_count",
        ),
        sa.CheckConstraint(
            "current_revision_seq >= 0", name="ck_projects_revision_seq_nonneg"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_projects"),
    )

    op.create_table(
        "images",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        # ★ Server-controlled. NEVER serialised to the wire.
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("thumbnail_path", sa.Text(), nullable=True),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("checksum_sha256", sa.CHAR(64), nullable=False),
        sa.Column(
            "status",
            _IMAGE_STATUS,
            server_default=sa.text("'uploaded'::image_status"),
            nullable=False,
        ),
        # ★ Post EXIF-orientation normalisation.
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("band_count", sa.SmallInteger(), server_default=sa.text("3"), nullable=False),
        sa.Column("resolution_dpi", sa.Double(), nullable=True),
        sa.Column("gsd_m", sa.Double(), nullable=True),
        # ★ FULL EXIF, verbatim. The forensic record.
        sa.Column(
            "exif",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "exif_gps",
            geoalchemy2.types.Geography(
                geometry_type="POINT", srid=4326, spatial_index=False
            ),
            nullable=True,
        ),
        sa.Column("exif_gps_altitude_m", sa.Double(), nullable=True),
        sa.Column("exif_gps_direction_deg", sa.Double(), nullable=True),
        sa.Column("exif_gps_hpe_m", sa.Double(), nullable=True),
        sa.Column("gps_source", sa.Text(), nullable=True),
        sa.Column("camera_make", sa.Text(), nullable=True),
        sa.Column("camera_model", sa.Text(), nullable=True),
        sa.Column("lens_model", sa.Text(), nullable=True),
        sa.Column("focal_length_mm", sa.Double(), nullable=True),
        sa.Column("focal_length_35mm", sa.Double(), nullable=True),
        sa.Column("sensor_width_mm", sa.Double(), nullable=True),
        sa.Column("f_number", sa.Double(), nullable=True),
        # ★ A property DISCOVERED at ingest, never a declared type.
        sa.Column("is_geotiff", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("crs_epsg", sa.Integer(), nullable=True),
        sa.Column("crs_wkt", sa.Text(), nullable=True),
        sa.Column(
            "bounds",
            geoalchemy2.types.Geography(
                geometry_type="POLYGON", srid=4326, spatial_index=False
            ),
            nullable=True,
        ),
        sa.Column("geotransform", postgresql.ARRAY(sa.Double(), dimensions=1), nullable=True),
        sa.Column("nodata_value", sa.Double(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("width > 0 AND height > 0", name="ck_images_dims"),
        sa.CheckConstraint("size_bytes > 0", name="ck_images_size"),
        sa.CheckConstraint("band_count > 0", name="ck_images_band_count"),
        sa.CheckConstraint(
            "checksum_sha256 ~ '^[0-9a-f]{64}$'", name="ck_images_checksum_hex"
        ),
        # ★ A GeoTIFF is only usable if it carries the FULL georeferencing triple.
        # Half-georeferenced is worse than not georeferenced: it looks trustworthy.
        sa.CheckConstraint(
            "NOT is_geotiff OR ("
            " crs_epsg IS NOT NULL"
            " AND bounds IS NOT NULL"
            " AND geotransform IS NOT NULL"
            " AND array_length(geotransform, 1) = 6)",
            name="ck_images_geotiff_complete",
        ),
        sa.CheckConstraint(
            "geotransform IS NULL OR array_length(geotransform, 1) = 6",
            name="ck_images_geotransform_arity",
        ),
        sa.CheckConstraint(
            "exif_gps_direction_deg IS NULL"
            " OR (exif_gps_direction_deg >= 0 AND exif_gps_direction_deg < 360)",
            name="ck_images_gps_direction_range",
        ),
        sa.CheckConstraint(
            "gps_source IS NULL OR gps_source IN ('exif', 'manual')",
            name="ck_images_gps_source",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_images_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_images"),
    )


def downgrade() -> None:
    op.drop_table("images")
    op.drop_table("projects")
