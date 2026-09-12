/**
 * Annotations — endpoints 16–22.
 *
 * ★ THE SHARP EDGE, resolved (§8.5): annotations are edited locally but persisted
 *   server-side. A Konva drag updates the **transient** `annotationStore` draft; on
 *   drop, {@link useBulkUpsertAnnotations} `PUT`s with an optimistic update and
 *   rollback, and **the server response is authoritative**. The draft is cleared on
 *   settle — by IU-26, which owns the store interaction.
 *
 * ★★ SCOPE.md §5: moving a landmark ON THE PHOTOGRAPH is an annotation edit and it is
 *    what marks a linked GCP `is_stale` (`stale_reason: 'landmark_moved'`). **It never
 *    recomputes one** — *"a GCP changes when a human decides it changes"*. So every
 *    write here invalidates the GCP cache: the flag is server-set and the table must
 *    show it.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import type { Page, Uuid } from '../../types/common';
import type {
  AnnotationBulkUpsertRequest,
  AnnotationBulkUpsertResponse,
  AnnotationCreate,
  AnnotationKind,
  AnnotationRead,
  AnnotationUpdate,
} from '../../types/annotation';
import { annotationsApi, type AnnotationFilters } from '../annotations';
import { qk } from '../queryKeys';

export function useAnnotations(
  imageId: Uuid | null,
  f: AnnotationFilters = {},
): UseQueryResult<Page<AnnotationRead>> {
  return useQuery({
    queryKey: qk.annotations.forImageFiltered(imageId!, f),
    queryFn: ({ signal }) => annotationsApi.list(imageId!, f, signal),
    enabled: imageId !== null,
  });
}

/** Endpoint 20. Reading one populates its `ETag`, which endpoint 21 REQUIRES. */
export function useAnnotation(annotationId: Uuid | null): UseQueryResult<AnnotationRead> {
  return useQuery({
    queryKey: qk.annotations.detail(annotationId!),
    queryFn: ({ signal }) => annotationsApi.get(annotationId!, signal),
    enabled: annotationId !== null,
  });
}

/** Invalidate everything an annotation write can move. One place, so nothing is missed. */
function invalidateAfterAnnotationWrite(
  queryClient: ReturnType<typeof useQueryClient>,
  imageId: Uuid,
  projectId?: Uuid,
): void {
  void queryClient.invalidateQueries({ queryKey: qk.annotations.forImage(imageId) });
  // ★ A moved or deleted landmark marks its GCP stale, server-side.
  void queryClient.invalidateQueries({ queryKey: qk.gcps.forImage(imageId) });
  // `ImageRead.counts.annotations`.
  void queryClient.invalidateQueries({ queryKey: qk.images.detail(imageId) });
  // A write opens a revision.
  if (projectId !== undefined)
    void queryClient.invalidateQueries({ queryKey: qk.projects.revisions(projectId) });
}

export interface CreateAnnotationVariables {
  imageId: Uuid;
  body: AnnotationCreate;
  projectId?: Uuid;
}

export function useCreateAnnotation(): UseMutationResult<
  AnnotationRead,
  unknown,
  CreateAnnotationVariables
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ imageId, body }: CreateAnnotationVariables) =>
      annotationsApi.create(imageId, body),
    onSuccess: (annotation, { imageId, projectId }) => {
      queryClient.setQueryData(qk.annotations.detail(annotation.id), annotation);
      invalidateAfterAnnotationWrite(queryClient, imageId, projectId);
    },
  });
}

export interface BulkUpsertVariables {
  imageId: Uuid;
  body: AnnotationBulkUpsertRequest;
  projectId?: Uuid;
}

/**
 * Endpoint 18 — `PUT /images/{id}/annotations`. **The hot path.**
 *
 * ★ No optimistic cache write here, deliberately: the *optimism already happened* in
 *   `annotationStore`'s draft, which is what Konva renders during the drag (§8.5).
 *   Writing a second optimistic copy into React Query would make two sources of truth
 *   for the same pixels and they would disagree the moment one rolled back. The draft
 *   is the optimistic layer; this is the commit; the response is authoritative.
 */
export function useBulkUpsertAnnotations(): UseMutationResult<
  AnnotationBulkUpsertResponse,
  unknown,
  BulkUpsertVariables
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ imageId, body }: BulkUpsertVariables) =>
      annotationsApi.bulkUpsert(imageId, body),
    onSuccess: (_response, { imageId, projectId }) =>
      invalidateAfterAnnotationWrite(queryClient, imageId, projectId),
  });
}

export interface UpdateAnnotationVariables {
  annotationId: Uuid;
  imageId: Uuid;
  body: AnnotationUpdate;
  /** `If-Match` — **REQUIRED** by endpoint 21. Supplied from the client's ETag registry when omitted. */
  etag?: string;
  projectId?: Uuid;
}

export function useUpdateAnnotation(): UseMutationResult<
  AnnotationRead,
  unknown,
  UpdateAnnotationVariables
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ annotationId, body, etag }: UpdateAnnotationVariables) =>
      annotationsApi.update(annotationId, body, etag),
    onSuccess: (annotation, { imageId, projectId }) => {
      queryClient.setQueryData(qk.annotations.detail(annotation.id), annotation);
      invalidateAfterAnnotationWrite(queryClient, imageId, projectId);
    },
  });
}

export interface DeleteAnnotationVariables {
  annotationId: Uuid;
  imageId: Uuid;
  etag?: string;
  projectId?: Uuid;
}

/** Endpoint 22 — a SOFT delete that returns the row with `is_deleted: true`. */
export function useDeleteAnnotation(): UseMutationResult<
  AnnotationRead,
  unknown,
  DeleteAnnotationVariables
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ annotationId, etag }: DeleteAnnotationVariables) =>
      annotationsApi.remove(annotationId, etag),
    onSuccess: (annotation, { imageId, projectId }) => {
      queryClient.setQueryData(qk.annotations.detail(annotation.id), annotation);
      invalidateAfterAnnotationWrite(queryClient, imageId, projectId);
    },
  });
}

export interface DeleteAllAnnotationsVariables {
  imageId: Uuid;
  kinds?: AnnotationKind[];
  projectId?: Uuid;
}

/**
 * Endpoint 19 — `DELETE /images/{id}/annotations`.
 *
 * ★ `X-Confirm-Delete` is sent unconditionally by `annotationsApi.deleteAll` because
 *   the endpoint REQUIRES it — this erases every landmark on the photo in one call,
 *   and marks every linked GCP stale. The confirmation dialog is IU-26/28's; the
 *   header is not a substitute for it.
 */
export function useDeleteAllAnnotations(): UseMutationResult<
  AnnotationBulkUpsertResponse,
  unknown,
  DeleteAllAnnotationsVariables
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ imageId, kinds }: DeleteAllAnnotationsVariables) =>
      annotationsApi.deleteAll(imageId, kinds),
    onSuccess: (_response, { imageId, projectId }) =>
      invalidateAfterAnnotationWrite(queryClient, imageId, projectId),
  });
}
