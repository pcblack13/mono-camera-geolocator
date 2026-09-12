"""``app.db.repositories`` — ★ **ALL SQL LIVES HERE** (L6).

Routers receive already-loaded entities from ``api.deps`` and call services; services
orchestrate and call these classes. **A ``select()`` above this layer is a defect** — and
that is a build failure, not a code-review opinion: ``.importlinter``'s ``api-not-db``
contract forbids ``app.api.v1`` from importing ``app.db`` or ``app.models`` at all.

**Fourteen classes over seventeen tables.** ``annotations.py`` carries three
(annotations, the version ledger, revisions) because they are one mechanism — the hybrid
event-log + rolling-snapshot design — and splitting them would put the replay join in a
file that owns neither side of it. ``jobs.py`` carries the state machine for four tables
for the opposite reason: they deliberately do **not** share a column set, and four copies
of one state machine is four things to drift.

★ **SCOPE.md and this layer.** The automatic matching engine is deferred, so
``match_results``, ``camera_poses``, ``confidence_heatmaps``, ``semantic_features`` and
``landmark_suggestions`` have **no writer in this build** — but their repositories are
real code against a real schema, not stubs. The schema is not cut (SCOPE.md §4 rule 5),
and the day the engine lands, "zero changes outside ``ai_engine/``" (SCOPE.md §7) is only
true if the persistence layer is already here and already correct.

★ **``gcps.py`` is the core of this build.** Manual GCP creation, adjustment, reset and
every PostGIS spatial query. Read its module docstring — in particular the lon/lat
ordering note — before touching a coordinate anywhere in this package.
"""

from __future__ import annotations

from app.db.repositories.annotations import (
    GCP_CANDIDATE_KINDS,
    AnnotationRepository,
    AnnotationVersionRepository,
    RevisionRepository,
    normalise_pixel_geom,
)
from app.db.repositories.base import (
    BaseRepository,
    BaseSyncRepository,
    SortableColumns,
    apply_pagination,
    apply_sort,
    constraint_name_of,
    count_stmt_of,
    csv_enum_filter,
    like_escape,
)
from app.db.repositories.batches import BatchRepository
from app.db.repositories.exports import ExportRepository
from app.db.repositories.gcps import ACCURACY_DOMINANT_TERMS, GcpRepository
from app.db.repositories.heatmaps import HeatmapRepository
from app.db.repositories.images import ImageRepository
from app.db.repositories.jobs import (
    JOB_MODEL_BY_TYPE,
    LIVE_JOB_STATUSES,
    JobRepository,
    JobView,
    SyncJobRepository,
    v_jobs,
)
from app.db.repositories.matches import MatchResultRepository
from app.db.repositories.poses import CameraPoseRepository
from app.db.repositories.projects import ProjectRepository
from app.db.repositories.semantics import SemanticFeatureRepository
from app.db.repositories.suggestions import LandmarkSuggestionRepository

__all__ = [
    # base + shared helpers
    "BaseRepository",
    "BaseSyncRepository",
    "SortableColumns",
    "apply_pagination",
    "apply_sort",
    "constraint_name_of",
    "count_stmt_of",
    "csv_enum_filter",
    "like_escape",
    # constants the service layer legitimately needs
    "ACCURACY_DOMINANT_TERMS",
    "GCP_CANDIDATE_KINDS",
    "JOB_MODEL_BY_TYPE",
    "LIVE_JOB_STATUSES",
    "normalise_pixel_geom",
    "v_jobs",
    # read models
    "JobView",
    # repositories
    "AnnotationRepository",
    "AnnotationVersionRepository",
    "BatchRepository",
    "CameraPoseRepository",
    "ExportRepository",
    "GcpRepository",
    "HeatmapRepository",
    "ImageRepository",
    "JobRepository",
    "LandmarkSuggestionRepository",
    "MatchResultRepository",
    "ProjectRepository",
    "RevisionRepository",
    "SemanticFeatureRepository",
    "SyncJobRepository",
]
