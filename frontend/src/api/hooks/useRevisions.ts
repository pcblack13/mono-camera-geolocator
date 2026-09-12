/**
 * Revisions and annotation versions — endpoints 23–29.
 *
 * ★ SCOPE.md §3: version history for annotations and project revisions is **BUILT**,
 *   in full.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import type { Page, RevisionSummary, Uuid } from '../../types/common';
import type {
  AnnotationVersionFilters,
  AnnotationVersionRead,
  AnnotationVersionSummary,
  RevisionCreate,
  RevisionRead,
  RevisionRestoreRequest,
  RevisionRestoreResponse,
} from '../../types/annotation';
import { revisionsApi, type RevisionDetailParams, type RevisionFilters } from '../revisions';
import { qk } from '../queryKeys';

export function useProjectRevisions(
  projectId: Uuid | null,
  f: RevisionFilters = {},
): UseQueryResult<Page<RevisionSummary>> {
  return useQuery({
    queryKey: qk.projects.revisionsFiltered(projectId!, f),
    queryFn: ({ signal }) => revisionsApi.listForProject(projectId!, f, signal),
    enabled: projectId !== null,
  });
}

export function useRevision(
  revisionId: Uuid | null,
  params: RevisionDetailParams = {},
): UseQueryResult<RevisionRead> {
  return useQuery({
    queryKey: qk.revisions.detailWith(revisionId!, params),
    queryFn: ({ signal }) => revisionsApi.get(revisionId!, params, signal),
    enabled: revisionId !== null,
  });
}

export interface CreateRevisionVariables {
  projectId: Uuid;
  body: RevisionCreate;
}

export function useCreateRevision(): UseMutationResult<
  RevisionRead,
  unknown,
  CreateRevisionVariables
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ projectId, body }: CreateRevisionVariables) =>
      revisionsApi.create(projectId, body),
    onSuccess: (revision, { projectId }) => {
      queryClient.setQueryData(qk.revisions.detail(revision.id), revision);
      void queryClient.invalidateQueries({ queryKey: qk.projects.revisions(projectId) });
      // `ProjectRead.current_revision_seq` moved.
      void queryClient.invalidateQueries({ queryKey: qk.projects.detail(projectId) });
    },
  });
}

export interface RestoreRevisionVariables {
  revisionId: Uuid;
  projectId: Uuid;
  body: RevisionRestoreRequest;
}

/**
 * Endpoint 26 — `POST /revisions/{id}/restore`.
 *
 * ★★ A restore rewrites annotations wholesale, so it invalidates almost everything
 *    scoped to the project — and, crucially, **the GCPs**: a restore marks every
 *    linked GCP `is_stale` with `stale_reason: 'annotations_restored'`. It does not
 *    recompute them (nothing does — *"a GCP changes when a human decides it
 *    changes"*), so the flag is the only signal the surveyor gets, and it must be
 *    visible immediately.
 *
 * ★ `409 REVISION_RESTORE_CONFLICT` when the project moved underneath; `422
 *   REVISION_REPLAY_TOO_EXPENSIVE` over `LE_MAX_REPLAY_EVENTS`. Both are 4xx and are
 *   never retried (§8.4).
 */
export function useRestoreRevision(): UseMutationResult<
  RevisionRestoreResponse,
  unknown,
  RestoreRevisionVariables
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ revisionId, body }: RestoreRevisionVariables) =>
      revisionsApi.restore(revisionId, body),
    onSuccess: (_response, { projectId }) => {
      void queryClient.invalidateQueries({ queryKey: qk.annotations.all() });
      void queryClient.invalidateQueries({ queryKey: qk.gcps.all() });
      void queryClient.invalidateQueries({ queryKey: qk.projects.detail(projectId) });
      void queryClient.invalidateQueries({ queryKey: qk.projects.revisions(projectId) });
    },
  });
}

/**
 * Endpoint 27 — the image's annotation-version feed.
 *
 * ★ `offset` XOR `before_id` — both is `422 PARAM_CONFLICT`. `before_id` is the keyset
 *   mode for the version drawer's infinite scroll, where `offset` would skip events as
 *   new ones land.
 */
export function useImageAnnotationVersions(
  imageId: Uuid | null,
  f: AnnotationVersionFilters = {},
): UseQueryResult<Page<AnnotationVersionSummary>> {
  return useQuery({
    queryKey: qk.annotations.versionsFiltered(imageId!, f),
    queryFn: ({ signal }) => revisionsApi.versionsForImage(imageId!, f, signal),
    enabled: imageId !== null,
  });
}

/** Endpoint 28 — one annotation's version history. */
export function useAnnotationVersions(
  annotationId: Uuid | null,
  f: AnnotationVersionFilters = {},
): UseQueryResult<Page<AnnotationVersionSummary>> {
  return useQuery({
    queryKey: qk.annotations.versionsForAnnotation(annotationId!, f),
    queryFn: ({ signal }) => revisionsApi.versionsForAnnotation(annotationId!, f, signal),
    enabled: annotationId !== null,
  });
}

/**
 * Endpoint 29 — one version.
 *
 * ★ `versionId` is a **number**: `annotation_versions.id` is `BIGSERIAL` and is the
 *   one id in this API serialised as a JSON number rather than a UUID string (§6.1).
 *   It is deliberately not a `Uuid`, and passing one is a compile error.
 */
export function useAnnotationVersion(
  versionId: number | null,
): UseQueryResult<AnnotationVersionRead> {
  return useQuery({
    queryKey: qk.annotations.version(versionId!),
    queryFn: ({ signal }) => revisionsApi.version(versionId!, signal),
    enabled: versionId !== null,
  });
}
