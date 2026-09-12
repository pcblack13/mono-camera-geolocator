/**
 * Landmark suggestions — endpoints 43–45 (§7).
 *
 * ★★ DEFERRED — SCOPE.md §4. Automatic landmark suggestion is an ABC only; `POST
 *    /images/{id}/suggest-landmarks` returns **`501`** with a `feature: "deferred"`
 *    marker. The `landmark_suggestions` table IS created and holds no rows (rule 5),
 *    so endpoint 44 answers `200` with an empty page — reading an empty table is not
 *    a deferred feature.
 *
 * ★ §8.8: `LandmarkSuggestions` with no weights renders **a calm explainer, never an
 *   error**.
 */

import type { Page, Uuid } from '../types/common';
import type { JobRead } from '../types/job';
import type {
  LandmarkSuggestionRead,
  SuggestionAcceptRequest,
  SuggestionAcceptResponse,
  SuggestionFilters,
  SuggestLandmarksRequest,
  SuggestionRejectRequest,
  SuggestionRejectResponse,
} from '../types/suggestion';
import { fetchJson, toQuery } from './client';

const base = (imageId: Uuid): string => `/images/${imageId}`;

export const suggestionsApi = {
  /** ★ DEFERRED — endpoint 43 → **`501`**. Live: `202 JobRead`. */
  start: (
    imageId: Uuid,
    body: SuggestLandmarksRequest = {},
    signal?: AbortSignal,
  ): Promise<JobRead> =>
    fetchJson<JobRead>(`${base(imageId)}/suggest-landmarks`, { method: 'POST', body, signal }),

  /** Endpoint 44 — `GET /images/{id}/landmark-suggestions` → `200 Page[LandmarkSuggestionRead]` (empty here). */
  list: (
    imageId: Uuid,
    f: SuggestionFilters = {},
    signal?: AbortSignal,
  ): Promise<Page<LandmarkSuggestionRead>> =>
    fetchJson<Page<LandmarkSuggestionRead>>(`${base(imageId)}/landmark-suggestions`, {
      query: toQuery(f),
      signal,
    }),

  /**
   * Endpoint 45 — `POST /images/{id}/landmark-suggestions/accept` → `200`.
   *
   * ★ §7 types the response `AnnotationBulkUpsertResponse`; IU-23 declares the richer
   *   `SuggestionAcceptResponse` (which adds `accepted: SuggestionAcceptedRef[]` on
   *   top of the same `revision`/`annotations`/`warnings`). IU-23's is used — it is
   *   the more specific mirror of §6.2 and the caller needs the suggestion→annotation
   *   mapping to clear the accepted rows. Flagged for IU-21.
   */
  accept: (
    imageId: Uuid,
    body: SuggestionAcceptRequest,
    signal?: AbortSignal,
  ): Promise<SuggestionAcceptResponse> =>
    fetchJson<SuggestionAcceptResponse>(`${base(imageId)}/landmark-suggestions/accept`, {
      method: 'POST',
      body,
      signal,
    }),

  /**
   * ★ NOT IN §7 — IU-23 declares `SuggestionRejectRequest`/`SuggestionRejectResponse`
   *   and `SuggestionStatus` has a `'rejected'` member, but the endpoint table has no
   *   reject row (only 43/44/45). Exposed at the symmetric path so the gap is visible;
   *   **no hook calls it**. Flagged for IU-21.
   */
  reject: (
    imageId: Uuid,
    body: SuggestionRejectRequest,
    signal?: AbortSignal,
  ): Promise<SuggestionRejectResponse> =>
    fetchJson<SuggestionRejectResponse>(`${base(imageId)}/landmark-suggestions/reject`, {
      method: 'POST',
      body,
      signal,
    }),
};
