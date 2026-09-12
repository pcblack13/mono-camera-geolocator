"""Constants shared across the backend — the SOLE HOME of the job-stage vocabulary.

CONTRACT.md §3 makes this module the single owner of ``JobStage``, ``STAGES``,
``STAGE_WEIGHTS`` and the error ``docs_url`` map. ``tasks/progress.py`` (IU-20)
**imports** them; it does not redeclare them. v1.0 put ``STAGE_WEIGHTS`` in both
places — two units, one symbol, and they would not have agreed by luck.

★ **No paired enums live here.** The seventeen DB/wire enums of §5.3 live in
``app.models.enums`` (IU-16) and ``app.schemas.enums`` (IU-17), separately, with
``test_enum_parity`` asserting they agree. ``JobStage`` is *not* one of them: it is
explicitly listed among §5.3's thirteen **wire-only** enums (no PG type at all), so
it has exactly one home, and this is it. IU-16/IU-17 are granted an import of
``core.constants`` precisely so they can re-export it rather than fork it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final, Mapping, TypeVar

__all__ = [
    "ERROR_CODES",
    "ERROR_DOCS_BASE_URL",
    "ERROR_DOCS_URL",
    "JOB_TYPE_BATCH",
    "JOB_TYPE_EXPORT",
    "JOB_TYPE_GCP_RECOMPUTE",
    "JOB_TYPE_INGEST",
    "JOB_TYPE_MATCH",
    "JOB_TYPE_SEGMENT",
    "JOB_TYPE_SUGGEST_LANDMARKS",
    "JOB_TYPES",
    "MATCH_STAGES",
    "STAGES",
    "STAGE_WEIGHTS",
    "TERMINAL_JOB_STATUSES",
    "JobStage",
    "docs_url_for",
    "stage_weights_for",
    "stages_for",
]


# ── Job types ─────────────────────────────────────────────────────────────────
#
# ★ Why strings and not the JobType enum, when §5.5 writes `STAGE_WEIGHTS[JobType.MATCH]`.
#
# `JobType` is a PARITY enum (§5.3): it is declared twice, independently, in
# app.models.enums (IU-16) and app.schemas.enums (IU-17), and this module may import
# NEITHER — both of those units depend on *this* one, so either import is a cycle.
# Declaring a third JobType here is worse still: it would be a fourth leg of a
# parity test that only checks three, i.e. the one copy free to drift silently.
#
# So the keys are the enum's VALUES, and lookup by enum member is preserved by the
# mapping type below. `STAGE_WEIGHTS[JobType.MATCH]` works, `STAGE_WEIGHTS["match"]`
# works, and §13.1's `set(STAGE_WEIGHTS[t]) == set(STAGES[t]) for t in JobType`
# passes verbatim. Values are pinned to §5.3's `job_type` PG enum and §8.2's TS
# union; a mismatch is caught by test_enum_parity, which sees all three legs.

JOB_TYPE_MATCH: Final = "match"
JOB_TYPE_EXPORT: Final = "export"
JOB_TYPE_BATCH: Final = "batch"
JOB_TYPE_SEGMENT: Final = "segment"
JOB_TYPE_SUGGEST_LANDMARKS: Final = "suggest_landmarks"
JOB_TYPE_GCP_RECOMPUTE: Final = "gcp_recompute"
JOB_TYPE_INGEST: Final = "ingest"

JOB_TYPES: Final[tuple[str, ...]] = (
    JOB_TYPE_MATCH,
    JOB_TYPE_EXPORT,
    JOB_TYPE_BATCH,
    JOB_TYPE_SEGMENT,
    JOB_TYPE_SUGGEST_LANDMARKS,
    JOB_TYPE_GCP_RECOMPUTE,
    JOB_TYPE_INGEST,
)

# Clients stop polling on exactly these three. There is no `expired` state —
# retention deletes the row, which surfaces as 404 (§5.5).
TERMINAL_JOB_STATUSES: Final[frozenset[str]] = frozenset({"succeeded", "failed", "cancelled"})


_V = TypeVar("_V")


class _JobTypeKeyed(dict[str, _V]):
    """A dict keyed by job-type *values* that also accepts the ``JobType`` enum.

    ``STAGE_WEIGHTS[JobType.MATCH]`` must work — §5.5 writes exactly that — but this
    module cannot import ``JobType`` (see above). If ``JobType`` is a ``StrEnum``
    the plain ``dict`` lookup already succeeds by hash equality and ``__missing__``
    is never reached. If it is a bare ``Enum``, ``__missing__`` coerces via
    ``.value`` and the lookup still succeeds.

    Covering both costs four lines and removes a cross-unit assumption that would
    otherwise fail as a ``KeyError`` inside a Celery worker, at the moment a job
    tries to report progress, rather than at import.
    """

    __slots__ = ()

    def __missing__(self, key: object) -> _V:
        value = getattr(key, "value", None)
        if isinstance(value, str) and value in self:
            return self[value]
        raise KeyError(key)


# ── Job stages ────────────────────────────────────────────────────────────────


class JobStage(StrEnum):
    """Every stage any job type can report (§5.5).

    Wire-only (§5.3): there is no ``job_stage`` PG type. The column is text and the
    UI switches on these values, so they are a closed set and this is where it is
    closed.
    """

    # Shared
    PENDING = "pending"
    PERSISTING = "persisting"
    DONE = "done"

    # match
    # ★ RESOLVING_MODELS exists because §11.1/§11.8 mandate that degradation is
    # reported "the instant it is known" at a named stage — and the stage they both
    # named, `loading_model`, exists only for segment/suggest_landmarks. The match
    # list had no legal value the worker could write at the moment it discovered
    # SuperGlue's weights were missing: the job type where that discovery matters
    # most. It is match's second stage and carries weight 0.0 — resolve_with_fallback
    # is a find_spec and a sha256, i.e. milliseconds.
    RESOLVING_MODELS = "resolving_models"
    RESOLVING_AOI = "resolving_aoi"
    FETCHING_TILES = "fetching_tiles"
    EXTRACTING_QUERY = "extracting_query"
    EXTRACTING_TRAIN = "extracting_train"
    MATCHING = "matching"
    ESTIMATING_HOMOGRAPHY = "estimating_homography"
    SCORING = "scoring"
    DERIVING_GCPS = "deriving_gcps"

    # segment
    LOADING_MODEL = "loading_model"
    SEGMENTING = "segmenting"
    VECTORIZING = "vectorizing"

    # suggest_landmarks
    DETECTING = "detecting"
    RANKING = "ranking"

    # export
    COLLECTING_GCPS = "collecting_gcps"
    REPROJECTING = "reprojecting"
    RENDERING = "rendering"
    WRITING = "writing"

    # batch
    FANNING_OUT = "fanning_out"
    WAITING_CHILDREN = "waiting_children"
    AGGREGATING = "aggregating"

    # gcp_recompute
    REFITTING_HOMOGRAPHY = "refitting_homography"

    # ingest
    DECODING = "decoding"
    THUMBNAILING = "thumbnailing"


#: The ``match`` stages ``ai_engine``'s ``ProgressCallback`` may emit (§4.13's
#: ``MatchStage`` literal). The callback is the entire coupling between IU-08 and
#: IU-20, so its emitted set is literally a subset of the JobStage values and
#: ``tasks/progress.py`` needs no translation table at all.
#: §13.1 asserts ``set(MatchStage) <= set(STAGES[JobType.MATCH])``; this tuple is the
#: backend's side of that assertion.
MATCH_STAGES: Final[tuple[JobStage, ...]] = (
    JobStage.RESOLVING_MODELS,
    JobStage.FETCHING_TILES,
    JobStage.EXTRACTING_QUERY,
    JobStage.EXTRACTING_TRAIN,
    JobStage.MATCHING,
    JobStage.ESTIMATING_HOMOGRAPHY,
    JobStage.SCORING,
    JobStage.DERIVING_GCPS,
)


#: The ordered stage list per job type — normative (§5.5).
STAGES: Final[Mapping[str, tuple[JobStage, ...]]] = _JobTypeKeyed(
    {
        JOB_TYPE_MATCH: (
            JobStage.PENDING,
            JobStage.RESOLVING_MODELS,
            JobStage.RESOLVING_AOI,
            JobStage.FETCHING_TILES,
            JobStage.EXTRACTING_QUERY,
            JobStage.EXTRACTING_TRAIN,
            JobStage.MATCHING,
            JobStage.ESTIMATING_HOMOGRAPHY,
            JobStage.SCORING,
            JobStage.DERIVING_GCPS,
            JobStage.PERSISTING,
            JobStage.DONE,
        ),
        JOB_TYPE_SEGMENT: (
            JobStage.PENDING,
            JobStage.LOADING_MODEL,
            JobStage.SEGMENTING,
            JobStage.VECTORIZING,
            JobStage.PERSISTING,
            JobStage.DONE,
        ),
        JOB_TYPE_SUGGEST_LANDMARKS: (
            JobStage.PENDING,
            JobStage.LOADING_MODEL,
            JobStage.DETECTING,
            JobStage.RANKING,
            JobStage.PERSISTING,
            JobStage.DONE,
        ),
        JOB_TYPE_EXPORT: (
            JobStage.PENDING,
            JobStage.COLLECTING_GCPS,
            JobStage.REPROJECTING,
            JobStage.RENDERING,
            JobStage.WRITING,
            JobStage.DONE,
        ),
        JOB_TYPE_BATCH: (
            JobStage.PENDING,
            JobStage.FANNING_OUT,
            JobStage.WAITING_CHILDREN,
            JobStage.AGGREGATING,
            JobStage.DONE,
        ),
        JOB_TYPE_GCP_RECOMPUTE: (
            JobStage.PENDING,
            JobStage.REFITTING_HOMOGRAPHY,
            JobStage.DERIVING_GCPS,
            JobStage.PERSISTING,
            JobStage.DONE,
        ),
        JOB_TYPE_INGEST: (
            JobStage.PENDING,
            JobStage.DECODING,
            JobStage.THUMBNAILING,
            JobStage.PERSISTING,
            JobStage.DONE,
        ),
    }
)


#: The fraction of a job's WALL CLOCK each stage is expected to consume (§5.5).
#:
#: ``percent`` is a weighted blend of these, **not** ``stage_index / n_stages``, so
#: the bar tracks time rather than stage count. Every map sums to 1.0 and every key
#: is a real ``JobStage`` from ``STAGES`` for the same type — asserted by §13.1's
#: ``set(STAGE_WEIGHTS[t]) == set(STAGES[t])`` and ``sum(...) == 1.0 ± 1e-9``.
#:
#: ``pending`` and ``done`` are 0.0 by construction: a job that has not started has
#: made no progress, and a job that is done is at 100% by virtue of being terminal,
#: not by virtue of a weight.
#:
#: The ``match`` row is transcribed verbatim from §5.5. The other six are derived
#: from the same principle (dominant cost first) and are the numbers this build
#: ships; they are cheap to retune because they live in exactly one file.
STAGE_WEIGHTS: Final[Mapping[str, Mapping[JobStage, float]]] = _JobTypeKeyed(
    {
        # Verbatim from §5.5. Tile fetch dominates: it is network-bound over hundreds
        # of tiles, while estimating a homography is milliseconds of linear algebra.
        JOB_TYPE_MATCH: {
            JobStage.PENDING: 0.00,
            JobStage.RESOLVING_MODELS: 0.00,
            JobStage.RESOLVING_AOI: 0.02,
            JobStage.FETCHING_TILES: 0.33,
            JobStage.EXTRACTING_QUERY: 0.05,
            JobStage.EXTRACTING_TRAIN: 0.15,
            JobStage.MATCHING: 0.30,
            JobStage.ESTIMATING_HOMOGRAPHY: 0.05,
            JobStage.SCORING: 0.04,
            JobStage.DERIVING_GCPS: 0.03,
            JobStage.PERSISTING: 0.03,
            JobStage.DONE: 0.00,
        },
        # Inference dominates; vectorising masks to polygons is real but smaller.
        JOB_TYPE_SEGMENT: {
            JobStage.PENDING: 0.00,
            JobStage.LOADING_MODEL: 0.15,
            JobStage.SEGMENTING: 0.55,
            JobStage.VECTORIZING: 0.20,
            JobStage.PERSISTING: 0.10,
            JobStage.DONE: 0.00,
        },
        JOB_TYPE_SUGGEST_LANDMARKS: {
            JobStage.PENDING: 0.00,
            JobStage.LOADING_MODEL: 0.15,
            JobStage.DETECTING: 0.55,
            JobStage.RANKING: 0.20,
            JobStage.PERSISTING: 0.10,
            JobStage.DONE: 0.00,
        },
        # Rendering dominates for PDF (the slowest writer); collecting is a bounded
        # query capped at LE_EXPORT_MAX_ROWS.
        JOB_TYPE_EXPORT: {
            JobStage.PENDING: 0.00,
            JobStage.COLLECTING_GCPS: 0.25,
            JobStage.REPROJECTING: 0.10,
            JobStage.RENDERING: 0.45,
            JobStage.WRITING: 0.20,
            JobStage.DONE: 0.00,
        },
        # A batch is almost entirely its children's wall clock. Fanning out is a
        # handful of INSERTs.
        JOB_TYPE_BATCH: {
            JobStage.PENDING: 0.00,
            JobStage.FANNING_OUT: 0.05,
            JobStage.WAITING_CHILDREN: 0.85,
            JobStage.AGGREGATING: 0.10,
            JobStage.DONE: 0.00,
        },
        JOB_TYPE_GCP_RECOMPUTE: {
            JobStage.PENDING: 0.00,
            JobStage.REFITTING_HOMOGRAPHY: 0.45,
            JobStage.DERIVING_GCPS: 0.35,
            JobStage.PERSISTING: 0.20,
            JobStage.DONE: 0.00,
        },
        # Decoding a 500 MB TIFF and building overviews is the cost here.
        JOB_TYPE_INGEST: {
            JobStage.PENDING: 0.00,
            JobStage.DECODING: 0.45,
            JobStage.THUMBNAILING: 0.35,
            JobStage.PERSISTING: 0.20,
            JobStage.DONE: 0.00,
        },
    }
)


def stages_for(job_type: object) -> tuple[JobStage, ...]:
    """The ordered stages for ``job_type``, which may be a ``JobType`` or its value.

    Raises:
        KeyError: if ``job_type`` is not one of the seven job types.
    """
    return STAGES[job_type]  # type: ignore[index]


def stage_weights_for(job_type: object) -> Mapping[JobStage, float]:
    """The stage -> wall-clock-fraction map for ``job_type``.

    Raises:
        KeyError: if ``job_type`` is not one of the seven job types.
    """
    return STAGE_WEIGHTS[job_type]  # type: ignore[index]


# ── Error documentation ───────────────────────────────────────────────────────

#: Where ``ErrorBody.docs_url`` points. IU-32 owns ``docs/api/errors.md`` and gives
#: every code below an anchor named after its lowercased self.
#:
#: Relative on purpose: the API is reachable at an arbitrary host (compose publishes
#: nginx on LE_WEB_PORT; a bare host runs uvicorn on LE_API_PORT), so any absolute
#: URL baked in here would be wrong for most deployments and would be a
#: phone-home-shaped link in an air-gapped install.
ERROR_DOCS_BASE_URL: Final = "/docs/api/errors.md"


#: Every stable, machine-readable error code the API can emit (§6.3).
#:
#: The client switches on these. They are SCREAMING_SNAKE, they are never localised,
#: and they are never renamed — a renamed code is a silently broken client.
#:
#: This tuple is the code side of the docs_url map; ``core.exceptions`` declares the
#: same strings as each exception's ``code`` ClassVar. IU-22 asserts the two agree
#: (every ``LandExplorerError`` subclass's code appears here), which is what keeps a
#: new exception from shipping with a dead documentation link.
ERROR_CODES: Final[tuple[str, ...]] = (
    # Generic / envelope
    "INTERNAL_ERROR",
    "CONFIGURATION_ERROR",
    "FEATURE_DEFERRED",
    # 404
    "NOT_FOUND",
    "PROJECT_NOT_FOUND",
    "ALBUM_NOT_FOUND",
    "CAMERA_NOT_FOUND",
    "IMAGE_NOT_FOUND",
    "VIDEO_NOT_FOUND",
    "ANNOTATION_NOT_FOUND",
    "JOB_NOT_FOUND",
    "MATCH_RESULT_NOT_FOUND",
    "GCP_NOT_FOUND",
    "REVISION_NOT_FOUND",
    "ANNOTATION_VERSION_NOT_FOUND",
    "EXPORT_NOT_FOUND",
    "BATCH_NOT_FOUND",
    "SUGGESTION_NOT_FOUND",
    "CAMERA_POSE_NOT_AVAILABLE",
    "HEATMAP_NOT_AVAILABLE",
    "UNKNOWN_PROVIDER",
    # 422
    "VALIDATION_ERROR",
    "INVALID_BBOX",
    "BBOX_CROSSES_ANTIMERIDIAN",
    "INVALID_SORT_FIELD",
    "UNKNOWN_QUERY_PARAM",
    "PARAM_CONFLICT",
    "SEARCH_HINT_REQUIRED",
    "ZOOM_OUT_OF_RANGE",
    "SEARCH_AREA_TOO_LARGE",
    "NO_ANNOTATIONS",
    "GCP_ADJUSTMENT_AMBIGUOUS",
    "GCP_OUT_OF_BOUNDS",
    "ANNOTATION_GEOMETRY_INVALID",
    "ANNOTATION_OUT_OF_BOUNDS",
    "CANNOT_RESCALE_GEOTIFF",
    "TOO_MANY_ANNOTATIONS",
    "GEOMETRY_TOO_COMPLEX",
    "STATIC_IMAGE_TOO_LARGE",
    "IMAGE_TOO_LARGE",
    "VIDEO_FRAME_UNAVAILABLE",
    "NO_ADJUSTED_GCPS",
    "INSUFFICIENT_ANCHORS",
    "REVISION_REPLAY_TOO_EXPENSIVE",
    # 400
    "EMPTY_PATCH",
    # 409
    "CONFLICT",
    "MATCH_JOB_ALREADY_RUNNING",
    "EXPORT_NOT_READY",
    "JOB_NOT_CANCELLABLE",
    "REVISION_CONFLICT",
    "REVISION_RESTORE_CONFLICT",
    "IMAGE_STILL_PROCESSING",
    "PROJECT_HAS_ACTIVE_JOBS",
    "GCP_CODE_CONFLICT",
    "PROJECT_NAME_CONFLICT",
    "ALBUM_NAME_CONFLICT",
    "IDEMPOTENCY_KEY_REUSED",
    "IDEMPOTENCY_IN_PROGRESS",
    "GCP_ORIGINAL_UNAVAILABLE",
    # 412 / 428
    "PRECONDITION_FAILED",
    "STALE_ANNOTATION_VERSION",
    "STALE_GCP_VERSION",
    "STALE_PROJECT_VERSION",
    "PRECONDITION_REQUIRED",
    "CONFIRMATION_REQUIRED",
    # 413 / 415 / 416
    "PAYLOAD_TOO_LARGE",
    "UPLOAD_TOO_LARGE",
    "BATCH_TOO_LARGE",
    "UNSUPPORTED_MEDIA_TYPE",
    "UNSUPPORTED_IMAGE_FORMAT",
    "UNSUPPORTED_VIDEO_FORMAT",
    "RANGE_NOT_SATISFIABLE",
    # 410
    "GONE",
    "EXPORT_EXPIRED",
    "IMAGE_PURGED",
    "REVISION_PRUNED",
    "SATELLITE_IMAGE_PURGED",
    # 401 / 403
    "UNAUTHORIZED",
    "MISSING_CREDENTIALS",
    "INVALID_CREDENTIALS",
    "FORBIDDEN",
    "PROVIDER_TOS_FORBIDDEN",
    "READ_ONLY_MODE",
    # 429
    "RATE_LIMITED",
    "RATE_LIMIT_EXCEEDED",
    "PROVIDER_RATE_LIMITED",
    # 502 / 503
    "PROVIDER_ERROR",
    "PROVIDER_UPSTREAM_ERROR",
    "PROVIDER_INVALID_RESPONSE",
    "PROVIDER_NOT_CONFIGURED",
    "DEPENDENCY_UNAVAILABLE",
    "DATABASE_UNAVAILABLE",
    "REDIS_UNAVAILABLE",
    "WORKER_UNAVAILABLE",
    # 500 / 507
    "STORAGE_ERROR",
    "ARTIFACT_WRITE_FAILED",
    "ARTIFACT_READ_FAILED",
    "INSUFFICIENT_STORAGE",
    # Terminal job classifications (§6.3's package-exception map). These never reach
    # an HTTP response as a status — they are written to `error_code` on a failed
    # job row and rendered by the UI's job panel.
    "OUT_OF_COVERAGE",
    "CANCELLED",
    "TIMEOUT",
)


#: code -> documentation anchor. The sole home of the map (§3).
ERROR_DOCS_URL: Final[Mapping[str, str]] = {
    code: f"{ERROR_DOCS_BASE_URL}#{code.lower()}" for code in ERROR_CODES
}


def docs_url_for(code: str) -> str | None:
    """The documentation URL for an error code, or ``None`` if it has no entry.

    ``None`` rather than a fabricated anchor: ``ErrorBody.docs_url`` is optional, and
    a link to a section that does not exist is worse than no link. The 500 handler
    passes ``docs_url: null`` for exactly this reason.
    """
    return ERROR_DOCS_URL.get(code)
