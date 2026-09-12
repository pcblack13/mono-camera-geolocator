/**
 * Camera drift — references and monitors, for the pill, banner and freeze flow.
 *
 * ★ ONE POLL FOR EVERYTHING VISIBLE. `/drift/status` carries every monitor's
 *   confirmed verdict; the pill and the map banner both render from this single
 *   query rather than each opening its own timer. 10 s is deliberate — the
 *   server checks every ~30 s, so polling faster would only re-read the same
 *   verdict.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import {
  driftApi,
  type DriftFreezeRequest,
  type DriftMonitor,
  type DriftReference,
  type DriftVerdict,
} from '../drift';
import { qk } from '../queryKeys';

const STATUS_POLL_MS = 10_000;

export function useDriftReferences(): UseQueryResult<DriftReference[]> {
  return useQuery({
    queryKey: qk.drift.references(),
    queryFn: async ({ signal }) => (await driftApi.references(signal)).items,
    staleTime: 30_000,
  });
}

/** All monitors' state. `enabled: false` while the page has nothing to show. */
export function useDriftMonitors(enabled: boolean): UseQueryResult<DriftMonitor[]> {
  return useQuery({
    queryKey: qk.drift.status(),
    queryFn: async ({ signal }) => (await driftApi.status(signal)).items,
    enabled,
    refetchInterval: STATUS_POLL_MS,
  });
}

export function useFreezeReference(): UseMutationResult<DriftReference, Error, DriftFreezeRequest> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: DriftFreezeRequest) => driftApi.freeze(body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.drift.references() });
    },
  });
}

export function useDriftCheck(): UseMutationResult<
  DriftVerdict,
  Error,
  { refId: string; atS?: number }
> {
  return useMutation({ mutationFn: ({ refId, atS }) => driftApi.check(refId, atS) });
}

export function useStartDriftMonitor(): UseMutationResult<
  DriftMonitor,
  Error,
  { refId: string; intervalS: number; cameraId?: string | null }
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ refId, intervalS, cameraId }) =>
      driftApi.startMonitor(refId, intervalS, cameraId ?? null),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.drift.status() });
    },
  });
}

export function useStopDriftMonitor(): UseMutationResult<
  DriftMonitor,
  Error,
  string | { refId: string; cameraId?: string | null }
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (arg) =>
      typeof arg === 'string'
        ? driftApi.stopMonitor(arg)
        : driftApi.stopMonitor(arg.refId, arg.cameraId ?? null),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.drift.status() });
    },
  });
}

/**
 * Forget a frozen reference. Its monitor (if any) goes with it server-side; the
 * status poll is invalidated too so a stopped watch disappears on the next tick.
 */
export function useRemoveDriftReference(): UseMutationResult<void, Error, string> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (refId: string) => driftApi.remove(refId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.drift.all() });
    },
  });
}
