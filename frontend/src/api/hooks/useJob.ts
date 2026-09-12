/**
 * ★★ THE JOB POLLER — `src/api/hooks/useJob.ts` (§8.4).
 *
 * **The only polling in the app, and its stop condition is load-bearing.**
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * ★ §8.4 is implemented VERBATIM, including the two things v1.0's poller specified
 *   and then contradicted, which the contract calls out at length:
 *
 *   1. **It reads `VITE_JOB_POLL_INTERVAL_MS`.** §9.11 declares the var with consumer
 *      `api/hooks/useJob` — "floor for the adaptive schedule" — and v1.0's verbatim
 *      poller read no env var at all *and* returned `1_000` for jobs younger than
 *      10 s, **below its own floor**.
 *   2. **It honours `Retry-After`.** §6.2 mandates it (`1` running, `2`
 *      pending/queued, `5` retrying) and describes its **absence on a terminal job as
 *      "the machine-readable 'stop polling'"** — a signal the server goes out of its
 *      way to send and v1.0 discarded.
 *
 *   *"Either the code honours the config and the header, or the config and the header
 *   should not exist. They exist, so it honours them."*
 *
 * ★ TERMINAL STOPS DEAD. `isTerminal` (IU-23) is an EXHAUSTIVE switch — adding a
 *   `JobStatus` member is a compile error until this poller is updated. **A bug here
 *   means infinite polling on a dead job, this pattern's classic failure mode**, and
 *   returning `false` from `refetchInterval` is what makes it stop.
 * ─────────────────────────────────────────────────────────────────────────────
 */

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import type { Uuid } from '../../types/common';
import { isTerminal, type JobRead } from '../../types/job';
import type { Parsed } from '../client';
import { jobsApi } from '../jobs';
import { qk } from '../queryKeys';

/**
 * ★ §9.11 default `1500`.
 *
 *   `Number(import.meta.env.VITE_JOB_POLL_INTERVAL_MS ?? 1500)` — §8.4's literal —
 *   yields **`0` for an empty-string env var**, because `Number('') === 0` and `??`
 *   only catches `undefined`/`null`. An unset var in a `.env` file is very commonly
 *   an empty string, and a `0` floor here means `Math.max(schedule, 0, …)` silently
 *   degrades to the raw schedule — the failure is invisible because the poller still
 *   works, just not at the configured rate. L10's spirit: every setting has a working
 *   default, and a malformed one must not be worse than an absent one.
 */
function readPollFloorMs(): number {
  const parsed = Number(import.meta.env.VITE_JOB_POLL_INTERVAL_MS);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 1500;
}

const POLL_FLOOR_MS = readPollFloorMs();

/**
 * Poll a job to completion.
 *
 * ★ **RETURNS `Parsed<JobRead>`, so the job is `data.data`.** §8.4 mandates it:
 *   `jobsApi.get` surfaces `retryAfterMs` alongside the body and *"the poller is the
 *   only consumer"*. Unwrapping with `select` would read better and would contradict
 *   the contract IU-28 is coding against right now.
 *
 * @param jobId The job to poll, or `null` to disable the query entirely.
 */
export function useJob(jobId: Uuid | null): UseQueryResult<Parsed<JobRead>> {
  return useQuery({
    queryKey: qk.jobs.detail(jobId!),
    queryFn: ({ signal }) => jobsApi.get(jobId!, undefined, signal),
    enabled: jobId !== null,
    refetchInterval: (query) => {
      const res = query.state.data;
      // ★ STOP DEAD on terminal. Nothing below this line runs for a finished job.
      if (!res || isTerminal(res.data.status)) return false;

      // ★ The adaptive schedule: fresh jobs move fast, old ones are probably queued
      //   behind something. Age is measured from `created_at` — the server's clock —
      //   so a skewed client cannot make it poll 20× faster than intended.
      const age = Date.now() - new Date(res.data.created_at).getTime();
      const schedule = age < 10_000 ? 1_000 : age < 60_000 ? 2_000 : 5_000;

      // ★ The server's `Retry-After` WINS when larger; the env floor otherwise
      //   applies. Both are honoured, neither can be undercut.
      return Math.max(schedule, POLL_FLOOR_MS, res.retryAfterMs ?? 0);
    },
    // ★ CLEANUP. A backgrounded tab stops polling (a surveyor's tablet is not a
    //   monitoring dashboard), and an unobserved job's cache entry is collected 5
    //   minutes after the last component unmounts — long enough to survive a tab
    //   switch or a route change back, short enough not to pin finished jobs forever.
    refetchIntervalInBackground: false,
    staleTime: 0,
    gcTime: 5 * 60_000,
  });
}

/**
 * `true` while the job is running — i.e. not terminal, not absent.
 *
 * Convenience for the common `disabled={isJobActive(job)}` gate, so no component
 * re-derives the terminal set by hand. **`isTerminal` stays the only definition.**
 */
export function isJobActive(res: Parsed<JobRead> | undefined): boolean {
  return res !== undefined && !isTerminal(res.data.status);
}
