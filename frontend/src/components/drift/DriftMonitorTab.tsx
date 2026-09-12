/**
 * `drift/DriftMonitorTab.tsx` — the DRIFT MONITOR page: has this camera moved?
 *
 * ★ A PAGE OF ITS OWN (Monitoring Workspace). The drift watch strip still rides
 *   inside the Live stream and Video detection pages — there it judges the view
 *   those pages are showing. This page is the other way round: it starts from the
 *   CAMERA. Pick a source and the lookup table it was trusted with, freeze the
 *   reference, check or watch it, and see every reference and every running watch
 *   in one place — the operator's console, not a strip under a player.
 *
 * ★ WHAT A VERDICT CLAIMS, repeated because it matters: the monitor measures
 *   CHANGE from the frozen reference, never correctness. MOVED and CHANGED both
 *   mean "stop trusting the coordinates"; DEGRADED means "cannot judge" and is
 *   not an alarm. Every sentence the server writes is shown verbatim.
 *
 * ★ TWO SETS, DELIBERATELY (the same rule as the detection pages): the pickers
 *   hold what the operator is CHOOSING; `applied` holds what the watch is
 *   ABOUT. Apply commits one to the other, so browsing the source list never
 *   swaps the reference out from under a running check.
 */

import { useMemo, useState, type JSX } from 'react';
import { useQuery } from '@tanstack/react-query';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogContentText from '@mui/material/DialogContentText';
import DialogTitle from '@mui/material/DialogTitle';
import FormControl from '@mui/material/FormControl';
import InputLabel from '@mui/material/InputLabel';
import ListSubheader from '@mui/material/ListSubheader';
import MenuItem from '@mui/material/MenuItem';
import Select from '@mui/material/Select';
import Stack from '@mui/material/Stack';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import TextField from '@mui/material/TextField';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import VideoFileOutlinedIcon from '@mui/icons-material/VideoFileOutlined';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import DriveFolderUploadOutlinedIcon from '@mui/icons-material/DriveFolderUploadOutlined';
import RadarOutlinedIcon from '@mui/icons-material/RadarOutlined';
import StopCircleOutlinedIcon from '@mui/icons-material/StopCircleOutlined';

import type { DriftMonitor, DriftReference, DriftState, DriftVerdict } from '../../api/drift';
import {
  useDriftMonitors,
  useDriftReferences,
  useRemoveDriftReference,
  useStopDriftMonitor,
} from '../../api/hooks/useDrift';
import { useAllVideos } from '../../api/hooks/useVideos';
import { lutApi } from '../../api/lut';
import { videosApi } from '../../api/videos';
import { asUuid as asVideoUuid } from '../../types/common';
import { qk } from '../../api/queryKeys';
import { useLiveSourcesStore } from '../../store/liveSourcesStore';
import { MEDIA_WELL } from '../../theme/paint';
import { useT } from '../../i18n';
import { LutImportDialog } from '../lut/LutImportDialog';
import { DRIFT_LABEL, DriftPill } from './DriftPill';
import { DriftOverlay } from './DriftOverlay';
import { DriftSection } from './DriftSection';
import { useDriftPlayback } from './useDriftPlayback';

const CUSTOM = '__custom__';

/** The four states as a tiny square — for the history strip. Colour AND shape. */
const DOT: Record<DriftState, { color: string; style: string }> = {
  OK: { color: 'var(--status-ok)', style: 'solid' },
  MOVED: { color: 'var(--status-warn)', style: 'dashed' },
  CHANGED: { color: 'var(--status-error)', style: 'double' },
  DEGRADED: { color: 'var(--hairline-strong)', style: 'solid' },
};

function HistoryStrip({ history }: { history: readonly DriftVerdict[] }): JSX.Element | null {
  const t = useT();
  const recent = history.slice(-16);
  if (recent.length === 0) return null;
  return (
    <Stack
      direction="row"
      spacing={0.5}
      aria-label={t('Recent verdicts')}
      sx={{ alignItems: 'center' }}
    >
      {recent.map((v, i) => (
        <Tooltip key={`${v.checked_utc}-${i}`} title={`${t(DRIFT_LABEL[v.state])} — ${v.why}`}>
          <Box
            component="span"
            role="img"
            tabIndex={0}
            aria-label={`${t(DRIFT_LABEL[v.state])} — ${v.why}`}
            data-drift-state={v.state}
            sx={{
              'width': 10,
              'height': 10,
              '&:focus-visible': { outline: '2px solid var(--accent)', outlineOffset: 1 },
              'borderRadius': 'var(--radius-sm)',
              'border': `2px ${DOT[v.state].style} ${DOT[v.state].color}`,
              'bgcolor': v.state === 'OK' ? DOT[v.state].color : 'transparent',
              'flexShrink': 0,
            }}
          />
        </Tooltip>
      ))}
    </Stack>
  );
}

function Readout({ label, value }: { label: string; value: string }): JSX.Element {
  return (
    <Box sx={{ minWidth: 0 }}>
      <Typography
        sx={{
          fontSize: 11,
          letterSpacing: '0.06em',
          textTransform: 'uppercase',
          color: 'text.secondary',
          lineHeight: 1.2,
        }}
      >
        {label}
      </Typography>
      <Typography className="le-mono" sx={{ fontSize: 15, fontWeight: 600, lineHeight: 1.3 }}>
        {value}
      </Typography>
    </Box>
  );
}

const fmt = (n: number | null | undefined, digits: number, unit = ''): string =>
  n === null || n === undefined ? '—' : `${n.toFixed(digits)}${unit}`;

export function DriftMonitorTab(): JSX.Element {
  const t = useT();
  const savedSources = useLiveSourcesStore((s) => s.sources);
  const videos = useAllVideos();
  // Also queried by the detection pages; React Query dedupes the two by key.
  const lutLibrary = useQuery({
    queryKey: qk.lut.library(),
    queryFn: ({ signal }) => lutApi.library(signal),
    staleTime: 30_000,
  });
  const references = useDriftReferences();
  // ★ This page IS the console: the status poll runs for as long as it is open.
  const monitors = useDriftMonitors(true);
  const stop = useStopDriftMonitor();
  const remove = useRemoveDriftReference();

  // ── choosing vs applied ─────────────────────────────────────────────────────
  const [sourceChoice, setSourceChoice] = useState<string>('');
  const [customSource, setCustomSource] = useState('');
  const [lutSite, setLutSite] = useState('');
  // ★ The monitor's table can come from another machine — import it from here and
  //   it lands in the same library, selected. See LutImportDialog.
  const [importOpen, setImportOpen] = useState(false);
  const [applied, setApplied] = useState({ source: '', lutSite: '' });
  const [verdict, setVerdict] = useState<DriftVerdict | null>(null);
  const [forgetting, setForgetting] = useState<DriftReference | null>(null);

  const chosenSource = sourceChoice === CUSTOM ? customSource.trim() : sourceChoice;
  const dirty = applied.source !== chosenSource || applied.lutSite !== lutSite;
  const canApply = chosenSource !== '' && lutSite !== '';
  const live = applied.source !== '' && !applied.source.startsWith('video:');
  const appliedClipId = applied.source.startsWith('video:') ? applied.source.slice(6) : '';

  // ★ SEE THE CLIP WHILE IT IS JUDGED. A verdict read off a table says "moved";
  //   the frozen view's outline drawn over the playing picture shows WHERE. While
  //   the player runs, the frame at its current second is checked about once a
  //   second (useDriftPlayback); paused, Check now judges the typed second by hand.
  //   Live sources get no player here — the Live stream page already shows the
  //   picture with this overlay, and a second open of the device would starve the
  //   monitor's own capture.
  const [videoEl, setVideoEl] = useState<HTMLVideoElement | null>(null);
  const appliedRefId = useMemo(
    () => (references.data ?? []).find((r) => r.source === applied.source)?.ref_id,
    [references.data, applied.source],
  );
  const playbackVerdict = useDriftPlayback(videoEl, appliedRefId, appliedClipId !== '');

  const clipOptions = useMemo(
    () => (videos.data?.items ?? []).map((v) => ({ value: `video:${v.id}`, label: v.filename })),
    [videos.data],
  );
  const knownSources = useMemo(
    () => new Set([...savedSources.map((s) => s.url), ...clipOptions.map((c) => c.value)]),
    [savedSources, clipOptions],
  );

  const apply = (): void => setApplied({ source: chosenSource, lutSite });

  /** Point the pickers at a frozen reference and apply it in one press. */
  const use = (ref: DriftReference): void => {
    if (knownSources.has(ref.source)) {
      setSourceChoice(ref.source);
    } else {
      setSourceChoice(CUSTOM);
      setCustomSource(ref.source);
    }
    setLutSite(ref.lut_site);
    setApplied({ source: ref.source, lutSite: ref.lut_site });
    setVerdict(null);
  };

  const monitorFor = (ref: DriftReference): DriftMonitor | undefined =>
    (monitors.data ?? []).find((m) => m.ref_id === ref.ref_id) ??
    (monitors.data ?? []).find((m) => m.source === ref.source && m.status === 'running');

  const refs = references.data ?? [];
  const running = (monitors.data ?? []).filter((m) => m.status === 'running');

  return (
    <Box>
      <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mb: 1 }}>
        <RadarOutlinedIcon color="primary" />
        <Typography variant="h6">{t('Drift monitor')}</Typography>
        {running.length > 0 && (
          <Chip
            size="small"
            variant="outlined"
            label={`${running.length} ${t(running.length === 1 ? 'watch running' : 'watches running')}`}
          />
        )}
      </Stack>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2, maxWidth: 820 }}>
        {t(
          'A fixed camera is only as trustworthy as its aim. Freeze a reference while the view is trusted, and every later check says whether the camera has moved, whether its optics have changed, or whether the frame is too poor to judge. The monitor measures change from the reference — never whether the reference itself was right.',
        )}
      </Typography>

      {/* ── the camera under watch ─────────────────────────────────────────── */}
      <Card variant="outlined" sx={{ mb: 2 }}>
        <CardContent>
          <Typography variant="subtitle2" sx={{ mb: 1.5 }}>
            {t('Camera under watch')}
          </Typography>
          <Stack
            direction={{ xs: 'column', md: 'row' }}
            spacing={1.5}
            alignItems={{ xs: 'stretch', md: 'flex-start' }}
          >
            <FormControl size="small" sx={{ minWidth: 260, flex: 1 }}>
              <InputLabel id="drift-source-label">{t('Source')}</InputLabel>
              <Select
                labelId="drift-source-label"
                label={t('Source')}
                value={sourceChoice}
                onChange={(e) => setSourceChoice(String(e.target.value))}
                inputProps={{ 'aria-label': t('Source') }}
              >
                <MenuItem value="">
                  <em>{t('Choose a camera or a clip')}</em>
                </MenuItem>
                {savedSources.length > 0 && (
                  <ListSubheader disableSticky>{t('Saved cameras')}</ListSubheader>
                )}
                {savedSources.map((s) => (
                  <MenuItem key={s.id} value={s.url}>
                    {s.name}
                    <Typography
                      component="span"
                      className="le-mono"
                      sx={{ ml: 1, fontSize: 11, color: 'text.secondary' }}
                    >
                      {s.url}
                    </Typography>
                  </MenuItem>
                ))}
                {clipOptions.length > 0 && (
                  <ListSubheader disableSticky>{t('Library clips')}</ListSubheader>
                )}
                {clipOptions.map((c) => (
                  <MenuItem key={c.value} value={c.value}>
                    {c.label}
                  </MenuItem>
                ))}
                <ListSubheader disableSticky>{t('Other')}</ListSubheader>
                <MenuItem value={CUSTOM}>{t('A camera URL or capture device…')}</MenuItem>
              </Select>
            </FormControl>

            {sourceChoice === CUSTOM && (
              <TextField
                size="small"
                label={t('Camera URL or device')}
                placeholder="rtsp://…  ·  http://…  ·  /dev/video0"
                value={customSource}
                onChange={(e) => setCustomSource(e.target.value)}
                sx={{ minWidth: 260, flex: 1 }}
                inputProps={{ 'aria-label': t('Camera URL or device') }}
              />
            )}

            <FormControl size="small" sx={{ minWidth: 220, flex: 1 }}>
              <InputLabel id="drift-lut-label">{t('Lookup table')}</InputLabel>
              <Select
                labelId="drift-lut-label"
                label={t('Lookup table')}
                value={lutSite}
                onChange={(e) => setLutSite(String(e.target.value))}
                inputProps={{ 'aria-label': t('Lookup table') }}
              >
                <MenuItem value="">
                  <em>{t('Choose the lookup table this camera was trusted with')}</em>
                </MenuItem>
                {(lutLibrary.data ?? []).map((entry) => (
                  <MenuItem
                    key={entry.site_name}
                    value={entry.site_name}
                    // ★ DRIFT NEEDS THE POSE, not just the table. Freezing a
                    //   reference re-solves geometry from `pose.R/C/K` + `dem.epsg`
                    //   in the manifest; a bundle imported as bare lat/lon arrays
                    //   has none, and the freeze would fail seconds after the
                    //   surveyor committed to it. Say so while they are choosing.
                    disabled={!entry.has_pose}
                  >
                    {entry.site_name}
                    {!entry.has_pose && (
                      <Typography
                        component="span"
                        sx={{ ml: 1, fontSize: 11, color: 'var(--text-secondary)' }}
                      >
                        {t('no pose in its manifest')}
                      </Typography>
                    )}
                    {entry.has_pose && entry.validation_passed === false && (
                      <Typography
                        component="span"
                        sx={{ ml: 1, fontSize: 11, color: 'var(--status-warn)' }}
                      >
                        {t('validation failed')}
                      </Typography>
                    )}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>

            <Button
              variant="outlined"
              startIcon={<DriveFolderUploadOutlinedIcon />}
              onClick={() => setImportOpen(true)}
              sx={{ alignSelf: { md: 'center' }, whiteSpace: 'nowrap' }}
            >
              {t('Import')}
            </Button>

            <Button
              variant={dirty && canApply ? 'contained' : 'outlined'}
              disabled={!canApply || !dirty}
              onClick={apply}
              sx={{ alignSelf: { md: 'center' }, whiteSpace: 'nowrap' }}
            >
              {t('Apply')}
            </Button>
          </Stack>
          {lutLibrary.data !== undefined && lutLibrary.data.length === 0 && (
            <Alert severity="info" variant="outlined" sx={{ mt: 1.5 }}>
              {t(
                'No lookup table built yet — the reference needs one to give each landmark its ground position. Build one in the LUT generator first, or import one built elsewhere.',
              )}
            </Alert>
          )}
          {/* ★ The library holds tables, but only tables WITH A POSE can be frozen.
              Saying it once here beats a row of disabled options with no reason. */}
          {(lutLibrary.data ?? []).length > 0 &&
            (lutLibrary.data ?? []).every((e) => !e.has_pose) && (
              <Alert severity="warning" variant="outlined" sx={{ mt: 1.5 }}>
                {t(
                  'None of the lookup tables in the library carries a camera pose, and the drift monitor re-solves geometry from it. Import a full bundle (one that includes its manifest.json), or build one here.',
                )}
              </Alert>
            )}

          <LutImportDialog
            open={importOpen}
            onClose={() => setImportOpen(false)}
            onImported={(entry) => {
              // ★ Only select what this page can actually use — silently selecting a
              //   poseless table would hand the surveyor a Freeze that cannot work.
              if (entry.has_pose) setLutSite(entry.site_name);
            }}
          />
        </CardContent>
      </Card>

      {/* ── the watch itself ───────────────────────────────────────────────── */}
      <Box sx={{ mb: 2 }}>
        <DriftSection
          source={applied.source === '' ? null : applied.source}
          lutSite={applied.lutSite}
          live={live}
          onVerdict={setVerdict}
          liveVerdict={playbackVerdict}
        />
      </Box>

      {appliedClipId !== '' && (
        <Card variant="outlined" sx={{ mb: 2, overflow: 'hidden' }}>
          <Stack
            direction="row"
            alignItems="center"
            spacing={1}
            sx={{ px: 2, py: 1, borderBottom: '1px solid var(--hairline)' }}
          >
            <VideoFileOutlinedIcon fontSize="small" />
            <Typography variant="subtitle2">
              {clipOptions.find((c) => c.value === applied.source)?.label ?? applied.source}
            </Typography>
            <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
              {t('Play the clip — each second is judged against the frozen view as it goes.')}
            </Typography>
          </Stack>
          <Box sx={{ position: 'relative', bgcolor: MEDIA_WELL }}>
            <video
              key={appliedClipId}
              ref={setVideoEl}
              src={videosApi.fileUrl(asVideoUuid(appliedClipId))}
              controls
              preload="metadata"
              style={{ display: 'block', width: '100%', maxHeight: 520, objectFit: 'contain' }}
            />
            {/* the frozen view's box, riding on the playing picture */}
            <DriftOverlay verdict={verdict} />
          </Box>
        </Card>
      )}

      {verdict !== null && (
        <Card variant="outlined" sx={{ mb: 2 }}>
          <CardContent>
            <Stack
              direction="row"
              spacing={1.5}
              alignItems="center"
              sx={{ mb: 1.5, flexWrap: 'wrap' }}
            >
              <DriftPill state={verdict.state} confirmed={verdict.status === verdict.state} />
              {verdict.status !== null && verdict.status !== verdict.state && (
                <Typography variant="caption" color="text.secondary">
                  {t('confirmed:')} {t(DRIFT_LABEL[verdict.status])}
                </Typography>
              )}
              <Typography variant="body2" sx={{ flex: 1, minWidth: 200 }}>
                {verdict.why}
              </Typography>
            </Stack>
            <Box
              sx={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))',
                gap: 2,
              }}
            >
              <Readout label={t('Rotation')} value={fmt(verdict.rot_deg, 3, '°')} />
              {/* ★ GEO-DRIFT A3: which way it moved — pan (left/right), tilt (up/down), roll. */}
              <Readout label={t('Pan')} value={fmt(verdict.angles?.pan_deg ?? null, 3, '°')} />
              <Readout label={t('Tilt')} value={fmt(verdict.angles?.tilt_deg ?? null, 3, '°')} />
              <Readout label={t('Roll')} value={fmt(verdict.angles?.roll_deg ?? null, 3, '°')} />
              <Readout label={t('Ground error')} value={fmt(verdict.ground_err_at_ref, 2, ' m')} />
              <Readout
                label={t('Landmarks')}
                value={`${verdict.n_matched}/${verdict.n_landmarks} · ${verdict.n_lost} ${t('lost')}`}
              />
              <Readout
                label={t('Inliers')}
                value={verdict.n_inliers === null ? '—' : String(verdict.n_inliers)}
              />
              <Readout label={t('Residual')} value={fmt(verdict.resid_mean_px, 2, ' px')} />
              <Readout label={t('Confidence')} value={fmt(verdict.mean_conf, 2)} />
              <Readout label={t('SNR')} value={fmt(verdict.snr, 1)} />
              <Readout label={t('Checked')} value={verdict.checked_utc} />
            </Box>
          </CardContent>
        </Card>
      )}

      {/* ── every frozen reference ─────────────────────────────────────────── */}
      <Typography variant="subtitle2" sx={{ mt: 3, mb: 1 }}>
        {t('Frozen references')}
      </Typography>
      {references.isLoading ? (
        <Box sx={{ py: 3, textAlign: 'center' }}>
          <CircularProgress size={24} />
        </Box>
      ) : references.isError ? (
        <Alert severity="error" variant="outlined">
          {t('Could not load the drift references.')}
        </Alert>
      ) : refs.length === 0 ? (
        <Card variant="outlined">
          <CardContent>
            <Typography variant="body2" color="text.secondary">
              {t(
                'No reference frozen yet. Choose a source and its lookup table above, apply them, and freeze while the aim is trusted.',
              )}
            </Typography>
          </CardContent>
        </Card>
      ) : (
        <TableContainer component={Card} variant="outlined">
          <Table size="small" aria-label={t('Frozen references')}>
            <TableHead>
              <TableRow>
                <TableCell>{t('Reference')}</TableCell>
                <TableCell>{t('Source')}</TableCell>
                <TableCell>{t('Lookup table')}</TableCell>
                <TableCell align="right">{t('Landmarks')}</TableCell>
                <TableCell align="right">{t('Alert above')}</TableCell>
                <TableCell>{t('Frozen')}</TableCell>
                <TableCell>{t('Watch')}</TableCell>
                <TableCell align="right" />
              </TableRow>
            </TableHead>
            <TableBody>
              {refs.map((ref) => {
                const monitor = monitorFor(ref);
                const isApplied = applied.source === ref.source && applied.lutSite === ref.lut_site;
                return (
                  <TableRow
                    key={ref.ref_id}
                    hover
                    selected={isApplied}
                    sx={{ '&.Mui-selected': { bgcolor: 'var(--accent-quiet)' } }}
                  >
                    <TableCell>
                      <Typography variant="body2" sx={{ fontWeight: 500 }}>
                        {ref.name}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <Tooltip title={ref.source}>
                        <Typography className="le-mono" sx={{ fontSize: 12 }} noWrap>
                          {ref.source_label}
                        </Typography>
                      </Tooltip>
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2">{ref.lut_site}</Typography>
                    </TableCell>
                    <TableCell align="right">{ref.n_landmarks}</TableCell>
                    <TableCell align="right">
                      {ref.alert_ground_m} m @ {Math.round(ref.ref_range_m)} m
                    </TableCell>
                    <TableCell>
                      <Typography className="le-mono" sx={{ fontSize: 12 }}>
                        {ref.created_utc}
                        {ref.frozen_at_s != null ? ` · ${ref.frozen_at_s} s` : ''}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      {monitor === undefined ? (
                        <Typography variant="caption" color="text.secondary">
                          {ref.source.startsWith('video:') ? t('on demand') : t('not watching')}
                        </Typography>
                      ) : (
                        <Stack spacing={0.5}>
                          <Stack direction="row" spacing={1} alignItems="center">
                            <Chip
                              size="small"
                              variant="outlined"
                              label={
                                monitor.status === 'running'
                                  ? `${t('every')} ${monitor.interval_s} s · ${monitor.checks_done} ${t('checks')}`
                                  : t(monitor.status === 'failed' ? 'watch failed' : 'stopped')
                              }
                              sx={{
                                borderColor:
                                  monitor.status === 'running'
                                    ? 'var(--status-busy)'
                                    : monitor.status === 'failed'
                                      ? 'var(--status-error)'
                                      : undefined,
                              }}
                            />
                            {monitor.last !== null && (
                              <DriftPill
                                state={monitor.last.state}
                                confirmed={monitor.last.status === monitor.last.state}
                              />
                            )}
                          </Stack>
                          <HistoryStrip history={monitor.history} />
                          {monitor.capture_failures > 0 && (
                            <Typography variant="caption" sx={{ color: 'var(--status-warn)' }}>
                              {monitor.capture_failures} {t('looks failed (device busy)')}
                            </Typography>
                          )}
                        </Stack>
                      )}
                    </TableCell>
                    <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>
                      <Button size="small" onClick={() => use(ref)} disabled={isApplied}>
                        {isApplied ? t('In use') : t('Use')}
                      </Button>
                      {monitor?.status === 'running' && (
                        <Button
                          size="small"
                          startIcon={<StopCircleOutlinedIcon sx={{ fontSize: 16 }} />}
                          disabled={stop.isPending}
                          onClick={() => stop.mutate(monitor.ref_id)}
                        >
                          {t('Stop')}
                        </Button>
                      )}
                      <Tooltip title={t('Forget this reference')}>
                        <span>
                          <Button
                            size="small"
                            color="inherit"
                            aria-label={`${t('Forget')} ${ref.name}`}
                            disabled={remove.isPending}
                            onClick={() => setForgetting(ref)}
                            sx={{ 'minWidth': 0, 'px': 1, '&:hover': { color: 'error.main' } }}
                          >
                            <DeleteOutlineIcon sx={{ fontSize: 18 }} />
                          </Button>
                        </span>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {(stop.error !== null || remove.error !== null) && (
        <Typography
          variant="caption"
          sx={{ color: 'var(--status-error)', display: 'block', mt: 1 }}
        >
          {(stop.error ?? remove.error)?.message}
        </Typography>
      )}

      <Dialog
        open={forgetting !== null}
        onClose={() => setForgetting(null)}
        maxWidth="xs"
        fullWidth
      >
        <DialogTitle>{t('Forget this reference?')}</DialogTitle>
        <DialogContent>
          <DialogContentText component="div">
            <Typography variant="body2">
              <strong>{forgetting?.name}</strong> — {forgetting?.source_label}.{' '}
              {t('Its watch stops and its history goes with it. The camera itself is not touched.')}
            </Typography>
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setForgetting(null)} disabled={remove.isPending}>
            {t('Cancel')}
          </Button>
          <Button
            color="error"
            variant="contained"
            disabled={remove.isPending}
            onClick={() => {
              if (forgetting === null) return;
              remove.mutate(forgetting.ref_id, { onSettled: () => setForgetting(null) });
            }}
          >
            {remove.isPending ? t('Forgetting…') : t('Forget')}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

export default DriftMonitorTab;
