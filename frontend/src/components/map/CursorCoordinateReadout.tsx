/**
 * `map/CursorCoordinateReadout.tsx` — where is the cursor, in the world?
 *
 * ★ THE MOST-ASKED QUESTION A MAP CAN ANSWER, and until now this app only answered
 *   it *after* a point was committed. Hovering is how a surveyor checks a spot
 *   against a printed coordinate, a GPS handset, or a client's spreadsheet — so the
 *   position under the pointer is shown live, in the same format the rest of the app
 *   uses (`workspaceStore.coordinateFormat`: DD / DMS / UTM).
 *
 * ★ HONEST PRECISION. It shows SIX decimals of degree (~0.1 m) — the resolution of
 *   the position itself, NOT a claim about accuracy. Accuracy is a different number
 *   with its own readout (`MapAccuracyReadout`), and conflating "where the pointer
 *   is" with "how well we know it" is exactly the confusion this product refuses.
 *   `formatLatLon` is called with a hair-tight CE90 for that reason: the digits are
 *   about the cursor, and the cursor is exact.
 *
 * ★ `null` renders an em-dash rather than vanishing: a readout that disappears when
 *   the pointer leaves makes the panel jump, and a blank slot says "off the map"
 *   just as clearly.
 */

import type { JSX } from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import MyLocationIcon from '@mui/icons-material/MyLocation';

import { formatLatLon } from '../../lib/geo/format';
import type { CoordinateFormat } from '../../types/common';
import type { LatLon } from '../../types/geo';

export interface CursorCoordinateReadoutProps {
  /** The position under the pointer, or null when it is off the map. */
  at: LatLon | null;
  format: CoordinateFormat;
}

/** ★ Cursor position is exact; this only drives the DECIMAL COUNT, never a claim. */
const EXACT_CE90_M = 0.05;

export function CursorCoordinateReadout({ at, format }: CursorCoordinateReadoutProps): JSX.Element {
  const text = at === null ? '—' : formatLatLon(at, format, EXACT_CE90_M, 'high').text;

  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        gap: 0.75,
        px: 1,
        py: 0.5,
        borderRadius: 1,
        bgcolor: 'background.paper',
        boxShadow: 2,
        pointerEvents: 'none',
        maxWidth: '100%',
      }}
      aria-live="off"
    >
      <MyLocationIcon sx={{ fontSize: 14, color: 'text.disabled' }} />
      <Typography
        variant="mono"
        sx={{ whiteSpace: 'nowrap', color: at === null ? 'text.disabled' : 'text.primary' }}
      >
        {text}
      </Typography>
    </Box>
  );
}

export default CursorCoordinateReadout;
