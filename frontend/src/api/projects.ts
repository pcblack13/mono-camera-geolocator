/**
 * Projects — endpoints 4–8 (§7).
 *
 * ★ No `fetch` here or in any sibling: every call goes through `client.ts` (§2.5).
 */

import type { Page, Uuid } from '../types/common';
import type {
  ProjectCreate,
  ProjectExportResult,
  ProjectFilters,
  ProjectRead,
  ProjectSummary,
  ProjectUpdate,
} from '../types/project';
import { fetchJson, forgetEtag, toQuery } from './client';

const path = (id: Uuid): string => `/projects/${id}`;

export const projectsApi = {
  /** Endpoint 4 — `POST /projects` → `201 ProjectRead` + `Location`. */
  create: (body: ProjectCreate, signal?: AbortSignal): Promise<ProjectRead> =>
    fetchJson<ProjectRead>('/projects', { method: 'POST', body, signal }),

  /** Endpoint 5 — `GET /projects` → `200 Page[ProjectSummary]`. */
  list: (f: ProjectFilters = {}, signal?: AbortSignal): Promise<Page<ProjectSummary>> =>
    fetchJson<Page<ProjectSummary>>('/projects', { query: toQuery(f), signal }),

  /** Endpoint 6 — `GET /projects/{id}` → `200 ProjectRead` + `ETag`. */
  get: (id: Uuid, includeDeleted = false, signal?: AbortSignal): Promise<ProjectRead> =>
    fetchJson<ProjectRead>(path(id), { query: { include_deleted: includeDeleted }, signal }),

  /**
   * Endpoint 7 — `PATCH /projects/{id}`, `If-Match?` (optional here, unlike
   * endpoints 21/40). The client sends the last-seen `ETag` automatically; pass
   * `etag` to override.
   *
   * ★ UNSET semantics (§6.1): omit a key to leave it untouched, send `null` to clear.
   *   `JSON.stringify` drops `undefined` keys, so `ProjectUpdate`'s
   *   `T | null | undefined` typing does this for free — do not "normalise" the body.
   */
  update: (
    id: Uuid,
    body: ProjectUpdate,
    etag?: string,
    signal?: AbortSignal,
  ): Promise<ProjectRead> =>
    fetchJson<ProjectRead>(path(id), { method: 'PATCH', body, ifMatch: etag, signal }),

  /**
   * Endpoint 8 — `DELETE /projects/{id}` → `204`.
   *
   * ★ `hard: true` REQUIRES `X-Confirm-Delete` — a hard delete drops the GCPs, the
   *   exports and the revision history with them.
   */
  remove: async (id: Uuid, hard = false, signal?: AbortSignal): Promise<void> => {
    await fetchJson<void>(path(id), {
      method: 'DELETE',
      query: { hard },
      confirmDelete: hard,
      parse: 'none',
      signal,
    });
    // The id is gone; a recreated one must not inherit its ETag.
    forgetEtag(path(id));
  },

  /**
   * Write a self-contained folder of this project (photos, GCPs, DEM, solve
   * outputs, LUTs) into the visible LandExplorer directory — 2026-09-03.
   */
  exportFolder: (id: Uuid, signal?: AbortSignal): Promise<ProjectExportResult> =>
    fetchJson<ProjectExportResult>(`${path(id)}/export-folder`, { method: 'POST', signal }),
};
