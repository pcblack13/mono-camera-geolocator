"""The ORM layer (CONTRACT.md §5).

★ **This module imports every model module and re-exports every class**, so that
``Base.metadata`` is fully populated the moment ``app.models`` is imported. Alembic
autogenerate silently produces an **empty diff** for any model module it never imported
— the second-most-common PostGIS+Alembic footgun after the missing ``import
geoalchemy2`` in ``script.py.mako`` (§5.5). ``alembic/env.py`` imports *this* package,
never an individual module, for exactly that reason.

Eighteen models, eighteen tables. ★ SCOPE.md §4 rule 5: the six tables belonging to
the deferred automatic engine (``match_jobs``, ``match_results``, ``camera_poses``,
``confidence_heatmaps`` + ``…_cells``, ``semantic_features``, ``landmark_suggestions``)
are created exactly as specified. They simply hold no rows in this build.
"""

from __future__ import annotations

from app.models.album import Album, album_projects
from app.models.annotation import Annotation, AnnotationVersion
from app.models.camera import Camera
from app.models.detection_event import DetectionEvent
from app.models.base import NAMING_CONVENTION, Base
from app.models.enums import (
    AnnotationGeomType,
    AnnotationKind,
    AnnotationOp,
    ExportFormat,
    FeatureDetector,
    FeatureExtractor,
    FeatureMatcher,
    FeatureSpace,
    GcpSource,
    GcpStaleReason,
    ImageryProvider,
    ImageStatus,
    JobStatus,
    JobType,
    PoseMethod,
    RobustEstimator,
    SemanticClass,
    SuggestionStatus,
    pg_enum,
)
from app.models.export import Export
from app.models.gcp import GCP
from app.models.heatmap import ConfidenceHeatmap, ConfidenceHeatmapCell
from app.models.image import Image
from app.models.job import AuxJob, BatchJob, BatchJobItem, MatchJob
from app.models.match import MatchResult
from app.models.mixins import SoftDeleteMixin, TimestampMixin, UUIDPkMixin
from app.models.image_camera import ImageCamera
from app.models.pose import CameraPose
from app.models.project import Project
from app.models.revision import ProjectRevision
from app.models.semantic import SemanticFeature
from app.models.suggestion import LandmarkSuggestion
from app.models.video import Video

__all__ = [
    # base + mixins
    "NAMING_CONVENTION",
    "Base",
    "SoftDeleteMixin",
    "TimestampMixin",
    "UUIDPkMixin",
    # enums (§5.3)
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
    "PoseMethod",
    "RobustEstimator",
    "SemanticClass",
    "SuggestionStatus",
    "pg_enum",
    # models (§5.5)
    "GCP",
    "Album",
    "Camera",
    "Annotation",
    "AnnotationVersion",
    "AuxJob",
    "BatchJob",
    "BatchJobItem",
    "CameraPose",
    "ConfidenceHeatmap",
    "ConfidenceHeatmapCell",
    "DetectionEvent",
    "Export",
    "Image",
    "ImageCamera",
    "LandmarkSuggestion",
    "MatchJob",
    "MatchResult",
    "Project",
    "ProjectRevision",
    "SemanticFeature",
    "Video",
    "album_projects",
]
