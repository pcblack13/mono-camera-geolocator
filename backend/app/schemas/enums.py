"""The wire enums — §6.2's thirty, plus the two SCOPE.md §5 adds.

★ **This file is a MIRROR, not a source.** ``app.models.enums`` (IU-16) and
``ai_engine.types.enums`` (IU-01) declare the same seventeen paired enums,
independently, with **identical values**. None imports another;
``backend/app/tests/unit/test_enum_parity.py`` asserts all three legs agree via
§5.3's normative ``PARITY_MAP``. Three separate files is deliberate: a shared
enum module would drag ``sqlalchemy`` into the wire layer or ``pydantic`` into
the ORM, and §10.2 forbids both directions.

★ **Values are the wire.** Every enum here is a ``StrEnum``, so
``JobStatus.PENDING`` serialises as ``"pending"`` — never ``"PENDING"``. That is
L9 (snake_case on the wire) applied to enum members, and it is why the PG types
use ``values_callable`` (§5.4) rather than SQLAlchemy's default name-based
serialisation.

★ **The two buckets, per §5.3, and a member belongs to exactly one:**

*Paired* (17) — has a PG type, is in ``PARITY_MAP``, must match ``models.enums``:
    ``JobStatus`` · ``JobType`` · ``ImageStatus`` · ``ProviderName`` ·
    ``AnnotationGeomType`` · ``AnnotationKind`` · ``AnnotationOp`` ·
    ``SemanticClass`` · ``FeatureSpace`` · ``FeatureDetectorName`` ·
    ``ExtractorName`` · ``MatcherName`` · ``EstimatorName`` · ``PoseMethod`` ·
    ``ExportFormat`` · ``GcpStaleReason`` · ``SuggestionStatus``

*Wire-only* (13) — no PG type at all, explicitly OUT of parity scope:
    ``JobStage`` · ``SegmentBackend`` · ``SuggestionStrategy`` · ``BatchOnError`` ·
    ``HealthStatus`` · ``ComponentStatus`` · ``ThumbnailSize`` · ``ImageFormat`` ·
    ``HeatmapFormat`` · ``Colormap`` · ``ViewRegime`` · ``QualityFlag`` ·
    ``CoordinateFormat``

★ ``JobStage`` is **re-exported from** ``app.core.constants``, not redeclared.
§3 makes that module its sole home and grants IU-16/IU-17 the import precisely
so the vocabulary is not forked. ``STAGES`` and ``STAGE_WEIGHTS`` stay there;
this module re-exports only the enum, because it is the only part of the
vocabulary that reaches the wire (``JobProgress.stage``).

★ ``GcpSource`` and ``SurveyorConfidence`` are **added by SCOPE.md §5** and are
flagged in IU-17's report. See their docstrings.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final, Literal

# ★ THE SOLE HOME of the job-stage vocabulary is app.core.constants (§3). This
#   re-export is sanctioned there by name; it is not a second declaration.
from app.core.constants import JobStage

__all__ = [
    "PAIRED_ENUMS",
    "WIRE_ONLY_ENUMS",
    "AnnotationGeomType",
    "AnnotationKind",
    "AnnotationOp",
    "BatchOnError",
    "Colormap",
    "ComponentStatus",
    "CoordinateFormat",
    "EstimatorName",
    "ExportFormat",
    "ExtractorName",
    "FeatureDetectorName",
    "FeatureSpace",
    "GcpSource",
    "GcpStaleReason",
    "HealthStatus",
    "HeatmapFormat",
    "ImageFormat",
    "ImageStatus",
    "JobStage",
    "JobStatus",
    "JobType",
    "MatcherName",
    "PoseMethod",
    "ProviderName",
    "QualityFlag",
    "SegmentBackend",
    "SemanticClass",
    "SuggestionStatus",
    "SuggestionStrategy",
    "SurveyorConfidence",
    "ThumbnailSize",
    "ViewRegime",
]


# ═════════════════════════════════════════════════════════════════════════════
# PAIRED — a PG type exists; PARITY_MAP checks these against models.enums (§5.3)
# ═════════════════════════════════════════════════════════════════════════════


class JobStatus(StrEnum):
    """PG ``job_status``. Mirrors ``models.enums.JobStatus``.

    ★ The TERMINAL SET is ``{succeeded, failed, cancelled}`` — clients stop
    polling on exactly these three (``core.constants.TERMINAL_JOB_STATUSES``).
    There is deliberately no ``expired`` member: retention deletes the row,
    which surfaces as a 404.
    """

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


class JobType(StrEnum):
    """PG ``job_type``. ★ The discriminator over the ``v_jobs`` union (§5.5)."""

    MATCH = "match"
    EXPORT = "export"
    BATCH = "batch"
    SEGMENT = "segment"
    SUGGEST_LANDMARKS = "suggest_landmarks"
    GCP_RECOMPUTE = "gcp_recompute"
    INGEST = "ingest"


class ImageStatus(StrEnum):
    """PG ``image_status``."""

    UPLOADED = "uploaded"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class ProviderName(StrEnum):
    """PG ``imagery_provider``. ★ Paired with ``models.enums.ImageryProvider``
    under a DIFFERENT class name — see §5.3's ``PARITY_MAP``, which pairs
    ``imagery_provider`` → ``ImageryProvider`` (ORM) → **``ProviderName``**
    (wire). The values, not the class names, are what parity checks.

    ★ Values ARE the registry keys of ``gis.imagery``'s ``ImageryProvider``
    implementations. A backend test pins this enum to ``gis.imagery.base.
    PROVIDER_NAMES`` — ``gis`` may not import ``sqlalchemy`` or ``pydantic``
    (§10.2), so the assertion has to live on this side of the boundary.

    ★ There is deliberately NO ``google_earth`` member. Google Earth imagery is
    out of scope by client legal constraint, and making it UNREPRESENTABLE IN
    THE TYPE SYSTEM is the cheapest possible enforcement. Not a disabled flag:
    an absence.
    """

    ESRI_WORLD_IMAGERY = "esri_world_imagery"  # ★★ DEFAULT · KEYLESS (L2)
    LOCAL_ORTHOPHOTO = "local_orthophoto"  # ★★ OFFLINE · HIGHEST ACCURACY
    FIXTURE = "fixture"  # ★★ deterministic, NO NETWORK
    MAPBOX_SATELLITE = "mapbox_satellite"  # †LE_MAPBOX_ACCESS_TOKEN
    BING_AERIAL = "bing_aerial"  # †LE_BING_MAPS_KEY
    SENTINEL_COPERNICUS = "sentinel_copernicus"  # †LE_COPERNICUS_*
    GOOGLE_MAPS_STATIC = "google_maps_static"  # †key AND LE_GOOGLE_TOS_ACKNOWLEDGED
    GOOGLE_MAP_TILES = "google_map_tiles"  # †key AND LE_GOOGLE_TOS_ACKNOWLEDGED


class AnnotationGeomType(StrEnum):
    """PG ``annotation_geom_type``."""

    POINT = "point"
    POLYLINE = "polyline"
    POLYGON = "polygon"


class AnnotationKind(StrEnum):
    """PG ``annotation_kind``."""

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
    """PG ``annotation_op``."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    RESTORE = "restore"


class SemanticClass(StrEnum):
    """PG ``semantic_class``. ★ PARITY LEG 3 — also declared in
    ``ai_engine.types.enums`` (§5.3).
    """

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
    """PG ``feature_space``.

    ★ ``ck_semantic_features_space_xor`` binds this to the geometry columns:
    ``image_pixel`` ⇒ ``pixel_geom`` set and ``geo_geom`` null; ``satellite_geo``
    ⇒ the reverse. The constraint is what makes the invariant mechanical rather
    than reviewer-dependent.
    """

    IMAGE_PIXEL = "image_pixel"
    SATELLITE_GEO = "satellite_geo"


class FeatureDetectorName(StrEnum):
    """PG ``feature_detector``. Paired with ``models.enums.FeatureDetector``."""

    CLASSICAL_CV = "classical_cv"
    SAM = "sam"
    DINOV2 = "dinov2"
    MANUAL = "manual"
    OTHER = "other"


class ExtractorName(StrEnum):
    """PG ``feature_extractor``. Paired with ``models.enums.FeatureExtractor``.

    ★★ DEFERRED (SCOPE.md §4): feature extraction is an ABC + registry entry
    with a body that raises ``NotImplementedDeferred``. The enum is COMPLETE
    anyway — the seam must be real, not decorative, and re-enabling the engine
    must require zero changes outside ``ai_engine/`` (SCOPE.md §7). A request
    naming any member is accepted and answered honestly; it is never a 404.

    ★ No SURF/BEBLID/VGG/LATCH: OpenCV's contrib extra-features module is
    ABSENT on this box (§0.1), so the classical vocabulary is
    SIFT/ORB/AKAZE/BRISK only.
    """

    SIFT = "sift"  # ★ DEFAULT · TERMINAL FALLBACK
    ORB = "orb"  # ★ TERMINAL FALLBACK · binary
    AKAZE = "akaze"
    BRISK = "brisk"
    ASIFT = "asift"
    SUPERPOINT = "superpoint"  # [weights, lazy]
    DINOV2 = "dinov2"  # [weights, lazy]


class MatcherName(StrEnum):
    """PG ``feature_matcher``. Paired with ``models.enums.FeatureMatcher``.

    ★★ DEFERRED (SCOPE.md §4) — see ``ExtractorName``.

    ★ ``bf``, not ``bruteforce``: the PG label is ``'bf'`` (§5.3) and the wire
    follows the PG label, because parity is checked on VALUES.
    """

    BF = "bf"  # ★ TERMINAL FALLBACK
    FLANN = "flann"  # ★ DEFAULT · TERMINAL FALLBACK
    SUPERGLUE = "superglue"  # [weights, lazy]
    LIGHTGLUE = "lightglue"  # [weights, lazy]
    LOFTR = "loftr"  # detector-free


class EstimatorName(StrEnum):
    """PG ``robust_estimator``. ★ PARITY LEG 3 — ``ai_engine.types.enums``
    declares the same values as ``HomographyMethod`` (§5.3).

    ★ On the wire and in the DB, ``estimator`` **always** means the robust-fit
    METHOD (``RansacConfig.method``) — never a component registry key, and it
    never reaches ``Registry.resolve``. The registry key is
    ``AiEngineConfig.estimator_backend`` and is not exposed (§6.1).

    ★★ DEFERRED (SCOPE.md §4): RANSAC homography estimation is an ABC only.
    """

    RANSAC = "ransac"
    USAC_MAGSAC = "usac_magsac"  # ★ DEFAULT
    LMEDS = "lmeds"
    PROSAC = "prosac"
    USAC_ACCURATE = "usac_accurate"
    LSQ = "lsq"


class PoseMethod(StrEnum):
    """PG ``pose_method``. ★ PARITY LEG 3 — also in ``ai_engine.types.enums``.

    ★★ DEFERRED (SCOPE.md §4): camera pose estimation is an ABC only.
    """

    ZHANG_PLANE = "zhang_plane"  # ★ the PRIMARY path
    HOMOGRAPHY_DECOMPOSITION = "homography_decomposition"
    PNP = "pnp"
    EXIF_GPS_ONLY = "exif_gps_only"
    MANUAL = "manual"
    HEATMAP_ARGMAX = "heatmap_argmax"


class ExportFormat(StrEnum):
    """PG ``export_format``. ★ SCOPE.md §3: exports are BUILT, in full."""

    CSV = "csv"
    GEOJSON = "geojson"
    SHAPEFILE = "shapefile"
    KML = "kml"
    KMZ = "kmz"
    PDF = "pdf"
    GPKG = "gpkg"
    DXF = "dxf"


class GcpStaleReason(StrEnum):
    """PG ``gcp_stale_reason``.

    ★ Staleness is a FLAG and never an auto-recompute. A GCP is a coordinate
    that may already be in a survey report, a contract, or a machine-control
    file. **It changes when a human decides it changes.**
    """

    LANDMARK_MOVED = "landmark_moved"
    LANDMARK_DELETED = "landmark_deleted"
    HOMOGRAPHY_SUPERSEDED = "homography_superseded"
    ANNOTATIONS_RESTORED = "annotations_restored"


class SuggestionStatus(StrEnum):
    """PG ``suggestion_status``.

    ★★ DEFERRED (SCOPE.md §4): automatic landmark suggestion is an ABC only and
    the ``landmark_suggestions`` table holds no rows in this build (rule 5).
    """

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


# ═════════════════════════════════════════════════════════════════════════════
# WIRE-ONLY — no PG type; explicitly OUT of parity scope (§5.3)
# ═════════════════════════════════════════════════════════════════════════════
#
# ``JobStage`` is the fourteenth wire-only enum and is imported above from
# app.core.constants rather than declared here.


class SegmentBackend(StrEnum):
    """Which segmenter ``POST /images/{id}/segment`` asks for.

    ★★ DEFERRED (SCOPE.md §4): semantic detection is an ABC only; the endpoint
    is registered and documented and returns ``501`` with a
    ``feature: "deferred"`` marker.
    """

    CLASSICAL = "classical"
    SAM = "sam"
    DINOV2 = "dinov2"


class SuggestionStrategy(StrEnum):
    """How ``POST /images/{id}/suggest-landmarks`` should propose landmarks.

    ★★ DEFERRED (SCOPE.md §4) — the endpoint returns ``501``.
    """

    CORNERS = "corners"
    SALIENCY = "saliency"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"


class BatchOnError(StrEnum):
    """★ ``continue`` is the default: one unreadable photo in a batch of forty
    must not discard the other thirty-nine's work. The failed item carries its
    own error and is re-runnable alone.
    """

    CONTINUE = "continue"
    ABORT = "abort"


class HealthStatus(StrEnum):
    """``GET /health`` · ``GET /health/ready`` (§7.1).

    ★ ``degraded`` is a **200**. If no Celery worker is running the API can
    still serve every read — returning 503 would take the whole UI offline,
    including the screens that would tell the operator the workers are down.
    """

    OK = "ok"
    DEGRADED = "degraded"
    NOT_READY = "not_ready"


class ComponentStatus(StrEnum):
    """One readiness check's verdict (§7.1).

    ★ ``skipped`` exists because ``GET /health/ready`` accepts ``?check=`` — an
    unrequested check reports ``skipped``, never a fabricated ``up``.
    """

    UP = "up"
    DEGRADED = "degraded"
    DOWN = "down"
    SKIPPED = "skipped"


class ThumbnailSize(StrEnum):
    """``ThumbnailParams.size`` for endpoint 13.

    ★ CONTRACT-SILENT (flagged in IU-17's report). §6.2 names the enum and
    §2.4 names the endpoint, but no section fixes the members. These are the
    obvious three and they map onto the ``thumbnail``/``preview`` variants of
    ``ImageVariant`` that ingest already materialises, so the endpoint serves a
    stored raster rather than resizing inside a GET — which is what keeps
    endpoint 13 on the right side of L5.
    """

    SMALL = "small"  # ~ 128 px on the long edge
    MEDIUM = "medium"  # ~ 512 px  — the `thumbnail` variant
    LARGE = "large"  # ~ 1024 px — the `preview` variant


class ImageFormat(StrEnum):
    """Encoding for a binary image response (endpoints 13, 36, 53).

    ★ CONTRACT-SILENT (flagged in IU-17's report). Deliberately NOT the same
    set as the UPLOAD MIME allow-list (``image/jpeg|png|tiff|webp``): this is
    what we *encode*, and encoding a thumbnail as TIFF serves nobody.
    """

    PNG = "png"
    JPEG = "jpeg"
    WEBP = "webp"


class HeatmapFormat(StrEnum):
    """``HeatmapParams.format`` for endpoint 49.

    ★★ DEFERRED (SCOPE.md §4): the confidence heatmap is an ABC only.
    """

    JSON = "json"
    GEOJSON = "geojson"
    PNG = "png"


class Colormap(StrEnum):
    """★ The default is ``viridis_r`` — viridis REVERSED — so LOW confidence is
    the attention-getting end (yellow) rather than the pleasant end. A heatmap
    where the GOOD regions glow brightly trains the eye to look at exactly the
    wrong places. A legend with numeric stops is mandatory and always rendered
    with the layer; an unlabelled heatmap is decoration.
    """

    VIRIDIS = "viridis"
    VIRIDIS_R = "viridis_r"
    MAGMA = "magma"
    INFERNO = "inferno"
    TURBO = "turbo"
    GRAY = "gray"


class ViewRegime(StrEnum):
    """A property of the QUERY IMAGE, not of a window.

    ★ Wire-only ON PURPOSE (§5.3): ``match_results.view_regime`` is a plain
    ``Text`` column because it is diagnostic provenance rather than a queried
    dimension, and it is the field most likely to gain members as the taxonomy
    is tuned against real oblique photos.

    ★ SCOPE.md §2 is this enum read as a reason: a planar homography is only
    strictly valid for a planar scene or pure rotation, and ``oblique_raw`` /
    ``ground_horizon`` violate both. That is why the automatic engine is
    deferred and why manual mode has none of the risk.
    """

    NADIR = "nadir"
    OBLIQUE_RECTIFIABLE = "oblique_rectifiable"
    OBLIQUE_RAW = "oblique_raw"
    GROUND_HORIZON = "ground_horizon"
    UNKNOWN = "unknown"


class QualityFlag(StrEnum):
    """Advisory; the UI badges them. Never gates a response."""

    LOW_INLIERS = "low_inliers"
    LOW_INLIER_RATIO = "low_inlier_ratio"
    DEGENERATE_HOMOGRAPHY = "degenerate_homography"
    REFLECTED_HOMOGRAPHY = "reflected_homography"
    HIGH_REPROJ_ERROR = "high_reproj_error"
    LOW_SEMANTIC_EVIDENCE = "low_semantic_evidence"
    GEOTIFF_GEOREFERENCE_DISAGREEMENT = "geotiff_georeference_disagreement"
    FEW_LANDMARKS = "few_landmarks"
    ZOOM_CLAMPED = "zoom_clamped"


class CoordinateFormat(StrEnum):
    """How a coordinate is rendered. Persisted client-side in ``workspaceStore``
    and accepted by ``CsvExportOptions``.
    """

    DD = "dd"  # decimal degrees
    DMS = "dms"  # degrees/minutes/seconds
    UTM = "utm"
    DD_UTM_Z = "ddutmz"  # decimal degrees + UTM (easting/northing/zone) + Z (elevation)


# ═════════════════════════════════════════════════════════════════════════════
# SCOPE.md §5 — the manual-mode provenance vocabulary
# ═════════════════════════════════════════════════════════════════════════════


class GcpSource(StrEnum):
    """★★ ADDED BY SCOPE.md §5. Flagged in IU-17's report — §6 has no such enum
    because the contract assumed the automatic engine, and §5.3 therefore has no
    ``gcp_source`` PG type and no ``PARITY_MAP`` row.

    SCOPE.md §5, verbatim: *"The GCP records ``source = 'manual'`` so an
    automatic GCP can never be confused with an observed one downstream or in an
    export."* That sentence is a **schema** requirement, not a convention —
    it has to be a stored, filterable, exported column, which makes it a PG enum
    and a parity enum. IU-16 must mirror it, IU-30 must ``CREATE TYPE
    gcp_source``, and IU-22 must add the ``PARITY_MAP`` row.

    - ``manual`` — the surveyor marked the landmark in the photo and clicked the
      same physical spot on the satellite map. **The coordinate is a DIRECT
      OBSERVATION, not an inference.** Every GCP in this build.
    - ``automatic`` — derived by the matching engine through an estimated
      homography. **DEFERRED** (SCOPE.md §1); no row carries it in this build.
      The member exists because the seam must be real: re-enabling the engine
      must require zero changes outside ``ai_engine/`` (SCOPE.md §7), and a
      column that gains a value later is a migration, not a no-op.
    """

    MANUAL = "manual"
    AUTOMATIC = "automatic"


#: ★★ ADDED BY SCOPE.md §5. The surveyor's own, declared judgement — 1..5, where
#: 5 is the most certain.
#:
#: A ``Literal`` and not an ``IntEnum`` so it serialises as a JSON **number** and
#: OpenAPI emits ``enum: [1,2,3,4,5]``, which ``openapi-typescript`` renders as
#: ``1 | 2 | 3 | 4 | 5`` — exactly IU-23's hand-written ``SurveyorConfidence``.
#: An ``IntEnum`` would generate a named component and a string-keyed union, and
#: the two layers would drift on the first regeneration.
#:
#: ★ A discrete ordinal, not a continuum, because the surveyor's judgement IS
#: discrete: *"am I sure this is the same tank top?"* has about five honest
#: answers, not a hundred. A 0–100 slider for a human judgement would
#: manufacture a precision the human never claimed — the same failure the
#: display-decimal truncation exists to prevent, one field over.
#:
#: ★ SCOPE.md §5: *"``confidence`` in manual mode is a SURVEYOR-DECLARED value
#: … NEVER a computed number."*
SurveyorConfidence = Literal[1, 2, 3, 4, 5]


# ═════════════════════════════════════════════════════════════════════════════
# The parity buckets, declared as data (§5.3)
# ═════════════════════════════════════════════════════════════════════════════

#: The seventeen enums that have a PG type and a ``models.enums`` twin. Keyed by
#: PG type name so ``test_enum_parity`` can walk §5.3's table without restating
#: it. ★ ``GcpSource`` is NOT here: it has no PG type **yet** — see its
#: docstring and IU-17's report.
PAIRED_ENUMS: Final[dict[str, type[StrEnum]]] = {
    "job_status": JobStatus,
    "job_type": JobType,
    "image_status": ImageStatus,
    "imagery_provider": ProviderName,
    "annotation_geom_type": AnnotationGeomType,
    "annotation_kind": AnnotationKind,
    "annotation_op": AnnotationOp,
    "semantic_class": SemanticClass,
    "feature_space": FeatureSpace,
    "feature_detector": FeatureDetectorName,
    "feature_extractor": ExtractorName,
    "feature_matcher": MatcherName,
    "robust_estimator": EstimatorName,
    "pose_method": PoseMethod,
    "export_format": ExportFormat,
    "gcp_stale_reason": GcpStaleReason,
    "suggestion_status": SuggestionStatus,
}

#: The thirteen enums with no PG type at all. ``test_enum_parity`` asserts these
#: are absent from ``models.enums`` — so a NEW schema enum must be *deliberately*
#: placed in one bucket or the other rather than silently escaping both.
WIRE_ONLY_ENUMS: Final[dict[str, type[StrEnum]]] = {
    "JobStage": JobStage,
    "SegmentBackend": SegmentBackend,
    "SuggestionStrategy": SuggestionStrategy,
    "BatchOnError": BatchOnError,
    "HealthStatus": HealthStatus,
    "ComponentStatus": ComponentStatus,
    "ThumbnailSize": ThumbnailSize,
    "ImageFormat": ImageFormat,
    "HeatmapFormat": HeatmapFormat,
    "Colormap": Colormap,
    "ViewRegime": ViewRegime,
    "QualityFlag": QualityFlag,
    "CoordinateFormat": CoordinateFormat,
}
