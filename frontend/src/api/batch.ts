/**
 * Batch — endpoints 54–57 (§7).
 *
 * ★★ PARTIALLY DEFERRED, and the split is precise (SCOPE.md §3): *"Batch processing of
 *    multiple uploaded images — **BUILD** — batch upload/metadata/export only; **no
 *    batch matching**"*.
 *
 *    A batch that fans out to `match` jobs is a deferred feature wearing a batch, and
 *    IU-23's `types/batch.ts` says so: such a create *"returns `501` at creation with a
 *    `feature: "deferred"` marker rather than fanning out into a group of jobs that
 *    each 501"* — which would be 40 rows of red for one deferred feature.
 *
 *    ★ `BatchCreate`'s shape betrays its origin: `search_hint`, `options:
 *      MatchOptions`, `provider`. Those fields only make sense for matching. A batch
 *      UPLOAD or EXPORT in this build sends none of them. Flagged for IU-17/IU-21:
 *      `BatchCreate` needs a discriminator (a `job_type`) for the built half to be
 *      expressible at all — as written, every `BatchCreate` reads as a match batch.
 */

import type { Page, Uuid } from '../types/common';
import type { BatchCreate, BatchFilters, BatchRead, BatchSummary } from '../types/batch';
import { fetchJson, toQuery, upload, type UploadOptions } from './client';

/**
 * `BatchUploadForm` (§6.2) — the multipart half of endpoint 54.
 *
 * ★ DECLARED HERE — IU-23 declared `BatchCreate` (the JSON half) but not the
 *   multipart one. Belongs in `types/batch.ts`; flagged for IU-23.
 */
export interface BatchUploadForm {
  files: File[];
  project_id: Uuid;
  name?: string;
  concurrency?: number;
  on_error?: 'continue' | 'abort';
}

export const batchApi = {
  /**
   * Endpoint 54 — `POST /batch` (JSON) → `202 BatchRead`.
   *
   * ★ Returns **`501`** in this build when the batch would fan out to `match` jobs.
   */
  create: (body: BatchCreate & { project_id: Uuid }, signal?: AbortSignal): Promise<BatchRead> =>
    fetchJson<BatchRead>('/batch', { method: 'POST', body, signal }),

  /** Endpoint 54 — `POST /batch` (multipart) → `202 BatchRead`. The BUILT half: batch upload. */
  upload: (form: BatchUploadForm, opts: UploadOptions = {}): Promise<BatchRead> => {
    const fd = new FormData();
    for (const file of form.files) fd.append('files', file, file.name);
    fd.append('project_id', form.project_id);
    if (form.name !== undefined) fd.append('name', form.name);
    if (form.concurrency !== undefined) fd.append('concurrency', String(form.concurrency));
    if (form.on_error !== undefined) fd.append('on_error', form.on_error);
    return upload<BatchRead>('/batch', fd, opts);
  },

  /** Endpoint 55 — `GET /batch` → `200 Page[BatchSummary]`. */
  list: (f: BatchFilters = {}, signal?: AbortSignal): Promise<Page<BatchSummary>> =>
    fetchJson<Page<BatchSummary>>('/batch', { query: toQuery(f), signal }),

  /** Endpoint 56 — `GET /batch/{id}` → `200 BatchRead`. */
  get: (id: Uuid, signal?: AbortSignal): Promise<BatchRead> =>
    fetchJson<BatchRead>(`/batch/${id}`, { signal }),

  /**
   * Endpoint 57 — `DELETE /batch/{id}` → `202 BatchRead` · `409`.
   *
   * ★ `202`, like a job cancel: `cancel_requested` is set and the children stop
   *   cooperatively. Keep polling — the batch is not terminal until it says so.
   */
  cancel: (id: Uuid, signal?: AbortSignal): Promise<BatchRead> =>
    fetchJson<BatchRead>(`/batch/${id}`, { method: 'DELETE', signal }),
};
