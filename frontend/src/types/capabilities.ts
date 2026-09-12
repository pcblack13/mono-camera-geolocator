/**
 * `GET /capabilities` — mirrors `backend/app/schemas/capabilities.py` (§6.2).
 *
 * ★ The report is computed ONCE in `main.py`'s lifespan and cached on `app.state`
 *   (§11.1). This endpoint READS the cache and never re-resolves — re-sha256'ing a
 *   2.4 GB SAM checkpoint per request is not a health check, it is an outage.
 *
 * ★ SCOPE.md §4: in this build every deep-model path resolves to DEFERRED rather
 *   than to a classical fallback, because the classical path is deferred too. The
 *   `status` field below is how `models/policy.py` expresses that without
 *   special-casing callers.
 */

import type { IsoDateTime } from './common';
import type { ExportFormat } from './export';
import type { EstimatorName, ExtractorName, MatcherName } from './match';
import type { ProviderId } from './geo';

/**
 * ★ `available: false` NEVER means "you may not request it" (§6.2). The API accepts
 *   `matcher: "superglue"` on a weightless box and returns a job that warns and
 *   falls back. It means *"if you pick this, you will get `fallback` instead."*
 *   The frontend renders such options disabled with `reason` as the tooltip.
 *
 * ★ SCOPE.md §4 rule 4: a DEFERRED component renders disabled with an honest
 *   tooltip ("Automatic matching is not enabled in this build — place GCPs
 *   manually"). No spinner that never resolves, no fake confidence, no placeholder
 *   coordinates.
 */
export interface CapabilityItem {
  name: string;
  available: boolean;
  kind: 'classical' | 'deep';
  requires_weights: boolean;
  /**
   * ★ `deferred` is a first-class status, distinct from `unavailable` (SCOPE.md §4):
   *   - `available`   — resolves and runs.
   *   - `unavailable` — a weight/key/dep is missing; you get `fallback` instead.
   *   - `deferred`    — NOT IMPLEMENTED IN THIS BUILD. The interface exists; the
   *     body raises `NotImplementedDeferred`. There is no fallback, because the
   *     fallback is deferred too. The UI must say so plainly rather than offer a
   *     substitute that also will not run.
   */
  status: 'available' | 'unavailable' | 'deferred';
  /** e.g. "Weights not found at /models/superpoint_v1.pth" — or a pointer to SCOPE.md. */
  reason: string | null;
  /** What you WILL get if you pick this anyway. `null` when `status === 'deferred'`. */
  fallback: string | null;
}

export interface ExportCapability {
  format: ExportFormat;
  available: boolean;
  /** e.g. "geopandas is not installed". */
  reason: string | null;
  requires_extra: string | null;
}

export interface ComputeInfo {
  /** ★ Never inferred from a build name: a `cu130` wheel with no usable GPU is `cpu`. */
  device: 'cpu' | 'cuda';
  torch_available: boolean;
  torch_version: string | null;
  cuda_available: boolean;
  gpu_name: string | null;
  opencv_version: string;
  numpy_version: string;
  /** Which backend `gis.rasterio_shim.probe()` bound: `rasterio` | `gdal` | `none`. */
  raster_backend: string;
  worker_count: number;
}

export interface LimitsInfo {
  upload_max_bytes: number;
  async_ingest_threshold_bytes: number;
  max_image_pixels: number;
  max_image_dimension: number;
  max_annotations_per_image: number;
  max_tiles_per_match: number;
  max_search_radius_m: number;
  max_timeout_s: number;
  max_replay_events: number;
  max_batch_items: number;
}

export interface DefaultsInfo {
  /** ★ The frontend NEVER hard-codes these — they come from the server (§8.7). */
  provider: ProviderId;
  extractor: ExtractorName;
  matcher: MatcherName;
  estimator: EstimatorName;
  search_radius_m: number;
  search_zoom: number;
  min_confidence: number;
}

export interface CapabilitiesResponse {
  version: string;
  engine_version: string;
  extractors: CapabilityItem[];
  matchers: CapabilityItem[];
  estimators: CapabilityItem[];
  segmenters: CapabilityItem[];
  suggesters: CapabilityItem[];
  providers: CapabilityItem[];
  elevation_providers: CapabilityItem[];
  exports: ExportCapability[];
  compute: ComputeInfo;
  limits: LimitsInfo;
  defaults: DefaultsInfo;
  /**
   * ★ SCOPE.md §1. The names of the features this build defers, so the UI can gate
   *   controls off ONE server-provided list rather than a hard-coded constant that
   *   must be edited when the engine lands (SCOPE.md §7: re-enabling must not
   *   require changes outside `ai_engine/` plus flipping the endpoints).
   *
   *   In this build: matching, feature extraction, RANSAC, pose, heatmap,
   *   segmentation, landmark suggestion.
   */
  deferred_features: string[];
  checked_at: IsoDateTime;
}

// ─────────────────────────────────────────────────────────────────────────────
// Health (§6.2 `health.py`)
// ─────────────────────────────────────────────────────────────────────────────

export type HealthStatus = 'ok' | 'degraded' | 'not_ready';

export type ComponentStatus = 'up' | 'degraded' | 'down' | 'skipped';

export interface ComponentHealth {
  name: string;
  status: ComponentStatus;
  latency_ms: number | null;
  message: string | null;
}

export interface HealthResponse {
  status: HealthStatus;
  version: string;
  uptime_s: number;
}

/**
 * ★ THE SINGLE EXPLICIT EXCEPTION to the error envelope (§6.2): `GET /health/ready`
 *   returns this on 503, not an `ErrorEnvelope` — a probe wants the check detail,
 *   and that response is not an application error.
 */
export interface ReadinessResponse {
  status: HealthStatus;
  components: ComponentHealth[];
  checked_at: IsoDateTime;
}

// ─────────────────────────────────────────────────────────────────────────────
// Logs (`GET /health/logs` — the app-status page's monitor)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * One captured log line. Everything here already went through the server's
 * secret-scrubber (§9.10) — the buffer captures after the same chain stdout gets.
 */
export interface LogRecordEntry {
  /** Monotonic cursor — poll with `?after=<last seen seq>`. */
  seq: number;
  timestamp: string;
  level: string;
  logger: string | null;
  /** The log message (structlog's `event`). */
  event: string;
  /** The same id an `ErrorEnvelope` carries — what links a failure to its lines. */
  request_id: string | null;
  /** The formatted traceback, when the line carried one. */
  exception: string | null;
  /** Every other structured field the line carried. */
  fields: Record<string, unknown>;
}

export interface LogsResponse {
  /** The newest matching lines, oldest first. */
  entries: LogRecordEntry[];
  /** The buffer's cursor regardless of filters — pass back as `?after=`. */
  last_seq: number;
  /** Seqs at or below this were evicted from the bounded buffer. */
  dropped_before: number;
  capacity: number;
  checked_at: IsoDateTime;
}
