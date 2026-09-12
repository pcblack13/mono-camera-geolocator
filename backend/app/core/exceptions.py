"""The ``LandExplorerError`` hierarchy (CONTRACT.md §6.3).

**Application code raises domain exceptions and NEVER ``HTTPException``.** That is
what keeps the service layer importable and unit-testable without FastAPI, and it
is what lets the same services run inside a Celery worker, where an
``HTTPException`` would be nonsense.

A **single** handler — ``api.errors.landexplorer_exception_handler`` (IU-21) — reads
``exc.status`` / ``exc.code`` / ``exc.details`` / ``exc.headers`` and builds the
``ErrorEnvelope``. **There is no per-exception if-ladder**, which is the whole point
of the two ClassVars: adding an exception must not require touching the handler.

Every ``code`` here appears in ``core.constants.ERROR_CODES``, so every error the
API emits carries a working ``docs_url``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Mapping, Sequence

from app.core.constants import docs_url_for

if TYPE_CHECKING:
    # ★ Type-checking only, and deliberately so.
    #
    # §6.3 types `details` as `list[ErrorDetail]`, and ErrorDetail is a pydantic
    # model in app.schemas.errors — a module owned by IU-17, which depends on THIS
    # package (§3: IU-17 may import core.constants). A runtime import here would
    # point app.core at app.schemas: backwards through the layer stack (§10.2 gives
    # app.core NO app.* dependencies at all), and a cycle the moment IU-17 imports
    # anything from core. Under TYPE_CHECKING mypy resolves the annotation and the
    # runtime never executes the import.
    from app.schemas.errors import ErrorDetail

__all__ = [
    "AlbumNameConflict",
    "AlbumNotFound",
    "AnnotationGeometryInvalid",
    "AnnotationNotFound",
    "AnnotationOutOfBounds",
    "AnnotationVersionNotFound",
    "ArtifactReadFailed",
    "ArtifactWriteFailed",
    "AuthError",
    "BatchNotFound",
    "BatchTooLarge",
    "BboxCrossesAntimeridian",
    "CameraNotFound",
    "CameraPoseNotAvailable",
    "CannotRescaleGeotiff",
    "ConfigurationError",
    "ConfirmationRequired",
    "ConflictError",
    "DatabaseUnavailable",
    "DependencyUnavailable",
    "EmptyPatch",
    "EmptyPatchError",
    "ExportExpired",
    "ExportNotFound",
    "ExportNotReady",
    "FeatureDeferredError",
    "ForbiddenError",
    "GcpAdjustmentAmbiguous",
    "GcpCodeConflict",
    "GcpNotFound",
    "GcpOriginalUnavailable",
    "GcpOutOfBounds",
    "GeometryTooComplex",
    "GoneError",
    "HeatmapNotAvailable",
    "IdempotencyInProgress",
    "IdempotencyKeyReused",
    "ImageNotFound",
    "ImagePurged",
    "ImageStillProcessing",
    "ImageTooLarge",
    "InsufficientAnchors",
    "InsufficientStorage",
    "InvalidBBox",
    "InvalidCredentials",
    "InvalidSortField",
    "JobNotCancellable",
    "JobNotFound",
    "LandExplorerError",
    "MatchJobAlreadyRunning",
    "MatchResultNotFound",
    "MissingCredentials",
    "NoAdjustedGcps",
    "NoAnnotations",
    "NotFoundError",
    "ParamConflict",
    "PayloadTooLargeError",
    "PreconditionFailedError",
    "PreconditionRequired",
    "PreconditionRequiredError",
    "ProjectHasActiveJobs",
    "ProjectNameConflict",
    "ProjectNotFound",
    "ProviderError",
    "ProviderInvalidResponse",
    "ProviderNotConfigured",
    "ProviderRateLimited",
    "ProviderToSForbidden",
    "ProviderUpstreamError",
    "RangeNotSatisfiable",
    "RangeNotSatisfiableError",
    "RateLimitError",
    "RateLimitExceeded",
    "ReadOnlyMode",
    "RedisUnavailable",
    "RevisionConflict",
    "RevisionNotFound",
    "RevisionPruned",
    "RevisionReplayTooExpensive",
    "RevisionRestoreConflict",
    "SatelliteImagePurged",
    "SearchAreaTooLarge",
    "SearchHintRequired",
    "StaleAnnotationVersion",
    "StaleGcpVersion",
    "StaleProjectVersion",
    "StaticImageTooLarge",
    "StorageError",
    "SuggestionNotFound",
    "TooManyAnnotations",
    "UnknownProvider",
    "UnknownQueryParam",
    "UnsupportedImageFormat",
    "UnsupportedMediaTypeError",
    "UnsupportedVideoFormat",
    "UploadTooLarge",
    "ValidationError",
    "VideoFrameUnavailable",
    "VideoNotFound",
    "WorkerUnavailable",
    "ZoomOutOfRange",
]


class LandExplorerError(Exception):
    """Base of every domain error.

    ``code`` and ``status`` are ClassVars, not instance state: the code is a property
    of the *kind* of failure, and duplicating it per raise site is how two call sites
    end up emitting ``GCP_NOT_FOUND`` and ``GCPNOTFOUND``.
    """

    code: ClassVar[str] = "INTERNAL_ERROR"
    status: ClassVar[int] = 500

    def __init__(
        self,
        message: str,
        *,
        details: Sequence[ErrorDetail] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        """
        Args:
            message: Human, English, safe to display. **Never** SQL, stack frames,
                filesystem paths, or provider keys — this string reaches the browser.
            details: Field-level detail, rendered into ``ErrorBody.details``.
            headers: Response headers the failure requires. This is not decoration:
                ``429`` carries ``Retry-After``, ``412`` carries ``ETag``, and
                ``428`` tells the client which precondition it omitted. The handler
                copies them onto the response verbatim.
        """
        super().__init__(message)
        self.message = message
        self.details: list[ErrorDetail] = list(details) if details else []
        self.headers: dict[str, str] = dict(headers) if headers else {}

    @property
    def docs_url(self) -> str | None:
        """The documentation anchor for this error's code, or None if undocumented."""
        return docs_url_for(self.code)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code!r}, status={self.status}, message={self.message!r})"


# ── 501 — the SCOPE.md surface ────────────────────────────────────────────────


class FeatureDeferredError(LandExplorerError):
    """A registered, documented, planned feature that this build does not implement.

    ★ **SCOPE.md.** The automatic matching engine is deferred: feature extraction,
    matching, RANSAC, camera pose, heatmaps, semantic segmentation, scoring and
    landmark suggestion are ABCs and stubs in this build. Their endpoints
    (``POST /images/{id}/match``, ``/suggest-landmarks``, ``/segment``,
    ``/camera-pose``, ``/heatmap``) stay **registered and documented** and raise
    this.

    **501, not 404.** The feature is *planned, not absent*: a 404 tells a client the
    route was a typo and invites it to stop asking; a 501 tells it the route is real
    and not yet enabled. And it must never fake a result — no placeholder coordinate,
    no invented confidence, no spinner that never resolves. A confidently-wrong
    coordinate handed to a surveyor is this system's worst failure mode (L12), and a
    fabricated one is worse than a refusal by exactly that margin.

    ``feature`` is the marker the API layer renders as ``feature: "deferred"``. It is
    also surfaced in ``details`` so it reaches the client through the uniform
    envelope without ``ErrorBody`` needing a bespoke field.
    """

    code: ClassVar[str] = "FEATURE_DEFERRED"
    status: ClassVar[int] = 501

    #: The marker value the API layer emits. Constant by design — a client tests
    #: `feature === "deferred"`, not a taxonomy.
    feature: ClassVar[str] = "deferred"

    def __init__(
        self,
        message: str,
        *,
        component: str,
        details: Sequence[ErrorDetail] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        """
        Args:
            message: What is deferred, in the surveyor's terms, and what to do
                instead. E.g. "Automatic matching is not enabled in this build —
                place GCPs manually."
            component: The deferred module or capability, for logs and for the
                ``details`` entry. E.g. ``"ai_engine.pipeline.orchestrator"``.
        """
        super().__init__(message, details=details, headers=headers)
        self.component = component

    def marker(self) -> dict[str, Any]:
        """The ``{"feature": "deferred", ...}`` marker for the error envelope.

        IU-21's handler merges this into the response body. Kept as a method here so
        the shape has one definition rather than one per deferred endpoint.
        """
        return {"feature": self.feature, "component": self.component, "scope": "docs/architecture/SCOPE.md"}


# ── 500 — configuration ───────────────────────────────────────────────────────


class ConfigurationError(LandExplorerError):
    """The operator asked for something the deployment cannot do. Fail at boot.

    ★ Not in §6.3's tree, but §11.3 mandates the behaviour it names: *"boto3 — only
    reachable with LE_STORAGE_BACKEND=s3; that is a configuration error, **not a
    degradation** -> ConfigurationError at boot."* The distinction is the whole of
    L11: a missing *optional* dependency degrades and warns, but a dependency that
    an explicit setting **requires** is a mistake, and starting up to serve 500s per
    request instead of refusing to start is how it reaches production unnoticed.
    """

    code: ClassVar[str] = "CONFIGURATION_ERROR"
    status: ClassVar[int] = 500


# ── 404 ───────────────────────────────────────────────────────────────────────


class NotFoundError(LandExplorerError):
    code: ClassVar[str] = "NOT_FOUND"
    status: ClassVar[int] = 404


class ProjectNotFound(NotFoundError):
    code: ClassVar[str] = "PROJECT_NOT_FOUND"


class AlbumNotFound(NotFoundError):
    code: ClassVar[str] = "ALBUM_NOT_FOUND"


class CameraNotFound(NotFoundError):
    code: ClassVar[str] = "CAMERA_NOT_FOUND"


class ImageNotFound(NotFoundError):
    code: ClassVar[str] = "IMAGE_NOT_FOUND"


class VideoNotFound(NotFoundError):
    code: ClassVar[str] = "VIDEO_NOT_FOUND"


class AnnotationNotFound(NotFoundError):
    code: ClassVar[str] = "ANNOTATION_NOT_FOUND"


class JobNotFound(NotFoundError):
    """Also the honest answer for a retention-deleted job: there is no `expired`
    state, the row is gone, and gone is 404 (§5.5)."""

    code: ClassVar[str] = "JOB_NOT_FOUND"


class MatchResultNotFound(NotFoundError):
    code: ClassVar[str] = "MATCH_RESULT_NOT_FOUND"


class GcpNotFound(NotFoundError):
    code: ClassVar[str] = "GCP_NOT_FOUND"


class RevisionNotFound(NotFoundError):
    code: ClassVar[str] = "REVISION_NOT_FOUND"


class AnnotationVersionNotFound(NotFoundError):
    code: ClassVar[str] = "ANNOTATION_VERSION_NOT_FOUND"


class ExportNotFound(NotFoundError):
    code: ClassVar[str] = "EXPORT_NOT_FOUND"


class BatchNotFound(NotFoundError):
    code: ClassVar[str] = "BATCH_NOT_FOUND"


class SuggestionNotFound(NotFoundError):
    code: ClassVar[str] = "SUGGESTION_NOT_FOUND"


class PrecacheOperationNotFound(NotFoundError):
    code: ClassVar[str] = "PRECACHE_OPERATION_NOT_FOUND"


class OfflineManifestNotFound(NotFoundError):
    code: ClassVar[str] = "OFFLINE_MANIFEST_NOT_FOUND"


class CameraPoseNotAvailable(NotFoundError):
    """No pose was produced for this result — distinct from 'the feature is deferred'.

    A deferred pose endpoint raises FeatureDeferredError (501). This is the 404 for
    a live pose path that simply has no row.
    """

    code: ClassVar[str] = "CAMERA_POSE_NOT_AVAILABLE"


class HeatmapNotAvailable(NotFoundError):
    code: ClassVar[str] = "HEATMAP_NOT_AVAILABLE"


class UnknownProvider(NotFoundError):
    """A provider name that is not registered at all — as opposed to registered and
    unconfigured, which is 503 PROVIDER_NOT_CONFIGURED."""

    code: ClassVar[str] = "UNKNOWN_PROVIDER"


# ── 422 ───────────────────────────────────────────────────────────────────────


class ValidationError(LandExplorerError):
    code: ClassVar[str] = "VALIDATION_ERROR"
    status: ClassVar[int] = 422


class InvalidBBox(ValidationError):
    code: ClassVar[str] = "INVALID_BBOX"


class BboxCrossesAntimeridian(ValidationError):
    """Refused rather than silently mishandled. A bbox that wraps 180° and is treated
    as if it did not covers the entire globe *except* the parcel the surveyor meant."""

    code: ClassVar[str] = "BBOX_CROSSES_ANTIMERIDIAN"


class InvalidSortField(ValidationError):
    """Carries the allowed set in ``details`` — an error that says only 'invalid' makes
    the client guess."""

    code: ClassVar[str] = "INVALID_SORT_FIELD"


class UnknownQueryParam(ValidationError):
    """Never ignored. A typo'd filter that silently returns unfiltered data is how a
    surveyor exports the wrong parcel."""

    code: ClassVar[str] = "UNKNOWN_QUERY_PARAM"


class ParamConflict(ValidationError):
    code: ClassVar[str] = "PARAM_CONFLICT"


class SearchHintRequired(ValidationError):
    """Unconditional (§12 C-37). A hint is a hard input requirement, not a toggle;
    LE_SEARCH_REQUIRE_PRIOR is deleted because a flag implying global search is
    possible would be a lie."""

    code: ClassVar[str] = "SEARCH_HINT_REQUIRED"


class ZoomOutOfRange(ValidationError):
    code: ClassVar[str] = "ZOOM_OUT_OF_RANGE"


class SearchAreaTooLarge(ValidationError):
    code: ClassVar[str] = "SEARCH_AREA_TOO_LARGE"


class NoAnnotations(ValidationError):
    code: ClassVar[str] = "NO_ANNOTATIONS"


class GcpAdjustmentAmbiguous(ValidationError):
    code: ClassVar[str] = "GCP_ADJUSTMENT_AMBIGUOUS"


class GcpOutOfBounds(ValidationError):
    code: ClassVar[str] = "GCP_OUT_OF_BOUNDS"


class AnnotationGeometryInvalid(ValidationError):
    code: ClassVar[str] = "ANNOTATION_GEOMETRY_INVALID"


class CannotRescaleGeotiff(ValidationError):
    """A GeoTIFF cannot be rescaled — resizing drops the geotransform.

    422, not 409: the request is well-formed but semantically impossible. A GeoTIFF's
    pixels are bound to ground coordinates by its geotransform; resampling to a new
    pixel grid silently invalidates that mapping, turning a georeferenced deliverable
    into a plain raster that still *claims* to be georeferenced — the exact
    half-georeferenced state ``ck_images_geotiff_complete`` exists to forbid. The
    honest answer is to refuse, so the surveyor re-derives control the right way rather
    than shipping a corrupted GeoTIFF.
    """

    code: ClassVar[str] = "CANNOT_RESCALE_GEOTIFF"


class AnnotationOutOfBounds(ValidationError):
    code: ClassVar[str] = "ANNOTATION_OUT_OF_BOUNDS"


class TooManyAnnotations(ValidationError):
    code: ClassVar[str] = "TOO_MANY_ANNOTATIONS"


class GeometryTooComplex(ValidationError):
    code: ClassVar[str] = "GEOMETRY_TOO_COMPLEX"


class StaticImageTooLarge(ValidationError):
    code: ClassVar[str] = "STATIC_IMAGE_TOO_LARGE"


class PrecacheBudgetExceeded(ValidationError):
    """An offline pre-cache request exceeds a configured request budget.

    422 with the numbers in the message: the surveyor shrinks the AOI/zoom band or the
    operator raises ``LE_MAPBOX_MAX_TILE_REQUESTS_PER_OPERATION`` /
    ``LE_MAPBOX_MAX_PREFETCH_TILES`` / ``LE_MAPBOX_MAX_TILE_REQUESTS_PER_DAY``. Refusing
    up front beats a silent multi-gigabyte, multi-dollar download."""

    code: ClassVar[str] = "PRECACHE_BUDGET_EXCEEDED"


class PrecacheConflict(ValidationError):
    """The requested state change is impossible for this operation's current state
    (resume a cancelled run, start a second run for the same provider, …)."""

    code: ClassVar[str] = "PRECACHE_CONFLICT"


class ImageTooLarge(ValidationError):
    code: ClassVar[str] = "IMAGE_TOO_LARGE"


class VideoFrameUnavailable(ValidationError):
    """The requested timestamp is out of range, or no frame could be decoded there.

    422, not 500: an unreadable frame at a client-supplied second is bad input, not a
    server fault. The frame extractor raises a plain ``FrameExtractionError`` and the
    video service maps it here."""

    code: ClassVar[str] = "VIDEO_FRAME_UNAVAILABLE"


class NoAdjustedGcps(ValidationError):
    code: ClassVar[str] = "NO_ADJUSTED_GCPS"


class InsufficientAnchors(ValidationError):
    code: ClassVar[str] = "INSUFFICIENT_ANCHORS"


class RevisionReplayTooExpensive(ValidationError):
    code: ClassVar[str] = "REVISION_REPLAY_TOO_EXPENSIVE"


# ── 400 ───────────────────────────────────────────────────────────────────────


class EmptyPatchError(LandExplorerError):
    code: ClassVar[str] = "EMPTY_PATCH"
    status: ClassVar[int] = 400


#: §6.3 names the branch ``EmptyPatchError`` and the leaf ``EmptyPatch``. They are
#: the same failure; the alias exists so both names in the contract resolve.
EmptyPatch = EmptyPatchError


# ── 409 ───────────────────────────────────────────────────────────────────────


class ConflictError(LandExplorerError):
    code: ClassVar[str] = "CONFLICT"
    status: ClassVar[int] = 409


class MatchJobAlreadyRunning(ConflictError):
    """Returns the running job's id and offers ``?force=true`` — strictly more useful
    than a silent dedupe, which is why the content-derived ``idempotency_key`` column
    was deleted (§12 C-27)."""

    code: ClassVar[str] = "MATCH_JOB_ALREADY_RUNNING"


class ExportNotReady(ConflictError):
    code: ClassVar[str] = "EXPORT_NOT_READY"


class JobNotCancellable(ConflictError):
    """The job is already terminal. Cancelling something that finished is not a
    no-op, it is a misunderstanding, and saying so beats pretending."""

    code: ClassVar[str] = "JOB_NOT_CANCELLABLE"


class RevisionConflict(ConflictError):
    code: ClassVar[str] = "REVISION_CONFLICT"


class RevisionRestoreConflict(ConflictError):
    code: ClassVar[str] = "REVISION_RESTORE_CONFLICT"


class ImageStillProcessing(ConflictError):
    code: ClassVar[str] = "IMAGE_STILL_PROCESSING"


class ProjectHasActiveJobs(ConflictError):
    code: ClassVar[str] = "PROJECT_HAS_ACTIVE_JOBS"


class GcpCodeConflict(ConflictError):
    code: ClassVar[str] = "GCP_CODE_CONFLICT"


class ProjectNameConflict(ConflictError):
    code: ClassVar[str] = "PROJECT_NAME_CONFLICT"


class AlbumNameConflict(ConflictError):
    """``uq_albums_name_lower`` — album names are unique among LIVE albums,
    case-insensitively. Deleting an album frees its name again."""

    code: ClassVar[str] = "ALBUM_NAME_CONFLICT"


class IdempotencyKeyReused(ConflictError):
    """Same Idempotency-Key, different request body. The client has a bug and
    replaying the first response would hide it."""

    code: ClassVar[str] = "IDEMPOTENCY_KEY_REUSED"


class IdempotencyInProgress(ConflictError):
    """The first request with this key has not finished yet. Retry, do not duplicate."""

    code: ClassVar[str] = "IDEMPOTENCY_IN_PROGRESS"


class GcpOriginalUnavailable(ConflictError):
    code: ClassVar[str] = "GCP_ORIGINAL_UNAVAILABLE"


class ImportFileChanged(ConflictError):
    """The file being applied is not the one that was previewed.

    ★ The preview is the operator's consent, and consent is to a specific set of moves.
    If re-parsing at apply time yields a different match count, the bytes changed between
    the two calls — a different file picked, or the same file re-saved — and applying it
    would commit edits nobody looked at. Refusing is the only honest option; the operator
    simply previews again.
    """

    code: ClassVar[str] = "IMPORT_FILE_CHANGED"


# ── 412 / 428 ─────────────────────────────────────────────────────────────────


class PreconditionFailedError(LandExplorerError):
    code: ClassVar[str] = "PRECONDITION_FAILED"
    status: ClassVar[int] = 412


class StaleAnnotationVersion(PreconditionFailedError):
    code: ClassVar[str] = "STALE_ANNOTATION_VERSION"


class StaleGcpVersion(PreconditionFailedError):
    code: ClassVar[str] = "STALE_GCP_VERSION"


class StaleProjectVersion(PreconditionFailedError):
    code: ClassVar[str] = "STALE_PROJECT_VERSION"


class PreconditionRequiredError(LandExplorerError):
    """428, not 412: the client sent no precondition at all.

    The distinction matters — 412 means "your If-Match lost a race", which a client
    retries after refetching; 428 means "you never sent one", which a client fixes in
    its code.
    """

    code: ClassVar[str] = "PRECONDITION_REQUIRED"
    status: ClassVar[int] = 428


PreconditionRequired = PreconditionRequiredError


class ConfirmationRequired(PreconditionRequiredError):
    """A hard delete without ``X-Confirm-Delete``. Destructive and irreversible
    operations get an explicit second signal, not a hopeful one."""

    code: ClassVar[str] = "CONFIRMATION_REQUIRED"


# ── 413 / 415 / 416 ───────────────────────────────────────────────────────────


class PayloadTooLargeError(LandExplorerError):
    code: ClassVar[str] = "PAYLOAD_TOO_LARGE"
    status: ClassVar[int] = 413


class UploadTooLarge(PayloadTooLargeError):
    code: ClassVar[str] = "UPLOAD_TOO_LARGE"


class BatchTooLarge(PayloadTooLargeError):
    code: ClassVar[str] = "BATCH_TOO_LARGE"


class UnsupportedMediaTypeError(LandExplorerError):
    code: ClassVar[str] = "UNSUPPORTED_MEDIA_TYPE"
    status: ClassVar[int] = 415


class UnsupportedImageFormat(UnsupportedMediaTypeError):
    code: ClassVar[str] = "UNSUPPORTED_IMAGE_FORMAT"


class UnsupportedVideoFormat(UnsupportedMediaTypeError):
    """A declared or actual video type outside the allow-list, or a container OpenCV's
    FFMPEG backend cannot open at all. 415, like its image sibling."""

    code: ClassVar[str] = "UNSUPPORTED_VIDEO_FORMAT"


class RangeNotSatisfiableError(LandExplorerError):
    code: ClassVar[str] = "RANGE_NOT_SATISFIABLE"
    status: ClassVar[int] = 416


RangeNotSatisfiable = RangeNotSatisfiableError


# ── 410 ───────────────────────────────────────────────────────────────────────


class GoneError(LandExplorerError):
    """410, not 404: it existed, we deleted it on a schedule, and saying so lets the
    client distinguish 'expired' from 'never yours'."""

    code: ClassVar[str] = "GONE"
    status: ClassVar[int] = 410


class ExportExpired(GoneError):
    code: ClassVar[str] = "EXPORT_EXPIRED"


class ImagePurged(GoneError):
    code: ClassVar[str] = "IMAGE_PURGED"


class RevisionPruned(GoneError):
    code: ClassVar[str] = "REVISION_PRUNED"


class SatelliteImagePurged(GoneError):
    code: ClassVar[str] = "SATELLITE_IMAGE_PURGED"


# ── 401 / 403 ─────────────────────────────────────────────────────────────────


class AuthError(LandExplorerError):
    code: ClassVar[str] = "UNAUTHORIZED"
    status: ClassVar[int] = 401


class MissingCredentials(AuthError):
    """★ The audit trail is enforced the moment there is more than one person who
    could be lying: PATCH /gcps/{id} raises this whenever LE_AUTH_MODE != none and no
    principal resolves (§9.2)."""

    code: ClassVar[str] = "MISSING_CREDENTIALS"


class InvalidCredentials(AuthError):
    code: ClassVar[str] = "INVALID_CREDENTIALS"


class ForbiddenError(LandExplorerError):
    code: ClassVar[str] = "FORBIDDEN"
    status: ClassVar[int] = 403


class ProviderToSForbidden(ForbiddenError):
    """The operator has a key but has not asserted their ToS coverage — e.g. Google
    Static without LE_GOOGLE_TOS_ACKNOWLEDGED=true. The double opt-in is the point."""

    code: ClassVar[str] = "PROVIDER_TOS_FORBIDDEN"


class ReadOnlyMode(ForbiddenError):
    code: ClassVar[str] = "READ_ONLY_MODE"


# ── 429 ───────────────────────────────────────────────────────────────────────


class RateLimitError(LandExplorerError):
    code: ClassVar[str] = "RATE_LIMITED"
    status: ClassVar[int] = 429


class RateLimitExceeded(RateLimitError):
    code: ClassVar[str] = "RATE_LIMIT_EXCEEDED"


class ProviderRateLimited(RateLimitError):
    """Upstream said 429. Pass ``Retry-After`` through in ``headers`` — the upstream
    knows when it will serve us again and we do not."""

    code: ClassVar[str] = "PROVIDER_RATE_LIMITED"


# ── 502 / 503 ─────────────────────────────────────────────────────────────────


class ProviderError(LandExplorerError):
    code: ClassVar[str] = "PROVIDER_ERROR"
    status: ClassVar[int] = 502


class ProviderUpstreamError(ProviderError):
    code: ClassVar[str] = "PROVIDER_UPSTREAM_ERROR"


class ProviderInvalidResponse(ProviderError):
    code: ClassVar[str] = "PROVIDER_INVALID_RESPONSE"


class ProviderNotConfigured(LandExplorerError):
    """★ L11 exception 1 (§11.0). An **explicitly requested** unconfigured provider is
    a 503 — an explicit request is not a default.

    Note the deliberate asymmetry with a missing *weight*, which is a 202 + fallback
    even when explicitly requested: **imagery changes the answer's provenance; a
    matcher changes only its accuracy.** Silently serving 10 m Sentinel when the
    operator paid for 0.3 m Mapbox is worse than a 503. Both are reported; only one
    is refusable.
    """

    code: ClassVar[str] = "PROVIDER_NOT_CONFIGURED"
    status: ClassVar[int] = 503


class DependencyUnavailable(LandExplorerError):
    code: ClassVar[str] = "DEPENDENCY_UNAVAILABLE"
    status: ClassVar[int] = 503


class DatabaseUnavailable(DependencyUnavailable):
    code: ClassVar[str] = "DATABASE_UNAVAILABLE"


class RedisUnavailable(DependencyUnavailable):
    code: ClassVar[str] = "REDIS_UNAVAILABLE"


class WorkerUnavailable(DependencyUnavailable):
    code: ClassVar[str] = "WORKER_UNAVAILABLE"


# ── 500 / 507 ─────────────────────────────────────────────────────────────────


class StorageError(LandExplorerError):
    code: ClassVar[str] = "STORAGE_ERROR"
    status: ClassVar[int] = 500


class ArtifactWriteFailed(StorageError):
    code: ClassVar[str] = "ARTIFACT_WRITE_FAILED"


class ArtifactReadFailed(StorageError):
    code: ClassVar[str] = "ARTIFACT_READ_FAILED"


class InsufficientStorage(LandExplorerError):
    """Checked BEFORE streaming an upload (§9.5). Discovering the disk is full having
    already written 400 MB of a 500 MB file helps nobody."""

    code: ClassVar[str] = "INSUFFICIENT_STORAGE"
    status: ClassVar[int] = 507
