/**
 * Offline Area Manager — `/imagery/offline/*` + `/imagery/usage`.
 *
 * ★ The pre-cache runs SERVER-SIDE now: the backend enumerates the AOI's XYZ tiles,
 *   checks its own cache, enforces the request budgets (LE_MAPBOX_MAX_*), downloads with
 *   bounded concurrency through the same read-through cache the live map uses, and writes
 *   the offline manifest. The client's job is the polygon, the zoom band, and honest
 *   display of the server's estimate/progress — not the download loop it used to run
 *   (which could not see the cache, the budgets, or survive a page navigation).
 */

import { fetchJson } from './client';

/** One AOI vertex, `(lon, lat)` — GeoJSON axis order. */
export type LonLat = [number, number];

export type BasemapKindStr = 'satellite' | 'hybrid' | 'terrain';

export interface OfflineAreaRequest {
  provider: string;
  kind: BasemapKindStr;
  polygon: LonLat[];
  zoom_min: number;
  zoom_max: number;
  project_id?: string | null;
}

export interface PrecacheBudget {
  per_operation_limit: number | null;
  max_prefetch_tiles: number | null;
  per_day_limit: number | null;
  per_day_used: number;
  within_budget: boolean;
  reason: string | null;
}

export interface OfflineEstimate {
  provider: string;
  zoom_min: number;
  zoom_max: number;
  total_tiles: number;
  cached_tiles: number;
  missing_tiles: number;
  estimated_upstream_requests: number;
  average_tile_size_bytes: number;
  /** `measured` = sampled from this machine's own cache; `default` = stated constant. */
  average_tile_size_source: 'measured' | 'default';
  estimated_storage_bytes: number;
  capped: boolean;
  budget: PrecacheBudget;
}

export type PrecacheState = 'pending' | 'running' | 'paused' | 'completed' | 'cancelled' | 'failed';

export interface PrecacheOperation {
  id: string;
  state: PrecacheState;
  provider: string;
  kind: BasemapKindStr;
  zoom_min: number;
  zoom_max: number;
  project_id: string | null;
  total_tiles: number;
  completed_tiles: number;
  skipped_cached: number;
  no_imagery_tiles: number;
  failed_tiles: number;
  remaining_tiles: number;
  downloaded_bytes: number;
  percent: number;
  started_at: string | null;
  finished_at: string | null;
  note: string | null;
  manifest_id: string | null;
}

export interface OfflineManifest {
  id: string;
  project_id: string | null;
  provider: string;
  kind: BasemapKindStr;
  cache_variant: string;
  polygon: LonLat[];
  bbox: [number, number, number, number];
  zoom_min: number;
  zoom_max: number;
  tile_size_px: number;
  tile_count: number;
  completed_tiles: number;
  no_imagery_tiles: number;
  missing_tiles: number;
  downloaded_bytes: number;
  created_at: string;
  expires_at: string | null;
}

export interface OfflineCoverage {
  provider: string;
  total_tiles: number;
  cached_tiles: number;
  coverage_ratio: number;
  by_zoom: Record<string, { total: number; cached: number }>;
  capped: boolean;
}

export const offlineApi = {
  estimate: (body: OfflineAreaRequest, signal?: AbortSignal): Promise<OfflineEstimate> =>
    fetchJson<OfflineEstimate>('/imagery/offline/estimate', { method: 'POST', body, signal }),

  coverage: (body: OfflineAreaRequest, signal?: AbortSignal): Promise<OfflineCoverage> =>
    fetchJson<OfflineCoverage>('/imagery/offline/coverage', { method: 'POST', body, signal }),

  start: (body: OfflineAreaRequest): Promise<PrecacheOperation> =>
    fetchJson<PrecacheOperation>('/imagery/offline/operations', { method: 'POST', body }),

  listOperations: (signal?: AbortSignal): Promise<PrecacheOperation[]> =>
    fetchJson<PrecacheOperation[]>('/imagery/offline/operations', { signal }),

  getOperation: (id: string, signal?: AbortSignal): Promise<PrecacheOperation> =>
    fetchJson<PrecacheOperation>(`/imagery/offline/operations/${id}`, { signal }),

  pause: (id: string): Promise<PrecacheOperation> =>
    fetchJson<PrecacheOperation>(`/imagery/offline/operations/${id}/pause`, { method: 'POST' }),

  resume: (id: string): Promise<PrecacheOperation> =>
    fetchJson<PrecacheOperation>(`/imagery/offline/operations/${id}/resume`, { method: 'POST' }),

  cancel: (id: string): Promise<PrecacheOperation> =>
    fetchJson<PrecacheOperation>(`/imagery/offline/operations/${id}/cancel`, { method: 'POST' }),

  retry: (id: string): Promise<PrecacheOperation> =>
    fetchJson<PrecacheOperation>(`/imagery/offline/operations/${id}/retry`, { method: 'POST' }),

  listManifests: (signal?: AbortSignal): Promise<OfflineManifest[]> =>
    fetchJson<OfflineManifest[]>('/imagery/offline/manifests', { signal }),

  deleteManifest: (id: string): Promise<void> =>
    fetchJson<void>(`/imagery/offline/manifests/${id}`, { method: 'DELETE', parse: 'none' }),
};

// ── automatic viewport caching ────────────────────────────────────────────────

/** A settled viewport, in PROVIDER zoom levels (map zoom minus the 512px zoomShift). */
export interface ViewportReport {
  provider: string;
  kind: BasemapKindStr;
  west: number;
  south: number;
  east: number;
  north: number;
  zoom: number;
  project_id?: string | null;
}

export interface AutoCacheSession {
  started_at: string;
  project_id: string | null;
  tiles_requested: number;
  tiles_downloaded: number;
  tiles_skipped_cached: number;
  tiles_no_imagery: number;
  tiles_failed: number;
  bytes_downloaded: number;
  limit_reached: string | null;
}

export interface AutoCacheStatus {
  enabled: boolean;
  online: boolean;
  active: boolean;
  provider: string | null;
  kind: BasemapKindStr;
  zoom: number | null;
  viewport_tiles: number;
  cached_tiles: number;
  missing_tiles: number;
  coverage_percent: number | null;
  queued_tiles: number;
  /** More missing tiles remain beyond this chunk — re-report on drain to continue. */
  truncated: boolean;
  note: string | null;
  session: AutoCacheSession;
}

export const autoCacheApi = {
  /** Report a settled viewport — queues background caching, returns coverage. */
  reportViewport: (body: ViewportReport, signal?: AbortSignal): Promise<AutoCacheStatus> =>
    fetchJson<AutoCacheStatus>('/imagery/cache/viewport', { method: 'POST', body, signal }),

  getStatus: (signal?: AbortSignal): Promise<AutoCacheStatus> =>
    fetchJson<AutoCacheStatus>('/imagery/cache/status', { signal }),

  setEnabled: (enabled: boolean): Promise<AutoCacheStatus> =>
    fetchJson<AutoCacheStatus>('/imagery/cache/enabled', { method: 'PUT', body: { enabled } }),
};

/** Human-readable byte size for estimates ("1.7 GB"). */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '—';
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let value = bytes;
  let unit = -1;
  do {
    value /= 1024;
    unit += 1;
  } while (value >= 1024 && unit < units.length - 1);
  return `${value.toFixed(value >= 100 ? 0 : 1)} ${units[unit]}`;
}
