"""``app.services`` — the orchestration layer, and the ONLY both-sides layer.

Routers (``app.api``) call services; services call repositories (``app.db.repositories``)
and the domain libraries (``ai_engine``, ``gis``). A service never imports FastAPI and
never imports Celery (it enqueues through ``core.queue.JobQueue``); a router never touches
the DB (L6). ``_adapters`` is the single module here permitted to import ``gis`` / ``ai_engine``
*types* — it is where a wire type becomes a domain type (§4.22).

★ SCOPE.md: ``gcp_service`` is the heart (manual GCP surveying); ``match_service``,
``suggestion_service``, ``semantic_service``, ``pose_service``, ``heatmap_service`` and
``batch_service.create`` front DEFERRED features and raise ``FeatureDeferredError`` (501).
"""

from __future__ import annotations

from app.services.annotation_service import AnnotationService
from app.services.batch_service import BatchService
from app.services.capability_service import CapabilityService
from app.services.dem_service import DemService
from app.services.elevation_service import ElevationService
from app.services.export_service import ExportService
from app.services.gcp_service import GcpService
from app.services.heatmap_service import HeatmapService
from app.services.image_service import ImageService
from app.services.imagery_service import ImageryService
from app.services.match_service import MatchService
from app.services.pose_service import PoseService
from app.services.project_service import ProjectService
from app.services.result_service import ResultService
from app.services.revision_service import RevisionService
from app.services.semantic_service import SemanticService
from app.services.suggestion_service import SuggestionService

__all__ = [
    "AnnotationService",
    "BatchService",
    "CapabilityService",
    "DemService",
    "ElevationService",
    "ExportService",
    "GcpService",
    "HeatmapService",
    "ImageService",
    "ImageryService",
    "MatchService",
    "PoseService",
    "ProjectService",
    "ResultService",
    "RevisionService",
    "SemanticService",
    "SuggestionService",
]
