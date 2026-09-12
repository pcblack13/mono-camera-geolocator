/**
 * `image/ResolutionFields.tsx` — the shared pixel-RESOLUTION editor (§ resolution feature).
 *
 * A controlled widget: the parent owns `width`/`height`, this renders the two integer
 * inputs plus an aspect-ratio LOCK and a quick scale-% row, and calls `onChange(w, h)`.
 *
 * ★ THE ASPECT LOCK (default ON). While locked, editing ONE dimension recomputes the
 *   OTHER from the ORIGINAL ratio (`originalWidth / originalHeight`) — not from the
 *   current field, so rounding never drifts across successive edits. Unlock to set a
 *   free (non-proportional) size. The scale-% buttons always derive both dimensions
 *   straight from the original, so they are exact regardless of the lock.
 *
 * Used by both the upload-time control (`upload/PhotoUploadDialog`) and the post-upload
 * `image/RescaleImageDialog`.
 */

import { useState, type JSX } from 'react';
import Button from '@mui/material/Button';
import IconButton from '@mui/material/IconButton';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import LinkIcon from '@mui/icons-material/Link';
import LinkOffIcon from '@mui/icons-material/LinkOff';
import { t } from '../../i18n';

const SCALES = [100, 75, 50, 25] as const;

export interface ResolutionFieldsProps {
  /** The source dimensions the ratio and scale-% are derived from. */
  originalWidth: number;
  originalHeight: number;
  /** Current target — parent-owned. `0` renders an empty field. */
  width: number;
  height: number;
  onChange: (width: number, height: number) => void;
  disabled?: boolean;
}

/** Parse an input string to a positive integer; `0` for empty/invalid (parent validates). */
function toInt(raw: string): number {
  const n = Math.floor(Number(raw));
  return Number.isFinite(n) && n > 0 ? n : 0;
}

export function ResolutionFields({
  originalWidth,
  originalHeight,
  width,
  height,
  onChange,
  disabled = false,
}: ResolutionFieldsProps): JSX.Element {
  const [locked, setLocked] = useState(true);
  const ratio = originalHeight > 0 ? originalWidth / originalHeight : 0;

  const handleWidth = (raw: string): void => {
    const w = toInt(raw);
    if (locked && ratio > 0 && w > 0) onChange(w, Math.max(1, Math.round(w / ratio)));
    else onChange(w, height);
  };

  const handleHeight = (raw: string): void => {
    const h = toInt(raw);
    if (locked && ratio > 0 && h > 0) onChange(Math.max(1, Math.round(h * ratio)), h);
    else onChange(width, h);
  };

  const applyScale = (pct: number): void => {
    onChange(
      Math.max(1, Math.round((originalWidth * pct) / 100)),
      Math.max(1, Math.round((originalHeight * pct) / 100)),
    );
  };

  return (
    <Stack spacing={1.5}>
      <Stack direction="row" spacing={1} alignItems="center">
        <TextField
          label={t('Width')}
          type="number"
          size="small"
          value={width || ''}
          onChange={(e) => handleWidth(e.target.value)}
          disabled={disabled}
          inputProps={{ min: 1, step: 1 }}
          sx={{ width: 120 }}
        />
        <Typography variant="body2" color="text.secondary">
          ×
        </Typography>
        <TextField
          label={t('Height')}
          type="number"
          size="small"
          value={height || ''}
          onChange={(e) => handleHeight(e.target.value)}
          disabled={disabled}
          inputProps={{ min: 1, step: 1 }}
          sx={{ width: 120 }}
        />
        <Tooltip
          title={
            locked
              ? 'Aspect ratio locked — editing one dimension updates the other'
              : 'Aspect ratio unlocked — set width and height freely'
          }
        >
          <span>
            <IconButton
              onClick={() => setLocked((v) => !v)}
              disabled={disabled}
              color={locked ? 'primary' : 'default'}
              aria-label={locked ? 'Unlock aspect ratio' : 'Lock aspect ratio'}
            >
              {locked ? <LinkIcon /> : <LinkOffIcon />}
            </IconButton>
          </span>
        </Tooltip>
      </Stack>

      <Stack direction="row" spacing={1} alignItems="center" sx={{ flexWrap: 'wrap', gap: 0.5 }}>
        <Typography variant="caption" color="text.secondary" sx={{ mr: 0.5 }}>
          {t('Scale')}
        </Typography>
        {SCALES.map((pct) => (
          <Button
            key={pct}
            size="small"
            variant="outlined"
            onClick={() => applyScale(pct)}
            disabled={disabled}
          >
            {pct}%
          </Button>
        ))}
      </Stack>
    </Stack>
  );
}

export default ResolutionFields;
