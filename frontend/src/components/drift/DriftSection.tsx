/**
 * `drift/DriftSection.tsx` — the drift watch strip: freeze, check, monitor.
 *
 * ★ THE FLOW IT SERVES: while the aim is trusted, FREEZE a reference (the LUT
 *   gives each landmark its ground position); afterwards CHECK judges any fresh
 *   frame against it, and on a live source the MONITOR does that on a clock.
 *   Stored clips get no monitor toggle — the server refuses them (a clip does
 *   not drift while it sits on disk), so the control is not offered.
 *
 * ★ Every refusal and verdict sentence from the server is shown VERBATIM — the
 *   monitor's `why` is written for operators, and paraphrasing an honesty
 *   instrument is how it stops being one.
 */

import { useEffect, useMemo, useState, type JSX } from 'react';
import { useQuery } from '@tanstack/react-query';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CircularProgress from '@mui/material/CircularProgress';
import MenuItem from '@mui/material/MenuItem';
import Select from '@mui/material/Select';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Tooltip from '@mui/material/Tooltip';
import Link from '@mui/material/Link';
import Typography from '@mui/material/Typography';
import AcUnitOutlinedIcon from '@mui/icons-material/AcUnitOutlined';
import MemoryOutlinedIcon from '@mui/icons-material/MemoryOutlined';
import RadarOutlinedIcon from '@mui/icons-material/RadarOutlined';
import TravelExploreOutlinedIcon from '@mui/icons-material/TravelExploreOutlined';

import type { DriftVerdict } from '../../api/drift';
import { API_BASE_URL } from '../../api/client';
import { lutApi } from '../../api/lut';
import { qk } from '../../api/queryKeys';
import {
  useDriftCheck,
  useDriftMonitors,
  useDriftReferences,
  useFreezeReference,
  useStartDriftMonitor,
  useStopDriftMonitor,
} from '../../api/hooks/useDrift';
import { t } from '../../i18n';
import { DRIFT_LABEL, DriftPill } from './DriftPill';
import { freshestVerdict } from './verdict';

const INTERVALS: ReadonlyArray<{ s: number; label: string }> = [
  { s: 2, label: '2 s' },
  { s: 5, label: '5 s' },
  { s: 10, label: '10 s' },
  { s: 30, label: '30 s' },
  { s: 60, label: '1 min' },
  { s: 300, label: '5 min' },
];

export interface DriftSectionProps {
  /** The tab's APPLIED source (`video:<id>` or a live src); null = none yet. */
  source: string | null;
  /** The tab's APPLIED LUT site; '' = none. */
  lutSite: string;
  /** Live tabs offer the monitor clock; clip tabs check on demand only. */
  live: boolean;
  /** The freshest verdict, for the tab's map banner. Null when nothing is known. */
  onVerdict?: (verdict: DriftVerdict | null) => void;
  /** A verdict the tab produced itself (clip playback checks) — outranks a manual one. */
  liveVerdict?: DriftVerdict | null;
  /**
   * `strip` (default): one row, for a wide tab. `stack`: a column, for the
   * monitor's inspector — the strip overlapped its own controls at 360 px.
   */
  layout?: 'strip' | 'stack';
  /** The registered camera this watch belongs to (1.3): with it, Watch is the
   *  camera's DESIRED state and comes back after an API restart. */
  cameraId?: string | null;
  /** The camera's field of view (step 3 of its settings) — the seed for a freeze
   *  on a lookup table that carries no intrinsics (GEO-DRIFT C1). */
  cameraFovDeg?: number | null;
}

export function DriftSection({
  source,
  lutSite,
  live,
  onVerdict,
  liveVerdict = null,
  layout = 'strip',
  cameraId = null,
  cameraFovDeg = null,
}: DriftSectionProps): JSX.Element {
  const stacked = layout === 'stack';
  const references = useDriftReferences();
  // Newest-first from the server, so the first match is the current reference —
  // re-freezing supersedes without deleting history.
  const reference = useMemo(
    () => (references.data ?? []).find((r) => r.source === source),
    [references.data, source],
  );

  const monitors = useDriftMonitors(reference !== undefined);
  // ★ The current reference's monitor — but ALSO any still-running watch on this
  //   source from an older reference: nothing invisible may hold the camera.
  //   (The server retires those on re-freeze; this is the belt to that brace.)
  const monitor = useMemo(() => {
    const items = monitors.data ?? [];
    return (
      items.find((m) => m.ref_id === reference?.ref_id) ??
      items.find((m) => m.source === source && m.status === 'running')
    );
  }, [monitors.data, reference?.ref_id, source]);

  const freeze = useFreezeReference();
  const check = useDriftCheck();
  const start = useStartDriftMonitor();
  const stop = useStopDriftMonitor();
  const [intervalS, setIntervalS] = useState(30);
  const [manual, setManual] = useState<DriftVerdict | null>(null);
  // Clip sources: which second to freeze from / judge — a clip check without a
  // time would re-read frame 0, the frozen frame itself.
  const isClip = source?.startsWith('video:') ?? false;
  const [clipAtS, setClipAtS] = useState('0');
  const atS = isClip ? Math.max(0, Number(clipAtS) || 0) : undefined;
  // ★ The trap found in the field: freezing AND checking at the same second
  //   compares a frame with itself and reads "perfectly steady". Recognised,
  //   named, and refused.
  const sameAsFrozen =
    isClip && reference?.frozen_at_s != null && atS !== undefined && atS === reference.frozen_at_s;
  // The alarm threshold, in metres at the scene's range — set at freeze time.
  const [alertM, setAlertM] = useState('1');

  // ★ The NEWEST reading wins — a stopped watch, or a watch on an older reference,
  //   must never outrank a fresh Check now (drift/verdict.ts).
  const verdict = useMemo(
    () => freshestVerdict(monitor?.last, liveVerdict, manual),
    [monitor?.last, liveVerdict, manual],
  );
  useEffect(() => {
    onVerdict?.(verdict);
  }, [verdict, onVerdict]);
  // A manual check belongs to the source and reference it was made on.
  useEffect(() => {
    setManual(null);
  }, [source, reference?.ref_id]);

  const running = monitor?.status === 'running';

  // ★ DRIFT NEEDS THE POSE, NOT JUST THE TABLE. Freezing re-solves geometry from
  //   `pose.R/C/K` in the bundle's manifest; a lookup table imported as bare
  //   lat/lon arrays (or built by a generator that predates the pose record) has
  //   none, and the server refuses the freeze. That refusal used to be the first
  //   the surveyor heard of it — after pressing the button. The library already
  //   says which bundles carry a pose, so say it here, before.
  const lutLibrary = useQuery({
    queryKey: qk.lut.library(),
    queryFn: ({ signal }) => lutApi.library(signal),
    staleTime: 30_000,
  });
  const lutEntry = (lutLibrary.data ?? []).find((e) => e.site_name === lutSite);
  // ★ GEO-DRIFT C1: a bundle with everything but intrinsics is freezable once a
  //   field of view is given — the camera's own (step 3) seeds it, and the box
  //   below lets the operator correct it. Only a bundle with NO pose at all blocks.
  const lutNeedsFov = lutEntry?.pose_needs_fov === true;
  const lutHasNoPose = lutEntry !== undefined && !lutEntry.has_pose && !lutNeedsFov;
  const [fovText, setFovText] = useState<string>('');
  const fovDeg = fovText.trim() !== '' ? Number(fovText) : (cameraFovDeg ?? null);
  const fovOk = fovDeg !== null && Number.isFinite(fovDeg) && fovDeg > 0 && fovDeg < 180;
  const canFreeze =
    source !== null && source !== '' && lutSite !== '' && !lutHasNoPose && (!lutNeedsFov || fovOk);
  const freezeBlocker =
    source === null || source === ''
      ? t('Choose and apply a source above first.')
      : lutSite === ''
        ? t(
            'Apply a lookup table above — the reference needs it to give each landmark its ground position.',
          )
        : lutNeedsFov && !fovOk
          ? t(
              'This lookup table has no intrinsics — give the camera’s horizontal field of view (degrees) to freeze; the true sensor angle, not a spec sheet’s diagonal.',
            )
          : lutHasNoPose
            ? t(
                'This lookup table carries no camera pose, so the drift watch cannot use it — it can still place detections. Import the full bundle (with its manifest.json), or build one in the LUT generator.',
              )
            : null;

  const mutationError =
    (freeze.error ?? check.error ?? start.error ?? stop.error) instanceof Error
      ? ((freeze.error ?? check.error ?? start.error ?? stop.error) as Error).message
      : null;

  return (
    <Card variant="outlined" sx={{ px: stacked ? 1.5 : 2, py: 1.25 }}>
      <Stack
        direction={stacked ? 'column' : { xs: 'column', md: 'row' }}
        spacing={1.5}
        alignItems={stacked ? 'stretch' : { xs: 'stretch', md: 'center' }}
      >
        <Stack
          direction="row"
          spacing={1}
          alignItems="center"
          flexWrap={stacked ? 'wrap' : 'nowrap'}
          useFlexGap
          sx={{ minWidth: 0, flex: 1 }}
        >
          <RadarOutlinedIcon fontSize="small" color="action" />
          <Typography variant="subtitle2" sx={{ whiteSpace: 'nowrap' }}>
            {t('Drift watch')}
          </Typography>

          {verdict !== null && verdict !== undefined ? (
            <>
              {/* ★ THIS FRAME'S reading, always — hiding a raw MOVED behind a
                  still-OK confirmed status was a review bug. When the two differ
                  the confirmed status is named beside it. */}
              <DriftPill state={verdict.state} confirmed={verdict.status === verdict.state} />
              {verdict.status !== null && verdict.status !== verdict.state && (
                <Typography variant="caption" color="text.secondary" noWrap>
                  {t('confirmed:')} {t(DRIFT_LABEL[verdict.status])}
                </Typography>
              )}
              {verdict.rot_deg !== null && (
                <Typography variant="caption" className="le-mono" color="text.secondary">
                  {verdict.rot_deg.toFixed(3)}° · {verdict.ground_err_at_ref?.toFixed(2) ?? '—'} m
                  {verdict.angles && (
                    <>
                      {' · '}
                      {t('pan')} {verdict.angles.pan_deg.toFixed(2)}° {t('tilt')}{' '}
                      {verdict.angles.tilt_deg.toFixed(2)}° {t('roll')}{' '}
                      {verdict.angles.roll_deg.toFixed(2)}°
                    </>
                  )}
                </Typography>
              )}
              <Tooltip title={verdict.why}>
                <Typography
                  variant="caption"
                  color="text.secondary"
                  noWrap={!stacked}
                  sx={{ minWidth: 0, flex: stacked ? '1 0 100%' : 1 }}
                >
                  {verdict.why}
                </Typography>
              </Tooltip>
            </>
          ) : (
            <Typography
              variant="caption"
              color="text.secondary"
              noWrap={!stacked}
              sx={{ minWidth: 0, flex: stacked ? '1 0 100%' : undefined }}
            >
              {reference !== undefined
                ? t('Reference frozen — no check has run yet.')
                : (freezeBlocker ??
                  t('No reference for this view yet. Freeze one while the aim is trusted.'))}
            </Typography>
          )}
        </Stack>

        <Stack
          direction="row"
          spacing={1}
          alignItems="center"
          flexShrink={0}
          flexWrap={stacked ? 'wrap' : 'nowrap'}
          useFlexGap
        >
          {canFreeze && (
            <TextField
              size="small"
              type="number"
              value={alertM}
              onChange={(e) => setAlertM(e.target.value)}
              label={t('alert above (m)')}
              inputProps={{ 'min': 0.05, 'step': 0.1, 'aria-label': t('alert above (m)') }}
              sx={{ width: stacked ? '100%' : 124 }}
            />
          )}
          {isClip && (source !== null || reference !== undefined) && (
            <TextField
              size="small"
              type="number"
              value={clipAtS}
              onChange={(e) => setClipAtS(e.target.value)}
              label={reference !== undefined ? t('check at second') : t('at second')}
              error={sameAsFrozen}
              inputProps={{ 'min': 0, 'step': 1, 'aria-label': t('at second') }}
              sx={{ width: stacked ? '100%' : 130 }}
            />
          )}
          {reference !== undefined && (
            <Button
              size="small"
              startIcon={
                check.isPending ? (
                  <CircularProgress size={14} color="inherit" />
                ) : (
                  <TravelExploreOutlinedIcon sx={{ fontSize: 16 }} />
                )
              }
              disabled={check.isPending || sameAsFrozen}
              onClick={() =>
                check.mutate(
                  { refId: reference.ref_id, atS },
                  { onSuccess: (fresh) => setManual(fresh) },
                )
              }
            >
              {t('Check now')}
            </Button>
          )}

          {reference !== undefined && live && (
            <>
              {!running && (
                <Select
                  size="small"
                  value={intervalS}
                  onChange={(e) => setIntervalS(Number(e.target.value))}
                  sx={{ minWidth: 84 }}
                  inputProps={{ 'aria-label': t('Check interval') }}
                >
                  {INTERVALS.map((o) => (
                    <MenuItem key={o.s} value={o.s}>
                      {o.label}
                    </MenuItem>
                  ))}
                </Select>
              )}
              <Button
                size="small"
                variant={running ? 'outlined' : 'contained'}
                disabled={start.isPending || stop.isPending}
                onClick={() =>
                  running
                    ? // ★ stop the RUNNING watch — which may belong to an older
                      //   reference of this source, not the current one
                      stop.mutate({ refId: monitor?.ref_id ?? reference.ref_id, cameraId })
                    : start.mutate({ refId: reference.ref_id, intervalS, cameraId })
                }
              >
                {running ? t('Stop watching') : t('Watch')}
              </Button>
            </>
          )}

          {lutNeedsFov && (
            <TextField
              size="small"
              label={t('Field of view (°)')}
              value={fovText !== '' ? fovText : cameraFovDeg !== null ? String(cameraFovDeg) : ''}
              onChange={(e) => setFovText(e.target.value)}
              inputProps={{ inputMode: 'decimal', dir: 'ltr', style: { width: 72 } }}
              helperText={t('a seed for the intrinsics — the true sensor angle')}
            />
          )}
          <Tooltip title={freezeBlocker ?? ''}>
            {/* span: a disabled button swallows the tooltip's listeners */}
            <span>
              <Button
                size="small"
                variant={reference === undefined ? 'contained' : 'text'}
                startIcon={
                  freeze.isPending ? (
                    <CircularProgress size={14} color="inherit" />
                  ) : (
                    <AcUnitOutlinedIcon sx={{ fontSize: 16 }} />
                  )
                }
                disabled={!canFreeze || freeze.isPending}
                onClick={() => {
                  setManual(null);
                  freeze.mutate({
                    source: source ?? '',
                    lut_site: lutSite,
                    name: lutSite,
                    at_s: atS ?? null,
                    alert_ground_m: Math.max(0.05, Number(alertM) || 1),
                    // ★ A clip check is a deliberate look, not one tick of a clock —
                    //   asking for three identical presses would just be a chore.
                    confirm_n: isClip ? 1 : 3,
                    // ★ GEO-DRIFT D1: freeze on the photograph the table was built from
                    //   (its pose belongs to THAT picture), falling back to a grab.
                    use_lut_image: true,
                    // ★ GEO-DRIFT C1: a table without intrinsics takes K from the FOV.
                    ...(lutNeedsFov && fovOk
                      ? { no_calibration: true, fov_h_deg: fovDeg, square_pixels: true }
                      : {}),
                  });
                }}
              >
                {reference === undefined ? t('Freeze reference') : t('Re-freeze')}
              </Button>
            </span>
          </Tooltip>
        </Stack>
      </Stack>

      {/* ★ A poseless table is the one blocker worth a sentence, not just a tooltip:
          the surveyor chose it on purpose and needs to know it works for detection
          but not for this. */}
      {lutHasNoPose && (
        <Typography variant="caption" sx={{ color: 'var(--status-warn)', display: 'block' }}>
          {freezeBlocker}
        </Typography>
      )}

      {/* server refusals and loop trouble, verbatim */}
      {mutationError !== null && (
        <Typography variant="caption" sx={{ color: 'var(--status-error)', display: 'block' }}>
          {mutationError}
        </Typography>
      )}
      {monitor?.last_error != null && (
        <Typography variant="caption" sx={{ color: 'var(--status-warn)', display: 'block' }}>
          {monitor.status === 'failed' ? t('Watch stopped:') : t('Last look failed:')}{' '}
          {monitor.last_error}
        </Typography>
      )}
      {sameAsFrozen && (
        <Typography variant="caption" sx={{ color: 'var(--status-warn)', display: 'block' }}>
          {t(
            'That is the frozen second — checking it against itself proves nothing. Pick another second.',
          )}
        </Typography>
      )}
      {reference !== undefined && (
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
          {t('{n} landmarks').replace('{n}', String(reference.n_landmarks))} · {t('alert above')}{' '}
          {reference.alert_ground_m} m @ {Math.round(reference.ref_range_m)} m · {t('frozen')}{' '}
          {reference.created_utc}
          {reference.frozen_at_s != null && (
            <>
              {' '}
              · {t('frozen at')} {reference.frozen_at_s} s
            </>
          )}
          {isClip && (
            <> · {t('Clip checks confirm immediately — each one is a deliberate look.')}</>
          )}
          {/* ★ GEO-DRIFT D1 / C1: how far this reference can be trusted, stated. */}
          {reference.frozen_from !== undefined && (
            <>
              {' · '}
              {reference.frozen_from === 'image'
                ? `${t('frozen on the photograph')}${reference.frozen_from_label ? ` ${reference.frozen_from_label}` : ''}`
                : reference.frozen_from === 'clip'
                  ? t('frozen from the clip')
                  : t('frozen from a live grab')}
            </>
          )}
          {reference.intrinsics_mode === 'fov' && (
            <>
              {' · '}
              {t('intrinsics from a field of view')}
              {reference.fov ? ` (${reference.fov.fov_h_deg}°)` : ''}
            </>
          )}
          {' · '}
          <Link
            href={`${API_BASE_URL}/drift/references/${encodeURIComponent(reference.ref_id)}/field-unit`}
            download
            underline="hover"
            sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}
          >
            <MemoryOutlinedIcon sx={{ fontSize: 13 }} />
            {t('Field unit bundle')}
          </Link>
        </Typography>
      )}
      {reference?.intrinsics_warning && (
        <Typography variant="caption" sx={{ color: 'var(--status-warn)', display: 'block' }}>
          {reference.intrinsics_warning}
        </Typography>
      )}
    </Card>
  );
}
