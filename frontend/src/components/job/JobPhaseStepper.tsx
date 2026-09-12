/**
 * `job/JobPhaseStepper.tsx` — the pipeline-phase view (50-frontend §2.24 / §8.4).
 *
 * ★ "A 40-second wait is legible rather than opaque." The phases (`fetching_tiles →
 *   extracting_features → matching → …`) are the PRIMARY progress signal; the bar is
 *   secondary (§8.4). This renders the ordered phases for the job's type, marks the
 *   current one active and the passed ones done.
 *
 * ★ The canonical per-type stage ORDER + weights live in
 *   `backend/app/core/constants.py` (IU-15) and are never serialised to the frontend.
 *   The sequences below are a PRESENTATIONAL grouping with human labels — they decide
 *   only what the stepper draws, never progress arithmetic (that is `job.progress.percent`,
 *   computed server-side). If a stage arrives that is not in the sequence, the stepper
 *   degrades to showing just the current stage rather than guessing an order.
 *
 * ★ (pure).
 */

import type { JSX } from 'react';
import Step from '@mui/material/Step';
import StepLabel from '@mui/material/StepLabel';
import Stepper from '@mui/material/Stepper';
import Typography from '@mui/material/Typography';

import type { JobStage, JobType } from '../../types/job';

export interface JobPhaseStepperProps {
  type: JobType;
  stage: JobStage;
  /** `true` once the job is terminal-succeeded — every phase reads done. */
  complete?: boolean;
  orientation?: 'horizontal' | 'vertical';
}

/** Human labels for every `JobStage` member (§7.1 job.ts union). */
const STAGE_LABEL: Record<JobStage, string> = {
  pending: 'Queued',
  persisting: 'Saving',
  done: 'Done',
  resolving_models: 'Resolving models',
  resolving_aoi: 'Resolving area',
  fetching_tiles: 'Fetching imagery',
  extracting_query: 'Reading photo',
  extracting_train: 'Reading imagery',
  matching: 'Matching',
  estimating_homography: 'Estimating fit',
  scoring: 'Scoring',
  deriving_gcps: 'Deriving GCPs',
  loading_model: 'Loading model',
  segmenting: 'Segmenting',
  vectorizing: 'Vectorizing',
  detecting: 'Detecting',
  ranking: 'Ranking',
  collecting_gcps: 'Collecting points',
  reprojecting: 'Reprojecting',
  rendering: 'Rendering',
  writing: 'Writing file',
  fanning_out: 'Fanning out',
  waiting_children: 'Processing images',
  aggregating: 'Aggregating',
  decoding: 'Decoding',
  thumbnailing: 'Thumbnailing',
};

/**
 * The ordered phases shown per job type. Presentational only — see the header note.
 * Built types (export / ingest / batch) are complete; the deferred types (match /
 * segment / suggest_landmarks / gcp_recompute) keep their order so the stepper is
 * correct the day the engine is enabled (SCOPE.md §7).
 */
const SEQUENCE: Record<JobType, JobStage[]> = {
  match: [
    'resolving_models',
    'resolving_aoi',
    'fetching_tiles',
    'extracting_query',
    'extracting_train',
    'matching',
    'estimating_homography',
    'scoring',
    'deriving_gcps',
    'persisting',
    'done',
  ],
  export: ['collecting_gcps', 'reprojecting', 'rendering', 'writing', 'done'],
  batch: ['fanning_out', 'waiting_children', 'aggregating', 'done'],
  segment: ['loading_model', 'segmenting', 'vectorizing', 'persisting', 'done'],
  suggest_landmarks: ['loading_model', 'detecting', 'ranking', 'persisting', 'done'],
  gcp_recompute: ['estimating_homography', 'deriving_gcps', 'persisting', 'done'],
  ingest: ['decoding', 'thumbnailing', 'persisting', 'done'],
};

export function JobPhaseStepper({
  type,
  stage,
  complete = false,
  orientation = 'horizontal',
}: JobPhaseStepperProps): JSX.Element {
  const phases = SEQUENCE[type] ?? [];
  const activeIndex = phases.indexOf(stage);

  // ★ Degrade honestly: an unmapped stage shows just the live label rather than a
  //   fabricated position in a sequence it isn't part of.
  if (phases.length === 0 || activeIndex === -1) {
    return (
      <Typography variant="body2" color="text.secondary" role="status">
        {STAGE_LABEL[stage] ?? stage}
      </Typography>
    );
  }

  const effectiveActive = complete ? phases.length : activeIndex;

  return (
    <Stepper
      activeStep={effectiveActive}
      orientation={orientation}
      alternativeLabel={orientation === 'horizontal'}
    >
      {phases.map((phase) => (
        <Step key={phase}>
          <StepLabel>{STAGE_LABEL[phase]}</StepLabel>
        </Step>
      ))}
    </Stepper>
  );
}

export default JobPhaseStepper;
