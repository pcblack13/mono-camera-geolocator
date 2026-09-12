/**
 * `cameras/FrameChangeDialog.tsx` — a new frame over one that has control points.
 *
 * ★ OWNER ASK (2026-09-09). Adopting a fresh frame used to leave the camera with
 *   zero control points and a lookup table that still read "Done" — built on the
 *   old frame, right only if the camera had not moved, and nothing said which.
 *   So the one question that decides everything is asked, once, before adopting:
 *
 *     Same aim  → the points are carried over at the same pixels, the table stays,
 *                 the drift reference refreshes on the new picture.
 *     It moved  → the points start afresh and the table is DETACHED — a moved
 *                 camera has no valid table, and a stale one must not look finished.
 */

import { type JSX } from 'react';
import Button from '@mui/material/Button';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import CenterFocusStrongOutlinedIcon from '@mui/icons-material/CenterFocusStrongOutlined';
import OpenWithOutlinedIcon from '@mui/icons-material/OpenWithOutlined';

import { t } from '../../i18n';

export type FrameChangeDecision = 'same-aim' | 'moved';

export interface FrameChangeDialogProps {
  open: boolean;
  /** Control points on the frame being replaced. */
  pointCount: number;
  /** The camera has a lookup table built on the old frame. */
  hasTable: boolean;
  busy?: boolean;
  onDecide: (decision: FrameChangeDecision) => void;
  onCancel: () => void;
}

export function FrameChangeDialog({
  open,
  pointCount,
  hasTable,
  busy = false,
  onDecide,
  onCancel,
}: FrameChangeDialogProps): JSX.Element {
  return (
    <Dialog open={open} onClose={busy ? undefined : onCancel} maxWidth="sm" fullWidth>
      <DialogTitle>{t('Has the camera moved?')}</DialogTitle>
      <DialogContent>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          {t('The current frame has {n} control points.').replace('{n}', String(pointCount))}{' '}
          {t('What happens to them depends on whether the camera still looks exactly where it did.')}
        </Typography>
        <Stack spacing={1.5}>
          <Button
            variant="outlined"
            size="large"
            startIcon={<CenterFocusStrongOutlinedIcon />}
            disabled={busy}
            onClick={() => onDecide('same-aim')}
            sx={{ justifyContent: 'flex-start', textAlign: 'start', py: 1.25 }}
            data-testid="frame-change-same-aim"
          >
            <Stack alignItems="flex-start">
              <Typography variant="body2" sx={{ fontWeight: 600 }}>
                {t('No — same aim')}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {hasTable
                  ? t('The control points are carried over at the same pixels, the lookup table stays, and the drift reference refreshes on the new frame.')
                  : t('The control points are carried over at the same pixels.')}
              </Typography>
            </Stack>
          </Button>
          <Button
            variant="outlined"
            size="large"
            color="warning"
            startIcon={<OpenWithOutlinedIcon />}
            disabled={busy}
            onClick={() => onDecide('moved')}
            sx={{ justifyContent: 'flex-start', textAlign: 'start', py: 1.25 }}
            data-testid="frame-change-moved"
          >
            <Stack alignItems="flex-start">
              <Typography variant="body2" sx={{ fontWeight: 600 }}>
                {t('Yes — it moved')}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {hasTable
                  ? t('The points start afresh on the new frame, and the lookup table is detached — it was solved for the old aim and must be rebuilt.')
                  : t('The points start afresh on the new frame.')}
              </Typography>
            </Stack>
          </Button>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onCancel} disabled={busy}>
          {t('Cancel')}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
