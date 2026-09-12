/**
 * Shared wire vocabulary — mirrors `backend/app/schemas/common.py` + `errors.py` (§6.2).
 *
 * ★ THE CASING LAW (§8.1 / L9): snake_case at the API boundary, in the generated
 *   types, AND here. There is no case-mapping layer anywhere in the frontend.
 *   `camelcase` is disabled for `src/types/**` in `.eslintrc.cjs` for this reason.
 *
 * ★ Nulls — RESPONSES (§6.1): a nullable field is ALWAYS present with value `null`.
 *   Clients must not distinguish "absent" from "null" in a response. Response types
 *   here therefore use `T | null`, never `T?`.
 *
 * ★ Nulls — REQUESTS (§6.1): PATCH bodies are the ONE exception and DO distinguish
 *   absent from null (UNSET semantics). `XxxUpdate` fields are `T | null | undefined`
 *   and the client OMITS the key (via JSON.stringify) for "leave untouched".
 */

// ─────────────────────────────────────────────────────────────────────────────
// Branded ids (§8.1)
// ─────────────────────────────────────────────────────────────────────────────

declare const __brand: unique symbol;
type Brand<T, B> = T & { readonly [__brand]: B };

/** A UUIDv4 string. Branded so an `image_id` cannot be passed where a `gcp_id` goes. */
export type Uuid = Brand<string, 'Uuid'>;

/** UTC, RFC 3339, always an explicit `Z`: `2026-07-17T09:41:22.481Z` (§6.1). */
export type IsoDateTime = Brand<string, 'IsoDateTime'>;

/**
 * The generated transport types (`api/generated/schema.ts`) are structurally correct
 * but semantically flat (`id: string`). These two casts are the branding seam and
 * are the ONLY sanctioned way in. They add zero renames (§8.1).
 */
export const asUuid = (s: string): Uuid => s as Uuid;
export const asIsoDateTime = (s: string): IsoDateTime => s as IsoDateTime;

// ─────────────────────────────────────────────────────────────────────────────
// Geometry primitives — client-side, UI-idiomatic (no server mirror)
// ─────────────────────────────────────────────────────────────────────────────

export interface Point2D {
  x: number;
  y: number;
}

export interface Size {
  width: number;
  height: number;
}

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// Pagination (§6.2 `Page[ItemT]`)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * ★ Collections are NEVER a bare list (§6.1). A bare top-level JSON array is a
 *   hijacking footgun and makes adding pagination a breaking change.
 */
export interface Page<T> {
  items: T[];
  /** Exact count matching the filter, ignoring limit/offset. */
  total: number;
  limit: number;
  offset: number;
  /** `offset + items.length < total`. */
  has_more: boolean;
}

/** Query params. `limit` out of 1..200 is a 422, NEVER silently clamped (§6.2). */
export interface PaginationParams {
  limit?: number;
  offset?: number;
}

/** Comma-separated, leading `-` = descending, max 3 keys, per-endpoint whitelist. */
export interface SortParams {
  sort?: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Errors (§6.2 `errors.py`, §8.1)
// ─────────────────────────────────────────────────────────────────────────────

export interface ErrorDetail {
  loc: (string | number)[];
  msg: string;
  type: string;
  input: unknown | null;
}

export interface ErrorBody {
  /** ★ STABLE, machine-readable, SCREAMING_SNAKE. The client switches on this. Never localised. */
  code: ApiErrorCode;
  /** Human, English, safe to display. NEVER SQL, stack frames, file paths, or provider keys. */
  message: string;
  /** Mirrors HTTP. Duplicated in-body deliberately: it survives logging, proxies, and client libs. */
  status: number;
  details: ErrorDetail[] | null;
  /** ULID. Also the `X-Request-ID` header. The string a user pastes into a bug report. */
  request_id: string;
  timestamp: IsoDateTime;
  docs_url: string | null;
}

/** EVERY non-2xx response has this exact shape (§6.2). */
export interface ErrorEnvelope {
  error: ErrorBody;
}

/**
 * Thrown by `src/api/client.ts` (IU-24). Carries the parsed envelope.
 *
 * ★ This is a real class, not an interface: `api/queryClient.ts`'s retry predicate
 *   does `error instanceof ApiError && error.status >= 400 && error.status < 500`
 *   (§8.4), so it must exist as a runtime value.
 */
export class ApiError extends Error {
  readonly body: ErrorBody;
  readonly status: number;

  constructor(body: ErrorBody) {
    super(body.message);
    this.name = 'ApiError';
    this.body = body;
    this.status = body.status;
    // Required for `instanceof` to survive the ES5 downlevel of Error subclassing.
    Object.setPrototypeOf(this, ApiError.prototype);
  }

  get code(): ApiErrorCode {
    return this.body.code;
  }

  get request_id(): string {
    return this.body.request_id;
  }

  /** ★ Never retry a 4xx (§8.4) — a retry cannot fix a malformed request. */
  get is_client_error(): boolean {
    return this.status >= 400 && this.status < 500;
  }

  /**
   * ★ SCOPE.md §4 rule 3: deferred endpoints return 501 with a `feature: "deferred"`
   *   marker rather than 404 — the feature is planned, not absent. The UI renders
   *   these as a calm explainer, never as an error (§8.8).
   */
  get is_deferred(): boolean {
    return this.status === 501;
  }
}

/**
 * ★ GENERATED, NOT HAND-MAINTAINED. `scripts/gen_error_codes.py` walks the §6.3
 * hierarchy (every `LandExplorerError` subclass's `code` ClassVar), adds the two
 * JOB-ONLY codes, and emits this union. CI fails on a diff — the same gate, for the
 * same reason, as openapi-typescript.
 *
 * Hand-maintaining a mirror of a Python hierarchy is the drift the generator gate
 * exists to kill; it has no business being the one exception.
 *
 * CI test: every `LandExplorerError.code` reachable in the app appears in this union.
 */
export type ApiErrorCode =
  // ── job-only (never an HTTP status; produced by the task classifier, §6.3) ──
  | 'CANCELLED'
  | 'TIMEOUT'
  // ── the §6.3 hierarchy ──
  | 'VALIDATION_ERROR'
  | 'PROJECT_NOT_FOUND'
  | 'IMAGE_NOT_FOUND'
  | 'ANNOTATION_NOT_FOUND'
  | 'JOB_NOT_FOUND'
  | 'MATCH_RESULT_NOT_FOUND'
  | 'GCP_NOT_FOUND'
  | 'REVISION_NOT_FOUND'
  | 'EXPORT_NOT_FOUND'
  | 'BATCH_NOT_FOUND'
  | 'CAMERA_POSE_NOT_AVAILABLE'
  | 'HEATMAP_NOT_AVAILABLE'
  | 'SEARCH_HINT_REQUIRED'
  | 'NO_ANNOTATIONS'
  | 'ZOOM_OUT_OF_RANGE'
  | 'SEARCH_AREA_TOO_LARGE'
  | 'INVALID_BBOX'
  | 'BBOX_CROSSES_ANTIMERIDIAN'
  | 'INVALID_SORT_FIELD'
  | 'UNKNOWN_QUERY_PARAM'
  | 'PARAM_CONFLICT'
  | 'GCP_ADJUSTMENT_AMBIGUOUS'
  | 'GCP_OUT_OF_BOUNDS'
  | 'GCP_CODE_CONFLICT'
  | 'ANNOTATION_GEOMETRY_INVALID'
  | 'ANNOTATION_OUT_OF_BOUNDS'
  | 'TOO_MANY_ANNOTATIONS'
  | 'GEOMETRY_TOO_COMPLEX'
  | 'MATCH_JOB_ALREADY_RUNNING'
  | 'IMAGE_STILL_PROCESSING'
  | 'JOB_NOT_CANCELLABLE'
  | 'REVISION_CONFLICT'
  | 'REVISION_RESTORE_CONFLICT'
  | 'REVISION_PRUNED'
  | 'REVISION_REPLAY_TOO_EXPENSIVE'
  | 'PROJECT_HAS_ACTIVE_JOBS'
  | 'STALE_ANNOTATION_VERSION'
  | 'STALE_GCP_VERSION'
  | 'STALE_PROJECT_VERSION'
  | 'PRECONDITION_REQUIRED'
  | 'CONFIRMATION_REQUIRED'
  | 'EMPTY_PATCH'
  | 'UPLOAD_TOO_LARGE'
  | 'BATCH_TOO_LARGE'
  | 'UNSUPPORTED_IMAGE_FORMAT'
  | 'IMAGE_TOO_LARGE'
  | 'EXPORT_EXPIRED'
  | 'EXPORT_NOT_READY'
  | 'IMAGE_PURGED'
  | 'SATELLITE_IMAGE_PURGED'
  | 'IDEMPOTENCY_KEY_REUSED'
  | 'IDEMPOTENCY_IN_PROGRESS'
  | 'MISSING_CREDENTIALS'
  | 'INVALID_CREDENTIALS'
  | 'PROVIDER_TOS_FORBIDDEN'
  | 'READ_ONLY_MODE'
  | 'RATE_LIMIT_EXCEEDED'
  | 'PROVIDER_RATE_LIMITED'
  | 'PROVIDER_UPSTREAM_ERROR'
  | 'PROVIDER_NOT_CONFIGURED'
  | 'OUT_OF_COVERAGE'
  | 'PROVIDER_INVALID_RESPONSE'
  | 'UNKNOWN_PROVIDER'
  | 'DATABASE_UNAVAILABLE'
  | 'REDIS_UNAVAILABLE'
  | 'WORKER_UNAVAILABLE'
  | 'ARTIFACT_WRITE_FAILED'
  | 'ARTIFACT_READ_FAILED'
  | 'INSUFFICIENT_STORAGE'
  | 'INTERNAL_ERROR'
  // ── present in §6.3, absent from v1.0's union ──
  | 'NO_ADJUSTED_GCPS'
  | 'INSUFFICIENT_ANCHORS'
  | 'STATIC_IMAGE_TOO_LARGE'
  | 'GCP_ORIGINAL_UNAVAILABLE'
  | 'PROJECT_NAME_CONFLICT'
  // ── albums (§7): names are case-insensitively unique among live albums ──
  | 'ALBUM_NOT_FOUND'
  | 'ALBUM_NAME_CONFLICT'
  | 'RANGE_NOT_SATISFIABLE'
  | 'SUGGESTION_NOT_FOUND'
  | 'ANNOTATION_VERSION_NOT_FOUND'
  | 'TIMEOUT_EXCEEDS_LIMIT'
  | 'ELEVATION_UNAVAILABLE'
  // ── SCOPE.md §4 rule 3: the deferred surface is honest, not absent ──
  | 'FEATURE_DEFERRED';

// ─────────────────────────────────────────────────────────────────────────────
// Warnings — the NON-ERROR channel (§6.2)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * ★ A missing SuperGlue weight is a successful match with a note, not a failure (L11).
 *
 * ★ §8.8: the distinction that decides how this renders is `requested !== null`.
 *   An UNREQUESTED fallback is INFORMATIONAL ("Matched with SIFT + FLANN"); a
 *   requested-and-denied one is a WARNING. Per SCOPE.md the classical path is the
 *   default state on a fresh machine — framing it as a degradation would be both
 *   wrong and demoralising.
 */
export interface WarningItem {
  /** SCREAMING_SNAKE, e.g. `MODEL_WEIGHTS_MISSING`. */
  code: string;
  message: string;
  field: string | null;
  requested: string | null;
  effective: string | null;
}

// ─────────────────────────────────────────────────────────────────────────────
// Misc shared value objects
// ─────────────────────────────────────────────────────────────────────────────

/** `JobRead.result_ref` (§6.2). */
export interface ResultRef {
  /** `match_result` | `export` | `batch` | `semantic_features` | `suggestions` */
  kind: string;
  id: string;
}

/**
 * ★ MOVED HERE from `revision.ts`, mirroring the Python move (§6.2). It is a shared
 *   value object: `AnnotationBulkUpsertResponse.revision` needs it, and endpoint 45
 *   (suggestions) returns that same response. `RevisionRead` — the fat one, with
 *   snapshot/events/diff_summary — stays in `annotation.ts`.
 */
export interface RevisionSummary {
  id: Uuid;
  project_id: Uuid;
  seq: number;
  label: string | null;
  is_checkpoint: boolean;
  annotation_count: number;
  created_at: IsoDateTime;
}

export interface IdResponse {
  id: Uuid;
}

export interface DeletedResponse {
  id: Uuid;
  deleted: boolean;
}

export interface CountResponse {
  count: number;
}

/** How a coordinate is rendered. Persisted in `workspaceStore` (§8.5).
 *  ★ `ddutmz` — a combined view: decimal degrees + UTM + a Z (elevation) column. */
export type CoordinateFormat = 'dd' | 'dms' | 'utm' | 'ddutmz';

// ─────────────────────────────────────────────────────────────────────────────
// Result<T, E> — client-only (§8.2)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * For the call sites that must handle failure as a value rather than a throw —
 * chiefly parsers and the viewport transform's guards, where a throw would unmount
 * a canvas mid-drag.
 */
export type Result<T, E = ApiError> = { ok: true; value: T } | { ok: false; error: E };

export const ok = <T>(value: T): Result<T, never> => ({ ok: true, value });
export const err = <E>(error: E): Result<never, E> => ({ ok: false, error });
