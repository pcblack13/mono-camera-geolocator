/**
 * Async jobs — mirrors `backend/app/schemas/job.py` (§6.2 / §8.2), field for field.
 */

import type { ErrorBody, IsoDateTime, ResultRef, Uuid, WarningItem } from './common';

export type JobStatus =
  | 'pending'
  | 'queued'
  | 'running'
  | 'retrying'
  | 'succeeded'
  | 'failed'
  | 'cancelled';

/** ★ The discriminator over the `v_jobs` union. */
export type JobType =
  | 'match'
  | 'export'
  | 'batch'
  | 'segment'
  | 'suggest_landmarks'
  | 'gcp_recompute'
  | 'ingest';

/**
 * ★ The union of every stage across every `JobType`. `STAGES[JobType]` — the
 *   per-type ordered list — lives in `backend/app/core/constants.py` (IU-15) and
 *   NOWHERE ELSE.
 *
 * ★ `resolving_models` is where a `match` job reports degradation — at the INSTANT
 *   it is known, not at the end (§11.1/§11.8). Its stage weight is 0.0:
 *   `resolve_with_fallback` uses `find_spec` and a sha256, and is milliseconds.
 */
export type JobStage =
  // common
  | 'pending'
  | 'persisting'
  | 'done'
  // match
  | 'resolving_models'
  | 'resolving_aoi'
  | 'fetching_tiles'
  | 'extracting_query'
  | 'extracting_train'
  | 'matching'
  | 'estimating_homography'
  | 'scoring'
  | 'deriving_gcps'
  // segment / suggest_landmarks
  | 'loading_model'
  | 'segmenting'
  | 'vectorizing'
  | 'detecting'
  | 'ranking'
  // export
  | 'collecting_gcps'
  | 'reprojecting'
  | 'rendering'
  | 'writing'
  // batch
  | 'fanning_out'
  | 'waiting_children'
  | 'aggregating'
  // ingest
  | 'decoding'
  | 'thumbnailing';

/**
 * ★ Rules the workers MUST honour, because the UI depends on them (§6.2):
 *   - `percent` is MONOTONIC NON-DECREASING within an attempt and resets to 0 on
 *     `retrying`. *A progress bar that goes backwards is a bug report.*
 *   - `percent` is a WEIGHTED BLEND of stages, not `stage_index / n_stages`, so the
 *     bar tracks wall-clock rather than stage count.
 *   - Progress writes are throttled to ≥ 250 ms apart and never run inside the CV
 *     transaction. Progress is telemetry; it must never hold a lock a matcher needs.
 */
export interface JobProgress {
  /** 0–100, monotonic within an attempt. */
  percent: number;
  stage: JobStage;
  message: string | null;
  current: number | null;
  total: number | null;
  /** ★ `null` until ≥ 3 rate samples. **A wrong ETA is worse than none.** */
  eta_seconds: number | null;
  tiles_fetched: number | null;
  tiles_total: number | null;
  candidates_evaluated: number | null;
}

export interface JobRead {
  id: Uuid;
  type: JobType;
  status: JobStatus;
  image_id: Uuid | null;
  project_id: Uuid | null;
  batch_id: Uuid | null;
  /**
   * ★ `running` → cancel sets this and returns 202; the worker polls it at every
   *   stage boundary and inside the tile-fetch loop. `revoke(terminate=True)` is
   *   NEVER used — a hard kill of a process holding GDAL dataset handles orphans
   *   `*.part` files and can wedge the CUDA context so the worker's NEXT task fails
   *   too. A 1-second cooperative window is worth avoiding an entire class of
   *   corruption.
   */
  cancel_requested: boolean;
  attempt: number;
  max_attempts: number;
  progress: JobProgress;

  /**
   * ★ §8.8: `degraded: true` whose only cause is "no deep weights present" renders
   *   an INFORMATIONAL chip — "Matched with SIFT + FLANN" — **not a warning**. Per
   *   SCOPE.md and the environment constraints this is the DEFAULT state on a fresh
   *   machine. SIFT + RANSAC is a real algorithm with real accuracy; framing it as
   *   a degradation would be both wrong and demoralising.
   *
   *   The distinction that decides warning-vs-informational is
   *   `warnings[].requested !== null` — an unrequested fallback is informational; a
   *   requested-and-denied one is a warning.
   */
  degraded: boolean;
  degradation_reason: string | null;
  warnings: WarningItem[];

  /** `null` until `succeeded`. */
  result_ref: ResultRef | null;
  result_url: string | null;
  /**
   * ★ `ErrorBody`-shaped: the client renders job failures with the SAME component
   *   as HTTP errors. `error_traceback` is stored server-side but NEVER serialised.
   *
   * ★ "No match found" is `succeeded`, NOT `failed` (§6.2). A match job that
   *   fetched tiles, extracted features and found no candidate above
   *   `min_confidence` DID ITS JOB CORRECTLY. `failed` is reserved for *the
   *   pipeline could not run*.
   */
  error: ErrorBody | null;

  queued_at: IsoDateTime | null;
  started_at: IsoDateTime | null;
  finished_at: IsoDateTime | null;
  duration_ms: number | null;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

export interface JobSummary {
  id: Uuid;
  type: JobType;
  status: JobStatus;
  image_id: Uuid | null;
  project_id: Uuid | null;
  percent: number;
  stage: JobStage;
  degraded: boolean;
  created_at: IsoDateTime;
  finished_at: IsoDateTime | null;
}

export interface JobFilters {
  type?: JobType | JobType[];
  status?: JobStatus | JobStatus[];
  image_id?: Uuid;
  project_id?: Uuid;
  batch_id?: Uuid;
  sort?: string;
  limit?: number;
  offset?: number;
}

/**
 * ★ Optional long-poll: `?wait=0..30` subscribes to the Redis pubsub channel
 *   `job:{id}:events`, cutting poll traffic ~25×. **Falls back transparently** — if
 *   Redis pubsub is unavailable, `wait` is ignored and the current state returns
 *   immediately (L11). nginx `proxy_read_timeout` must exceed 30 s.
 */
export interface JobPollParams {
  wait?: number;
}

/**
 * ★ TERMINAL SET = `{succeeded, failed, cancelled}`. There is no `expired` state —
 *   retention deletes the row, which surfaces as a 404.
 *
 * ★ EXHAUSTIVE, deliberately. Adding a `JobStatus` member is a COMPILE ERROR until
 *   the poller is updated. A bug here means infinite polling on a dead job — this
 *   pattern's classic failure mode.
 *
 * ★ `Retry-After`'s ABSENCE on a terminal job is the machine-readable "stop
 *   polling"; `useJob` (IU-24) honours both this predicate and that header (§8.4).
 */
export function isTerminal(status: JobStatus): boolean {
  switch (status) {
    case 'succeeded':
    case 'failed':
    case 'cancelled':
      return true;
    case 'pending':
    case 'queued':
    case 'running':
    case 'retrying':
      return false;
    default: {
      const _exhaustive: never = status;
      return _exhaustive;
    }
  }
}
