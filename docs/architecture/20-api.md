# 20 — Backend REST API Specification

**Status:** Authoritative for the HTTP surface of LandExplorer v1.
**Owner:** Backend API Architect.
**Companions:** `00-overview.md` (system), `10-database.md` (persistence — **authoritative** for tables/columns/enums), `40-imagery.md` (provider internals), `50-frontend.md` (client consumption).

This document specifies every endpoint, every request/response schema, every status code, and every error case. It is written to be implementable without further design decisions.

---

## 0. Table of contents

1. [Ground rules](#1-ground-rules)
2. [Master endpoint table](#2-master-endpoint-table)
3. [Conventions: pagination, filtering, sorting](#3-conventions-pagination-filtering-sorting)
4. [Error envelope and exception mapping](#4-error-envelope-and-exception-mapping)
5. [Async job contract](#5-async-job-contract)
6. [Health and readiness](#6-health-and-readiness)
7. [Projects](#7-projects)
8. [Images](#8-images)
9. [Annotations (landmarks)](#9-annotations-landmarks)
10. [Revisions and annotation history](#10-revisions-and-annotation-history)
11. [Matching and jobs](#11-matching-and-jobs)
12. [GCPs](#12-gcps)
13. [Landmark suggestions](#13-landmark-suggestions)
14. [Semantic features and segmentation](#14-semantic-features-and-segmentation)
15. [Camera pose](#15-camera-pose)
16. [Confidence heatmap](#16-confidence-heatmap)
17. [Imagery](#17-imagery)
18. [Batch](#18-batch)
19. [Exports](#19-exports)
20. [Capabilities](#20-capabilities)
21. [Router file layout](#21-router-file-layout)
22. [Pydantic v2 schema catalogue](#22-pydantic-v2-schema-catalogue)
23. [OpenAPI, versioning, CORS, rate limiting, auth](#23-openapi-versioning-cors-rate-limiting-auth)

---

## 1. Ground rules

### 1.1 Base path

Every endpoint is prefixed **`/api/v1`**. The prefix is applied once, in `backend/app/api/v1/router.py`, via `APIRouter(prefix="/api/v1")`. No router module repeats it. Paths in this document are written without the prefix in section bodies but **with** it in the master table.

### 1.2 Wire format

- **JSON only** for request/response bodies, except: multipart uploads (`POST /images`, `POST /batch`), and binary responses (`/file`, `/thumbnail`, `/tiles/...`, `/static`, `/exports/{id}/download`).
- **snake_case** on the wire. No alias generator. The frontend generates its TypeScript types from `openapi.json`, so there is zero benefit to camelCase aliasing and a real cost: two names for every field, and a permanent source of `populate_by_name` bugs. Decided: snake_case end to end.
- **UTC, RFC 3339** for all timestamps, always with an explicit `Z` offset (`2026-07-17T09:41:22.481Z`). Serialized from `TIMESTAMPTZ`.
- **UUIDv4 strings** for all resource ids, except `annotation_versions.id` which is a `BIGSERIAL` and is therefore serialized as a JSON **number**. This asymmetry is inherited from the DB design (an append-only log wants a cheap monotonic key) and is called out in every schema that touches it.
- **No nulls omitted.** A nullable field is always present with value `null`. Clients must not distinguish "absent" from "null"; making them identical removes a whole class of TS `undefined` bugs.

### 1.3 Coordinate and unit conventions

These are load-bearing. Getting them wrong silently produces wrong survey coordinates.

| Concept | Convention | Where |
|---|---|---|
| Image pixel space | `(x, y)`, origin **top-left**, y-**down**, floats (sub-pixel allowed), SRID 0 | `pixel_x`, `pixel_y`, `image_px` |
| Satellite mosaic pixel space | `(u, v)`, origin top-left of the candidate mosaic, y-down | `satellite_px` |
| World | **EPSG:4326**, decimal degrees, `lat` then `lon` in objects, but **`[lon, lat]` inside any GeoJSON** (RFC 7946 mandates x,y order) | `lat`, `lon` |
| Homography | 9 floats, **row-major**, maps image pixel → satellite mosaic pixel | `homography` |
| Geotransform | 6 floats, **GDAL order** `[c, a, b, f, d, e]`, maps mosaic pixel → EPSG:3857 | `sat_geotransform` |
| Distances | metres, suffix `_m` | `radius_m`, `elevation_m` |
| Angles | degrees, suffix `_deg` | `yaw_deg` |
| **Match/GCP confidence** | **0–100** float | `confidence`, `overall_confidence` |
| **Annotation confidence** | **0–1** float — this is the *surveyor's own certainty*, a different quantity | `annotations.confidence` |

> **The two confidence scales are deliberate and must not be unified.** `gcps.confidence` (0–100) is an algorithmic score the pipeline computes; `annotations.confidence` (0–1) is a human assertion typed into the annotation tool. They mean different things, are produced by different actors, and are never compared. The DB enforces both ranges with CHECK constraints. Every schema below states which scale it uses. Any client that renders a "confidence" bar must read the field's scale from this table, not guess.

### 1.4 Naming conventions

- Schema classes: `XxxCreate` (POST body), `XxxUpdate` (PATCH body, all fields optional), `XxxRead` (full response), `XxxSummary` (list-item projection), `XxxListParams` (query-param dependency model).
- Every response model that maps to an ORM row sets `model_config = ConfigDict(from_attributes=True, extra="forbid")`.
- Every request model sets `extra="forbid"`. A typo'd field is a 422, never a silent no-op. This is non-negotiable for a PATCH surface where a silently-ignored field means an unsaved survey correction.
- `operation_id` follows `{tag}_{action}` (`images_upload`, `gcps_patch`) so the generated TS client reads `api.images.upload(...)` instead of `api.uploadImagesApiV1ImagesPost(...)`.

### 1.5 What the API never does

- **Never blocks on CV work.** Every OpenCV/Torch/GDAL operation heavier than reading EXIF or generating a thumbnail runs in Celery. Endpoints that trigger such work return `202` with a job handle. The only synchronous raster work in the request path is thumbnail generation on upload (bounded, ~50 ms) and tile transcoding in the proxy (bounded, cached).
- **Never lets a missing model weight reach the client as an error.** Weight absence is a *degradation*, surfaced as `degraded: true` + `warnings[]` on the result, never a 5xx. See §5.5.
- **Never leaks an imagery provider API key.** See §17.2.
- **Never returns a bare list.** All collection responses are wrapped in `Page[T]`. Bare top-level JSON arrays are a JSON hijacking footgun and make it impossible to add pagination later without a breaking change.

---

## 2. Master endpoint table

| # | Method | Path | Purpose |
|---|---|---|---|
| **Health** |
| 1 | `GET` | `/api/v1/health` | Liveness. No dependencies touched. Always 200 if the process is up. |
| 2 | `GET` | `/api/v1/health/ready` | Readiness. Checks Postgres, Redis, Celery workers, default imagery provider, storage, model weights. |
| **Capabilities** |
| 3 | `GET` | `/api/v1/capabilities` | What this deployment can actually do: available extractors, matchers, providers, export formats, model-weight presence. Drives frontend dropdowns. |
| **Projects** |
| 4 | `POST` | `/api/v1/projects` | Create a project. |
| 5 | `GET` | `/api/v1/projects` | List projects, paginated/filtered/sorted. |
| 6 | `GET` | `/api/v1/projects/{project_id}` | Get one project with rollup counts. |
| 7 | `PATCH` | `/api/v1/projects/{project_id}` | Partial update (name, description, aoi, default pipeline config). |
| 8 | `DELETE` | `/api/v1/projects/{project_id}` | Soft-delete a project and cascade-hide its images. |
| **Images** |
| 9 | `POST` | `/api/v1/images` | Multipart upload. JPG/PNG/TIFF/GeoTIFF. Returns extracted metadata incl. EXIF + GPS. |
| 10 | `GET` | `/api/v1/images` | List images, paginated. |
| 11 | `GET` | `/api/v1/images/{image_id}` | Get one image record. |
| 12 | `GET` | `/api/v1/images/{image_id}/file` | Download/stream original bytes. Range-capable. |
| 13 | `GET` | `/api/v1/images/{image_id}/thumbnail` | Cached thumbnail, size-parameterized. |
| 14 | `GET` | `/api/v1/images/{image_id}/metadata` | Full metadata: verbatim EXIF, decoded GPS, camera, GeoTIFF georeference. |
| 15 | `DELETE` | `/api/v1/images/{image_id}` | Soft-delete (default) or hard-delete an image. |
| **Annotations (landmarks)** |
| 16 | `GET` | `/api/v1/images/{image_id}/annotations` | List an image's live annotations, in toolbar order. |
| 17 | `POST` | `/api/v1/images/{image_id}/annotations` | Create one annotation. |
| 18 | `PUT` | `/api/v1/images/{image_id}/annotations` | **Bulk upsert** — the annotation tool's save-everything call. Transactional, one revision. |
| 19 | `DELETE` | `/api/v1/images/{image_id}/annotations` | Soft-delete all annotations on the image (one revision). |
| 20 | `GET` | `/api/v1/annotations/{annotation_id}` | Get one annotation. |
| 21 | `PATCH` | `/api/v1/annotations/{annotation_id}` | **Edit a single point.** Optimistic-locked via `If-Match`. |
| 22 | `DELETE` | `/api/v1/annotations/{annotation_id}` | Soft-delete one annotation (tombstone, recoverable). |
| **Revisions / history** |
| 23 | `GET` | `/api/v1/projects/{project_id}/revisions` | List project revisions (the restorable checkpoints + event groups). |
| 24 | `POST` | `/api/v1/projects/{project_id}/revisions` | Cut an explicit, labelled checkpoint. |
| 25 | `GET` | `/api/v1/revisions/{revision_id}` | Get one revision, with its materialized annotation snapshot. |
| 26 | `POST` | `/api/v1/revisions/{revision_id}/restore` | Restore the project's annotations to that revision. Forward-only (creates a new revision). |
| 27 | `GET` | `/api/v1/images/{image_id}/annotation-versions` | Per-image append-only event timeline (undo stack / audit). |
| 28 | `GET` | `/api/v1/annotations/{annotation_id}/versions` | Per-annotation history. |
| 29 | `GET` | `/api/v1/annotation-versions/{version_id}` | Get one event (`before`/`after` payloads). `version_id` is an integer. |
| **Matching** |
| 30 | `POST` | `/api/v1/images/{image_id}/match` | Start an async match job. Body = search hint + pipeline selection. → `202`. |
| 31 | `GET` | `/api/v1/jobs` | List jobs, filterable by type/status/image/batch. |
| 32 | `GET` | `/api/v1/jobs/{job_id}` | Job status + progress. Supports long-poll via `?wait=`. |
| 33 | `DELETE` | `/api/v1/jobs/{job_id}` | Request cancellation. |
| 34 | `GET` | `/api/v1/images/{image_id}/match-results` | Ranked candidate results for an image. |
| 35 | `GET` | `/api/v1/match-results/{match_result_id}` | One match result: homography, stats, score breakdown. |
| 36 | `GET` | `/api/v1/match-results/{match_result_id}/satellite-image` | The cached satellite mosaic that this match landed on. |
| 37 | `POST` | `/api/v1/match-results/{match_result_id}/select` | Mark this candidate as the selected one; re-derives GCPs. |
| **GCPs** |
| 38 | `GET` | `/api/v1/images/{image_id}/gcps` | GCPs for an image (from the selected match result by default). |
| 39 | `GET` | `/api/v1/gcps/{gcp_id}` | Get one GCP. |
| 40 | `PATCH` | `/api/v1/gcps/{gcp_id}` | **Manual adjustment mode.** Refine `lat`/`lon` **or** `satellite_px`; server derives the other. |
| 41 | `POST` | `/api/v1/gcps/{gcp_id}/reset` | Revert a manual adjustment to the algorithm's original. Idempotent. |
| 42 | `POST` | `/api/v1/images/{image_id}/gcps/recompute` | Refit the homography using adjusted GCPs as constraints. → `202`. |
| **Suggestions** |
| 43 | `POST` | `/api/v1/images/{image_id}/suggest-landmarks` | AI automatic landmark suggestions. → `202`. |
| 44 | `GET` | `/api/v1/images/{image_id}/landmark-suggestions` | Fetch suggestions produced by a suggest job. |
| 45 | `POST` | `/api/v1/images/{image_id}/landmark-suggestions/accept` | Promote selected suggestions into real annotations. |
| **Semantics** |
| 46 | `GET` | `/api/v1/images/{image_id}/semantic-features` | Detected semantic features (masks/polygons) for an image. |
| 47 | `POST` | `/api/v1/images/{image_id}/segment` | Run segmentation (SAM, or classical fallback). → `202`. |
| **Pose** |
| 48 | `GET` | `/api/v1/images/{image_id}/camera-pose` | Estimated camera position + orientation + intrinsics. |
| **Heatmap** |
| 49 | `GET` | `/api/v1/images/{image_id}/heatmap` | Candidate camera locations + scores. `json` / `geojson` / `png`. |
| **Imagery** |
| 50 | `GET` | `/api/v1/imagery/providers` | List providers, which are configured, capabilities, attribution. |
| 51 | `GET` | `/api/v1/imagery/providers/{provider}` | One provider's detail + live self-check. |
| 52 | `GET` | `/api/v1/imagery/tiles/{provider}/{z}/{x}/{y}` | **Server-side tile proxy.** Keys never reach the browser. |
| 53 | `GET` | `/api/v1/imagery/static` | bbox → stitched image (PNG/JPEG/GeoTIFF). |
| **Batch** |
| 54 | `POST` | `/api/v1/batch` | Batch over many images (multipart upload **or** JSON of existing ids). → `202`. |
| 55 | `GET` | `/api/v1/batch` | List batch jobs. |
| 56 | `GET` | `/api/v1/batch/{batch_id}` | Batch status, per-item rollup. |
| 57 | `DELETE` | `/api/v1/batch/{batch_id}` | Cancel a batch and its pending children. |
| **Exports** |
| 58 | `POST` | `/api/v1/images/{image_id}/export` | Export one image's GCPs. `?format=csv\|geojson\|shapefile\|kml\|pdf`. → `202`. |
| 59 | `POST` | `/api/v1/projects/{project_id}/export` | Export a whole project. → `202`. |
| 60 | `GET` | `/api/v1/exports` | List exports. |
| 61 | `GET` | `/api/v1/exports/{export_id}` | Export status + download link + expiry. |
| 62 | `GET` | `/api/v1/exports/{export_id}/download` | Download the artifact bytes. |
| 63 | `DELETE` | `/api/v1/exports/{export_id}` | Delete an export artifact early. |

**63 endpoints across 14 routers.** Endpoints 3, 21, 24, 27–29, 36, 37, 42, 45, 51, 59, 61, 63 are additions beyond the assignment's minimum; each is justified where it is specified.

---

## 3. Conventions: pagination, filtering, sorting

### 3.1 Pagination

**Offset/limit, uniformly, on every collection endpoint.**

| Param | Type | Default | Bounds | Notes |
|---|---|---|---|---|
| `limit` | int | `50` | `1..200` | Out of range → `422`, never silently clamped. Silent clamping makes clients believe they read everything. |
| `offset` | int | `0` | `>= 0` | |

Response envelope — `Page[ItemT]` in `backend/app/schemas/common.py`:

```jsonc
{
  "items":    [ /* ItemT */ ],
  "total":    1274,      // exact count matching the filter, ignoring limit/offset
  "limit":    50,
  "offset":   100,
  "has_more": true       // offset + len(items) < total
}
```

`Page` is a Pydantic v2 generic:

```python
ItemT = TypeVar("ItemT")

class Page(BaseModel, Generic[ItemT]):
    items: list[ItemT]
    total: int
    limit: int
    offset: int
    has_more: bool

    @classmethod
    def of(cls, items: Sequence[ItemT], total: int, p: PaginationParams) -> "Page[ItemT]": ...
```

FastAPI instantiates it concretely per route (`response_model=Page[ImageSummary]`), which produces a distinct, properly-named OpenAPI component `Page_ImageSummary_` and therefore a clean generated TS type. The `Page` model is exported once; each route parameterizes it.

**Why offset and not cursor.** Cursor pagination is strictly better for large, hot, append-heavy collections. LandExplorer has none: a project holds tens of images, an image holds tens to low-hundreds of annotations, a match produces ≤ `max_candidates` (default 25) results. The largest realistic collection is `annotation_versions` for a heavily-edited image — low thousands. Offset pagination over a `(image_id, id DESC)` index at those cardinalities is free, and `total` is what the UI actually wants (it renders "1,274 events"). Cursor pagination cannot cheaply produce `total`. Decided: offset.

**The one exception** is documented, not hidden: `GET /images/{image_id}/annotation-versions` additionally accepts `before_id` (int). Passing it switches that endpoint to keyset mode (`WHERE id < before_id ORDER BY id DESC`), used by the undo stack's infinite scroll where `offset` would skip events as new ones land. When `before_id` is supplied, `offset` must be absent → else `422 PARAM_CONFLICT`. `total` is still returned.

### 3.2 Filtering

**Explicit, whitelisted query params only. No generic filter DSL.** A `?filter=` mini-language is a security surface (it becomes SQL) and an OpenAPI blind spot (it types as `string`). Every filter is a declared, typed, documented param, bound through a `*ListParams` Pydantic dependency.

Grammar:

| Form | Meaning | Example |
|---|---|---|
| `field=value` | equality | `?status=succeeded` |
| `field=v1,v2` | IN (comma-separated) | `?status=queued,running` |
| `field__gte=`, `field__lte=` | inclusive range | `?confidence__gte=70` |
| `field__gt=`, `field__lt=` | exclusive range | `?created_at__gt=2026-07-01T00:00:00Z` |
| `q=` | free-text search, per-endpoint semantics | `?q=north+parcel` |
| `bbox=` | `minlon,minlat,maxlon,maxlat` spatial intersect | `?bbox=12.4,41.8,12.6,42.0` |
| `include_deleted=` | bool, default `false` | `?include_deleted=true` |

Rules:
- Unknown query param → **`422 UNKNOWN_QUERY_PARAM`**, not ignored. (`extra="forbid"` on `*ListParams`.) A typo'd filter that silently returns unfiltered data is how a surveyor exports the wrong parcel.
- Multiple filters AND together. There is no OR. If a screen needs OR, it gets a purpose-built param.
- `bbox` is validated: `minlon < maxlon`, `minlat < maxlat`, lat ∈ [-90,90], lon ∈ [-180,180], area ≤ 25 deg² → else `422 INVALID_BBOX`. Antimeridian-crossing bboxes are rejected in v1 (`422 BBOX_CROSSES_ANTIMERIDIAN`) rather than silently mishandled.
- Soft-deleted rows (`deleted_at IS NOT NULL` / `is_deleted = true`) are excluded by default everywhere.

### 3.3 Sorting

`?sort=` takes a comma-separated list of fields; a leading `-` means descending.

```
?sort=-created_at            # newest first
?sort=ordering,created_at    # toolbar order, ties by age
?sort=-confidence,code       # best GCPs first
```

- Each endpoint declares a **whitelist**; a field outside it → `422 INVALID_SORT_FIELD` with the allowed set in `error.details`.
- Max 3 sort keys → else `422`.
- Every sort is **stabilized**: the server silently appends `id ASC` as the final tiebreaker. Without this, offset pagination over equal-valued rows (e.g. 40 GCPs all at `confidence = 100`) duplicates and drops rows across pages. This is invisible to the client and always applied.
- Parsed by `SortParams` in `common.py`:

```python
class SortParams(BaseModel):
    raw: str | None = None
    def parse(self, allowed: frozenset[str], default: str) -> list[tuple[str, Literal["asc", "desc"]]]: ...
```

Defaults per endpoint are stated in each section (almost always `-created_at`).

---

## 4. Error envelope and exception mapping

### 4.1 The envelope

**Every** non-2xx response — including FastAPI's own validation errors and unhandled exceptions — has this exact shape. Uniformity is enforced by overriding FastAPI's `RequestValidationError` and `HTTPException` handlers in `backend/app/api/errors.py`; the default `{"detail": ...}` shape never escapes.

```jsonc
{
  "error": {
    "code": "IMAGE_NOT_FOUND",
    "message": "Image 7f3a1c2e-… does not exist.",
    "status": 404,
    "details": [
      { "loc": ["path", "image_id"], "msg": "not found", "type": "not_found", "input": "7f3a1c2e-…" }
    ],
    "request_id": "01J8XW6M4T7Q2R9K3ZC5VYB0AE",
    "timestamp": "2026-07-17T09:41:22.481Z",
    "docs_url": "https://docs.landexplorer.local/errors/IMAGE_NOT_FOUND"
  }
}
```

| Field | Type | Notes |
|---|---|---|
| `code` | `str` | **Stable, machine-readable, SCREAMING_SNAKE.** The client switches on this. Never localize, never reword; adding a code is additive, changing one is breaking. |
| `message` | `str` | Human-readable, English, safe to display. Never contains SQL, stack frames, file paths, or provider keys. |
| `status` | `int` | Mirrors the HTTP status. Duplicated in-body deliberately: it survives logging, proxies, and client libs that discard the status line. |
| `details` | `list[ErrorDetail] \| null` | Field-level detail. Pydantic's `loc/msg/type/input` shape, reused verbatim for validation errors so the frontend has one parser. |
| `request_id` | `str` | ULID from `RequestIdMiddleware`; also returned as the `X-Request-ID` header and printed in every log line for that request. This is the string a user pastes into a bug report. |
| `timestamp` | `str` | RFC 3339 UTC. |
| `docs_url` | `str \| null` | Deep link per code. |

Schemas: `ErrorEnvelope`, `ErrorBody`, `ErrorDetail` in `backend/app/schemas/errors.py`. `ErrorEnvelope` is registered as the `responses=` model for 4xx/5xx on every route via a shared `COMMON_ERROR_RESPONSES` dict, so `openapi.json` documents it everywhere rather than on a lucky few routes.

### 4.2 Exception hierarchy

Defined in `backend/app/core/exceptions.py`. Application code raises **domain** exceptions and never `HTTPException` — that keeps the service layer importable and unit-testable without FastAPI, and is what lets the same services run inside Celery workers where `HTTPException` would be nonsense.

```python
class LandExplorerError(Exception):
    code: ClassVar[str]
    status: ClassVar[int]
    def __init__(self, message: str, *, details: list[ErrorDetail] | None = None, headers: dict[str, str] | None = None): ...
```

```
LandExplorerError
├── NotFoundError            (404)  ProjectNotFound, ImageNotFound, AnnotationNotFound,
│                                   JobNotFound, MatchResultNotFound, GcpNotFound,
│                                   RevisionNotFound, ExportNotFound, BatchNotFound,
│                                   CameraPoseNotAvailable, HeatmapNotAvailable
├── ValidationError          (422)  InvalidBBox, InvalidSortField, UnknownQueryParam,
│                                   SearchHintRequired, GcpAdjustmentAmbiguous,
│                                   AnnotationGeometryInvalid, ParamConflict,
│                                   StaticImageTooLarge, ZoomOutOfRange
├── ConflictError            (409)  MatchJobAlreadyRunning, ExportNotReady,
│                                   RevisionRestoreConflict, JobNotCancellable,
│                                   ImageStillProcessing
├── PreconditionFailedError  (412)  StaleAnnotationVersion, StaleGcpVersion
├── PayloadTooLargeError     (413)  UploadTooLarge, BatchTooLarge
├── UnsupportedMediaTypeError(415)  UnsupportedImageFormat
├── GoneError                (410)  ExportExpired, ImagePurged
├── AuthError                (401)  MissingCredentials, InvalidCredentials
├── ForbiddenError           (403)  ProviderToSForbidden, ReadOnlyMode
├── RateLimitError           (429)  RateLimitExceeded, ProviderRateLimited
├── ProviderError            (502)  ProviderUpstreamError, ProviderInvalidResponse
├── ProviderNotConfigured    (503)  — key/credential absent for a keyed provider
├── DependencyUnavailable    (503)  DatabaseUnavailable, RedisUnavailable, WorkerUnavailable
└── StorageError             (500)  ArtifactWriteFailed, ArtifactReadFailed
```

### 4.3 Mapping table

A single handler `landexplorer_exception_handler` reads `exc.status`/`exc.code`. There is no per-exception `if`-ladder.

| Exception | HTTP | `error.code` | When | Client action |
|---|---|---|---|---|
| `ProjectNotFound` | 404 | `PROJECT_NOT_FOUND` | unknown/soft-deleted project id | show 404 page |
| `ImageNotFound` | 404 | `IMAGE_NOT_FOUND` | unknown/soft-deleted image id | |
| `AnnotationNotFound` | 404 | `ANNOTATION_NOT_FOUND` | unknown or tombstoned annotation | drop from local store |
| `JobNotFound` | 404 | `JOB_NOT_FOUND` | unknown job id, or job reaped past retention | stop polling |
| `MatchResultNotFound` | 404 | `MATCH_RESULT_NOT_FOUND` | | |
| `GcpNotFound` | 404 | `GCP_NOT_FOUND` | | |
| `RevisionNotFound` | 404 | `REVISION_NOT_FOUND` | | |
| `ExportNotFound` | 404 | `EXPORT_NOT_FOUND` | | |
| `BatchNotFound` | 404 | `BATCH_NOT_FOUND` | | |
| `CameraPoseNotAvailable` | 404 | `CAMERA_POSE_NOT_AVAILABLE` | no successful match yet, or pose not estimable | hide the pose panel |
| `HeatmapNotAvailable` | 404 | `HEATMAP_NOT_AVAILABLE` | job never produced a heatmap | hide the heatmap layer |
| `RequestValidationError` (FastAPI) | 422 | `VALIDATION_ERROR` | body/query/path fails Pydantic | highlight fields from `details[].loc` |
| `InvalidBBox` | 422 | `INVALID_BBOX` | malformed/inverted/oversized bbox | |
| `BboxCrossesAntimeridian` | 422 | `BBOX_CROSSES_ANTIMERIDIAN` | `minlon > maxlon` | |
| `InvalidSortField` | 422 | `INVALID_SORT_FIELD` | sort key not whitelisted | |
| `UnknownQueryParam` | 422 | `UNKNOWN_QUERY_PARAM` | `extra="forbid"` on `*ListParams` | |
| `ParamConflict` | 422 | `PARAM_CONFLICT` | mutually exclusive params (`offset`+`before_id`) | |
| `SearchHintRequired` | 422 | `SEARCH_HINT_REQUIRED` | no `center`, no EXIF GPS, no project AOI | prompt for a map click |
| `ZoomOutOfRange` | 422 | `ZOOM_OUT_OF_RANGE` | zoom outside provider `min_zoom..max_zoom` | |
| `GcpAdjustmentAmbiguous` | 422 | `GCP_ADJUSTMENT_AMBIGUOUS` | PATCH sends both `lat`/`lon` and `satellite_px`, inconsistent | send one |
| `AnnotationGeometryInvalid` | 422 | `ANNOTATION_GEOMETRY_INVALID` | self-intersecting polygon, <2 pts polyline, out-of-bounds pixel | |
| `StaticImageTooLarge` | 422 | `STATIC_IMAGE_TOO_LARGE` | requested stitch > 8192×8192 or > 256 tiles | reduce zoom/bbox |
| `MatchJobAlreadyRunning` | 409 | `MATCH_JOB_ALREADY_RUNNING` | active match for image and `force != true` | offer "cancel & restart" |
| `ExportNotReady` | 409 | `EXPORT_NOT_READY` | `/download` before `succeeded` | keep polling |
| `JobNotCancellable` | 409 | `JOB_NOT_CANCELLABLE` | DELETE on a terminal job | refresh |
| `RevisionRestoreConflict` | 409 | `REVISION_RESTORE_CONFLICT` | project mutated mid-restore | re-fetch, retry |
| `ImageStillProcessing` | 409 | `IMAGE_STILL_PROCESSING` | match requested before ingest finished | wait on ingest job |
| `StaleAnnotationVersion` | 412 | `STALE_ANNOTATION_VERSION` | `If-Match` ≠ `version_no` | re-fetch, re-apply, merge |
| `StaleGcpVersion` | 412 | `STALE_GCP_VERSION` | `If-Match` ≠ current GCP etag | |
| `UploadTooLarge` | 413 | `UPLOAD_TOO_LARGE` | body > `MAX_UPLOAD_BYTES` | |
| `BatchTooLarge` | 413 | `BATCH_TOO_LARGE` | > 100 files or > aggregate cap | split |
| `UnsupportedImageFormat` | 415 | `UNSUPPORTED_IMAGE_FORMAT` | magic bytes not JPEG/PNG/TIFF/WebP | |
| `ExportExpired` | 410 | `EXPORT_EXPIRED` | artifact GC'd past `expires_at` | re-export |
| `ImagePurged` | 410 | `IMAGE_PURGED` | record exists, bytes hard-deleted | |
| `MissingCredentials` | 401 | `MISSING_CREDENTIALS` | auth on, no key | login |
| `InvalidCredentials` | 401 | `INVALID_CREDENTIALS` | | |
| `ProviderToSForbidden` | 403 | `PROVIDER_TOS_FORBIDDEN` | provider disabled by operator ToS policy | pick another |
| `ReadOnlyMode` | 403 | `READ_ONLY_MODE` | maintenance | |
| `RateLimitExceeded` | 429 | `RATE_LIMIT_EXCEEDED` | our bucket; sets `Retry-After` | backoff |
| `ProviderRateLimited` | 429 | `PROVIDER_RATE_LIMITED` | upstream 429; sets `Retry-After` | backoff / switch provider |
| `ProviderUpstreamError` | 502 | `PROVIDER_UPSTREAM_ERROR` | upstream 5xx/timeout/garbage | retry or switch |
| `ProviderNotConfigured` | 503 | `PROVIDER_NOT_CONFIGURED` | keyed provider selected, no key | switch to keyless default |
| `DatabaseUnavailable` | 503 | `DATABASE_UNAVAILABLE` | pool exhausted / DB down; `Retry-After: 5` | |
| `RedisUnavailable` | 503 | `REDIS_UNAVAILABLE` | broker down | |
| `WorkerUnavailable` | 503 | `WORKER_UNAVAILABLE` | no Celery workers; job would hang forever | |
| `StorageError` | 500 | `STORAGE_ERROR` | artifact I/O failed | |
| *anything else* | 500 | `INTERNAL_ERROR` | unhandled | show `request_id` |

### 4.4 The 500 handler

Unhandled exceptions are caught by `unhandled_exception_handler`, which:
1. logs `exc_info=True` with `request_id`, route, and principal;
2. increments `landexplorer_unhandled_exceptions_total{route=...}`;
3. returns exactly `{"error":{"code":"INTERNAL_ERROR","message":"An unexpected error occurred.","status":500,"details":null,"request_id":"…","timestamp":"…","docs_url":null}}`.

**Never** the exception string. Tracebacks contain storage paths, connection strings, and provider keys. In `DEBUG=true` only, `details` carries `[{"loc":[],"msg":"<repr>","type":"debug.traceback"}]`. Production defaults `DEBUG=false`.

### 4.5 Warnings: the non-error channel

Degradations are **not** errors and must not use this envelope. A missing SuperGlue weight is a successful match with a note. Every job-producing resource carries:

```jsonc
"warnings": [
  { "code": "MODEL_WEIGHTS_MISSING",
    "message": "SuperGlue weights not found at /models/superglue_outdoor.pth; fell back to matcher 'flann'.",
    "field": "matcher",
    "requested": "superglue",
    "effective": "flann" }
]
```

`WarningItem` in `schemas/common.py`; persisted to `match_jobs.warnings` JSONB. This is the hard requirement from the environment constraints made concrete: **absence of weights is a 200 with a warning, never a 4xx/5xx.**

---

## 5. Async job contract

### 5.1 Starting a job

Every job-starting endpoint (`/match`, `/segment`, `/suggest-landmarks`, `/export`, `/batch`, `/gcps/recompute`) behaves identically:

- Validates input **synchronously**. Bad input is `422` now, not a failed job in 40 seconds. Validation includes: image exists and is `ready`, provider is configured, zooms in range, search area resolvable.
- Inserts the job row (`match_jobs` / `exports` / `batch_jobs`) with `status='pending'` **in the same transaction as nothing else**, then calls `.delay()` **after commit** (via a `SessionEvents.after_commit` hook), then sets `celery_task_id` and `status='queued'`. Enqueueing before commit is the classic race where the worker fetches a row that does not exist yet.
- Returns **`202 Accepted`** with:
  - `Location: /api/v1/jobs/{job_id}` header — RFC 7231 §6.3.3.
  - `Retry-After: 1` header — the polling hint.
  - Body: `JobRead`.

`202` is used and not `201`: the *job* resource is created, but the *outcome* the client asked for is not. `201` would imply the match exists.

### 5.2 Idempotency

All job-starting POSTs and `POST /images` accept an **`Idempotency-Key`** header (client-generated UUID, 24 h TTL in Redis at `idem:{route}:{key}`).

- First request: executes, stores `(status, body, etag)` keyed by the request-hash.
- Replay with same key **and** same body hash: returns the original `202`/`201` verbatim, plus `Idempotency-Replayed: true`.
- Replay with same key but **different** body: `409 IDEMPOTENCY_KEY_REUSED`.
- Concurrent replay while in flight: `409 IDEMPOTENCY_IN_PROGRESS`, `Retry-After: 1`.

This is what makes a React Query `retry: 3` on a flaky uplink safe. Without it, one dropped response on a 400 MB upload creates two images.

### 5.3 Polling

`GET /api/v1/jobs/{job_id}` is the single poll endpoint for **all** job types (`match_jobs`, `exports`, `batch_jobs` are unioned behind a `JobRead` view; `job.type` discriminates).

Client algorithm — normative:

1. `GET /jobs/{id}`.
2. Honor `Retry-After` (seconds). Server emits: `1` while `running`, `2` while `pending`/`queued`, `5` while `retrying`. Never poll faster.
3. Stop on a terminal state (§5.4).
4. On `304 Not Modified` (client sent `If-None-Match`), nothing changed — keep the cached body, keep polling. Progress ticks change the ETag, so 304 is cheap and common.
5. On `404 JOB_NOT_FOUND`, stop. Jobs are retained 30 days; a 404 means reaped or never existed.

**Long-poll (optional, recommended):** `GET /jobs/{id}?wait=25` holds the connection up to 25 s (`0..30`, default `0`), returning as soon as `status` or `progress_stage` changes, else on timeout with the current state. Implemented by subscribing to the Redis pubsub channel `job:{id}:events` the worker publishes to. This cuts poll traffic ~25× and makes the progress bar feel live without introducing a WebSocket. Falls back transparently: if Redis pubsub is unavailable, `wait` is ignored and the current state returns immediately. `wait` requires the request to survive proxy read timeouts — nginx `proxy_read_timeout` must exceed 30 s (documented in the deploy doc).

WebSockets/SSE are explicitly **out of scope for v1**. Polling + long-poll covers a single-user-per-job UI at a fraction of the operational cost.

### 5.4 States

`job_status` (from `10-database.md`, unchanged):

| State | Terminal | Meaning |
|---|---|---|
| `pending` | no | Row inserted; not yet handed to Celery. |
| `queued` | no | `celery_task_id` assigned; sitting in Redis. |
| `running` | no | Worker owns it; `progress` is advancing. |
| `retrying` | no | Transient failure; will re-enter `queued`. `attempt` incremented. |
| `succeeded` | **yes** | `result_ref` populated. |
| `failed` | **yes** | `error_type`/`error_message` populated. |
| `cancelled` | **yes** | User revoked. |

**Terminal set = `{succeeded, failed, cancelled}`.** Clients stop polling on exactly these three. There is no `expired` state: retention deletes the row, which surfaces as `404`.

Transitions (the only legal ones; enforced in the service layer, not by the DB):

```
pending → queued → running → succeeded
                          ├→ failed
                          ├→ retrying → queued
                          └→ cancelled
pending  → cancelled          (never enqueued)
queued   → cancelled          (revoked before pickup)
running  → cancelled          (cooperative; see §5.6)
```

### 5.5 Progress payload

```jsonc
{
  "id": "0a9c…", "type": "match", "status": "running",
  "image_id": "7f3a…", "project_id": "1b2c…", "batch_id": null,
  "attempt": 1, "max_attempts": 3,
  "progress": {
    "percent": 42.5,                    // 0-100, monotonic non-decreasing within an attempt
    "stage": "matching",                // enum, see below
    "message": "Matching tile 108/256 (z=18)",
    "current": 108, "total": 256,       // nullable; unit implied by stage
    "eta_seconds": 37,                  // nullable; null until ≥3 samples
    "tiles_fetched": 108, "tiles_total": 256,
    "candidates_evaluated": 4
  },
  "warnings": [ /* WarningItem */ ],
  "result_ref":  { "kind": "match_result", "id": "cc11…" },   // null until succeeded
  "result_url":  "/api/v1/match-results/cc11…",               // null until succeeded
  "error": null,                                              // ErrorBody-shaped when failed
  "queued_at": "…", "started_at": "…", "finished_at": null,
  "duration_ms": null,
  "created_at": "…", "updated_at": "…"
}
```

`progress.stage` — `JobStage` enum, ordered, per type:

- **match**: `pending` → `resolving_aoi` → `fetching_tiles` → `extracting_query` → `extracting_train` → `matching` → `estimating_homography` → `scoring` → `deriving_gcps` → `persisting` → `done`
- **segment**: `pending` → `loading_model` → `segmenting` → `vectorizing` → `persisting` → `done`
- **suggest_landmarks**: `pending` → `loading_model` → `detecting` → `ranking` → `persisting` → `done`
- **export**: `pending` → `collecting_gcps` → `reprojecting` → `rendering` → `writing` → `done`
- **batch**: `pending` → `fanning_out` → `waiting_children` → `aggregating` → `done`
- **gcp_recompute**: `pending` → `refitting_homography` → `deriving_gcps` → `persisting` → `done`

Rules the workers must honor, because the UI depends on them:
- `percent` is **monotonic non-decreasing within an attempt** and resets to `0` on `retrying`. A progress bar that goes backwards is a bug report.
- `percent` is a **weighted** blend of stages, not `stage_index / n_stages`. Weights ship in `worker/progress.py::STAGE_WEIGHTS` (tile fetch 0.35, extract 0.20, match 0.30, estimate 0.05, score 0.05, persist 0.05) so the bar tracks wall-clock, not stage count.
- `eta_seconds` is null until a stage has ≥3 rate samples. A wrong ETA is worse than none.
- Progress writes are **throttled to ≥250 ms apart** and use a plain `UPDATE match_jobs SET progress…` — never inside the CV transaction. Progress is telemetry; it must never hold a lock a matcher needs.
- **Degradation is reported the instant it is known**, at `loading_model`, not at the end: the job appends a `WarningItem` and continues on the classical path. A client watching `warnings` sees "SuperGlue unavailable → FLANN" within a second of the job starting.

### 5.6 Cancellation

`DELETE /api/v1/jobs/{job_id}`:

- `pending`/`queued` → row set to `cancelled`, `celery_task.revoke()` called. **`200`**, terminal immediately.
- `running` → sets `match_jobs.cancel_requested = true` and publishes to `job:{id}:control`. `revoke(terminate=True)` is **not** used: SIGKILL mid-`cv2.findHomography` leaks the tile cache and can corrupt a partially-written mosaic. Instead workers poll the cancel flag at every stage boundary and inside the tile-fetch loop (every tile) and raise `JobCancelled`, which the task handler converts to `status='cancelled'`. Returns **`202`** with `status: "cancelling"` in the body's `_meta` — the DB status remains `running` until the worker acknowledges (typically < 1 s, bounded by one tile fetch ≈ 2 s).
- terminal → **`409 JOB_NOT_CANCELLABLE`**.

> **Why cancellation is cooperative.** The alternative — `terminate=True` — is a hard kill of a process holding GDAL dataset handles, a torch CUDA context, and an open mosaic file. In practice that orphans `/data/cache/mosaics/*.part` files and, with `torch`, can wedge the CUDA context so the worker's *next* task fails too. A 1-second cooperative window is worth avoiding an entire class of corruption. The `cancelling` intermediate state is exposed so the UI can grey the button instead of lying that it's done.

Cancelling a **batch** cascades: parent `cancelled`, all non-terminal children revoked/flagged. Already-`succeeded` children keep their results — a batch cancel is "stop doing more work", not "undo".

### 5.7 Retries

- `max_attempts = 3` default. Only **transient** failures retry: `ProviderUpstreamError`, `ProviderRateLimited` (respecting upstream `Retry-After`), `RedisUnavailable`, `DatabaseUnavailable`, socket timeouts.
- **Never retried:** `ValidationError`, `SearchHintRequired`, `UnsupportedImageFormat`, `JobCancelled`, and any `MatchFailed` (a genuine "no match found" is a *result*, not a failure — see below).
- Backoff: `min(2 ** attempt * 5s, 120s)` with full jitter.
- On final failure: `status='failed'`, `error_type` = exception class name, `error_message` = safe string, `error_traceback` stored **server-side only** and never serialized into `JobRead.error`.

**"No match found" is `succeeded`, not `failed`.** A match job that fetched tiles, extracted features, and found no candidate above `min_confidence` did its job correctly. It ends `succeeded` with `result_count = 0` and `best_confidence = null`; `GET /images/{id}/match-results` returns an empty page. Modelling this as `failed` would trigger pointless retries of a deterministic outcome and would tell the surveyor the system broke when in fact the answer is "not here". `failed` is reserved for *the pipeline could not run*.

---

## 6. Health and readiness

Router: `backend/app/api/v1/health.py` — `APIRouter(tags=["health"])`, no prefix.
Both endpoints are **exempt from auth and rate limiting** and excluded from the OpenAPI schema's auth requirement (`include_in_schema=True`, `dependencies=[]`).

### 6.1 `GET /health` — liveness

**Purpose:** "Is the process alive?" Used by Docker `HEALTHCHECK` and the container orchestrator's liveness probe.

**Touches no dependency.** No DB, no Redis, no network. This is the whole point: a liveness probe that checks Postgres will restart every API container when Postgres blips, turning a 30-second database hiccup into a full outage. Liveness answers only "is this process wedged?".

- **Params:** none.
- **200** → `HealthResponse`:

```jsonc
{ "status": "ok", "version": "1.4.2", "git_sha": "9c1f4ab", "uptime_seconds": 84213.4, "timestamp": "2026-07-17T09:41:22.481Z" }
```

- **Errors:** none. If the process is alive it returns 200. If it cannot, the probe fails by connection error, which is the correct signal.

### 6.2 `GET /health/ready` — readiness

**Purpose:** "Should this instance receive traffic?" Used by the orchestrator's readiness probe, Compose `depends_on: condition: service_healthy`, and the frontend's boot-time system banner.

**Query params:**

| Param | Type | Default | Notes |
|---|---|---|---|
| `verbose` | bool | `true` | `false` → `{status, timestamp}` only. Probes use `false`. |
| `check` | csv | all | Restrict to named checks, e.g. `?check=postgres,redis`. Unknown name → `422`. |

**Checks** (each → `ComponentHealth`):

| `name` | Probe | Timeout | Cache | Down ⇒ |
|---|---|---|---|---|
| `postgres` | `SELECT 1` + `postgis_version()` on a pool connection | 2 s | none | **`not_ready`** |
| `redis` | `PING` on broker + result backend | 1 s | none | **`not_ready`** |
| `celery` | `control.inspect(timeout=1).ping()`, count live workers | 1.5 s | 10 s | `degraded` |
| `imagery` | default provider `self_check()` — Esri: `HEAD` a fixed tile (z=1,x=0,y=0); `local_orthophoto`: dir exists + ≥1 readable GeoTIFF | 2 s | 30 s | `degraded` |
| `storage` | write+read+delete a 1-byte probe file in the upload dir | 1 s | 10 s | **`not_ready`** |
| `models` | `os.path.exists` per configured weight file | — | 60 s | **never** (informational) |

**Aggregation — opinionated and deliberate:**

- `postgres` **or** `redis` **or** `storage` down → `status: "not_ready"` → **`503`**.
- `celery` or `imagery` down/degraded → `status: "degraded"` → **`200`**.
- all up → `status: "ready"` → **`200`**.

> **Why `degraded` is 200.** If no Celery worker is running, the API can still serve every read: projects, images, annotations, past match results, past exports, downloads. Returning 503 would take the whole UI offline — including the screens that would *tell the operator the workers are down*. The same holds for imagery: with the tile proxy failing, the surveyor can still annotate, review, and export. Only the three dependencies without which *no request can be served correctly* (DB, Redis, disk) gate readiness. Meanwhile `POST /images/{id}/match` independently returns `503 WORKER_UNAVAILABLE` when there are no workers, so the failure is reported precisely at the operation that actually needs a worker, rather than by blanket-failing the instance.
>
> **Why `models` never affects readiness.** This is the environment's hard requirement expressed in the health surface: the dev machine has no deep weights and must run end-to-end. If missing weights made the app unready it would never start here. Weight presence is reported so the UI can grey out `superglue` in the matcher dropdown, and that is *all* it does.

- **200** → `ReadinessResponse`:

```jsonc
{
  "status": "degraded",
  "version": "1.4.2", "git_sha": "9c1f4ab",
  "timestamp": "2026-07-17T09:41:22.481Z",
  "checks": [
    { "name": "postgres", "status": "up", "latency_ms": 3.1,
      "detail": { "server_version": "16.2", "postgis_version": "3.4.2", "pool_in_use": 2, "pool_size": 20 } },
    { "name": "redis", "status": "up", "latency_ms": 0.8,
      "detail": { "broker": "up", "result_backend": "up" } },
    { "name": "celery", "status": "down", "latency_ms": 1500.0,
      "detail": { "workers": [], "worker_count": 0 },
      "message": "No Celery workers responded to ping. Async jobs will not start." },
    { "name": "imagery", "status": "up", "latency_ms": 142.0,
      "detail": { "default_provider": "esri_world_imagery", "keyless": true, "configured_providers": ["esri_world_imagery", "local_orthophoto"] } },
    { "name": "storage", "status": "up", "latency_ms": 2.2,
      "detail": { "upload_dir": "/data/uploads", "free_bytes": 210453069824, "free_pct": 43.1 } },
    { "name": "models", "status": "degraded", "latency_ms": 0.4,
      "detail": { "available": [], "missing": ["superpoint", "superglue", "lightglue", "loftr", "dinov2", "sam"] },
      "message": "No deep model weights present. Classical CV pipeline (SIFT/ORB + FLANN/BF + RANSAC) is fully operational." }
  ]
}
```

- **503** → same body, `status: "not_ready"`, header `Retry-After: 5`. Body is the `ReadinessResponse`, **not** an `ErrorEnvelope` — a probe wants the check detail, and this response is not an application error. This is the single, explicit exception to §4.1, called out here so it is a decision rather than an inconsistency.
- **Never 500.** Every check is individually wrapped; an exception inside a check becomes `status: "down"` + `message` for that component. A readiness endpoint that can itself throw is useless precisely when you need it.

`ComponentHealth.status` ∈ `up | degraded | down`. `ReadinessResponse.status` ∈ `ready | degraded | not_ready`.

---

## 7. Capabilities

Router: `backend/app/api/v1/capabilities.py` — `APIRouter(tags=["capabilities"])`.

### 7.1 `GET /capabilities`

**Purpose:** one call that tells the frontend what this deployment can do, so the match-configuration panel renders only choices that will actually work. Without it the client either hardcodes the enum (and offers `superglue` on a box with no weights, producing a guaranteed silent fallback the user didn't ask for) or makes three calls and joins them.

- **Params:** none. **Cache:** `Cache-Control: public, max-age=60`; ETag over the payload.
- **200** → `CapabilitiesResponse`:

```jsonc
{
  "version": "1.4.2",
  "extractors": [
    { "name": "sift",       "available": true,  "kind": "classical", "requires_weights": false, "reason": null },
    { "name": "orb",        "available": true,  "kind": "classical", "requires_weights": false, "reason": null },
    { "name": "akaze",      "available": true,  "kind": "classical", "requires_weights": false, "reason": null },
    { "name": "superpoint", "available": false, "kind": "deep", "requires_weights": true,
      "reason": "Weights not found at /models/superpoint_v1.pth", "fallback": "sift" },
    { "name": "disk",       "available": false, "kind": "deep", "requires_weights": true, "reason": "…", "fallback": "sift" },
    { "name": "loftr_dense","available": false, "kind": "deep", "requires_weights": true, "reason": "…", "fallback": "sift" }
  ],
  "matchers": [
    { "name": "bf",        "available": true,  "kind": "classical", "requires_weights": false, "reason": null },
    { "name": "flann",     "available": true,  "kind": "classical", "requires_weights": false, "reason": null },
    { "name": "superglue", "available": false, "kind": "deep", "requires_weights": true, "reason": "…", "fallback": "flann" },
    { "name": "lightglue", "available": false, "kind": "deep", "requires_weights": true, "reason": "…", "fallback": "flann" },
    { "name": "loftr",     "available": false, "kind": "deep", "requires_weights": true, "reason": "…", "fallback": "flann" }
  ],
  "estimators": [
    { "name": "ransac", "available": true }, { "name": "usac_magsac", "available": true },
    { "name": "lmeds", "available": true },  { "name": "prosac", "available": true }
  ],
  "segmentation_backends": [
    { "name": "sam",       "available": false, "kind": "deep", "reason": "…", "fallback": "classical_contour" },
    { "name": "classical_contour", "available": true, "kind": "classical", "reason": null }
  ],
  "providers": [ /* ProviderInfo[] — same objects as GET /imagery/providers */ ],
  "export_formats": [
    { "format": "csv",       "available": true,  "reason": null },
    { "format": "geojson",   "available": true,  "reason": null },
    { "format": "kml",       "available": true,  "reason": null },
    { "format": "kmz",       "available": true,  "reason": null },
    { "format": "shapefile", "available": true,  "reason": null },
    { "format": "gpkg",      "available": true,  "reason": null },
    { "format": "dxf",       "available": true,  "reason": null },
    { "format": "pdf",       "available": true,  "reason": null }
  ],
  "compute": { "torch_available": true, "cuda_available": true, "device": "cuda:0",
               "gpu_name": "NVIDIA RTX 4090", "torch_version": "2.11.0+cu130" },
  "limits": { "max_upload_bytes": 524288000, "max_batch_files": 100, "max_image_pixels": 400000000,
              "max_annotations_per_image": 2000, "max_static_pixels": 67108864, "max_tiles_per_job": 256 },
  "defaults": { "provider": "esri_world_imagery", "extractor": "sift", "matcher": "flann",
                "estimator": "usac_magsac", "search_radius_m": 1000.0, "search_zoom": 18 }
}
```

Each entry carries `available` + `reason` + `fallback`. `available: false` never means "you may not request it" — the API accepts `matcher: "superglue"` on a weightless box and returns a job that warns and falls back (§4.5). It means "if you pick this, you will get `fallback` instead". The frontend renders such options disabled with the `reason` as tooltip.

Schemas: `CapabilitiesResponse`, `CapabilityItem`, `ExportCapability`, `ComputeInfo`, `LimitsInfo`, `DefaultsInfo` in `backend/app/schemas/capabilities.py`.

---

## 8. Projects

Router: `backend/app/api/v1/projects.py` — `APIRouter(prefix="/projects", tags=["projects"])`.
Table: `projects`.

A project is the ownership and configuration root: it holds the AOI that seeds match search when an image has no EXIF GPS, the default pipeline config that `POST /match` inherits, and the revision counter (`current_revision_seq`) that the annotation history hangs off.

### 8.1 `POST /projects`

**Purpose:** create a project.

- **Body:** `ProjectCreate` (`backend/app/schemas/project.py`)

| Field | Type | Req | Rules |
|---|---|---|---|
| `name` | `str` | yes | 1–200 chars, stripped, non-blank after strip |
| `description` | `str \| null` | no | ≤ 4000 |
| `aoi` | `GeoJsonPolygon \| null` | no | RFC 7946 Polygon, EPSG:4326, `[lon,lat]`, ≤ 1000 vertices, must be `ST_IsValid`, area ≤ 10 000 km² |
| `default_provider` | `ProviderName` | no | default `esri_world_imagery` |
| `default_extractor` | `ExtractorName` | no | default `sift` |
| `default_matcher` | `MatcherName` | no | default `flann` |
| `default_estimator` | `EstimatorName` | no | default `usac_magsac` |
| `default_search_radius_m` | `float` | no | default `1000`, `10..50000` |
| `default_search_zoom` | `int` | no | default `18`, `10..21` |
| `tags` | `list[str]` | no | ≤ 20, each ≤ 50 chars |
| `metadata` | `dict[str, Any]` | no | free-form, ≤ 16 KB serialized |

- **201** → `ProjectRead`. Header `Location: /api/v1/projects/{id}`.
- **422** `VALIDATION_ERROR` — blank name, invalid/self-intersecting AOI, unknown enum value.
- **409** `PROJECT_NAME_CONFLICT` — only if `UNIQUE(name)` is enabled by config (`PROJECT_NAMES_UNIQUE=true`, default `false`).

**`ProjectRead`:**

```jsonc
{
  "id": "1b2c…", "name": "North Parcel Survey 2026",
  "description": "Spring re-survey of block 4",
  "aoi": { "type": "Polygon", "coordinates": [[[12.41,41.87],[12.44,41.87],[12.44,41.90],[12.41,41.90],[12.41,41.87]]] },
  "aoi_area_km2": 8.94,
  "default_provider": "esri_world_imagery", "default_extractor": "sift",
  "default_matcher": "flann", "default_estimator": "usac_magsac",
  "default_search_radius_m": 1000.0, "default_search_zoom": 18,
  "tags": ["2026", "spring"], "metadata": {},
  "current_revision_seq": 47,
  "counts": { "images": 12, "annotations": 218, "gcps": 96, "match_jobs": 14, "exports": 3 },
  "created_at": "…", "updated_at": "…", "deleted_at": null
}
```

`counts` is a rollup. It is computed on `GET /projects/{id}` with a single lateral-join query, and is **omitted (null) in list responses** — see §8.2.

### 8.2 `GET /projects`

**Purpose:** list projects.

- **Query:** `ProjectListParams` — `limit`, `offset`, `sort`, `q`, `tag`, `bbox`, `include_deleted`, `created_at__gte`, `created_at__lte`.
  - `q` → case-insensitive substring over `name` and `description` (`ILIKE %q%`; trigram index per `10-database.md`).
  - `tag` → repeatable; multiple tags AND.
  - `bbox` → projects whose `aoi` intersects (`ST_Intersects`). Projects with `aoi = null` are excluded when `bbox` is given.
- **Sort whitelist:** `created_at`, `updated_at`, `name`. **Default:** `-created_at`.
- **200** → `Page[ProjectSummary]`.

`ProjectSummary` = `id, name, description, tags, aoi_area_km2, image_count, created_at, updated_at`. It deliberately **omits `aoi` and `counts`**: a 1000-vertex AOI polygon × 50 rows is a ~2 MB list response for a screen that renders names, and the full `counts` rollup costs 5 aggregate subqueries per row. `image_count` alone is kept (one cheap correlated count, indexed) because the list UI shows it. Clients needing geometry fetch the detail.

- **422** `INVALID_SORT_FIELD`, `INVALID_BBOX`, `UNKNOWN_QUERY_PARAM`.

### 8.3 `GET /projects/{project_id}`

- **Path:** `project_id: UUID`.
- **Query:** `include_deleted: bool = false`.
- **200** → `ProjectRead` (with `counts`). `ETag` = weak hash of `(updated_at, current_revision_seq)`.
- **304** if `If-None-Match` matches.
- **404** `PROJECT_NOT_FOUND` — unknown id, or soft-deleted and `include_deleted=false`.

### 8.4 `PATCH /projects/{project_id}`

**Purpose:** partial update. PATCH, not PUT: a PUT would force the client to round-trip the entire AOI to rename a project, and any field it failed to echo back would be silently nulled.

- **Body:** `ProjectUpdate` — every field of `ProjectCreate`, all `Optional`, `extra="forbid"`.
  - **Explicit-null semantics:** `ProjectUpdate` distinguishes "field absent" from `"field": null` via a sentinel (`Field(default=UNSET)` with a custom `Unset` type), so `{"aoi": null}` **clears** the AOI while `{}` leaves it untouched. Without this, nullable fields are un-clearable through PATCH — a real, common bug.
  - Empty body `{}` → **`400 EMPTY_PATCH`**. Almost certainly a client bug.
- **Headers:** `If-Match: <etag>` optional; when supplied and stale → **`412 STALE_PROJECT_VERSION`**.
- **200** → `ProjectRead`.
- **404** `PROJECT_NOT_FOUND`. **422** `VALIDATION_ERROR`. **409** `PROJECT_NAME_CONFLICT`.

Changing `default_*` fields affects **future** jobs only. Existing `match_jobs` rows carry their own denormalized config (the reproducibility record) and are never rewritten. Stated explicitly because "I changed the default and my old result changed" would be a data-integrity failure in a survey product.

### 8.5 `DELETE /projects/{project_id}`

**Purpose:** delete a project.

- **Query:** `hard: bool = false`.
- **Soft (default):** sets `deleted_at = now()`. Images/annotations/GCPs cascade-hide via the `deleted_at` filter. Recoverable by `PATCH {"deleted_at": null}` (admin-only field). → **`204`**.
- **Hard (`?hard=true`):** `DELETE FROM projects` — cascades per DDL: images, annotations, revisions, match_jobs, gcps, exports all removed; artifact files enqueued for GC.
  - Requires `X-Confirm-Delete: {project_id}` header → else **`428 CONFIRMATION_REQUIRED`**. A destructive irreversible cascade behind a single `?hard=true` typo is unacceptable in a product whose output is legal survey data.
  - Blocked if any job is non-terminal → **`409 PROJECT_HAS_ACTIVE_JOBS`** (`details` lists job ids). Hard-deleting under a running worker is how you get an FK violation in a Celery task at 3 a.m.
  - → **`204`**.
- **404** `PROJECT_NOT_FOUND` (idempotent: deleting an already-soft-deleted project → `204`).

---

## 9. Images

Router: `backend/app/api/v1/images.py` — `APIRouter(prefix="/images", tags=["images"])`.
Table: `images`.

### 9.1 Upload constraints

| Constraint | Value | Setting | Violation |
|---|---|---|---|
| Max body size | **500 MB** | `MAX_UPLOAD_BYTES=524288000` | `413 UPLOAD_TOO_LARGE` |
| Max decoded pixels | **400 MP** (`width*height`) | `MAX_IMAGE_PIXELS=400_000_000` | `422 IMAGE_TOO_LARGE` |
| Max dimension | 65535 px per side | `MAX_IMAGE_DIM=65535` | `422 IMAGE_TOO_LARGE` |
| Allowed MIME | `image/jpeg`, `image/png`, `image/tiff`, `image/webp` | `ALLOWED_IMAGE_MIME` | `415 UNSUPPORTED_IMAGE_FORMAT` |
| Allowed extensions | `.jpg .jpeg .png .tif .tiff .webp` | — | advisory only |
| Files per batch | 100 | `MAX_BATCH_FILES=100` | `413 BATCH_TOO_LARGE` |

**MIME is determined by magic bytes, never by the client.** The `Content-Type` part header and the filename extension are both untrusted and are recorded only as advisory metadata. The server sniffs the first 32 bytes (`FF D8 FF` → JPEG; `89 50 4E 47 0D 0A 1A 0A` → PNG; `49 49 2A 00`/`4D 4D 00 2A` → TIFF little/big-endian; `49 49 2B 00`/`4D 4D 00 2B` → BigTIFF; `RIFF....WEBP` → WebP) and then confirms by opening with GDAL. A client that posts `evil.php` with `Content-Type: image/jpeg` gets `415`. `application/octet-stream` is accepted at the header level and resolved by sniffing — browsers and `curl` both send it for `.tif`.

**GeoTIFF has no distinct MIME.** `image/tiff` covers both. GeoTIFF-ness is a *property discovered at ingest*, never a declared type. Concretely: the file is `image/tiff`; `is_geotiff` is `true` iff GDAL reports a non-null projection **and** a geotransform that is not the default identity `(0,1,0,0,0,1)`. That second condition matters — GDAL hands back the identity transform for plain TIFFs, and a naive `if gt:` check marks every scanned TIFF as georeferenced at the equator.

**Streaming, not buffering.** The body is streamed to a temp file in 1 MB chunks with a running SHA-256 and a running byte count; the count is checked against `MAX_UPLOAD_BYTES` **during** the stream and aborts at the first chunk that exceeds it. `await file.read()` into memory would let 8 concurrent 500 MB uploads OOM the container. `Content-Length`, when present, is checked first as a cheap early reject, but is never trusted as the sole guard (it is client-supplied and chunked encoding omits it).

**Ingest is synchronous but bounded.** The upload request itself does: stream to disk → sniff → GDAL open → read dimensions/bands/CRS/geotransform → parse EXIF → normalize orientation → write thumbnail → INSERT. Target p95 < 800 ms for a 24 MP JPEG. Nothing here is CV work; it is header parsing plus one downsample. For **files > `ASYNC_INGEST_THRESHOLD_BYTES` (50 MB)** — i.e. essentially all GeoTIFFs — the row is inserted with `status='processing'`, a `thumbnail` job is enqueued, and the response is `202` with the image record plus a job handle. This keeps a 400 MB orthophoto from holding a worker thread for 20 seconds building overviews.

**EXIF orientation is normalized at ingest**, and `width`/`height` are stored **post-rotation**. The stored file is rewritten upright (JPEG: lossless `jpegtran`-equivalent rotation where possible, else re-encode at q=95) and the orientation tag reset to 1. If it were not, every downstream consumer — Konva canvas, OpenCV `imread`, GDAL, the PDF exporter — would each have to independently re-apply the tag, and they do not agree with each other. Annotation pixel coordinates would then mean different things in different components, which corrupts GCP output. The original EXIF block is preserved verbatim in `images.exif` (including the original `Orientation`), so nothing is lost.

### 9.2 `POST /images`

**Purpose:** upload a ground-level photograph (or an orthophoto), extract metadata, create the record.

- **Content-Type:** `multipart/form-data`.
- **Headers:** `Idempotency-Key` (recommended — see §5.2; the dedup hash is `sha256(file) + project_id`, so a retried upload of the same bytes returns the original record instead of a duplicate).
- **Form fields** (`ImageUploadForm`, `backend/app/schemas/image.py`):

| Field | Type | Req | Notes |
|---|---|---|---|
| `file` | binary | **yes** | the image |
| `project_id` | UUID | **yes** | must exist and not be soft-deleted |
| `filename` | str | no | overrides the part's filename; sanitized (basename only, path separators and control chars stripped) |
| `captured_at` | datetime | no | overrides EXIF `DateTimeOriginal` |
| `notes` | str | no | ≤ 4000 |
| `lat` / `lon` | float | no | manual GPS override when EXIF has none; **both or neither** → else `422 PARAM_CONFLICT` |
| `metadata` | str (JSON) | no | free-form; ≤ 16 KB |

- **201** → `ImageRead` (ingest completed inline). `Location: /api/v1/images/{id}`.
- **202** → `ImageUploadAccepted` = `{ "image": ImageRead, "job": JobRead }` — large-file path; `image.status = "processing"`, thumbnail pending.
- **413** `UPLOAD_TOO_LARGE` — body exceeded the cap. Emitted mid-stream; the connection is drained then closed.
- **415** `UNSUPPORTED_IMAGE_FORMAT` — magic bytes unrecognized, or GDAL cannot open. `details` carries the sniffed signature.
- **422** `VALIDATION_ERROR` — missing `file`/`project_id`, `lat` without `lon`, bad `metadata` JSON, image exceeds `MAX_IMAGE_PIXELS`.
- **404** `PROJECT_NOT_FOUND`.
- **409** `IDEMPOTENCY_KEY_REUSED` / `IDEMPOTENCY_IN_PROGRESS`.
- **507** `INSUFFICIENT_STORAGE` — upload dir below the reserve watermark (`STORAGE_MIN_FREE_BYTES`, default 2 GB). Checked *before* streaming. Filling the disk mid-write corrupts the current upload and every concurrent one.

**`ImageRead`:**

```jsonc
{
  "id": "7f3a…", "project_id": "1b2c…",
  "filename": "IMG_4471.JPG",
  "mime_type": "image/jpeg", "size_bytes": 8451233, "checksum_sha256": "a3f1…",
  "width": 6000, "height": 4000, "band_count": 3,
  "status": "ready",                       // uploaded | processing | ready | failed
  "is_geotiff": false,
  "gps": { "lat": 41.8902, "lon": 12.4231, "altitude_m": 87.4,
           "direction_deg": 143.2, "hpe_m": 4.8, "source": "exif" },   // null when no GPS at all
  "camera": { "make": "DJI", "model": "FC7303", "lens_model": null,
              "focal_length_mm": 4.49, "focal_length_35mm": 24.0,
              "sensor_width_mm": 6.17, "f_number": 2.8 },
  "captured_at": "2026-04-11T08:14:52Z",
  "notes": null, "metadata": {},
  "urls": { "file": "/api/v1/images/7f3a…/file",
            "thumbnail": "/api/v1/images/7f3a…/thumbnail",
            "metadata": "/api/v1/images/7f3a…/metadata" },
  "counts": { "annotations": 14, "gcps": 12, "match_results": 3, "semantic_features": 0 },
  "latest_match": { "match_result_id": "cc11…", "confidence": 87.3, "created_at": "…" },  // nullable
  "warnings": [],
  "uploaded_at": "…", "created_at": "…", "updated_at": "…", "deleted_at": null
}
```

Notes on shape:
- `gps.source` ∈ `exif | manual | none`. A manual `lat`/`lon` at upload sets `manual` and is stored in `exif_gps` all the same — the search pipeline does not care where the prior came from, but the surveyor does.
- `storage_path` is **never** serialized. It is a server-controlled filesystem/S3 path; exposing it invites path-traversal probing and leaks the storage layout. Clients get `urls.file`.
- `exif` (the verbatim blob) is **not** in `ImageRead` — it can be hundreds of tags including embedded thumbnails. It lives at `/metadata`.
- `is_geotiff` is surfaced here because the frontend branches on it (a GeoTIFF gets a "use own georeference" affordance).

### 9.3 `GET /images`

- **Query:** `ImageListParams` — `limit`, `offset`, `sort`, `project_id`, `q`, `status`, `is_geotiff`, `has_gps`, `has_match`, `bbox`, `captured_at__gte`, `captured_at__lte`, `created_at__gte`, `created_at__lte`, `include_deleted`.
  - `bbox` filters on `exif_gps` (point-in-bbox) for photos; for GeoTIFFs it tests `bounds` intersection. Rows with neither are excluded when `bbox` is set.
  - `has_gps` / `has_match` → bool.
  - `q` → substring over `filename` and `notes`.
- **Sort whitelist:** `created_at`, `uploaded_at`, `captured_at`, `filename`, `size_bytes`. **Default:** `-uploaded_at`.
- **200** → `Page[ImageSummary]`.

`ImageSummary` = `id, project_id, filename, mime_type, width, height, size_bytes, status, is_geotiff, has_gps, captured_at, uploaded_at, thumbnail_url, annotation_count, gcp_count, best_confidence`. Omits `exif`, `camera`, full `gps`, `counts` — the gallery grid needs a thumbnail and two badges.

- **422** `INVALID_SORT_FIELD`, `INVALID_BBOX`, `UNKNOWN_QUERY_PARAM`. **404** `PROJECT_NOT_FOUND` if `project_id` given and unknown.

### 9.4 `GET /images/{image_id}`

- **200** → `ImageRead`. `ETag` from `updated_at`.
- **304** on `If-None-Match`. **404** `IMAGE_NOT_FOUND`.

### 9.5 `GET /images/{image_id}/file`

**Purpose:** stream the original bytes — the Konva canvas backdrop, and the OpenCV/QGIS download path.

- **Query:** `download: bool = false` → `Content-Disposition: attachment` vs `inline`.
- **200** → binary.
  - `Content-Type` = stored `mime_type`.
  - `Content-Length`, `ETag: "<checksum_sha256>"` (**strong** — the SHA-256 *is* the content hash, so it is exactly the strong validator HTTP wants), `Last-Modified`, `Accept-Ranges: bytes`.
  - `Cache-Control: private, max-age=31536000, immutable` — image bytes never change; a new upload is a new id. This makes the annotation canvas reload instantly.
  - `Content-Disposition` filename is RFC 5987 encoded (`filename*=UTF-8''…`) — surveyors use non-ASCII filenames.
- **206 Partial Content** — `Range` honored. Required for a 400 MB GeoTIFF: it lets the browser/GDAL `/vsicurl/` fetch headers and overviews without pulling the whole file.
- **304** on `If-None-Match`/`If-Modified-Since`.
- **416** `RANGE_NOT_SATISFIABLE`.
- **404** `IMAGE_NOT_FOUND`. **410** `IMAGE_PURGED` — row exists, bytes gone.
- **409** `IMAGE_STILL_PROCESSING` — `status='uploaded'`, bytes not yet durable.

Served via `FileResponse`/`StreamingResponse`. In production `X-Accel-Redirect` (nginx) or `X-Sendfile` hands the descriptor to the front proxy so a 400 MB download does not occupy a Python worker for its duration; the app still performs authorization first. This is toggled by `USE_SENDFILE=true` and is transparent to the client.

### 9.6 `GET /images/{image_id}/thumbnail`

- **Query:**

| Param | Type | Default | Rules |
|---|---|---|---|
| `size` | enum | `md` | `sm`(128) \| `md`(512) \| `lg`(1024) \| `xl`(2048), longest edge |
| `format` | enum | `webp` | `webp` \| `jpeg` \| `png` |
| `fit` | enum | `contain` | `contain` (preserve aspect) \| `cover` (center-crop square) |

Only this **fixed enum** of sizes is accepted — not arbitrary `w`/`h` integers. Free-form dimensions turn the endpoint into an unbounded resize farm: any client can request 10 000 distinct sizes and blow out both CPU and the cache. Four sizes cover the gallery, the canvas preview, and the PDF export.

- **200** → binary. `Cache-Control: public, max-age=604800, immutable`; `ETag: "<checksum>-<size>-<fit>-<format>"`; `Vary: Accept`.
- Generated on first request, then cached at `thumbnail_path` (+ variant suffix). Generation is bounded: for TIFF/GeoTIFF the **existing GDAL overview pyramid** is used (`gdal.Open(...).GetRasterBand(1).GetOverview(n)`) rather than decoding the full raster — decoding a 400 MP orthophoto to make a 128 px thumbnail takes ~30 s and 4 GB of RAM; reading the right overview level takes ~20 ms.
- **202** `Retry-After: 2` + `JobRead` — thumbnail still generating (large-file async path). Not an error; the UI shows a spinner.
- **404** `IMAGE_NOT_FOUND`. **410** `IMAGE_PURGED`. **422** bad enum.

**Multi-band and non-8-bit rasters** (a 5-band 16-bit multispectral GeoTIFF) are rendered for display: bands are picked by GDAL color interpretation, else `[1,2,3]`, else band 1 as greyscale; 16/32-bit is stretched to 8-bit by 2–98 percentile. This is display-only and never touches the data used for matching.

### 9.7 `GET /images/{image_id}/metadata`

**Purpose:** the metadata inspector panel, and the reproducibility record. Separate from `ImageRead` because the payload is large, rarely needed, and shaped for display rather than logic.

- **Query:** `include_raw_exif: bool = true`.
- **200** → `ImageMetadataRead`:

```jsonc
{
  "image_id": "7f3a…",
  "file": { "filename": "IMG_4471.JPG", "mime_type": "image/jpeg", "size_bytes": 8451233,
            "checksum_sha256": "a3f1…", "uploaded_at": "…" },
  "raster": { "width": 6000, "height": 4000, "band_count": 3,
              "data_type": "Byte", "color_interpretation": ["Red","Green","Blue"],
              "resolution_dpi": 72.0, "gsd_m": null, "nodata_value": null,
              "has_overviews": false, "overview_levels": [],
              "orientation_normalized": true, "original_orientation": 6 },
  "gps": { "lat": 41.8902, "lon": 12.4231, "altitude_m": 87.4, "altitude_ref": "above_sea_level",
           "direction_deg": 143.2, "direction_ref": "true_north",
           "hpe_m": 4.8, "dop": 1.4, "satellites": 12, "timestamp_utc": "2026-04-11T08:14:52Z",
           "source": "exif", "datum": "WGS-84" },
  "camera": { "make": "DJI", "model": "FC7303", "lens_model": null,
              "focal_length_mm": 4.49, "focal_length_35mm": 24.0,
              "sensor_width_mm": 6.17, "sensor_width_source": "camera_db",
              "f_number": 2.8, "exposure_time": "1/500", "iso": 100 },
  "geotiff": null,
  "capture": { "captured_at": "2026-04-11T08:14:52Z", "captured_at_source": "exif_with_gps_tz",
               "timezone": "Europe/Rome" },
  "derived": { "estimated_intrinsics": { "fx": 5833.3, "fy": 5833.3, "cx": 3000.0, "cy": 2000.0,
                                         "source": "exif_focal_and_sensor_width", "confidence": "medium" } },
  "exif": { /* verbatim tag→value, IFD-grouped; null when include_raw_exif=false */ },
  "exif_parse_warnings": ["MakerNote: unparsed proprietary block (3812 bytes), preserved as base64"]
}
```

For a **GeoTIFF**, `geotiff` is populated and `gps` is typically `null`:

```jsonc
"geotiff": {
  "crs_epsg": 32633, "crs_wkt": "PROJCRS[\"WGS 84 / UTM zone 33N\"…]",
  "crs_name": "WGS 84 / UTM zone 33N", "crs_units": "metre", "is_projected": true,
  "geotransform": [499980.0, 0.5, 0.0, 4600020.0, 0.0, -0.5],
  "gsd_m": 0.5,
  "bounds_native": { "minx": 499980.0, "miny": 4590000.0, "maxx": 510000.0, "maxy": 4600020.0 },
  "bounds_wgs84": { "type": "Polygon", "coordinates": [[[12.41,41.47],[12.53,41.47],[12.53,41.56],[12.41,41.56],[12.41,41.47]]] },
  "center_wgs84": { "lat": 41.5153, "lon": 12.4712 },
  "area_km2": 100.4,
  "pixel_is_area": true,
  "compression": "DEFLATE", "tiled": true, "block_size": [512, 512],
  "is_cog": true,
  "overview_levels": [2, 4, 8, 16],
  "nodata_value": 0.0,
  "reprojection_note": "bounds_wgs84 computed at ingest via ST_Transform from EPSG:32633 (R5)."
}
```

- **404** `IMAGE_NOT_FOUND`. **409** `IMAGE_STILL_PROCESSING`.

**How TIFF/GeoTIFF differ in handling — the complete list:**

| Aspect | JPEG / PNG / WebP | TIFF (plain) | **GeoTIFF** |
|---|---|---|---|
| Reader | PIL + `piexif` | GDAL | GDAL |
| EXIF | full, typical | rare/partial | usually none |
| `is_geotiff` | `false` | `false` | **`true`** |
| Georeference | EXIF GPS point, or none | none | **CRS + geotransform + footprint** |
| `bounds` | null | null | Polygon, **reprojected to 4326 at ingest** |
| `gsd_m` | null | null | from geotransform |
| Orientation | normalized, rewritten upright | tag rare; honored if present | **never rotated** — rotating would invalidate the geotransform |
| Thumbnail | full decode + Lanczos | overviews if present, else windowed read | **overview pyramid** |
| Ingest mode | sync (< 50 MB) | sync/async by size | almost always **async** |
| Multi-band / >8-bit | n/a | percentile-stretched for display | percentile-stretched for display |
| BigTIFF | n/a | supported | supported |
| Match role | **query image** (the photo) | query image | **query image _or_ imagery source** |
| Search hint | seeded from EXIF GPS | none → needs `center` or AOI | **seeded from its own `bounds` centroid**, `radius_m` defaults to its diagonal |

The last row is the interesting one. A GeoTIFF *already knows where it is*. `POST /images/{id}/match` therefore never needs a `center` for a GeoTIFF: `search_hint.use_image_gps=true` resolves to the footprint centroid, and the match becomes a *verification/refinement* against the provider rather than a blind search. Its own georeference is also the natural ground truth for validating the pipeline — a GeoTIFF whose match disagrees with its own geotransform by > `GEOTIFF_DISAGREEMENT_M` (default 50 m) yields `WarningItem{code: "GEOTIFF_GEOREFERENCE_DISAGREEMENT"}` on the match result. That is a free, always-available regression test on the matcher, and it needs no weights and no network (with `local_orthophoto`).

A GeoTIFF uploaded as *imagery* rather than as a *query* belongs in the `local_orthophoto` provider directory (see `40-imagery.md`), not in `POST /images`. `POST /images` is for things you want coordinates *for*.

### 9.8 `DELETE /images/{image_id}`

- **Query:** `hard: bool = false`.
- **Soft (default):** `deleted_at = now()`. Annotations/GCPs/results retained and hidden. → **`204`**.
- **Hard:** row deleted (cascades per DDL), file + thumbnails + cached mosaics enqueued for GC.
  - Requires `X-Confirm-Delete: {image_id}` → else **`428 CONFIRMATION_REQUIRED`**.
  - **`409 IMAGE_HAS_ACTIVE_JOBS`** if any non-terminal job references it.
  - Note the DDL's `fk_gcps_match_result_id … ON DELETE RESTRICT`: GCPs are purged before their match results within the same transaction, in dependency order. A naive `DELETE FROM images` would raise a 23503.
  - → **`204`**.
- **404** `IMAGE_NOT_FOUND` (idempotent for already-soft-deleted).

---

## 10. Annotations (landmarks)

Routers, both in `backend/app/api/v1/annotations.py`:
- `router_nested = APIRouter(prefix="/images/{image_id}/annotations", tags=["annotations"])`
- `router_flat   = APIRouter(prefix="/annotations", tags=["annotations"])`

Table: `annotations`.

> **Naming.** The product calls them "landmarks"; the schema calls them `annotations`. The API follows the **schema**, because an annotation is the general thing (a point, polyline, or polygon the surveyor drew) and a landmark is the *role* a point plays when it becomes a GCP candidate. `gcps.landmark_id → annotations.id` is exactly this relationship. The word "landmark" survives in the API only where it names that role: `POST /images/{id}/suggest-landmarks`, `gcps.landmark_id`. One concept, one name, at each layer.

### 10.1 The annotation object

**`AnnotationRead`** (`backend/app/schemas/annotation.py`):

```jsonc
{
  "id": "9d4e…", "image_id": "7f3a…",
  "kind": "field_corner",              // annotation_kind enum, 16 values
  "geom_type": "point",                // point | polyline | polygon
  "pixel_x": 2431.5, "pixel_y": 1102.0,   // representative point; == the point itself for geom_type=point
  "geometry": { "type": "Point", "coordinates": [2431.5, 1102.0] },   // GeoJSON-shaped, IMAGE PIXEL space, SRID 0
  "label": "NE fence corner",
  "description": null,
  "confidence": 0.9,                   // 0-1, the SURVEYOR's certainty (see §1.3)
  "ordering": 3,
  "style": { "color": "#ff5722", "radius": 6 },
  "attributes": {},
  "version_no": 4,                     // optimistic-lock counter
  "revision_seq": 47,
  "is_gcp_candidate": true,            // derived: kind ∈ {field_corner, road_intersection, building_corner} && geom_type == point
  "gcp_id": "aa22…",                   // nullable; set once a match derives a GCP from this annotation
  "created_by": "alice", "updated_by": "alice",
  "created_at": "…", "updated_at": "…"
}
```

**Geometry is GeoJSON-*shaped* but is not geographic.** `geometry.coordinates` are **image pixels**, `[x, y]`, y-down, SRID 0 — not `[lon, lat]`. This is deliberate: the shape is already understood by every client library (and by Konva's serializer), while the CRS is unambiguously declared by `geom_type` living on an image-scoped resource. To make the trap impossible to fall into, the API **rejects** any `crs` member on input (`422 ANNOTATION_GEOMETRY_INVALID`) and never emits one. A reader must not feed this into Leaflet expecting degrees.

Validation on every write (mirrors the DDL CHECKs, so a violation is a clean 422 rather than a 23514):

| Rule | Error |
|---|---|
| `geom_type` matches `geometry.type` (`point`↔`Point`, `polyline`↔`LineString`, `polygon`↔`Polygon`) | `ANNOTATION_GEOMETRY_INVALID` |
| polyline ≥ 2 points; polygon exterior ring ≥ 4 points and closed | `ANNOTATION_GEOMETRY_INVALID` |
| `ST_IsValid` — no self-intersection | `ANNOTATION_GEOMETRY_INVALID` |
| 2D only (no z/m) | `ANNOTATION_GEOMETRY_INVALID` |
| all coords within `[0, width] × [0, height]` of the image | `ANNOTATION_OUT_OF_BOUNDS` |
| `confidence` ∈ [0, 1] | `VALIDATION_ERROR` |
| ≤ `MAX_ANNOTATIONS_PER_IMAGE` (2000) | `422 TOO_MANY_ANNOTATIONS` |
| ≤ 10 000 vertices per geometry | `422 GEOMETRY_TOO_COMPLEX` |

Bounds are checked against the **post-orientation-normalization** `width`/`height` (§9.1) — the only dimensions that exist as far as the API is concerned.

### 10.2 `GET /images/{image_id}/annotations`

- **Query:** `AnnotationListParams` — `limit` (default **200** here, max 2000 — the canvas loads them all), `offset`, `sort`, `kind` (csv), `geom_type` (csv), `q` (over `label`/`description`), `confidence__gte`, `is_gcp_candidate`, `include_deleted`, `revision_seq` (**time travel**: state as of that revision).
- **Sort whitelist:** `ordering`, `created_at`, `updated_at`, `confidence`, `kind`. **Default:** `ordering,created_at` — matches `ix_annotations_image_order`, so the canvas's load is an index-only scan.
- **200** → `Page[AnnotationRead]`. `ETag` = hash of `(max(updated_at), count)`; the canvas polls it cheaply.
- **404** `IMAGE_NOT_FOUND`. **422** bad params.

`?revision_seq=` reconstructs historical state by replaying `annotation_versions` from the nearest preceding checkpoint (`ix_project_revisions_checkpoints` makes finding it one backward index scan). This is what powers the "ghost preview" of a past revision on the canvas without mutating anything.

### 10.3 `POST /images/{image_id}/annotations`

**Purpose:** create one annotation — a single click in the tool.

- **Body:** `AnnotationCreate`

| Field | Type | Req | Default |
|---|---|---|---|
| `kind` | `AnnotationKind` | no | `generic` |
| `geom_type` | `AnnotationGeomType` | **yes** | |
| `geometry` | `GeoJsonGeometry` | **yes** | pixel space |
| `label` | `str \| null` | no | `null` |
| `description` | `str \| null` | no | `null` |
| `confidence` | `float` | no | `1.0` |
| `ordering` | `int \| null` | no | `null` → server assigns `max(ordering)+1` |
| `style` | `dict` | no | `{}` |
| `attributes` | `dict` | no | `{}` |
| `client_op_id` | `str \| null` | no | idempotency key for this gesture (§10.7) |

- **201** → `AnnotationRead`. `Location`, `ETag: "<version_no>"`.
- **404** `IMAGE_NOT_FOUND`. **409** `IMAGE_STILL_PROCESSING` (bounds unknown until ingest completes). **422** per §10.1.

`pixel_x`/`pixel_y` are **derived server-side**, never accepted from the client: point → itself; polyline → midpoint by arc length; polygon → `ST_PointOnSurface`. Accepting them would let the denormalized column drift from `pixel_geom`, and that column is what the label renderer and the GCP deriver read.

### 10.4 `PUT /images/{image_id}/annotations` — bulk upsert

**Purpose:** the annotation tool's save. The surveyor drags six points, deletes one, adds two, hits Save; this is one call, one transaction, **one revision**.

`PUT` on the **collection** is correct here: the request declares the desired state of the image's annotation set. It is idempotent — replaying it converges. Six separate PATCHes would produce six revisions (making undo useless), six round trips, and a partially-saved canvas if the fourth fails.

- **Body:** `AnnotationBulkUpsertRequest`

```jsonc
{
  "mode": "merge",                 // merge (default) | replace
  "base_revision_seq": 47,         // optional optimistic lock for the whole set
  "revision_label": "adjusted north fence",
  "client_op_id": "5f2c…",
  "items": [
    { "id": null,     "op": "create", "kind": "field_corner", "geom_type": "point",
      "geometry": {"type":"Point","coordinates":[2431.5,1102.0]}, "label": "NE corner",
      "confidence": 0.9, "ordering": 3, "client_ref": "tmp-17" },
    { "id": "9d4e…", "op": "update", "version_no": 4,
      "geometry": {"type":"Point","coordinates":[2440.0,1110.0]} },
    { "id": "3c8b…", "op": "delete", "version_no": 2 },
    { "id": "7a1f…", "op": "restore", "version_no": 5 }
  ]
}
```

| Field | Rules |
|---|---|
| `mode` | `merge`: apply `items` only. `replace`: apply `items`, **and soft-delete every live annotation not named in `items`**. |
| `base_revision_seq` | If given and ≠ `projects.current_revision_seq` → **`409 REVISION_CONFLICT`**, nothing applied. |
| `items` | 1–2000. Empty → `422`. |
| `items[].op` | `create` \| `update` \| `delete` \| `restore` — mirrors `annotation_op`. |
| `items[].id` | required for `update`/`delete`/`restore`; **must be null** for `create` → else `422`. |
| `items[].version_no` | required for `update`/`delete`/`restore`; stale → `412`. |
| `items[].client_ref` | client-side temp id, echoed back in the response so the Zustand store can swap `tmp-17` → the real UUID. |

**Atomicity: all-or-nothing.** One transaction, `SERIALIZABLE`-equivalent via `SELECT … FOR UPDATE` on the project row (which also serializes `current_revision_seq` allocation). Any item failing validation or the version check aborts everything. A partial save on a survey annotation set is worse than no save: the surveyor believes the canvas matches the database when it does not.

- **200** → `AnnotationBulkUpsertResponse`:

```jsonc
{
  "revision": { "id": "e1f2…", "seq": 48, "label": "adjusted north fence", "created_at": "…" },
  "applied": { "created": 1, "updated": 1, "deleted": 1, "restored": 1, "unchanged": 0 },
  "items": [
    { "client_ref": "tmp-17", "id": "b4d9…", "op": "create",  "version_no": 1, "status": "applied" },
    { "client_ref": null,     "id": "9d4e…", "op": "update",  "version_no": 5, "status": "applied" },
    { "client_ref": null,     "id": "3c8b…", "op": "delete",  "version_no": 3, "status": "applied" },
    { "client_ref": null,     "id": "7a1f…", "op": "restore", "version_no": 6, "status": "applied" }
  ],
  "annotations": [ /* AnnotationRead[] — full resulting live set */ ],
  "warnings": []
}
```

Returning the **full resulting set** costs one query and removes an entire class of desync: the client replaces its store wholesale instead of reconciling deltas. At ≤ 2000 small objects this is a few hundred KB worst case, and the realistic case is ~20 items.

- **409** `REVISION_CONFLICT` — `base_revision_seq` stale. `details` carries `current_revision_seq`.
- **412** `STALE_ANNOTATION_VERSION` — an item's `version_no` is stale. `details` lists every conflicting `{id, expected, actual}` — all of them, not just the first, so the UI can present one merge dialog.
- **422** — geometry invalid, `op`/`id` mismatch, > 2000 items, duplicate `id` in `items`.
- **404** `IMAGE_NOT_FOUND`; `ANNOTATION_NOT_FOUND` if a referenced `id` is not on this image (cross-image ids are rejected, not silently ignored).

`status` ∈ `applied | unchanged`. `unchanged` is returned when an `update` is byte-identical to current state; **no revision event is written** for it. Without this, an idle canvas auto-save every 30 s inflates the undo stack with thousands of no-op events.

### 10.5 `GET /annotations/{annotation_id}`

- **200** → `AnnotationRead`, `ETag: "<version_no>"`. **404** `ANNOTATION_NOT_FOUND`.

### 10.6 `PATCH /annotations/{annotation_id}` — edit a single point

**Purpose:** "the user must be able to edit every point." This is the single-point editor: nudge a coordinate, retype a label, change kind, re-rank order.

- **Headers:** **`If-Match: "<version_no>"` — required** (`428 PRECONDITION_REQUIRED` if absent). Every other precondition in this API is optional; this one is not. Two surveyors on the same image dragging the same fence corner is a *routine* event, and last-write-wins silently discards one person's field correction. Requiring `If-Match` makes the conflict a 412 the UI can resolve.
- **Body:** `AnnotationUpdate` — all fields of `AnnotationCreate` optional, `extra="forbid"`, `UNSET`-sentinel semantics (§8.4) so `{"label": null}` clears and `{}` is a `400 EMPTY_PATCH`.
  - `geom_type` may change **only** if `geometry` changes with it and they agree → else `422`.
- **200** → `AnnotationRead` with `version_no` incremented, new `ETag`.
- **412** `STALE_ANNOTATION_VERSION` — `details` = `{"expected": 4, "actual": 7}`; body also embeds `current` (the full server-side `AnnotationRead`) so the client can render a diff without a second round trip.
- **404** `ANNOTATION_NOT_FOUND`. **422** per §10.1. **428** `PRECONDITION_REQUIRED`.

Each successful PATCH: `version_no += 1`, appends one `annotation_versions` row (`op='update'`, `before`/`after` payloads), allocates a new `revision_seq`. Editing a point that already produced a GCP does **not** mutate the GCP — `gcps` keeps `pixel_x`/`pixel_y` as of derivation, with `match_result_id` provenance. The response's `gcp_id` becomes *stale-flagged* via `GET /images/{id}/gcps?stale=true`, and re-deriving is an explicit `POST /images/{id}/gcps/recompute`. Silently mutating delivered survey coordinates because someone nudged an annotation is exactly the behavior this design refuses.

### 10.7 `DELETE /annotations/{annotation_id}`

- **Headers:** `If-Match: "<version_no>"` optional; stale → `412`.
- **200** → `AnnotationRead` with `is_deleted: true` (not `204`) — the tombstone is a real, restorable state and the client needs the new `version_no` to restore it.
- **404** `ANNOTATION_NOT_FOUND`. Deleting an already-tombstoned annotation → **200**, idempotent, no new event.

Soft-delete (`is_deleted = true`), never a row delete. `gcps.landmark_id` is `ON DELETE SET NULL` precisely so a delivered coordinate survives; keeping the tombstone means `restore` works and the GCP keeps its provenance link.

### 10.8 `DELETE /images/{image_id}/annotations`

**Purpose:** "clear canvas".

- **Query:** `kind` (csv, optional — clear only these kinds).
- **Headers:** `X-Confirm-Delete: {image_id}` **required** → else `428 CONFIRMATION_REQUIRED`.
- **200** → `AnnotationBulkUpsertResponse` (one revision, `applied.deleted = N`, `annotations: []`). Restorable in one call via `POST /revisions/{id}/restore`.
- **404** `IMAGE_NOT_FOUND`.

### 10.9 Client op idempotency

`client_op_id` (on `AnnotationCreate` and `AnnotationBulkUpsertRequest`) is a client-minted UUID **per user gesture**, landing in `annotation_versions.client_op_id` under `uq_annotation_versions_client_op`. A retried mutation hits the unique index; the API catches `23505` and returns the **original** result with `Idempotency-Replayed: true` instead of a 409. This is what makes React Query's automatic retry safe during a drag on a flaky uplink — without it, one retried request duplicates the point and corrupts the undo stack. It is distinct from the `Idempotency-Key` header (§5.2): that one guards expensive job starts at the transport layer; this one guards annotation events at the domain layer and is what the undo log itself is keyed on.

---

## 11. Revisions and annotation history

Router: `backend/app/api/v1/revisions.py` — `router_project = APIRouter(prefix="/projects/{project_id}/revisions", tags=["revisions"])`, `router_flat = APIRouter(prefix="/revisions", tags=["revisions"])`, `router_versions = APIRouter(tags=["revisions"])` (owns the `/annotation-versions` paths).

Tables: `project_revisions`, `annotation_versions`.

**Two layers, deliberately distinct.** The assignment asks for "annotation versions: list revisions, get a revision, restore a revision". The DB splits this into a **revision** (a project-scoped, restorable point in time — `project_revisions.seq`) and a **version event** (an append-only per-annotation change record — `annotation_versions`). The API exposes both, because they answer different questions:

- *"Take me back to how it was before the re-survey"* → **revisions**. Restorable.
- *"Who moved this fence corner, when, and from where?"* → **version events**. Audit, undo, never restorable in isolation.

Collapsing them would mean either making every keystroke a restorable checkpoint (thousands of them) or losing per-point attribution. Both are unacceptable.

### 11.1 `GET /projects/{project_id}/revisions`

- **Query:** `RevisionListParams` — `limit`, `offset`, `sort`, `is_checkpoint`, `actor_id`, `image_id` (revisions touching that image), `seq__gte`, `seq__lte`, `created_at__gte`, `created_at__lte`.
- **Sort whitelist:** `seq`, `created_at`. **Default:** `-seq` (hits `ix_project_revisions_project_seq`).
- **200** → `Page[RevisionSummary]`:

```jsonc
{ "id": "e1f2…", "project_id": "1b2c…", "seq": 48,
  "label": "adjusted north fence", "actor_id": "alice",
  "is_checkpoint": true, "annotation_count": 219, "event_count": 4,
  "restorable": true, "created_at": "…" }
```

`RevisionSummary` omits `snapshot` — checkpoint snapshots are whole-project annotation blobs (hundreds of KB each); 50 of them in a list response is tens of MB.

`restorable` is derived: `true` iff a snapshot exists at-or-before this seq and the replay chain from it is intact. Non-checkpoint revisions are still restorable — replay from the nearest preceding checkpoint. It goes `false` only if history was pruned below this seq.

- **404** `PROJECT_NOT_FOUND`. **422** bad params.

### 11.2 `POST /projects/{project_id}/revisions`

**Purpose:** cut an explicit, labelled checkpoint — "before I start the re-survey, mark this".

- **Body:** `RevisionCreate` — `{ "label": str (1..200, required), "is_checkpoint": bool = true, "metadata": dict = {} }`.
- **201** → `RevisionRead`. `Location: /api/v1/revisions/{id}`.
- **404** `PROJECT_NOT_FOUND`. **409** `PROJECT_HAS_ACTIVE_JOBS` — a running match derives GCPs against annotation state; checkpointing mid-flight records a moment that never coherently existed.

Automatic checkpoints are also cut by the service every `CHECKPOINT_EVERY_N_EVENTS` (default 50) — this is what bounds replay cost. This endpoint is the manual override.

### 11.3 `GET /revisions/{revision_id}`

- **Query:** `include_snapshot: bool = true`, `image_id: UUID | null` (restrict the snapshot to one image).
- **200** → `RevisionRead`:

```jsonc
{
  "id": "e1f2…", "project_id": "1b2c…", "seq": 48,
  "label": "adjusted north fence", "actor_id": "alice",
  "is_checkpoint": true, "annotation_count": 219, "event_count": 4,
  "restorable": true, "created_at": "…",
  "snapshot": {
    "schema_version": 1,
    "images": { "7f3a…": [ /* AnnotationRead[] as of seq=48 */ ] }
  },
  "snapshot_source": "stored",         // stored | replayed
  "events": [ /* AnnotationVersionSummary[] — the events grouped under this revision */ ],
  "diff_summary": { "created": 1, "updated": 1, "deleted": 1, "restored": 1 }
}
```

`snapshot_source` tells the truth about cost: `stored` = read straight from `project_revisions.snapshot`; `replayed` = materialized by replaying events from the nearest preceding checkpoint (non-checkpoint revisions). Replay is capped at `MAX_REPLAY_EVENTS` (5000) → else **`422 REVISION_REPLAY_TOO_EXPENSIVE`** directing the caller to a nearby checkpoint (`details.nearest_checkpoint_seq`). A history endpoint that can spin for 40 s is a DoS on your own database.

- **404** `REVISION_NOT_FOUND`. **410** `REVISION_PRUNED` — history pruned below this seq; `restorable: false`.

### 11.4 `POST /revisions/{revision_id}/restore`

**Purpose:** restore the project's annotations to that revision.

- **Body:** `RevisionRestoreRequest`

| Field | Type | Default | Notes |
|---|---|---|---|
| `image_ids` | `list[UUID] \| null` | `null` = whole project | restore only these images |
| `label` | `str \| null` | `"restore of revision {seq}"` | label for the **new** revision |
| `base_revision_seq` | `int \| null` | `null` | optimistic lock against concurrent edits |
| `dry_run` | `bool` | `false` | compute and return the diff, change nothing |

- **200** → `RevisionRestoreResponse`:

```jsonc
{
  "restored_from": { "id": "e1f2…", "seq": 48 },
  "new_revision":  { "id": "aa77…", "seq": 62, "label": "restore of revision 48", "created_at": "…" },
  "applied": { "created": 2, "updated": 5, "deleted": 3, "restored": 1, "unchanged": 211 },
  "affected_image_ids": ["7f3a…"],
  "dry_run": false,
  "warnings": [
    { "code": "GCPS_NOW_STALE", "message": "12 GCPs on 1 image were derived from annotations that this restore changed.",
      "field": "gcps", "requested": null, "effective": null }
  ]
}
```

**Restore is forward-only.** It never rewrites or deletes history; it computes the delta from current state to the target state and applies it as a **new** revision (seq 62), emitting normal `op='restore'`/`update`/`delete` events. So a restore is itself undoable by restoring the revision before it. Rewinding `current_revision_seq` — the obvious alternative — would orphan every event above it and make the log lie about what happened. An append-only log that gets rewound is not an audit log.

- **409** `REVISION_RESTORE_CONFLICT` — `base_revision_seq` stale, or the project mutated between diff and apply (the whole operation holds `SELECT … FOR UPDATE` on the project row; this fires only on lock timeout).
- **409** `PROJECT_HAS_ACTIVE_JOBS` — a running match is reading annotation state.
- **404** `REVISION_NOT_FOUND`, `IMAGE_NOT_FOUND` (an `image_ids` entry not in this project).
- **410** `REVISION_PRUNED`. **422** `REVISION_REPLAY_TOO_EXPENSIVE`.

Restore **never touches GCPs**, only annotations. It warns (`GCPS_NOW_STALE`) and leaves them, for the same reason as §10.6: delivered coordinates change only when a human explicitly asks. Recomputing is `POST /images/{id}/gcps/recompute`.

### 11.5 `GET /images/{image_id}/annotation-versions`

**Purpose:** the per-image event timeline — undo stack, audit trail, "what changed on this photo".

- **Query:** `AnnotationVersionListParams` — `limit` (default 50, max 200), `offset` **or** `before_id` (keyset, §3.1 — mutually exclusive → `422 PARAM_CONFLICT`), `annotation_id`, `op` (csv), `actor_id`, `revision_id`, `created_at__gte`, `created_at__lte`, `include_payloads` (bool, default `false`).
- **Sort:** fixed `-id`. Not configurable: this is an append-only log and `id DESC` *is* reverse-chronological, backed by `ix_annotation_versions_image_time`. Offering `?sort=created_at` would invite a slower scan that answers the identical question.
- **200** → `Page[AnnotationVersionSummary]`:

```jsonc
{ "id": 918342, "annotation_id": "9d4e…", "image_id": "7f3a…", "revision_id": "e1f2…",
  "op": "update", "version_no": 5,
  "actor_id": "alice", "client_op_id": "5f2c…", "created_at": "…",
  "summary": { "changed_fields": ["geometry"], "pixel_delta": 12.7 },
  "before": null, "after": null }
```

`before`/`after` are `null` unless `include_payloads=true` — full payloads on both sides of 200 events is megabytes for a timeline that renders one line each. `summary.changed_fields` + `pixel_delta` (Euclidean move distance in pixels, for geometry changes) give the list view everything it needs.

**`id` is a JSON number**, not a string — `annotation_versions.id` is `BIGSERIAL` (§1.2).

- **404** `IMAGE_NOT_FOUND`. **422** `PARAM_CONFLICT`.

### 11.6 `GET /annotations/{annotation_id}/versions`

**Purpose:** one point's full history — "who has touched this fence corner".

- **Query:** same as §11.5 minus `annotation_id`. **Sort:** fixed `-version_no` (`ix_annotation_versions_annotation`).
- **200** → `Page[AnnotationVersionSummary]`.
- **404** `ANNOTATION_NOT_FOUND` — **only if** no events exist for that id. Note the DDL's deliberate omission of an FK on `annotation_versions.annotation_id`: the log outlives hard-deleted rows. So this endpoint **returns history for annotations that no longer exist**, which is the point of an audit log. It 404s only when the id is genuinely unknown to the ledger.

### 11.7 `GET /annotation-versions/{version_id}`

- **Path:** `version_id: int` (BIGSERIAL).
- **200** → `AnnotationVersionRead` — always includes `before`/`after` in full, plus `diff` (RFC 6902 JSON Patch from `before` to `after`) and `pixel_geom_after` as GeoJSON for canvas ghost rendering.
- **404** `ANNOTATION_VERSION_NOT_FOUND`.

Per the DDL CHECK: `before` is null iff `op='create'`; `after` is null iff `op='delete'`. Schemas mirror this exactly, and the invariant is stated in the OpenAPI description so client code can rely on it.

---

## 12. Matching and jobs

Routers:
- `backend/app/api/v1/matching.py` — `router_image = APIRouter(prefix="/images/{image_id}", tags=["matching"])`, `router_results = APIRouter(prefix="/match-results", tags=["matching"])`
- `backend/app/api/v1/jobs.py` — `APIRouter(prefix="/jobs", tags=["jobs"])`

Tables: `match_jobs`, `match_results`.

### 12.1 `POST /images/{image_id}/match`

**Purpose:** start the async search: fetch satellite tiles around a hint, extract features on both sides, match, estimate a homography, score candidates, derive GCPs.

- **Headers:** `Idempotency-Key` (recommended).
- **Query:** `force: bool = false` — cancel any in-flight match for this image and start fresh.
- **Body:** `MatchRequest` (`backend/app/schemas/matching.py`)

```jsonc
{
  "search_hint": {
    "center": { "lat": 41.8902, "lon": 12.4231 },
    "radius_m": 1200.0,
    "zoom_levels": [17, 18],
    "use_image_gps": true,
    "aoi": null
  },
  "provider": "esri_world_imagery",
  "extractor": "sift",
  "matcher": "flann",
  "estimator": "usac_magsac",
  "use_semantic": false,
  "annotation_version_seq": 48,
  "annotation_ids": null,
  "options": {
    "max_tiles": 256,
    "max_candidates": 25,
    "min_confidence": 40.0,
    "ratio_test": 0.75,
    "cross_check": false,
    "ransac_threshold_px": 3.0,
    "ransac_max_iters": 5000,
    "min_inliers": 12,
    "max_keypoints": 8000,
    "tile_stride": 1,
    "mosaic_cols": 2, "mosaic_rows": 2,
    "seed": 42,
    "timeout_s": 900
  },
  "score_weights": { "feature": 0.4, "geometric": 0.3, "landmark": 0.2, "semantic": 0.1 }
}
```

**`SearchHint` resolution order** — first that yields a geometry wins; recorded in `match_jobs.search_aoi` and echoed in the response:

1. `search_hint.aoi` — explicit GeoJSON Polygon.
2. `search_hint.center` + `radius_m` — a geodesic buffer.
3. `use_image_gps: true` + image has `exif_gps` → buffer around it by `radius_m`.
4. `use_image_gps: true` + image `is_geotiff` → its `bounds` (footprint), `radius_m` ignored.
5. Project `aoi`.
6. → **`422 SEARCH_HINT_REQUIRED`**, `details` explains all five were empty.

Never a global search. A worldwide SIFT search is not a slow feature; it is a nonexistent one — there is no budget in which it terminates.

| Field | Type | Default | Validation |
|---|---|---|---|
| `search_hint.center` | `LatLon \| null` | `null` | lat ∈ [-90,90], lon ∈ [-180,180] |
| `search_hint.radius_m` | `float` | project default (1000) | **`50..50000`** → else `422`. Above 50 km the tile count is absurd at any useful zoom. |
| `search_hint.zoom_levels` | `list[int]` | `[project.default_search_zoom]` | 1–3 entries, each within the provider's `min_zoom..max_zoom` → else `422 ZOOM_OUT_OF_RANGE`. Sorted+deduped server-side. |
| `search_hint.use_image_gps` | `bool` | `true` | |
| `search_hint.aoi` | `GeoJsonPolygon \| null` | `null` | valid, ≤ 1000 vertices, area ≤ 2500 km² |
| `provider` | `ProviderName \| null` | project default | must be configured → else `503 PROVIDER_NOT_CONFIGURED` |
| `extractor` | `ExtractorName \| null` | project default | any enum value accepted, incl. unavailable ones (→ warn+fallback) |
| `matcher` | `MatcherName \| null` | project default | same |
| `estimator` | `EstimatorName \| null` | `usac_magsac` | |
| `use_semantic` | `bool` | `false` | if `true` and no weights → `semantic_available=false` + warning; job proceeds |
| `annotation_version_seq` | `int \| null` | current | **pins** the annotation set matched against |
| `annotation_ids` | `list[UUID] \| null` | all live | subset to match against |
| `options.max_tiles` | `int` | 256 | `1..1024`; combined with zoom+radius → `422 SEARCH_AREA_TOO_LARGE` if the AOI needs more |
| `options.min_confidence` | `float` | 40.0 | `0..100`; candidates below are dropped |
| `options.seed` | `int \| null` | `null` | pins RANSAC's RNG → bit-reproducible results |
| `options.timeout_s` | `int` | 900 | `30..3600`; soft cap, checked at stage boundaries |
| `score_weights` | `dict` | `{"feature":0.4,"geometric":0.3,"landmark":0.2,"semantic":0.1}` | keys fixed, values ≥ 0, **must sum to 1.0 ± 1e-6** → else `422` |

**Pre-flight validation, all synchronous** (a job that dies in 3 s on a checkable condition is a worse UX than a 422 now):

| Check | Failure |
|---|---|
| image exists, not soft-deleted | `404 IMAGE_NOT_FOUND` |
| `image.status == 'ready'` | `409 IMAGE_STILL_PROCESSING` |
| ≥ 1 live annotation (or `annotation_ids` non-empty and resolvable) | `422 NO_ANNOTATIONS` |
| hint resolves (§ above) | `422 SEARCH_HINT_REQUIRED` |
| provider configured | `503 PROVIDER_NOT_CONFIGURED` |
| provider allowed by ToS policy | `403 PROVIDER_TOS_FORBIDDEN` |
| zooms within provider range | `422 ZOOM_OUT_OF_RANGE` |
| estimated tiles ≤ `max_tiles` | `422 SEARCH_AREA_TOO_LARGE` (`details`: `estimated_tiles`, `max_tiles`, `suggested_zoom`) |
| ≥ 1 Celery worker alive (cached 10 s) | `503 WORKER_UNAVAILABLE` |
| no active match for this image unless `force=true` | `409 MATCH_JOB_ALREADY_RUNNING` (`details.job_id`) |

> `NO_ANNOTATIONS` is a 422 and not a permissive "match on raw features anyway". The product's premise is that the surveyor marks landmarks and the system locates *those*. A match with zero landmarks can still estimate a homography, but it cannot produce a single GCP — the deliverable — so it is a job whose successful completion is worthless. Rejecting it up front is honest.

- **202** → `JobRead` (`type: "match"`). Headers `Location: /api/v1/jobs/{job_id}`, `Retry-After: 1`.
- **409** `MATCH_JOB_ALREADY_RUNNING`, `IMAGE_STILL_PROCESSING`, `IDEMPOTENCY_*`.
- **422**, **403**, **404**, **503** as above.

`force=true` cancels the in-flight job (cooperatively, §5.6) and enqueues the new one immediately; the old job lands `cancelled`. It does **not** wait for the old worker to acknowledge — the new job's `resolving_aoi` stage is longer than the cancel latency.

**Reproducibility.** The whole resolved config (provider, extractor, matcher, estimator, params, score_weights, search_aoi, seed, `code_version`, `used_gpu`) is denormalized onto `match_jobs` at insert. Changing project defaults later never changes what an old job did. With `options.seed` set, the classical path is bit-reproducible: same image + same annotations + same tiles + same seed → same homography.

### 12.2 `GET /jobs`

- **Query:** `JobListParams` — `limit`, `offset`, `sort`, `type` (csv: `match|segment|suggest_landmarks|export|batch|gcp_recompute|thumbnail`), `status` (csv), `image_id`, `project_id`, `batch_id`, `active` (bool — sugar for `status=pending,queued,running,retrying`), `created_at__gte`, `created_at__lte`.
- **Sort whitelist:** `created_at`, `updated_at`, `started_at`, `finished_at`, `duration_ms`. **Default:** `-created_at`.
- **200** → `Page[JobSummary]` = `id, type, status, image_id, project_id, batch_id, progress_percent, progress_stage, warning_count, created_at, started_at, finished_at, duration_ms`.
- **422** bad params.

`JobRead`/`JobSummary` are a **union view** over `match_jobs`, `exports`, and `batch_jobs` (a `UNION ALL` view `v_jobs` per `10-database.md`, or three queries merged in the service). One job surface for the client, discriminated by `type`. The alternative — `/match-jobs`, `/export-jobs`, `/batch-jobs` — forces the frontend to write three pollers with three response shapes for one progress bar component.

### 12.3 `GET /jobs/{job_id}`

**The** polling endpoint (§5.3).

- **Query:** `wait: int = 0` (`0..30`, long-poll seconds).
- **Headers:** `If-None-Match` supported.
- **200** → `JobRead` (§5.5 shape). Headers: `ETag` (over status+progress+updated_at), `Retry-After` (1 running / 2 pending|queued / 5 retrying; **absent** when terminal — its absence is the machine-readable "stop polling"), `Cache-Control: no-store`.
- **304** — unchanged since `If-None-Match`.
- **404** `JOB_NOT_FOUND` — unknown, or reaped (30-day retention).

`JobRead.error` when `status='failed'`:

```jsonc
"error": { "code": "PROVIDER_UPSTREAM_ERROR", "message": "Esri World Imagery returned HTTP 503 for 14 tiles after 3 attempts.",
           "status": 502, "details": null, "request_id": "01J8…", "timestamp": "…", "docs_url": "…" }
```

Deliberately `ErrorBody`-shaped — the client renders job failures with the same component as HTTP errors. `error_traceback` is stored but **never** serialized (§5.7).

### 12.4 `DELETE /jobs/{job_id}`

Semantics in §5.6.

- **200** → `JobRead` (`status: "cancelled"`) — was `pending`/`queued`.
- **202** → `JobRead` (`status: "running"`, `cancel_requested: true`) + `Retry-After: 1` — cooperative cancel in flight.
- **409** `JOB_NOT_CANCELLABLE` — terminal. `details.status` = actual.
- **404** `JOB_NOT_FOUND`.

### 12.5 `GET /images/{image_id}/match-results`

**Purpose:** the ranked candidate list — the "we think it's one of these places" panel.

- **Query:** `MatchResultListParams` — `limit` (default 25), `offset`, `sort`, `job_id`, `is_selected`, `confidence__gte`, `provider`, `latest_job_only` (bool, default **`true`**).
- **Sort whitelist:** `rank`, `overall_confidence`, `inlier_count`, `created_at`. **Default:** `rank` (ascending; rank 1 = best).
- **200** → `Page[MatchResultSummary]` = `id, match_job_id, rank, is_selected, provider, tile_z, tile_x, tile_y, center, overall_confidence, inlier_count, inlier_ratio, gcp_count, satellite_image_url, created_at`.

`latest_job_only=true` by default: an image matched five times has five generations of candidates, and mixing them in one rank-sorted list produces nonsense (rank 1 from three jobs ago next to rank 1 from now). Default to the most recent job's results; `false` + `sort=-overall_confidence` gives the cross-job view for comparison.

- **404** `IMAGE_NOT_FOUND`. Empty page (not 404) when the job succeeded with no candidates — §5.7.

### 12.6 `GET /match-results/{match_result_id}`

- **200** → `MatchResultRead`:

```jsonc
{
  "id": "cc11…", "match_job_id": "0a9c…", "image_id": "7f3a…",
  "rank": 1, "is_selected": true,
  "provider": "esri_world_imagery",
  "tile": { "z": 18, "x": 137204, "y": 93518, "mosaic_cols": 2, "mosaic_rows": 2 },
  "tile_bounds": { "type": "Polygon", "coordinates": [[[12.418,41.888],[12.424,41.888],[12.424,41.892],[12.418,41.892],[12.418,41.888]]] },
  "center": { "lat": 41.8900, "lon": 12.4210 },
  "satellite_image_url": "/api/v1/match-results/cc11…/satellite-image",
  "satellite_checksum": "b7c2…",
  "satellite_size_px": { "width": 512, "height": 512 },

  "homography": [1.0324, -0.0142, 214.77, 0.0091, 1.0288, -87.31, 0.0000031, -0.0000012, 1.0],
  "sat_geotransform": [1382104.9, 0.5971, 0.0, 5145821.3, 0.0, -0.5971],
  "transform_note": "image_px --homography--> mosaic_px --sat_geotransform--> EPSG:3857 --> EPSG:4326. Row-major H; GDAL-order geotransform. See 10-database.md Appendix A.",

  "stats": { "feature_extractor_used": "sift", "feature_matcher_used": "flann", "estimator_used": "usac_magsac",
             "keypoints_query": 6132, "keypoints_train": 7841, "raw_matches": 2104, "good_matches": 388,
             "inlier_count": 214, "inlier_ratio": 0.5515,
             "ransac_reproj_error_px": 1.82, "ransac_threshold_px": 3.0, "ransac_iterations": 1420,
             "homography_condition_number": 84.2, "homography_determinant": 1.0619 },

  "scores": { "feature_similarity_score": 0.81, "geometric_consistency_score": 0.93,
              "landmark_consistency_score": 0.88, "semantic_similarity_score": null,
              "overall_confidence": 87.3,
              "weights_used": { "feature": 0.4, "geometric": 0.3, "landmark": 0.2, "semantic": 0.1 },
              "renormalized": true,
              "renormalization_note": "semantic_similarity_score is null (no deep model ran); its 0.1 weight was redistributed proportionally over the remaining three." },

  "degraded": true,
  "degradation_reason": "Requested matcher 'superglue' unavailable (weights missing); used 'flann'.",
  "warnings": [ { "code": "MODEL_WEIGHTS_MISSING", "message": "…", "field": "matcher", "requested": "superglue", "effective": "flann" } ],

  "gcp_count": 12,
  "gcps_url": "/api/v1/images/7f3a…/gcps?match_result_id=cc11…",
  "quality_flags": ["low_semantic_evidence"],
  "created_at": "…"
}
```

Three things worth calling out:

- **`transform_note` ships in the payload.** The image-pixel → world chain is two composed transforms with two different memory-layout conventions (row-major H, GDAL-order geotransform), and getting either backwards yields coordinates that look plausible and are wrong by hundreds of metres. A one-line statement of the chain costs 200 bytes and prevents the single most expensive mistake a consumer of this API can make.
- **Score renormalization is explicit.** With no deep models, `semantic_similarity_score` is `null` and its weight is redistributed over the remaining three, which are then renormalized to sum to 1. Without `renormalized: true`, an 87.3 on a weightless box and an 87.3 on a GPU box would be quietly incomparable. Stating it makes the number's meaning inspectable.
- **`degraded`/`warnings` at the result level, not just the job level.** Results outlive jobs in the UI; a candidate reviewed a week later must still say it came from the fallback path.

`quality_flags` ∈ `low_inliers`, `low_inlier_ratio`, `degenerate_homography` (cond > 1e6), `reflected_homography` (det ≤ 0), `high_reproj_error`, `low_semantic_evidence`, `geotiff_georeference_disagreement`, `few_landmarks`. Advisory; the UI badges them.

- **404** `MATCH_RESULT_NOT_FOUND`.

### 12.7 `GET /match-results/{match_result_id}/satellite-image`

**Purpose:** "the matching satellite image" — the product's stated deliverable alongside the coordinates.

- **Query:** `overlay: bool = false` — draw projected annotation positions + inlier correspondences onto the mosaic. `format: png|jpeg = png`.
- **200** → binary. `ETag: "<satellite_checksum>"`, `Cache-Control: private, max-age=31536000, immutable` (`overlay=true` → `max-age=86400`), `X-Imagery-Attribution: <required attribution string>`.
- **404** `MATCH_RESULT_NOT_FOUND`; `SATELLITE_IMAGE_NOT_CACHED` if the cached mosaic was GC'd (`details.recoverable: true`, re-fetchable by re-running the match).
- **410** `SATELLITE_IMAGE_PURGED` — provider ToS-mandated cache expiry elapsed (see `40-imagery.md`). Some providers forbid indefinite caching; when the retention window lapses the bytes are deleted and this is the honest answer.

The `X-Imagery-Attribution` header is not decorative — every provider's terms require attribution wherever the imagery is displayed, and this is the mechanism by which the frontend and the PDF exporter obtain the exact required string per result rather than hardcoding one provider's.

### 12.8 `POST /match-results/{match_result_id}/select`

**Purpose:** the surveyor overrides the ranking — "rank 2 is the right field, not rank 1".

- **Body:** `MatchResultSelectRequest` — `{ "note": str | null, "recompute_gcps": bool = true }`.
- **200** → `MatchResultRead` with `is_selected: true`.

Within a `match_job`, `is_selected` is exclusive (partial unique index per `10-database.md`); selecting one clears the rest in the same transaction. With `recompute_gcps=true` (default) the previous selection's GCPs are **replaced** by GCPs derived from this homography — but **manually adjusted GCPs are preserved and re-flagged** rather than destroyed: their `manually_adjusted`/`original_geom`/`adjustment_note` survive, and `GCPS_REPARENTED` warns that a human correction now sits on a different homography. Silently discarding a surveyor's field correction because the ranking changed is unacceptable; silently keeping it without saying so is worse.

- **404** `MATCH_RESULT_NOT_FOUND`. **409** `MATCH_JOB_ALREADY_RUNNING` — selection during an in-flight match on the same image would race the deriver.

---

## 13. GCPs

Routers, both in `backend/app/api/v1/gcps.py`:
- `router_image = APIRouter(prefix="/images/{image_id}/gcps", tags=["gcps"])`
- `router_flat  = APIRouter(prefix="/gcps", tags=["gcps"])`

Table: `gcps`. **This is the product's deliverable.** Every rule below is written to protect it.

### 13.1 The GCP object

**`GcpRead`** (`backend/app/schemas/gcp.py`):

```jsonc
{
  "id": "aa22…", "image_id": "7f3a…", "match_result_id": "cc11…", "landmark_id": "9d4e…",
  "code": "GCP01",
  "image_px": { "x": 2431.5, "y": 1102.0 },
  "satellite_px": { "x": 318.42, "y": 204.91 },
  "lat": 41.890214, "lon": 12.423087,
  "crs": "EPSG:4326",
  "elevation_m": 87.4, "elevation_source": "copernicus_dem",
  "confidence": 87.3,                      // 0-100 (see §1.3)
  "horizontal_accuracy_m": 2.4,
  "manually_adjusted": false,
  "original": null,                        // GcpOriginal, non-null iff manually_adjusted
  "adjustment_offset_m": null,
  "adjusted_by": null, "adjusted_at": null, "adjustment_note": null,
  "is_included_in_export": true,
  "is_stale": false,
  "stale_reason": null,
  "landmark": { "id": "9d4e…", "label": "NE fence corner", "kind": "field_corner", "confidence": 0.9 },
  "residual_px": 1.42,
  "created_at": "…", "updated_at": "…"
}
```

When adjusted:

```jsonc
"manually_adjusted": true,
"original": { "lat": 41.890201, "lon": 12.423055,
              "satellite_px": { "x": 318.42, "y": 204.91 },
              "confidence": 87.3, "derived_at": "…" },
"adjustment_offset_m": 3.14,
"adjusted_by": "alice", "adjusted_at": "…",
"adjustment_note": "Matched to the actual fence post, 3 m NE of the algorithmic fix."
```

- `lat`/`lon` are serialized from `geom geography(Point,4326)` — never a raw WKB/GeoJSON blob. Flat `lat`/`lon` floats are what a CSV exporter, a Leaflet marker, and a surveyor all want.
- `crs` is **always** `"EPSG:4326"` here, present so nobody has to assume. Reprojection happens **at export** (`exports.target_srid`), never on the stored geometry — one CRS in the database, N in the deliverables.
- `residual_px` = reprojection error of this specific point under the homography (`‖H·image_px − satellite_px‖`). Per-point residual is how a surveyor finds *the one bad correspondence* in an otherwise good match; a job-level RMSE hides it.
- `is_stale` / `stale_reason` — the flag that ties §10.6 and §11.4 together.

`stale_reason` ∈ `landmark_moved` (source annotation's geometry changed after derivation), `landmark_deleted`, `homography_superseded` (a newer match result is now selected), `annotations_restored`. Computed on read by comparing `gcps.updated_at`/`pixel_x`/`pixel_y` against the source annotation's current state.

> **Why staleness is a flag and not an auto-recompute.** A GCP is a coordinate that may already be in a survey report, a contract, or a machine-control file. It changes when a human decides it changes. Every path that *could* invalidate a GCP — editing the source annotation, restoring a revision, selecting a different match result — marks it stale and says so. Nothing recomputes it implicitly. `POST /images/{id}/gcps/recompute` is the only door, and it is one a person opens.

### 13.2 `GET /images/{image_id}/gcps`

- **Query:** `GcpListParams` — `limit` (default 200), `offset`, `sort`, `match_result_id`, `confidence__gte`, `manually_adjusted`, `is_included_in_export`, `is_stale`, `landmark_id`, `format` (`json` | `geojson`).
- **Sort whitelist:** `code`, `confidence`, `created_at`, `adjustment_offset_m`, `residual_px`. **Default:** `code` (natural survey order — `GCP01, GCP02, …`; collated so `GCP10` sorts after `GCP09`, not after `GCP01`).
- **Default scope:** GCPs of the image's **selected** match result. `match_result_id` overrides; `match_result_id=all` returns every generation (`details` note: only meaningful for audit).
- **200** → `Page[GcpRead]`, or with `format=geojson` a **`GeoJsonFeatureCollection`**:

```jsonc
{ "type": "FeatureCollection",
  "features": [ { "type": "Feature",
                  "geometry": { "type": "Point", "coordinates": [12.423087, 41.890214] },   // [lon, lat] — RFC 7946
                  "properties": { "id": "aa22…", "code": "GCP01", "confidence": 87.3,
                                  "manually_adjusted": false, "image_x": 2431.5, "image_y": 1102.0,
                                  "label": "NE fence corner", "residual_px": 1.42, /* … */ } } ],
  "bbox": [12.4185, 41.8881, 12.4242, 41.8921] }

```

`format=geojson` here is a **convenience for map rendering**, not an export. It returns the same page (respecting `limit`) and is not persisted, checksummed, or ToS-attributed. `POST /images/{id}/export?format=geojson` is the deliverable: async, complete, reprojected, checksummed, retained. Both exist because conflating them means either the map layer waits on a Celery round trip or the deliverable silently truncates at 200 rows.

- **404** `IMAGE_NOT_FOUND`, `MATCH_RESULT_NOT_FOUND`. Empty page when no match has succeeded.

### 13.3 `GET /gcps/{gcp_id}`

- **200** → `GcpRead`. `ETag` = weak hash of `updated_at`.
- **404** `GCP_NOT_FOUND`.

### 13.4 `PATCH /gcps/{gcp_id}` — manual adjustment mode

**Purpose:** the surveyor refines the answer. This is the most consequential write in the API: its output is what gets delivered.

- **Headers:** `If-Match: "<etag>"` **required** → else `428 PRECONDITION_REQUIRED`; stale → `412 STALE_GCP_VERSION`.
- **Body:** `GcpUpdate` — `extra="forbid"`, `UNSET`-sentinel semantics.

| Field | Type | Notes |
|---|---|---|
| `lat` | `float \| null` | with `lon`; **both or neither** → else `422 PARAM_CONFLICT` |
| `lon` | `float \| null` | |
| `satellite_px` | `PixelXY \| null` | drag on the satellite view |
| `elevation_m` | `float \| null` | sets `elevation_source='manual'` |
| `code` | `str \| null` | 1–32 chars, `^[A-Za-z0-9_\-]+$`, unique per image → else `409 GCP_CODE_CONFLICT` |
| `adjustment_note` | `str \| null` | ≤ 2000 |
| `is_included_in_export` | `bool \| null` | exclude a bad point without deleting it |

**The two adjustment modes, and how the server closes the loop:**

| Client sends | Server does |
|---|---|
| `lat`/`lon` only | Sets `geom`. Derives `satellite_px` by the **inverse** chain: `4326 → 3857 → inv(sat_geotransform) → mosaic_px`. `satellite_pixel_x/y` updated. |
| `satellite_px` only | Sets `satellite_pixel_x/y`. Derives `lat`/`lon` by the **forward** chain: `mosaic_px → sat_geotransform → 3857 → 4326`. `geom` updated. |
| **both** | Checks consistency: forward-project the given `satellite_px` and compare to the given `lat`/`lon`. Within `GCP_CONSISTENCY_TOLERANCE_M` (0.5 m) → accept, `lat`/`lon` authoritative. Beyond → **`422 GCP_ADJUSTMENT_AMBIGUOUS`**, `details` = `{"disagreement_m": 14.2, "tolerance_m": 0.5, "hint": "Send lat/lon or satellite_px, not both."}` |
| neither (only `code`/`note`/flags) | Metadata-only edit. **Does not** set `manually_adjusted`, does not touch `original_geom`. Renaming a GCP is not adjusting it. |

> **Why the server derives the other representation instead of storing one.** `satellite_px` and `lat`/`lon` are two views of one fact, and the DDL stores both (`satellite_pixel_x/y` **and** `geom`). If a PATCH updated only what the client sent, the two would diverge — the map would show the marker in one place and the CSV would export another, with no indication which is right. Deriving is not redundant work; it is the invariant. It is cheap (two affine ops + one `ST_Transform`) and it is done inside the same transaction.
>
> **Why `satellite_px` mode exists at all.** Dragging a marker on the satellite tile is the natural gesture, and it is *more accurate* than typing coordinates: the surveyor is matching what they see. `lat`/`lon` mode exists for the surveyor who has an RTK fix from the field, which is ground truth and outranks the imagery entirely.

**Note that `image_px` is not adjustable here.** Moving the point *on the photograph* is editing the annotation, not the GCP — that is `PATCH /annotations/{id}` (§10.6), which marks this GCP stale. Two endpoints, two meanings: "the algorithm put the coordinate in the wrong place" vs. "I marked the wrong pixel". Allowing `image_px` on this endpoint would silently fork `gcps.pixel_x` from `annotations.pixel_x` with no revision record of the change.

**On the first adjustment**, in one transaction:
1. `original_geom := geom` (the algorithm's answer, **kept forever** — DDL CHECK `ck_gcps_adjustment_complete` enforces it exists whenever `manually_adjusted`).
2. `manually_adjusted := true`; `adjusted_by := principal` (required — `ck_gcps_no_adjustment_metadata_unless_adjusted`; **`401 MISSING_CREDENTIALS` when auth is enabled and unattributable**; with auth disabled, `adjusted_by := 'anonymous'`, and the deployment doc states this plainly: an unauthenticated deployment cannot attribute survey edits).
3. `adjusted_at := now()`.
4. `adjustment_offset_m := ST_Distance(original_geom, geom)` — geodesic, geography type.
5. `confidence` **is left untouched**.

> **Why a manual adjustment does not set `confidence = 100`.** Tempting, and wrong. `gcps.confidence` is defined as *the pipeline's score for this correspondence* — it feeds `best_confidence`, the ranking, and the export filter `min_confidence`. Overwriting it with 100 on human edit destroys the only record of how well the algorithm did, makes `?confidence__gte=70` meaningless (every adjusted point passes), and asserts a certainty the human never claimed — a surveyor nudging a marker 3 m is *guessing better*, not measuring. Human certainty is carried by `manually_adjusted: true` + `adjustment_offset_m` + `adjusted_by` + the note. A client that wants "trust human edits absolutely" filters on `manually_adjusted`, which says exactly that and nothing more.

Subsequent adjustments update `geom`/`satellite_px`/`offset`/`by`/`at`/`note`. **`original_geom` is written once and never again** — it is the algorithm's answer, and there is only one of those.

- **200** → `GcpRead`, new `ETag`.
- **409** `GCP_CODE_CONFLICT` — duplicate `code` on the image.
- **412** `STALE_GCP_VERSION` — body embeds `current` for diffing.
- **422** `GCP_ADJUSTMENT_AMBIGUOUS`, `PARAM_CONFLICT` (`lat` without `lon`), `VALIDATION_ERROR`, `GCP_OUT_OF_BOUNDS` (adjusted position falls outside `tile_bounds` by > `GCP_BOUNDS_SLACK_M` (100 m) — the point is no longer on the imagery that justifies it; `details.hint` suggests re-matching with a wider radius).
- **428** `PRECONDITION_REQUIRED`. **404** `GCP_NOT_FOUND`. **400** `EMPTY_PATCH`.

Every adjustment is audit-logged (actor, before, after, offset, note, `request_id`). Adjusting a **stale** GCP is allowed and clears nothing — `is_stale` is about provenance, not validity, and blocking edits on stale points would trap the surveyor.

### 13.5 `POST /gcps/{gcp_id}/reset`

**Purpose:** undo a manual adjustment — back to the algorithm's answer.

- **Body:** `GcpResetRequest` — `{ "note": str | null }` (optional; why the correction was withdrawn).
- **200** → `GcpRead`, with `geom := original_geom`, `satellite_px` re-derived, `manually_adjusted := false`, `original := null`, `adjustment_offset_m/adjusted_by/adjusted_at/adjustment_note := null` (per `ck_gcps_no_adjustment_metadata_unless_adjusted`).
- **200, no-op** — when `manually_adjusted` is already `false`. **Idempotent by design:** reset is "make it be the algorithm's answer", which is already true. A 409 here would mean a double-clicked Reset button shows the surveyor an error for a state they successfully reached. The response carries `_meta: {"reset_applied": false}` for clients that care.
- **404** `GCP_NOT_FOUND`.
- **409** `GCP_ORIGINAL_UNAVAILABLE` — `manually_adjusted=true` but `original_geom` is null. The DDL makes this unreachable; it is specified so that if data is ever hand-repaired past the constraint, the API says so instead of nulling out a coordinate.

The reset event is retained in the audit log. `original_geom` is not cleared on reset — it remains for the next adjustment cycle.

### 13.6 `POST /images/{image_id}/gcps/recompute`

**Purpose:** refit the homography using manually adjusted GCPs as constraints, then re-derive the rest. The core of the refinement loop: the surveyor corrects 3 points they're sure of, and the other 9 improve.

- **Body:** `GcpRecomputeRequest`

| Field | Type | Default | Notes |
|---|---|---|---|
| `match_result_id` | `UUID \| null` | selected | which homography to refit |
| `mode` | enum | `refit` | `refit`: re-estimate H with adjusted GCPs as weighted anchors. `rederive`: keep H, re-derive from current annotation geometry (clears staleness after annotation edits). |
| `anchor_weight` | `float` | `10.0` | `1..1000`; how much an adjusted GCP outweighs an algorithmic correspondence in the refit |
| `preserve_adjusted` | `bool` | `true` | adjusted GCPs keep their coordinates and are not overwritten by the new H |
| `estimator` | `EstimatorName \| null` | job's | |
| `dry_run` | `bool` | `false` | return predicted deltas, write nothing |

- **202** → `JobRead` (`type: "gcp_recompute"`). `Location`, `Retry-After: 1`.
- **200** → `GcpRecomputeDryRun` when `dry_run=true` — synchronous (refitting ≤ 2000 correspondences is milliseconds; only the full pipeline needs a worker):

```jsonc
{ "match_result_id": "cc11…", "mode": "refit",
  "before": { "rmse_px": 1.82, "inlier_count": 214, "anchors_used": 0 },
  "after":  { "rmse_px": 0.94, "inlier_count": 231, "anchors_used": 3 },
  "deltas": [ { "gcp_id": "aa22…", "code": "GCP01", "shift_m": 0.0,  "reason": "preserved (manually adjusted)" },
              { "gcp_id": "bb33…", "code": "GCP02", "shift_m": 1.72, "reason": "rederived from refit homography" } ],
  "max_shift_m": 4.21, "mean_shift_m": 1.13,
  "warnings": [] }
```

`dry_run` is not a nicety. "Recompute" moves coordinates the surveyor may have already reported; they get to see how far, and for which points, before committing.

- **422** `NO_ADJUSTED_GCPS` — `mode=refit` with zero adjusted GCPs (nothing to refit *toward*; the result would be the existing H).
- **422** `INSUFFICIENT_ANCHORS` — fewer than 4 total correspondences. A homography needs 4; `details.required: 4`.
- **409** `MATCH_JOB_ALREADY_RUNNING`. **404** `IMAGE_NOT_FOUND`, `MATCH_RESULT_NOT_FOUND`. **503** `WORKER_UNAVAILABLE`.

A recompute writes a **new** `match_results` row (`rank` retained, `is_selected` moved to it, `estimator_used` recorded, `parent_match_result_id` set) rather than mutating the old one, keeping the DDL's `ON DELETE RESTRICT` provenance chain intact and the original algorithmic answer inspectable forever. Adjusted GCPs are re-parented to the new result with their `original_geom` and adjustment metadata carried across.

---

## 14. Landmark suggestions

Router: `backend/app/api/v1/suggestions.py` — `APIRouter(prefix="/images/{image_id}", tags=["suggestions"])`.
Storage: `semantic_features` rows with `source='suggestion'` + a `landmark_suggestions` materialization (see `10-database.md`); suggestions are **not** `annotations` until accepted.

> **Why suggestions are a separate resource.** Writing AI guesses straight into `annotations` would put unreviewed machine output into the surveyor's revision history, the undo stack, and — via `is_gcp_candidate` — the GCP deriver. A suggestion is a *proposal*; an annotation is an *assertion by a human*. The boundary between them is `POST …/accept`, and it is the only door.

### 14.1 `POST /images/{image_id}/suggest-landmarks`

**Purpose:** AI automatic landmark suggestions — propose GCP-worthy points the surveyor can accept in one click.

- **Body:** `SuggestLandmarksRequest`

| Field | Type | Default | Notes |
|---|---|---|---|
| `strategy` | enum | `corners` | `corners` \| `saliency` \| `semantic` \| `hybrid` |
| `detector` | `FeatureDetectorName \| null` | `null` → strategy default | `gftt` \| `harris` \| `fast` \| `sift` \| `orb` \| `akaze` \| `superpoint` |
| `max_suggestions` | `int` | `25` | `1..200` |
| `min_score` | `float` | `0.3` | `0..1` |
| `min_separation_px` | `float` | `40.0` | NMS radius — prevents 25 suggestions on one fence post |
| `region` | `GeoJsonPolygon \| null` | `null` | restrict to an image-pixel-space polygon |
| `exclude_existing` | `bool` | `true` | suppress suggestions within `min_separation_px` of a live annotation |
| `kinds` | `list[AnnotationKind] \| null` | `null` | bias/filter toward these kinds (`semantic`/`hybrid` only) |
| `use_semantic` | `bool` | `false` | allow DINOv2/SAM if available |
| `seed` | `int \| null` | `null` | reproducibility |

**Strategy → backend, and what happens with no weights** (the graceful-degradation contract, concretely):

| `strategy` | Preferred | Classical fallback (always available) |
|---|---|---|
| `corners` | `cv2.goodFeaturesToTrack` (Shi-Tomasi) + subpixel refine | *is* the classical path — no weights, no fallback needed |
| `saliency` | `cv2.saliency.StaticSaliencySpectralResidual` + peak NMS | same — classical |
| `semantic` | DINOv2 features / SAM masks → corners of `field_border`/`building`/`road` masks | **contour-based**: Canny → `findContours` → `approxPolyDP` → polygon vertices, kind-labelled by heuristics (`40-imagery.md`) |
| `hybrid` | semantic ∪ corners, rank-fused | corners ∪ contour-corners |

`corners` is the default precisely because it needs nothing beyond OpenCV and produces genuinely useful GCP candidates on agricultural imagery — field corners *are* Shi-Tomasi corners. The deep path improves ranking and labelling, not existence.

- **202** → `JobRead` (`type: "suggest_landmarks"`). `Location`, `Retry-After: 1`.
- **404** `IMAGE_NOT_FOUND`. **409** `IMAGE_STILL_PROCESSING`, `SUGGEST_JOB_ALREADY_RUNNING`. **422** `VALIDATION_ERROR`, `ANNOTATION_OUT_OF_BOUNDS` (region outside the image). **503** `WORKER_UNAVAILABLE`.

The job replaces the image's prior suggestions from the same strategy (they are proposals with no history worth keeping); accepted ones are unaffected — they are annotations now.

### 14.2 `GET /images/{image_id}/landmark-suggestions`

- **Query:** `SuggestionListParams` — `limit` (default 50), `offset`, `sort`, `job_id`, `strategy`, `kind`, `score__gte`, `status` (`pending|accepted|rejected`), `latest_job_only` (default `true`).
- **Sort whitelist:** `score`, `created_at`. **Default:** `-score`.
- **200** → `Page[LandmarkSuggestionRead]`:

```jsonc
{ "id": "d5e6…", "image_id": "7f3a…", "job_id": "0b1c…",
  "strategy": "corners", "detector_used": "gftt",
  "kind": "field_corner",                 // proposed kind
  "geom_type": "point",
  "geometry": { "type": "Point", "coordinates": [2431.5, 1102.0] },   // image pixel space
  "score": 0.87,                          // 0-1, detector-normalized
  "rank": 1,
  "label": null,
  "rationale": "Strong Shi-Tomasi corner (λmin=0.31) at the junction of two field borders.",
  "status": "pending",                    // pending | accepted | rejected
  "accepted_annotation_id": null,
  "degraded": true,
  "warnings": [ { "code": "MODEL_WEIGHTS_MISSING", "message": "DINOv2 weights absent; used classical Shi-Tomasi corners.",
                  "field": "strategy", "requested": "semantic", "effective": "corners" } ],
  "created_at": "…" }
```

`rationale` is a short human-readable justification. A surveyor asked to accept 25 machine guesses needs to know *why* each was proposed; "strong corner at a field-border junction" is actionable, a bare 0.87 is not.

- **404** `IMAGE_NOT_FOUND`. Empty page when never run — not a 404. Absence of suggestions is a normal state.

### 14.3 `POST /images/{image_id}/landmark-suggestions/accept`

**Purpose:** promote suggestions into real annotations. Bulk, because the gesture is "accept these 8".

- **Body:** `SuggestionAcceptRequest`

```jsonc
{ "suggestion_ids": ["d5e6…", "f7a8…"],
  "overrides": { "d5e6…": { "kind": "field_corner", "label": "NE corner", "confidence": 0.8 } },
  "reject_others": false,
  "revision_label": "accepted AI suggestions",
  "client_op_id": "9c3d…" }
```

| Field | Rules |
|---|---|
| `suggestion_ids` | 1–200; all must belong to this image, `status='pending'` |
| `overrides` | per-suggestion partial `AnnotationCreate` (kind, label, description, confidence, style, attributes) |
| `reject_others` | mark every other pending suggestion from the same job `rejected` |

- **200** → `AnnotationBulkUpsertResponse` (§10.4) — one transaction, **one revision**, plus `accepted: [{suggestion_id, annotation_id}]`. Reusing the bulk-upsert response shape is deliberate: accepting suggestions *is* a bulk annotation create, and the client's store-reconciliation code should be identical.
- Accepted suggestions → `status='accepted'`, `accepted_annotation_id` set. Created annotations carry `attributes.suggested_by = {strategy, detector, score, job_id}` — provenance survives, so a later audit can distinguish "the surveyor marked this" from "the surveyor accepted a machine proposal".
- **Default `confidence` for an accepted suggestion is `0.7`, not the detector's score.** The scales are different quantities (§1.3): a detector's 0.87 is corner strength; `annotations.confidence` is *the surveyor's certainty*. Copying one into the other silently launders a machine score into a human assertion. 0.7 is an honest "a human glanced at this and clicked OK"; `overrides` lets them say otherwise.
- **404** `IMAGE_NOT_FOUND`, `SUGGESTION_NOT_FOUND`. **409** `SUGGESTION_ALREADY_ACCEPTED` (`details` lists ids). **422** `TOO_MANY_ANNOTATIONS`, `VALIDATION_ERROR`.

Rejection alone: `POST /images/{image_id}/landmark-suggestions/reject` with `{suggestion_ids, reason}` → `200 {rejected: N}`. Rejections are kept and fed back as negative examples if a learned re-ranker is ever added.

---

## 15. Semantic features and segmentation

Router: `backend/app/api/v1/semantics.py` — `APIRouter(prefix="/images/{image_id}", tags=["semantics"])`.
Table: `semantic_features`.

### 15.1 `GET /images/{image_id}/semantic-features`

**Purpose:** the detected semantic layer — field borders, roads, buildings, canals — used to boost matching (`landmark_consistency_score`, `semantic_similarity_score`) and rendered as a canvas overlay.

- **Query:** `SemanticFeatureListParams` — `limit` (default 100), `offset`, `sort`, `semantic_class` (csv), `space` (`image_pixel` | `satellite_geo`), `score__gte`, `source` (csv), `job_id`, `match_result_id`, `format` (`json` | `geojson`), `simplify_px` (float, 0–50), `include_mask` (bool, default `false`).
- **Sort whitelist:** `score`, `area`, `created_at`. **Default:** `-score`.
- **200** → `Page[SemanticFeatureRead]`:

```jsonc
{ "id": "e8f9…", "image_id": "7f3a…", "job_id": "1c2d…",
  "semantic_class": "field_border",       // semantic_class enum, 13 values
  "space": "image_pixel",                 // feature_space enum
  "source": "classical_contour",          // sam | dinov2 | classical_contour | classical_hough
  "geometry": { "type": "Polygon", "coordinates": [[[100,200],[900,210],[905,880],[95,870],[100,200]]] },
  "geometry_crs": "image_pixel",          // image_pixel | EPSG:4326  — explicit, never inferred
  "area_px": 561240.0, "area_m2": null,
  "bbox_px": [95, 200, 905, 880],
  "vertex_count": 5,
  "score": 0.74,
  "mask": null,
  "attributes": { "mean_ndvi": null, "contour_arc_length": 3184.2 },
  "degraded": true,
  "warnings": [ { "code": "MODEL_WEIGHTS_MISSING", "message": "SAM weights absent; used classical contour segmentation.",
                  "field": "backend", "requested": "sam", "effective": "classical_contour" } ],
  "created_at": "…" }
```

Per the DDL's `ck_semantic_features_space_xor`, a feature lives in **exactly one** space: `image_pixel` (SRID 0, pixel coords, on the photograph) or `satellite_geo` (EPSG:4326, on the imagery). `geometry_crs` states which, in the payload, always. This is the same trap as §10.1 and gets the same treatment: two coordinate systems in one field, with an explicit discriminator rather than a convention someone has to remember.

`include_mask=true` adds `mask: { "encoding": "coco_rle", "size": [4000, 6000], "counts": "…" }` — COCO RLE, not a PNG data-URI. RLE for a 24 MP mask is a few KB and decodes with `pycocotools`/`numpy` in ~1 ms; a PNG data-URI is ~400 KB base64 per mask and 100 of them is a 40 MB response. Default `false`: the polygon is what the overlay renders.

`simplify_px` applies Douglas-Peucker server-side (`ST_SimplifyPreserveTopology`). A SAM mask vectorizes to thousands of vertices; the canvas needs dozens. Doing it server-side ships kilobytes instead of megabytes and keeps the topology valid.

- **200** with `format=geojson` → `GeoJsonFeatureCollection`. **Rejected with `422 PARAM_CONFLICT` unless `space` is also specified** — a FeatureCollection mixing pixel-space and geographic geometries is a malformed GeoJSON document that will land polygons off the coast of Africa if fed to Leaflet.
- **404** `IMAGE_NOT_FOUND`. Empty page when never segmented — a normal state, not a 404.

### 15.2 `POST /images/{image_id}/segment`

**Purpose:** run segmentation over the image (SAM when available, classical otherwise).

- **Body:** `SegmentRequest`

| Field | Type | Default | Notes |
|---|---|---|---|
| `backend` | enum | `auto` | `auto` \| `sam` \| `classical_contour` \| `classical_hough` |
| `mode` | enum | `everything` | `everything` \| `points` \| `boxes` \| `region` |
| `points` | `list[SegmentPoint] \| null` | `null` | `{x, y, label: 1\|0}` — SAM-style positive/negative prompts |
| `boxes` | `list[PixelBox] \| null` | `null` | `{x0,y0,x1,y1}` prompts |
| `region` | `GeoJsonPolygon \| null` | `null` | pixel-space restriction |
| `max_masks` | `int` | `50` | `1..500` |
| `min_area_px` | `float` | `500.0` | drop specks |
| `min_score` | `float` | `0.5` | `0..1` |
| `simplify_px` | `float` | `2.0` | vectorization tolerance |
| `classify` | `bool` | `true` | assign `semantic_class`; `false` → all `unknown` |
| `space` | enum | `image_pixel` | `image_pixel` \| `satellite_geo` (requires a selected match result → else `422 NO_SELECTED_MATCH_RESULT`) |
| `seed` | `int \| null` | `null` | |

**`backend: "auto"` (default) resolves at job start, in the worker**, not at request time: `sam` if `SAM_CHECKPOINT` exists and loads, else `classical_contour`. Resolution is reported in `warnings` within a second of `loading_model` (§5.5), and in `semantic_features.source` forever.

Requesting `backend: "sam"` explicitly on a weightless box **still returns 202**, then warns and falls back. It does not 422 or 503. This is the hard requirement: *a missing weight file must never crash the app — it must log and fall back to the classical path.* The client asked for a segmentation; it gets one.

The classical path is real, not a stub: bilateral filter → Canny (auto-thresholded by median) → morphological close → `findContours` (external + hierarchy) → `approxPolyDP` → area/score filter → heuristic classification (elongation + orientation → `road`/`crop_row`/`irrigation_canal`; rectangularity + size → `building`/`greenhouse`; large convex low-texture → `field_border`; HSV/ExG vegetation index → `vegetation`/`bare_soil`). Deterministic, no weights, ~300 ms on a 24 MP image.

- **202** → `JobRead` (`type: "segment"`). **404** `IMAGE_NOT_FOUND`. **409** `IMAGE_STILL_PROCESSING`, `SEGMENT_JOB_ALREADY_RUNNING`. **422** `VALIDATION_ERROR` (`mode=points` with no `points`, prompts outside bounds, `space=satellite_geo` with no selected match), **503** `WORKER_UNAVAILABLE`.

Prior features from the same `source` + `space` are replaced. `DELETE /images/{image_id}/semantic-features?source=&space=` → `200 {deleted: N}` clears the overlay.

---

## 16. Camera pose

Router: `backend/app/api/v1/pose.py` — `APIRouter(prefix="/images/{image_id}", tags=["pose"])`.
Table: `camera_poses`.

### 16.1 `GET /images/{image_id}/camera-pose`

**Purpose:** where the surveyor stood and which way they were pointing — the ground-level counterpart to the GCPs, and the thing that makes the heatmap interpretable.

- **Query:** `match_result_id: UUID | null` (default: selected), `method: PoseMethod | null` (default: best available by the precedence below).
- **200** → `CameraPoseRead`:

```jsonc
{
  "id": "f1a2…", "image_id": "7f3a…", "match_result_id": "cc11…",
  "method": "homography_decomposition",       // pose_method enum
  "position": { "lat": 41.889412, "lon": 12.422108, "altitude_m": 91.2, "altitude_source": "dem" },
  "orientation": { "yaw_deg": 143.2, "pitch_deg": -4.1, "roll_deg": 0.8,
                   "yaw_reference": "true_north", "yaw_convention": "clockwise_from_north" },
  "intrinsics": { "fx": 5833.3, "fy": 5833.3, "cx": 3000.0, "cy": 2000.0,
                  "k1": null, "k2": null, "k3": null, "p1": null, "p2": null,
                  "model": "pinhole_no_distortion",
                  "source": "exif_focal_and_sensor_width",
                  "confidence": "medium" },
  "confidence": 71.4,                          // 0-100
  "uncertainty": { "position_sigma_m": 8.3, "yaw_sigma_deg": 6.1,
                   "pitch_sigma_deg": 3.4, "roll_sigma_deg": 2.9,
                   "covariance_available": false },
  "reprojection_error_px": 2.41,
  "gcps_used": 12,
  "ambiguity": { "resolved": true,
                 "alternatives_considered": 4,
                 "resolution_rule": "Selected the solution with positive depth for all points and plane normal within 30 deg of gravity (from EXIF pitch prior).",
                 "runner_up_position": { "lat": 41.891803, "lon": 12.424511 } },
  "degraded": false,
  "warnings": [],
  "estimated_at": "…", "created_at": "…"
}
```

**Method precedence** (best available wins when `method` is unset):

| `method` | Inputs | Yields | Typical σ |
|---|---|---|---|
| `pnp` | ≥ 4 geo-located GCPs + intrinsics (`cv2.solvePnPRansac`) | full 6-DoF | 2–5 m |
| `homography_decomposition` | H + intrinsics (`cv2.decomposeHomographyMat`) | full 6-DoF, up to a 4-fold ambiguity | 5–15 m |
| `heatmap_argmax` | best heatmap cell | position only | grid-resolution |
| `exif_gps_only` | EXIF GPS (+ `GPSImgDirection` for yaw) | position, yaw maybe | 3–10 m |
| `manual` | operator-entered | as given | — |

- **404** `CAMERA_POSE_NOT_AVAILABLE` when no pose can be produced. `details.reason` ∈ `no_successful_match`, `insufficient_gcps`, `no_intrinsics`, `degenerate_geometry`, and `details.hint` says what to do (`"Run a match first"`, `"Camera intrinsics unknown: EXIF lacks FocalLength and the camera is not in the sensor database. Provide intrinsics via PATCH /images/{id}/camera-pose."`).

> **Why 404 and not 200-with-nulls.** A pose either exists or does not. `200 {"position": null, "orientation": null, "confidence": null}` forces every client to null-check five levels deep and tempts a chart into plotting `(0, 0)` — off the coast of Ghana, which is where bad geodata famously goes to die. A 404 with a machine-readable `reason` is unambiguous and lets React Query cache the absence correctly.

- **409** `MATCH_JOB_ALREADY_RUNNING` — pose is being re-estimated; `Retry-After: 2`.
- **404** `IMAGE_NOT_FOUND`, `MATCH_RESULT_NOT_FOUND`.

**On `intrinsics.source` and the honesty of `confidence`.** `fx`/`fy` come from EXIF `FocalLength` + a sensor-width lookup (`camera_db` keyed by make/model), and `sensor_width_mm` is *frequently absent or wrong*. `source` ∈ `calibrated` (a real calibration was supplied), `exif_focal_and_sensor_width`, `exif_35mm_equivalent` (derived from `FocalLength35mm`, less precise), `assumed_fov` (a 60° horizontal FOV guess when nothing else exists), `manual`. `confidence` ∈ `high | medium | low` tracks it. A pose from `assumed_fov` is a *guess with a plausible number attached*, and the payload says so rather than laundering it into an authoritative-looking decimal. `pose.confidence` (0–100) is scaled down accordingly, and `uncertainty.position_sigma_m` blows up to tens of metres — which is the correct, useful answer.

**The 4-fold ambiguity is surfaced, not hidden.** `cv2.decomposeHomographyMat` returns up to 4 physically valid solutions. The service disambiguates with cheirality (positive depth) plus a gravity prior from EXIF pitch, and reports the rule it used plus the runner-up. When `resolved: false`, `confidence` is capped at 40 and a `POSE_AMBIGUOUS` warning is attached. A pose that silently picks one of four possibilities and presents it as fact is how a surveyor ends up 200 m from where they stood.

### 16.2 `PATCH /images/{image_id}/camera-pose`

**Purpose:** supply known intrinsics (from a calibration) or a manual pose.

- **Body:** `CameraPoseUpdate` — `{ intrinsics?: CameraIntrinsicsInput, position?: LatLonAlt, orientation?: OrientationInput, note?: str, recompute?: bool = true }`.
- **200** → `CameraPoseRead` with `method: "manual"` (position/orientation given) or re-estimated with the supplied intrinsics (`recompute=true`).
- **404** `IMAGE_NOT_FOUND`. **422** `VALIDATION_ERROR` (`fx`/`fy` ≤ 0, principal point outside the image, yaw ∉ [0,360), pitch ∉ [-90,90], roll ∉ [-180,180]).

Supplying real intrinsics is the highest-leverage accuracy fix available: a calibrated `fx` typically halves `position_sigma_m` versus `exif_35mm_equivalent`.

---

## 17. Confidence heatmap

Router: `backend/app/api/v1/pose.py` (same module — a heatmap is a distribution over camera *positions*, so it shares the pose service and its dependencies).
Tables: `confidence_heatmaps`, `confidence_heatmap_cells`.

### 17.1 `GET /images/{image_id}/heatmap`

**Purpose:** candidate camera locations + scores — the "where might this photo have been taken?" layer. It is the honest picture of the search: not one answer, but a scored field over the AOI.

- **Query:**

| Param | Type | Default | Notes |
|---|---|---|---|
| `job_id` | `UUID \| null` | latest succeeded match | |
| `format` | enum | `json` | `json` \| `geojson` \| `png` |
| `resolution` | enum | `native` | `native` \| `coarse` (≤ 32×32, downsampled by max) |
| `min_score` | `float` | `0.0` | `0..100`; drop cells below |
| `top_n` | `int \| null` | `null` | return only the N best cells |
| `bbox` | bbox | `null` | clip |
| `colormap` | enum | `viridis` | `png` only: `viridis` \| `magma` \| `turbo` \| `grey` |
| `width` | `int` | `512` | `png` only, `64..2048` |
| `opacity` | `float` | `1.0` | `png` only, `0..1` |

- **200, `format=json`** → `HeatmapRead`:

```jsonc
{
  "id": "b2c3…", "image_id": "7f3a…", "match_job_id": "0a9c…",
  "provider": "esri_world_imagery",
  "bbox": [12.4102, 41.8801, 12.4351, 41.9004],
  "grid": { "rows": 24, "cols": 28, "cell_size_m": 92.4, "cell_size_deg": [0.00089, 0.00085],
            "crs": "EPSG:4326", "origin": "top_left", "cell_anchor": "center" },
  "score_range": { "min": 0.0, "max": 91.7, "mean": 12.4, "p95": 68.2 },
  "cells": [ { "row": 11, "col": 14, "lat": 41.8902, "lon": 12.4231,
               "score": 91.7, "rank": 1, "inlier_count": 214, "match_result_id": "cc11…" },
             { "row": 11, "col": 15, "lat": 41.8902, "lon": 12.4242,
               "score": 74.3, "rank": 2, "inlier_count": 168, "match_result_id": "dd44…" } ],
  "top_candidates": [ { "rank": 1, "lat": 41.8902, "lon": 12.4231, "score": 91.7,
                        "match_result_id": "cc11…", "distance_from_exif_m": 41.2 } ],
  "sparsity": { "cells_total": 672, "cells_scored": 214, "cells_returned": 214,
                "note": "Unscored cells were never evaluated (outside the AOI or pruned by the coarse-to-fine search); they are absent, not zero." },
  "unimodal": true,
  "peak_prominence": 0.62,
  "png_url": "/api/v1/images/7f3a…/heatmap?format=png",
  "created_at": "…"
}
```

Three deliberate choices:

- **Sparse cells, and it says so.** Only *evaluated* cells are present. `cells_scored < cells_total` is the normal case — a coarse-to-fine search prunes most of the grid, which is why the search finishes at all. An absent cell means "never looked", not "looked and found nothing"; rendering absence as score-0 blue paints confident negatives the pipeline never asserted. The `sparsity.note` ships in the payload because this is exactly the kind of thing a client gets wrong once and never notices.
- **`unimodal` + `peak_prominence`** answer "should I trust the top candidate?" cheaply. A bimodal heatmap with two 90-scoring peaks 2 km apart means the field looks like two fields, and the surveyor must choose — that is a materially different situation from one sharp peak, and it is invisible if you only read `top_candidates[0]`.
- **Both `row`/`col` and `lat`/`lon` per cell.** The grid indices let a client rebuild a dense array for a canvas/WebGL layer without recomputing the affine; the lat/lon lets Leaflet place a marker without any grid math. It costs 16 bytes per cell and removes a class of off-by-one-cell errors.

- **200, `format=geojson`** → `GeoJsonFeatureCollection` of cell **Polygons** (not points) with `properties: {score, rank, row, col, inlier_count}` — drops straight into a Leaflet choropleth.
- **200, `format=png`** → binary. Colormapped, transparent where unscored (`alpha=0` — the visual encoding of sparsity), `Cache-Control: private, max-age=86400`, `ETag`. Headers `X-Heatmap-BBox: minlon,minlat,maxlon,maxlat` and `X-Heatmap-Score-Range: 0,91.7` so a client can georeference and label the legend **without a second JSON call** — this is the fast path for `L.imageOverlay`, and it is the one the map actually uses at native resolution where the JSON is 600+ cells.
- **404** `HEATMAP_NOT_AVAILABLE` — job never produced one (`details.reason` ∈ `no_match_job`, `job_failed`, `heatmap_disabled`, `single_candidate`). `details.hint` explains: a single-tile AOI yields one cell, which is not a heatmap.
- **404** `IMAGE_NOT_FOUND`, `JOB_NOT_FOUND`. **409** `MATCH_JOB_ALREADY_RUNNING` — partial heatmaps are not served; `Retry-After: 2`.
- **422** `VALIDATION_ERROR`, `INVALID_BBOX`.

Heatmaps are written once by the match job and never mutated, so they cache hard (`ETag` over `id`, `immutable`).

---

## 18. Imagery

Router: `backend/app/api/v1/imagery.py` — `APIRouter(prefix="/imagery", tags=["imagery"])`.
Backed by the `ImageryProvider` registry (`40-imagery.md`). **No database table** — providers are a runtime registry, not persisted state.

### 18.1 `GET /imagery/providers`

**Purpose:** what can I actually use, and what must I display for it.

- **Query:** `configured_only: bool = false`, `check: bool = false` (run each provider's live `self_check()`; adds up to 2 s).
- **200** → `Page[ProviderInfo]` (a `Page` for uniformity — §1.5 — even though N ≈ 6):

```jsonc
{
  "name": "esri_world_imagery",
  "display_name": "Esri World Imagery",
  "configured": true,
  "keyless": true,
  "is_default": true,
  "enabled": true,
  "requires_env": [],
  "missing_env": [],
  "capabilities": { "tiles": true, "static": true, "wmts": false,
                    "min_zoom": 0, "max_zoom": 19, "tile_size_px": 256,
                    "formats": ["jpeg"], "supports_retina": false,
                    "crs": "EPSG:3857", "tile_scheme": "xyz" },
  "coverage": { "global": true, "bbox": [-180, -85.06, 180, 85.06], "note": "Resolution varies; sub-metre in most agricultural regions." },
  "attribution": { "text": "Esri, Maxar, Earthstar Geographics, and the GIS User Community",
                   "url": "https://www.esri.com/en-us/legal/terms/full-master-agreement",
                   "required": true, "logo_url": null },
  "tos": { "url": "…", "cache_max_age_s": 604800, "commercial_use": "restricted",
           "requires_opt_in": false, "note": "Cached tiles are purged after 7 days per terms." },
  "tile_url_template": "/api/v1/imagery/tiles/esri_world_imagery/{z}/{x}/{y}",
  "rate_limit": { "requests_per_second": 10, "burst": 20, "scope": "per_deployment" },
  "health": { "status": "up", "checked_at": "…", "latency_ms": 142.0 },
  "priority": 100
}
```

Keyed and unavailable providers appear too, so the UI can render them disabled with a reason:

```jsonc
{ "name": "mapbox_satellite", "display_name": "Mapbox Satellite",
  "configured": false, "keyless": false, "is_default": false, "enabled": true,
  "requires_env": ["MAPBOX_TOKEN"], "missing_env": ["MAPBOX_TOKEN"],
  "capabilities": { "tiles": true, "static": true, "min_zoom": 0, "max_zoom": 22,
                    "tile_size_px": 512, "formats": ["jpeg","png","webp"], "supports_retina": true, /* … */ },
  "health": { "status": "unconfigured", "checked_at": null, "latency_ms": null },
  "tile_url_template": null,
  "priority": 80 }
```

`tile_url_template` is **always our proxy path, never the upstream URL** — that is the whole design (§18.3). It is `null` when unconfigured, so a client cannot construct a request that is guaranteed to 503.

The **default is `esri_world_imagery`, keyless**, so a `docker compose up` with an empty `.env` is a working application. `local_orthophoto` is also keyless and works with no network at all — the offline/test path. `priority` orders the picker; `is_default` marks the one used when `provider` is omitted.

- **200 always.** Never 503: "which providers are configured" is answerable even when all of them are broken, and the answer is the diagnosis.

### 18.2 `GET /imagery/providers/{provider}`

- **Path:** `provider: ProviderName` (enum-validated → **`404 PROVIDER_UNKNOWN`** for anything else, with `details.available` listing the valid names).
- **Query:** `check: bool = true` (live `self_check()`).
- **200** → `ProviderInfo` with `health` populated.
- **404** `PROVIDER_UNKNOWN`.

> Note there is no `google_earth` value in `ProviderName`, and this endpoint therefore returns `404 PROVIDER_UNKNOWN` for it. Per the client's legal constraint, Google Earth imagery is out of scope; making it unrepresentable in the enum means the API cannot be asked for it, by anyone, ever — including by a future maintainer who did not read the constraint. `google_maps_static` is present but ships **disabled** (`enabled: false` unless `GOOGLE_MAPS_TOS_ACKNOWLEDGED=true` **and** `GOOGLE_MAPS_KEY` are both set), and returns `403 PROVIDER_TOS_FORBIDDEN` otherwise. Terms compliance there depends on the operator's own agreement, so the operator opts in explicitly and the system records that they did.

### 18.3 `GET /imagery/tiles/{provider}/{z}/{x}/{y}` — the tile proxy

**Purpose:** serve one XYZ tile to Leaflet, from any provider, through one URL shape.

- **Path:** `provider: ProviderName`, `z: int`, `x: int`, `y: int`.
- **Query:** `scale: 1|2 = 1` (retina, if `supports_retina`), `format: jpeg|png|webp|auto = auto`, `style: str|null` (provider-specific style id), `date: str|null` (`YYYY-MM-DD` or `YYYY-MM/YYYY-MM`, Sentinel/Copernicus time selection).
- **200** → binary tile.
  - `Content-Type: image/jpeg|png|webp`
  - `Cache-Control: public, max-age=86400, stale-while-revalidate=604800` — clamped to the provider's `tos.cache_max_age_s`; never exceeds what the terms allow.
  - `ETag` (upstream's, or SHA-256 of the bytes), `X-Imagery-Attribution`, `X-Imagery-Provider`, `X-Cache: HIT|MISS|REVALIDATED`.
- **204 No Content** — provider has no coverage at this tile (ocean, out-of-footprint `local_orthophoto`). **Not 404**: the tile *address* is valid, there is simply no imagery. Leaflet renders empty space. A 404 makes Leaflet log an error per tile and, in some configs, retry — a 204 is the accurate and quiet answer.
- **304** — `If-None-Match` matched.
- **404** `PROVIDER_UNKNOWN`; `TILE_OUT_OF_RANGE` if `z`/`x`/`y` are outside the scheme (`x`,`y` ∈ `[0, 2^z)`, `z` ∈ provider range) — a malformed *address*, distinct from valid-but-empty.
- **403** `PROVIDER_TOS_FORBIDDEN` — provider disabled by policy.
- **429** `PROVIDER_RATE_LIMITED` / `RATE_LIMIT_EXCEEDED` — upstream or our bucket; `Retry-After` set.
- **502** `PROVIDER_UPSTREAM_ERROR` — upstream 5xx/timeout/non-image body after retries.
- **503** `PROVIDER_NOT_CONFIGURED` — keyed provider, no key. `details.missing_env` names it.
- **422** `VALIDATION_ERROR` — bad `scale`/`format`/`date`.

Two-tier cache: Redis (hot, 24 h, `tile:{provider}:{z}:{x}:{y}:{scale}:{style}:{date}`) → disk (`/data/cache/tiles/...`, LRU, `TILE_CACHE_MAX_BYTES` default 20 GB) → upstream. A cache **hit never touches the network** and serves in ~2 ms. Crucially, the **match worker reads the same cache**, so panning the map over a field pre-warms the exact tiles the subsequent match needs.

#### Why the proxy exists — the justification

This is the single most important architectural decision in the imagery layer, and it is not primarily about performance.

1. **API keys never reach the browser.** This is the load-bearing reason. If the frontend hit `api.mapbox.com/...?access_token=pk.eyJ1...` directly, the token would be in the JS bundle, in devtools' Network tab, in the browser history, in any user's HAR export, and in every CDN log. Mapbox/Bing tokens are billable — a leaked token is someone else's satellite imagery bill on your card, and URL-referrer restrictions are trivially forged with `curl -H "Referer:"`. There is **no way** to call a keyed tile API from a browser without exposing the key. The proxy is not a hardening measure; it is the only correct topology. Keys live in the API container's env, are read by the provider adapter, and are never serialized into any response — including error messages, which are scrubbed for `token`/`key`/`secret` patterns before leaving §4.4.

2. **One URL shape for every provider — the interchangeability requirement made real.** The client's constraint is that swapping providers must not change the matching algorithm, and the UX must stay a 2D satellite view. Every provider gets `/api/v1/imagery/tiles/{provider}/{z}/{x}/{y}`. Behind it, Esri is XYZ, Bing is a quadkey (`z/x/y` → `qk` conversion), Sentinel is a WMTS `GetTile` with a time dimension, `local_orthophoto` is a GDAL window read + reproject from an arbitrary UTM zone with **no upstream at all**. Leaflet knows about none of this. Swapping the provider is one string in one config. Without the proxy, the frontend would carry a per-provider URL-template branch, a per-provider auth scheme, and a quadkey implementation in TypeScript — and `local_orthophoto` would be *impossible*, because a browser cannot window-read a 40 GB GeoTIFF off the server's disk.

3. **Provider ToS are enforceable in exactly one place.** Cache lifetimes, attribution, opt-in gating, request ceilings — all live in the adapter. A browser hitting upstream directly can be told to respect a 7-day cache limit; it cannot be *made* to. With the proxy, `tos.cache_max_age_s` clamps the `Cache-Control` we emit and the retention of what we store, and the ToS-gated `google_maps_static` provider simply cannot be reached without the operator's recorded opt-in. For a product whose founding constraint is a legal one about imagery sourcing, "compliance is enforced at a single chokepoint" is worth more than the latency it costs.

4. **Quota and cost control.** Keyed providers bill per request and rate-limit per key. A React `<TileLayer>` on a fast pan issues hundreds of requests per second from N browsers against one shared key — the key gets 429'd or the bill explodes, and neither is visible to the operator. The proxy applies a token bucket per provider (`rate_limit.scope: per_deployment`), coalesces concurrent identical requests (single-flight), and serves the shared cache across *all* users and *all* match jobs. A second surveyor opening the same field pays zero upstream requests.

5. **The same bytes are matched and displayed.** The worker and the browser read one cache. Without it, the surveyor could be looking at a freshly-updated tile while the matcher scored a cached one from last week, and the projected GCP would sit visibly off the feature it matched — an unreproducible, unfalsifiable bug report. Shared cache makes `satellite_checksum` on `match_results` meaningful: the exact bytes that produced the homography are the exact bytes on screen.

6. **CORS, and offline tests.** Not every provider sends `Access-Control-Allow-Origin`; same-origin tiles sidestep this entirely, along with mixed-content and referrer-policy issues. And because everything funnels through one interface, the test suite registers a `fixture` provider that serves deterministic generated tiles from disk — **the whole app, including matching, runs and is tested with no network, no keys, and no weights**, which is precisely what the environment constraints demand.

The costs are real and accepted: a proxy hop (~2 ms on cache hit, dominated by upstream on miss), bandwidth through our container, and cache storage. For a keyed, ToS-bound, legally-constrained imagery product, this is not close.

### 18.4 `GET /imagery/static`

**Purpose:** bbox → one stitched image. Used by the PDF exporter, the match worker's mosaic builder, report thumbnails, and any client that wants a picture rather than a tile grid.

- **Query:**

| Param | Type | Req | Rules |
|---|---|---|---|
| `bbox` | `minlon,minlat,maxlon,maxlat` | **yes*** | valid, ≤ 25 deg², no antimeridian |
| `provider` | `ProviderName` | no | default provider |
| `zoom` | `int` | no | derived from bbox+size if omitted |
| `width` / `height` | `int` | no | `64..8192`; if one is given the other is derived from the bbox aspect |
| `center` + `radius_m` | | **yes*** | alternative to `bbox` |
| `format` | enum | no | `png` \| `jpeg` \| `webp` \| **`geotiff`**; default `png` |
| `scale` | `1\|2` | no | retina |
| `date` | str | no | Sentinel time selection |
| `attribution` | `bool` | no | default `true` — burn the attribution string into the bottom-left |
| `crs` | enum | no | `EPSG:3857` (default) \| `EPSG:4326` |

\* exactly one of `bbox` or (`center`+`radius_m`) → else `422 PARAM_CONFLICT`.

- **200** → binary.
  - `format=geotiff` → a **georeferenced** GeoTIFF (CRS + geotransform embedded, `COMPRESS=DEFLATE`, tiled, with overviews). This is what makes the endpoint useful to GIS: the surveyor drops it into QGIS and it lands in the right place. It is also how `local_orthophoto` round-trips losslessly.
  - Headers: `X-Imagery-Attribution`, `X-Imagery-Provider`, `X-Imagery-BBox`, `X-Imagery-Zoom`, `X-Imagery-Tiles-Used`, `ETag`, `Cache-Control: public, max-age=86400` (ToS-clamped).
- **422** `STATIC_IMAGE_TOO_LARGE` — `width*height > MAX_STATIC_PIXELS` (64 MP) or tiles needed > `MAX_STATIC_TILES` (256). `details` = `{"requested_pixels": …, "max_pixels": 67108864, "estimated_tiles": 900, "max_tiles": 256, "suggested_zoom": 16}` — the client is told exactly how to succeed rather than being told no.
- **422** `INVALID_BBOX`, `BBOX_CROSSES_ANTIMERIDIAN`, `ZOOM_OUT_OF_RANGE`, `PARAM_CONFLICT`.
- **204** — no coverage anywhere in the bbox.
- **404** `PROVIDER_UNKNOWN`. **403** `PROVIDER_TOS_FORBIDDEN`. **429**. **502** `PROVIDER_UPSTREAM_ERROR` — > 20 % of tiles unfetchable after retries (below that, missing tiles are filled transparent and reported in `X-Imagery-Tiles-Missing`; a mosaic with 3 % holes is still useful, one with 40 % is a lie).
- **503** `PROVIDER_NOT_CONFIGURED`.

**Synchronous, and bounded to stay that way.** A 64 MP cap over ≤ 256 cached tiles stitches in ~1–3 s. The caps are what keep this out of Celery: an unbounded `bbox=-180,-90,180,90&zoom=19` would be a 400-billion-tile request, which is why the limits are hard failures rather than clamps. Anything larger is a *match job*, which is async and has a job handle.

The tile fetches underneath go through the same two-tier cache as §18.3, so a static image over an already-browsed area costs zero upstream requests.

---

## 19. Batch

Router: `backend/app/api/v1/batch.py` — `APIRouter(prefix="/batch", tags=["batch"])`.
Tables: `batch_jobs`, `batch_job_items`.

### 19.1 `POST /batch`

**Purpose:** run one operation over many images. Two entry modes on one path.

**Mode A — multipart (upload + process):**
- `Content-Type: multipart/form-data`
- `files`: repeated file parts (1–100)
- `project_id`: UUID (required)
- `operation`: `match` | `suggest_landmarks` | `segment` | `export` | `ingest_only`
- `config`: JSON string — the operation's request body (`MatchRequest` / `SuggestLandmarksRequest` / `SegmentRequest` / `ExportRequest`), applied to every image
- `on_error`: `continue` (default) | `abort`

**Mode B — JSON (process existing):**
- `Content-Type: application/json`
- Body: `BatchCreate`

```jsonc
{
  "project_id": "1b2c…",
  "image_ids": ["7f3a…", "8g4b…"],          // OR "image_filter"
  "image_filter": null,                      // { "status": "ready", "has_gps": true, "created_at__gte": "…" }
  "operation": "match",
  "config": { /* MatchRequest, minus image-specific fields */ },
  "on_error": "continue",
  "concurrency": null,                       // null → server default (worker pool size)
  "priority": "normal",                      // low | normal | high
  "label": "Block 4 spring re-survey",
  "idempotency_scope": "batch"
}
```

Exactly one of `image_ids` / `image_filter` → else `422 PARAM_CONFLICT`. `image_filter` resolves at submit time (not at execution) and the resolved id list is frozen onto the batch — otherwise a batch's membership would change under it as uploads land mid-run, and "did it process everything?" would have no answer.

- **202** → `BatchRead`. `Location: /api/v1/batch/{id}`, `Retry-After: 2`.
- **413** `BATCH_TOO_LARGE` — > 100 files, > `MAX_BATCH_BYTES` (2 GB aggregate), or > 500 `image_ids`.
- **415** `UNSUPPORTED_IMAGE_FORMAT` — `details` names the offending part; **the whole batch is rejected** in `abort` mode, or the item is marked failed in `continue` mode.
- **422** `VALIDATION_ERROR`, `PARAM_CONFLICT`, `EMPTY_BATCH` (filter matched zero images — near-certainly a mistake worth surfacing now, not as a batch that instantly "succeeds" over nothing).
- **404** `PROJECT_NOT_FOUND`, `IMAGE_NOT_FOUND` (any listed id; `details` names all missing ids, not just the first).
- **503** `WORKER_UNAVAILABLE`, `INSUFFICIENT_STORAGE`.

**Fan-out.** The parent `batch_jobs` row is created with one `batch_job_items` row per image, then a Celery **chord** dispatches children (each a normal `match_jobs`/`exports` row with `batch_job_item_id` set) with a callback that aggregates. Children are ordinary jobs: they appear in `GET /jobs?batch_id=…`, poll identically, and cancel individually. There is **no separate batch execution engine** — a batch is a fan-out plus a rollup, and building it any other way means two implementations of every operation.

`config` is validated **once, up front**, against the operation's real request model. A batch of 100 images that dies on item 1 because of a typo'd `zoom_levels` has wasted the surveyor's afternoon; validation is cheap and immediate.

`priority` maps to Celery queues (`low`/`default`/`high`). A batch defaults to `normal` but is **soft-yielding**: interactive single-image matches go to `high` by default, so one surveyor's 100-image overnight batch never starves another's live click.

### 19.2 `GET /batch`

- **Query:** `BatchListParams` — `limit`, `offset`, `sort`, `project_id`, `status` (csv), `operation` (csv), `active` (bool), `created_at__gte/lte`, `q` (over `label`).
- **Sort whitelist:** `created_at`, `updated_at`, `finished_at`, `progress_percent`. **Default:** `-created_at`.
- **200** → `Page[BatchSummary]` = `id, label, project_id, operation, status, counts, progress_percent, created_at, finished_at, duration_ms`.

### 19.3 `GET /batch/{batch_id}`

- **Query:** `include_items: bool = true`, `item_status` (csv filter), `item_limit: int = 200`, `item_offset: int = 0`.
- **200** → `BatchRead`:

```jsonc
{
  "id": "c3d4…", "label": "Block 4 spring re-survey", "project_id": "1b2c…",
  "operation": "match", "status": "running",
  "on_error": "continue", "priority": "normal",
  "config": { /* frozen resolved config */ },
  "counts": { "total": 100, "pending": 0, "queued": 42, "running": 8,
              "succeeded": 47, "failed": 2, "cancelled": 1, "retrying": 0 },
  "progress": { "percent": 51.3, "stage": "waiting_children",
                "message": "50/100 complete (47 succeeded, 2 failed, 1 cancelled)",
                "current": 50, "total": 100, "eta_seconds": 1840 },
  "rollup": { "gcps_created": 512, "mean_confidence": 78.4, "median_confidence": 82.1,
              "images_with_no_match": 3, "degraded_count": 47 },
  "items": [
    { "id": "i1…", "image_id": "7f3a…", "filename": "IMG_4471.JPG", "job_id": "0a9c…",
      "status": "succeeded", "result_ref": { "kind": "match_result", "id": "cc11…" },
      "result_url": "/api/v1/match-results/cc11…",
      "confidence": 87.3, "gcp_count": 12, "error": null,
      "started_at": "…", "finished_at": "…", "duration_ms": 41200 },
    { "id": "i2…", "image_id": "8g4b…", "filename": "IMG_4472.JPG", "job_id": "0b2d…",
      "status": "failed", "result_ref": null, "result_url": null,
      "confidence": null, "gcp_count": 0,
      "error": { "code": "SEARCH_HINT_REQUIRED", "message": "No EXIF GPS, no project AOI, and no center supplied.",
                 "status": 422, "details": null, "request_id": "…", "timestamp": "…", "docs_url": "…" },
      "started_at": "…", "finished_at": "…", "duration_ms": 120 }
  ],
  "items_page": { "total": 100, "limit": 200, "offset": 0, "has_more": false },
  "warnings": [ { "code": "MODEL_WEIGHTS_MISSING", "message": "47 of 55 completed items fell back to the classical matcher.",
                  "field": "matcher", "requested": "superglue", "effective": "flann" } ],
  "created_at": "…", "started_at": "…", "finished_at": null, "duration_ms": null
}
```

- `status` is the **parent** status. Terminal `succeeded` means *the batch ran to completion*, even with failed children — `counts.failed > 0` carries that. The parent is `failed` only if the fan-out itself broke (config invalid at dispatch, broker down) or `on_error=abort` tripped. A batch of 100 where 2 images had no GPS did its job; reporting it as `failed` would hide the 98 good results behind a red banner.
- `rollup` is the point of the whole endpoint — after a 100-image overnight run the surveyor wants "512 GCPs, mean confidence 78, 3 images found nothing", not 100 rows to read.
- `warnings` are **aggregated** across children (deduped by `code` + `requested` + `effective`, counted). 47 identical weight warnings is one line.
- **404** `BATCH_NOT_FOUND`. **422** bad params.

### 19.4 `DELETE /batch/{batch_id}`

- **Query:** `hard: bool = false` (delete the record; only allowed when terminal).
- **202** → `BatchRead` with `status: "running"`, `cancel_requested: true` — cancels every non-terminal child (§5.6). Already-`succeeded` children **keep their results**: a batch cancel means "stop doing more work", not "undo what's done". `Retry-After: 1`.
- **200** → `BatchRead` (`status: "cancelled"`) when nothing was running.
- **409** `BATCH_NOT_CANCELLABLE` — already terminal and `hard=false`.
- **404** `BATCH_NOT_FOUND`.

---

## 20. Exports

Router: `backend/app/api/v1/exports.py` — `router_image = APIRouter(prefix="/images/{image_id}", tags=["exports"])`, `router_project = APIRouter(prefix="/projects/{project_id}", tags=["exports"])`, `router_flat = APIRouter(prefix="/exports", tags=["exports"])`.
Table: `exports`.

### 20.1 `POST /images/{image_id}/export`

**Purpose:** produce the deliverable.

- **Query:** `format: csv|geojson|shapefile|kml|kmz|pdf|gpkg|dxf` — **required**.

> Format is a query param because the assignment specifies `?format=`, and it reads well. It is also mirrored in `ExportRequest.format` as optional; if both are given and disagree → **`422 PARAM_CONFLICT`**. The query param wins when the body omits it. This is a small inconsistency accepted for interface compatibility, and it is resolved explicitly rather than by precedence-guessing.

- **Body:** `ExportRequest` (optional — an empty body exports the selected match's included GCPs as-is)

```jsonc
{
  "match_result_id": null,               // null → selected
  "target_srid": 4326,
  "filter": { "min_confidence": 70.0, "included_only": true,
              "manually_adjusted_only": false, "gcp_ids": null, "exclude_stale": true },
  "options": {
    "decimals": 8,
    "include_satellite_image": true,
    "include_thumbnails": true,
    "include_annotations": true,
    "include_heatmap": false,
    "include_metadata_sheet": true,
    "coordinate_order": "lat_lon",
    "csv_delimiter": ",", "csv_encoding": "utf-8-sig", "csv_include_header": true,
    "shapefile_encoding": "UTF-8",
    "kml_style": "pin", "kml_include_photo_overlay": true,
    "pdf_template": "survey_a4", "pdf_page_size": "A4", "pdf_dpi": 200,
    "pdf_include_map": true, "pdf_include_signature_block": true,
    "dxf_version": "R2010", "dxf_layer": "GCP"
  },
  "filename": null,
  "expires_in_s": 604800
}
```

| Field | Rules |
|---|---|
| `target_srid` | `1024..32767` (DDL CHECK). Must be a CRS `pyproj` knows → else `422 UNKNOWN_SRID`. **Reprojection happens here, at export, never on stored geometry.** |
| `filter.min_confidence` | `0..100` |
| `filter.exclude_stale` | default `true` — a stale GCP (§13.1) is one whose provenance changed; exporting it silently into a survey deliverable is the failure mode this whole design guards against |
| `options.decimals` | `0..12`, default `8` (~1 mm at the equator; 6 is ~0.1 m and lossy for RTK work) |
| `options.coordinate_order` | `lat_lon` (default, CSV/KML human convention) \| `lon_lat`. **GeoJSON always emits `[lon, lat]` regardless** — RFC 7946 is not negotiable, and this option is ignored there with a `COORDINATE_ORDER_IGNORED` warning if set. |
| `expires_in_s` | `3600..2592000`, default 7 days |

**Per-format behavior:**

| Format | Produces | Notes |
|---|---|---|
| `csv` | single `.csv` | `utf-8-sig` default — Excel renders UTF-8 as mojibake without a BOM, and surveyors open these in Excel. Columns: `code,lat,lon,elevation_m,confidence,image_x,image_y,satellite_x,satellite_y,label,kind,manually_adjusted,adjustment_offset_m,adjusted_by,adjusted_at,residual_px,horizontal_accuracy_m,image_filename,match_result_id,provider,crs`. |
| `geojson` | single `.geojson` | FeatureCollection, `[lon,lat]`, `bbox`. Non-4326 `target_srid` → RFC 7946 requires CRS84; a projected SRID emits a `crs` member (pre-2016 style) **and** a `GEOJSON_NON_STANDARD_CRS` warning. |
| `shapefile` | **`.zip`** | Always zipped: a shapefile is 4+ sidecar files (`.shp/.shx/.dbf/.prj/.cpg`) and delivering one of them is meaningless. `.dbf` field names are truncated to **10 chars** (DBF limit) via a documented deterministic map, emitted in `field_mapping.txt` inside the zip, with a `SHAPEFILE_FIELD_TRUNCATED` warning. `.prj` written from `target_srid`. |
| `kml` / `kmz` | `.kml` / `.kmz` | KML is **always EPSG:4326** — the spec permits nothing else. A non-4326 `target_srid` → `422 KML_REQUIRES_WGS84`. `kmz` bundles the satellite image as a `GroundOverlay` when `include_satellite_image`. |
| `gpkg` | `.gpkg` | GeoPackage; one layer `gcps`, plus `annotations` when `include_annotations`. The best format here and the one to recommend — no field-name limits, real types, one file. |
| `dxf` | `.dxf` | CAD hand-off. Points on layer `GCP` with `code` as TEXT. **Projected `target_srid` strongly advised** — DXF is unitless Cartesian, and degrees in a CAD drawing are nonsense at any scale. Emits `DXF_GEOGRAPHIC_CRS` warning if `target_srid` is geographic. |
| `pdf` | `.pdf` | Report: title block, project/image metadata, satellite image with numbered GCP markers, the annotated photo, the GCP table, per-point confidence, attribution (**required** — §12.7), generation timestamp, `request_id`, optional signature block. |

- **202** → `JobRead` (`type: "export"`, `result_ref: {kind: "export", id}`). `Location: /api/v1/exports/{export_id}`, `Retry-After: 1`.
- **404** `IMAGE_NOT_FOUND`, `MATCH_RESULT_NOT_FOUND`.
- **422** `NO_GCPS_TO_EXPORT` — the filter matched zero. An empty shapefile is a support ticket; `details` reports `{"total_gcps": 12, "excluded_by": {"min_confidence": 8, "stale": 4}}` so the surveyor can see *why* and relax the filter.
- **422** `UNKNOWN_SRID`, `KML_REQUIRES_WGS84`, `PARAM_CONFLICT`, `VALIDATION_ERROR`.
- **409** `IMAGE_STILL_PROCESSING`, `MATCH_JOB_ALREADY_RUNNING` (exporting mid-match would capture a half-derived GCP set).
- **503** `WORKER_UNAVAILABLE`, `INSUFFICIENT_STORAGE`.

Exports are async even for a 12-row CSV. Not because the CSV is slow — but `pdf` renders a map, `shapefile` shells out to GDAL, `kmz` embeds imagery, and all four share one code path, one status model, one retention policy, and one download endpoint. A synchronous fast path for CSV would double the surface to save 400 ms on the least-used format, and the client already has a job poller.

### 20.2 `POST /projects/{project_id}/export`

Same body/query. Additional `filter.image_ids` (`null` → all images with a selected match). `exports.image_id` is `NULL` for these (per DDL).

- **202** → `JobRead`. **422** `NO_GCPS_TO_EXPORT`. **404** `PROJECT_NOT_FOUND`.

`csv`/`geojson`/`gpkg` merge all images into one layer with an `image_filename` column. `shapefile` merges into one `.shp`. `pdf` paginates one section per image with a summary sheet. `kmz` groups per image as folders.

### 20.3 `GET /exports`

- **Query:** `ExportListParams` — `limit`, `offset`, `sort`, `project_id`, `image_id`, `format` (csv), `status` (csv), `include_expired` (default `false`), `created_at__gte/lte`.
- **Sort whitelist:** `created_at`, `size_bytes`, `expires_at`. **Default:** `-created_at`.
- **200** → `Page[ExportSummary]`.

### 20.4 `GET /exports/{export_id}`

- **200** → `ExportRead`:

```jsonc
{
  "id": "ee55…", "project_id": "1b2c…", "image_id": "7f3a…",
  "format": "shapefile", "status": "succeeded",
  "filename": "north-parcel_IMG_4471_gcps_epsg4326_20260717.zip",
  "size_bytes": 48213, "checksum_sha256": "c9d0…",
  "gcp_count": 12, "target_srid": 4326,
  "options": { /* echoed */ }, "filter": { /* echoed */ },
  "download_url": "/api/v1/exports/ee55…/download",
  "expires_at": "2026-07-24T09:41:22Z", "expires_in_s": 604233,
  "is_expired": false,
  "requested_by": "alice",
  "job_id": "0c1d…",
  "error_message": null,
  "warnings": [ { "code": "SHAPEFILE_FIELD_TRUNCATED",
                  "message": "3 field names exceeded the 10-character DBF limit and were truncated. See field_mapping.txt in the archive.",
                  "field": "options.shapefile_encoding", "requested": null, "effective": null } ],
  "created_at": "…", "updated_at": "…"
}
```

- `download_url` is `null` until `succeeded` (DDL: `ck_exports_succeeded_has_path`).
- `filename` is deterministic and informative: `{project-slug}_{image-slug}_gcps_epsg{srid}_{yyyymmdd}.{ext}`. A surveyor with 40 exports in `~/Downloads` can tell them apart.
- **404** `EXPORT_NOT_FOUND`.

### 20.5 `GET /exports/{export_id}/download`

- **Query:** `inline: bool = false` (PDF preview in-browser vs. attachment).
- **200** → binary.
  - `Content-Type`: `text/csv` / `application/geo+json` / `application/zip` / `application/vnd.google-earth.kml+xml` / `application/vnd.google-earth.kmz` / `application/geopackage+sqlite3` / `image/vnd.dxf` / `application/pdf`.
  - `Content-Disposition: attachment; filename="…"; filename*=UTF-8''…` (RFC 5987).
  - `Content-Length`, `ETag: "<checksum_sha256>"` (strong), `Accept-Ranges: bytes`, `Cache-Control: private, max-age=3600`, `X-Checksum-SHA256`, `X-GCP-Count`.
- **206** — `Range` honored.
- **409** `EXPORT_NOT_READY` — status not `succeeded`. `details.status` + `Retry-After: 2`. **Not a 404**: the resource exists, it is not finished, and the difference tells the client to keep polling rather than give up.
- **410** `EXPORT_EXPIRED` — past `expires_at`, artifact GC'd. `details.hint` says to re-export; `details.original_request` echoes the config so the client can one-click reproduce it.
- **404** `EXPORT_NOT_FOUND`. **500** `STORAGE_ERROR` — row says `succeeded`, bytes are gone (disk failure); alerts.

Downloads are counted (`download_count`, `last_downloaded_at`) — GC prefers never-downloaded artifacts, and "was the deliverable actually collected?" is a question worth answering. Served via `X-Accel-Redirect` when `USE_SENDFILE=true`.

### 20.6 `DELETE /exports/{export_id}`

- **204** — record deleted, artifact GC'd. Idempotent (already-deleted → `204`).
- **409** `EXPORT_NOT_CANCELLABLE` — non-terminal; cancel the job first via `DELETE /jobs/{job_id}`.
- **404** `EXPORT_NOT_FOUND`.

---

## 21. Router file layout

```
backend/app/api/
├── __init__.py
├── deps.py                     # shared dependencies (not a router)
├── errors.py                   # exception handlers + envelope translation
├── middleware.py               # RequestId, Timing, RateLimit, BodySizeLimit
└── v1/
    ├── __init__.py
    ├── router.py               # APIRouter(prefix="/api/v1") — the ONLY place the prefix appears
    ├── health.py
    ├── capabilities.py
    ├── projects.py
    ├── images.py
    ├── annotations.py
    ├── revisions.py
    ├── matching.py
    ├── jobs.py
    ├── gcps.py
    ├── suggestions.py
    ├── semantics.py
    ├── pose.py
    ├── imagery.py
    ├── batch.py
    └── exports.py
```

| File | `APIRouter` instances | prefix | tags | Endpoints |
|---|---|---|---|---|
| `health.py` | `router` | *(none)* | `["health"]` | 1, 2 |
| `capabilities.py` | `router` | *(none)* | `["capabilities"]` | 3 |
| `projects.py` | `router` | `/projects` | `["projects"]` | 4–8 |
| `images.py` | `router` | `/images` | `["images"]` | 9–15 |
| `annotations.py` | `router_nested` | `/images/{image_id}/annotations` | `["annotations"]` | 16–19 |
| | `router_flat` | `/annotations` | `["annotations"]` | 20–22 |
| `revisions.py` | `router_project` | `/projects/{project_id}/revisions` | `["revisions"]` | 23, 24 |
| | `router_flat` | `/revisions` | `["revisions"]` | 25, 26 |
| | `router_versions` | *(none)* | `["revisions"]` | 27–29 |
| `matching.py` | `router_image` | `/images/{image_id}` | `["matching"]` | 30 |
| | `router_results` | `/match-results` | `["matching"]` | 35–37 |
| | *(34 lives on `router_image`)* | | | 34 |
| `jobs.py` | `router` | `/jobs` | `["jobs"]` | 31–33 |
| `gcps.py` | `router_image` | `/images/{image_id}/gcps` | `["gcps"]` | 38, 42 |
| | `router_flat` | `/gcps` | `["gcps"]` | 39–41 |
| `suggestions.py` | `router` | `/images/{image_id}` | `["suggestions"]` | 43–45 |
| `semantics.py` | `router` | `/images/{image_id}` | `["semantics"]` | 46, 47 |
| `pose.py` | `router` | `/images/{image_id}` | `["pose"]`, `["heatmap"]` | 48, 49 |
| `imagery.py` | `router` | `/imagery` | `["imagery"]` | 50–53 |
| `batch.py` | `router` | `/batch` | `["batch"]` | 54–57 |
| `exports.py` | `router_image` | `/images/{image_id}` | `["exports"]` | 58 |
| | `router_project` | `/projects/{project_id}` | `["exports"]` | 59 |
| | `router_flat` | `/exports` | `["exports"]` | 60–63 |

**Why several modules export more than one router.** Resources here are naturally addressed two ways: nested for collection operations scoped to a parent (`/images/{id}/annotations`), flat for item operations on a globally-unique id (`/annotations/{id}`). Nesting the item routes as `/images/{image_id}/annotations/{annotation_id}` would force every client holding an annotation id to also carry its image id, and would make `PATCH` on a point require two path params to identify one row. Splitting by *module* instead — an `annotations_nested.py` and an `annotations_flat.py` — would scatter one resource's logic across two files. So: **one module per resource, one `APIRouter` per prefix.** Grouping is by domain concept, not by URL shape.

`router.py` composition, and the **order matters**:

```python
api_router = APIRouter(prefix="/api/v1")

api_router.include_router(health.router)
api_router.include_router(capabilities.router)
api_router.include_router(projects.router)
api_router.include_router(images.router)
api_router.include_router(annotations.router_nested)
api_router.include_router(annotations.router_flat)
api_router.include_router(revisions.router_project)
api_router.include_router(revisions.router_flat)
api_router.include_router(revisions.router_versions)
api_router.include_router(matching.router_image)
api_router.include_router(matching.router_results)
api_router.include_router(jobs.router)
api_router.include_router(gcps.router_image)      # BEFORE gcps.router_flat
api_router.include_router(gcps.router_flat)
api_router.include_router(suggestions.router)
api_router.include_router(semantics.router)
api_router.include_router(pose.router)
api_router.include_router(imagery.router)
api_router.include_router(batch.router)
api_router.include_router(exports.router_image)
api_router.include_router(exports.router_project)
api_router.include_router(exports.router_flat)
```

Starlette matches routes in registration order. Concretely: `/images/{image_id}/gcps/recompute` must be registered before any `/{...}` catch-all on the same prefix, and `/imagery/providers/{provider}` must not be shadowed by a hypothetical `/imagery/{something}`. The layout above has no literal-vs-parameter collisions, and a startup assertion in `router.py` walks `app.routes` and fails fast on any duplicate `(method, path)` — a duplicate route silently shadows in FastAPI and is otherwise found in production.

### 21.1 `deps.py` — shared dependencies

```python
async def get_db() -> AsyncIterator[AsyncSession]: ...
def     get_settings() -> Settings: ...
async def get_principal(request: Request) -> Principal: ...          # auth; anonymous when disabled
def     get_pagination(limit: int = Query(50, ge=1, le=200),
                       offset: int = Query(0, ge=0)) -> PaginationParams: ...
def     get_sorting(sort: str | None = Query(None)) -> SortParams: ...
async def get_project(project_id: UUID, db=Depends(get_db)) -> Project: ...          # 404s
async def get_image(image_id: UUID, db=Depends(get_db)) -> Image: ...                # 404s
async def get_annotation(annotation_id: UUID, db=Depends(get_db)) -> Annotation: ...
async def get_gcp(gcp_id: UUID, db=Depends(get_db)) -> Gcp: ...
async def get_job(job_id: UUID, db=Depends(get_db)) -> JobView: ...
async def get_export(export_id: UUID, db=Depends(get_db)) -> Export: ...
async def get_provider(provider: ProviderName) -> ImageryProvider: ...               # 404/503s
def     get_imagery_registry() -> ImageryRegistry: ...
def     get_celery() -> Celery: ...
async def require_worker() -> None: ...                                              # 503 WORKER_UNAVAILABLE
def     require_if_match(request: Request) -> str: ...                               # 428 when absent
def     require_confirm_delete(resource_id: UUID, request: Request) -> None: ...     # 428
async def get_idempotency(request: Request) -> IdempotencyContext: ...
```

`get_image`/`get_project`/etc. raise `NotFoundError` themselves, so no route body repeats the existence check, and the 404 is guaranteed to precede any body validation.

### 21.2 Middleware order (outermost → innermost)

1. `RequestIdMiddleware` — mint/propagate ULID; bind to logging context; emit `X-Request-ID`. Outermost so *every* response, including rejections below, carries one.
2. `CORSMiddleware`.
3. `TimingMiddleware` — `X-Response-Time-ms`, Prometheus histogram.
4. `BodySizeLimitMiddleware` — rejects over-cap bodies before they reach a route (§9.1).
5. `RateLimitMiddleware` — §22.4.
6. `GZipMiddleware(minimum_size=1024)` — JSON only; **excluded for `image/*` and `application/zip`** (re-compressing JPEG burns CPU to add bytes).
7. Router.

---

## 22. Pydantic v2 schema catalogue

All under `backend/app/schemas/`. Every model inherits `ApiModel` (`common.py`), which sets `model_config = ConfigDict(from_attributes=True, extra="forbid", populate_by_name=True, ser_json_timedelta="float", str_strip_whitespace=True)`.

### `common.py`
`ApiModel`, `Page[ItemT]`, `PaginationParams`, `SortParams`, `WarningItem`, `LatLon`, `LatLonAlt`, `PixelXY`, `PixelBox`, `BBox`, `GeoJsonGeometry`, `GeoJsonPoint`, `GeoJsonLineString`, `GeoJsonPolygon`, `GeoJsonFeature`, `GeoJsonFeatureCollection`, `ResultRef`, `Unset`, `UNSET`, `IdResponse`, `DeletedResponse`, `CountResponse`

### `enums.py`
`JobStatus`, `JobType`, `JobStage`, `ProviderName`, `ExtractorName`, `MatcherName`, `EstimatorName`, `FeatureDetectorName`, `AnnotationKind`, `AnnotationGeomType`, `AnnotationOp`, `SemanticClass`, `FeatureSpace`, `SegmentBackend`, `PoseMethod`, `ExportFormat`, `ImageStatus`, `ImageKind`, `GcpStaleReason`, `SuggestionStrategy`, `SuggestionStatus`, `BatchOperation`, `BatchOnError`, `JobPriority`, `HealthStatus`, `ComponentStatus`, `ThumbnailSize`, `ImageFormat`, `HeatmapFormat`, `Colormap`

### `errors.py`
`ErrorEnvelope`, `ErrorBody`, `ErrorDetail`

### `health.py`
`HealthResponse`, `ReadinessResponse`, `ComponentHealth`

### `capabilities.py`
`CapabilitiesResponse`, `CapabilityItem`, `ExportCapability`, `ComputeInfo`, `LimitsInfo`, `DefaultsInfo`

### `project.py`
`ProjectCreate`, `ProjectUpdate`, `ProjectRead`, `ProjectSummary`, `ProjectCounts`, `ProjectListParams`

### `image.py`
`ImageUploadForm`, `ImageUploadAccepted`, `ImageUpdate`, `ImageRead`, `ImageSummary`, `ImageCounts`, `ImageUrls`, `ImageListParams`, `ImageMetadataRead`, `FileMetadata`, `RasterMetadata`, `GpsMetadata`, `CameraMetadata`, `GeoTiffMetadata`, `CaptureMetadata`, `DerivedMetadata`, `LatestMatchRef`, `ThumbnailParams`

### `annotation.py`
`AnnotationCreate`, `AnnotationUpdate`, `AnnotationRead`, `AnnotationSummary`, `AnnotationListParams`, `AnnotationBulkUpsertRequest`, `AnnotationBulkUpsertItem`, `AnnotationBulkUpsertResponse`, `AnnotationBulkUpsertResultItem`, `AnnotationApplyCounts`, `AnnotationStyle`

### `revision.py`
`RevisionCreate`, `RevisionRead`, `RevisionSummary`, `RevisionListParams`, `RevisionSnapshot`, `RevisionDiffSummary`, `RevisionRestoreRequest`, `RevisionRestoreResponse`, `AnnotationVersionRead`, `AnnotationVersionSummary`, `AnnotationVersionChangeSummary`, `AnnotationVersionListParams`

### `matching.py`
`MatchRequest`, `SearchHint`, `MatchOptions`, `ScoreWeights`, `MatchResultRead`, `MatchResultSummary`, `MatchResultListParams`, `MatchTileRef`, `MatchStats`, `MatchScores`, `MatchResultSelectRequest`, `SatelliteImageParams`

### `job.py`
`JobRead`, `JobSummary`, `JobProgress`, `JobListParams`, `JobPollParams`

### `gcp.py`
`GcpRead`, `GcpSummary`, `GcpUpdate`, `GcpOriginal`, `GcpLandmarkRef`, `GcpListParams`, `GcpResetRequest`, `GcpRecomputeRequest`, `GcpRecomputeDryRun`, `GcpRecomputeDelta`, `GcpRecomputeFitStats`

### `suggestion.py`
`SuggestLandmarksRequest`, `LandmarkSuggestionRead`, `SuggestionListParams`, `SuggestionAcceptRequest`, `SuggestionAcceptedRef`, `SuggestionRejectRequest`, `SuggestionRejectResponse`

### `semantic.py`
`SemanticFeatureRead`, `SemanticFeatureSummary`, `SemanticFeatureListParams`, `SegmentRequest`, `SegmentPoint`, `MaskRle`, `SemanticFeatureDeleteParams`

### `pose.py`
`CameraPoseRead`, `CameraPoseUpdate`, `CameraIntrinsics`, `CameraIntrinsicsInput`, `Orientation`, `OrientationInput`, `PoseUncertainty`, `PoseAmbiguity`, `HeatmapRead`, `HeatmapCell`, `HeatmapGrid`, `HeatmapCandidate`, `HeatmapScoreRange`, `HeatmapSparsity`, `HeatmapParams`

### `imagery.py`
`ProviderInfo`, `ProviderCapabilities`, `ProviderCoverage`, `ProviderAttribution`, `ProviderToS`, `ProviderRateLimit`, `ProviderHealth`, `ProviderListParams`, `TileParams`, `StaticImageParams`

### `batch.py`
`BatchCreate`, `BatchUploadForm`, `BatchRead`, `BatchSummary`, `BatchItemRead`, `BatchCounts`, `BatchRollup`, `BatchListParams`, `BatchImageFilter`

### `export.py`
`ExportRequest`, `ExportFilter`, `ExportOptions`, `ExportRead`, `ExportSummary`, `ExportListParams`, `PdfExportOptions`, `CsvExportOptions`, `ShapefileExportOptions`, `KmlExportOptions`, `DxfExportOptions`

**198 classes, 18 modules** (including the 30 enums in `enums.py`). Import direction is strictly one-way: `common`/`enums`/`errors` ← everything else. No schema module imports another domain schema module except through those three, which keeps the dependency graph acyclic and lets any schema be imported into a Celery worker without dragging in FastAPI.

---

## 23. OpenAPI, versioning, CORS, rate limiting, auth

### 23.1 OpenAPI

| | |
|---|---|
| Schema | `GET /api/v1/openapi.json` (OpenAPI 3.1 — Pydantic v2 emits 3.1 JSON Schema natively; do not downgrade to 3.0, which cannot express `null` unions correctly) |
| Swagger UI | `GET /api/v1/docs` |
| ReDoc | `GET /api/v1/redoc` |
| Docs in prod | gated by `ENABLE_DOCS` (default `true` — an internal survey tool benefits far more from discoverable docs than it loses to disclosure) |

- `operation_id` = `{tag}_{action}` (§1.4), asserted unique at startup.
- Every route declares `responses=` from `COMMON_ERROR_RESPONSES | {...route-specific}` so `ErrorEnvelope` appears on every documented failure. A missing 404 in the spec becomes an untyped `any` in the generated client.
- `Page[T]` parameterizations emit distinct named components (§3.1).
- Frontend types are generated (`openapi-typescript`) in CI, and **a diff in generated output fails the build** — the API cannot change shape without the change being visible in a reviewed PR.
- Examples are attached via `Field(examples=[...])` and `model_config["json_schema_extra"]`, using real payloads from this document.

### 23.2 Versioning

- **URL major versioning**: `/api/v1`. Chosen over header negotiation because it is visible in logs, curl, and bug reports, and because a browser can hit it directly.
- **Within v1, only additive changes**: new endpoints, new optional request fields, new response fields, new enum values on *response-only* enums.
- **Breaking** (⇒ `/api/v2`): removing/renaming a field, changing a type, making an optional field required, removing an enum value, changing a status code or an `error.code`, changing pagination/sorting defaults.

> **`extra="forbid"` on requests interacts with additivity, deliberately.** A *new optional request field* is additive (old clients omit it). But a **new value on a request enum** is not safe to treat as additive: an old client cannot send it, and a *new* client sending it to an *old* server gets a 422. So request enums grow only with a matching capability advertised in `GET /capabilities` — which is one of the reasons that endpoint exists.

- Deprecation: `Deprecation: true` + `Sunset: <RFC 1123 date>` + `Link: <…>; rel="deprecation"` headers, ≥ 90 days before removal, plus `deprecated: true` in OpenAPI. Deprecated endpoints emit a counter so the operator can see whether anyone still calls them.
- `X-API-Version: 1.4.2` on every response (build version, distinct from the `v1` contract).

### 23.3 CORS

```python
CORSMiddleware(
    allow_origins=settings.CORS_ORIGINS,          # explicit list; default ["http://localhost:5173"]
    allow_credentials=settings.AUTH_MODE == "cookie",
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "If-Match", "If-None-Match",
                   "Idempotency-Key", "X-Request-ID", "X-Confirm-Delete", "X-API-Key"],
    expose_headers=["ETag", "Location", "Retry-After", "X-Request-ID", "X-API-Version",
                    "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset",
                    "X-Imagery-Attribution", "X-Imagery-Provider", "X-Cache",
                    "X-Heatmap-BBox", "X-Heatmap-Score-Range", "X-Checksum-SHA256",
                    "Content-Disposition", "Idempotency-Replayed"],
    max_age=600,
)
```

- **`allow_origins=["*"]` is never used.** Not even in dev. Wildcard is incompatible with `allow_credentials=True`, and the habit ships to production.
- **`expose_headers` is not optional detail.** Browsers hide all but seven response headers from JS. Without this list the client cannot read `ETag` (so no `If-Match`, so no optimistic locking), cannot read `Location` (so no job polling), cannot read `Retry-After`, and cannot read `Content-Disposition` (so no filename on download). Every mechanism this API relies on is header-carried; omitting one silently disables a feature in the browser only, and it will pass every curl-based test.
- In production the SPA is served same-origin behind the reverse proxy and CORS is inert — it exists for the Vite dev server on :5173 and for third-party API consumers.

### 23.4 Rate limiting

Redis token bucket (`ratelimit:{scope}:{key}:{window}`), enforced by `RateLimitMiddleware`.

| Scope | Key | Limit | Rationale |
|---|---|---|---|
| global read | IP or API key | 600 / min, burst 100 | generous; reads are cheap |
| `POST /images` | principal | 60 / hour, burst 10 | 500 MB each |
| `POST /batch` | principal | 10 / hour | fans out to hundreds of jobs |
| job starts (`match`/`segment`/`suggest`/`export`/`recompute`) | principal | 120 / hour, burst 20 | each occupies a worker for minutes |
| `/imagery/tiles/*` | IP | 600 / min, burst 200 | matches a Leaflet pan burst; the shared cache absorbs the rest |
| `/imagery/static` | principal | 60 / min | stitches up to 256 tiles |
| `/exports/*/download` | principal | 120 / min | |
| per-provider upstream | provider | provider's `rate_limit` | protects the key/quota, **counted across all users** |

Headers on every response: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` (epoch seconds). On 429: `Retry-After` + `RATE_LIMIT_EXCEEDED`.

- **`/health` and `/health/ready` are exempt.** Rate-limiting your own liveness probe causes the orchestrator to kill healthy containers under load — an outage amplifier.
- **Fail-open when Redis is unreachable.** The limiter logs, increments `ratelimit_failopen_total`, and allows the request. Rate limiting is a protection mechanism, not a correctness one; failing closed converts a Redis blip into a total outage. Meanwhile `/health/ready` reports `not_ready` for Redis, so the instance is pulled from rotation anyway — the two mechanisms cover each other.
- The **provider bucket is per-deployment, not per-user** — it protects a shared key/quota, so it is the one bucket that must be globally coordinated, and it is why it lives in Redis rather than in-process.

### 23.5 Auth posture

**v1 ships single-tenant with auth disabled by default** (`AUTH_MODE=none`), because the deployment target is a surveyor's own machine or a private network, and requiring an identity provider to run `docker compose up` contradicts the zero-configuration requirement that also drives the keyless imagery default.

| `AUTH_MODE` | Mechanism | Use |
|---|---|---|
| `none` (default) | principal = `anonymous` | local/dev/single-user |
| `api_key` | `X-API-Key` header, hashed keys in `api_keys` | machine clients, small teams |
| `bearer` | `Authorization: Bearer <JWT>`, JWKS-verified | SSO |
| `cookie` | httpOnly session cookie + CSRF | browser SPA |

`Principal` = `{id, display_name, roles, auth_mode}`. It flows into `annotations.created_by/updated_by`, `gcps.adjusted_by`, `project_revisions.actor_id`, `exports.requested_by` — the audit columns.

> **The honest consequence, stated rather than hidden.** With `AUTH_MODE=none`, `gcps.adjusted_by = 'anonymous'` and the DDL's `ck_gcps_adjustment_complete` is satisfied by a value that attributes nothing. The database can then prove *that* a coordinate was adjusted and *when*, but not *by whom*. That is acceptable for a single-surveyor deployment and **not** acceptable for a multi-user one producing legal survey deliverables. `POST /gcps/{id}` adjustments therefore return `401 MISSING_CREDENTIALS` whenever `AUTH_MODE != none` and no principal resolves — the audit trail is enforced the moment there is more than one person who could be lying. Operators running multi-user must set `AUTH_MODE`; the deploy doc says so, and `/health/ready` reports `auth_mode` in its `detail` so a reviewer can see it at a glance.

`403 READ_ONLY_MODE` on every mutating route when `READ_ONLY=true` (maintenance/migration windows).

### 23.6 Observability contract

- `X-Request-ID` in and out; generated when absent; in every log line and every `ErrorBody`.
- `GET /metrics` (Prometheus, separate port `9090`, **not** under `/api/v1` — it is not part of the public contract): `http_requests_total{route,method,status}`, `http_request_duration_seconds{route}`, `job_duration_seconds{type,status}`, `job_queue_depth{queue}`, `imagery_tile_requests_total{provider,cache}`, `imagery_upstream_errors_total{provider}`, `model_fallbacks_total{requested,effective}`, `gcp_adjustments_total`, `ratelimit_rejections_total{scope}`, `unhandled_exceptions_total{route}`.
- `model_fallbacks_total` is the metric that proves the degradation requirement is working in production rather than merely specified here.
- Structured JSON logs; `request_id`, `principal`, `route`, `status`, `duration_ms`, `job_id` bound via contextvars. **Keys, tokens, and `Authorization` values are scrubbed by a logging filter** before emission.

---

## Appendix A — Status codes used

| Code | Meaning here |
|---|---|
| `200` | OK |
| `201` | Created (project, image, annotation) |
| `202` | Accepted — async job started, or cooperative cancel in flight |
| `204` | No Content — delete; **or a valid tile address with no imagery** (§18.3) |
| `206` | Partial Content — `Range` on `/file`, `/download` |
| `304` | Not Modified — `If-None-Match` |
| `400` | `EMPTY_PATCH` |
| `401` | auth required/invalid |
| `403` | ToS-forbidden provider, read-only mode |
| `404` | not found; unknown provider; pose/heatmap unavailable |
| `409` | conflict — job running, export not ready, code taken, revision conflict |
| `410` | gone — export expired, imagery cache ToS-purged, revision pruned |
| `412` | precondition failed — stale `If-Match` |
| `413` | payload too large |
| `415` | unsupported media type |
| `416` | range not satisfiable |
| `422` | validation |
| `428` | precondition required — missing `If-Match` / `X-Confirm-Delete` |
| `429` | rate limited |
| `500` | internal |
| `502` | provider upstream error |
| `503` | dependency unavailable, provider not configured, no workers |
| `507` | insufficient storage |

## Appendix B — Headers used

**Request:** `Authorization`, `X-API-Key`, `Content-Type`, `Content-Length`, `If-Match`, `If-None-Match`, `If-Modified-Since`, `Range`, `Idempotency-Key`, `X-Request-ID`, `X-Confirm-Delete`, `Accept`

**Response:** `ETag`, `Location`, `Retry-After`, `Cache-Control`, `Content-Disposition`, `Content-Range`, `Accept-Ranges`, `Vary`, `X-Request-ID`, `X-API-Version`, `X-Response-Time-ms`, `X-RateLimit-*`, `X-Imagery-Attribution`, `X-Imagery-Provider`, `X-Imagery-BBox`, `X-Imagery-Zoom`, `X-Imagery-Tiles-Used`, `X-Imagery-Tiles-Missing`, `X-Cache`, `X-Heatmap-BBox`, `X-Heatmap-Score-Range`, `X-Checksum-SHA256`, `X-GCP-Count`, `Idempotency-Replayed`, `Deprecation`, `Sunset`

## Appendix C — Settings referenced

`MAX_UPLOAD_BYTES` (524288000) · `MAX_IMAGE_PIXELS` (400000000) · `MAX_IMAGE_DIM` (65535) · `ALLOWED_IMAGE_MIME` · `ASYNC_INGEST_THRESHOLD_BYTES` (52428800) · `MAX_BATCH_FILES` (100) · `MAX_BATCH_BYTES` (2147483648) · `MAX_ANNOTATIONS_PER_IMAGE` (2000) · `MAX_STATIC_PIXELS` (67108864) · `MAX_STATIC_TILES` (256) · `MAX_TILES_PER_JOB` (256) · `MAX_REPLAY_EVENTS` (5000) · `CHECKPOINT_EVERY_N_EVENTS` (50) · `GCP_CONSISTENCY_TOLERANCE_M` (0.5) · `GCP_BOUNDS_SLACK_M` (100) · `GEOTIFF_DISAGREEMENT_M` (50) · `TILE_CACHE_MAX_BYTES` (21474836480) · `STORAGE_MIN_FREE_BYTES` (2147483648) · `JOB_RETENTION_DAYS` (30) · `EXPORT_DEFAULT_TTL_S` (604800) · `CORS_ORIGINS` · `AUTH_MODE` (none) · `READ_ONLY` (false) · `ENABLE_DOCS` (true) · `DEBUG` (false) · `USE_SENDFILE` (false) · `PROJECT_NAMES_UNIQUE` (false) · `GOOGLE_MAPS_TOS_ACKNOWLEDGED` (false)

