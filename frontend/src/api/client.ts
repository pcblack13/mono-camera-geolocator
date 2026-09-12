/**
 * ★★ THE ONLY `fetch()` IN THE APP — `src/api/client.ts` (§2.5).
 *
 * Base URL · request id · `ErrorEnvelope` → `ApiError` · `Retry-After` parsing ·
 * `ETag` capture for `If-Match`. Everything that crosses the wire crosses here.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * ★ THE CASING LAW (§8.1 / L9). Every WIRE field this module reads or writes is
 *   snake_case and is never renamed. The handful of camelCase identifiers here
 *   (`retryAfterMs`, `requestId`) are CLIENT-SIDE transport metadata that mirror no
 *   Pydantic field — §8.4 declares `Parsed<T>` with exactly that spelling and the
 *   poller reads `res.retryAfterMs`, so this is the contract's own naming, not a
 *   mapping layer. `camelcase` is disabled for `src/api/**` in `.eslintrc.cjs`.
 *
 * ★ EVERY non-2xx carries `{ error: ErrorBody }` (§6.2) and becomes an `ApiError`
 *   (declared by IU-23 in `types/common.ts` — this module throws it, it does not
 *   own it). `queryClient.ts`'s retry predicate does `error instanceof ApiError`,
 *   so a network failure, an nginx HTML 502 and a JSON envelope must ALL arrive as
 *   one type. A thrown `TypeError` from `fetch` would sail straight past that
 *   predicate and be retried three times against a dead socket.
 *
 * ★ SCOPE.md §4 rule 3 — THE DEFERRED SURFACE. Deferred endpoints return `501` with
 *   the uniform envelope and a `feature: "deferred"` marker. They must not 404 (the
 *   feature is planned, not absent) and must not fake a result. {@link isDeferredError}
 *   is the typed way to ask; {@link hasDeferredMarker} reports the explicit marker.
 *   ★ But the PRIMARY gate is `useCapabilities`'s `deferred_features` — see
 *   `hooks/useCapabilities.ts`. Rule 4 requires the control be disabled with an
 *   honest tooltip BEFORE it is clicked; discovering deferral from a failed response
 *   is the fallback, not the mechanism.
 */

import { ApiError, asIsoDateTime, type ErrorBody, type ErrorDetail } from '../types/common';

// ─────────────────────────────────────────────────────────────────────────────
// Base URL (§9.11)
// ─────────────────────────────────────────────────────────────────────────────

const DEFAULT_BASE_URL = '/api/v1';

/**
 * ★ L10's spirit on the frontend: a working default, always. An unset OR EMPTY
 *   `VITE_API_BASE_URL` yields `/api/v1` — same-origin in dev (the Vite proxy) and
 *   in prod (nginx). An empty-string env var is the common CI accident and must not
 *   silently retarget every request at the document root.
 */
function readBaseUrl(): string {
  const raw = import.meta.env.VITE_API_BASE_URL;
  const trimmed = typeof raw === 'string' ? raw.trim() : '';
  const base = trimmed.length > 0 ? trimmed : DEFAULT_BASE_URL;
  return base.endsWith('/') ? base.slice(0, -1) : base;
}

export const API_BASE_URL: string = readBaseUrl();

/** `X-Request-ID` — the default of `LE_REQUEST_ID_HEADER` (§9). */
const REQUEST_ID_HEADER = 'X-Request-ID';

/** SCOPE.md §4 rule 3. The one status that means "planned, not built". */
const HTTP_NOT_IMPLEMENTED = 501;

// ─────────────────────────────────────────────────────────────────────────────
// Request ids — ULID, minted client-side
// ─────────────────────────────────────────────────────────────────────────────

/** Crockford base32 — the ULID alphabet. No I, L, O or U. */
const CROCKFORD = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';

/**
 * ★ The server MINTS OR PROPAGATES (`RequestIdMiddleware`, §6.5) — so a client-sent
 *   id survives into the server's logs, and `ErrorBody.request_id` comes back as the
 *   same string the browser already has. That is what makes "paste the id into the
 *   bug report" work for a failure the server never saw (a timeout, a dead socket):
 *   without minting here, exactly the failures hardest to diagnose are the ones with
 *   no id at all.
 *
 * ULID rather than UUID because `ErrorBody.request_id` is specified as a ULID (§6.2)
 * and a mixed-format id column is a log-grepping tax forever.
 */
export function ulid(): string {
  let now = Date.now();
  let time = '';
  for (let i = 0; i < 10; i += 1) {
    const mod = now % 32;
    time = CROCKFORD[mod] + time;
    now = (now - mod) / 32;
  }
  return time + randomChars(16);
}

/**
 * ★ L11 in miniature: a missing optional capability is a fallback, never a
 *   traceback. `crypto.getRandomValues` is present in every browser we support and
 *   in jsdom, but a request id is telemetry — it must never be the reason a
 *   surveyor's upload throws.
 */
function randomChars(len: number): string {
  const webcrypto = globalThis.crypto;
  let out = '';
  if (typeof webcrypto?.getRandomValues === 'function') {
    const bytes = new Uint8Array(len);
    webcrypto.getRandomValues(bytes);
    for (let i = 0; i < len; i += 1) out += CROCKFORD[bytes[i] & 0x1f];
    return out;
  }
  for (let i = 0; i < len; i += 1) out += CROCKFORD[Math.floor(Math.random() * 32)];
  return out;
}

// ─────────────────────────────────────────────────────────────────────────────
// Query serialisation
// ─────────────────────────────────────────────────────────────────────────────

export type QueryScalar = string | number | boolean;
export type QueryValue = QueryScalar | QueryScalar[] | null | undefined;
export type QueryParams = Record<string, QueryValue>;

/**
 * ★ ARRAYS SERIALISE AS CSV — `?kind=point,polygon`, not repeated keys. §7 spells
 *   "(csv)" out for `/health/ready`'s `check` and for `DELETE
 *   /images/{id}/annotations`' `kind`, and never specifies repeated keys anywhere,
 *   so CSV is the contract's only stated convention and every list filter follows
 *   it. ★ FastAPI's DEFAULT for `list[str]` is repeated keys — IU-21's
 *   `*ListParams` dependencies must therefore parse CSV explicitly. Flagged.
 *
 * `undefined` and `null` are OMITTED, never sent as the string "undefined". An
 * empty array is omitted too: `?status=` is a filter on the empty string, which is
 * an `INVALID_SORT_FIELD`-shaped 422 rather than the "no filter" the caller meant.
 */
function encodeQuery(params: QueryParams | undefined): string {
  if (!params) return '';
  const sp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null) continue;
    if (Array.isArray(value)) {
      if (value.length === 0) continue;
      sp.append(key, value.map(String).join(','));
    } else {
      sp.append(key, String(value));
    }
  }
  const qs = sp.toString();
  return qs.length > 0 ? `?${qs}` : '';
}

/** The absolute (or origin-relative) URL for an API path. `path` starts with `/`. */
export function buildUrl(path: string, query?: QueryParams): string {
  return `${API_BASE_URL}${path}${encodeQuery(query)}`;
}

/**
 * ★ Widen a typed filter object (`GcpFilters`, `ImageFilters`, …) to query params.
 *
 *   **THE ONE SANCTIONED WIDENING POINT.** A TypeScript `interface` gets no implicit
 *   index signature, so `someFilters as QueryParams` is accepted for some shapes and
 *   rejected for others depending on structural comparability — an inconsistency with
 *   nothing to do with correctness, which would otherwise be papered over with a
 *   scattering of `as unknown as QueryParams` double-casts. Those are load-bearing
 *   lies: they would also silence a filter type that genuinely contained a
 *   non-serialisable value.
 *
 *   Every field of every `*Filters` type in `src/types/**` is a string, number,
 *   boolean or array thereof — i.e. already a {@link QueryValue} — and
 *   {@link encodeQuery} handles `undefined`, `null` and `[]` by omission regardless.
 *   Widening is therefore safe HERE, once, with the reason written down.
 */
export function toQuery(params: object | undefined): QueryParams | undefined {
  return params as QueryParams | undefined;
}

// ─────────────────────────────────────────────────────────────────────────────
// The response envelope (§8.4)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * ★ §8.4 declares this as `{ data: T; retryAfterMs: number | null }` and names the
 *   poller its only consumer. The three extra fields are ADDITIVE — a consumer
 *   destructuring `{ data, retryAfterMs }` is unaffected — and exist because the
 *   contract's own mechanisms need them: `If-Match` needs `etag` (§7 endpoints 21 and
 *   40 REQUIRE it), and `202 + Location` is how every async endpoint hands back a job.
 */
export interface Parsed<T> {
  data: T;
  /** ★ From `Retry-After`. **Absent on a terminal job — its absence IS the
   *  machine-readable "stop polling"** (§6.2). `null`, never `0`, when absent. */
  retryAfterMs: number | null;
  status: number;
  /** ★ Feeds {@link etagFor} → the `If-Match` on endpoints 21 and 40. */
  etag: string | null;
  location: string | null;
  requestId: string | null;
}

/**
 * ★ `Retry-After` is `delta-seconds` OR an HTTP-date (RFC 9110). Servers send the
 *   former; caches and proxies send the latter. Reading only the integer form makes
 *   the poller silently ignore a proxy-rewritten header — which looks like "polling
 *   is a bit fast" and is never diagnosed.
 */
function parseRetryAfter(raw: string | null): number | null {
  if (raw === null) return null;
  const text = raw.trim();
  if (text.length === 0) return null;

  const seconds = Number(text);
  if (Number.isFinite(seconds)) return Math.max(0, seconds * 1000);

  const at = Date.parse(text);
  if (!Number.isNaN(at)) return Math.max(0, at - Date.now());

  return null;
}

// ─────────────────────────────────────────────────────────────────────────────
// ETag registry — what makes `If-Match` possible in a browser
// ─────────────────────────────────────────────────────────────────────────────

/**
 * ★ WHY THIS EXISTS. Endpoints 21 (`PATCH /annotations/{id}`) and 40 (`PATCH
 *   /gcps/{id}`) REQUIRE `If-Match`; without it the server answers `428
 *   PRECONDITION_REQUIRED`. The ETag arrives on a RESPONSE HEADER, and React Query
 *   caches response BODIES — so by the time a component holds a `GcpRead` the ETag
 *   is gone. Worse, a LIST response carries ONE ETag for the whole page, so a
 *   per-row ETag is not recoverable from `useGcps` at all.
 *
 *   Every 2xx that carries an `ETag` records it here, keyed by the request PATH; the
 *   write hooks read it back. A PATCH response's own new ETag overwrites the entry,
 *   so consecutive adjustments to the same GCP work without a refetch.
 *
 * ★ A STALE ENTRY IS SAFE BY CONSTRUCTION. If someone else changed the row, our
 *   ETag no longer matches and the server returns `412` — which is exactly the
 *   conflict the mechanism exists to surface. The failure mode is a visible,
 *   correct, recoverable error, never a lost update. **This is the one place where
 *   being wrong is designed to be loud.**
 *
 * ★ Callers that HAVE a fresher ETag may always pass it explicitly; the explicit
 *   value wins over the registry.
 *
 * ★ Not a `Map` that grows forever in practice: keys are resource paths a single
 *   session actually opened. The GC-pressure alternative (a WeakMap) cannot be keyed
 *   by string.
 */
const etagRegistry = new Map<string, string>();

/** The `ETag` last seen for `path`, if any. `path` is base-relative, e.g. `/gcps/x`. */
export function etagFor(path: string): string | undefined {
  return etagRegistry.get(path);
}

/** Record an `ETag` for `path`. Called automatically for every 2xx that carries one. */
export function rememberEtag(path: string, etag: string): void {
  etagRegistry.set(path, etag);
}

/** Drop a path's `ETag` — e.g. after a delete, so a recreated id cannot inherit it. */
export function forgetEtag(path: string): void {
  etagRegistry.delete(path);
}

/** ★ Test seam only. Never called by app code. */
export function __clearEtagRegistry(): void {
  etagRegistry.clear();
}

// ─────────────────────────────────────────────────────────────────────────────
// The deferred surface — SCOPE.md §4 rule 3
// ─────────────────────────────────────────────────────────────────────────────

/**
 * The envelope's marker value. SCOPE.md §4 rule 3 specifies the literal
 * `feature: "deferred"` — a MARKER, not a feature name.
 */
export type FeatureMarker = 'deferred';

/**
 * ★ Errors carrying the explicit `feature: "deferred"` marker.
 *
 *   A `WeakMap` rather than a subclass: `ApiError` is IU-23's (`types/common.ts`),
 *   its constructor takes `(body: ErrorBody)` only, and — decisively — it calls
 *   `Object.setPrototypeOf(this, ApiError.prototype)`, which would silently strip a
 *   subclass's own prototype after `super()` returned. Extending it would work only
 *   by re-setting the prototype in every subclass, which is a trap laid for whoever
 *   adds the next one. The seam stays where IU-23 put it and this module annotates
 *   from the outside.
 */
const deferredMarked = new WeakMap<ApiError, FeatureMarker>();

/**
 * ★ SCOPE.md §4 rule 3 — THE TYPED WAY TO ASK "is this feature deferred in this
 *   build?" for a request that already failed.
 *
 * `501` is the definition (matching `ApiError.is_deferred`, IU-23), and the explicit
 * marker — when the server sends it — is corroboration. Either is sufficient: a
 * proxy-generated 501 with no envelope is still, in this system, "not built".
 *
 * ★ Use `useCapabilities().deferred_features` to DISABLE a control up front. This is
 *   for the response path — the belt to that braces.
 */
export function isDeferredError(error: unknown): error is ApiError {
  return (
    error instanceof ApiError &&
    (error.status === HTTP_NOT_IMPLEMENTED || deferredMarked.has(error))
  );
}

/** `true` iff the server sent the explicit `feature: "deferred"` marker (SCOPE.md §4 rule 3). */
export function hasDeferredMarker(error: unknown): boolean {
  return error instanceof ApiError && deferredMarked.has(error);
}

/**
 * ★ Where the marker may legally live. SCOPE.md says "the uniform error envelope AND
 *   a `feature: "deferred"` marker" without siting it, and `ErrorBody` (§8.1, IU-23)
 *   has no `feature` field — so a top-level sibling of `error` is the reading that
 *   leaves `ErrorBody` unchanged. Both placements are accepted because IU-21 writes
 *   the endpoint in parallel with this file and a marker in the "wrong" spot must
 *   degrade to "we still saw the 501", not to a mis-render. Flagged for IU-21.
 */
function readFeatureMarker(raw: unknown): FeatureMarker | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const top = (raw as { feature?: unknown }).feature;
  if (top === 'deferred') return 'deferred';
  const nested = (raw as { error?: { feature?: unknown } }).error?.feature;
  if (nested === 'deferred') return 'deferred';
  return null;
}

// ─────────────────────────────────────────────────────────────────────────────
// Error construction
// ─────────────────────────────────────────────────────────────────────────────

function isErrorDetailArray(value: unknown): value is ErrorDetail[] {
  return (
    Array.isArray(value) && value.every((d) => typeof d === 'object' && d !== null && 'msg' in d)
  );
}

/**
 * Parse a server envelope into an `ErrorBody`, or synthesise an honest one.
 *
 * ★ NEVER INVENT A CODE THAT IMPLIES A CAUSE WE DID NOT OBSERVE. A 502 of nginx HTML
 *   becomes `INTERNAL_ERROR` — not `DATABASE_UNAVAILABLE`, which would send an
 *   operator to the wrong dashboard. The one inference made is `501 →
 *   FEATURE_DEFERRED`, and only because `501` has exactly one meaning in this system
 *   (SCOPE.md §4 rule 3).
 */
function coerceErrorBody(raw: unknown, status: number, requestId: string): ErrorBody {
  const envelope =
    typeof raw === 'object' && raw !== null ? (raw as { error?: unknown }).error : null;

  if (typeof envelope === 'object' && envelope !== null) {
    const e = envelope as Partial<ErrorBody>;
    if (typeof e.code === 'string' && typeof e.message === 'string') {
      return {
        code: e.code,
        message: e.message,
        // ★ HTTP wins over the body: a proxy can rewrite the status but not the body.
        status: typeof e.status === 'number' ? e.status : status,
        details: isErrorDetailArray(e.details) ? e.details : null,
        request_id: typeof e.request_id === 'string' ? e.request_id : requestId,
        timestamp: asIsoDateTime(
          typeof e.timestamp === 'string' ? e.timestamp : new Date().toISOString(),
        ),
        docs_url: typeof e.docs_url === 'string' ? e.docs_url : null,
      };
    }
  }

  return {
    code: status === HTTP_NOT_IMPLEMENTED ? 'FEATURE_DEFERRED' : 'INTERNAL_ERROR',
    message:
      status === HTTP_NOT_IMPLEMENTED
        ? 'This feature is not enabled in this build.'
        : `The server returned ${status} without a readable error envelope.`,
    status,
    details: null,
    request_id: requestId,
    timestamp: asIsoDateTime(new Date().toISOString()),
    docs_url: null,
  };
}

function makeApiError(raw: unknown, status: number, requestId: string): ApiError {
  const error = new ApiError(coerceErrorBody(raw, status, requestId));
  const marker = readFeatureMarker(raw);
  if (marker !== null) deferredMarked.set(error, marker);
  return error;
}

/**
 * ★ A TRANSPORT failure must arrive as an `ApiError` too.
 *
 *   `fetch` rejects with a bare `TypeError` on DNS failure, a dropped connection, a
 *   CORS rejection or an offline tablet. `queryClient`'s predicate only recognises
 *   `ApiError`, so an unwrapped `TypeError` is treated as retryable-forever AND
 *   renders through a different code path than every other failure the user can see.
 *   A surveyor on a dying cellular link is precisely who must get a coherent message.
 *
 *   `status: 0` is deliberate — it is not a 4xx, so the retry predicate DOES retry
 *   it, which is right: a flaky link is exactly what retries are for.
 */
function makeTransportError(cause: unknown, requestId: string): ApiError {
  const detail = cause instanceof Error ? cause.message : String(cause);
  return new ApiError({
    code: 'INTERNAL_ERROR',
    message: `The request could not reach the server (${detail}).`,
    status: 0,
    details: null,
    request_id: requestId,
    timestamp: asIsoDateTime(new Date().toISOString()),
    docs_url: null,
  });
}

/**
 * ★ An abort is a CANCELLATION, not a failure — and `uploadStore` (IU-25) explicitly
 *   distinguishes them ("rendering the user's own cancel as a red error is both
 *   wrong and alarming"). React Query also relies on `AbortError` propagating
 *   unwrapped to drop a superseded query silently.
 */
function isAbort(cause: unknown): boolean {
  return cause instanceof DOMException && cause.name === 'AbortError';
}

// ─────────────────────────────────────────────────────────────────────────────
// The request
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Open a STREAMING response — an MJPEG re-stream read frame by frame onto a canvas.
 *
 * ★ WHY IT LIVES HERE. §2.5's rule is that this module is the only thing that
 *   calls `fetch()`. A multipart stream cannot go through `fetchJson` (there is no
 *   JSON, and the body is read incrementally for minutes), so the one raw call the
 *   live player needs is exposed from here rather than made from a hook. The caller
 *   owns the reader; this mints the request id and nothing else.
 */
export function fetchStream(url: string, signal?: AbortSignal): Promise<Response> {
  // ★ The request id goes only to OUR server. On a third-party camera a custom
  //   header turns a simple GET into a preflighted one, which a camera that allows
  //   plain cross-origin reads would then refuse — breaking measured mode for the
  //   very sources that supported it.
  const ours =
    url.startsWith('/') || url.startsWith(API_BASE_URL) || url.startsWith(window.location.origin);
  return fetch(url, ours ? { signal, headers: { [REQUEST_ID_HEADER]: ulid() } } : { signal });
}

export type HttpMethod = 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';

export interface RequestOptions {
  method?: HttpMethod;
  query?: QueryParams;
  /**
   * JSON-encoded, unless it is a `FormData` (multipart — endpoints 9 and 54) or a
   * `Blob`. ★ `undefined` KEYS ARE DROPPED BY `JSON.stringify`, which is exactly
   * PATCH's UNSET semantics (§6.1): `{}` leaves untouched, `{"aoi": null}` clears.
   * That is why `XxxUpdate` fields are `T | null | undefined` and why this module
   * must never "normalise" a body.
   */
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  /** Endpoints 21 and 40 REQUIRE this. Falls back to {@link etagFor}. */
  ifMatch?: string;
  /** Endpoints 9 and 30 — `Idempotency-Key`. */
  idempotencyKey?: string;
  /** `X-Confirm-Delete` — endpoints 8, 15 and 19. */
  confirmDelete?: boolean;
  /** `json` (default) · `blob` for binary responses · `none` for 204. */
  parse?: 'json' | 'blob' | 'none';
  accept?: string;
  /**
   * ★ Statuses to parse as a SUCCESS body instead of throwing.
   *
   *   Exists for exactly one caller, and the contract names it: **`GET /health/ready`
   *   is "THE SINGLE EXPLICIT EXCEPTION to the error envelope" (§6.2)** — on `503` it
   *   returns a `ReadinessResponse` carrying the per-component check detail, not an
   *   `ErrorEnvelope`. Without this option the generic client would throw an
   *   `ApiError` with a synthesised body and **discard the diagnostics precisely when
   *   the system is unhealthy**, which §7.1 calls out as making a readiness endpoint
   *   useless.
   *
   *   Not a general escape hatch: every other non-2xx in this API is an
   *   `ErrorEnvelope` and must stay an `ApiError`.
   */
  okStatuses?: number[];
}

/**
 * ★ THE one entry point. Returns the full {@link Parsed} envelope.
 *
 * Use {@link fetchJson} unless you need `retryAfterMs`, `etag` or `location`.
 */
export async function request<T>(path: string, opts: RequestOptions = {}): Promise<Parsed<T>> {
  const {
    method = 'GET',
    query,
    body,
    headers = {},
    signal,
    ifMatch,
    idempotencyKey,
    confirmDelete,
    parse = 'json',
    accept,
    okStatuses,
  } = opts;

  const requestId = ulid();
  const isForm = typeof FormData !== 'undefined' && body instanceof FormData;
  const isBlob = typeof Blob !== 'undefined' && body instanceof Blob;
  const hasBody = body !== undefined;

  const finalHeaders: Record<string, string> = {
    [REQUEST_ID_HEADER]: requestId,
    Accept: accept ?? (parse === 'blob' ? '*/*' : 'application/json'),
    ...headers,
  };

  // ★ NEVER set Content-Type for FormData — the browser must append the multipart
  //   boundary itself, and an explicit header omits it, yielding a body the server
  //   cannot parse. A classic, and it fails only at runtime.
  if (hasBody && !isForm && !isBlob) finalHeaders['Content-Type'] = 'application/json';

  // ★ The registry fallback backs PATCH/PUT only. A GET or POST carrying a stale
  //   `If-Match` (registered by an earlier list or detail read) can be 412'd by a
  //   conformant server, and then the row could never refresh.
  const etag = ifMatch ?? (method === 'PATCH' || method === 'PUT' ? etagFor(path) : undefined);
  if (etag !== undefined) finalHeaders['If-Match'] = etag;
  if (idempotencyKey !== undefined) finalHeaders['Idempotency-Key'] = idempotencyKey;
  if (confirmDelete === true) finalHeaders['X-Confirm-Delete'] = 'true';

  let response: Response;
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      headers: finalHeaders,
      body: hasBody ? (isForm || isBlob ? (body as BodyInit) : JSON.stringify(body)) : undefined,
      signal,
      // ★ Same-origin by default (§9.11: the SPA and the API share an origin behind
      //   nginx). No credentials are sent cross-origin by accident.
      credentials: 'same-origin',
    });
  } catch (cause) {
    if (isAbort(cause)) throw cause;
    throw makeTransportError(cause, requestId);
  }

  const accepted = response.ok || okStatuses?.includes(response.status) === true;

  const responseEtag = response.headers.get('ETag');
  if (responseEtag !== null && response.ok) rememberEtag(path, responseEtag);

  if (!accepted) {
    let raw: unknown = null;
    try {
      raw = await response.json();
    } catch {
      // Not JSON — an nginx error page, a truncated body, an empty 502. Synthesised below.
    }
    throw makeApiError(raw, response.status, response.headers.get(REQUEST_ID_HEADER) ?? requestId);
  }

  const envelope = {
    retryAfterMs: parseRetryAfter(response.headers.get('Retry-After')),
    status: response.status,
    etag: responseEtag,
    location: response.headers.get('Location'),
    requestId: response.headers.get(REQUEST_ID_HEADER) ?? requestId,
  };

  if (parse === 'none' || response.status === 204) {
    return { data: undefined as T, ...envelope };
  }
  if (parse === 'blob') {
    return { data: (await response.blob()) as T, ...envelope };
  }

  // A 200 with an empty body is legal for some proxies; treat it as `undefined`
  // rather than exploding inside JSON.parse with a message about position 0.
  const text = await response.text();
  return { data: (text.length === 0 ? undefined : JSON.parse(text)) as T, ...envelope };
}

/** {@link request}, unwrapped. What every resource module uses. */
export async function fetchJson<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  return (await request<T>(path, opts)).data;
}

// ─────────────────────────────────────────────────────────────────────────────
// Upload — the one XMLHttpRequest, and why
// ─────────────────────────────────────────────────────────────────────────────

export interface UploadOptions {
  query?: QueryParams;
  idempotencyKey?: string;
  signal?: AbortSignal;
  /** Bytes sent / total. Fires on the browser's upload progress events only. */
  onProgress?: (bytesSent: number, bytesTotal: number) => void;
}

/**
 * ★ WHY XHR EXISTS IN THE ONE-`fetch()` MODULE.
 *
 *   **`fetch` cannot report upload progress.** There is no event, no callback, and
 *   `ReadableStream` request bodies are not supported for this case across our
 *   browser matrix. The choice is an XHR here or a PROGRESS BAR THAT LIES — and a
 *   400 MB orthophoto over a field uplink is precisely when a surveyor needs to know
 *   whether it is moving (§12 C-06: the highest-accuracy path in the product is also
 *   its biggest upload).
 *
 *   §2.5's rule is that `src/api/` is the only thing that talks to the network, and
 *   `uploadStore` (IU-25) states the reason exactly: an XHR opened from a store
 *   "would be a second, unauthenticated API client with no `ErrorEnvelope` parsing
 *   and no request id". So the XHR lives HERE, mints the same `X-Request-ID`, and
 *   throws the same `ApiError` through the same {@link makeApiError}. The rule is
 *   honoured in substance; the letter bends only where the platform forces it.
 */
export function upload<T>(path: string, form: FormData, opts: UploadOptions = {}): Promise<T> {
  const { query, idempotencyKey, signal, onProgress } = opts;
  const requestId = ulid();

  return new Promise<T>((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('Aborted', 'AbortError'));
      return;
    }

    const xhr = new XMLHttpRequest();
    xhr.open('POST', buildUrl(path, query), true);
    xhr.responseType = 'text';
    xhr.setRequestHeader(REQUEST_ID_HEADER, requestId);
    xhr.setRequestHeader('Accept', 'application/json');
    if (idempotencyKey !== undefined) xhr.setRequestHeader('Idempotency-Key', idempotencyKey);
    // ★ No Content-Type: the browser sets multipart/form-data + boundary itself.

    const onAbort = (): void => xhr.abort();
    signal?.addEventListener('abort', onAbort, { once: true });

    const cleanup = (): void => signal?.removeEventListener('abort', onAbort);

    if (onProgress) {
      xhr.upload.onprogress = (e: ProgressEvent): void => {
        // ★ `lengthComputable` is false for a chunked body; reporting 0/0 would make
        //   the bar jump to 100% and back. Silence is honest; a fake number is not.
        if (e.lengthComputable) onProgress(e.loaded, e.total);
      };
    }

    xhr.onload = (): void => {
      cleanup();
      let raw: unknown = null;
      try {
        raw = xhr.responseText.length > 0 ? JSON.parse(xhr.responseText) : null;
      } catch {
        // Non-JSON body — handled identically to the fetch path.
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(raw as T);
      } else {
        reject(
          makeApiError(raw, xhr.status, xhr.getResponseHeader(REQUEST_ID_HEADER) ?? requestId),
        );
      }
    };

    xhr.onerror = (): void => {
      cleanup();
      reject(makeTransportError(new Error('network error'), requestId));
    };

    xhr.ontimeout = (): void => {
      cleanup();
      reject(makeTransportError(new Error('timeout'), requestId));
    };

    xhr.onabort = (): void => {
      cleanup();
      reject(new DOMException('Aborted', 'AbortError'));
    };

    xhr.send(form);
  });
}
