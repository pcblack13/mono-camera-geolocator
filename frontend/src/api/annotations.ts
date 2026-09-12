/**
 * Annotations — endpoints 16–22 (§7).
 *
 * ★ Endpoint 21 (`PATCH /annotations/{id}`) REQUIRES `If-Match`. The client sends the
 *   last `ETag` it saw for the path automatically (see `client.ts`'s ETag registry);
 *   a caller holding a fresher one passes it explicitly. With neither, the server
 *   answers `428 PRECONDITION_REQUIRED` — loudly, which is the point.
 *
 * ★ SCOPE.md §5: moving a point ON THE PHOTOGRAPH is an annotation edit, and it is
 *   what marks a linked GCP stale. Moving the coordinate on the MAP is
 *   `PATCH /gcps/{id}`. **Two endpoints, two meanings** (§8.5) — do not route one
 *   through the other.
 */

import type { Page, Uuid } from '../types/common';
import type {
  AnnotationBulkUpsertRequest,
  AnnotationBulkUpsertResponse,
  AnnotationCreate,
  AnnotationKind,
  AnnotationRead,
  AnnotationUpdate,
} from '../types/annotation';
import { fetchJson, forgetEtag, toQuery } from './client';

/**
 * `AnnotationListParams` (§6.2, endpoint 16).
 *
 * ★ DECLARED HERE, NOT IN `types/` — IU-23 owns `src/types/**` and shipped
 *   `AnnotationVersionFilters` but no `AnnotationFilters`, while §7 endpoint 16 takes
 *   `AnnotationListParams`. Inlining `any` at the call site is exactly the drift §8.1
 *   exists to prevent, and this unit may not write into `types/`. **Belongs in
 *   `types/annotation.ts`; flagged for IU-23.**
 */
export interface AnnotationFilters {
  kind?: AnnotationKind | AnnotationKind[];
  is_gcp_candidate?: boolean;
  include_deleted?: boolean;
  revision_seq?: number;
  q?: string;
  sort?: string;
  limit?: number;
  offset?: number;
}

const nested = (imageId: Uuid): string => `/images/${imageId}/annotations`;
const flat = (id: Uuid): string => `/annotations/${id}`;

export const annotationsApi = {
  /** Endpoint 16 — `GET /images/{id}/annotations` → `200 Page[AnnotationRead]` + `ETag`. */
  list: (
    imageId: Uuid,
    f: AnnotationFilters = {},
    signal?: AbortSignal,
  ): Promise<Page<AnnotationRead>> =>
    fetchJson<Page<AnnotationRead>>(nested(imageId), { query: toQuery(f), signal }),

  /** Endpoint 17 — `POST /images/{id}/annotations` → `201 AnnotationRead`. */
  create: (imageId: Uuid, body: AnnotationCreate, signal?: AbortSignal): Promise<AnnotationRead> =>
    fetchJson<AnnotationRead>(nested(imageId), { method: 'POST', body, signal }),

  /**
   * Endpoint 18 — `PUT /images/{id}/annotations` → `200 AnnotationBulkUpsertResponse`.
   *
   * ★ THE hot path: Konva drops a dragged point → this fires with an optimistic
   *   update, and **the server response is authoritative** (§8.5).
   */
  bulkUpsert: (
    imageId: Uuid,
    body: AnnotationBulkUpsertRequest,
    signal?: AbortSignal,
  ): Promise<AnnotationBulkUpsertResponse> =>
    fetchJson<AnnotationBulkUpsertResponse>(nested(imageId), { method: 'PUT', body, signal }),

  /**
   * Endpoint 19 — `DELETE /images/{id}/annotations` → `200 AnnotationBulkUpsertResponse`.
   *
   * ★ `X-Confirm-Delete` is **REQUIRED, unconditionally** (not only for a hard
   *   delete): this erases every landmark on the photo in one call.
   */
  deleteAll: (
    imageId: Uuid,
    kinds?: AnnotationKind[],
    signal?: AbortSignal,
  ): Promise<AnnotationBulkUpsertResponse> =>
    fetchJson<AnnotationBulkUpsertResponse>(nested(imageId), {
      method: 'DELETE',
      query: { kind: kinds },
      confirmDelete: true,
      signal,
    }),

  /** Endpoint 20 — `GET /annotations/{id}` → `200 AnnotationRead` + `ETag`. */
  get: (id: Uuid, signal?: AbortSignal): Promise<AnnotationRead> =>
    fetchJson<AnnotationRead>(flat(id), { signal }),

  /** Endpoint 21 — `PATCH /annotations/{id}`, **`If-Match` REQUIRED** → `200` · `412`. */
  update: (
    id: Uuid,
    body: AnnotationUpdate,
    etag?: string,
    signal?: AbortSignal,
  ): Promise<AnnotationRead> =>
    fetchJson<AnnotationRead>(flat(id), { method: 'PATCH', body, ifMatch: etag, signal }),

  /**
   * Endpoint 22 — `DELETE /annotations/{id}` → `200 AnnotationRead` (`is_deleted: true`).
   *
   * ★ A SOFT delete that returns the row: the annotation stays inspectable and its
   *   version history intact. The ETag is dropped anyway — the returned row's
   *   `version_no` moved, so the cached ETag is dead.
   */
  remove: async (id: Uuid, etag?: string, signal?: AbortSignal): Promise<AnnotationRead> => {
    const result = await fetchJson<AnnotationRead>(flat(id), {
      method: 'DELETE',
      ifMatch: etag,
      signal,
    });
    forgetEtag(flat(id));
    return result;
  },
};
