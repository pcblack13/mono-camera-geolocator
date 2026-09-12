/**
 * `map/ViewModeSwitch.tsx` (pure) — 2D ↔ 3D, and the exaggeration control.
 *
 * ★ **2D IS THE DEFAULT AND THE SWITCH SAYS WHAT YOU GIVE UP.** The 3D pane is a viewing
 *   aid: it renders terrain and imagery and nothing else. The GCP markers, the offline
 *   cache overlay, the footprint and the heatmap seam all live in the 2D Leaflet pane.
 *   A switch that hid that would leave a surveyor wondering where their points went.
 *
 * ★ **3D IS DISABLED WITHOUT A DEM, WITH THE REASON.** With no elevation source every
 *   terrain tile 404s and the view renders dead flat — which looks like working software
 *   showing you flat ground, and is the most misleading possible outcome. SCOPE.md §4
 *   rule 4: disable the control with an honest tooltip *before* it is clicked.
 *
 * ★ **THE EXAGGERATION SLIDER DEFAULTS TO TRUE SCALE.** Every globe demo ships 1.5×
 *   because it looks better. This is a survey tool: a surveyor judging whether a slope
 *   matches their photograph must be able to trust the angle unless they deliberately
 *   changed it. The control is offered; the default does not distort, and any value
 *   other than 1.0 is labelled as exaggerated.
 *
 * **Pure.** State in, callbacks out.
 */

import type { JSX } from 'react';
import Box from '@mui/material/Box';
import Slider from '@mui/material/Slider';
import ToggleButton from '@mui/material/ToggleButton';
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import { t } from '../../i18n';

export type MapViewMode = '2d' | '3d';

export interface ViewModeSwitchProps {
  mode: MapViewMode;
  onModeChange: (mode: MapViewMode) => void;
  /** Kept for API stability; 3D now always has a surface (project DEM or the global
   *  AWS/Mapzen fallback), so callers pass true. */
  terrainAvailable: boolean;
  exaggeration: number;
  onExaggerationChange: (value: number) => void;
}

const TWO_D_TIP =
  'Flat, north-up map. Shows GCP markers, the offline cache and the image footprint — ' +
  'this is the pane GCP pairing runs in.';

const THREE_D_TIP =
  'Tilted terrain from this project’s DEM, with the same imagery draped over it. ' +
  'Viewing aid only: GCP markers and overlays stay in the 2D pane, and the rendered ' +
  'surface is approximate — a point’s elevation always comes from the DEM sampler.';

const NO_DEM_TIP =
  '3D needs an elevation source. This project has no DEM attached, so terrain would ' +
  'render dead flat — which would look like real ground and be wrong. Attach a DEM in ' +
  'the workspace setup to enable it.';

export function ViewModeSwitch({
  mode,
  onModeChange,
  terrainAvailable,
  exaggeration,
  onExaggerationChange,
}: ViewModeSwitchProps): JSX.Element {
  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        gap: 1,
        p: 0.5,
        borderRadius: 1,
        bgcolor: 'background.paper',
        boxShadow: 2,
      }}
    >
      <ToggleButtonGroup
        size="small"
        exclusive
        value={mode}
        onChange={(_e, next: MapViewMode | null) => {
          // A view mode is not deselectable; swallow the group's null on re-click.
          if (next !== null) onModeChange(next);
        }}
        aria-label={t('Map view mode')}
      >
        <Tooltip title={TWO_D_TIP}>
          <ToggleButton value="2d" aria-label={t('2D map')}>
            2D
          </ToggleButton>
        </Tooltip>
        {/* span so the tooltip still fires while the button is disabled */}
        <Tooltip title={terrainAvailable ? THREE_D_TIP : NO_DEM_TIP}>
          <span>
            <ToggleButton value="3d" aria-label={t('3D terrain')} disabled={!terrainAvailable}>
              3D
            </ToggleButton>
          </span>
        </Tooltip>
      </ToggleButtonGroup>

      {mode === '3d' && terrainAvailable && (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 160, px: 1 }}>
          <Tooltip
            title={
              exaggeration === 1
                ? 'Vertical scale is TRUE — slopes are real.'
                : `Vertical scale is EXAGGERATED ${exaggeration.toFixed(1)}×. Slopes look ` +
                  'steeper than they are; return to 1.0 to judge terrain honestly.'
            }
          >
            <Typography
              variant="caption"
              sx={{
                whiteSpace: 'nowrap',
                fontWeight: exaggeration === 1 ? 400 : 700,
                color: exaggeration === 1 ? 'text.secondary' : 'warning.main',
              }}
            >
              {exaggeration.toFixed(1)}×
            </Typography>
          </Tooltip>
          <Slider
            size="small"
            min={1}
            max={3}
            step={0.1}
            value={exaggeration}
            onChange={(_e, v) => onExaggerationChange(Array.isArray(v) ? v[0] : v)}
            aria-label={t('Vertical exaggeration')}
            marks={[{ value: 1, label: '' }]}
          />
        </Box>
      )}
    </Box>
  );
}
