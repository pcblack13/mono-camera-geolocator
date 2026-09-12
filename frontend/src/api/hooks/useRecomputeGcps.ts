/**
 * `useRecomputeGcps` — endpoint 42.
 *
 * ★★ DEFERRED — SCOPE.md §4. **Both modes**: `rederive` runs the matching pipeline and
 *    `refit` re-fits a homography. Returns `501` in this build. Gate the control on
 *    `useIsFeatureDeferred('matching')` — see {@link useRecomputeDeferral}.
 *
 * ★ WHEN LIVE, `dry_run` IS NOT A NICETY. "Recompute" moves coordinates the surveyor
 *   may have already reported; they get to see how far, and for which points, BEFORE
 *   committing. `dry_run: true` answers `200 GcpRecomputeDryRun` synchronously;
 *   otherwise `202 JobRead`.
 *
 * ★ Recompute is **the only door, and it is one a person opens.** Nothing in this
 *   system recomputes a GCP implicitly — staleness is a flag, never an
 *   auto-recompute, because a GCP may already be in a survey report, a contract, or a
 *   machine-control file.
 */

import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';

import type { Uuid } from '../../types/common';
import type { GcpRecomputeRequest } from '../../types/gcp';
import { gcpsApi, isRecomputeDryRun, type GcpRecomputeResponse } from '../gcps';
import { qk } from '../queryKeys';
import { DEFERRED_TOOLTIP, useIsFeatureDeferred } from './useCapabilities';

/** The honest gate for a recompute control. See `useMatchDeferral` for the pattern. */
export function useRecomputeDeferral(): { disabled: boolean; tooltip: string | undefined } {
  const deferred = useIsFeatureDeferred('matching');
  return { disabled: deferred, tooltip: deferred ? DEFERRED_TOOLTIP.matching : undefined };
}

export interface RecomputeGcpsVariables {
  imageId: Uuid;
  body?: GcpRecomputeRequest;
}

/**
 * ★ DEFERRED — endpoint 42 → **`501`**.
 *
 * The two outcomes are discriminated by {@link isRecomputeDryRun}: a `GcpRecomputeDryRun`
 * is a preview to render, a `JobRead` is a job to poll with `useJob`.
 */
export function useRecomputeGcps(): UseMutationResult<
  GcpRecomputeResponse,
  unknown,
  RecomputeGcpsVariables
> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ imageId, body }: RecomputeGcpsVariables) =>
      gcpsApi.recompute(imageId, body ?? {}),
    onSuccess: (response, { imageId }) => {
      // ★ A DRY RUN CHANGED NOTHING. Invalidating on it would refetch the very rows the
      //   surveyor is comparing the preview against — and the preview's whole purpose
      //   is to show `lat_before` next to `lat_after`.
      if (isRecomputeDryRun(response)) return;

      void queryClient.invalidateQueries({ queryKey: qk.jobs.lists() });
      // The job will move the GCPs when it lands; the list refetches then. Invalidating
      // now is harmless and keeps `is_stale` fresh if the server cleared it on accept.
      void queryClient.invalidateQueries({ queryKey: qk.gcps.forImage(imageId) });
    },
  });
}
