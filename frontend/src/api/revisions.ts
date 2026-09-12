/**
 * Revisions and annotation versions — endpoints 23–29 (§7).
 *
 * ★ `annotation_versions.id` is `BIGSERIAL` and is serialised as a JSON **number**,
 *   not a UUID string (§6.1). It is the one id in this API that is not a `Uuid`, and
 *   §6.1 says the asymmetry "is called out in every schema that touches it" — so it
 *   is called out here.
 */

import type { Page, RevisionSummary, Uuid } from '../types/common';
import type {
  AnnotationVersionFilters,
  AnnotationVersionRead,
  AnnotationVersionSummary,
  RevisionCreate,
  RevisionRead,
  RevisionRestoreRequest,
  RevisionRestoreResponse,
} from '../types/annotation';
import { fetchJson, toQuery } from './client';

/**
 * `RevisionListParams` (§6.2, endpoint 23).
 *
 * ★ DECLARED HERE — IU-23 owns `types/**` and declared no revision list filter.
 *   Belongs in `types/annotation.ts`; flagged for IU-23.
 */
export interface RevisionFilters {
  is_checkpoint?: boolean;
  q?: string;
  sort?: string;
  limit?: number;
  offset?: number;
}

/**
 * Endpoint 25's query params. `include_snapshot` materially changes the response
 * body's size, so it is part of the cache key (`qk.revisions.detailWith`).
 *
 * ★ DECLARED HERE — flagged for IU-23.
 */
export interface RevisionDetailParams {
  include_snapshot?: boolean;
  image_id?: Uuid;
}

export const revisionsApi = {
  /** Endpoint 23 — `GET /projects/{id}/revisions` → `200 Page[RevisionSummary]`. */
  listForProject: (
    projectId: Uuid,
    f: RevisionFilters = {},
    signal?: AbortSignal,
  ): Promise<Page<RevisionSummary>> =>
    fetchJson<Page<RevisionSummary>>(`/projects/${projectId}/revisions`, {
      query: toQuery(f),
      signal,
    }),

  /** Endpoint 24 — `POST /projects/{id}/revisions` → `201 RevisionRead`. */
  create: (projectId: Uuid, body: RevisionCreate, signal?: AbortSignal): Promise<RevisionRead> =>
    fetchJson<RevisionRead>(`/projects/${projectId}/revisions`, { method: 'POST', body, signal }),

  /** Endpoint 25 — `GET /revisions/{id}` → `200 RevisionRead`. */
  get: (id: Uuid, params: RevisionDetailParams = {}, signal?: AbortSignal): Promise<RevisionRead> =>
    fetchJson<RevisionRead>(`/revisions/${id}`, { query: toQuery(params), signal }),

  /**
   * Endpoint 26 — `POST /revisions/{id}/restore` → `200 RevisionRestoreResponse`.
   *
   * ★ A restore rewrites the annotations of an image, which marks every linked GCP
   *   `is_stale` with `stale_reason: 'annotations_restored'` — it **never**
   *   recomputes one (`GcpRead.is_stale`: "a GCP changes when a human decides it
   *   changes"). `useRevisions` invalidates the GCP cache accordingly.
   */
  restore: (
    id: Uuid,
    body: RevisionRestoreRequest,
    signal?: AbortSignal,
  ): Promise<RevisionRestoreResponse> =>
    fetchJson<RevisionRestoreResponse>(`/revisions/${id}/restore`, {
      method: 'POST',
      body,
      signal,
    }),

  /**
   * Endpoint 27 — `GET /images/{id}/annotation-versions` → `200 Page[AnnotationVersionSummary]`.
   *
   * ★ `offset` XOR `before_id` — sending both is `422 PARAM_CONFLICT`. `before_id` is
   *   the keyset mode for the undo stack's infinite scroll, where `offset` would skip
   *   events as new ones land.
   */
  versionsForImage: (
    imageId: Uuid,
    f: AnnotationVersionFilters = {},
    signal?: AbortSignal,
  ): Promise<Page<AnnotationVersionSummary>> =>
    fetchJson<Page<AnnotationVersionSummary>>(`/images/${imageId}/annotation-versions`, {
      query: toQuery(f),
      signal,
    }),

  /** Endpoint 28 — `GET /annotations/{id}/versions` → `200 Page[AnnotationVersionSummary]`. */
  versionsForAnnotation: (
    annotationId: Uuid,
    f: AnnotationVersionFilters = {},
    signal?: AbortSignal,
  ): Promise<Page<AnnotationVersionSummary>> =>
    fetchJson<Page<AnnotationVersionSummary>>(`/annotations/${annotationId}/versions`, {
      query: toQuery(f),
      signal,
    }),

  /** Endpoint 29 — `GET /annotation-versions/{version_id}`. ★ `versionId` is a NUMBER (§6.1). */
  version: (versionId: number, signal?: AbortSignal): Promise<AnnotationVersionRead> =>
    fetchJson<AnnotationVersionRead>(`/annotation-versions/${versionId}`, { signal }),
};
