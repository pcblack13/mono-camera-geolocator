/**
 * `monitor/globe/CameraGridView.tsx` — the fleet as a WALL of live tiles.
 *
 * ★ THE OTHER HALF OF /monitor (2026-09-02, owner ask, after trafficvision.live):
 *   the globe answers "where are my cameras", the grid answers "what do they see
 *   RIGHT NOW" — every camera as a card with its live picture, its name in mono,
 *   and a small spec block (GEO · connection · what it provides), exactly the
 *   reading a wall of traffic cams gives.
 *
 * ★ THE TILES ARE PROBES. Each streaming tile reports what happened to its
 *   picture into the registry's transient statuses — the same store the globe's
 *   markers paint — so flipping to the globe shows what the grid just learned.
 *
 * ★ A DATA-ONLY integration (serial/UART, a Pi sending detections) has no
 *   picture to show; its tile says so honestly and still opens its monitor page,
 *   where the marks land on the map.
 */

import { useEffect, useMemo, useRef, useState, type JSX } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { keyframes } from '@mui/system';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import InputAdornment from '@mui/material/InputAdornment';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import ToggleButton from '@mui/material/ToggleButton';
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup';
import Typography from '@mui/material/Typography';
import PlayArrowRoundedIcon from '@mui/icons-material/PlayArrowRounded';
import StopRoundedIcon from '@mui/icons-material/StopRounded';
import CableOutlinedIcon from '@mui/icons-material/CableOutlined';
import RouterOutlinedIcon from '@mui/icons-material/RouterOutlined';
import SearchIcon from '@mui/icons-material/Search';
import SensorsOutlinedIcon from '@mui/icons-material/SensorsOutlined';
import UsbIcon from '@mui/icons-material/Usb';
import VideocamOffOutlinedIcon from '@mui/icons-material/VideocamOffOutlined';
import DirectionsCarIcon from '@mui/icons-material/DirectionsCar';
import DirectionsWalkIcon from '@mui/icons-material/DirectionsWalk';
import LocalShippingIcon from '@mui/icons-material/LocalShipping';
import DirectionsBusIcon from '@mui/icons-material/DirectionsBus';
import TwoWheelerIcon from '@mui/icons-material/TwoWheeler';
import PedalBikeIcon from '@mui/icons-material/PedalBike';
import PriorityHighIcon from '@mui/icons-material/PriorityHigh';
import type { SvgIconComponent } from '@mui/icons-material';

import { API_BASE_URL } from '../../../api/client';
import { detectionApi, type DetectionSession } from '../../../api/detection';
import { previewSrcForSource } from '../../../hooks/useLiveFeed';
import { selectSettingsFor, useMonitorSettingsStore } from '../../../store/monitorSettingsStore';
import { useDataFeedStatus } from '../../../hooks/useDataFeedStatus';
import { useNotify } from '../../common/Notifications';
import {
  selectCameraStatus,
  useCameraRegistryStore,
  type CameraConnection,
  type RegisteredCamera,
} from '../../../store/cameraRegistryStore';
import { matchesFilter, statusOf, type CameraFilter } from '../cameraFilter';
import { MEDIA_WELL, ON_MEDIA } from '../../../theme/paint';
import { t } from '../../../i18n';

export interface CameraGridViewProps {
  cameras: RegisteredCamera[];
  onOpen: (id: string) => void;
}

// ★ The wall keeps its short labels (the monitoring page is unchanged, 2026-09-04).
const CONNECTION_LABEL: Record<CameraConnection, string> = {
  lan: 'LAN',
  usb: 'USB',
  serial: 'Serial / UART',
};

const CONNECTION_ICON: Record<CameraConnection, JSX.Element> = {
  lan: <RouterOutlinedIcon sx={{ fontSize: 13 }} />,
  usb: <UsbIcon sx={{ fontSize: 13 }} />,
  serial: <CableOutlinedIcon sx={{ fontSize: 13 }} />,
};

// ★ DETECTION ALERTS (2026-09-03, owner ask). On the wall, each detecting tile
//   flashes a plain monochrome icon of WHAT it is seeing right now — a walking
//   figure for a person, a car for a car — so the operator watching many tiles
//   is alerted at a glance. Icons (not emoji) so they render as one blank colour.
const CLASS_ICON: Record<string, SvgIconComponent> = {
  person: DirectionsWalkIcon,
  car: DirectionsCarIcon,
  motorcycle: TwoWheelerIcon,
  bus: DirectionsBusIcon,
  truck: LocalShippingIcon,
  bicycle: PedalBikeIcon,
};

const alertPulse = keyframes`
  0%   { opacity: 0.2;  transform: scale(0.82); }
  50%  { opacity: 1;    transform: scale(1.1); }
  100% { opacity: 0.2;  transform: scale(0.82); }
`;

/** The pulsing icon of what a tile is detecting RIGHT NOW.
 *
 * ★ A class whose cumulative count ROSE since the last wall poll is being
 *   detected now — its icon appears and pulses (the alert). When the class stops
 *   being seen, its count stops rising and the icon disappears. Driven by the
 *   session's `counts` the wall already polls; no extra request.
 */
function TileDetectionAlerts({
  counts,
}: {
  counts: Record<string, number> | undefined;
}): JSX.Element | null {
  const prev = useRef<Record<string, number>>({});
  const [active, setActive] = useState<string[]>([]);
  useEffect(() => {
    const c = counts ?? {};
    const rising = Object.keys(c).filter((cls) => c[cls] > (prev.current[cls] ?? 0));
    prev.current = { ...c };
    // Only update when the active SET changes, so a steady detection keeps its
    // smooth pulse instead of restarting every poll.
    setActive((old) =>
      old.length === rising.length && old.every((x) => rising.includes(x)) ? old : rising,
    );
  }, [counts]);
  if (active.length === 0) return null;
  return (
    <Stack
      direction="row"
      spacing={0.5}
      // ★ Bottom-right of the tile media (owner ask 2026-09-03).
      sx={{ position: 'absolute', bottom: 8, insetInlineEnd: 8, pointerEvents: 'none', zIndex: 1 }}
    >
      {active.slice(0, 4).map((cls) => {
        const Icon = CLASS_ICON[cls] ?? PriorityHighIcon;
        return (
          <Box
            key={cls}
            title={cls}
            aria-label={`${t('detecting')}: ${cls}`}
            sx={{
              width: 30,
              height: 30,
              borderRadius: '50%',
              display: 'grid',
              placeItems: 'center',
              bgcolor: 'var(--scrim-hud)',
              animation: `${alertPulse} 1.1s ease-in-out infinite`,
            }}
          >
            <Icon sx={{ fontSize: 18, color: ON_MEDIA }} />
          </Box>
        );
      })}
    </Stack>
  );
}

/** One spec row — label in dim mono, value beside it, trafficvision-style. */
function SpecRow({
  label,
  children,
}: {
  label: string;
  children: JSX.Element | string;
}): JSX.Element {
  return (
    <Stack direction="row" spacing={1} alignItems="baseline" sx={{ minWidth: 0 }}>
      <Typography
        className="le-mono"
        sx={{
          fontSize: 10,
          color: 'text.disabled',
          width: 44,
          flexShrink: 0,
          textTransform: 'uppercase',
        }}
      >
        {label}
      </Typography>
      <Typography
        className="le-mono"
        component="div"
        sx={{
          fontSize: 11,
          minWidth: 0,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {children}
      </Typography>
    </Stack>
  );
}

function CameraTile({
  camera,
  onOpen,
  session,
  onSessionsChanged,
}: {
  camera: RegisteredCamera;
  onOpen: (id: string) => void;
  /** This camera's RUNNING detection session, when one is on (from the wall poll). */
  session?: DetectionSession;
  onSessionsChanged: () => void;
}): JSX.Element {
  const setStatus = useCameraRegistryStore((s) => s.setStatus);
  const notify = useNotify();
  // ★ ONE CLICK, THE SAVED SETUP (2026-09-02): starting from the wall uses the
  //   camera's remembered dials — the same ones the camera page saved on Apply.
  const saved = useMonitorSettingsStore(selectSettingsFor(camera.id));
  const [busy, setBusy] = useState(false);
  const detecting = session !== undefined;
  const toggleDetection = (): void => {
    if (busy) return;
    setBusy(true);
    const done = (): void => {
      setBusy(false);
      onSessionsChanged();
    };
    if (session !== undefined) {
      detectionApi
        .stop(session.session_id)
        .then(done)
        .catch((e) => {
          notify(e instanceof Error ? e.message : String(e), { severity: 'error' });
          done();
        });
    } else {
      detectionApi
        .start({
          source: camera.source,
          lut_site: saved?.lutSite ? saved.lutSite : null,
          conf: saved?.conf ?? 0.25,
          imgsz: saved?.imgszChoice ?? 480,
          model: saved?.model ? saved.model : null,
          // ★ Manual tracking only — never auto-lock (2026-09-03). A pre-change
          //   saved setup may carry a nonzero trackerStart; ignore it here.
          tracker_start_frame: 0,
          tracker_type: saved?.trackerType ?? 'vit',
          classes: saved !== undefined && saved.classes.length > 0 ? saved.classes : null,
          steady_boxes: saved?.steadyBoxes ?? true,
        })
        .then(done)
        .catch((e) => {
          notify(e instanceof Error ? e.message : String(e), { severity: 'error' });
          done();
        });
    }
  };
  const status = useCameraRegistryStore(selectCameraStatus(camera.id));
  const provides = camera.provides ?? 'camera';
  const connection = camera.connection ?? 'lan';
  const hasVideo = provides !== 'data' && camera.source !== '';
  // ★ A data tile has no picture to probe, so it asks the feed instead — else the
  //   wall would count a working board as unknown. See `useDataFeedStatus`.
  useDataFeedStatus(camera.id, camera.data_source ?? null, provides !== 'camera');
  // ★ The <img> IS the probe: first frame = live, an error = lost. `seq` remounts
  //   the stream on retry — an MJPEG <img> that errored never recovers by itself.
  const [seq, setSeq] = useState(0);
  const [tileState, setTileState] = useState<'connecting' | 'live' | 'lost'>('connecting');
  // ★ CANCEL THE STREAM ON UNMOUNT (2026-09-02). A removed <img> can keep its
  //   MJPEG download alive as a zombie — Chromium does not reliably abort it —
  //   and a zombie of a DEVICE source holds the camera against the very page
  //   the click navigated to. Blanking src is the documented way to cancel.
  const imgRef = useRef<HTMLImageElement | null>(null);
  useEffect(() => {
    // Captured NOW: React nulls the ref before passive cleanups run on unmount,
    // so the closure must hold the element itself. Keyed on `seq`, the cleanup
    // also cancels the OLD stream when Retry swaps in a fresh one.
    const img = imgRef.current;
    return () => {
      if (img) img.src = '';
    };
  }, [seq]);

  const dot =
    tileState === 'live' || (!hasVideo && status.state === 'live')
      ? 'var(--status-ok)'
      : tileState === 'lost'
        ? 'var(--status-error)'
        : 'var(--status-warn)';

  return (
    <Box
      component="button"
      type="button"
      onClick={() => onOpen(camera.id)}
      aria-label={`${t('Open')} ${camera.name}`}
      sx={{
        'all': 'unset',
        'cursor': 'pointer',
        'display': 'flex',
        'flexDirection': 'column',
        'borderRadius': 1.5,
        'overflow': 'hidden',
        'border': '1px solid var(--hairline)',
        'bgcolor': 'var(--bg-elevated)',
        'transition': 'border-color 120ms',
        '&:hover': { borderColor: 'var(--accent)' },
        '&:focus-visible': { outline: '2px solid var(--accent)' },
      }}
    >
      {/* ── the picture (or the honest absence of one) ── */}
      <Box sx={{ position: 'relative', aspectRatio: '16 / 9', bgcolor: MEDIA_WELL, width: '100%' }}>
        {hasVideo ? (
          <>
            <Box
              key={`${seq}:${session?.session_id ?? 'preview'}`}
              ref={imgRef}
              component="img"
              src={
                detecting
                  ? `${API_BASE_URL}/detection/sessions/${session.session_id}/stream`
                  : previewSrcForSource(camera.source)
              }
              alt=""
              onLoad={() => {
                setTileState('live');
                setStatus(camera.id, 'live');
              }}
              onError={() => {
                setTileState('lost');
                setStatus(camera.id, 'lost');
              }}
              sx={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
            />
            {tileState !== 'live' && (
              <Box
                sx={{
                  position: 'absolute',
                  inset: 0,
                  display: 'grid',
                  placeItems: 'center',
                  color: ON_MEDIA,
                }}
              >
                <Typography className="le-mono" sx={{ fontSize: 11, letterSpacing: 2 }}>
                  {tileState === 'lost' ? t('SIGNAL LOST') : t('CONNECTING…')}
                </Typography>
                {tileState === 'lost' && (
                  <Button
                    size="small"
                    variant="outlined"
                    onClick={(e) => {
                      e.stopPropagation();
                      setTileState('connecting');
                      setSeq((n) => n + 1);
                    }}
                    sx={{ position: 'absolute', bottom: 8 }}
                  >
                    {t('Retry')}
                  </Button>
                )}
              </Box>
            )}
          </>
        ) : (
          <Stack
            spacing={0.5}
            alignItems="center"
            justifyContent="center"
            sx={{ position: 'absolute', inset: 0, color: 'text.disabled' }}
          >
            {provides === 'data' ? (
              <SensorsOutlinedIcon sx={{ fontSize: 34 }} />
            ) : (
              <VideocamOffOutlinedIcon sx={{ fontSize: 34 }} />
            )}
            <Typography className="le-mono" sx={{ fontSize: 10.5, letterSpacing: 1.5 }}>
              {provides === 'data' ? t('DATA FEED — NO PICTURE') : t('NO PREVIEW')}
            </Typography>
          </Stack>
        )}
        {/* ★ Emoji alerts of what this tile is detecting right now (2026-09-03). */}
        {detecting && <TileDetectionAlerts counts={session.counts} />}
        {/* status LED + provides badges, over the media */}
        <Stack
          direction="row"
          spacing={0.5}
          sx={{ position: 'absolute', top: 6, insetInlineEnd: 6, alignItems: 'center' }}
        >
          {detecting && (
            <Chip
              size="small"
              label={`${t('DETECTING')} · ${session.marks_total} · ${session.fps.toFixed(0)} fps`}
              sx={{
                height: 18,
                fontSize: 9.5,
                bgcolor: 'var(--status-busy)',
                color: 'var(--text-inverse)',
              }}
            />
          )}
          {(provides === 'data' || provides === 'both') && (
            <Chip
              size="small"
              label={t('DATA')}
              sx={{ height: 18, fontSize: 9.5, bgcolor: 'var(--accent-quiet)' }}
            />
          )}
          <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: dot, boxShadow: 1 }} />
        </Stack>
      </Box>

      {/* ── the spec block ── */}
      <Stack spacing={0.25} sx={{ p: 1.25, width: '100%', boxSizing: 'border-box' }}>
        <Typography className="le-mono" sx={{ fontSize: 12.5, fontWeight: 700 }} noWrap>
          {camera.name}
        </Typography>
        <SpecRow label={t('geo')}>
          <span dir="ltr">
            {camera.lat.toFixed(5)}, {camera.lon.toFixed(5)}
          </span>
        </SpecRow>
        <SpecRow label={t('via')}>
          <Stack direction="row" spacing={0.5} alignItems="center" component="span">
            {CONNECTION_ICON[connection]}
            <span>{t(CONNECTION_LABEL[connection])}</span>
          </Stack>
        </SpecRow>
        <SpecRow label={t('feeds')}>
          {provides === 'both'
            ? t('camera + detection data')
            : provides === 'data'
              ? t('detection data')
              : t('camera')}
        </SpecRow>
        {hasVideo && (
          <Button
            size="small"
            variant={detecting ? 'contained' : 'outlined'}
            color={detecting ? 'warning' : 'primary'}
            startIcon={detecting ? <StopRoundedIcon /> : <PlayArrowRoundedIcon />}
            disabled={busy}
            onClick={(e) => {
              // The tile navigates; this button must not.
              e.stopPropagation();
              toggleDetection();
            }}
            sx={{ mt: 0.75, alignSelf: 'flex-start' }}
          >
            {busy ? t('…') : detecting ? t('Stop detection') : t('Start detection')}
          </Button>
        )}
      </Stack>
    </Box>
  );
}

export function CameraGridView({ cameras, onOpen }: CameraGridViewProps): JSX.Element {
  const [query, setQuery] = useState('');
  // ★ The tiles themselves write these: each one probes its stream and records
  //   live / lost in the registry, so the filter reads what the wall is seeing.
  const [filter, setFilter] = useState<CameraFilter>('all');
  const statuses = useCameraRegistryStore((s) => s.statuses);
  const queryClient = useQueryClient();
  // ★ ONE poll answers "who is detecting" for the whole wall (2 s cadence —
  //   the tiles' own MJPEG streams carry the live picture; this only flips
  //   badges and buttons).
  const sessions = useQuery({
    queryKey: ['detection', 'sessions', 'wall'],
    queryFn: ({ signal }) => detectionApi.list(signal),
    refetchInterval: 2000,
  });
  const sessionBySource = useMemo(() => {
    const map = new Map<string, DetectionSession>();
    for (const s of sessions.data?.items ?? []) {
      if ((s.status === 'starting' || s.status === 'running') && !map.has(s.source)) {
        map.set(s.source, s);
      }
    }
    return map;
  }, [sessions.data]);
  const onSessionsChanged = (): void => {
    void queryClient.invalidateQueries({ queryKey: ['detection', 'sessions', 'wall'] });
  };
  const q = query.trim().toLowerCase();
  const shown = cameras.filter((c) => {
    if (!matchesFilter(statusOf(statuses, c.id), filter)) return false;
    if (q === '') return true;
    return (
      c.name.toLowerCase().includes(q) ||
      (c.tags ?? []).some((tag) => tag.toLowerCase().includes(q))
    );
  });

  return (
    <Box sx={{ position: 'absolute', inset: 0, overflowY: 'auto', bgcolor: 'var(--bg-canvas)' }}>
      <Box sx={{ p: 2, maxWidth: 1720, mx: 'auto' }}>
        <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 2 }}>
          <TextField
            size="small"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t('Search cameras')}
            inputProps={{ 'aria-label': t('Search cameras') }}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <SearchIcon fontSize="small" />
                </InputAdornment>
              ),
            }}
            sx={{ width: 280 }}
          />
          <ToggleButtonGroup
            exclusive
            size="small"
            value={filter}
            onChange={(_e, v: CameraFilter | null) => {
              if (v !== null) setFilter(v);
            }}
            aria-label={t('Show')}
          >
            <ToggleButton value="all">{t('All')}</ToggleButton>
            <ToggleButton value="live">{t('Live')}</ToggleButton>
            <ToggleButton value="lost">{t('Lost')}</ToggleButton>
          </ToggleButtonGroup>
          <Typography className="le-mono" sx={{ fontSize: 11, color: 'text.secondary', flex: 1 }}>
            {shown.length} / {cameras.length} {t('cameras')}
          </Typography>
        </Stack>

        {shown.length === 0 ? (
          <Typography variant="body2" color="text.secondary" sx={{ py: 6, textAlign: 'center' }}>
            {cameras.length === 0
              ? t('No cameras yet — register one in the camera workspace.')
              : q === ''
                ? // ★ The filter emptied the wall, not the search — say which.
                  filter === 'live'
                  ? t('No camera is live right now.')
                  : t('No camera is lost right now.')
                : t('Nothing matches the search.')}
          </Typography>
        ) : (
          <Box
            sx={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
              gap: 1.5,
            }}
          >
            {shown.map((c) => (
              <CameraTile
                key={c.id}
                camera={c}
                onOpen={onOpen}
                session={sessionBySource.get(c.source)}
                onSessionsChanged={onSessionsChanged}
              />
            ))}
          </Box>
        )}
      </Box>
    </Box>
  );
}
