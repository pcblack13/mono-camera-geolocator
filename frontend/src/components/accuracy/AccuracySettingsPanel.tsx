/**
 * `accuracy/AccuracySettingsPanel.tsx` — the error measurement's settings, on the
 * picking page.
 *
 * ★ WHY IT IS A BUTTON HERE AND NOT A PAGE. The measurement runs by itself from the
 *   fourth control point on, so there is nothing to *drive* — only something to
 *   configure, occasionally, when a scene is unusual. That is a settings window, and it
 *   belongs beside the map's own settings rather than behind a screen the surveyor
 *   would otherwise never open.
 *
 * ★ A POPPER, NOT A DIALOG — the same shape as the offline-cache panel next to it. No
 *   modal backdrop, because the surveyor changes a tile size in order to look at the
 *   scene while they do it.
 *
 * ★ EVERY CONTROL SAYS WHAT IT COSTS. Changing the tile size or the range changes the
 *   next measurement; freeing the focal changes the POSE, which retires the stored
 *   measurement outright. The second is a different kind of act from the first, and the
 *   panel says so rather than presenting seven equal switches.
 */

import { useEffect, useRef, useState, type JSX } from 'react';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Checkbox from '@mui/material/Checkbox';
import ClickAwayListener from '@mui/material/ClickAwayListener';
import Divider from '@mui/material/Divider';
import FormControlLabel from '@mui/material/FormControlLabel';
import IconButton from '@mui/material/IconButton';
import Paper from '@mui/material/Paper';
import Popper from '@mui/material/Popper';
import Stack from '@mui/material/Stack';
import Switch from '@mui/material/Switch';
import TextField from '@mui/material/TextField';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import StraightenOutlinedIcon from '@mui/icons-material/StraightenOutlined';

import type { MeasureRequest, SolveOptions } from '../../api/accuracy';
import {
  useAccuracyState,
  useMeasureAccuracy,
  useSetSolveOptions,
} from '../../api/hooks/useAccuracy';
import { resetAccuracyAutopilot } from '../../api/hooks/useAccuracyAutopilot';
import { useWorkspaceStore } from '../../store';
import type { Uuid } from '../../types/common';
import { t } from '../../i18n';

export interface AccuracySettingsPanelProps {
  imageId: Uuid;
}

/** What the panel edits — the measurement's knobs, not the pose's. */
interface StageDParams {
  tile: number;
  stride: number;
  max_range: number;
  gsd: number;
  sat_zoom: number;
  mi_rescue: boolean;
  fine_pass: boolean;
  // ── grazing geometry (2026-09-10) ──
  max_shift: number;
  sigma_dtm: number;
  reliability_max: number;
  ecc_rescue: boolean;
  tile_auto: boolean;
  auto_reach: boolean;
  cloud_mask: boolean;
}

/** The core's own defaults — the field tool's, unchanged. */
const DEFAULTS: StageDParams = {
  tile: 128,
  stride: 64,
  max_range: 1100,
  gsd: 1,
  sat_zoom: 17,
  mi_rescue: true,
  fine_pass: true,
  // ★ 50, not the engine's 25: this product watches masts at grazing incidence,
  //   where 25 m censors real 26–30 m errors as false locks (upstream §8).
  max_shift: 50,
  sigma_dtm: 3,
  reliability_max: 0,
  ecc_rescue: false,
  tile_auto: false,
  auto_reach: true,
  cloud_mask: false,
};

export function AccuracySettingsPanel({ imageId }: AccuracySettingsPanelProps): JSX.Element {
  const anchorRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);

  const state = useAccuracyState(imageId).data;
  const measure = useMeasureAccuracy();
  const setSolveOptions = useSetSolveOptions();

  const autoMeasure = useWorkspaceStore((st) => st.autoMeasure);
  const setAutoMeasure = useWorkspaceStore((st) => st.setAutoMeasure);

  const [params, setParams] = useState<StageDParams>({ ...DEFAULTS });
  // Seed from whatever the last measurement actually used, so the panel opens showing
  // the settings in force rather than the defaults it was born with.
  useEffect(() => {
    const used = state?.measurement?.params;
    if (used == null) return;
    setParams((p) => ({
      ...p,
      tile: Number(used.tile ?? p.tile),
      stride: Number(used.stride ?? p.stride),
      max_range: Number(used.max_range ?? p.max_range),
      gsd: Number(used.gsd ?? p.gsd),
      sat_zoom: Number(used.sat_zoom ?? p.sat_zoom),
      mi_rescue: Boolean(used.mi_rescue ?? p.mi_rescue),
      fine_pass: Boolean(used.fine_pass ?? p.fine_pass),
      max_shift: Number(used.max_shift ?? p.max_shift),
      sigma_dtm: Number(used.sigma_dtm ?? p.sigma_dtm),
      reliability_max: Number(used.reliability_max ?? p.reliability_max),
      ecc_rescue: Boolean(used.ecc_rescue ?? p.ecc_rescue),
      tile_auto: Boolean(used.tile_auto ?? p.tile_auto),
      auto_reach: Boolean(used.auto_reach ?? p.auto_reach),
      cloud_mask: Boolean(used.cloud_mask ?? p.cloud_mask),
    }));
  }, [state?.measurement?.params]);

  // ★ What `tile_auto` CHOSE last time, not what was asked for: the two differ
  //   exactly when the switch is on, and the asked-for number would misreport it.
  const lastTileUsed =
    state?.measurement?.params?.tile_used != null
      ? Number(state.measurement.params.tile_used)
      : null;
  // ★ What the coverage rule DID last time. A raised reach is a finding — it says
  //   the requested setting did not contain the scene — so it is shown beside the
  //   switch rather than left in the run's warnings.
  const lastReach = state?.measurement?.reach ?? null;
  // ★ Cloud is reported whether or not it was masked — with the switch off, the
  //   count of locked tiles on cloud is the reason to turn it on.
  const lastCloud = state?.measurement?.cloud ?? null;
  const busy = state?.active_run != null || measure.isPending;
  const strideTooWide = params.stride > params.tile;
  const freeFocal = state?.solve_options?.free_focal ?? false;

  const remeasure = (): void => {
    // ★ A manual run re-arms the loop: without this the cycle for the current point
    //   count counts as already run, and the automatic chain would not follow it.
    resetAccuracyAutopilot(imageId);
    measure.mutate({ image_id: imageId, ...params } as MeasureRequest);
    setOpen(false);
  };

  const setOption = (options: SolveOptions): void => {
    setSolveOptions.mutate({ imageId, options });
  };

  const num = (
    label: string,
    key: 'tile' | 'stride' | 'max_range' | 'gsd' | 'sat_zoom' | 'max_shift' | 'sigma_dtm' | 'reliability_max',
    step = 1,
  ): JSX.Element => (
    <TextField
      size="small"
      label={label}
      type="number"
      value={params[key]}
      onChange={(e) => setParams((p) => ({ ...p, [key]: Number(e.target.value) }))}
      inputProps={{ step }}
      error={key === 'stride' && strideTooWide}
      sx={{ width: 118 }}
    />
  );

  return (
    <>
      <Tooltip title="Error measurement settings — how the scene is matched against the imagery">
        <IconButton
          ref={anchorRef}
          size="small"
          onClick={() => setOpen((v) => !v)}
          aria-label={t('Error measurement settings')}
          color={open ? 'primary' : 'default'}
          sx={{
            'bgcolor': 'background.paper',
            'boxShadow': 2,
            '&:hover': { bgcolor: 'action.hover' },
          }}
        >
          <StraightenOutlinedIcon fontSize="small" />
        </IconButton>
      </Tooltip>

      <Popper open={open} anchorEl={anchorRef.current} placement="bottom-end" sx={{ zIndex: 1300 }}>
        <ClickAwayListener onClickAway={() => setOpen(false)}>
          <Paper variant="outlined" sx={{ p: 2, width: 380, maxHeight: '70vh', overflowY: 'auto' }}>
            <Stack spacing={1.5}>
              <Box>
                <Typography variant="subtitle2">{t('Error measurement')}</Typography>
                <Typography variant="caption" color="text.secondary">
                  {t(
                    'Your photograph is flattened onto the terrain and matched against satellite imagery in overlapping tiles. Wherever the two match, the offset between them is the error there.',
                  )}
                </Typography>
              </Box>

              <Stack direction="row" spacing={1}>
                {num(t('Tile (m)'), 'tile', 16)}
                {num(t('Stride (m)'), 'stride', 16)}
                {num(t('Max range (m)'), 'max_range', 100)}
              </Stack>
              {strideTooWide && (
                <Alert severity="warning" variant="outlined">
                  {t(
                    'The stride is wider than the tile, so the tiles would not overlap and most of the scene would go unmeasured.',
                  )}
                </Alert>
              )}

              <Stack direction="row" spacing={1}>
                {num(t('Ortho GSD (m)'), 'gsd', 0.25)}
                {num(t('Satellite zoom'), 'sat_zoom', 1)}
              </Stack>

              <FormControlLabel
                control={
                  <Switch
                    size="small"
                    checked={params.mi_rescue}
                    onChange={(e) => setParams((p) => ({ ...p, mi_rescue: e.target.checked }))}
                  />
                }
                label={
                  <Typography variant="caption">
                    {t(
                      'Mutual-information second chance — rescues tiles the basemap shows in a different season',
                    )}
                  </Typography>
                }
              />
              <FormControlLabel
                control={
                  <Switch
                    size="small"
                    checked={params.fine_pass}
                    onChange={(e) => setParams((p) => ({ ...p, fine_pass: e.target.checked }))}
                  />
                }
                label={
                  <Typography variant="caption">
                    {t(
                      'Coarse-to-fine sub-tiles — recovers local detail a full tile averages away',
                    )}
                  </Typography>
                }
              />
              <FormControlLabel
                control={
                  <Switch
                    size="small"
                    checked={params.cloud_mask}
                    onChange={(e) => setParams((p) => ({ ...p, cloud_mask: e.target.checked }))}
                  />
                }
                label={
                  <Typography variant="caption">
                    {t(
                      'Cloud mask — leaves cloud in the satellite imagery out of the match. A lock on a cloud edge is not a geolocation error, and the neighbour check cannot catch one. Off by default: bright white roofs can be taken for cloud.',
                    )}
                    {lastCloud && lastCloud.locked_tiles_on_cloud > 0 && (
                      <Box component="span" sx={{ color: 'var(--accent)' }}>
                        {' '}
                        {t('The last run found')} {lastCloud.locked_tiles_on_cloud}{' '}
                        {t(lastCloud.locked_tiles_on_cloud === 1 ? 'locked tile on cloud' : 'locked tiles on cloud')}
                        {' '}({(100 * lastCloud.content_fraction).toFixed(1)}% {t('of the content')}).
                      </Box>
                    )}
                  </Typography>
                }
              />

              <Divider />

              {/* ★ GRAZING GEOMETRY (2026-09-10). A fixed mast looking kilometres out
                  is not a drone looking down: terrain-height error moves the ground
                  intersection several times further along the sight line, which
                  SHEARS a tile rather than shifting it. Every default here is the
                  engine's own, so a scene that does not need any of this measures
                  exactly what it always did. */}
              <Typography
                variant="caption"
                sx={{ color: 'var(--text-tertiary)', letterSpacing: '0.08em' }}
              >
                {t('GRAZING GEOMETRY')}
              </Typography>
              <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                {num(t('Max shift (m)'), 'max_shift', 5)}
                {num(t('DTM sigma (m)'), 'sigma_dtm', 0.5)}
                {num(t('Max sigma (m)'), 'reliability_max', 1)}
              </Stack>
              <Typography variant="caption" sx={{ color: 'var(--text-tertiary)' }}>
                {t(
                  'A match larger than the max shift is refused as a false lock — 25 m suits a drone and censors a ground camera\u2019s real errors. Max sigma drops tiles the terrain model cannot support; at 0 it keeps every tile and just reports how much each one is worth.',
                )}
              </Typography>
              <FormControlLabel
                control={
                  <Switch
                    size="small"
                    checked={params.auto_reach}
                    onChange={(e) => setParams((p) => ({ ...p, auto_reach: e.target.checked }))}
                  />
                }
                label={
                  <Typography variant="caption">
                    {t(
                      'Raise the reach to cover the scene — when the max range above leaves under 85% of the visible ground inside it, the run reaches to the far edge of what the camera sees. A drone flight that already covers its view is left exactly as set.',
                    )}
                    {lastReach?.raised && (
                      <Box component="span" sx={{ color: 'var(--accent)' }}>
                        {' '}
                        {t('The last run raised it from')} {lastReach.requested_m.toFixed(0)} m{' '}
                        {t('to')} {lastReach.used_m.toFixed(0)} m ({Math.round(100 * lastReach.coverage_requested)}% → {Math.round(100 * lastReach.coverage_used)}%).
                      </Box>
                    )}
                  </Typography>
                }
              />
              <FormControlLabel
                control={
                  <Switch
                    size="small"
                    checked={params.ecc_rescue}
                    onChange={(e) => setParams((p) => ({ ...p, ecc_rescue: e.target.checked }))}
                  />
                }
                label={
                  <Typography variant="caption">
                    {t(
                      'Affine third chance — recovers tiles that are sheared by terrain-height error rather than merely shifted. It only ever adds tiles, but it changes which ground is measured, so a run with it on is not comparable with one without.',
                    )}
                  </Typography>
                }
              />
              <FormControlLabel
                control={
                  <Switch
                    size="small"
                    checked={params.tile_auto}
                    onChange={(e) => setParams((p) => ({ ...p, tile_auto: e.target.checked }))}
                  />
                }
                label={
                  <Typography variant="caption">
                    {t(
                      'Tile size from the scene — overrides the tile and stride above. A large tile holds more texture; a small one spans less change in amplification.',
                    )}
                    {params.tile_auto && lastTileUsed !== null && (
                      <Box component="span" sx={{ color: 'var(--accent)' }}>
                        {' '}
                        {t('The last run used')} {lastTileUsed} m.
                      </Box>
                    )}
                  </Typography>
                }
              />

              <Divider />

              {/* ★ Below the line on purpose: everything above changes the MEASUREMENT,
                  this changes the POSE being measured — and therefore discards the
                  stored result rather than just producing a different one next time. */}
              <FormControlLabel
                control={
                  <Checkbox
                    size="small"
                    checked={freeFocal}
                    disabled={setSolveOptions.isPending}
                    onChange={(e) => setOption({ free_focal: e.target.checked })}
                  />
                }
                label={
                  <Typography variant="caption">
                    {t(
                      'Free the focal length in the raw solve — solve one focal scale from the control points instead of trusting the calibration. At grazing angles focal trades off against tilt, so use it when the calibration is suspect. Changing this clears the current measurement, and nothing re-measures until you press the button below.',
                    )}
                  </Typography>
                }
              />

              <Divider />

              {/* ★ THE LOOP IS OPT-IN (2026-08-20). Measuring spends a satellite mosaic
                  and minutes of compute; it used to start by itself the moment a project
                  with four points was opened. Off by default — the button below is the
                  only trigger — and on for surveys that want a reading per point. */}
              <FormControlLabel
                control={
                  <Checkbox
                    size="small"
                    checked={autoMeasure}
                    onChange={(e) => setAutoMeasure(e.target.checked)}
                  />
                }
                label={
                  <Typography variant="caption">
                    {t(
                      'Measure automatically after every control point — the error, the correction and the next suggestion, without asking. Off: nothing measures until you press Measure again.',
                    )}
                  </Typography>
                }
              />

              <Stack direction="row" spacing={1} justifyContent="flex-end">
                <Button size="small" onClick={() => setParams({ ...DEFAULTS })}>
                  {t('Defaults')}
                </Button>
                <Button
                  size="small"
                  variant="contained"
                  disabled={busy || strideTooWide}
                  onClick={remeasure}
                >
                  {t('Measure again')}
                </Button>
              </Stack>
            </Stack>
          </Paper>
        </ClickAwayListener>
      </Popper>
    </>
  );
}
