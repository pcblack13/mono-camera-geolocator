/**
 * `ui/StatusPill.tsx` — lifecycle in SHAPE, accuracy in COLOUR.
 *
 * ★ THE SYSTEM'S CENTRAL ENCODING, in one component. Colour is reserved for the
 *   accuracy bands, so a pill may not say "committed" with green. Instead the
 *   BORDER STYLE carries lifecycle — solid committed, dashed draft, double
 *   stale — and the optional dot inside still carries the accuracy band. Two
 *   channels, never competing for one; both survive colour-blindness.
 */

import type { JSX } from 'react';
import Box from '@mui/material/Box';

export type Lifecycle = 'committed' | 'draft' | 'stale' | 'refused';

const BORDER: Record<Lifecycle, { width: string; style: string; color: string }> = {
  committed: { width: '1px', style: 'solid', color: 'var(--hairline-strong)' },
  draft: { width: '1px', style: 'dashed', color: 'var(--status-draft)' },
  stale: { width: '3px', style: 'double', color: 'var(--status-warn)' },
  refused: { width: '1px', style: 'solid', color: 'var(--status-error)' },
};

const INK: Record<Lifecycle, string> = {
  committed: 'var(--text-secondary)',
  draft: 'var(--status-draft)',
  stale: 'var(--text-secondary)',
  refused: 'var(--status-error)',
};

export interface StatusPillProps {
  lifecycle: Lifecycle;
  /** The label — already translated by the caller. */
  children: React.ReactNode;
  /** The accuracy band's colour for the dot; omit when nothing is measured. */
  dotColor?: string;
}

export function StatusPill({ lifecycle, children, dotColor }: StatusPillProps): JSX.Element {
  return (
    <Box
      component="span"
      className="le-mono"
      sx={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 0.75,
        fontSize: 10,
        letterSpacing: '0.04em',
        px: 1,
        py: 0.25,
        borderRadius: 'var(--radius-pill)',
        borderWidth: BORDER[lifecycle].width,
        borderStyle: BORDER[lifecycle].style,
        borderColor: BORDER[lifecycle].color,
        color: INK[lifecycle],
        whiteSpace: 'nowrap',
      }}
    >
      {dotColor !== undefined && (
        <Box
          component="span"
          sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: dotColor, flexShrink: 0 }}
        />
      )}
      {children}
    </Box>
  );
}
