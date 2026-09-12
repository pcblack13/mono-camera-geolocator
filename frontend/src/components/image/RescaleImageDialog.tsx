/**
 * `image/RescaleImageDialog.tsx` — change an existing photo's pixel RESOLUTION
 * (§ resolution feature). Mirrors the server of cameras' remove-confirm style.
 *
 * ★ THE WARNINGS, shown prominently BEFORE the confirm button:
 *   - LANDMARK POINTS: rescaling may make landmark points marked earlier disappear from
 *     the photo; the surveyor is told to re-check and re-mark any that are gone.
 *   - GCPs: their pixel positions move proportionally to the new size — the recorded
 *     lat/lon do NOT change, but the markers must be re-verified afterward.
 *   With neither, there is nothing to warn about and the button is a plain "Rescale".
 *
 * On confirm the mutation resizes the raster server-side and scales the marker pixels,
 * then invalidates the image, its GCPs, its annotations and the list so the viewer
 * reloads at the new size with markers at their scaled positions (see useRescaleImage).
 */

import { useEffect, useState, type JSX } from 'react';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import CircularProgress from '@mui/material/CircularProgress';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import PhotoSizeSelectLargeIcon from '@mui/icons-material/PhotoSizeSelectLarge';

import type { ApiError, Uuid } from '../../types/common';
import { useRescaleImage, useRestoreImageResolution } from '../../api/hooks/useImages';
import { useGcps } from '../../api/hooks/useGcps';
import { useAnnotationStore } from '../../store/annotationStore';
import { useNotify } from '../common/Notifications';
import { ResolutionFields } from './ResolutionFields';
import { t } from '../../i18n';

export interface RescaleImageDialogProps {
  open: boolean;
  imageId: Uuid;
  filename: string;
  currentWidth: number;
  currentHeight: number;
  onClose: () => void;
  onRescaled?: () => void;
}

export function RescaleImageDialog({
  open,
  imageId,
  filename,
  currentWidth,
  currentHeight,
  onClose,
  onRescaled,
}: RescaleImageDialogProps): JSX.Element {
  const notify = useNotify();
  const rescale = useRescaleImage(imageId);
  const restore = useRestoreImageResolution(imageId);

  // ★ THE UNDO. Restores the pristine camera bytes the first rescale set aside —
  //   not an upsample. The server answers 422 when the photo was never rescaled;
  //   that message is shown as-is rather than pre-guessed client-side.
  const handleRestore = (): void => {
    restore.mutate(undefined, {
      onSuccess: (image) => {
        notify(`Restored ${image.width}×${image.height} — the original resolution.`, {
          severity: 'success',
        });
        onRescaled?.();
        onClose();
      },
      onError: (error) =>
        notify((error as ApiError)?.message ?? 'Could not restore the original.', {
          severity: 'warning',
        }),
    });
  };

  // ★ Counts drive the warnings. `ImageRead.counts` is not populated on the detail endpoint,
  //   so read reliable client-side sources: the live landmark draft, and the GCP list query.
  const landmarkCount = useAnnotationStore(
    (s) => s.draft.annotations.filter((a) => !a.is_deleted).length,
  );
  const gcpCount = useGcps(imageId).data?.total ?? 0;

  const [width, setWidth] = useState(currentWidth);
  const [height, setHeight] = useState(currentHeight);

  // Re-seed to the photo's current size whenever the dialog (re)opens or the photo changes.
  useEffect(() => {
    if (open) {
      setWidth(currentWidth);
      setHeight(currentHeight);
    }
  }, [open, currentWidth, currentHeight]);

  const hasGcps = gcpCount > 0;
  const hasLandmarks = landmarkCount > 0;
  const unchanged = width === currentWidth && height === currentHeight;
  const invalid = width < 1 || height < 1;
  const canConfirm = !unchanged && !invalid && !rescale.isPending;

  const handleConfirm = (): void => {
    if (!canConfirm) return;
    rescale.mutate(
      { width, height },
      {
        onSuccess: () => {
          notify(`Rescaled to ${width} × ${height}.`, { severity: 'success' });
          onRescaled?.();
          onClose();
        },
        onError: (error) => {
          const message = (error as ApiError)?.message ?? 'Could not rescale this photo.';
          notify(message, { severity: 'error' });
        },
      },
    );
  };

  return (
    <Dialog open={open} onClose={rescale.isPending ? undefined : onClose} maxWidth="xs" fullWidth>
      <DialogTitle>{t('Change resolution')}</DialogTitle>
      <DialogContent dividers>
        <Stack spacing={2}>
          <Typography variant="body2" color="text.secondary" noWrap title={filename}>
            {filename}
          </Typography>
          <Typography variant="body2">
            Current size:{' '}
            <Typography component="span" variant="mono" sx={{ fontSize: 13 }}>
              {currentWidth} × {currentHeight}
            </Typography>
          </Typography>

          <ResolutionFields
            originalWidth={currentWidth}
            originalHeight={currentHeight}
            width={width}
            height={height}
            onChange={(w, h) => {
              setWidth(w);
              setHeight(h);
            }}
            disabled={rescale.isPending}
          />

          {hasLandmarks && (
            <Alert severity="warning">
              <strong>
                This photo has {landmarkCount} landmark point{landmarkCount === 1 ? '' : 's'} you
                marked earlier — rescaling may make {landmarkCount === 1 ? 'it' : 'them'} disappear
                from the photo.
              </strong>{' '}
              After rescaling, re-check the landmark markers and re-mark any that are gone.
            </Alert>
          )}

          {hasGcps && (
            <Alert severity="warning">
              This photo has {gcpCount} ground control point{gcpCount === 1 ? '' : 's'}. Rescaling
              will move their pixel positions proportionally to match the new size. Your recorded
              coordinates (latitude/longitude) will NOT change, but please verify the markers still
              sit on the right features afterward.
            </Alert>
          )}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ justifyContent: 'space-between' }}>
        <Button
          size="small"
          onClick={handleRestore}
          disabled={rescale.isPending || restore.isPending}
          startIcon={restore.isPending ? <CircularProgress size={14} color="inherit" /> : undefined}
        >
          {restore.isPending ? 'Restoring…' : 'Restore original'}
        </Button>
        <Box>
          <Button onClick={onClose} color="inherit" disabled={rescale.isPending} sx={{ mr: 1 }}>
            {t('Cancel')}
          </Button>
          <Button
            onClick={handleConfirm}
            variant="contained"
            disabled={!canConfirm}
            startIcon={
              rescale.isPending ? (
                <CircularProgress size={16} color="inherit" />
              ) : (
                <PhotoSizeSelectLargeIcon />
              )
            }
          >
            {rescale.isPending ? 'Rescaling…' : hasGcps ? 'Rescale & keep GCPs' : 'Rescale'}
          </Button>
        </Box>
      </DialogActions>
    </Dialog>
  );
}

export default RescaleImageDialog;
