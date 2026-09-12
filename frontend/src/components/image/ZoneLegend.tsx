/**
 * `image/ZoneLegend.tsx` — what the zone colours mean, in metres.
 *
 * ★ A DOM CHIP, NOT A KONVA NODE: a legend must stay put at the corner of the pane
 *   while the photograph zooms and pans under it, which is exactly what the stage
 *   transform would prevent. The satellite pane's own legend works the same way.
 *
 * ★ ITS TWO ENDS ARE THIS MEASUREMENT'S BEST AND WORST ZONE, not a fixed scale: the
 *   overlay exists to be compared zone against zone, and a fixed scale would wash
 *   every zone of a good run into the same pale tint.
 */

import type { JSX } from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';

import { HEAT_STOPS } from '../../theme/dataColors';
import { t } from '../../i18n';

export interface ZoneLegendProps {
  /** The scale's two ends, metres. Null draws nothing — there is nothing to explain. */
  range: [number, number] | null | undefined;
}

export function ZoneLegend({ range }: ZoneLegendProps): JSX.Element | null {
  if (!range) return null;
  const [lo, hi] = range;
  return (
    <Box
      data-testid="zone-legend"
      sx={{
        position: 'absolute',
        left: 12,
        bottom: 12,
        px: 1.25,
        py: 0.75,
        borderRadius: 1.5,
        bgcolor: 'var(--surface-overlay, rgba(15, 20, 28, 0.78))',
        color: 'var(--text-primary)',
        pointerEvents: 'none',
        minWidth: 150,
        zIndex: 3,
      }}
    >
      <Typography variant="caption" sx={{ display: 'block', lineHeight: 1.3, opacity: 0.85 }}>
        {t('median error vs satellite')}
      </Typography>
      <Box
        sx={{
          height: 8,
          borderRadius: 4,
          mt: 0.5,
          background: `linear-gradient(90deg, ${HEAT_STOPS.join(', ')})`,
        }}
      />
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 0.25 }}>
        <Typography variant="caption" sx={{ fontFamily: 'var(--font-mono)' }}>
          {lo.toFixed(1)} m
        </Typography>
        <Typography variant="caption" sx={{ fontFamily: 'var(--font-mono)' }}>
          {hi.toFixed(1)} m
        </Typography>
      </Box>
    </Box>
  );
}
