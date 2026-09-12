/**
 * `common/ConfidenceBar.tsx` — the length encoding of confidence (50-frontend §8.6).
 *
 * ★ One of the THREE REDUNDANT ENCODINGS the table cell carries (length, colour,
 *   text) so the meaning survives colour-blindness and greyscale printing (§8.8
 *   item 6). This component is length + colour; the numeric and the band label sit
 *   beside it in `ConfidenceCell` (IU-27).
 *
 * ★ It NEVER computes a colour inline — it derives the band via `confidenceBand`
 *   (the single source of truth in `theme/confidence.ts`) and reads the colour from
 *   the theme palette. "No component computes a confidence colour inline."
 *
 * ★ (pure).
 */

import type { JSX } from 'react';
import Box from '@mui/material/Box';
import { useTheme } from '@mui/material/styles';

import { confidenceBand } from '../../lib/confidence';
import type { ConfidenceBand } from '../../types/gcp';

export interface ConfidenceBarProps {
  /** 0–100 (the `GcpRead.confidence` scale). */
  value: number;
  /** Override the derived band — pass when a caller already knows it (e.g. manual). */
  band?: ConfidenceBand;
  height?: number;
  /** The full-width unfilled track behind the fill. */
  showTrack?: boolean;
}

export function ConfidenceBar({
  value,
  band,
  height = 6,
  showTrack = true,
}: ConfidenceBarProps): JSX.Element {
  const theme = useTheme();
  const clamped = Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 0;
  const resolvedBand: ConfidenceBand = band ?? confidenceBand(clamped);
  const color = theme.palette.confidence[resolvedBand];

  return (
    <Box
      aria-hidden
      sx={{
        width: '100%',
        minWidth: 48,
        height,
        borderRadius: height / 2,
        overflow: 'hidden',
        bgcolor: showTrack ? 'action.hover' : 'transparent',
      }}
    >
      <Box
        sx={{
          width: `${clamped}%`,
          height: '100%',
          borderRadius: height / 2,
          bgcolor: color,
          transition: theme.transitions.create('width', {
            duration: theme.transitions.duration.short,
          }),
        }}
      />
    </Box>
  );
}

export default ConfidenceBar;
