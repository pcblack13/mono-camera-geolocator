/**
 * The accuracy check — one state query per photograph, three mutations that start jobs.
 *
 * ★ THE PAGE READS ONE THING. `useAccuracyState` returns everything stored for the
 *   photograph and POLLS ITSELF while a run is in flight (`active_run` comes from the
 *   server, so a run started in another tab — or before a reload — is picked up too).
 *   When it goes idle the polling stops. No client-side run bookkeeping, because the
 *   server already owns it and the disk already owns the result.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import type { Uuid } from '../../types/common';
import {
  accuracyApi,
  type AccuracyRunStatus,
  type AccuracyState,
  type Adoption,
  type CorrectRequest,
  type HeatmapVersion,
  type MeasureRequest,
  type PixelQueryRead,
  type SolutionKey,
  type SolveOptions,
  type SuggestRequest,
} from '../accuracy';
import { qk } from '../queryKeys';

/** While a stage runs, ask again this often. Stage D reports every few seconds. */
const POLL_MS = 1200;

export function useAccuracyState(imageId: Uuid | null): UseQueryResult<AccuracyState> {
  return useQuery({
    queryKey: qk.accuracy.state(imageId!),
    queryFn: ({ signal }) => accuracyApi.state(imageId!, signal),
    enabled: imageId !== null,
    refetchInterval: (query) => (query.state.data?.active_run == null ? false : POLL_MS),
  });
}

/**
 * The heat-map version history.
 *
 * ★ Polls WHILE A RUN IS IN FLIGHT, like the state query, because a finishing
 *   measurement adds an entry — a history that needed a manual refresh to show the run
 *   the surveyor just watched would be the wrong kind of stale.
 */
export function useAccuracyHistory(imageId: Uuid | null): UseQueryResult<HeatmapVersion[]> {
  const state = useAccuracyState(imageId);
  const running = state.data?.active_run != null;
  return useQuery({
    queryKey: qk.accuracy.history(imageId!),
    queryFn: ({ signal }) => accuracyApi.history(imageId!, signal),
    enabled: imageId !== null,
    refetchInterval: running ? POLL_MS : false,
  });
}

function useStageMutation<TBody extends { image_id: Uuid }>(
  call: (body: TBody, signal?: AbortSignal) => Promise<AccuracyRunStatus>,
): UseMutationResult<AccuracyRunStatus, unknown, TBody> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: TBody) => call(body),
    // ★ Invalidate the STATE, not a run key: the state query is what carries
    //   `active_run`, so refreshing it is what starts the polling.
    onSuccess: (_run, body) =>
      queryClient.invalidateQueries({ queryKey: qk.accuracy.state(body.image_id) }),
  });
}

export const useMeasureAccuracy = (): UseMutationResult<
  AccuracyRunStatus,
  unknown,
  MeasureRequest
> => useStageMutation<MeasureRequest>(accuracyApi.measure);

export const useCorrectAccuracy = (): UseMutationResult<
  AccuracyRunStatus,
  unknown,
  CorrectRequest
> => useStageMutation<CorrectRequest>(accuracyApi.correct);

export const useSuggestGcps = (): UseMutationResult<AccuracyRunStatus, unknown, SuggestRequest> =>
  useStageMutation<SuggestRequest>(accuracyApi.suggest);

export interface SolveOptionsVariables {
  imageId: Uuid;
  options: SolveOptions;
}

/**
 * Change how the raw pose is solved.
 *
 * ★ CHANGING A SETTING DOES NOT MEASURE (2026-08-20). The server clears the
 *   measurement and everything derived from it, and this used to re-arm the loop's
 *   guards as well — so flipping one switch immediately spent a fresh satellite
 *   mosaic and minutes of compute. The results are cleared, the panel says so, and
 *   the next measurement happens when the surveyor presses Measure. Deciding to
 *   change a setting and deciding to pay for a run are two different decisions.
 */
export function useSetSolveOptions(): UseMutationResult<
  SolveOptions,
  unknown,
  SolveOptionsVariables
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ imageId, options }: SolveOptionsVariables) =>
      accuracyApi.setSolveOptions(imageId, options),
    onSuccess: (_data, { imageId }) => {
      void queryClient.invalidateQueries({ queryKey: qk.accuracy.state(imageId) });
    },
  });
}

export interface AdoptVariables {
  imageId: Uuid;
  stage: SolutionKey;
}

/**
 * Choose the stage this photograph stands on.
 *
 * ★ Invalidates the accuracy state (which carries the adoption) AND the LUT builds
 *   list — the LUT is the one artefact adoption reaches, so a build listed beside a
 *   changed choice must not keep implying it was built on the old one.
 */
export function useAdoptStage(): UseMutationResult<Adoption, unknown, AdoptVariables> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ imageId, stage }: AdoptVariables) => accuracyApi.adopt(imageId, stage),
    onSuccess: (_data, { imageId }) => {
      void queryClient.invalidateQueries({ queryKey: qk.accuracy.state(imageId) });
      void queryClient.invalidateQueries({ queryKey: qk.lut.all() });
    },
  });
}

export function useClearAdoption(): UseMutationResult<void, unknown, Uuid> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (imageId: Uuid) => accuracyApi.clearAdoption(imageId),
    onSuccess: (_data, imageId) => {
      void queryClient.invalidateQueries({ queryKey: qk.accuracy.state(imageId) });
      void queryClient.invalidateQueries({ queryKey: qk.lut.all() });
    },
  });
}

export interface PixelQueryVariables {
  imageId: Uuid;
  u: number;
  v: number;
  targetHeightM?: number;
}

/**
 * One pixel → every stage's answer.
 *
 * ★ A MUTATION, not a query: it is an action the surveyor takes on a specific pixel,
 *   and caching "the answer for (u, v)" would outlive the correction it was computed
 *   against.
 */
export function usePixelQuery(): UseMutationResult<PixelQueryRead, unknown, PixelQueryVariables> {
  return useMutation({
    mutationFn: ({ imageId, u, v, targetHeightM }: PixelQueryVariables) =>
      accuracyApi.query(imageId, { u, v, target_height_m: targetHeightM ?? 0 }),
  });
}
