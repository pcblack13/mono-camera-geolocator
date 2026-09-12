"""create enums

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-17

★ **All SEVENTEEN native enum types, created ONCE, here.** Every table reference in
0003–0008 uses ``postgresql.ENUM(..., create_type=False)`` so no table DDL tries to
create one again. §5.3 is normative: seventeen, and these values exactly. The Python
mirrors in ``app/models/enums.py`` are a separate file with identical values; the parity
test pins them together.

★ **Why native enums.** 4 bytes, self-documenting in ``\\dT+``, and — critically —
``ALTER TYPE … ADD VALUE`` is non-blocking and instant in PG 12+, which kills the
classic "enums are hard to extend" objection. Lookup tables add a join to every read of
the hottest tables for data that changes at the rate of *code releases*.
``VARCHAR + CHECK`` requires a full table rewrite-scan to extend.

★ Any future enum-label migration contains **nothing but**
``ALTER TYPE … ADD VALUE IF NOT EXISTS`` and is never downgradable — its ``downgrade()``
is a documented ``pass`` (§5.7).
"""

from __future__ import annotations

from typing import Sequence

import geoalchemy2  # noqa: F401  # ★ see script.py.mako — never remove
import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: (type name, labels) — the order of §5.3, and the order of
#: ``app.models.enums.PG_ENUM_NAMES``. Two lists, one order, checked by eye once here so
#: nobody has to check it again.
ENUMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "job_status",
        ("pending", "queued", "running", "succeeded", "failed", "cancelled", "retrying"),
    ),
    (
        "job_type",
        ("match", "export", "batch", "segment", "suggest_landmarks", "gcp_recompute", "ingest"),
    ),
    ("image_status", ("uploaded", "processing", "ready", "failed")),
    # ★ The values ARE the registry keys of the ImageryProvider implementations.
    # ★ There is deliberately NO 'google_earth' label: out of scope by client legal
    #   constraint, and making it UNREPRESENTABLE IN THE TYPE SYSTEM is the cheapest
    #   possible enforcement. Not a disabled flag: an absence.
    (
        "imagery_provider",
        (
            "esri_world_imagery",  # ★ DEFAULT. KEYLESS. (L2)
            "local_orthophoto",
            "fixture",  # ★ TEST-ONLY. Deterministic synthetic tiles. NO NETWORK.
            "mapbox_satellite",
            "bing_aerial",
            "sentinel_copernicus",
            "google_maps_static",
        ),
    ),
    ("annotation_geom_type", ("point", "polyline", "polygon")),
    (
        "annotation_kind",
        (
            "generic",
            "field_corner",
            "field_border",
            "road",
            "road_intersection",
            "irrigation_canal",
            "tree",
            "tree_line",
            "greenhouse",
            "building",
            "building_corner",
            "water_body",
            "pole_or_pylon",
            "fence_post",
            "crop_row",
            "other",
        ),
    ),
    ("annotation_op", ("create", "update", "delete", "restore")),
    (
        "semantic_class",
        (
            "field_border",
            "road",
            "irrigation_canal",
            "tree",
            "tree_line",
            "greenhouse",
            "building",
            "water_body",
            "crop_row",
            "bare_soil",
            "vegetation",
            "shadow",
            "unknown",
        ),
    ),
    ("feature_space", ("image_pixel", "satellite_geo")),
    ("feature_detector", ("classical_cv", "sam", "dinov2", "manual", "other")),
    (
        "feature_extractor",
        ("sift", "orb", "akaze", "brisk", "asift", "superpoint", "dinov2"),
    ),
    ("feature_matcher", ("bf", "flann", "superglue", "lightglue", "loftr")),
    # ★ THE ROBUST-FIT METHOD (= RansacConfig.method = HomographyMethod). NOT a
    #   registry key. 'usac_accurate' and 'lsq' are HomographyMethod members, so
    #   without them a job using either could not record what actually ran.
    (
        "robust_estimator",
        ("ransac", "usac_magsac", "lmeds", "prosac", "usac_accurate", "lsq"),
    ),
    # ★ 'zhang_plane' is the PRIMARY pose method and camera_poses.method is NOT NULL —
    #   without this label every Zhang-plane pose would be literally unwritable.
    (
        "pose_method",
        (
            "zhang_plane",
            "homography_decomposition",
            "pnp",
            "exif_gps_only",
            "manual",
            "heatmap_argmax",
        ),
    ),
    ("export_format", ("csv", "geojson", "shapefile", "kml", "kmz", "pdf", "gpkg", "dxf")),
    (
        "gcp_stale_reason",
        (
            "landmark_moved",
            "landmark_deleted",
            "homography_superseded",
            "annotations_restored",
        ),
    ),
    ("suggestion_status", ("pending", "accepted", "rejected")),
)


def upgrade() -> None:
    assert len(ENUMS) == 17, "§5.3 is normative: seventeen enum types, no more, no less."
    for name, labels in ENUMS:
        rendered = ", ".join(f"'{label}'" for label in labels)
        op.execute(f"CREATE TYPE {name} AS ENUM ({rendered})")


def downgrade() -> None:
    for name, _labels in reversed(ENUMS):
        op.execute(f"DROP TYPE IF EXISTS {name}")
