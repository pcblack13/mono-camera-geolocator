/**
 * `live/LiveStreamTab.tsx` — the Live stream page: watch, measure, capture.
 *
 * ★ ITS OWN WORKSPACE PAGE now (split out of the Video editor): a live camera is a
 *   standing instrument, not a file — it earns a rail entry.
 *
 * ★ THE PLAYER READS THE STREAM ITSELF when it can: http(s) MJPEG is fetched and
 *   parsed frame-by-frame (JPEG SOI/EOI scan) onto a canvas, which is what makes
 *   the FPS a MEASURED number — frames actually decoded per second — never a guess.
 *   When the source refuses cross-origin reads, the player falls back to a plain
 *   `<img>` (browsers render MJPEG natively there) and the stats panel says
 *   honestly that FPS is not measurable for this source.
 *
 * ★ EVERYTHING ELSE GOES THROUGH THE SERVER'S RE-STREAM (`GET /live/stream`):
 *   RTSP cameras, and LOCAL capture devices — HDMI capture cards and USB/USB-C
 *   cameras, which the OS presents as `/dev/videoN` (Linux) / DirectShow devices
 *   (Windows). The backend opens them with OpenCV and re-serves http MJPEG, so
 *   the same canvas player (and the same measured FPS) works for all of them.
 *   Devices are listed by `GET /live/devices` on the explicit "Scan" button —
 *   probing opens hardware briefly, so it never runs on a timer.
 *
 * ★ THE DETECTIONS PANEL IS STRUCTURED, NOT SIMULATED: it renders one labeled
 *   entity per detected class (name + live count) from a typed record — which is
 *   exactly what the planned YOLO integration will feed. Until that exists the
 *   panel says "no detector connected" rather than inventing objects (SCOPE.md §4
 *   rule 4: deferred features are visible, disabled, and honest).
 */

import { useCallback, useEffect, useRef, useState, type JSX } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Chip from '@mui/material/Chip';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import Divider from '@mui/material/Divider';
import IconButton from '@mui/material/IconButton';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import AddIcon from '@mui/icons-material/Add';
import CameraAltOutlinedIcon from '@mui/icons-material/CameraAltOutlined';
import CloseIcon from '@mui/icons-material/Close';
import FolderOpenOutlinedIcon from '@mui/icons-material/FolderOpenOutlined';
import FullscreenIcon from '@mui/icons-material/Fullscreen';
import FullscreenExitIcon from '@mui/icons-material/FullscreenExit';
import RefreshIcon from '@mui/icons-material/Refresh';
import SensorsIcon from '@mui/icons-material/Sensors';
import UsbIcon from '@mui/icons-material/Usb';
import VideocamOutlinedIcon from '@mui/icons-material/VideocamOutlined';
import PlaceOutlinedIcon from '@mui/icons-material/PlaceOutlined';
import UsbOffIcon from '@mui/icons-material/UsbOff';

import { lazy, Suspense, useMemo } from 'react';
import Skeleton from '@mui/material/Skeleton';
import { API_BASE_URL } from '../../api/client';
import { lutApi } from '../../api/lut';
import { qk } from '../../api/queryKeys';
import { useProviders } from '../../api/hooks';
import { useMapStore } from '../../store';
import { DetectionSettingsBar } from '../detection/DetectionSettingsBar';
import { DriftSection } from '../drift/DriftSection';
import { DriftMapBanner } from '../drift/DriftMapBanner';
import { DriftOverlay } from '../drift/DriftOverlay';
import type { DriftVerdict } from '../../api/drift';

// Leaflet is heavy and most live sessions never detect — pay for it on first use.
const LiveMarksMap = lazy(() => import('./LiveMarksMap'));
import { DetectionSessionPanel } from './DetectionSessionPanel';
import { StreamImage } from './StreamImage';
import { useDetectionAvailability, useLiveDetection } from '../../api/hooks/useDetection';
import { useSurvivingState } from '../../lib/survivingState';
import { liveApi, type LiveCaptureOptions, type LiveDeviceInfo } from '../../api/live';
import {
  hostOf,
  looksLikeStreamUrl,
  previewSrcFor,
  useLiveFeed,
  type ActiveSource,
  type StreamStats,
} from '../../hooks/useLiveFeed';
import { captureLibraryApi, type CaptureLibraryEntry } from '../../api/captureLibrary';
import { hasNativeDirectoryPicker, pickDirectoryNative } from '../../lib/nativeFilePicker';
import { ApiError } from '../../types/common';
import { useLiveSourcesStore } from '../../store/liveSourcesStore';
import { useNotify } from '../common/Notifications';
import { useT } from '../../i18n';
import { StatReadout } from '../ui';

// ─────────────────────────────────────────────────────────────────────────────
// Source rules + the MJPEG reader — moved to `hooks/useLiveFeed` (the globe's
// per-camera page runs the same state machine); re-exported so the tests and any
// caller that imported them from here keep working.
// ─────────────────────────────────────────────────────────────────────────────

export {
  canPreviewInBrowser,
  hostOf,
  looksLikeStreamUrl,
  previewSrcFor,
  type ActiveSource,
  type StreamStats,
} from '../../hooks/useLiveFeed';

/** Live counts per detected class — `{ person: 3, car: 1 }`. Empty = no detector. */
export type DetectionCounts = Record<string, number>;

// ─────────────────────────────────────────────────────────────────────────────
// Stats + detections panel
// ─────────────────────────────────────────────────────────────────────────────

// Phase 5: the local row gives way to the StatReadout primitive — same shape,
// plus the system's rules (tabular mono, em-dash for nothing).
const StatRow = StatReadout;

export function LiveStatsPanel({
  stats,
  fpsMeasurable,
  detections,
}: {
  stats: StreamStats;
  fpsMeasurable: boolean;
  detections: DetectionCounts;
}): JSX.Element {
  const t = useT();
  const classes = Object.entries(detections).sort(([, a], [, b]) => b - a);
  const uptime =
    stats.startedAt === null
      ? '—'
      : `${Math.max(0, Math.round((Date.now() - stats.startedAt) / 1000))} s`;
  return (
    <Card variant="outlined" sx={{ width: '100%', borderRadius: 2 }}>
      <CardContent>
        <Typography variant="subtitle2" sx={{ mb: 1 }}>
          {t('Stream statistics')}
        </Typography>
        <StatRow
          label={t('FPS')}
          value={
            !fpsMeasurable ? t('not measurable') : stats.fps === null ? '—' : stats.fps.toFixed(1)
          }
        />
        <StatRow
          label={t('Encoding')}
          // null in <img> fallback mode — the browser renders without showing us
          // headers, so "unknown" is the honest word there, never a guess.
          value={stats.encoding ?? (fpsMeasurable ? '—' : 'unknown')}
        />
        <StatRow
          label={t('Resolution')}
          value={stats.width && stats.height ? `${stats.width}×${stats.height}` : '—'}
        />
        <StatRow
          label={t('Frames received')}
          value={stats.frames > 0 ? String(stats.frames) : '—'}
        />
        <StatRow label={t('Uptime')} value={uptime} />

        <Divider sx={{ my: 1.5 }} />

        <Typography variant="subtitle2" sx={{ mb: 1 }}>
          {t('Detected objects')}
        </Typography>
        {classes.length === 0 ? (
          <Typography variant="caption" color="text.secondary">
            {t(
              'No detector connected — YOLO object detection is planned. Detected classes will appear here, one labeled counter per class.',
            )}
          </Typography>
        ) : (
          <Stack direction="row" sx={{ flexWrap: 'wrap', gap: 0.75 }}>
            {classes.map(([cls, count]) => (
              <Chip key={cls} size="small" variant="outlined" label={`${cls}: ${count}`} />
            ))}
          </Stack>
        )}
      </CardContent>
    </Card>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// The page
// ─────────────────────────────────────────────────────────────────────────────

export function LiveStreamTab(): JSX.Element {
  const t = useT();
  const notify = useNotify();
  const sources = useLiveSourcesStore((s) => s.sources);
  const addSource = useLiveSourcesStore((s) => s.add);
  const removeSource = useLiveSourcesStore((s) => s.remove);

  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [active, setActive] = useState<ActiveSource | null>(null);
  const [fullscreen, setFullscreen] = useState(false);

  // ── local devices (HDMI capture cards, USB/USB-C cameras) ────────────────
  const [devices, setDevices] = useState<LiveDeviceInfo[]>([]);
  const [scanning, setScanning] = useState(false);
  const [scanned, setScanned] = useState(false);

  const scanDevices = useCallback(() => {
    setScanning(true);
    liveApi
      .listDevices()
      .then((page) => {
        setDevices(page.items);
        setScanned(true);
      })
      .catch((err) => {
        notify(err instanceof ApiError ? err.message : String(err), { severity: 'error' });
      })
      .finally(() => setScanning(false));
  }, [notify]);

  const playerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  // ★ The YOLO feed is REAL now. Counts come from the session; the placeholder
  //   `DetectionCounts` contract this panel declared is exactly what it fills.
  const detection = useLiveDetection('live');
  const detecting =
    detection.session !== null &&
    (detection.session.status === 'starting' || detection.session.status === 'running');

  // ★ THE PREVIEW MUST LET GO OF THE CAMERA, NOT JUST LEAVE THE SCREEN.
  //   A USB camera admits ONE opener, and this preview holds it by keeping a
  //   `GET /live/stream` request open — through a FETCH inside `useMjpegCanvas`,
  //   which is driven by this url and knows nothing about which element renders.
  //   Swapping the picture for the detector's therefore released nothing: the
  //   fetch kept reading, the server kept the device, and every one of the run's
  //   retries lost to it. Passing null here aborts that fetch, which is what
  //   actually frees the camera for the detector.
  // ★ …and released the moment a run is STARTING, not once it has started: the
  //   detector opens the device during the POST, and the preview must be gone by then.
  const streamUrl =
    active !== null && !detecting && !detection.starting ? previewSrcFor(active) : null;
  const { mode, stats, reconnect, streamError, formatWarning, reportImgFailed, imgFailed } =
    useLiveFeed(streamUrl, canvasRef);
  /**
   * One verdict for both player modes: the picture on screen is NOT live.
   * ★ A server REFUSAL is excluded — it never connected, so "disconnected" would
   *   be the wrong word and would bury the reason the server actually gave.
   */
  const refused = streamError !== null;
  const disconnected = !refused && (mode === 'lost' || (mode === 'img' && imgFailed));

  const detectionAvailability = useDetectionAvailability();
  // ★ THE RUN'S SETTINGS LIVE HERE NOW, not inside a popover — the bar above the
  //   panels is the same control on both detection pages.
  //   SURVIVING, not useState: a language switch remounts the tree, and these dials
  //   plus the run in flight are the surveyor's work — see lib/survivingState.
  const [detModel, setDetModel] = useSurvivingState('detection.live.model', '');
  const [detLut, setDetLut] = useSurvivingState('detection.live.lutSite', '');
  const [detConf, setDetConf] = useSurvivingState('detection.live.conf', 0.25);
  const [detImgszChoice, setDetImgszChoice] = useSurvivingState<number | null>(
    'detection.live.imgsz',
    null,
  );
  const [detTrackerStart, setDetTrackerStart] = useSurvivingState('detection.live.trackerStart', 0);
  const [detTrackerType, setDetTrackerType] = useSurvivingState(
    'detection.live.trackerType',
    'vit',
  );
  const [detClasses, setDetClasses] = useSurvivingState<number[]>('detection.live.classes', []);
  // ★ What the CONTROLS hold vs what the PANELS show — the Video detection page's
  //   split, for the same reason: the map must not jump between sites while
  //   someone is still reading the list of tables. The camera needs no applying,
  //   so here the split covers the lookup table alone.
  const [appliedLut, setAppliedLut] = useSurvivingState('detection.live.appliedLut', '');
  const detDirty = appliedLut !== detLut;
  // The drift watch's freshest verdict — the map banner renders from it.
  const [driftVerdict, setDriftVerdict] = useState<DriftVerdict | null>(null);
  // Also queried by the settings bar; React Query dedupes the two by key.
  const lutLibrary = useQuery({
    queryKey: qk.lut.library(),
    queryFn: ({ signal }) => lutApi.library(signal),
  });
  const detOnCpu = detectionAvailability.data?.device === 'cpu';
  const detImgsz = detImgszChoice ?? (detOnCpu ? 480 : 640);
  const detector = detectionAvailability.data?.detector;
  const detDisabledReason =
    detector == null
      ? 'Checking what this machine can run…'
      : !detector.available
        ? (detector.reason ?? 'the detection runtime is not available.')
        : active === null
          ? 'Start a stream first — detection runs on the live picture.'
          : null;
  const startDetection = (): void => {
    if (active === null) return;
    setAppliedLut(detLut);
    detection.start({
      source: active.src,
      lut_site: detLut || null,
      conf: detConf,
      imgsz: detImgsz,
      model: detModel || null,
      tracker_start_frame: detTrackerStart,
      tracker_type: detTrackerType,
      classes: detClasses.length > 0 ? detClasses : null,
    });
  };
  const providersQuery = useProviders();
  const chosenProviderId = useMapStore((st) => st.providerId);
  // ★ THE SAME PROVIDER AS EVERY OTHER MAP — the picking page's rule, verbatim:
  //   the user's persisted choice if it is still USABLE, else the server default,
  //   else the first. The first version took the first `configured !== false` item,
  //   which on some servers is a banned provider — every tile then came back as the
  //   proxy's "Map data not yet available" placeholder and the map read as broken.
  const mapProvider = useMemo(() => {
    const items = providersQuery.data?.items ?? [];
    const byChoice = chosenProviderId ? items.find((p) => p.name === chosenProviderId) : undefined;
    const usable =
      byChoice && byChoice.configured && byChoice.allowed !== false ? byChoice : undefined;
    return usable ?? items.find((p) => p.is_default) ?? items[0];
  }, [providersQuery.data, chosenProviderId]);
  // ★ Fixed per session — the LUT's own centre. Never recomputed from marks, so the
  //   map is aimed once and then belongs to the user (see CenterOnce).
  const sessionCenter = useMemo((): [number, number] | null => {
    const c = detection.session?.lut_summary?.center;
    return Array.isArray(c) && c.length === 2 ? [Number(c[0]), Number(c[1])] : null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detection.session?.session_id]);

  // The chosen table's own site, so the map opens BEFORE anything runs. A live
  // run's own centre wins — that is the table it actually loaded.
  const appliedLutCenter = useMemo((): [number, number] | null => {
    const entry = (lutLibrary.data ?? []).find((e) => e.site_name === appliedLut);
    const c = entry?.center;
    return Array.isArray(c) && c.length === 2 ? [Number(c[0]), Number(c[1])] : null;
  }, [lutLibrary.data, appliedLut]);

  const marksCenter = sessionCenter ?? appliedLutCenter;
  const detections: DetectionCounts = detection.session === null ? {} : detection.session.counts;
  useEffect(() => {
    const onChange = (): void => setFullscreen(document.fullscreenElement !== null);
    document.addEventListener('fullscreenchange', onChange);
    return () => document.removeEventListener('fullscreenchange', onChange);
  }, []);

  const toggleFullscreen = (): void => {
    if (document.fullscreenElement) {
      void document.exitFullscreen();
    } else if (playerRef.current) {
      void playerRef.current.requestFullscreen();
    }
  };

  // ── capture: name it, optionally save a copy to a chosen folder ───────────
  const [captureOpen, setCaptureOpen] = useState(false);
  const [captureName, setCaptureName] = useState('');
  const [saveDir, setSaveDir] = useState('');
  const [recent, setRecent] = useState<CaptureLibraryEntry[]>([]);

  /** Reload the live-capture strip: capture-library entries named `live_*`. */
  const refreshRecent = useCallback(() => {
    void captureLibraryApi
      .list()
      .then((page) =>
        setRecent(page.items.filter((e) => e.filename.startsWith('live_')).slice(0, 12)),
      )
      .catch(() => {
        /* the strip is a convenience — a listing failure is not worth a toast */
      });
  }, []);

  useEffect(refreshRecent, [refreshRecent]);

  const capture = useMutation({
    // ★ The source rides in the variables: reading `active!` here threw once the
    //   active chip had been deleted with the capture dialog still open.
    mutationFn: ({ source, ...opts }: LiveCaptureOptions & { source: ActiveSource }) =>
      source.kind === 'device'
        ? liveApi.captureDeviceFrame(source.src, opts)
        : liveApi.captureFrame(source.src, opts),
    onSuccess: (frame) => {
      setCaptureOpen(false);
      notify(
        `Frame captured (${frame.width}×${frame.height}) — saved as ${frame.filename}` +
          (frame.saved_to ? ` and copied to ${frame.saved_to}` : '') +
          '. Import it into a project via "From library".',
        { severity: 'success' },
      );
      refreshRecent();
    },
    onError: (err) => {
      notify(err instanceof ApiError ? err.message : String(err), { severity: 'error' });
    },
  });

  const openCaptureDialog = useCallback(() => {
    if (active === null) return;
    // Pre-fill with the source label; the server appends its own timestamp to the
    // filename, so a date here would only duplicate it.
    setCaptureName(active.name);
    setCaptureOpen(true);
  }, [active]);

  const chooseSaveDir = useCallback(() => {
    void pickDirectoryNative().then((dir) => {
      if (dir) setSaveDir(dir);
    });
  }, []);

  const submitCapture = useCallback(() => {
    if (active === null) return;
    capture.mutate({
      source: active,
      name: captureName.trim() || undefined,
      saveDir: saveDir || undefined,
    });
  }, [capture, captureName, saveDir, active]);

  const submitSource = (): void => {
    const trimmedUrl = url.trim();
    if (!looksLikeStreamUrl(trimmedUrl)) return;
    addSource(name.trim() || hostOf(trimmedUrl), trimmedUrl);
    setName('');
    setUrl('');
  };

  return (
    <Box>
      <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mb: 0.5 }}>
        <SensorsIcon color="primary" />
        <Typography variant="h6">{t('Live stream')}</Typography>
      </Stack>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Watch a camera on your network (Raspberry Pi MJPEG, IP camera, RTSP) or a{' '}
        <b>{t('local capture device')}</b> — an HDMI capture card or a USB/USB-C camera plugged into
        this machine — and capture frames from it. Each captured frame lands in the{' '}
        <b>{t('capture library')}</b> {t('and becomes an ordinary photograph in any project.')}
      </Typography>

      {/* ── add / choose a source ─────────────────────────────────────── */}
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ mb: 1.5, maxWidth: 860 }}>
        <TextField
          size="small"
          label={t('Name')}
          value={name}
          onChange={(e) => setName(e.target.value)}
          sx={{ minWidth: 140 }}
        />
        <TextField
          size="small"
          label={t('Stream URL')}
          placeholder="http://raspberrypi.local:8080/?action=stream"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          fullWidth
          error={url.trim() !== '' && !looksLikeStreamUrl(url)}
          helperText={
            url.trim() !== '' && !looksLikeStreamUrl(url)
              ? 'must start with http://, https:// or rtsp://'
              : undefined
          }
        />
        <Button
          variant="outlined"
          startIcon={<AddIcon />}
          onClick={submitSource}
          disabled={!looksLikeStreamUrl(url)}
          sx={{ flexShrink: 0 }}
        >
          {t('Add')}
        </Button>
      </Stack>

      {sources.length > 0 && (
        <Stack direction="row" spacing={1} sx={{ mb: 1.5, flexWrap: 'wrap', rowGap: 1 }}>
          {sources.map((s) => (
            <Chip
              key={s.id}
              icon={<SensorsIcon />}
              label={s.name}
              color={active?.key === s.id ? 'primary' : 'default'}
              variant={active?.key === s.id ? 'filled' : 'outlined'}
              onClick={() => setActive({ key: s.id, kind: 'url', name: s.name, src: s.url })}
              onDelete={() => {
                removeSource(s.id);
                if (active?.key === s.id) setActive(null);
              }}
              deleteIcon={<CloseIcon />}
            />
          ))}
        </Stack>
      )}

      {/* ── local capture devices: HDMI capture cards, USB/USB-C cameras ── */}
      <Stack
        direction="row"
        spacing={1}
        alignItems="center"
        sx={{ mb: 1, flexWrap: 'wrap', rowGap: 1 }}
      >
        <Button
          size="small"
          variant="outlined"
          startIcon={<RefreshIcon />}
          onClick={scanDevices}
          disabled={scanning}
        >
          {scanning ? 'Scanning…' : 'Scan local devices'}
        </Button>
        <Typography variant="caption" color="text.secondary">
          {t('HDMI capture cards and USB/USB-C cameras plugged into this machine.')}
        </Typography>
      </Stack>

      {devices.length > 0 && (
        <Stack direction="row" spacing={1} sx={{ mb: 2, flexWrap: 'wrap', rowGap: 1 }}>
          {devices.map((d) => (
            <Chip
              key={d.id}
              icon={<UsbIcon />}
              label={d.label}
              color={active?.key === d.id ? 'primary' : 'default'}
              variant={active?.key === d.id ? 'filled' : 'outlined'}
              onClick={() => setActive({ key: d.id, kind: 'device', name: d.label, src: d.id })}
            />
          ))}
        </Stack>
      )}
      {scanned && devices.length === 0 && (
        <Typography variant="caption" color="text.secondary" sx={{ mb: 2, display: 'block' }}>
          No capture devices found. An HDMI source needs its capture card connected (and a live
          signal on the HDMI input); a device already in use by another program will not appear.
        </Typography>
      )}

      {/* ── THE DETECTION SETTINGS BAR — above the panels it governs.
          ★ These were a popover over the player until 2026-08-20: a cramped
            column that covered the very picture being configured. Same bar, same
            order, as the Video detection page. */}
      <Box sx={{ mb: 2 }}>
        <DetectionSettingsBar
          value={{
            model: detModel,
            lutSite: detLut,
            classes: detClasses,
            conf: detConf,
            imgsz: detImgsz,
            trackerStart: detTrackerStart,
            trackerType: detTrackerType,
          }}
          onChange={(patch) => {
            if (patch.model !== undefined) setDetModel(patch.model);
            if (patch.lutSite !== undefined) setDetLut(patch.lutSite);
            if (patch.classes !== undefined) setDetClasses(patch.classes);
            if (patch.conf !== undefined) setDetConf(patch.conf);
            if (patch.imgsz !== undefined) setDetImgszChoice(patch.imgsz);
            if (patch.trackerStart !== undefined) setDetTrackerStart(patch.trackerStart);
            if (patch.trackerType !== undefined) setDetTrackerType(patch.trackerType);
          }}
          running={detecting}
          starting={detection.starting}
          disabledReason={detDisabledReason}
          startError={detection.startError}
          onStart={startDetection}
          onStop={detection.stop}
          onRestart={() => {
            detection.stop();
            startDetection();
          }}
          session={detection.session}
          onApply={() => setAppliedLut(detLut)}
          dirty={detDirty}
        />
      </Box>

      {/* ── DRIFT WATCH — a live camera CAN be watched on a clock. While a
          detection run holds the device, the server borrows its frames. */}
      <Box sx={{ mb: 2 }}>
        <DriftSection
          source={active?.src ?? null}
          lutSite={appliedLut}
          live
          onVerdict={setDriftVerdict}
        />
      </Box>

      {/* ── the player + stats ─────────────────────────────────────────────
          ★ ALWAYS MOUNTED (1.2.6). The panel used to appear only once a source was
          chosen, so opening the page showed a bare form and nothing else — the
          player looked missing rather than idle. Now the frame is always here and
          SAYS what it is waiting for. */}
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} sx={{ alignItems: 'stretch' }}>
        {/* ★ THE CAMERA IS THE MAP'S TWIN, not a loose picture with buttons under
            it. It was a bare Box capped at 920 px beside a full-height card, so the
            two panels shared a row at different widths AND different heights, with a
            dead gap under the shorter one. Same card, same header shape, same flex
            share — the row now reads as one pair. */}
        <Card
          variant="outlined"
          sx={{
            flex: 1,
            minWidth: 320,
            display: 'flex',
            flexDirection: 'column',
            borderRadius: 2,
          }}
        >
          <Stack
            direction="row"
            alignItems="center"
            spacing={1}
            sx={{ px: 2, py: 1.25, borderBottom: 1, borderColor: 'divider' }}
          >
            <VideocamOutlinedIcon fontSize="small" color="action" />
            <Typography variant="subtitle2" sx={{ flex: 1 }} noWrap>
              {active?.name ?? 'Live stream'}
            </Typography>
            {/* The controls that act ON the picture live with the picture. */}
            {active !== null && mode === 'img' && !disconnected && (
              <Button size="small" onClick={reconnect}>
                {t('Retry measured mode')}
              </Button>
            )}
            <Button
              size="small"
              variant="contained"
              startIcon={<CameraAltOutlinedIcon />}
              onClick={openCaptureDialog}
              // ★ Nothing to capture with no source, and capturing a DEAD stream
              //   would file a frozen frame as if it were just taken.
              disabled={capture.isPending || active === null || disconnected || refused}
            >
              {capture.isPending ? t('Capturing…') : t('Capture frame')}
            </Button>
          </Stack>
          <Box
            ref={playerRef}
            sx={{
              position: 'relative',
              flex: 1,
              bgcolor: 'black',
              overflow: 'hidden',
              // Fullscreen: let the element fill the screen, letterboxed.
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              minHeight: 400,
            }}
          >
            {/* ★ Every source is previewable now: http MJPEG directly, rtsp and
                  local devices through the server's re-stream (previewSrcFor). */}
            {/* Clip detection lives on its own page now (Workspace → Video
                detection); this player shows only live sources. */}
            {active === null ? (
              // ── IDLE: nothing chosen. State the reason and the next step. ──
              <Stack alignItems="center" spacing={1} sx={{ py: 6, px: 3, textAlign: 'center' }}>
                <UsbIcon sx={{ fontSize: 40, color: 'rgba(255,255,255,0.35)' }} />
                <Typography variant="subtitle2" sx={{ color: 'rgba(255,255,255,0.85)' }}>
                  {scanned
                    ? devices.length > 0
                      ? t('Choose a device above to start the stream')
                      : t('No capture device found')
                    : 'No device scanned yet'}
                </Typography>
                <Typography
                  variant="caption"
                  sx={{ color: 'rgba(255,255,255,0.55)', maxWidth: 460 }}
                >
                  {scanned
                    ? devices.length > 0
                      ? 'The player starts as soon as you select one of the scanned devices.'
                      : 'Connect an HDMI capture card or a USB/USB-C camera and scan again — or add a network stream URL above.'
                    : 'Click “Scan local devices” to find HDMI capture cards and USB/USB-C cameras plugged into this machine, or add a network stream URL above.'}
                </Typography>
                {!scanned && (
                  // ★ Deliberately labelled differently from the toolbar's "Scan
                  //   local devices" — two identically-named buttons on one page
                  //   are ambiguous to a screen reader and to a test.
                  <Button
                    size="small"
                    variant="outlined"
                    startIcon={<RefreshIcon />}
                    onClick={scanDevices}
                    disabled={scanning}
                    sx={{
                      'mt': 1,
                      'color': 'white',
                      'borderColor': 'rgba(255,255,255,0.4)',
                      '&:hover': { borderColor: 'white' },
                    }}
                  >
                    {scanning ? 'Scanning…' : 'Scan now'}
                  </Button>
                )}
              </Stack>
            ) : refused ? (
              // ── REFUSED: it never connected. Say what the server said. ──
              <Stack alignItems="center" spacing={1} sx={{ py: 6, px: 3, textAlign: 'center' }}>
                <UsbOffIcon sx={{ fontSize: 40, color: 'error.light' }} />
                <Typography variant="subtitle2" sx={{ color: 'error.light' }}>
                  {t('This source could not be opened')}
                </Typography>
                <Typography
                  variant="caption"
                  sx={{ color: 'rgba(255,255,255,0.7)', maxWidth: 520 }}
                >
                  {streamError}
                </Typography>
              </Stack>
            ) : disconnected ? (
              // ── DISCONNECTED: the frozen frame is NOT live. Cover it. ──
              <Stack alignItems="center" spacing={1} sx={{ py: 6, px: 3, textAlign: 'center' }}>
                <UsbOffIcon sx={{ fontSize: 40, color: 'warning.light' }} />
                <Typography variant="subtitle2" sx={{ color: 'warning.light' }}>
                  {active.kind === 'device' ? t('Device disconnected') : t('Stream disconnected')}
                </Typography>
                <Typography
                  variant="caption"
                  sx={{ color: 'rgba(255,255,255,0.6)', maxWidth: 460 }}
                >
                  {t('Frames stopped arriving from')} <b>{active.name}</b>
                  {t(
                    '. This is not a delay — the video has stopped. Reconnect the device (or check the camera) and press Reconnect.',
                  )}
                </Typography>
              </Stack>
            ) : detecting && detection.session !== null ? (
              // ★ WHILE DETECTING, THE PANEL WATCHES THE DETECTOR — not the camera.
              //   A V4L2 device admits ONE opener, and re-streaming it here through
              //   `GET /live/stream` is what made the detector's own open fail with
              //   "could not open capture device". Dropping this request releases the
              //   camera to the run; what comes back is the same picture with the
              //   boxes already burned into it, so they can never lag the frame.
              <StreamImage
                src={`${API_BASE_URL}/detection/sessions/${detection.session.session_id}/stream`}
                alt={`Detecting: ${active.name}`}
                style={{ display: 'block', width: '100%', objectFit: 'contain' }}
              />
            ) : mode === 'img' ? (
              // Fallback: the browser renders MJPEG in an <img> even when
              // fetch-reading is blocked. FPS is honestly unmeasurable here.
              <StreamImage
                src={streamUrl ?? ''}
                alt={`Live stream: ${active.name}`}
                style={{ display: 'block', width: '100%', objectFit: 'contain' }}
                // ★ The one disconnect signal available in fallback mode: the
                //   browser tells us the image failed. Same verdict, same words.
                onError={reportImgFailed}
              />
            ) : (
              <canvas
                ref={canvasRef}
                style={{ display: 'block', width: '100%', objectFit: 'contain' }}
                aria-label={`Live stream: ${active.name}`}
              />
            )}

            {/* The detection boxes ride INSIDE the detector's stream above; the
                one overlay drawn here is the drift watch's frozen-view box. */}
            <DriftOverlay verdict={driftVerdict} />

            <Box sx={{ position: 'absolute', top: 8, right: 8, display: 'flex', gap: 0.5 }}>
              {active !== null && mode === 'connecting' && (
                <Chip
                  size="small"
                  label={t('connecting…')}
                  sx={{ bgcolor: 'rgba(0,0,0,0.6)', color: 'white' }}
                />
              )}
              {active !== null && mode === 'canvas' && !disconnected && (
                <Chip size="small" label="LIVE" sx={{ bgcolor: 'success.main', color: 'white' }} />
              )}
              {disconnected && (
                <Chip
                  size="small"
                  label={t('DISCONNECTED')}
                  sx={{ bgcolor: 'warning.main', color: 'black' }}
                />
              )}
              {refused && (
                <Chip
                  size="small"
                  label={t('REFUSED')}
                  sx={{ bgcolor: 'error.main', color: 'white' }}
                />
              )}
              <Tooltip title={fullscreen ? 'Exit fullscreen' : 'Fullscreen'}>
                <IconButton
                  size="small"
                  onClick={toggleFullscreen}
                  aria-label={fullscreen ? 'Exit fullscreen' : 'Fullscreen'}
                  sx={{
                    'bgcolor': 'rgba(0,0,0,0.6)',
                    'color': 'white',
                    '&:hover': { bgcolor: 'rgba(0,0,0,0.8)' },
                  }}
                >
                  {fullscreen ? (
                    <FullscreenExitIcon fontSize="small" />
                  ) : (
                    <FullscreenIcon fontSize="small" />
                  )}
                </IconButton>
              </Tooltip>
            </Box>
          </Box>

          {/* ★ Uncompressed-format note: informational, and only while the
                stream is actually running — it is about picture RATE, not failure. */}
          {formatWarning !== null && !refused && !disconnected && (
            <Alert severity="info" sx={{ mt: 1.5 }}>
              {formatWarning}
            </Alert>
          )}

          {/* ★ The server's refusal, with its own words and a way to retry. */}
          {refused && (
            <Alert
              severity="error"
              sx={{ mt: 1.5 }}
              action={
                <Button
                  color="inherit"
                  size="small"
                  startIcon={<RefreshIcon />}
                  onClick={reconnect}
                >
                  {t('Try again')}
                </Button>
              }
            >
              {streamError}
            </Alert>
          )}

          {/* ★ The disconnect, stated OUTSIDE the black box too — a surveyor
                watching the frame may never look at the overlay chip. */}
          {disconnected && (
            <Alert
              severity="warning"
              sx={{ mt: 1.5 }}
              action={
                <Button
                  color="inherit"
                  size="small"
                  startIcon={<RefreshIcon />}
                  onClick={reconnect}
                >
                  {t('Reconnect')}
                </Button>
              }
            >
              {active?.kind === 'device'
                ? 'The capture device stopped sending frames — it looks unplugged, switched off, or taken over by another program. The video has stopped; this is not a delay.'
                : 'The stream stopped sending frames — the camera or the network connection to it has gone. The video has stopped; this is not a delay.'}
            </Alert>
          )}
        </Card>

        {/* ★ THE MAP IS THE VIDEO'S EQUAL, NOT A THUMBNAIL. The two answer one
            question from two sides — "what does the camera see" and "where is it on
            the ground" — so they share the row at full size. The centre is fixed per
            SESSION (the LUT's own), never derived from a moving mark: the map is the
            user's the moment they touch it. */}
        {/* ★ ALWAYS PRESENT, like the Video detection page. Mounting it only once a
            run was going left the camera panel alone in the row, which reads as a
            broken two-panel layout rather than one that is waiting. */}
        <Card
          variant="outlined"
          sx={{
            flex: 1,
            minWidth: 320,
            display: 'flex',
            flexDirection: 'column',
            borderRadius: 2,
          }}
        >
          {/* Same header shape as the Video detection page's map — one product. */}
          <Stack
            direction="row"
            alignItems="center"
            spacing={1}
            sx={{ px: 2, py: 1.25, borderBottom: 1, borderColor: 'divider' }}
          >
            <PlaceOutlinedIcon fontSize="small" color="action" />
            <Typography variant="subtitle2" sx={{ flex: 1 }}>
              {t('Detected objects on the map')}
            </Typography>
            <Chip
              size="small"
              variant="outlined"
              label={`${detection.marks.length} ${t('marks')}`}
            />
          </Stack>
          <CardContent sx={{ flex: 1, display: 'flex', flexDirection: 'column', p: 2 }}>
            <Box sx={{ flex: 1, minHeight: 400, display: 'flex', position: 'relative' }}>
              {/* fires only on a CONFIRMED MOVED/CHANGED — see DriftMapBanner */}
              <DriftMapBanner verdict={driftVerdict} />
              {mapProvider != null && marksCenter !== null ? (
                // `flex: 1, minWidth: 0`: the map asks for height only, so as a
                // bare flex child it would take its width from content — zero.
                <Box sx={{ flex: 1, minWidth: 0 }}>
                  <Suspense fallback={<Skeleton variant="rounded" height="100%" />}>
                    <LiveMarksMap
                      marks={detection.marks}
                      center={marksCenter}
                      provider={mapProvider}
                    />
                  </Suspense>
                </Box>
              ) : (
                <Stack
                  alignItems="center"
                  justifyContent="center"
                  spacing={1}
                  sx={{
                    flex: 1,
                    px: 3,
                    textAlign: 'center',
                    border: 1,
                    borderStyle: 'dashed',
                    borderColor: 'divider',
                    borderRadius: 1,
                  }}
                >
                  <PlaceOutlinedIcon sx={{ fontSize: 36, color: 'text.disabled' }} />
                  <Typography variant="body2" color="text.secondary">
                    {detLut === ''
                      ? t(
                          'Choose a lookup table above and every detection lands here, on the ground.',
                        )
                      : detDirty
                        ? t('Press Apply to open the map on this lookup table’s site.')
                        : 'This lookup table records no camera position, so the map cannot open on its site. Detections will still be placed once the run starts.'}
                  </Typography>
                  {detLut === '' && (
                    <Typography variant="caption" color="text.disabled">
                      {t(
                        'Without one the run still detects and counts — it just cannot say where.',
                      )}
                    </Typography>
                  )}
                </Stack>
              )}
            </Box>
          </CardContent>
        </Card>
      </Stack>

      {/* ── the numbers, one row under the pictures: the stream's and the
          detection's, beside each other at the same size ─────────────────── */}
      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        spacing={2}
        sx={{ mt: 2, alignItems: 'stretch' }}
      >
        <Box sx={{ flex: 1, minWidth: 280, maxWidth: 460, display: 'flex' }}>
          <LiveStatsPanel
            stats={stats}
            fpsMeasurable={
              active !== null && !disconnected && (mode === 'canvas' || mode === 'connecting')
            }
            detections={detections}
          />
        </Box>
        {detection.session !== null && (
          <Box sx={{ flex: 1, minWidth: 280, maxWidth: 460, display: 'flex' }}>
            <DetectionSessionPanel session={detection.session} />
          </Box>
        )}
      </Stack>

      {sources.length === 0 && devices.length === 0 && (
        <Alert severity="info" icon={false} sx={{ mt: 2, maxWidth: 860 }}>
          {t(
            'Add a stream URL above, or scan for local devices, to enable the player. On a Raspberry Pi,',
          )}{' '}
          <code>ustreamer --host 0.0.0.0 --port 8080</code> serves{' '}
          <code>http://&lt;pi-address&gt;:8080/stream</code>.
        </Alert>
      )}

      {/* ── the live-capture library strip ─────────────────────────────── */}
      {recent.length > 0 && (
        <Box sx={{ mt: 3 }}>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>
            {t('Live captures')}
          </Typography>
          <Stack direction="row" spacing={1.5} sx={{ overflowX: 'auto', pb: 1 }}>
            {recent.map((e) => (
              <Box key={e.filename} sx={{ flexShrink: 0, width: 140 }}>
                <Box
                  component="img"
                  src={captureLibraryApi.fileUrl(e.filename)}
                  alt={e.filename}
                  loading="lazy"
                  sx={{
                    width: 140,
                    height: 88,
                    objectFit: 'cover',
                    borderRadius: 1,
                    border: 1,
                    borderColor: 'divider',
                    bgcolor: 'action.hover',
                  }}
                />
                <Typography
                  variant="caption"
                  color="text.secondary"
                  noWrap
                  title={e.filename}
                  display="block"
                >
                  {e.filename.replace(/^live_/, '').replace(/\.(jpe?g|png)$/i, '')}
                </Typography>
              </Box>
            ))}
          </Stack>
        </Box>
      )}

      {/* ── capture dialog: name + optional save folder ────────────────── */}
      <Dialog
        open={captureOpen}
        onClose={() => (capture.isPending ? undefined : setCaptureOpen(false))}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>{t('Capture frame')}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 0.5 }}>
            <TextField
              label={t('Name')}
              value={captureName}
              onChange={(e) => setCaptureName(e.target.value)}
              fullWidth
              autoFocus
              helperText="Saved into the live-capture library. Letters, numbers, spaces — the rest is tidied for the filename."
            />
            {hasNativeDirectoryPicker() && (
              <Box>
                <Button
                  variant="outlined"
                  startIcon={<FolderOpenOutlinedIcon />}
                  onClick={chooseSaveDir}
                >
                  {saveDir ? 'Change folder…' : 'Also save to a folder…'}
                </Button>
                {saveDir && (
                  <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 1 }}>
                    <Typography
                      variant="caption"
                      color="text.secondary"
                      noWrap
                      title={saveDir}
                      sx={{ flex: 1 }}
                    >
                      A copy will be saved to: {saveDir}
                    </Typography>
                    <Button size="small" color="inherit" onClick={() => setSaveDir('')}>
                      {t('Clear')}
                    </Button>
                  </Stack>
                )}
              </Box>
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button
            color="inherit"
            onClick={() => setCaptureOpen(false)}
            disabled={capture.isPending}
          >
            {t('Cancel')}
          </Button>
          <Button
            variant="contained"
            startIcon={<CameraAltOutlinedIcon />}
            onClick={submitCapture}
            disabled={capture.isPending}
          >
            {capture.isPending ? 'Capturing…' : 'Capture'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

export default LiveStreamTab;
