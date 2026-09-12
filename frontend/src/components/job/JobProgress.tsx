/**
 * `job/JobProgress.tsx` — the canonical job renderer (50-frontend §2.24 / §8.3–8.4).
 *
 * ★ ONE renderer, used by the shell indicator, the map's matching overlay and the
 *   export dialog. Determinate bar when progress is known; INDETERMINATE otherwise —
 *   "we do not fake a determinate bar … a lying progress bar teaches users to
 *   distrust the whole UI" (§8.4). The `JobPhaseStepper` is the primary signal; the
 *   bar is secondary.
 *
 * ★ On failure it renders `JobErrorPanel` with the typed remedy (§8.5). On the
 *   fresh-machine default — a `degraded` job whose only cause is "no deep weights" —
 *   it shows an INFORMATIONAL chip, not a warning (§8.7): SIFT + RANSAC is a real
 *   algorithm and framing it as breakage would be wrong and demoralising.
 *
 * ★ (pure) — takes the job, reports up. Elapsed time is derived locally from the
 *   job's own timestamps, so no store or query is read here.
 */

import { useEffect, useState, type JSX } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import LinearProgress from '@mui/material/LinearProgress';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';

import { isTerminal, type JobRead } from '../../types/job';
import { JobErrorPanel } from './JobErrorPanel';
import { JobPhaseStepper } from './JobPhaseStepper';
import { t } from '../../i18n';

export interface JobProgressProps {
  job: JobRead;
  variant: 'inline' | 'panel' | 'compact';
  onCancel?: () => void;
  onRetry?: () => void;
}

/** ms since the job started (or was created), ticking while it is active. */
function useElapsedMs(job: JobRead): number {
  const startIso = job.started_at ?? job.created_at;
  const start = Date.parse(startIso);
  const active = !isTerminal(job.status);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!active) return undefined;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [active]);

  const end = job.finished_at ? Date.parse(job.finished_at) : now;
  // ★ An unparsable timestamp must read as "no elapsed time", never `NaN:NaN`.
  if (!Number.isFinite(start) || !Number.isFinite(end)) return 0;
  return Math.max(0, end - start);
}

function formatElapsed(ms: number): string {
  const total = Math.floor(ms / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export function JobProgress({ job, variant, onCancel, onRetry }: JobProgressProps): JSX.Element {
  const elapsed = useElapsedMs(job);
  const terminal = isTerminal(job.status);
  const failed = job.status === 'failed' || job.status === 'cancelled';
  const succeeded = job.status === 'succeeded';

  // ── Failure: the typed panel is the whole story ─────────────────────────────
  if (failed && job.error) {
    return <JobErrorPanel error={job.error} onRetry={onRetry} compact={variant !== 'panel'} />;
  }

  const percent = job.progress.percent;
  const determinate = succeeded || (job.status === 'running' && percent > 0);
  const value = succeeded ? 100 : percent;

  const cancellable = !terminal && !job.cancel_requested && onCancel !== undefined;

  // ── Compact: a bare ring-equivalent line for the shell ──────────────────────
  if (variant === 'compact') {
    return (
      <Stack direction="row" spacing={1} alignItems="center" sx={{ minWidth: 120 }}>
        <Box sx={{ flex: 1 }}>
          <LinearProgress
            variant={determinate ? 'determinate' : 'indeterminate'}
            value={value}
            aria-label={`Job ${job.progress.stage}`}
          />
        </Box>
        <Typography variant="mono" color="text.secondary" sx={{ fontSize: 12 }}>
          {formatElapsed(elapsed)}
        </Typography>
      </Stack>
    );
  }

  const showStepper = variant === 'panel';

  return (
    <Stack spacing={variant === 'panel' ? 2 : 1} sx={{ width: '100%' }}>
      <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between">
        <Typography variant="subtitle2">
          {succeeded ? 'Complete' : (job.progress.message ?? humanStatus(job))}
        </Typography>
        <Typography variant="mono" color="text.secondary" sx={{ fontSize: 12 }}>
          {formatElapsed(elapsed)}
        </Typography>
      </Stack>

      <LinearProgress
        variant={determinate ? 'determinate' : 'indeterminate'}
        value={value}
        sx={{ height: 6, borderRadius: 3 }}
        aria-label={`Job progress: ${job.progress.stage}`}
      />

      {job.progress.eta_seconds != null && !terminal && (
        <Typography variant="caption" color="text.secondary">
          About {Math.max(1, Math.round(job.progress.eta_seconds))} s remaining
        </Typography>
      )}

      {/* ★ §8.7 — the fresh-machine default is informational, never a warning. */}
      {job.degraded && (
        <Chip
          size="small"
          icon={<InfoOutlinedIcon />}
          variant="outlined"
          color="info"
          label={job.degradation_reason ?? 'Ran on the classical pipeline'}
          sx={{ alignSelf: 'flex-start' }}
        />
      )}

      {/* ★ §8.3 — a long-running job earns an actionable hint, not an apology. */}
      {!terminal && elapsed > 90_000 && (
        <Typography variant="caption" color="text.secondary">
          {t(
            'Large search areas take longer. Narrowing the location hint speeds this up considerably.',
          )}
        </Typography>
      )}

      {showStepper && (
        <Box sx={{ overflowX: 'auto' }}>
          <JobPhaseStepper type={job.type} stage={job.progress.stage} complete={succeeded} />
        </Box>
      )}

      {cancellable && (
        <Box>
          <Button size="small" color="inherit" onClick={onCancel}>
            {t('Cancel')}
          </Button>
        </Box>
      )}
      {job.cancel_requested && !terminal && (
        <Typography variant="caption" color="text.secondary">
          {t('Cancelling…')}
        </Typography>
      )}
    </Stack>
  );
}

function humanStatus(job: JobRead): string {
  switch (job.status) {
    case 'pending':
    case 'queued':
      return 'Queued';
    case 'running':
      return 'Working…';
    case 'retrying':
      return `Retrying (attempt ${job.attempt} of ${job.max_attempts})`;
    default:
      return 'Working…';
  }
}

export default JobProgress;
