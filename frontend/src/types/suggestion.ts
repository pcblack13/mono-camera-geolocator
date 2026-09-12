/**
 * Landmark suggestions — mirrors `backend/app/schemas/suggestion.py` (§6.2).
 *
 * ★★ DEFERRED (SCOPE.md §4): "Automatic landmark suggestions" is an ABC only.
 *    `POST /images/{id}/suggest-landmarks` is registered and documented and returns
 *    `501` with a `feature: "deferred"` marker. The `landmark_suggestions` table IS
 *    created exactly as specified — it simply holds no rows.
 *
 * ★ §8.8 / SCOPE.md §4 rule 4: `LandmarkSuggestions` with nothing behind it renders
 *   a CALM EXPLAINER, never an error and never a spinner that does not resolve.
 *
 * ★ WHY SUGGESTIONS ARE A SEPARATE RESOURCE (ADR-014): writing AI guesses straight
 *   into `annotations` would put unreviewed machine output into the surveyor's
 *   revision history, the undo stack, and — via `is_gcp_candidate` — the GCP
 *   deriver. **A suggestion is a proposal; an annotation is an assertion by a
 *   human.** The boundary between them is `POST …/accept`, and it is the only door.
 */

import type { IsoDateTime, Uuid, WarningItem } from './common';
import type { GeoJsonGeometry } from './geo';
import type { FeatureDetectorName } from './match';
import type { AnnotationGeomType, AnnotationKind, AnnotationRead } from './annotation';
import type { RevisionSummary } from './common';

export type SuggestionStatus = 'pending' | 'accepted' | 'rejected';

export type SuggestionStrategy = 'corners' | 'saliency' | 'semantic' | 'hybrid';

export interface LandmarkSuggestionRead {
  id: Uuid;
  image_id: Uuid;
  /** Which suggest job produced it. */
  aux_job_id: Uuid | null;
  kind: AnnotationKind;
  geom_type: AnnotationGeomType;
  pixel_x: number;
  pixel_y: number;
  /** IMAGE PIXELS, `[x, y]`, y-down, SRID 0. Not geographic. */
  pixel_geom: GeoJsonGeometry;
  /** ★ 0–1, the detector's own score. */
  score: number;
  /** 1 = best. */
  rank: number;
  detector: FeatureDetectorName;
  model_version: string | null;
  /** ★ Human-readable "why". A proposal a surveyor cannot interrogate is noise. */
  rationale: string | null;
  status: SuggestionStatus;
  /** Set on accept. */
  accepted_annotation_id: Uuid | null;
  decided_by: string | null;
  decided_at: IsoDateTime | null;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

/** ★ DEFERRED — returns `501` (SCOPE.md §4). */
export interface SuggestLandmarksRequest {
  strategy?: SuggestionStrategy;
  max_suggestions?: number;
  min_score?: number;
  kinds?: AnnotationKind[] | null;
}

export interface SuggestionAcceptedRef {
  suggestion_id: Uuid;
  annotation_id: Uuid;
  client_ref: string | null;
}

/**
 * `POST /images/{id}/suggestions/accept` — the only door from proposal to assertion.
 * Returns the same `AnnotationBulkUpsertResponse` shape as endpoint 45 (§6.2),
 * which is why `RevisionSummary` lives in `common.ts`.
 */
export interface SuggestionAcceptRequest {
  suggestion_ids: Uuid[];
  /** Override the proposed kind at accept time. */
  kind?: AnnotationKind | null;
  label_prefix?: string | null;
  /** The surveyor's own certainty, 0–1 — NOT the detector's `score`. */
  confidence?: number;
}

export interface SuggestionAcceptResponse {
  revision: RevisionSummary;
  accepted: SuggestionAcceptedRef[];
  annotations: AnnotationRead[];
  warnings: WarningItem[];
}

export interface SuggestionRejectRequest {
  suggestion_ids: Uuid[];
  reason?: string | null;
}

export interface SuggestionRejectResponse {
  rejected_ids: Uuid[];
  count: number;
}

export interface SuggestionFilters {
  status?: SuggestionStatus | SuggestionStatus[];
  kind?: AnnotationKind | AnnotationKind[];
  score__gte?: number;
  sort?: string;
  limit?: number;
  offset?: number;
}
