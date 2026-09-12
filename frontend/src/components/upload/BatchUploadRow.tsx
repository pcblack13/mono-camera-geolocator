/**
 * `upload/BatchUploadRow.tsx` — one row of the batch upload queue (50-frontend §2.25).
 *
 * ★ (pure). Renders a single `UploadItem` from `uploadStore`: thumbnail, filename,
 *   size, EXIF-GPS badge, per-item progress, and the retry/remove affordances. It
 *   reads nothing and mutates nothing — the container passes the item and the
 *   callbacks.
 *
 * ★ `processing` is shown distinctly from `done`: the bytes are up but the server's
 *   ingest job is still running, and the surveyor cannot open the image yet (§8.4).
 *   Saying "done" there would promise an image that is not ready.
 */

import type { JSX } from 'react';
import Avatar from '@mui/material/Avatar';
import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import IconButton from '@mui/material/IconButton';
import LinearProgress from '@mui/material/LinearProgress';
import Stack from '@mui/material/Stack';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import CheckCircleRoundedIcon from '@mui/icons-material/CheckCircleRounded';
import ErrorOutlineRoundedIcon from '@mui/icons-material/ErrorOutlineRounded';
import GpsFixedRoundedIcon from '@mui/icons-material/GpsFixedRounded';
import RefreshRoundedIcon from '@mui/icons-material/RefreshRounded';
import CloseRoundedIcon from '@mui/icons-material/CloseRounded';

import type { UploadItem, UploadStatus } from '../../store/uploadStore';
import { t } from '../../i18n';

export interface BatchUploadRowProps {
  item: UploadItem;
  onRetry: (clientId: string) => void;
  onRemove: (clientId: string) => void;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB'];
  let value = bytes / 1024;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[i]}`;
}

const STATUS_LABEL: Record<UploadStatus, string> = {
  queued: 'Queued',
  uploading: 'Uploading',
  processing: 'Processing',
  done: 'Ready',
  error: 'Failed',
  cancelled: 'Cancelled',
};

export function BatchUploadRow({ item, onRetry, onRemove }: BatchUploadRowProps): JSX.Element {
  const { status } = item;
  const isError = status === 'error' || status === 'cancelled';
  const isDone = status === 'done';
  const isActive = status === 'uploading';
  const isProcessing = status === 'processing';

  return (
    <Stack
      direction="row"
      spacing={1.5}
      alignItems="center"
      sx={{ py: 1, px: 0.5, borderBottom: 1, borderColor: 'divider' }}
    >
      <Avatar
        variant="rounded"
        src={item.previewUrl}
        alt=""
        sx={{ width: 44, height: 44, bgcolor: 'action.hover' }}
      />

      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Stack direction="row" spacing={0.75} alignItems="center">
          <Typography variant="body2" noWrap sx={{ flex: 1, minWidth: 0 }} title={item.file.name}>
            {item.file.name}
          </Typography>
          {item.exifHint !== null && (
            <Tooltip
              title={`Photo GPS: ${item.exifHint.lat.toFixed(4)}, ${item.exifHint.lon.toFixed(4)}`}
            >
              <GpsFixedRoundedIcon fontSize="small" color="success" aria-label={t('Has GPS')} />
            </Tooltip>
          )}
        </Stack>

        <Stack direction="row" spacing={1} alignItems="center">
          <Typography variant="caption" color="text.secondary">
            {formatBytes(item.file.size)}
          </Typography>
          <Chip
            size="small"
            label={STATUS_LABEL[status]}
            variant="outlined"
            color={isError ? 'error' : isDone ? 'success' : isProcessing ? 'info' : 'default'}
          />
        </Stack>

        {(isActive || isProcessing) && (
          <LinearProgress
            variant={isProcessing ? 'indeterminate' : 'determinate'}
            value={Math.round(item.progress * 100)}
            sx={{ mt: 0.75, height: 4, borderRadius: 2 }}
          />
        )}

        {status === 'error' && item.error !== null && (
          <Typography variant="caption" color="error" sx={{ display: 'block', mt: 0.25 }}>
            {item.error.body.message}
          </Typography>
        )}
      </Box>

      <Stack direction="row" spacing={0.25} alignItems="center">
        {isDone && (
          <CheckCircleRoundedIcon color="success" fontSize="small" aria-label={t('Uploaded')} />
        )}
        {status === 'error' && (
          <>
            <ErrorOutlineRoundedIcon color="error" fontSize="small" aria-hidden />
            <Tooltip title={t('Retry')}>
              <IconButton size="small" onClick={() => onRetry(item.clientId)}>
                <RefreshRoundedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </>
        )}
        <Tooltip title={t('Remove')}>
          <IconButton size="small" onClick={() => onRemove(item.clientId)}>
            <CloseRoundedIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Stack>
    </Stack>
  );
}

export default BatchUploadRow;
