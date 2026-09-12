/**
 * Matching — endpoints 30, 34–37.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * ★★ DEFERRED — SCOPE.md §1. `useStartMatch` calls an endpoint that returns **`501`**
 *    in this build.
 *
 *    **Do not render a match button that fires and fails.** Gate on
 *    `useIsFeatureDeferred('matching')` and render it disabled with
 *    `DEFERRED_TOOLTIP.matching` — SCOPE.md §4 rule 4: *"No spinner that never
 *    resolves."* {@link useMatchDeferral} packages exactly that decision so IU-26/27/28
 *    cannot forget it.
 *
 *    The hook exists in full anyway because the seam is real, not decorative
 *    (rule 1): when the engine lands, this file does not change — the endpoint flips
 *    from 501 to live and `deferred_features` stops listing `matching` (SCOPE.md §7).
 * ─────────────────────────────────────────────────────────────────────────────
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
  MatchFilters,
  MatchRequest,
  MatchResultRead,
  MatchResultSummary,
} from '../../types/match';
import { matchesApi, type StartMatchOptions } from '../matches';
import { qk } from '../queryKeys';
import { DEFERRED_TOOLTIP, useIsFeatureDeferred } from './useCapabilities';

/**
 * ★ THE GATE, packaged. Everything a control needs to render honestly:
 *
 * ```tsx
 * const { disabled, tooltip } = useMatchDeferral();
 * <Button disabled={disabled} title={tooltip}>Find on map</Button>
 * ```
 */
export function useMatchDeferral(): { disabled: boolean; tooltip: string | undefined } {
  const deferred = useIsFeatureDeferred('matching');
  return { disabled: deferred, tooltip: deferred ? DEFERRED_TOOLTIP.matching : undefined };
}

export interface StartMatchVariables {
  imageId: Uuid;
  body?: MatchRequest;
  options?: StartMatchOptions;
}

/**
 * ★ DEFERRED — endpoint 30 → **`501`** in this build. Live: `202 JobRead`.
 *
 * ★ On success the returned `JobRead.id` feeds `useJob` to poll to completion.
 * ★ `409 MATCH_JOB_ALREADY_RUNNING` returns the existing job's id and offers
 *   `force: true` — more informative than a silent idempotent replay, which is why
 *   §12 C-27 kept it and deleted the content-derived key column.
 */
export function useStartMatch(): UseMutationResult<JobRead, unknown, StartMatchVariables> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ imageId, body, options }: StartMatchVariables) =>
      matchesApi.start(imageId, body ?? {}, options),
    onSuccess: (_job, { imageId }) => {
      void queryClient.invalidateQueries({ queryKey: qk.jobs.lists() });
      void queryClient.invalidateQueries({ queryKey: qk.matches.forImage(imageId) });
      // `ImageRead.latest_match` / `counts.match_jobs` moved.
      void queryClient.invalidateQueries({ queryKey: qk.images.detail(imageId) });
      // ★ The job's detail cache is NOT seeded from this `202` body: `useJob` caches a
      //   `Parsed<JobRead>` (§8.4), not a bare `JobRead`, and seeding the wrong shape
      //   would crash the poller's `res.data.status` on its first tick. Let it fetch.
    },
  });
}

/** Endpoint 34 — the candidate list. `200` with an empty page in this build. */
export function useMatchResults(
  imageId: Uuid | null,
  f: MatchFilters = {},
): UseQueryResult<Page<MatchResultSummary>> {
  return useQuery({
    queryKey: qk.matches.forImageFiltered(imageId!, f),
    queryFn: ({ signal }) => matchesApi.listResults(imageId!, f, signal),
    enabled: imageId !== null,
  });
}

/** Endpoint 35 — one candidate, with its full stats, scores and degeneracy report. */
export function useMatchResult(matchResultId: Uuid | null): UseQueryResult<MatchResultRead> {
  return useQuery({
    queryKey: qk.matches.detail(matchResultId!),
    queryFn: ({ signal }) => matchesApi.getResult(matchResultId!, signal),
    enabled: matchResultId !== null,
  });
}

export interface SelectMatchResultVariables {
  matchResultId: Uuid;
  imageId: Uuid;
  confirm?: boolean;
}

/**
 * Endpoint 37 — `POST /match-results/{id}/select`.
 *
 * ★ Selecting a candidate re-derives that image's GCPs server-side, so the GCP cache
 *   is invalidated with it.
 */
export function useSelectMatchResult(): UseMutationResult<
  MatchResultRead,
  unknown,
  SelectMatchResultVariables
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ matchResultId, confirm }: SelectMatchResultVariables) =>
      matchesApi.selectResult(matchResultId, { confirm: confirm ?? true }),
    onSuccess: (result, { imageId }) => {
      queryClient.setQueryData(qk.matches.detail(result.id), result);
      void queryClient.invalidateQueries({ queryKey: qk.matches.forImage(imageId) });
      void queryClient.invalidateQueries({ queryKey: qk.gcps.forImage(imageId) });
    },
  });
}
