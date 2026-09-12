/**
 * `accuracy/HeatmapHistoryMenu.tsx` — every heat map this photograph has produced.
 *
 * ★ WHY A HISTORY IS THE RIGHT SHAPE. The loop re-measures after every control point,
 *   so a single "current error" answers the least interesting question. What a surveyor
 *   needs to know is whether the last point helped, and where — which is a comparison
 *   between two runs, not a reading of one.
 *
 * ★ THE COMPARISON SHOWS NUMBERS AND PICTURES, because the two answer different
 *   questions. The numbers say how much the median moved and whether the worst places
 *   moved with it; the two heat layers side by side say WHERE. A median that improves
 *   while one corner gets worse is common, and only the picture reveals it.
 *
 * ★ BOTH LAYERS ARE DRAWN ON THE SAME COLOUR SCALE — the newer run's — or the
 *   comparison would be between two palettes rather than two measurements.
 */

import { useMemo, useRef, useState, type JSX } from 'react';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import Dialog from '@mui/material/Dialog';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import Divider from '@mui/material/Divider';
import IconButton from '@mui/material/IconButton';
import ListItemText from '@mui/material/ListItemText';
import Menu from '@mui/material/Menu';
import MenuItem from '@mui/material/MenuItem';
import Stack from '@mui/material/Stack';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import TextField from '@mui/material/TextField';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import CloseOutlinedIcon from '@mui/icons-material/CloseOutlined';
import HistoryOutlinedIcon from '@mui/icons-material/HistoryOutlined';

import {
  historyLayerUrl,
  layerUrl,
  type AccuracyGrid,
  type HeatmapVersion,
} from '../../api/accuracy';
import { useAccuracyHistory, useAccuracyState } from '../../api/hooks/useAccuracy';
import type { Uuid } from '../../types/common';
import { HEAT_STOPS } from './heat';
import { t } from '../../i18n';

export interface HeatmapHistoryMenuProps {
  imageId: Uuid;
}

function when(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

/** The number a version is judged by: the corrected winner if there is one, else raw. */
function headline(v: HeatmapVersion): number | null {
  return v.corrected?.all_m ?? v.median_error_m;
}

function metres(value: number | null | undefined): string {
  return value == null ? '—' : `${value.toFixed(2)} m`;
}

/** Signed change, phrased so "better" is never implied by the sign alone. */
function delta(older: number | null | undefined, newer: number | null | undefined): string {
  if (older == null || newer == null) return '—';
  const d = newer - older;
  const pct = older === 0 ? 0 : (100 * d) / older;
  const word = d < 0 ? 'better' : d > 0 ? 'worse' : 'unchanged';
  return `${d >= 0 ? '+' : ''}${d.toFixed(2)} m (${pct >= 0 ? '+' : ''}${pct.toFixed(0)}% — ${word})`;
}

/** The end of the colour ramp, in metres — what the darkest red means. */
function scaleMax(v: HeatmapVersion | null): string | null {
  const vmax = v?.grid?.vmax_m;
  return typeof vmax === 'number' && Number.isFinite(vmax) ? `${vmax.toFixed(0)} m` : null;
}

/** Which corrected layer a version can show, best available first. */
function heatLayerOf(v: HeatmapVersion): string {
  if (v.layers.includes('heat_stagef')) return 'heat_stagef';
  if (v.layers.includes('heat_pose')) return 'heat_pose';
  return 'heat_raw';
}

/**
 * One version drawn the way the satellite pane draws it: the heat over the imagery it
 * was measured against.
 *
 * ★ THE BASE COMES FROM THE SAME VERSION, not from the live folder. The ortho grid
 *   changes with the range and the GSD, so pairing an older heat layer with today's
 *   base would slide the error field off the ground it describes — the one mistake this
 *   panel exists to prevent.
 */
function HeatOnMap({
  imageId,
  version,
  liveGrid,
}: {
  imageId: Uuid;
  version: HeatmapVersion;
  /** The CURRENT measurement's grid, for the fallback below. */
  liveGrid?: Partial<AccuracyGrid>;
}): JSX.Element {
  // ★ THE BASE, IN ORDER OF TRUTHFULNESS.
  //   1. The version's own archived satellite — always correct.
  //   2. Failing that, the LIVE satellite, but ONLY when the ortho grid is the same
  //      rectangle. Versions measured before the base was archived can then still be
  //      drawn as a map instead of a shape on black.
  //   3. Otherwise nothing. A heat field over the wrong rectangle would place the
  //      error somewhere it was never measured, which is worse than no backdrop.
  const sameGrid =
    liveGrid?.width != null &&
    version.grid?.width === liveGrid.width &&
    version.grid?.height === liveGrid.height;
  const base = version.layers.includes('satellite')
    ? historyLayerUrl(imageId, version.version, 'satellite')
    : sameGrid
      ? layerUrl(imageId, 'satellite')
      : null;
  const hasBase = base !== null;
  return (
    <Box
      sx={{
        position: 'relative',
        borderRadius: 1,
        border: 1,
        borderColor: 'divider',
        overflow: 'hidden',
        bgcolor: 'common.black',
        lineHeight: 0,
      }}
    >
      {base !== null && (
        <Box component="img" src={base} alt="" sx={{ width: '100%', display: 'block' }} />
      )}
      <Box
        component="img"
        src={historyLayerUrl(imageId, version.version, heatLayerOf(version))}
        alt={`Error heat map measured ${when(version.measured_at)}`}
        sx={
          hasBase
            ? { position: 'absolute', inset: 0, width: '100%', height: '100%' }
            : { width: '100%', display: 'block' }
        }
      />
    </Box>
  );
}

export function HeatmapHistoryMenu({ imageId }: HeatmapHistoryMenuProps): JSX.Element | null {
  const anchorRef = useRef<HTMLButtonElement>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [compare, setCompare] = useState<[string, string] | null>(null);

  const { data: versions = [] } = useAccuracyHistory(imageId);
  const liveGrid = useAccuracyState(imageId).data?.measurement?.grid;

  const [a, b] = useMemo<[HeatmapVersion | null, HeatmapVersion | null]>(() => {
    if (compare == null) return [null, null];
    const find = (v: string): HeatmapVersion | null =>
      versions.find((x) => x.version === v) ?? null;
    return [find(compare[0]), find(compare[1])];
  }, [compare, versions]);

  if (versions.length === 0) return null;

  const newest = versions[0];

  /** Compare a version with the one measured before it — the question actually asked. */
  const compareWithPrevious = (version: string): void => {
    const index = versions.findIndex((v) => v.version === version);
    const previous = versions[index + 1];
    setCompare(previous == null ? [version, version] : [previous.version, version]);
    setMenuOpen(false);
  };

  return (
    <>
      <Tooltip title={`Heat map history — ${versions.length} measurement(s)`}>
        <IconButton
          ref={anchorRef}
          size="small"
          onClick={() => setMenuOpen(true)}
          aria-label={t('Heat map history')}
          sx={{
            'bgcolor': 'background.paper',
            'boxShadow': 2,
            '&:hover': { bgcolor: 'action.hover' },
          }}
        >
          <HistoryOutlinedIcon fontSize="small" />
        </IconButton>
      </Tooltip>

      <Menu
        open={menuOpen}
        anchorEl={anchorRef.current}
        onClose={() => setMenuOpen(false)}
        slotProps={{ paper: { sx: { maxHeight: 420, width: 420 } } }}
      >
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ px: 2, py: 0.5, display: 'block' }}
        >
          {t('Each measurement is kept. Pick one to compare it with the run before it.')}
        </Typography>
        <Divider />
        {versions.map((v, i) => (
          <MenuItem key={v.version} onClick={() => compareWithPrevious(v.version)}>
            <ListItemText
              primary={
                <Stack direction="row" spacing={1} alignItems="center">
                  <Typography variant="body2" sx={{ flex: 1 }} noWrap>
                    {when(v.measured_at)}
                  </Typography>
                  <Typography variant="mono">{metres(headline(v))}</Typography>
                  {i === 0 && <Chip size="small" color="primary" label={t('current')} />}
                </Stack>
              }
              secondary={
                <Typography variant="caption" color="text.secondary">
                  {v.pose?.gcps_used != null && `${String(v.pose.gcps_used)} points · `}
                  {(100 * v.match_rate).toFixed(0)}% of {v.tiles_total} tiles locked
                  {v.corrected?.label != null && ` · ${v.corrected.label}`}
                </Typography>
              }
            />
          </MenuItem>
        ))}
      </Menu>

      <Dialog open={compare !== null} onClose={() => setCompare(null)} maxWidth="lg" fullWidth>
        <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Box sx={{ flex: 1 }}>{t('Comparing two measurements')}</Box>
          <IconButton size="small" onClick={() => setCompare(null)} aria-label={t('Close')}>
            <CloseOutlinedIcon fontSize="small" />
          </IconButton>
        </DialogTitle>
        <DialogContent dividers>
          {a !== null && b !== null && (
            <Stack spacing={2}>
              {a.version === b.version && (
                <Alert severity="info" variant="outlined">
                  {t(
                    'This is the first measurement, so there is nothing before it to compare against — the numbers below describe it on its own.',
                  )}
                </Alert>
              )}

              {/* ── the numbers ─────────────────────────────────────────── */}
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell />
                    <TableCell align="right">{when(a.measured_at)}</TableCell>
                    <TableCell align="right">{when(b.measured_at)}</TableCell>
                    <TableCell align="right">{t('Change')}</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  <TableRow>
                    <TableCell>{t('Control points')}</TableCell>
                    <TableCell align="right">{String(a.pose?.gcps_used ?? '—')}</TableCell>
                    <TableCell align="right">{String(b.pose?.gcps_used ?? '—')}</TableCell>
                    <TableCell align="right">—</TableCell>
                  </TableRow>
                  <TableRow selected>
                    <TableCell>
                      {t('Corrected median')}
                      <Typography variant="caption" color="text.secondary" display="block">
                        {t('the winning stage')}
                      </Typography>
                    </TableCell>
                    <TableCell align="right">
                      <Typography variant="mono">{metres(a.corrected?.all_m)}</Typography>
                    </TableCell>
                    <TableCell align="right">
                      <Typography variant="mono">{metres(b.corrected?.all_m)}</Typography>
                    </TableCell>
                    <TableCell align="right">
                      <Typography variant="mono">
                        {delta(a.corrected?.all_m, b.corrected?.all_m)}
                      </Typography>
                    </TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell>{t('Raw measured median')}</TableCell>
                    <TableCell align="right">
                      <Typography variant="mono">{metres(a.median_error_m)}</Typography>
                    </TableCell>
                    <TableCell align="right">
                      <Typography variant="mono">{metres(b.median_error_m)}</Typography>
                    </TableCell>
                    <TableCell align="right">
                      <Typography variant="mono">
                        {delta(a.median_error_m, b.median_error_m)}
                      </Typography>
                    </TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell>
                      p95
                      <Typography variant="caption" color="text.secondary" display="block">
                        {t('the worst areas — read this one')}
                      </Typography>
                    </TableCell>
                    <TableCell align="right">
                      <Typography variant="mono">{metres(a.corrected?.p95_m)}</Typography>
                    </TableCell>
                    <TableCell align="right">
                      <Typography variant="mono">{metres(b.corrected?.p95_m)}</Typography>
                    </TableCell>
                    <TableCell align="right">
                      <Typography variant="mono">
                        {delta(a.corrected?.p95_m, b.corrected?.p95_m)}
                      </Typography>
                    </TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell>{t('Tiles locked')}</TableCell>
                    <TableCell align="right">
                      {(100 * a.match_rate).toFixed(0)}% of {a.tiles_total}
                    </TableCell>
                    <TableCell align="right">
                      {(100 * b.match_rate).toFixed(0)}% of {b.tiles_total}
                    </TableCell>
                    <TableCell align="right">—</TableCell>
                  </TableRow>
                </TableBody>
              </Table>

              {/* ★ A median can improve while the worst corner gets worse. When the two
                  disagree, say so — the table alone lets it pass unnoticed. */}
              {a.corrected?.all_m != null &&
                b.corrected?.all_m != null &&
                a.corrected?.p95_m != null &&
                b.corrected?.p95_m != null &&
                b.corrected.all_m < a.corrected.all_m &&
                b.corrected.p95_m > a.corrected.p95_m && (
                  <Alert severity="warning" variant="outlined">
                    {t(
                      'The typical error improved but the worst areas got worse. Most of the scene is better and a minority is worse — check the right-hand map before treating this as a straight gain.',
                    )}
                  </Alert>
                )}

              {/* ── the pictures ────────────────────────────────────────── */}
              <Box
                sx={{
                  display: 'grid',
                  gap: 2,
                  gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' },
                }}
              >
                {(
                  [
                    ['Before', a, (v: string) => setCompare([v, compare![1]])],
                    ['After', b, (v: string) => setCompare([compare![0], v])],
                  ] as const
                ).map(([side, v, pick]) => (
                  <Box key={side}>
                    {/* ★ EITHER SIDE IS CHOSEN INDEPENDENTLY. Opening the panel offers
                        "this run vs the one before" because that is the usual question,
                        but a surveyor comparing against where they STARTED needs to
                        pick the other end themselves. */}
                    <TextField
                      select
                      size="small"
                      fullWidth
                      label={side}
                      value={v.version}
                      onChange={(e) => pick(e.target.value)}
                      sx={{ mb: 1 }}
                    >
                      {versions.map((option) => (
                        <MenuItem key={option.version} value={option.version}>
                          {when(option.measured_at)} · {metres(headline(option))}
                          {option.pose?.gcps_used != null &&
                            ` · ${String(option.pose.gcps_used)} pts`}
                        </MenuItem>
                      ))}
                    </TextField>
                    <HeatOnMap imageId={imageId} version={v} liveGrid={liveGrid} />
                  </Box>
                ))}
              </Box>

              <Stack direction="row" spacing={1} alignItems="center">
                <Typography variant="caption" color="text.secondary">
                  0 m
                </Typography>
                <Box
                  sx={{
                    flex: 1,
                    height: 8,
                    borderRadius: 4,
                    background: `linear-gradient(90deg, ${HEAT_STOPS.join(', ')})`,
                  }}
                />
                {/* ★ THE END OF THE SCALE IS A NUMBER, not a word. "worse" says which
                    direction the colour runs, which the ramp already shows; what a
                    surveyor needs is what the darkest red actually MEANS in metres. */}
                <Typography variant="caption" color="text.secondary">
                  {scaleMax(b) ?? scaleMax(a) ?? '—'}
                </Typography>
              </Stack>

              {newest.gate?.accepted === false && newest.gate?.reason != null && (
                <Alert severity="warning" variant="outlined">
                  {newest.gate.reason}
                </Alert>
              )}

              <Typography variant="caption" color="text.secondary">
                {t(
                  'Every figure is measured against the satellite basemap, which carries its own georeferencing error of a few metres. Breaking that floor needs GNSS-surveyed checkpoints.',
                )}
              </Typography>
            </Stack>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
