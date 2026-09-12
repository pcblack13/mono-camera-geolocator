/**
 * `useGcpOverview` — every GCP, across every project, for the dashboard map.
 *
 * ★ THIS QUERY IS ALLOWED TO FAIL. `GET /gcps` is the newest endpoint in the API and
 *   a client built against a server that predates it must still render its home
 *   screen. So the hook exposes {@link GcpOverviewState}, which folds "loading",
 *   "the endpoint is not there", "it failed" and "there is nothing yet" into four
 *   states the page can render honestly — instead of leaving `DashboardPage` to
 *   re-derive them from three booleans and get one of them wrong.
 *
 * ★ `retry` stays at the client default, which never retries a 4xx (`queryClient.ts`)
 *   — a 404 is answered once and the page degrades immediately rather than spinning
 *   through three doomed attempts.
 */

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { ApiError, type Page } from '../../types/common';
import type { GcpOverview, GcpOverviewFilters } from '../../types/gcp';
import { gcpsApi } from '../gcps';
import { qk } from '../queryKeys';

export function useGcpOverview(
  f: GcpOverviewFilters = {},
  enabled = true,
): UseQueryResult<Page<GcpOverview>> {
  return useQuery({
    queryKey: qk.gcps.overview(f),
    queryFn: ({ signal }) => gcpsApi.overview(f, signal),
    enabled,
    // The overview is a wide read; it need not be re-fetched on every focus change.
    staleTime: 60_000,
  });
}

/**
 * ★ `unavailable` is NOT `failed`, and the distinction is the whole point.
 *   A 404/501 means *this server does not serve the overview yet* — the correct
 *   response is a calm empty map, not a red error. A 5xx or a transport failure
 *   means *something broke* — the correct response is to say so and offer a retry.
 */
export type GcpOverviewStatus = 'loading' | 'ready' | 'empty' | 'unavailable' | 'failed';

export interface GcpOverviewState {
  status: GcpOverviewStatus;
  items: GcpOverview[];
  total: number;
  refetch: () => void;
}

/** `true` when the server simply does not implement `GET /gcps` (yet). */
export function isEndpointAbsent(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 404 || error.status === 501);
}

export function useGcpOverviewState(f: GcpOverviewFilters = {}): GcpOverviewState {
  const query = useGcpOverview(f);
  const items = query.data?.items ?? [];

  const status: GcpOverviewStatus = query.isLoading
    ? 'loading'
    : query.isError
      ? isEndpointAbsent(query.error)
        ? 'unavailable'
        : 'failed'
      : items.length === 0
        ? 'empty'
        : 'ready';

  return {
    status,
    items,
    total: query.data?.total ?? items.length,
    refetch: () => void query.refetch(),
  };
}
