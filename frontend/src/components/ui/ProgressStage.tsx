/**
 * `ui/ProgressStage.tsx` — staged progress that cannot lie.
 *
 * ★ A PERCENTAGE BAR LIES BY CONSTRUCTION on multi-stage work: 60% of what? This
 *   shows the stages themselves — done, running, waiting — so "where is it" and
 *   "what failed" are the same glance. A failed stage KEEPS its message; the
 *   stages after it show as never-started, because that is the truth.
 */

import type { JSX } from 'react';
import Box from '@mui/material/Box';
import CircularProgress from '@mui/material/CircularProgress';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';

export interface Stage {
  /** Already translated by the caller. */
  label: string;
  state: 'done' | 'running' | 'waiting' | 'failed';
  /** Progress within THIS stage when the server reports one, 0–100. */
  pct?: number;
  /** A failed stage's verbatim message. */
  message?: string;
}

export function ProgressStage({ stages }: { stages: readonly Stage[] }): JSX.Element {
  return (
    <Stack spacing={0.5}>
      {stages.map((s) => (
        <Stack key={s.label} direction="row" alignItems="center" spacing={1}>
          <Box sx={{ width: 18, display: 'flex', justifyContent: 'center', flexShrink: 0 }}>
            {s.state === 'done' && (
              <CheckCircleOutlineIcon sx={{ fontSize: 15, color: 'var(--status-ok)' }} />
            )}
            {s.state === 'running' && <CircularProgress size={12} thickness={5} />}
            {s.state === 'failed' && (
              <ErrorOutlineIcon sx={{ fontSize: 15, color: 'var(--status-error)' }} />
            )}
            {s.state === 'waiting' && (
              <Box
                sx={{
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  border: '1px solid var(--hairline-strong)',
                }}
              />
            )}
          </Box>
          <Typography
            variant="caption"
            sx={{
              color:
                s.state === 'waiting'
                  ? 'text.disabled'
                  : s.state === 'failed'
                    ? 'error.main'
                    : 'text.secondary',
            }}
          >
            {s.label}
            {s.state === 'running' && s.pct !== undefined && (
              <Typography component="span" className="le-mono" sx={{ fontSize: 11, ml: 0.75 }}>
                {Math.round(s.pct)}%
              </Typography>
            )}
          </Typography>
        </Stack>
      ))}
      {stages
        .filter((s) => s.state === 'failed' && s.message !== undefined)
        .map((s) => (
          <Typography
            key={`${s.label}-msg`}
            className="le-mono"
            sx={{ fontSize: 11, color: 'error.main', pl: 3.25, wordBreak: 'break-word' }}
          >
            {s.message}
          </Typography>
        ))}
    </Stack>
  );
}
