/**
 * Batch processing — mirrors `backend/app/schemas/batch.py` (§6.2).
 *
 * ★ SCOPE.md §3: batch upload / metadata / export are BUILT. **Batch MATCHING is
 *   not** — it fans out to `match` jobs, which are deferred. A batch whose
 *   `job_type` is `match` therefore returns `501` at creation with a
 *   `feature: "deferred"` marker rather than fanning out into a group of jobs that
 *   would each fail. Refusing up front is the honest half (L12).
 */

import type { IsoDateTime, Uuid, WarningItem } from './common';
import type { ProviderId } from './geo';
import type { JobStatus } from './job';
import type { MatchOptions, SearchHint } from './match';

/**
 * ★ `continue` is the default: one unreadable photo in a batch of forty must not
 *   discard the other thirty-nine's work. The failed item carries its own error and
 *   is re-runnable alone.
 */
export type BatchOnError = 'continue' | 'abort';

export interface BatchCreate {
  name?: string | null;
  /** Empty ⇒ every ready image in the project. */
  image_ids?: Uuid[] | null;
  filter?: BatchImageFilter | null;
  provider?: ProviderId | null;
  search_hint?: SearchHint;
  options?: MatchOptions;
  /** ★ 1..64. */
  concurrency?: number;
  on_error?: BatchOnError;
}

export interface BatchImageFilter {
  status?: string[];
  is_geotiff?: boolean | null;
  has_gps?: boolean | null;
  tags?: string[];
}

export interface BatchCounts {
  total: number;
  pending: number;
  running: number;
  succeeded: number;
  failed: number;
  cancelled: number;
}

/** Aggregate outcome across the batch's children. */
export interface BatchRollup {
  gcp_count: number;
  mean_confidence: number | null;
  images_with_results: number;
  images_without_results: number;
}

export interface BatchItemRead {
  id: Uuid;
  batch_job_id: Uuid;
  image_id: Uuid;
  /** `null` until the child job is submitted. */
  match_job_id: Uuid | null;
  ordinal: number;
  status: JobStatus;
  error_message: string | null;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

export interface BatchRead {
  id: Uuid;
  project_id: Uuid;
  name: string | null;
  status: JobStatus;
  cancel_requested: boolean;
  counts: BatchCounts;
  /** ★ 0–1 here (the `batch_jobs.progress` column), NOT the 0–100 `JobProgress.percent`. */
  progress: number;
  rollup: BatchRollup | null;
  provider: ProviderId;
  params: Record<string, unknown>;
  concurrency: number;
  continue_on_error: boolean;
  items: BatchItemRead[];
  warnings: WarningItem[];
  error_message: string | null;
  requested_by: string | null;
  started_at: IsoDateTime | null;
  finished_at: IsoDateTime | null;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

export interface BatchSummary {
  id: Uuid;
  project_id: Uuid;
  name: string | null;
  status: JobStatus;
  counts: BatchCounts;
  progress: number;
  created_at: IsoDateTime;
  finished_at: IsoDateTime | null;
}

export interface BatchFilters {
  status?: JobStatus | JobStatus[];
  sort?: string;
  limit?: number;
  offset?: number;
}
