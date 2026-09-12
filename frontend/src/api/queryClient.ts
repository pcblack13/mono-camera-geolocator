/**
 * The global React Query defaults — `src/api/queryClient.ts` (§8.4).
 *
 * ★ Constructed HERE and imported by `main.tsx` (IU-23) as `{ queryClient }`.
 *   `main.tsx` must not build one: a second client is a second cache, and the two
 *   would disagree about which GCPs exist.
 */

import { QueryClient } from '@tanstack/react-query';

import { ApiError } from '../types/common';
import { isDeferredError } from './client';

/**
 * ★ §8.4, VERBATIM, with ONE addition — see below.
 *
 *   ```ts
 *   retry: (failureCount, error) =>
 *     !(error instanceof ApiError && error.status >= 400 && error.status < 500)
 *     && failureCount < 3,          // ★ NEVER retry a 4xx
 *   ```
 *
 * ★★ THE ADDITION: **a deferred `501` is not retried either.** SCOPE.md overrides the
 *    contract (SCOPE.md §1), and §8.4's predicate was written for a build in which
 *    `501` could not occur — it retries anything `>= 500`, so every deferred endpoint
 *    would be called FOUR TIMES with backoff before the UI could say the honest
 *    thing. That is precisely SCOPE.md §4 rule 4's *"no spinner that never
 *    resolves"*, and it fails the predicate's own stated logic: the comment says
 *    "never retry a 4xx" because **a retry cannot fix a malformed request** — and a
 *    retry cannot fix a feature that was not built, either. `501` is as permanent
 *    and as deterministic as `400`.
 *
 *    Everything else about the predicate is unchanged: `5xx` still retries (a
 *    restarting worker is genuinely transient), and so does `status: 0` (the
 *    transport failure `client.ts` synthesises — a flaky field uplink is exactly
 *    what retries are for).
 *
 * ★ `refetchOnWindowFocus: false` — a surveyor tabbing back must not trigger a
 *   tile-fetch storm on cellular.
 *
 * ★ `mutations: { retry: 0 }` — every mutation in this app either writes a survey
 *   coordinate or spends a worker. Neither may happen twice because a socket
 *   hiccuped; the endpoints that CAN be safely repeated say so with
 *   `Idempotency-Key` (endpoints 9 and 30), which is a server-side mechanism, not a
 *   client-side gamble.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        retry: (failureCount, error) =>
          !(error instanceof ApiError && error.status >= 400 && error.status < 500) &&
          !isDeferredError(error) &&
          failureCount < 3,
        refetchOnWindowFocus: false,
      },
      mutations: { retry: 0 },
    },
  });
}

/** The app's single client. Imported by `main.tsx`. */
export const queryClient: QueryClient = createQueryClient();
