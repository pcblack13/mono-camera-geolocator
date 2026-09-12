"""The 17 Python mirrors of the 17 native PostgreSQL enum types (CONTRACT.md §5.3).

**This file imports nothing from ``app.schemas.enums`` or ``ai_engine.types.enums``,
and neither of them imports this one.** The three legs are deliberately separate files
with identical *values*; ``backend/app/tests/unit/test_enum_parity.py`` asserts they
agree member-for-member via the normative ``PARITY_MAP`` in §5.3. Importing one from
another would make the parity test tautological and would drag a wire package into the
ORM (or the ORM into ``ai_engine``, which may not know what a database is).

The PG types themselves are created **once**, in migration ``0002_create_enums.py``,
with ``create_type=True``. Every column reference below goes through :func:`pg_enum`,
which pins ``create_type=False`` (the type already exists) and ``values_callable``
(without it SQLAlchemy sends member **names** — ``PENDING`` — where PostgreSQL expects
member **values** — ``pending`` — and every INSERT fails).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from sqlalchemy.dialects.postgresql import ENUM

__all__ = [
    "AnnotationGeomType",
    "AnnotationKind",
    "AnnotationOp",
    "ExportFormat",
    "FeatureDetector",
    "FeatureExtractor",
    "FeatureMatcher",
    "FeatureSpace",
    "GcpSource",
    "GcpStaleReason",
    "ImageStatus",
    "ImageryProvider",
    "JobStatus",
    "JobType",
    "PG_ENUM_NAMES",
    "PoseMethod",
    "RobustEstimator",
    "SemanticClass",
    "SuggestionStatus",
    "pg_enum",
]


class JobStatus(StrEnum):
    """``job_status`` — the lifecycle of every job in ``v_jobs``."""

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


class JobType(StrEnum):
    """``job_type`` — the discriminator of the ``v_jobs`` UNION."""

    MATCH = "match"
    EXPORT = "export"
    BATCH = "batch"
    SEGMENT = "segment"
    SUGGEST_LANDMARKS = "suggest_landmarks"
    GCP_RECOMPUTE = "gcp_recompute"
    INGEST = "ingest"


class ImageStatus(StrEnum):
    """``image_status``."""

    UPLOADED = "uploaded"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class ImageryProvider(StrEnum):
    """``imagery_provider`` — the values ARE the registry keys of the providers.

    ★ There is deliberately **no** ``google_earth`` label. Google Earth imagery is out
    of scope by client legal constraint, and making it unrepresentable in the type
    system is the cheapest possible enforcement: an absence, not a disabled flag.
    """

    ESRI_WORLD_IMAGERY = "esri_world_imagery"  # ★ DEFAULT. KEYLESS. (L2)
    LOCAL_ORTHOPHOTO = "local_orthophoto"
    FIXTURE = "fixture"  # ★ TEST-ONLY. Deterministic synthetic tiles. NO NETWORK.
    MAPBOX_SATELLITE = "mapbox_satellite"
    BING_AERIAL = "bing_aerial"
    SENTINEL_COPERNICUS = "sentinel_copernicus"
    GOOGLE_MAPS_STATIC = "google_maps_static"
    GOOGLE_MAP_TILES = "google_map_tiles"


class AnnotationGeomType(StrEnum):
    """``annotation_geom_type`` — bound to ``GeometryType(pixel_geom)`` by CHECK."""

    POINT = "point"
    POLYLINE = "polyline"
    POLYGON = "polygon"


class AnnotationKind(StrEnum):
    """``annotation_kind`` — the surveyor's landmark vocabulary."""

    GENERIC = "generic"
    FIELD_CORNER = "field_corner"
    FIELD_BORDER = "field_border"
    ROAD = "road"
    ROAD_INTERSECTION = "road_intersection"
    IRRIGATION_CANAL = "irrigation_canal"
    TREE = "tree"
    TREE_LINE = "tree_line"
    GREENHOUSE = "greenhouse"
    BUILDING = "building"
    BUILDING_CORNER = "building_corner"
    WATER_BODY = "water_body"
    POLE_OR_PYLON = "pole_or_pylon"
    FENCE_POST = "fence_post"
    CROP_ROW = "crop_row"
    OTHER = "other"


class AnnotationOp(StrEnum):
    """``annotation_op`` — the event kinds of the annotation ledger."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    RESTORE = "restore"


class SemanticClass(StrEnum):
    """``semantic_class`` — ★ 3-leg parity with ``ai_engine.types.enums.SemanticClass``."""

    FIELD_BORDER = "field_border"
    ROAD = "road"
    IRRIGATION_CANAL = "irrigation_canal"
    TREE = "tree"
    TREE_LINE = "tree_line"
    GREENHOUSE = "greenhouse"
    BUILDING = "building"
    WATER_BODY = "water_body"
    CROP_ROW = "crop_row"
    BARE_SOIL = "bare_soil"
    VEGETATION = "vegetation"
    SHADOW = "shadow"
    UNKNOWN = "unknown"


class FeatureSpace(StrEnum):
    """``feature_space`` — which of the two physically distinct spaces a row lives in."""

    IMAGE_PIXEL = "image_pixel"
    SATELLITE_GEO = "satellite_geo"


class FeatureDetector(StrEnum):
    """``feature_detector``."""

    CLASSICAL_CV = "classical_cv"
    SAM = "sam"
    DINOV2 = "dinov2"
    MANUAL = "manual"
    OTHER = "other"


class FeatureExtractor(StrEnum):
    """``feature_extractor`` — registry keys of the extractor implementations."""

    SIFT = "sift"
    ORB = "orb"
    AKAZE = "akaze"
    BRISK = "brisk"
    ASIFT = "asift"
    SUPERPOINT = "superpoint"
    DINOV2 = "dinov2"


class FeatureMatcher(StrEnum):
    """``feature_matcher`` — registry keys of the matcher implementations."""

    BF = "bf"
    FLANN = "flann"
    SUPERGLUE = "superglue"
    LIGHTGLUE = "lightglue"
    LOFTR = "loftr"


class RobustEstimator(StrEnum):
    """``robust_estimator`` — ★ the robust-fit METHOD (``RansacConfig.method``).

    **Not a registry key.** 3-leg parity with ``ai_engine.types.enums.HomographyMethod``.
    """

    RANSAC = "ransac"
    USAC_MAGSAC = "usac_magsac"
    LMEDS = "lmeds"
    PROSAC = "prosac"
    USAC_ACCURATE = "usac_accurate"
    LSQ = "lsq"


class PoseMethod(StrEnum):
    """``pose_method`` — ★ 3-leg parity with ``ai_engine.types.enums.PoseMethod``."""

    ZHANG_PLANE = "zhang_plane"  # ★ PRIMARY
    HOMOGRAPHY_DECOMPOSITION = "homography_decomposition"
    PNP = "pnp"
    EXIF_GPS_ONLY = "exif_gps_only"
    MANUAL = "manual"
    HEATMAP_ARGMAX = "heatmap_argmax"


class ExportFormat(StrEnum):
    """``export_format``."""

    CSV = "csv"
    GEOJSON = "geojson"
    SHAPEFILE = "shapefile"
    KML = "kml"
    KMZ = "kmz"
    PDF = "pdf"
    GPKG = "gpkg"
    DXF = "dxf"


class GcpStaleReason(StrEnum):
    """``gcp_stale_reason``."""

    LANDMARK_MOVED = "landmark_moved"
    LANDMARK_DELETED = "landmark_deleted"
    HOMOGRAPHY_SUPERSEDED = "homography_superseded"
    ANNOTATIONS_RESTORED = "annotations_restored"


class SuggestionStatus(StrEnum):
    """``suggestion_status``."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class GcpSource(StrEnum):
    """★ How a GCP's coordinate came to exist. **Not a PG enum type.**

    SCOPE.md §5 requires that a GCP record whether its coordinate is a *direct
    observation* (the surveyor clicked the spot on the map) or an *inference* (a
    homography transported it there), so the two can never be confused downstream or in
    an export. §5.6 of the contract does not define the column; this build adds it (see
    :mod:`app.models.gcp`).

    It is stored as ``Text`` + ``CHECK``, **not** as an 18th native enum, because §5.3
    is normative that there are exactly **seventeen** PG enum types and migration
    ``0002`` creates exactly those. This mirrors the other value-constrained ``Text``
    columns in the same table (``elevation_source``, ``accuracy_dominant_term``).
    Consequently it is **out of ``PARITY_MAP`` scope** by construction: it has no PG
    type to be in parity with.
    """

    MANUAL = "manual"
    AUTOMATIC = "automatic"


#: The seventeen native PG type names, in the order migration ``0002`` creates them.
#: ``GcpSource`` is **not** here, and that is the point — see its docstring.
PG_ENUM_NAMES: Final[tuple[str, ...]] = (
    "job_status",
    "job_type",
    "image_status",
    "imagery_provider",
    "annotation_geom_type",
    "annotation_kind",
    "annotation_op",
    "semantic_class",
    "feature_space",
    "feature_detector",
    "feature_extractor",
    "feature_matcher",
    "robust_estimator",
    "pose_method",
    "export_format",
    "gcp_stale_reason",
    "suggestion_status",
)


def pg_enum(enum_cls: type[StrEnum], name: str) -> ENUM:
    """Bind a Python mirror to its already-created native PG enum type.

    Args:
        enum_cls: the ``StrEnum`` mirror declared in this module.
        name: the native PostgreSQL type name (one of :data:`PG_ENUM_NAMES`).

    Returns:
        A ``postgresql.ENUM`` with ``create_type=False`` — the type is created once, in
        migration ``0002``, and *never* by ``create_all`` or by a table DDL — and
        ``values_callable`` so the **values** go on the wire to PostgreSQL, not the
        member names.

    Raises:
        ValueError: if ``name`` is not one of the seventeen types §5.3 defines. A typo
            here would otherwise surface as a runtime ``type "..." does not exist``
            from PostgreSQL, on the first INSERT, in production.
    """
    if name not in PG_ENUM_NAMES:
        raise ValueError(
            f"{name!r} is not one of the seventeen PG enum types of CONTRACT.md §5.3; "
            f"adding an enum type means adding it to PG_ENUM_NAMES and to migration 0002."
        )
    return ENUM(
        enum_cls,
        name=name,
        create_type=False,
        values_callable=lambda e: [m.value for m in e],
    )
