/**
 * `image/MarkerColorsControl.tsx` — how the marks are DRAWN, chosen by the surveyor.
 *
 * ★ ORGANISED BY SURFACE, NOT BY DATA MODEL (2026-08-20). The first version offered
 *   "GCPs" and "landmarks", which are two states of one database row — a distinction
 *   the code cares about and nobody else does. It read as one of them being the marks
 *   on the photo and the other the marks on the map, which is exactly what a surveyor
 *   means and exactly what it did NOT do. So the sections are now the two surfaces
 *   themselves, each shown with a live preview of the mark it governs.
 *
 * ★ WHY A CONTROL AND NOT A THEME. Field conditions decide legibility: magenta boxes
 *   disappear over flowering ground, green points vanish in a crop canopy, and a
 *   colour-blind surveyor may need a pair the default palette does not offer.
 *
 * ★ THE DEFAULT MEANS SOMETHING. A control point's colour normally IS its confidence
 *   band — green high through red unreliable — so a flat colour trades an accuracy
 *   reading for legibility. Each surface therefore offers "By accuracy" or "One
 *   colour" as two visible choices, and says what the second one costs. The band's
 *   glyph and dash pattern keep encoding it either way, which is the only reason a
 *   flat colour is offerable at all.
 */

import { useRef, useState, type JSX } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Divider from '@mui/material/Divider';
import IconButton from '@mui/material/IconButton';
import Popover from '@mui/material/Popover';
import Stack from '@mui/material/Stack';
import ToggleButton from '@mui/material/ToggleButton';
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import ImageOutlinedIcon from '@mui/icons-material/ImageOutlined';
import MapOutlinedIcon from '@mui/icons-material/MapOutlined';
import PaletteOutlinedIcon from '@mui/icons-material/PaletteOutlined';
import CropFreeIcon from '@mui/icons-material/CropFree';

import { useWorkspaceStore } from '../../store';
import { CONFIDENCE_COLORS } from '../../theme/confidence';
import { useColorMode } from '../../theme';
import { t } from '../../i18n';

/** A colour well — the native picker, which works offline and needs no library. */
function Swatch({
  value,
  onChange,
  label,
}: {
  value: string;
  onChange: (hex: string) => void;
  label: string;
}): JSX.Element {
  return (
    <Box
      component="input"
      type="color"
      value={value}
      onChange={(e: React.ChangeEvent<HTMLInputElement>) => onChange(e.target.value)}
      aria-label={label}
      sx={{
        'width': 40,
        'height': 28,
        'p': 0,
        'border': 1,
        'borderColor': 'divider',
        'borderRadius': 1,
        'bgcolor': 'transparent',
        'cursor': 'pointer',
        '&::-webkit-color-swatch-wrapper': { p: '2px' },
        '&::-webkit-color-swatch': { border: 'none', borderRadius: '2px' },
      }}
    />
  );
}

/**
 * One surface's setting: by accuracy, or one colour.
 *
 * The preview dot is not decoration — it is the answer to "what will this look
 * like", which a hex field alone never gives.
 */
function SurfaceSection({
  icon,
  title,
  subtitle,
  value,
  fallback,
  onChange,
}: {
  icon: JSX.Element;
  title: string;
  subtitle: string;
  value: string | null;
  /** What the swatch opens on when switching from "by accuracy" to a flat colour. */
  fallback: string;
  onChange: (c: string | null) => void;
}): JSX.Element {
  return (
    <Box>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 0.25 }}>
        {icon}
        <Typography variant="body2" sx={{ fontWeight: 600 }}>
          {title}
        </Typography>
      </Stack>
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
        {subtitle}
      </Typography>

      <Stack direction="row" alignItems="center" spacing={1}>
        <ToggleButtonGroup
          size="small"
          exclusive
          value={value === null ? 'accuracy' : 'flat'}
          onChange={(_e, next: string | null) => {
            if (next === null) return; // clicking the active button must not clear it
            onChange(next === 'accuracy' ? null : fallback);
          }}
          sx={{ flex: 1 }}
        >
          <ToggleButton value="accuracy" sx={{ flex: 1, textTransform: 'none', py: 0.4 }}>
            {t('By accuracy')}
          </ToggleButton>
          <ToggleButton value="flat" sx={{ flex: 1, textTransform: 'none', py: 0.4 }}>
            {t('One colour')}
          </ToggleButton>
        </ToggleButtonGroup>
        {value !== null && <Swatch value={value} onChange={onChange} label={`${title} colour`} />}
      </Stack>

      {value === null && (
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.75 }}>
          {t('Green → red shows how good each point is at a glance.')}
        </Typography>
      )}
    </Box>
  );
}

export function MarkerColorsControl(): JSX.Element {
  const anchorRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const { mode } = useColorMode();

  const suggestionColor = useWorkspaceStore((s) => s.suggestionColor);
  const photoMarkColor = useWorkspaceStore((s) => s.photoMarkColor);
  const mapMarkColor = useWorkspaceStore((s) => s.mapMarkColor);
  const pointColors = useWorkspaceStore((s) => s.pointColors);
  const setSuggestionColor = useWorkspaceStore((s) => s.setSuggestionColor);
  const setPhotoMarkColor = useWorkspaceStore((s) => s.setPhotoMarkColor);
  const setMapMarkColor = useWorkspaceStore((s) => s.setMapMarkColor);
  const resetMarkerColors = useWorkspaceStore((s) => s.resetMarkerColors);

  // Where the picker opens from when leaving "by accuracy": the band a good point
  // lands in, rather than an unrelated colour.
  const fallback = CONFIDENCE_COLORS.high[mode];
  const overrides = Object.keys(pointColors).length;

  return (
    <>
      <Tooltip title={t('Marker colours')}>
        <IconButton
          ref={anchorRef}
          size="small"
          onClick={() => setOpen((v) => !v)}
          aria-label={t('Marker colours')}
        >
          <PaletteOutlinedIcon fontSize="small" />
        </IconButton>
      </Tooltip>

      <Popover
        open={open}
        anchorEl={anchorRef.current}
        onClose={() => setOpen(false)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
      >
        <Box sx={{ p: 2, width: 340 }}>
          <Typography variant="subtitle2">{t('Marker colours')}</Typography>
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 2 }}>
            {t(
              'Kept with your workspace on this computer. They change how marks are drawn, never the survey itself.',
            )}
          </Typography>

          <Stack spacing={2}>
            <SurfaceSection
              icon={<ImageOutlinedIcon fontSize="small" color="action" />}
              title={t('Points on the photograph')}
              subtitle="Every landmark and control point drawn on the photo."
              value={photoMarkColor}
              fallback={photoMarkColor ?? fallback}
              onChange={setPhotoMarkColor}
            />

            <Divider />

            <SurfaceSection
              icon={<MapOutlinedIcon fontSize="small" color="action" />}
              title={t('Points on the map')}
              subtitle="Every control point pinned on the satellite map."
              value={mapMarkColor}
              fallback={mapMarkColor ?? fallback}
              onChange={setMapMarkColor}
            />

            <Divider />

            <Box>
              <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 0.25 }}>
                <CropFreeIcon fontSize="small" color="action" />
                <Typography variant="body2" sx={{ fontWeight: 600, flex: 1 }}>
                  {t('Suggestion boxes')}
                </Typography>
                <Swatch
                  value={suggestionColor}
                  onChange={setSuggestionColor}
                  label={t('Suggestion box colour')}
                />
              </Stack>
              <Typography variant="caption" color="text.secondary" display="block">
                {t('Where the next point would help most.')}
              </Typography>
            </Box>
          </Stack>

          <Divider sx={{ my: 2 }} />

          {/* ★ Per-point colours are set on the POINT (select it, then the inspector),
              not here — a list of every point in a popover is a worse way to find one
              than the photograph itself. This line exists so the feature is
              discoverable, and so overrides cannot pile up invisibly. */}
          <Typography variant="caption" color="text.secondary" display="block">
            {t('To colour')} <b>one</b> point on its own, select it and use the colour well in the
            inspector. {overrides > 0 && <b>{overrides} point(s) have their own colour.</b>}
          </Typography>

          <Stack direction="row" justifyContent="flex-end" sx={{ mt: 1.5 }}>
            <Button size="small" onClick={resetMarkerColors}>
              {t('Reset all to defaults')}
            </Button>
          </Stack>
        </Box>
      </Popover>
    </>
  );
}
