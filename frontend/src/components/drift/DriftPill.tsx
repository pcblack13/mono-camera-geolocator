/**
 * `drift/DriftPill.tsx` — the four verdicts, in colour AND shape.
 *
 * ★ THE TWO-CHANNEL RULE, applied to drift: each state gets a colour severity
 *   and its OWN border style, so the four stay four under colour-blindness:
 *
 *     OK        solid  · status-ok      — steady, keep trusting
 *     MOVED     dashed · status-warn    — re-aim or re-solve
 *     CHANGED   double · status-error   — optics changed; full re-solve
 *     DEGRADED  solid  · neutral        — "cannot judge". NOT an alarm: painting
 *                                         fog red would be the monitor lying.
 */

import type { JSX } from 'react';
import Box from '@mui/material/Box';

import type { DriftState } from '../../api/drift';
import { t } from '../../i18n';

const STYLE: Record<DriftState, { width: string; style: string; color: string; ink: string }> = {
  OK: { width: '1px', style: 'solid', color: 'var(--status-ok)', ink: 'var(--status-ok)' },
  MOVED: { width: '2px', style: 'dashed', color: 'var(--status-warn)', ink: 'var(--status-warn)' },
  CHANGED: {
    width: '3px',
    style: 'double',
    color: 'var(--status-error)',
    ink: 'var(--status-error)',
  },
  DEGRADED: {
    width: '1px',
    style: 'solid',
    color: 'var(--hairline-strong)',
    ink: 'var(--text-secondary)',
  },
};

export const DRIFT_LABEL: Record<DriftState, string> = {
  OK: 'Camera steady',
  MOVED: 'Camera moved',
  CHANGED: 'Optics changed',
  DEGRADED: 'Cannot judge',
};

export interface DriftPillProps {
  state: DriftState;
  /** True when this is the CONFIRMED status, not one frame's raw reading. */
  confirmed?: boolean;
}

export function DriftPill({ state, confirmed = false }: DriftPillProps): JSX.Element {
  const s = STYLE[state];
  return (
    <Box
      component="span"
      className="le-mono"
      data-drift-state={state}
      sx={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 0.75,
        fontSize: 10,
        letterSpacing: '0.04em',
        px: 1,
        py: 0.25,
        borderRadius: 'var(--radius-pill)',
        borderWidth: s.width,
        borderStyle: s.style,
        borderColor: s.color,
        color: s.ink,
        whiteSpace: 'nowrap',
      }}
    >
      <Box
        component="span"
        sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: s.color, flexShrink: 0 }}
      />
      {t(DRIFT_LABEL[state])}
      {/* ★ A raw single-frame reading trails an ellipsis — only the temporally
          confirmed status speaks without qualification. */}
      {!confirmed && <span aria-hidden>…</span>}
    </Box>
  );
}
