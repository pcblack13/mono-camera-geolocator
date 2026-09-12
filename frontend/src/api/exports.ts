/**
 * Exports — endpoints 58–63 (§7).
 *
 * ★ FULLY BUILT (SCOPE.md §3): CSV · GeoJSON · Shapefile · KML · PDF report. Exports
 *   are real async jobs in this build and `useJob` polls them for real.
 *
 * ★★ SCOPE.md §5, THE INVARIANT: *"Uncommitted correspondences must never appear in
 *    the GCP table or an export."* Structurally guaranteed — an export reads `gcps`
 *    server-side, and an uncommitted correspondence is `correspondenceStore` state
 *    that never reached the server. There is no client-supplied GCP payload here to
 *    get wrong: `ExportFilter.gcp_ids` selects existing rows, it cannot introduce one.
 *
 * ★ `ExportFilter.source` is how an export separates observed GCPs from inferred ones
 *   (SCOPE.md §5). In this build every row is `source: 'manual'`.
 */

import type { Page, Uuid } from '../types/common';
import type {
  ExportFilters,
  ExportFormat,
  ExportRead,
  ExportRequest,
  ExportSummary,
} from '../types/export';
import type { JobRead } from '../types/job';
import { buildUrl, fetchJson, toQuery } from './client';

export const exportsApi = {
  /**
   * Endpoint 58 — `POST /images/{id}/export` → `202 JobRead`.
   *
   * ★ `format` is both a query param (§7) and a required field of `ExportRequest`
   *   (§6.2). Sent in both places, from the one value, so they cannot disagree.
   */
  startForImage: (imageId: Uuid, body: ExportRequest, signal?: AbortSignal): Promise<JobRead> =>
    fetchJson<JobRead>(`/images/${imageId}/export`, {
      method: 'POST',
      body,
      query: { format: body.format },
      signal,
    }),

  /** Endpoint 59 — `POST /projects/{id}/export` → `202 JobRead`. */
  startForProject: (projectId: Uuid, body: ExportRequest, signal?: AbortSignal): Promise<JobRead> =>
    fetchJson<JobRead>(`/projects/${projectId}/export`, {
      method: 'POST',
      body,
      query: { format: body.format },
      signal,
    }),

  /** Endpoint 60 — `GET /exports` → `200 Page[ExportSummary]`. */
  list: (f: ExportFilters = {}, signal?: AbortSignal): Promise<Page<ExportSummary>> =>
    fetchJson<Page<ExportSummary>>('/exports', { query: toQuery(f), signal }),

  /** Endpoint 61 — `GET /exports/{id}` → `200 ExportRead`. */
  get: (id: Uuid, signal?: AbortSignal): Promise<ExportRead> =>
    fetchJson<ExportRead>(`/exports/${id}`, { signal }),

  /**
   * Endpoint 62 — the artefact. **A URL, not a fetch.**
   *
   * ★ Navigating to this URL lets the browser stream a 200 MB shapefile to disk with
   *   a real progress UI and a `Content-Disposition` filename. Fetching it into a
   *   Blob would buffer the whole thing in JS heap to achieve strictly less. `409
   *   EXPORT_NOT_READY` · `410 EXPORT_EXPIRED` render as a normal navigation error —
   *   gate on `ExportRead.status` and `expires_at` before offering the link.
   *
   * ★ `lib/download.ts` (IU-25) triggers the navigation; it deliberately does no
   *   `fetch` of its own.
   */
  downloadUrl: (id: Uuid): string => buildUrl(`/exports/${id}/download`),

  /** Endpoint 63 — `DELETE /exports/{id}` → `204`. */
  remove: (id: Uuid, signal?: AbortSignal): Promise<void> =>
    fetchJson<void>(`/exports/${id}`, { method: 'DELETE', parse: 'none', signal }),
};

/** Formats that never need an optional dependency — always offered (§4.21). */
export const ALWAYS_AVAILABLE_FORMATS: readonly ExportFormat[] = ['csv', 'geojson', 'kml'] as const;
