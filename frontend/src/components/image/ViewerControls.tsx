/**
 * `image/ViewerControls.tsx` (pure) — the viewer's zoom / fit / fullscreen /
 * brightness-contrast rail. 50-frontend.md §2.10.
 *
 * Pure: every action is a callback, so the container (`ImagePanel`) owns the policy
 * and this can be storybooked with no store.
 *
 * ★ FULLSCREEN is a first-class, mandated control (SCOPE.md §3). Dark chrome in
 *   fullscreen is the surveyor's correct viewing condition (§9.3).
 */

import { useState } from 'react';
import Box from '@mui/material/Box';
import Divider from '@mui/material/Divider';
import IconButton from '@mui/material/IconButton';
import Popover from '@mui/material/Popover';
import Stack from '@mui/material/Stack';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import ZoomInIcon from '@mui/icons-material/ZoomIn';
import ZoomOutIcon from '@mui/icons-material/ZoomOut';
import FitScreenIcon from '@mui/icons-material/FitScreen';
import CenterFocusStrongIcon from '@mui/icons-material/CenterFocusStrong';
import FullscreenIcon from '@mui/icons-material/Fullscreen';
import FullscreenExitIcon from '@mui/icons-material/FullscreenExit';
import TuneIcon from '@mui/icons-material/Tune';

import PhotoSizeSelectLargeIcon from '@mui/icons-material/PhotoSizeSelectLarge';
import PlaceOutlinedIcon from '@mui/icons-material/PlaceOutlined';
import Slider from '@mui/material/Slider';
import Switch from '@mui/material/Switch';
import FormControlLabel from '@mui/material/FormControlLabel';

import GridViewOutlinedIcon from '@mui/icons-material/GridViewOutlined';

import { HEAT_STOPS } from '../../theme/dataColors';
import { BrightnessContrastControl } from './BrightnessContrastControl';
import { MarkerColorsControl } from './MarkerColorsControl';
import { t } from '../../i18n';

export interface ViewerControlsProps {
  scale: number;
  minScale: number;
  maxScale: number;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onFit: () => void;
  onActualSize: () => void;
  onToggleFullscreen: () => void;
  isFullscreen: boolean;
  brightness: number;
  contrast: number;
  onBrightnessChange: (v: number) => void;
  onContrastChange: (v: number) => void;
  onResetAdjustments: () => void;
  /** ★ Opens the change-resolution dialog — lives here beside brightness/contrast
   *  because both are "how this photo is displayed/stored" concerns, not header
   *  actions. Omitted (undefined) hides the button. */
  onRescale?: () => void;
  /**
   * ★ Suggested regions for the next control point (from the accuracy check), drawn on
   *   the photograph. The toggle appears only when there ARE suggestions — a control
   *   for nothing is noise. They default to shown, because a surveyor who just asked
   *   for them wants to see them.
   */
  suggestionCount?: number;
  showSuggestions?: boolean;
  onToggleSuggestions?: () => void;
  /** How many regions the next suggestion run should return. */
  suggestionLimit?: number;
  onSuggestionLimitChange?: (n: number) => void;
  /**
   * ★ The nine range zones from the last measurement, drawn on the photograph. The
   *   control appears only when a measurement HAS zones — a switch for nothing is
   *   noise. Opacity lives here rather than in a settings page because it is
   *   adjusted while looking at the picture it changes.
   */
  hasZones?: boolean;
  showZones?: boolean;
  onToggleZones?: () => void;
  /** Fill opacity, 0–100. */
  zoneOpacity?: number;
  onZoneOpacityChange?: (n: number) => void;
  /** The zone scale's two ends, for the legend inside the panel. */
  zoneRange?: [number, number] | null;
}

export function ViewerControls({
  scale,
  minScale,
  maxScale,
  onRescale,
  onZoomIn,
  onZoomOut,
  onFit,
  onActualSize,
  onToggleFullscreen,
  isFullscreen,
  brightness,
  contrast,
  onBrightnessChange,
  onContrastChange,
  onResetAdjustments,
  suggestionCount,
  showSuggestions,
  onToggleSuggestions,
  suggestionLimit,
  onSuggestionLimitChange,
  hasZones,
  showZones,
  onToggleZones,
  zoneOpacity,
  onZoneOpacityChange,
  zoneRange,
}: ViewerControlsProps): JSX.Element {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const [suggestAnchor, setSuggestAnchor] = useState<HTMLElement | null>(null);
  const [zoneAnchor, setZoneAnchor] = useState<HTMLElement | null>(null);
  const adjusted = brightness !== 0 || contrast !== 0;
  const pct = Math.round(scale * 100);

  return (
    <Stack
      direction="row"
      spacing={0.25}
      alignItems="center"
      sx={{ px: 1, py: 0.5, bgcolor: 'background.paper', borderTop: 1, borderColor: 'divider' }}
    >
      <Tooltip title={t('Zoom out (−)')}>
        <span>
          <IconButton
            size="small"
            onClick={onZoomOut}
            disabled={scale <= minScale}
            aria-label={t('Zoom out')}
          >
            <ZoomOutIcon fontSize="small" />
          </IconButton>
        </span>
      </Tooltip>
      <Typography
        variant="mono"
        sx={{
          minWidth: 48,
          textAlign: 'center',
          fontSize: 12,
          color: 'text.secondary',
          userSelect: 'none',
        }}
        aria-live="off"
      >
        {pct}%
      </Typography>
      <Tooltip title={t('Zoom in (+)')}>
        <span>
          <IconButton
            size="small"
            onClick={onZoomIn}
            disabled={scale >= maxScale}
            aria-label={t('Zoom in')}
          >
            <ZoomInIcon fontSize="small" />
          </IconButton>
        </span>
      </Tooltip>

      <Divider orientation="vertical" flexItem sx={{ mx: 0.5 }} />

      <Tooltip title={t('Fit to view (F)')}>
        <IconButton size="small" onClick={onFit} aria-label={t('Fit to view')}>
          <FitScreenIcon fontSize="small" />
        </IconButton>
      </Tooltip>
      <Tooltip title="Actual size — 1 image pixel = 1 screen pixel (1)">
        <IconButton size="small" onClick={onActualSize} aria-label={t('Actual size')}>
          <CenterFocusStrongIcon fontSize="small" />
        </IconButton>
      </Tooltip>

      <Divider orientation="vertical" flexItem sx={{ mx: 0.5 }} />

      <Tooltip title={t('Brightness & contrast')}>
        <IconButton
          size="small"
          onClick={(e) => setAnchor(e.currentTarget)}
          aria-label={t('Brightness and contrast')}
          color={adjusted ? 'primary' : 'default'}
        >
          <TuneIcon fontSize="small" />
        </IconButton>
      </Tooltip>
      {/* ★ ONE BUTTON, AND THE CHOICES LIVE INSIDE IT. Showing the boxes and deciding
          how many to ask for are the same thought — "what am I being told to do next" —
          so the pin opens a small panel holding both, rather than a toggle with a
          separate caret beside it. The icon still reports the current state at a
          glance: lit when the boxes are on. */}
      {onToggleSuggestions && (
        <Tooltip title="Suggested regions for the next control point">
          <IconButton
            size="small"
            onClick={(e) => setSuggestAnchor(e.currentTarget)}
            aria-label={t('Suggested regions')}
            color={showSuggestions ? 'primary' : 'default'}
          >
            <PlaceOutlinedIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      )}
      <Popover
        open={suggestAnchor !== null}
        anchorEl={suggestAnchor}
        onClose={() => setSuggestAnchor(null)}
        anchorOrigin={{ vertical: 'top', horizontal: 'center' }}
        transformOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Box sx={{ p: 2, width: 280 }}>
          <Typography variant="subtitle2">{t('Suggested regions')}</Typography>
          <Typography variant="caption" color="text.secondary" display="block">
            {t('Where the next control point would remove the most predicted error.')}
          </Typography>

          <FormControlLabel
            sx={{ mt: 1 }}
            control={
              <Switch
                size="small"
                checked={showSuggestions ?? false}
                onChange={() => onToggleSuggestions?.()}
              />
            }
            label={
              <Typography variant="caption">
                Show them on the photograph
                {(suggestionCount ?? 0) > 0 && ` — ${suggestionCount} drawn`}
              </Typography>
            }
          />

          {onSuggestionLimitChange && (
            <>
              <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
                {t('How many to rank:')} <b>{suggestionLimit ?? 1}</b>. One is an instruction;
                several are a menu to choose from in the field.
              </Typography>
              <Slider
                size="small"
                min={1}
                max={8}
                step={1}
                marks
                valueLabelDisplay="auto"
                value={suggestionLimit ?? 1}
                onChange={(_e, v) => onSuggestionLimitChange(v as number)}
                aria-label={t('Number of suggested regions')}
              />
              <Typography variant="caption" color="text.secondary">
                {t(
                  'Takes effect at the next measurement — the ranking is scored against the error field, so it is recomputed rather than trimmed.',
                )}
              </Typography>
            </>
          )}
        </Box>
      </Popover>
      {/* ★ THE NINE ZONES. Where the measurement's verdict lands on the photograph
          itself; lit when they are showing. */}
      {hasZones && onToggleZones && (
        <Tooltip title={t('Error zones on the photograph — where the last measurement found the geolocation weak')}>
          <IconButton
            size="small"
            onClick={(e) => setZoneAnchor(e.currentTarget)}
            aria-label={t('Error zones')}
            color={showZones ? 'primary' : 'default'}
          >
            <GridViewOutlinedIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      )}
      <Popover
        open={zoneAnchor !== null}
        anchorEl={zoneAnchor}
        onClose={() => setZoneAnchor(null)}
        anchorOrigin={{ vertical: 'top', horizontal: 'center' }}
        transformOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Box sx={{ p: 2, width: 300 }}>
          <Typography variant="subtitle2">{t('Error zones')}</Typography>
          <Typography variant="caption" color="text.secondary" display="block">
            {t(
              'Three range bands by three columns. Each zone carries the median error the last measurement found inside it, and how many tiles that number rests on. Compare zones against each other: a whole band worse than the rest points at the terrain model or the focal length; one column worse points at the pose.',
            )}
          </Typography>
          <FormControlLabel
            sx={{ mt: 1 }}
            control={
              <Switch
                size="small"
                checked={showZones ?? false}
                onChange={() => onToggleZones?.()}
              />
            }
            label={<Typography variant="caption">{t('Show them on the photograph')}</Typography>}
          />
          {onZoneOpacityChange && (
            <>
              <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
                {t('Fill opacity')} <b>{zoneOpacity ?? 45}%</b>
              </Typography>
              <Slider
                size="small"
                min={0}
                max={100}
                step={5}
                valueLabelDisplay="auto"
                value={zoneOpacity ?? 45}
                disabled={!showZones}
                onChange={(_e, v) => onZoneOpacityChange(v as number)}
                aria-label={t('Zone fill opacity')}
              />
            </>
          )}
          {zoneRange && (
            <Box sx={{ mt: 1 }}>
              <Box
                sx={{
                  height: 8,
                  borderRadius: 4,
                  background: `linear-gradient(90deg, ${HEAT_STOPS.join(', ')})`,
                }}
              />
              <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
                <Typography variant="caption">{zoneRange[0].toFixed(1)} m</Typography>
                <Typography variant="caption" color="text.secondary">
                  {t('median error vs satellite')}
                </Typography>
                <Typography variant="caption">{zoneRange[1].toFixed(1)} m</Typography>
              </Box>
            </Box>
          )}
        </Box>
      </Popover>
      {/* How the marks are drawn — beside the controls that decide WHICH marks show. */}
      <MarkerColorsControl />
      {onRescale && (
        <Tooltip title={t('Change resolution')}>
          <IconButton size="small" onClick={onRescale} aria-label={t('Change resolution')}>
            <PhotoSizeSelectLargeIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      )}
      <Popover
        open={anchor !== null}
        anchorEl={anchor}
        onClose={() => setAnchor(null)}
        anchorOrigin={{ vertical: 'top', horizontal: 'center' }}
        transformOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <BrightnessContrastControl
          brightness={brightness}
          contrast={contrast}
          onBrightnessChange={onBrightnessChange}
          onContrastChange={onContrastChange}
          onReset={onResetAdjustments}
        />
      </Popover>

      <Box sx={{ flex: 1 }} />

      <Tooltip title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}>
        <IconButton
          size="small"
          onClick={onToggleFullscreen}
          aria-label={isFullscreen ? 'Exit fullscreen' : 'Enter fullscreen'}
        >
          {isFullscreen ? (
            <FullscreenExitIcon fontSize="small" />
          ) : (
            <FullscreenIcon fontSize="small" />
          )}
        </IconButton>
      </Tooltip>
    </Stack>
  );
}
