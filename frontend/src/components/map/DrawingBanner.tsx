/**
 * `map/DrawingBanner.tsx` — "you are drawing an area right now".
 *
 * ★ THE STATE USED TO BE INVISIBLE UNTIL THE FIRST CLICK. Pressing "Cache area"
 *   armed the map to collect polygon corners, but the map looked exactly as it had a
 *   moment before: same cursor, no message on it. A surveyor could click intending
 *   to place a GCP and instead drop a cache vertex — or, more often, not realise
 *   drawing had started at all. Two cues fix that, and both live where the eyes
 *   already are (on the map, not in a side panel):
 *     1. a CROSSHAIR cursor over the whole map — the same "you are placing
 *        something" language the correspondence flow uses;
 *     2. this banner, which counts the corners as they land and says when enough
 *        exist to finish.
 *
 * ★ `pointerEvents: 'none'` — it must never eat a click meant for the map beneath.
 */

import type { JSX } from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import HighlightAltIcon from '@mui/icons-material/HighlightAlt';

export interface DrawingBannerProps {
  /** Corners placed so far. */
  count: number;
  /** Below this, the outline is not yet an area. */
  minimum?: number;
}

export function DrawingBanner({ count, minimum = 3 }: DrawingBannerProps): JSX.Element {
  const remaining = Math.max(0, minimum - count);
  return (
    <Box
      role="status"
      sx={{
        position: 'absolute',
        top: 12,
        left: '50%',
        transform: 'translateX(-50%)',
        zIndex: 1200,
        pointerEvents: 'none',
        display: 'flex',
        alignItems: 'center',
        gap: 1,
        px: 2,
        py: 1,
        borderRadius: 2,
        bgcolor: 'primary.main',
        color: 'primary.contrastText',
        boxShadow: 6,
        maxWidth: '90%',
      }}
    >
      <HighlightAltIcon fontSize="small" />
      <Typography variant="body2" sx={{ fontWeight: 600 }}>
        {remaining > 0
          ? `Click the corners of the area to cache — ${remaining} more needed`
          : `${count} corners — click more, or press “Done” to finish the area`}
      </Typography>
    </Box>
  );
}

export default DrawingBanner;
