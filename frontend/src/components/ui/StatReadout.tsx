/**
 * `ui/StatReadout.tsx` — one labelled number, instrument-style.
 *
 * ★ THE VALUE NEVER REFLOWS. Tabular mono, so `34.106613` counting up under a
 *   cursor keeps every glyph in its column. A readout that jitters is a readout
 *   the eye cannot track.
 *
 * ★ NOTHING IS SHOWN AS ZERO. An unmeasured value renders an em-dash: zero is a
 *   measurement, nothing is not — the distinction this whole product exists to
 *   keep honest.
 */

import type { JSX, ReactNode } from 'react';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

export interface StatReadoutProps {
  label: ReactNode;
  /** `null`/`undefined` renders an em-dash — never a zero, never a blank. */
  value: ReactNode | null | undefined;
  /** Optional unit, set apart so the number stays scannable. */
  unit?: string;
  /** Colour the VALUE only — e.g. an accuracy band. Labels stay neutral. */
  valueColor?: string;
}

export function StatReadout({ label, value, unit, valueColor }: StatReadoutProps): JSX.Element {
  const empty = value === null || value === undefined || value === '';
  return (
    <Stack direction="row" justifyContent="space-between" alignItems="baseline" sx={{ py: 0.25 }}>
      <Typography variant="caption" color="text.secondary" sx={{ pr: 2 }}>
        {label}
      </Typography>
      <Typography
        component="span"
        className="le-mono"
        sx={{
          fontSize: 13,
          color: empty ? 'text.disabled' : (valueColor ?? 'text.primary'),
          whiteSpace: 'nowrap',
        }}
      >
        {empty ? '—' : value}
        {!empty && unit !== undefined && (
          <Typography
            component="span"
            className="le-mono"
            sx={{ fontSize: 11, color: 'text.secondary', ml: 0.5 }}
          >
            {unit}
          </Typography>
        )}
      </Typography>
    </Stack>
  );
}
