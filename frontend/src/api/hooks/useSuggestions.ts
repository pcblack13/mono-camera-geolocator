/**
 * Landmark suggestions — endpoints 43–45.
 *
 * ★★ DEFERRED — SCOPE.md §4. `useSuggestLandmarks` returns `501`. Gate on
 *    {@link useSuggestionsDeferral}.
 *
 * ★ §8.8: `LandmarkSuggestions` with no weights renders **a calm explainer, never an
 *   error**. The explainer is IU-26's; `DEFERRED_TOOLTIP.landmark_suggestion` is its text.
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
import type {
  LandmarkSuggestionRead,
  SuggestionAcceptRequest,
  SuggestionAcceptResponse,
  SuggestionFilters,
  SuggestLandmarksRequest,
} from '../../types/suggestion';
import { suggestionsApi } from '../suggestions';
import { qk } from '../queryKeys';
import { DEFERRED_TOOLTIP, useIsFeatureDeferred } from './useCapabilities';

/** The honest gate for a "suggest landmarks" control. */
export function useSuggestionsDeferral(): { disabled: boolean; tooltip: string | undefined } {
  const deferred = useIsFeatureDeferred('landmark_suggestion');
  return {
    disabled: deferred,
    tooltip: deferred ? DEFERRED_TOOLTIP.landmark_suggestion : undefined,
  };
}

/** Endpoint 44 — `200` with an empty page in this build (the table exists, unpopulated). */
export function useSuggestions(
  imageId: Uuid | null,
  f: SuggestionFilters = {},
): UseQueryResult<Page<LandmarkSuggestionRead>> {
  return useQuery({
    queryKey: qk.suggestions.forImageFiltered(imageId!, f),
    queryFn: ({ signal }) => suggestionsApi.list(imageId!, f, signal),
    enabled: imageId !== null,
  });
}

export interface SuggestLandmarksVariables {
  imageId: Uuid;
  body?: SuggestLandmarksRequest;
}

/** ★ DEFERRED — endpoint 43 → **`501`**. Live: `202 JobRead`, polled with `useJob`. */
export function useSuggestLandmarks(): UseMutationResult<
  JobRead,
  unknown,
  SuggestLandmarksVariables
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ imageId, body }: SuggestLandmarksVariables) =>
      suggestionsApi.start(imageId, body ?? {}),
    onSuccess: (_job, { imageId }) => {
      void queryClient.invalidateQueries({ queryKey: qk.jobs.lists() });
      void queryClient.invalidateQueries({ queryKey: qk.suggestions.forImage(imageId) });
    },
  });
}

export interface AcceptSuggestionsVariables {
  imageId: Uuid;
  body: SuggestionAcceptRequest;
  projectId?: Uuid;
}

/**
 * Endpoint 45 — accepting a suggestion CREATES ANNOTATIONS, so it invalidates the
 * annotation cache and opens a revision.
 */
export function useAcceptSuggestions(): UseMutationResult<
  SuggestionAcceptResponse,
  unknown,
  AcceptSuggestionsVariables
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ imageId, body }: AcceptSuggestionsVariables) =>
      suggestionsApi.accept(imageId, body),
    onSuccess: (_response, { imageId, projectId }) => {
      void queryClient.invalidateQueries({ queryKey: qk.suggestions.forImage(imageId) });
      void queryClient.invalidateQueries({ queryKey: qk.annotations.forImage(imageId) });
      void queryClient.invalidateQueries({ queryKey: qk.images.detail(imageId) });
      if (projectId !== undefined)
        void queryClient.invalidateQueries({ queryKey: qk.projects.revisions(projectId) });
    },
  });
}
