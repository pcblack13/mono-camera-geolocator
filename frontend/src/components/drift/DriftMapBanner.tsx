/**
 * `drift/DriftMapBanner.tsx` — the map's "stop trusting these coordinates" strip.
 *
 * ★ CONFIRMED VERDICTS ONLY. The banner fires on `status` (three identical
 *   non-OK readings), never on one frame's raw `state` — a bird on the housing
 *   must not paint the map red. And ONLY for MOVED/CHANGED: DEGRADED means
 *   "cannot judge", which is a pill state, not a map alarm.
 *
 * ★ POINTER-TRANSPARENT, like the pairing HUD: it floats over the map's top
 *   edge, and a banner that swallows a pan gesture has broken the map it warns
 *   about. Mount inside the map's own `position: relative` well. The one
 *   exception is its own close button, which must take a click.
 *
 * ★ CLOSABLE (owner ask 2026-09-10). The × asks "show later" (30 minutes) or
 *   "don't show again" (this reference's alarm, remembered across reloads). A
 *   new alarm — a re-frozen reference, or MOVED becoming CHANGED — shows again.
 */

import { useEffect, useState, type JSX } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import IconButton from '@mui/material/IconButton';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import CloseIcon from '@mui/icons-material/Close';
import WarningAmberOutlinedIcon from '@mui/icons-material/WarningAmberOutlined';

import type { DriftVerdict } from '../../api/drift';
import { bannerKey, dontShowAgain, isClosed, showLater } from '../../lib/drift/bannerDismissal';
import { t } from '../../i18n';

export function DriftMapBanner({ verdict }: { verdict: DriftVerdict | null }): JSX.Element | null {
  const alarm = verdict !== null && (verdict.status === 'MOVED' || verdict.status === 'CHANGED');
  const key = alarm ? bannerKey(verdict.ref_id, verdict.status as string) : null;
  // `choosing`: the × was pressed and the two choices are showing.
  const [choosing, setChoosing] = useState(false);
  // Re-read the record whenever the alarm changes (and after a choice).
  const [closedAt, setClosedAt] = useState(0);
  useEffect(() => {
    setChoosing(false);
  }, [key]);

  if (key === null || verdict === null) return null;
  if (isClosed(key)) return null;

  const moved = verdict.status === 'MOVED';
  const colour = moved ? 'var(--status-warn)' : 'var(--status-error)';
  const choose = (later: boolean): void => {
    if (later) showLater(key);
    else dontShowAgain(key);
    setChoosing(false);
    setClosedAt(Date.now()); // re-render: isClosed() is now true
  };
  void closedAt;

  return (
    <Box
      role="alert"
      sx={{
        position: 'absolute',
        top: 8,
        left: '50%',
        transform: 'translateX(-50%)',
        zIndex: 1000, // over Leaflet's panes
        maxWidth: 'min(92%, 560px)',
        display: 'flex',
        alignItems: 'flex-start',
        gap: 1,
        px: 1.5,
        py: 0.75,
        borderRadius: 'var(--radius-md)',
        borderWidth: '1px',
        borderStyle: moved ? 'dashed' : 'solid',
        borderColor: colour,
        bgcolor: 'var(--bg-elevated)',
        // ★ The rule this component lives or dies by.
        pointerEvents: 'none',
      }}
    >
      <WarningAmberOutlinedIcon sx={{ fontSize: 18, mt: '1px', color: colour }} />
      <Box sx={{ minWidth: 0, flex: 1 }}>
        <Typography variant="body2" sx={{ fontWeight: 600, color: colour, lineHeight: 1.3 }}>
          {moved
            ? t('Camera moved — coordinates are no longer trusted.')
            : t('Camera optics changed — coordinates are no longer trusted.')}
        </Typography>
        <Typography variant="caption" sx={{ color: 'var(--text-secondary)', display: 'block' }}>
          {moved
            ? t('Re-aim the camera or re-solve the pose, then freeze a new reference.')
            : t('The mapping needs a full re-solve — re-aiming will not fix it.')}{' '}
          · {t('since')} {verdict.checked_utc}
        </Typography>
        {choosing && (
          <Stack direction="row" spacing={1} sx={{ mt: 0.75, pointerEvents: 'auto' }} useFlexGap flexWrap="wrap">
            <Button size="small" variant="outlined" onClick={() => choose(true)}>
              {t('Show later')}
            </Button>
            <Button size="small" variant="text" color="inherit" onClick={() => choose(false)}>
              {t('Don’t show again')}
            </Button>
            <Button size="small" variant="text" color="inherit" onClick={() => setChoosing(false)} sx={{ color: 'text.secondary' }}>
              {t('Keep it')}
            </Button>
          </Stack>
        )}
      </Box>
      {!choosing && (
        <IconButton
          size="small"
          aria-label={t('Close this warning')}
          onClick={() => setChoosing(true)}
          // ★ The one part of the banner that takes a click.
          sx={{ pointerEvents: 'auto', mt: '-2px', mr: '-6px', color: 'var(--text-secondary)' }}
        >
          <CloseIcon sx={{ fontSize: 16 }} />
        </IconButton>
      )}
    </Box>
  );
}
