/**
 * Batch — endpoints 54–57.
 *
 * ★★ PARTIALLY DEFERRED (SCOPE.md §3): batch **upload / metadata / export** are BUILT;
 *    **batch matching is not**. A batch that would fan out to `match` jobs returns
 *    `501` at creation — rather than fanning out into 40 jobs that each 501, which
 *    would be 40 rows of red for one deferred feature.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import type { Page, Uuid } from '../../types/common';
import type { BatchCreate, BatchFilters, BatchRead, BatchSummary } from '../../types/batch';
import { isTerminal } from '../../types/job';
import { batchApi, type BatchUploadForm } from '../batch';
import { qk } from '../queryKeys';
import { DEFERRED_TOOLTIP, useIsFeatureDeferred } from './useCapabilities';

/** The honest gate for a "match all images" control. Batch UPLOAD is never gated. */
export function useBatchMatchDeferral(): { disabled: boolean; tooltip: string | undefined } {
  const deferred = useIsFeatureDeferred('matching');
  return { disabled: deferred, tooltip: deferred ? DEFERRED_TOOLTIP.matching : undefined };
}

export function useBatches(f: BatchFilters = {}): UseQueryResult<Page<BatchSummary>> {
  return useQuery({
    queryKey: qk.batches.list(f),
    queryFn: ({ signal }) => batchApi.list(f, signal),
  });
}

/**
 * Endpoint 56 — one batch.
 *
 * ★ POLLS ITSELF while running. A batch is not a `JobRead`, so `useJob` cannot poll it
 *   — `BatchRead` carries its own `status`, `counts` and `progress`. The stop condition
 *   is the same `isTerminal` predicate, so there is still exactly one definition of
 *   "finished" in the app.
 *
 * ★ A cancelled-but-not-yet-stopped batch (`202` from endpoint 57) is NOT terminal:
 *   `cancel_requested` is set and the children stop cooperatively. Polling must
 *   continue until the server says `cancelled`.
 */
export function useBatch(batchId: Uuid | null): UseQueryResult<BatchRead> {
  return useQuery({
    queryKey: qk.batches.detail(batchId!),
    queryFn: ({ signal }) => batchApi.get(batchId!, signal),
    enabled: batchId !== null,
    refetchInterval: (query) => {
      const batch = query.state.data;
      if (!batch || isTerminal(batch.status)) return false;
      return 2_000;
    },
    refetchIntervalInBackground: false,
    staleTime: 0,
  });
}

/** ★ Returns `501` when the batch would fan out to `match` jobs. */
export function useCreateBatch(): UseMutationResult<
  BatchRead,
  unknown,
  BatchCreate & { project_id: Uuid }
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: BatchCreate & { project_id: Uuid }) => batchApi.create(body),
    onSuccess: (batch) => {
      queryClient.setQueryData(qk.batches.detail(batch.id), batch);
      void queryClient.invalidateQueries({ queryKey: qk.batches.lists() });
      void queryClient.invalidateQueries({ queryKey: qk.jobs.lists() });
    },
  });
}

export interface BatchUploadVariables {
  form: BatchUploadForm;
  onProgress?: (bytesSent: number, bytesTotal: number) => void;
  signal?: AbortSignal;
}

/** ★ The BUILT half — batch upload. Never gated. */
export function useBatchUpload(): UseMutationResult<BatchRead, unknown, BatchUploadVariables> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ form, onProgress, signal }: BatchUploadVariables) =>
      batchApi.upload(form, { onProgress, signal }),
    onSuccess: (batch, { form }) => {
      queryClient.setQueryData(qk.batches.detail(batch.id), batch);
      void queryClient.invalidateQueries({ queryKey: qk.batches.lists() });
      void queryClient.invalidateQueries({ queryKey: qk.images.lists() });
      void queryClient.invalidateQueries({ queryKey: qk.projects.detail(form.project_id) });
    },
  });
}

/** Endpoint 57 — `202`: cancellation REQUESTED. Keep polling. */
export function useCancelBatch(): UseMutationResult<BatchRead, unknown, Uuid> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (batchId: Uuid) => batchApi.cancel(batchId),
    onSuccess: (batch) => {
      queryClient.setQueryData(qk.batches.detail(batch.id), batch);
      void queryClient.invalidateQueries({ queryKey: qk.batches.lists() });
    },
  });
}
