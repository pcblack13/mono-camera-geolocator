/**
 * Semantic features — endpoints 46–47.
 *
 * ★★ DEFERRED — SCOPE.md §4. `useSegment` returns `501`. Gate on {@link useSemanticsDeferral}.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import type { Page, Uuid } from '../../types/common';
import type { JobRead } from '../../types/job';
import type { SegmentRequest, SemanticFeatureRead, SemanticFilters } from '../../types/semantic';
import { semanticsApi } from '../semantics';
import { qk } from '../queryKeys';
import { DEFERRED_TOOLTIP, useIsFeatureDeferred } from './useCapabilities';

/** The honest gate for a "detect features" control. */
export function useSemanticsDeferral(): { disabled: boolean; tooltip: string | undefined } {
  const deferred = useIsFeatureDeferred('semantic_segmentation');
  return {
    disabled: deferred,
    tooltip: deferred ? DEFERRED_TOOLTIP.semantic_segmentation : undefined,
  };
}

/** Endpoint 46 — `200` with an empty page in this build. */
export function useSemantics(
  imageId: Uuid | null,
  f: SemanticFilters = {},
): UseQueryResult<Page<SemanticFeatureRead>> {
  return useQuery({
    queryKey: qk.semantics.forImageFiltered(imageId!, f),
    queryFn: ({ signal }) => semanticsApi.list(imageId!, f, signal),
    enabled: imageId !== null,
  });
}

export interface SegmentVariables {
  imageId: Uuid;
  body?: SegmentRequest;
}

/** ★ DEFERRED — endpoint 47 → **`501`**. Live: `202 JobRead`. */
export function useSegment(): UseMutationResult<JobRead, unknown, SegmentVariables> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ imageId, body }: SegmentVariables) => semanticsApi.segment(imageId, body ?? {}),
    onSuccess: (_job, { imageId }) => {
      void queryClient.invalidateQueries({ queryKey: qk.jobs.lists() });
      void queryClient.invalidateQueries({ queryKey: qk.semantics.forImage(imageId) });
      // `SegmentRequest.as_annotation_kind` can turn detections into annotations.
      void queryClient.invalidateQueries({ queryKey: qk.annotations.forImage(imageId) });
    },
  });
}
