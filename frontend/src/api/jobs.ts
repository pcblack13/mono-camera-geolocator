/**
 * Jobs — endpoints 31–33 (§7).
 *
 * ★ REAL JOBS STILL EXIST IN THIS BUILD. SCOPE.md defers the MATCHING engine, not
 *   async work: `ingest` (a 400 MB GeoTIFF upload), `export` (CSV/GeoJSON/Shapefile/
 *   KML/PDF) and `batch` (upload/metadata/export fan-out) all produce jobs the
 *   poller polls for real. `match`, `segment`, `suggest_landmarks` and
 *   `gcp_recompute` are the deferred `JobType`s — their POSTs return `501` and no job
 *   row is ever created.
 */

import type { Page, Uuid } from '../types/common';
import type { JobFilters, JobRead, JobSummary } from '../types/job';
import { fetchJson, request, toQuery, type Parsed } from './client';

export const jobsApi = {
  /** Endpoint 31 — `GET /jobs` → `200 Page[JobSummary]`. */
  list: (f: JobFilters = {}, signal?: AbortSignal): Promise<Page<JobSummary>> =>
    fetchJson<Page<JobSummary>>('/jobs', { query: toQuery(f), signal }),

  /**
   * ★★ Endpoint 32 — `GET /jobs/{id}` → `200 JobRead` + `ETag`, `Retry-After`.
   *
   * ★ THE ONE FUNCTION IN THIS UNIT THAT RETURNS `Parsed<T>` RATHER THAN `T`, and
   *   §8.4 mandates it: *"`src/api/client.ts` parses `Retry-After` and surfaces it on
   *   the response envelope … **The poller is the only consumer**"*, with the
   *   verbatim `queryFn: () => jobsApi.get(jobId!)  // -> { data: JobRead, retryAfterMs }`.
   *
   *   The consequence is real and is deliberate: **`useJob(id).data` is a
   *   `Parsed<JobRead>`, so the job is `data.data`.** Wrapping it in a `select` to
   *   unwrap would be prettier and would contradict §8.4's own code, which IU-28 is
   *   reading right now. Verbatim wins.
   *
   * ★ `wait` (0..30) is an OPTIONAL long-poll that subscribes to `job:{id}:events`
   *   and cuts poll traffic ~25×. It **falls back transparently** — if Redis pubsub
   *   is unavailable the server ignores it and answers immediately (L11). nginx's
   *   `proxy_read_timeout` is 60 s for exactly this.
   *
   *   ★ NOT USED by `useJob`: §8.4's verbatim poller passes no `wait`, and a
   *     30-second held request inside React Query's default 3-retry envelope is a
   *     behaviour change no unit asked for. Exposed so IU-28 can opt in per-screen.
   */
  get: (id: Uuid, wait?: number, signal?: AbortSignal): Promise<Parsed<JobRead>> =>
    request<JobRead>(`/jobs/${id}`, { query: { wait }, signal }),

  /**
   * Endpoint 33 — `DELETE /jobs/{id}` → `200 JobRead` · `202 JobRead` · `409`.
   *
   * ★ `202` means *cancellation requested*, not *cancelled*: `cancel_requested` is
   *   set and the worker checks it at the next stage boundary. `revoke(terminate=True)`
   *   is never used — a hard kill of a process holding GDAL handles orphans `.part`
   *   files. **So the poller must keep polling after a cancel** — the job is not
   *   terminal until the worker says so. `409 JOB_NOT_CANCELLABLE` means it already
   *   finished.
   */
  cancel: (id: Uuid, signal?: AbortSignal): Promise<JobRead> =>
    fetchJson<JobRead>(`/jobs/${id}`, { method: 'DELETE', signal }),
};
