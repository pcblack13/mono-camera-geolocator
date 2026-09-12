/**
 * `gcp/AccuracyLoopStatus.tsx` — what the accuracy loop is doing, on the picking page.
 *
 * ★ THE LOOP RUNS WITHOUT BEING ASKED, so it has to account for itself where the work
 *   happens. This is one line in the GCP toolbar, and it answers the only three
 *   questions a surveyor has while placing points:
 *
 *     "is it doing something?"   → the running message, with progress
 *     "how wrong am I?"          → the current median error
 *     "am I done?"               → ENOUGH, once another point would not pay
 *
 * ★ "ENOUGH" IS THE POINT OF THE WHOLE FEATURE. Knowing when to stop placing control
 *   points is what the suggestion score is for — a surveyor who stops three points
 *   early has a worse survey, and one who places ten more has wasted a morning. So the
 *   verdict is stated plainly, with the number behind it, and it is never louder than
 *   the evidence: it says the best remaining region would cut only N%.
 */

import type { JSX } from 'react';
import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import PlaceOutlinedIcon from '@mui/icons-material/PlaceOutlined';

import type { AccuracyState } from '../../api/accuracy';

export interface AccuracyLoopStatusProps {
  state: AccuracyState | undefined;
  /** From the autopilot — a stage of the cycle is in flight. */
  running: boolean;
  /** The loop's own message while it works, or a countdown to the fourth point. */
  message: string | null;
  converged: boolean;
}

export function AccuracyLoopStatus({
  state,
  running,
  message,
  converged,
}: AccuracyLoopStatusProps): JSX.Element | null {
  const measurement = state?.measurement ?? null;
  const suggestions = state?.suggestions ?? null;

  if (running) {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, minWidth: 0 }}>
        <CircularProgress size={13} thickness={5} />
        <Typography variant="caption" color="text.secondary" noWrap>
          {message ?? 'working…'}
        </Typography>
      </Box>
    );
  }

  if (converged && suggestions !== null) {
    return (
      <Tooltip
        title={`The best remaining region would cut only ${suggestions.best_cut_pct.toFixed(
          0,
        )}% of the predicted error — below your ${suggestions.stop_below_pct.toFixed(
          0,
        )}% threshold. More points have stopped buying accuracy.`}
      >
        <Chip
          size="small"
          color="success"
          icon={<CheckCircleOutlineIcon />}
          label={`Enough points${
            measurement?.median_error_m != null
              ? ` · ${measurement.median_error_m.toFixed(1)} m`
              : ''
          }`}
        />
      </Tooltip>
    );
  }

  if (measurement !== null) {
    const next = suggestions?.regions[0];
    // ★ TWO NUMBERS, ALWAYS — the technique's own caption. `raw` is what was measured
    //   (median of the locked tiles); `corrected` is the candidate that won on held-out
    //   ground, which is also the field the satellite pane draws. Showing the corrected
    //   figure alone would claim an accuracy the survey does not currently have;
    //   showing only the raw one would hide what the correction is worth.
    const raw = measurement.median_error_m;
    const winner = state?.solutions?.entries.find((e) => e.key === state.solutions?.best);
    const corrected = winner?.all_m ?? null;
    const improved = raw != null && corrected != null && corrected < raw;

    return (
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, minWidth: 0 }}>
        <Tooltip
          title={
            `Measured against ${measurement.provider}: ${(100 * measurement.match_rate).toFixed(0)}% ` +
            `of ${measurement.tiles_total} tiles locked.` +
            (corrected != null
              ? ` The first figure is ${winner?.label ?? 'the winning correction'}; ` +
                `"was" is the uncorrected measurement it started from.`
              : ' Not corrected yet — this is the raw measured error.')
          }
        >
          <Chip
            size="small"
            variant="outlined"
            color={improved ? 'success' : 'default'}
            label={
              corrected != null
                ? `error ${corrected.toFixed(1)} m (was ${raw?.toFixed(1) ?? '?'})`
                : `error ${raw?.toFixed(1) ?? '?'} m`
            }
          />
        </Tooltip>
        {next != null && (
          <Tooltip title={next.reasons.join(' · ')}>
            <Chip
              size="small"
              variant="outlined"
              icon={<PlaceOutlinedIcon />}
              label={`next point: −${next.cut_pct.toFixed(0)}%`}
            />
          </Tooltip>
        )}
      </Box>
    );
  }

  return message === null ? null : (
    <Typography variant="caption" color="text.secondary" noWrap>
      {message}
    </Typography>
  );
}
