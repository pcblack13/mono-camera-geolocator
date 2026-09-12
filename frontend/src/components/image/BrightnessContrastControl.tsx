/**
 * `image/BrightnessContrastControl.tsx` (pure) — 50-frontend.md §2.10 / §6.4.
 *
 * Two sliders on the `-100 … 0 … +100` UI range (0 = neutral), plus reset. The
 * mapping to the CSS filter lives in `viewerStore.adjustmentsToFilterCss`; this
 * component only reports the UI value.
 *
 * ★ These are a HUMAN AID, never a preprocessing step (§6.4). The backend extracts
 *   features from the ORIGINAL raster; the slider changes what the surveyor sees, and
 *   `ImageStatusBar` shows an "Adjusted" chip so they never forget they are judging a
 *   modified rendering. `aria-valuetext` states the adjustment in words.
 */

import Box from '@mui/material/Box';
import IconButton from '@mui/material/IconButton';
import Slider from '@mui/material/Slider';
import Stack from '@mui/material/Stack';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import Brightness6Icon from '@mui/icons-material/Brightness6';
import ContrastIcon from '@mui/icons-material/Contrast';
import RestartAltIcon from '@mui/icons-material/RestartAlt';
import { t } from '../../i18n';

export interface BrightnessContrastControlProps {
  brightness: number;
  contrast: number;
  onBrightnessChange: (v: number) => void;
  onContrastChange: (v: number) => void;
  onReset: () => void;
}

function valueText(label: string, v: number): string {
  if (v === 0) return `${label} normal`;
  return `${label} ${Math.abs(v)}% ${v > 0 ? 'above' : 'below'} normal`;
}

export function BrightnessContrastControl({
  brightness,
  contrast,
  onBrightnessChange,
  onContrastChange,
  onReset,
}: BrightnessContrastControlProps): JSX.Element {
  const dirty = brightness !== 0 || contrast !== 0;
  return (
    <Stack spacing={1} sx={{ minWidth: 220, p: 1 }}>
      <Stack direction="row" spacing={1.5} alignItems="center">
        <Tooltip title={t('Brightness')}>
          <Brightness6Icon fontSize="small" color="action" aria-hidden />
        </Tooltip>
        <Slider
          size="small"
          min={-100}
          max={100}
          value={brightness}
          onChange={(_e, v) => onBrightnessChange(v as number)}
          aria-label={t('Brightness')}
          aria-valuetext={valueText('Brightness', brightness)}
          valueLabelDisplay="auto"
        />
      </Stack>
      <Stack direction="row" spacing={1.5} alignItems="center">
        <Tooltip title={t('Contrast')}>
          <ContrastIcon fontSize="small" color="action" aria-hidden />
        </Tooltip>
        <Slider
          size="small"
          min={-100}
          max={100}
          value={contrast}
          onChange={(_e, v) => onContrastChange(v as number)}
          aria-label={t('Contrast')}
          aria-valuetext={valueText('Contrast', contrast)}
          valueLabelDisplay="auto"
        />
      </Stack>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Typography variant="caption" color="text.secondary">
          {dirty ? 'Rendering adjusted' : 'Neutral'}
        </Typography>
        <Tooltip title="Reset brightness & contrast (⇧⌘R)">
          <span>
            <IconButton
              size="small"
              onClick={onReset}
              disabled={!dirty}
              aria-label={t('Reset brightness and contrast')}
            >
              <RestartAltIcon fontSize="small" />
            </IconButton>
          </span>
        </Tooltip>
      </Box>
    </Stack>
  );
}
