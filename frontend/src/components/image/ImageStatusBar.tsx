/**
 * `image/ImageStatusBar.tsx` (pure) — 50-frontend.md §2.10.
 *
 * Zoom %, the live cursor position **in ORIGINAL image pixels** (the readout that lets
 * a surveyor sanity-check a landmark at a glance — §8.6), the image dimensions, and an
 * EXIF-GPS presence indicator. Shows an "Adjusted" chip whenever brightness/contrast
 * is non-neutral, so the user never forgets they are judging a modified rendering
 * (§6.4).
 */

import Chip from '@mui/material/Chip';
import Stack from '@mui/material/Stack';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import GpsFixedIcon from '@mui/icons-material/GpsFixed';
import GpsOffIcon from '@mui/icons-material/GpsOff';
import TuneIcon from '@mui/icons-material/Tune';

import type { Point2D, Size } from '../../types/common';
import { t } from '../../i18n';
import { useViewerStore } from '../../store/viewerStore';

export interface ImageStatusBarProps {
  scale: number;
  /** ORIGINAL image px, or `null` when the cursor is off the canvas. Omit to let the
   *  bar subscribe itself — so a mouse-move re-renders THIS strip, not the whole pane. */
  cursorImagePos?: Point2D | null;
  /** ORIGINAL image dimensions. */
  naturalSize: Size | null;
  hasGps: boolean;
  adjusted: boolean;
}

export function ImageStatusBar({
  scale,
  cursorImagePos,
  naturalSize,
  hasGps,
  adjusted,
}: ImageStatusBarProps): JSX.Element {
  const liveCursor = useViewerStore((st) => st.cursorImagePos);
  const cursor = cursorImagePos === undefined ? liveCursor : cursorImagePos;
  return (
    <Stack
      direction="row"
      spacing={1.5}
      alignItems="center"
      sx={{
        px: 1.5,
        py: 0.5,
        bgcolor: 'background.paper',
        borderTop: 1,
        borderColor: 'divider',
        overflow: 'hidden',
      }}
    >
      <Typography variant="mono" sx={{ fontSize: 11, color: 'text.secondary' }}>
        {Math.round(scale * 100)}%
      </Typography>
      <Typography variant="mono" sx={{ fontSize: 11, color: 'text.secondary', minWidth: 120 }}>
        {cursor ? `x ${cursor.x.toFixed(1)}  y ${cursor.y.toFixed(1)}` : 'x —  y —'}
      </Typography>
      {naturalSize && (
        <Typography variant="mono" sx={{ fontSize: 11, color: 'text.disabled' }}>
          {naturalSize.width}×{naturalSize.height}
        </Typography>
      )}
      <Stack direction="row" spacing={0.5} sx={{ ml: 'auto' }} alignItems="center">
        {adjusted && (
          <Tooltip title="Brightness/contrast adjusted — you are viewing a modified rendering">
            <Chip
              size="small"
              icon={<TuneIcon />}
              label={t('Adjusted')}
              color="primary"
              variant="outlined"
              sx={{ height: 20, fontSize: 10 }}
            />
          </Tooltip>
        )}
        <Tooltip title={hasGps ? 'Photo carries EXIF GPS' : 'No EXIF GPS on this photo'}>
          {hasGps ? (
            <GpsFixedIcon fontSize="small" color="success" aria-label={t('EXIF GPS present')} />
          ) : (
            <GpsOffIcon fontSize="small" color="disabled" aria-label={t('No EXIF GPS')} />
          )}
        </Tooltip>
      </Stack>
    </Stack>
  );
}
