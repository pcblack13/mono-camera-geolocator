/**
 * Semantic features — endpoints 46–47 (§7).
 *
 * ★★ DEFERRED — SCOPE.md §4. Semantic detection (field borders, roads, canals, trees,
 *    greenhouses, buildings, water, crop rows) is an ABC only; `POST
 *    /images/{id}/segment` returns **`501`** with a `feature: "deferred"` marker. The
 *    `semantic_features` table IS created and holds no rows (rule 5), so endpoint 46
 *    answers `200` with an empty page.
 */

import type { Page, Uuid } from '../types/common';
import type { JobRead } from '../types/job';
import type { SegmentRequest, SemanticFeatureRead, SemanticFilters } from '../types/semantic';
import { fetchJson, toQuery } from './client';

export const semanticsApi = {
  /**
   * Endpoint 46 — `GET /images/{id}/semantic-features` → `200 Page[SemanticFeatureRead]` (empty here).
   *
   * ★ `class` is a reserved word in JS but a legal object key and a legal query param;
   *   `SemanticFilters.class` is the wire name (L9) and is passed through untouched.
   */
  list: (
    imageId: Uuid,
    f: SemanticFilters = {},
    signal?: AbortSignal,
  ): Promise<Page<SemanticFeatureRead>> =>
    fetchJson<Page<SemanticFeatureRead>>(`/images/${imageId}/semantic-features`, {
      query: toQuery(f),
      signal,
    }),

  /** ★ DEFERRED — endpoint 47 `POST /images/{id}/segment` → **`501`**. Live: `202 JobRead`. */
  segment: (imageId: Uuid, body: SegmentRequest = {}, signal?: AbortSignal): Promise<JobRead> =>
    fetchJson<JobRead>(`/images/${imageId}/segment`, { method: 'POST', body, signal }),
};
