/**
 * `shell/GlobalJobIndicator.tsx` — "is the machine doing something?" (50-frontend §2.3).
 *
 * ★ The ONLY component allowed to poll at the shell level, so polling cost is exactly
 *   one interval regardless of how many views want job status. It subscribes to
 *   `useJob(jobId)` (IU-24's adaptive poller — the app's single polling site), shows a
 *   determinate ring + phase + elapsed while active, a brief success flash on
 *   completion, and a persistent error chip on failure.
 *
 * ★ SCOPE.md §1 — matching is deferred, so the long match job never runs here. The
 *   jobs this indicator tracks in THIS build are `export` and `ingest`. When `jobId`
 *   is `null` it renders nothing; the shell is quiet when nothing is running.
 */

import { useEffect, useState, type JSX } from 'react';
import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import Stack from '@mui/material/Stack';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import CheckCircleRoundedIcon from '@mui/icons-material/CheckCircleRounded';
import ErrorOutlineRoundedIcon from '@mui/icons-material/ErrorOutlineRounded';

import { useJob } from '../../api/hooks/useJob';
import { isTerminal } from '../../types/job';
import type { Uuid } from '../../types/common';
import { t } from '../../i18n';

export interface GlobalJobIndicatorProps {
  jobId: Uuid | null;
  /** Opens the error panel when a failed job's chip is clicked. */
  onShowError?: (jobId: Uuid) => void;
}

const STAGE_TEXT: Record<string, string> = {
  fetching_tiles: 'Fetching imagery',
  matching: 'Matching',
  rendering: 'Rendering',
  writing: 'Writing file',
  collecting_gcps: 'Collecting points',
  decoding: 'Decoding',
  thumbnailing: 'Thumbnailing',
};

export function GlobalJobIndicator({
  jobId,
  onShowError,
}: GlobalJobIndicatorProps): JSX.Element | null {
  const { data } = useJob(jobId);
  const job = data?.data;
  const [flash, setFlash] = useState(false);

  // Success flash then auto-hide.
  useEffect(() => {
    if (job?.status === 'succeeded') {
      setFlash(true);
      const id = window.setTimeout(() => setFlash(false), 2500);
      return () => window.clearTimeout(id);
    }
    return undefined;
  }, [job?.status]);

  if (!job) return null;

  const active = !isTerminal(job.status);
  const failed = job.status === 'failed';

  if (failed) {
    return (
      <Chip
        size="small"
        color="error"
        icon={<ErrorOutlineRoundedIcon />}
        label={`${job.type} ${t('failed')}`}
        onClick={onShowError ? () => onShowError(job.id) : undefined}
        variant="outlined"
      />
    );
  }

  if (active) {
    const pct = job.progress.percent;
    const determinate = job.status === 'running' && pct > 0;
    return (
      <Stack direction="row" spacing={1} alignItems="center">
        <CircularProgress
          size={18}
          variant={determinate ? 'determinate' : 'indeterminate'}
          value={pct}
        />
        <Typography variant="caption" color="text.secondary">
          {t(STAGE_TEXT[job.progress.stage] ?? job.type)}
          {determinate ? ` ${Math.round(pct)}%` : ''}
        </Typography>
      </Stack>
    );
  }

  if (flash) {
    return (
      <Tooltip title={`${job.type} ${t('complete')}`}>
        <Box sx={{ display: 'flex' }}>
          <CheckCircleRoundedIcon color="success" fontSize="small" />
        </Box>
      </Tooltip>
    );
  }

  return null;
}

export default GlobalJobIndicator;
