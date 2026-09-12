/**
 * `pages/DashboardPage.tsx` — what this installation holds, at a glance.
 *
 * ★ AN INFORMATION DASHBOARD, NOT A MAP (owner ask 2026-09-10). The satellite
 *   overview that lived here moved to the globe on the monitoring page, together
 *   with the offline-cache tool and a place search. This page now answers the
 *   questions an operator asks before opening anything: how many cameras, how
 *   many are ready and live, what the setups still lack, what the drift watch
 *   says, what has been recorded lately, and whether the machine underneath is
 *   healthy — with the numbers drawn as thin bars where a comparison helps.
 *
 * ★ EVERY READING DEGRADES ALONE. A query that fails leaves its panel saying so;
 *   the others keep answering. Nothing here blocks on anything else.
 */

import { useMemo, type JSX } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import RemoveCircleOutlineIcon from '@mui/icons-material/RemoveCircleOutline';
import WarningAmberOutlinedIcon from '@mui/icons-material/WarningAmberOutlined';

import { capabilitiesApi } from '../api/capabilities';
import { useDetectionAvailability } from '../api/hooks/useDetection';
import { useDriftMonitors, useDriftReferences } from '../api/hooks/useDrift';
import { useGcpOverviewState } from '../api/hooks/useGcpOverview';
import { useProjects } from '../api/hooks/useProjects';
import { liveApi } from '../api/live';
import { lutApi } from '../api/lut';
import { offlineApi } from '../api/offline';
import { qk } from '../api/queryKeys';
import { BarRows, DayBars, Panel, StatTile, type DayCount } from '../components/dashboard/charts';
import { t } from '../i18n';
import { setupProgress } from './cameras/CameraServerPage';
import {
  selectCameras,
  useCameraRegistryStore,
  type CameraStatusState,
} from '../store/cameraRegistryStore';

// ── helpers ───────────────────────────────────────────────────────────────────

const STATE_TONE: Record<CameraStatusState, string> = {
  live: 'var(--status-ok)',
  connecting: 'var(--status-busy)',
  lost: 'var(--status-error)',
  refused: 'var(--status-error)',
  unknown: 'var(--hairline-strong)',
};

const VERDICT_TONE: Record<string, string> = {
  ok: 'var(--status-ok)',
  moved: 'var(--status-error)',
  changed: 'var(--status-warn)',
  degraded: 'var(--status-warn)',
  pending: 'var(--hairline-strong)',
};

function fmtDuration(s: number): string {
  if (s < 60) return `${Math.round(s)} s`;
  if (s < 3600) return `${Math.round(s / 60)} min`;
  return `${(s / 3600).toFixed(1)} h`;
}

function fmtBytes(b: number): string {
  if (b < 1024 ** 2) return `${Math.round(b / 1024)} KB`;
  if (b < 1024 ** 3) return `${(b / 1024 ** 2).toFixed(0)} MB`;
  return `${(b / 1024 ** 3).toFixed(1)} GB`;
}

function fmtUptime(s: number): string {
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  return d > 0 ? `${d} d ${h} h` : h > 0 ? `${h} h ${m} min` : `${m} min`;
}

/** The last `n` days, oldest first, with how many recordings started on each. */
export function recordingsPerDay(startedAt: readonly string[], n = 14, today = new Date()): DayCount[] {
  const days: DayCount[] = [];
  const counts = new Map<string, number>();
  for (const iso of startedAt) {
    const key = iso.slice(0, 10);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  for (let i = n - 1; i >= 0; i -= 1) {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    const key = d.toISOString().slice(0, 10);
    days.push({ day: key, count: counts.get(key) ?? 0 });
  }
  return days;
}

function StatusIcon({ status }: { status: string }): JSX.Element {
  const sx = { fontSize: 16 };
  if (status === 'up') return <CheckCircleOutlineIcon sx={{ ...sx, color: 'var(--status-ok)' }} />;
  if (status === 'degraded') return <WarningAmberOutlinedIcon sx={{ ...sx, color: 'var(--status-warn)' }} />;
  if (status === 'down') return <ErrorOutlineIcon sx={{ ...sx, color: 'var(--status-error)' }} />;
  return <RemoveCircleOutlineIcon sx={{ ...sx, color: 'text.disabled' }} />;
}

// ── the page ──────────────────────────────────────────────────────────────────

export function DashboardPage(): JSX.Element {
  const navigate = useNavigate();

  // Fleet — the registry is already in memory.
  const cameras = useCameraRegistryStore(selectCameras);
  const statuses = useCameraRegistryStore((s) => s.statuses);
  const fleet = useMemo(() => {
    const ready = cameras.filter((c) => setupProgress(c).complete).length;
    const byState: Record<CameraStatusState, number> = { live: 0, connecting: 0, lost: 0, refused: 0, unknown: 0 };
    for (const c of cameras) byState[statuses[c.id]?.state ?? 'unknown'] += 1;
    const has = { calibration: 0, frame: 0, lut: 0 };
    for (const c of cameras) {
      const p = setupProgress(c);
      if (p.calibration) has.calibration += 1;
      if (p.frame) has.frame += 1;
      if (p.lut) has.lut += 1;
    }
    return { total: cameras.length, ready, inSetup: cameras.length - ready, byState, has };
  }, [cameras, statuses]);

  // Survey
  const projects = useProjects({ limit: 200 });
  const overview = useGcpOverviewState({ limit: 200 });
  const photoCount = useMemo(
    () => (projects.data?.items ?? []).reduce((sum, p) => sum + p.image_count, 0),
    [projects.data],
  );
  const lut = useQuery({ queryKey: qk.lut.library(), queryFn: ({ signal }) => lutApi.library(signal), staleTime: 30_000 });
  const luts = lut.data ?? [];

  // Recordings
  const recordings = useQuery({
    queryKey: [...qk.all, 'live', 'recordings', 'dashboard'],
    queryFn: ({ signal }) => liveApi.listRecordings(signal),
    staleTime: 30_000,
  });
  const recs = useMemo(() => recordings.data?.items ?? [], [recordings.data]);
  const recTotals = useMemo(
    () => ({
      count: recs.length,
      seconds: recs.reduce((a, r) => a + (r.duration_s ?? 0), 0),
      bytes: recs.reduce((a, r) => a + (r.video_bytes ?? 0), 0),
      marks: recs.reduce((a, r) => a + (r.marks ?? 0), 0),
      perDay: recordingsPerDay(recs.map((r) => r.started_at).filter((s) => s !== '')),
    }),
    [recs],
  );

  // Drift
  const references = useDriftReferences();
  const monitors = useDriftMonitors(true);
  const drift = useMemo(() => {
    const running = (monitors.data ?? []).filter((m) => m.status === 'running');
    const verdicts: Record<string, number> = { ok: 0, moved: 0, changed: 0, degraded: 0, pending: 0 };
    for (const m of running) {
      const word = (m.last as { status?: string } | null)?.status ?? 'pending';
      verdicts[word in verdicts ? word : 'pending'] += 1;
    }
    return { references: (references.data ?? []).length, watching: running.length, verdicts };
  }, [references.data, monitors.data]);

  // System
  const health = useQuery({ queryKey: [...qk.all, 'health', 'dashboard'], queryFn: ({ signal }) => capabilitiesApi.health(signal), staleTime: 15_000 });
  const readiness = useQuery({ queryKey: [...qk.all, 'readiness', 'dashboard'], queryFn: ({ signal }) => capabilitiesApi.readiness(undefined, false, signal), staleTime: 15_000 });
  const detection = useDetectionAvailability();
  const manifests = useQuery({ queryKey: [...qk.all, 'offline', 'manifests', 'dashboard'], queryFn: ({ signal }) => offlineApi.listManifests(signal), staleTime: 30_000 });
  const cachedTiles = (manifests.data ?? []).reduce((a, m) => a + (m.completed_tiles ?? 0), 0);
  const device = detection.data?.device ?? null;
  const deviceWord = device === null ? '—' : device.startsWith('cuda') ? `GPU · ${device}` : device.toUpperCase();

  return (
    <Box sx={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
      <Box sx={{ maxWidth: 1400, mx: 'auto', px: { xs: 2, md: 3 }, py: 2.5 }}>
        {/* ── header ── */}
        <Stack direction="row" alignItems="center" spacing={2} sx={{ mb: 2 }}>
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography variant="h5" component="h1" sx={{ fontWeight: 700, lineHeight: 1.2 }}>
              {t('Overview')}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {health.data
                ? `${t('Server')} v${health.data.version} · ${t('up for')} ${fmtUptime(health.data.uptime_s)}`
                : t('What this installation holds, and how it is doing.')}
            </Typography>
          </Box>
          <Button variant="outlined" size="small" onClick={() => navigate('/cameras')}>
            {t('Camera workspace')}
          </Button>
          <Button variant="contained" size="small" onClick={() => navigate('/monitor')}>
            {t('Cameras Monitoring')}
          </Button>
        </Stack>

        {/* ── the headline numbers ── */}
        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: { xs: 'repeat(2, 1fr)', sm: 'repeat(4, 1fr)', lg: 'repeat(8, 1fr)' },
            gap: 1.5,
            mb: 2,
          }}
          data-testid="dashboard-tiles"
        >
          <StatTile value={fleet.total} label={t('cameras')} />
          <StatTile value={fleet.ready} label={t('ready')} tone={fleet.ready > 0 ? 'var(--status-ok)' : undefined} />
          <StatTile value={fleet.inSetup} label={t('in setup')} />
          <StatTile value={fleet.byState.live} label={t('live now')} tone={fleet.byState.live > 0 ? 'var(--status-ok)' : undefined} />
          <StatTile value={projects.data?.total ?? 0} label={t('projects')} />
          <StatTile value={photoCount} label={t('photographs')} />
          <StatTile value={overview.status === 'ready' ? overview.total : 0} label={t('control points')} />
          <StatTile value={luts.length} label={t('lookup tables')} hint={`${luts.filter((l) => l.validation_passed).length} ${t('validated')}`} />
        </Box>

        {/* ── the readings ── */}
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'repeat(2, 1fr)', xl: 'repeat(3, 1fr)' }, gap: 1.5 }}>
          <Panel title={t('Fleet')}>
            <BarRows
              aria-label={t('Cameras by live state')}
              max={Math.max(1, fleet.total)}
              rows={(['live', 'connecting', 'lost', 'refused', 'unknown'] as CameraStatusState[]).map((k) => ({
                label: t(k === 'unknown' ? 'not opened yet' : k),
                value: fleet.byState[k],
                color: STATE_TONE[k],
                note: `/ ${fleet.total}`,
              }))}
            />
          </Panel>

          <Panel
            title={t('Setup pipeline')}
            action={
              <Button size="small" onClick={() => navigate('/cameras')}>
                {t('Open')}
              </Button>
            }
          >
            <BarRows
              aria-label={t('Cameras that have each setup output')}
              max={Math.max(1, fleet.total)}
              rows={[
                { label: t('Calibration'), value: fleet.has.calibration, note: `/ ${fleet.total}` },
                { label: t('Frame'), value: fleet.has.frame, note: `/ ${fleet.total}` },
                { label: t('Lookup table'), value: fleet.has.lut, note: `/ ${fleet.total}` },
              ]}
            />
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1.25 }}>
              {fleet.inSetup === 0
                ? t('Every camera is measurable.')
                : `${fleet.inSetup} ${t('camera(s) still need their lookup table.')}`}
            </Typography>
          </Panel>

          <Panel
            title={t('Drift watch')}
            action={
              <Button size="small" onClick={() => navigate('/drift')}>
                {t('Open')}
              </Button>
            }
          >
            <Stack direction="row" spacing={3} sx={{ mb: 1.25 }}>
              <Box>
                <Typography className="le-mono" sx={{ fontSize: 20, fontWeight: 700, lineHeight: 1.1 }}>
                  {drift.watching}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {t('cameras watched')}
                </Typography>
              </Box>
              <Box>
                <Typography className="le-mono" sx={{ fontSize: 20, fontWeight: 700, lineHeight: 1.1 }}>
                  {drift.references}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {t('frozen references')}
                </Typography>
              </Box>
            </Stack>
            <BarRows
              aria-label={t('Watched cameras by latest verdict')}
              max={Math.max(1, drift.watching)}
              rows={(['ok', 'moved', 'changed', 'degraded', 'pending'] as const).map((k) => ({
                label: t(k),
                value: drift.verdicts[k],
                color: VERDICT_TONE[k],
              }))}
            />
          </Panel>

          <Panel
            title={t('Recordings')}
            action={
              <Button size="small" onClick={() => navigate('/videos')}>
                {t('Open')}
              </Button>
            }
          >
            <Stack direction="row" spacing={3} sx={{ mb: 1.25, flexWrap: 'wrap' }} useFlexGap>
              {[
                [recTotals.count, t('recordings')],
                [fmtDuration(recTotals.seconds), t('of video')],
                [fmtBytes(recTotals.bytes), t('on disk')],
                [recTotals.marks, t('marks recorded')],
              ].map(([v, l]) => (
                <Box key={String(l)}>
                  <Typography className="le-mono" sx={{ fontSize: 20, fontWeight: 700, lineHeight: 1.1 }}>
                    {v}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {l}
                  </Typography>
                </Box>
              ))}
            </Stack>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
              {t('Recordings started per day, last 14 days')}
            </Typography>
            <DayBars days={recTotals.perDay} aria-label={t('Recordings started per day, last 14 days')} />
          </Panel>

          <Panel
            title={t('System')}
            action={
              <Button size="small" onClick={() => navigate('/status')}>
                {t('Open')}
              </Button>
            }
          >
            <Stack spacing={0.75}>
              {(readiness.data?.components ?? []).map((c) => (
                <Stack key={c.name} direction="row" alignItems="center" spacing={1}>
                  <StatusIcon status={c.status} />
                  <Typography variant="body2" sx={{ flex: 1, textTransform: 'capitalize' }}>
                    {c.name}
                  </Typography>
                  <Typography variant="caption" className="le-mono" color="text.secondary">
                    {c.status === 'up' ? t('Up') : c.status === 'down' ? t('Down') : c.status === 'degraded' ? t('Degraded') : t('Skipped')}
                    {c.latency_ms !== null ? ` · ${c.latency_ms < 1 ? c.latency_ms.toFixed(2) : c.latency_ms.toFixed(1)} ms` : ''}
                  </Typography>
                </Stack>
              ))}
              {readiness.isError && (
                <Typography variant="caption" color="var(--status-error)">
                  {t('The server did not answer the readiness check.')}
                </Typography>
              )}
            </Stack>
            <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mt: 1.5 }}>
              <Chip size="small" variant="outlined" label={`${t('Detection')}: ${deviceWord}`} />
              {(detection.data?.models ?? []).map((m) => (
                <Chip key={m} size="small" variant="outlined" label={m} sx={{ fontFamily: 'var(--font-mono)' }} />
              ))}
            </Stack>
          </Panel>

          <Panel
            title={t('Offline imagery')}
            action={
              <Button size="small" onClick={() => navigate('/monitor')}>
                {t('Cache an area')}
              </Button>
            }
          >
            <Stack direction="row" spacing={3}>
              <Box>
                <Typography className="le-mono" sx={{ fontSize: 20, fontWeight: 700, lineHeight: 1.1 }}>
                  {(manifests.data ?? []).length}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {t('cached areas')}
                </Typography>
              </Box>
              <Box>
                <Typography className="le-mono" sx={{ fontSize: 20, fontWeight: 700, lineHeight: 1.1 }}>
                  {cachedTiles.toLocaleString()}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {t('tiles on disk')}
                </Typography>
              </Box>
            </Stack>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1.25 }}>
              {t('Areas are cached from the globe on the monitoring page: draw the area, pick the zoom band, download.')}
            </Typography>
          </Panel>
        </Box>
      </Box>
    </Box>
  );
}

export default DashboardPage;
