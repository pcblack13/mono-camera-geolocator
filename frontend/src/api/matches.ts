/**
 * Matching — endpoints 30, 34–37 (§7).
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * ★★ DEFERRED SURFACE — SCOPE.md §1 and §4 rule 3.
 *
 *   **`POST /images/{id}/match` (endpoint 30) returns `501` in this build**, with the
 *   uniform error envelope and a `feature: "deferred"` marker. It is registered and
 *   documented; it must not 404 (the feature is planned, not absent) and must not
 *   fake a result.
 *
 *   This module is written in full anyway, because **the seam is real, not
 *   decorative** (SCOPE.md §4 rule 1): re-enabling the engine must require zero
 *   changes outside `ai_engine/` plus flipping the endpoints from 501 to live
 *   (SCOPE.md §7). A caller of `matchesApi.start` must not change one character.
 *
 *   Endpoints 34–37 read `match_results`, a table that **is created and simply holds
 *   no rows** in this build (SCOPE.md §4 rule 5). They therefore answer `200` with an
 *   empty page — honestly. They are NOT 501: reading an empty table is not a
 *   deferred feature, it is an empty table.
 * ─────────────────────────────────────────────────────────────────────────────
 */

import type { Page, Uuid } from '../types/common';
import type { JobRead } from '../types/job';
import type {
  MatchFilters,
  MatchRequest,
  MatchResultRead,
  MatchResultSelectRequest,
  MatchResultSummary,
  SatelliteImageParams,
} from '../types/match';
import { buildUrl, fetchJson, toQuery } from './client';

export interface StartMatchOptions {
  /** `?force=true` overrides `409 MATCH_JOB_ALREADY_RUNNING`. */
  force?: boolean;
  /** `Idempotency-Key` — the double-click guard (§12 C-27). */
  idempotencyKey?: string;
  signal?: AbortSignal;
}

export const matchesApi = {
  /**
   * ★ DEFERRED — endpoint 30 `POST /images/{id}/match` → **`501`** in this build.
   *   Live: `202 JobRead` + `Location`, `Retry-After: 1`.
   */
  start: (imageId: Uuid, body: MatchRequest = {}, opts: StartMatchOptions = {}): Promise<JobRead> =>
    fetchJson<JobRead>(`/images/${imageId}/match`, {
      method: 'POST',
      body,
      query: { force: opts.force },
      idempotencyKey: opts.idempotencyKey,
      signal: opts.signal,
    }),

  /** Endpoint 34 — `GET /images/{id}/match-results` → `200 Page[MatchResultSummary]` (empty in this build). */
  listResults: (
    imageId: Uuid,
    f: MatchFilters = {},
    signal?: AbortSignal,
  ): Promise<Page<MatchResultSummary>> =>
    fetchJson<Page<MatchResultSummary>>(`/images/${imageId}/match-results`, {
      query: toQuery(f),
      signal,
    }),

  /** Endpoint 35 — `GET /match-results/{id}` → `200 MatchResultRead`. */
  getResult: (id: Uuid, signal?: AbortSignal): Promise<MatchResultRead> =>
    fetchJson<MatchResultRead>(`/match-results/${id}`, { signal }),

  /**
   * Endpoint 36 — a URL, not a fetch (it is an `<img src>`).
   *
   * ★ The response carries `X-Imagery-Attribution`, which a browser cannot read from
   *   an `<img>`. **Render the attribution from `MatchResultRead.attribution`** — a
   *   required field, served from the `match_results` row rather than by re-resolving
   *   the provider (which may have been reconfigured since the pixels were fetched).
   *   Attribution is a licence condition; pixels do not travel without their credit.
   */
  satelliteImageUrl: (
    id: Uuid,
    params: SatelliteImageParams & { overlay?: boolean } = {},
  ): string => buildUrl(`/match-results/${id}/satellite-image`, toQuery(params)),

  /** Endpoint 37 — `POST /match-results/{id}/select` → `200 MatchResultRead`. */
  selectResult: (
    id: Uuid,
    body: MatchResultSelectRequest,
    signal?: AbortSignal,
  ): Promise<MatchResultRead> =>
    fetchJson<MatchResultRead>(`/match-results/${id}/select`, { method: 'POST', body, signal }),
};
