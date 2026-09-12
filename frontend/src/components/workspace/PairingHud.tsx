/**
 * `workspace/PairingHud.tsx` — the guided pairing strip: photo → map → F1.
 *
 * ★ THE COMMIT KEY IS SHOWN INLINE, never only in a tooltip. The correspondence
 *   flow is the product's core action, and its finish key was knowledge you had
 *   to already have — the inspector mentions it, but the inspector sits in a side
 *   column the eye has left while lining up a corner. This strip rides over the
 *   workspace, says which endpoint is done and which is owed, and names the key
 *   the moment the pair becomes committable.
 *
 * ★ POINTER-TRANSPARENT, absolutely. It floats over the map's bottom edge, and a
 *   HUD that swallows one click has broken the exact interaction it narrates.
 *
 * ★ Reads the store, renders text: no coordinate ever passes through here — the
 *   Phase 4 gate ("no change may touch the photo↔map mapping") is honoured by
 *   construction.
 */

import type { JSX } from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';

import { t } from '../../i18n';
import { useCorrespondenceStore } from '../../store';

function Step({ done, label }: { done: boolean; label: string }): JSX.Element {
  return (
    <Typography
      component="span"
      className="le-mono"
      sx={{
        fontSize: 11,
        color: done ? 'var(--status-ok)' : 'var(--text-secondary)',
        whiteSpace: 'nowrap',
      }}
    >
      {label}
      {done ? ' ✓' : '…'}
    </Typography>
  );
}

export function PairingHud(): JSX.Element | null {
  const status = useCorrespondenceStore((s) => s.status);
  if (status === 'idle') return null;

  const photoDone =
    status === 'awaiting_map_point' || status === 'ready' || status === 'committing';
  const mapDone =
    status === 'awaiting_photo_point' || status === 'ready' || status === 'committing';

  return (
    <Box
      role="status"
      aria-live="polite"
      sx={{
        position: 'absolute',
        left: '50%',
        bottom: 12,
        transform: 'translateX(-50%)',
        zIndex: (theme) => theme.zIndex.snackbar - 1,
        display: 'flex',
        alignItems: 'center',
        gap: 1.5,
        px: 1.75,
        py: 0.75,
        borderRadius: 'var(--radius-pill)',
        border: '1px solid var(--hairline-strong)',
        bgcolor: 'var(--scrim-hud)',
        backdropFilter: 'blur(4px)',
        // ★ The rule this component lives or dies by.
        pointerEvents: 'none',
      }}
    >
      <Step done={photoDone} label={`① ${t('Photograph')}`} />
      <Step done={mapDone} label={`② ${t('Map')}`} />
      {status === 'ready' && (
        <Typography
          component="span"
          className="le-mono"
          sx={{
            fontSize: 10,
            px: 0.9,
            py: 0.2,
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--accent)',
            color: 'var(--accent)',
            letterSpacing: '0.06em',
          }}
        >
          F1 · {t('COMMIT')}
        </Typography>
      )}
      {status === 'committing' && (
        <Typography
          component="span"
          className="le-mono"
          sx={{ fontSize: 10.5, color: 'var(--status-busy)' }}
        >
          {t('committing…')}
        </Typography>
      )}
    </Box>
  );
}
