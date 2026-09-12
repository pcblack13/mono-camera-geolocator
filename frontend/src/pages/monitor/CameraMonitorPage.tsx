/**
 * `pages/monitor/CameraMonitorPage.tsx` — `/monitor/cameras/:id`: one camera, watched.
 *
 * ★ THE LIVE STREAM TAB'S FUNCTIONALITY IN A NEW SHAPE: the video as the hero, a
 *   staged inspector on the right, a status header, and a deck under the video
 *   whose map is synced to the picture. Every hook behind it is the tab's own —
 *   `useLiveFeed` (the MJPEG state machine), `useLiveDetection`, the drift hooks,
 *   the capture flow — so nothing about detection changed; only where it sits.
 *
 * ★ STATUS FLOWS BACK TO THE GLOBE. Whatever this page sees — connecting, live,
 *   lost, refused with the server's words — is written to the registry, which is
 *   what the marker paints when the operator returns.
 */

import { useCallback, useEffect, useMemo, useRef, useState, type JSX } from 'react';
import { Link as RouterLink, useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useMediaQuery } from '@mui/material';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import Drawer from '@mui/material/Drawer';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import IconButton from '@mui/material/IconButton';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import CloseOutlinedIcon from '@mui/icons-material/CloseOutlined';
import FolderOpenOutlinedIcon from '@mui/icons-material/FolderOpenOutlined';
import MapOutlinedIcon from '@mui/icons-material/MapOutlined';
import TuneOutlinedIcon from '@mui/icons-material/TuneOutlined';
import OpenInNewOutlinedIcon from '@mui/icons-material/OpenInNewOutlined';
import VerticalAlignBottomOutlinedIcon from '@mui/icons-material/VerticalAlignBottomOutlined';
import VerticalSplitOutlinedIcon from '@mui/icons-material/VerticalSplitOutlined';

import { API_BASE_URL } from '../../api/client';
import type { DriftVerdict } from '../../api/drift';
import { useDriftMonitors, useDriftReferences } from '../../api/hooks/useDrift';
import { detectionApi, type DetectionSession } from '../../api/detection';
import { DRIFT_ALERT_STAMPS } from '../../api/detection';
import { useDetectionAvailability, useLiveDetection } from '../../api/hooks/useDetection';
import type { DetectionStartRequest } from '../../api/detection';
import { useProviders } from '../../api/hooks';
import { liveApi, type LiveCaptureOptions, type RecordingRead } from '../../api/live';
import { lutApi } from '../../api/lut';
import { qk } from '../../api/queryKeys';
import { useDataFeed } from '../../hooks/useDataFeed';
import {
  boxesUrlFor,
  trackUrlFor,
  useSenderBoxes,
  useSourceBoxes,
} from '../../hooks/useSourceBoxes';
import { senderIdFromSource } from '../../hooks/useSenders';
import { canPreviewInBrowser, previewSrcForSource, useLiveFeed } from '../../hooks/useLiveFeed';
import { useLivePredict } from '../../hooks/useLivePredict';
import { useMonitorEvents } from '../../hooks/useMonitorEvents';
import { isMapWindowMessage, openMapChannel, openMapWindow } from '../../lib/monitor/mapWindow';
import { computeStages, startBlocker, type StageState } from '../../lib/monitor/stages';
import { hasNativeDirectoryPicker, pickDirectoryNative } from '../../lib/nativeFilePicker';
import { peekSurvivingState, useSurvivingState } from '../../lib/survivingState';
import { useMapStore } from '../../store';
import {
  isServerCameraId,
  selectCameraById,
  useCameraRegistryStore,
} from '../../store/cameraRegistryStore';
import { useMonitorLayoutStore, type DeckTab } from '../../store/monitorLayoutStore';
import { selectSettingsFor, useMonitorSettingsStore } from '../../store/monitorSettingsStore';
import { ApiError } from '../../types/common';
import { EmptyState } from '../../components/common/EmptyState';
import { useNotify } from '../../components/common/Notifications';
import { BottomDeck } from '../../components/monitor/camera/BottomDeck';
import { DataFeedPanel } from '../../components/monitor/camera/DataFeedPanel';
import { DetectionsDeck } from '../../components/monitor/camera/DetectionsDeck';
import { EventsDeck } from '../../components/monitor/camera/EventsDeck';
import { Inspector, type DetectorDraft } from '../../components/monitor/camera/Inspector';
import { MapDeck } from '../../components/monitor/camera/MapDeck';
import { MonitorHeader } from '../../components/monitor/camera/MonitorHeader';
import { VideoHero } from '../../components/monitor/camera/VideoHero';
import { Splitter } from '../../components/workspace/Splitter';
import { t } from '../../i18n';

interface Selection {
  origin: 'video' | 'map' | 'table';
  trackId: number | null;
  markIndex: number | null;
}

export function CameraMonitorPage(): JSX.Element {
  const { id } = useParams();
  const camera = useCameraRegistryStore(selectCameraById(id));
  if (camera === undefined) {
    return (
      <Box sx={{ p: 4 }}>
        <EmptyState
          title={t('No such camera')}
          description={t(
            'It is not in this browser’s registry — it may have been removed, or registered on another machine.',
          )}
          primaryAction={{ label: t('Back to the globe'), onClick: () => window.history.back() }}
        />
        <Button component={RouterLink} to="/monitor" sx={{ mt: 2 }}>
          {t('Open the globe')}
        </Button>
      </Box>
    );
  }
  return <CameraMonitor key={camera.id} cameraId={camera.id} />;
}

function CameraMonitor({ cameraId }: { cameraId: string }): JSX.Element {
  const camera = useCameraRegistryStore(selectCameraById(cameraId))!;
  const setStatus = useCameraRegistryStore((s) => s.setStatus);
  // ★ WHAT THE INTEGRATION DELIVERS (2026-09-02). 'camera' runs the app's own
  //   detector; 'data' receives ready-made detections (serial/UART, a Pi) and
  //   plots them; 'both' does both at once. The page reshapes accordingly.
  const provides = camera.provides ?? 'camera';
  const dataOnly = provides === 'data';
  // ★ A sender-backed camera's feed URL is REBUILT from its id, like its stream
  //   (2026-09-09): the stored one can name a stale port after a restart.
  const feedSenderId = senderIdFromSource(camera.source);
  const feedSource =
    feedSenderId !== null ? liveApi.senderDetectionsUrl(feedSenderId) : (camera.data_source ?? null);
  const dataFeed = useDataFeed(
    provides !== 'camera' ? feedSource : null,
    // ★ Only a SERVER camera can carry intent; a pre-1.3 browser row has no UUID.
    isServerCameraId(camera.id) ? camera.id : null,
  );
  const notify = useNotify();
  const navigate = useNavigate();
  const wide = useMediaQuery('(min-width:1280px)');

  // ── layout ──────────────────────────────────────────────────────────────────
  const inspectorPx = useMonitorLayoutStore((s) => s.inspectorPx);
  const setInspectorPx = useMonitorLayoutStore((s) => s.setInspectorPx);
  const inspectorOpen = useMonitorLayoutStore((s) => s.inspectorOpen);
  const setInspectorOpen = useMonitorLayoutStore((s) => s.setInspectorOpen);
  const overlays = useMonitorLayoutStore((s) => s.overlays);
  const toggleOverlay = useMonitorLayoutStore((s) => s.toggleOverlay);
  const mapBeside = useMonitorLayoutStore((s) => s.mapBeside);
  const setMapBeside = useMonitorLayoutStore((s) => s.setMapBeside);
  const mapFraction = useMonitorLayoutStore((s) => s.mapFraction);
  const setMapFraction = useMonitorLayoutStore((s) => s.setMapFraction);
  // The row the video and the map share — the seam moves the RATIO, so it needs the width.
  const rowRef = useRef<HTMLDivElement | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);

  // ── the run ─────────────────────────────────────────────────────────────────
  const detection = useLiveDetection('live');
  const detecting =
    detection.session !== null &&
    (detection.session.status === 'starting' || detection.session.status === 'running');

  // ★ ADOPT WHAT IS ALREADY RUNNING (2026-09-02). Runs can start from the WALL
  //   now, and several may run at once — so on entry this page binds to ITS
  //   camera's session: adopt a running one for this source; let go of a tracked
  //   session that belongs to a DIFFERENT camera (the run keeps running there).
  const adoptRef = useRef(detection.adopt);
  adoptRef.current = detection.adopt;
  useEffect(() => {
    let cancelled = false;
    void detectionApi
      .list()
      .then(({ items }) => {
        if (cancelled) return;
        const mine = items.find(
          (s) => s.source === camera.source && (s.status === 'starting' || s.status === 'running'),
        );
        const tracked = peekSurvivingState<DetectionSession | null>('detection.live.session', null);
        if (mine !== undefined && mine.session_id !== tracked?.session_id) {
          adoptRef.current(mine);
        } else if (mine === undefined && tracked !== null && tracked.source !== camera.source) {
          adoptRef.current(null);
        }
      })
      .catch(() => undefined); // adoption is a convenience, never a blocker
    return () => {
      cancelled = true;
    };
  }, [camera.source]);

  // ★ THE CHIPS WORK MID-RUN (2026-09-01). The run's picture carries its boxes
  //   burned in server-side (frame-synced by construction), which used to make
  //   the Boxes / Labels / Tracks toggles dead for the length of a run. This
  //   pushes the chips' state INTO the session — on start (so a chip turned off
  //   beforehand is honoured from the first frame) and on every later toggle.
  const overlaySessionId = detecting ? (detection.session?.session_id ?? null) : null;
  useEffect(() => {
    if (overlaySessionId === null) return;
    void detectionApi
      .setOverlay(overlaySessionId, {
        boxes: overlays.boxes,
        labels: overlays.labels,
        tracks: overlays.tracks,
        hud: overlays.hud,
      })
      .catch(() => undefined); // a missed toggle must never take the page down
  }, [overlaySessionId, overlays.boxes, overlays.labels, overlays.tracks, overlays.hud]);

  // ── the feed: released the moment a run is STARTING (one opener per device) ──
  const canvasRef = useRef<HTMLCanvasElement>(null);
  // ★ A SENDER-BACKED CAMERA PLAYS FROM AN ADDRESS WE REBUILD, NOT ONE WE STORED
  //   (2026-09-09). The desktop API takes the first free port at or after 8123,
  //   so the absolute URL written into the row when the camera was connected can
  //   name yesterday's port. The sender id inside it never goes stale, so the id
  //   is what we keep and the URL is what we recompute.
  const senderId = senderIdFromSource(camera.source);
  const playFrom =
    senderId !== null ? liveApi.senderStreamUrl(senderId) : camera.source;
  const previewUrl =
    !dataOnly && !detecting && !detection.starting ? previewSrcForSource(playFrom) : null;
  // ★ THE READER IS ENSURED ON EVERY ATTEMPT, NOT ASSUMED (2026-09-10). The
  //   app's reader for a sender lives in the API's memory: a relaunch forgets
  //   it, and this page used to sit on "not connected" with a Reconnect arrow
  //   that changed nothing. Connect is idempotent and cheap, so each attempt —
  //   first open, the arrow, the quiet 10 s retry — asks for it first; when the
  //   sender is not announcing itself, the server's own sentence is the refusal.
  const ensureSender = useMemo(
    () =>
      senderId === null
        ? undefined
        : async (): Promise<void> => {
            await liveApi.connectSender(senderId);
          },
    [senderId],
  );
  const feed = useLiveFeed(previewUrl, canvasRef, { prepare: ensureSender });

  // ── the SENDER'S own boxes (2026-09-08) ─────────────────────────────────────
  // ★ MUTUALLY EXCLUSIVE WITH OUR OWN RUN, BY CONSTRUCTION. `detecting` and
  //   `detection.starting` switch this off before a run can draw a single box,
  //   the same way `previewUrl` above releases the source. Two detectors on one
  //   picture is the "duplicated, unstable annotations" defect that
  //   DetectionOverlay's `pictureHasBoxes` was added to fix; here it cannot
  //   happen, because there is nothing to suppress.
  // ★ TWO WAYS A SENDER CAN REACH US, AND THE SOURCE SAYS WHICH (2026-09-09).
  //   A camera connected from the Detected panel plays from the app's OWN reader,
  //   so its id is in its source URL and its boxes come from our endpoint. A
  //   camera registered against an external bridge still works the old way. Both
  //   hooks are called unconditionally — only one of them is ever enabled.
  const boxesEnabled = overlays.piBoxes && !detecting && !detection.starting;
  const ownReaderBoxes = useSenderBoxes(senderId, boxesEnabled && senderId !== null);
  const senderBoxesUrl = boxesUrlFor(camera.data_source);
  const bridgeBoxes = useSourceBoxes(
    senderBoxesUrl,
    boxesEnabled && senderId === null,
  );
  const senderBoxes = senderId !== null ? ownReaderBoxes : bridgeBoxes;
  // ★ A CLICK ON A SENDER'S BOX IS A COMMAND TO THE SENDER (2026-09-08). It
  //   owns its own tracker, so the app carries the click and reports what came
  //   back — it does not decide, and it does not pretend the click landed. The
  //   point sent is the box's CENTRE rather than the pixel under the cursor:
  //   the boxes here refresh a few times a second, so by the time the command
  //   arrives the object has moved a little, and its centre is the part of it
  //   least likely to have left the box.
  const senderTrackUrl = trackUrlFor(camera.data_source);
  const onSenderBoxClick = useCallback(
    (index: number): void => {
      const box = senderBoxes?.boxes[index];
      if (box === undefined) return;
      const u = (box.x1 + box.x2) / 2;
      const v = (box.y1 + box.y2) / 2;
      // Two transports, narrowed one at a time: the app's own reader knows the
      // sender by id, the bridge path needs a URL that may not exist.
      let sent: Promise<{ ok: boolean; error: string | null }> | null = null;
      if (senderId !== null) {
        sent = liveApi.senderCommand(senderId, { op: 'track', u, v });
      } else if (senderTrackUrl !== null) {
        sent = liveApi.sourceCommand({ url: senderTrackUrl, op: 'track', u, v });
      }
      if (sent === null) return;
      void sent
        .then((answer) => {
          if (!answer.ok) notify(answer.error ?? t('The sender refused that.'),
                                 { severity: 'warning' });
        })
        .catch(() => notify(t('Could not reach the sender.'), { severity: 'warning' }));
    },
    [senderBoxes, senderId, senderTrackUrl, notify],
  );
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (feed.status !== 'lost') return undefined;
    const idt = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(idt);
  }, [feed.status]);
  const sinceLastFrameS =
    feed.status === 'lost' && feed.lastFrameAt !== null
      ? Math.max(0, Math.round((now - feed.lastFrameAt) / 1000))
      : null;

  // ── events + status write-back ──────────────────────────────────────────────
  const { events, log, clear } = useMonitorEvents(cameraId);
  const prevStatus = useRef<string | null>(null);
  // Data-only: the FEED is the pulse the globe should show.
  useEffect(() => {
    if (!dataOnly) return;
    const st = dataFeed.feed?.status;
    if (st === undefined) return;
    setStatus(
      cameraId,
      st === 'running'
        ? 'live'
        : st === 'starting'
          ? 'connecting'
          : st === 'failed'
            ? 'refused'
            : 'lost',
      dataFeed.feed?.error ?? undefined,
    );
  }, [dataOnly, dataFeed.feed?.status, dataFeed.feed?.error, cameraId, setStatus]);
  useEffect(() => {
    if (dataOnly) return;
    const st = detecting ? 'live' : feed.status;
    if (st === 'idle') return;
    setStatus(cameraId, st, feed.streamError ?? undefined);
    if (prevStatus.current !== st) {
      const was = prevStatus.current;
      prevStatus.current = st;
      if (st === 'live' && (was === 'lost' || was === 'refused'))
        log('stream', t('Stream recovered.'), 'ok');
      else if (st === 'live') log('stream', t('Stream live.'), 'ok');
      else if (st === 'lost')
        log('stream', t('Stream lost — frames stopped arriving (stalled 6 s).'), 'error');
      else if (st === 'refused')
        log('stream', `${t('Source refused:')} ${feed.streamError ?? ''}`, 'error');
      else if (st === 'connecting') log('stream', t('Connecting…'));
    }
  }, [dataOnly, feed.status, feed.streamError, detecting, cameraId, setStatus, log]);

  const prevRun = useRef<string | null>(null);
  useEffect(() => {
    const s = detection.session;
    const key = s === null ? null : `${s.session_id}:${s.status}`;
    if (key === prevRun.current) return;
    prevRun.current = key;
    if (s === null) return;
    if (s.status === 'starting') log('detection', t('Detection starting.'));
    else if (s.status === 'running') log('detection', t('Detection running.'), 'ok');
    else if (s.status === 'stopped')
      log('detection', `${t('Detection stopped.')} ${s.marks_total} ${t('marks')}.`);
    else if (s.status === 'failed')
      log('detection', `${t('Detection failed:')} ${s.error ?? ''}`, 'error');
  }, [detection.session, log]);

  // ── the inspector's draft vs what is applied ────────────────────────────────
  const availability = useDetectionAvailability();
  const onCpu = availability.data?.device === 'cpu';
  // ★ THE SETUP IS THE CAMERA'S OWN (2026-09-01). These slots used to be ONE set
  //   shared by every camera — walking A → B carried A's dials along, and a reload
  //   lost both. Now the keys carry the camera id (the session-surviving layer)
  //   and the INITIAL value is the camera's persisted setup (`monitorSettingsStore`,
  //   written on Apply/Start), so re-entering a camera finds it ready to start.
  const saved = useMonitorSettingsStore(selectSettingsFor(cameraId));
  const saveSettings = useMonitorSettingsStore((s) => s.save);
  const [model, setModel] = useSurvivingState(
    `detection.live.${cameraId}.model`,
    saved?.model ?? '',
  );
  // ★ The camera's OWN lookup table (built in its settings pipeline, 2026-09-04)
  //   is the fallback when this browser has never applied a setup here: a camera
  //   added on the server page is watchable with its marks placed at once.
  const [lutSite, setLutSite] = useSurvivingState(
    `detection.live.${cameraId}.lutSite`,
    saved?.lutSite || camera.lut_site || '',
  );
  const [conf, setConf] = useSurvivingState(`detection.live.${cameraId}.conf`, saved?.conf ?? 0.25);
  const [imgszChoice, setImgszChoice] = useSurvivingState<number | null>(
    `detection.live.${cameraId}.imgsz`,
    saved?.imgszChoice ?? null,
  );
  const [trackerStart, setTrackerStart] = useSurvivingState(
    `detection.live.${cameraId}.trackerStart`,
    saved?.trackerStart ?? 0,
  );
  const [trackerType, setTrackerType] = useSurvivingState(
    `detection.live.${cameraId}.trackerType`,
    saved?.trackerType ?? 'vit',
  );
  const [classes, setClasses] = useSurvivingState<number[]>(
    `detection.live.${cameraId}.classes`,
    saved?.classes ?? [],
  );
  const [centreMarks, setCentreMarks] = useSurvivingState<boolean>(
    `detection.live.${cameraId}.centreMarks`,
    saved?.centreMarks ?? false,
  );
  // ★ Marks per second, per object (2026-09-11). One is plenty for a ground fix
  //   and is what keeps the map — and with it the video — from drowning.
  const [markRateHz, setMarkRateHz] = useSurvivingState<number>(
    `detection.live.${cameraId}.markRateHz`,
    saved?.markRateHz ?? 1,
  );
  const [steadyBoxes, setSteadyBoxes] = useSurvivingState<boolean>(
    `detection.live.${cameraId}.steadyBoxes`,
    saved?.steadyBoxes ?? true,
  );
  // ★ The saved table counts as APPLIED from the first frame: the map centres on
  //   its site and the drift watch runs without a ritual re-Apply.
  const [appliedLut, setAppliedLut] = useSurvivingState(
    `detection.live.${cameraId}.appliedLut`,
    saved?.lutSite || camera.lut_site || '',
  );
  const [applied, setApplied] = useSurvivingState<string>(`monitor.live.${cameraId}.applied`, '');
  const imgsz = imgszChoice ?? (onCpu ? 480 : 640);
  const draft: DetectorDraft = {
    markRateHz,
    model,
    lutSite,
    classes,
    conf,
    imgsz,
    trackerStart,
    trackerType,
    centreMarks,
    steadyBoxes,
  };
  // ★ The snapshot is of the RAW dials (`imgszChoice`, not the resolved size): the
  //   CPU/GPU default arrives asynchronously and must not read as an unsaved edit.
  const draftKey = JSON.stringify({
    markRateHz,
    model,
    lutSite,
    classes,
    conf,
    imgszChoice,
    trackerStart,
    trackerType,
    centreMarks,
    steadyBoxes,
  });
  // First mount: the dials as they stand ARE the applied state.
  useEffect(() => {
    if (applied === '') setApplied(draftKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const dirty = applied !== '' && applied !== draftKey;
  const onChange = (patch: Partial<DetectorDraft>): void => {
    if (patch.model !== undefined) setModel(patch.model);
    if (patch.lutSite !== undefined) setLutSite(patch.lutSite);
    if (patch.classes !== undefined) setClasses(patch.classes);
    if (patch.conf !== undefined) setConf(patch.conf);
    if (patch.imgsz !== undefined) setImgszChoice(patch.imgsz);
    if (patch.trackerStart !== undefined) setTrackerStart(patch.trackerStart);
    if (patch.trackerType !== undefined) setTrackerType(patch.trackerType);
    if (patch.centreMarks !== undefined) setCentreMarks(patch.centreMarks);
    if (patch.steadyBoxes !== undefined) setSteadyBoxes(patch.steadyBoxes);
    if (patch.markRateHz !== undefined) setMarkRateHz(patch.markRateHz);
  };
  const apply = (): void => {
    setApplied(draftKey);
    setAppliedLut(lutSite);
    // ★ Apply IS the save: what comes back next visit is the setup that actually
    //   ran, never a half-edit abandoned mid-keystroke.
    saveSettings(cameraId, {
      model,
      lutSite,
      classes,
      conf,
      imgszChoice,
      trackerStart,
      trackerType,
      centreMarks,
      steadyBoxes,
    });
  };

  // ★ A camera that arrives CONFIGURED needs no setup pane: the inspector folds
  //   away and the header offers "Edit settings" instead. A camera never set up
  //   opens with the inspector out — the stages ARE the guide. Once, on entry.
  const arrivedConfigured = useRef(saved !== undefined);
  useEffect(() => {
    setInspectorOpen(!arrivedConfigured.current && !dataOnly);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const lutLibrary = useQuery({
    queryKey: qk.lut.library(),
    queryFn: ({ signal }) => lutApi.library(signal),
  });
  const appliedEntry = (lutLibrary.data ?? []).find((e) => e.site_name === appliedLut);
  // ★ The CHOSEN table drives the map's site and the drift watch the moment it is
  //   picked — Apply is for the detector's dials, not a second gate on the table.
  const chosenEntry = (lutLibrary.data ?? []).find((e) => e.site_name === lutSite);

  // ── live predict (2026-09-10, owner ask): the cursor on the picture → the ground ──
  // ★ Through the camera's LOOKUP TABLE — the same table the marks are placed
  //   through — and the elevation from the camera project's own DEM. Offered
  //   only when a table is set; a data-only camera has no picture to point at.
  const [predictOn, setPredictOn] = useState(false);
  const predictAvailable = !dataOnly && lutSite !== '';
  const livePredict = useLivePredict({
    enabled: predictOn && predictAvailable,
    lutSite,
    projectId: camera.project_id ?? null,
  });
  const onPredictCopied = useCallback(
    (text: string | null): void => {
      notify(
        text === null
          ? t('Nothing to copy yet — point at the ground first.')
          : `${t('Copied')} ${text}`,
        { severity: text === null ? 'warning' : 'success' },
      );
    },
    [notify],
  );
  const predictPoint =
    livePredict.prediction !== null &&
    livePredict.prediction.placed &&
    livePredict.prediction.lat !== null &&
    livePredict.prediction.lon !== null
      ? { lat: livePredict.prediction.lat, lon: livePredict.prediction.lon }
      : null;
  // ★ THE DRIFT WATCH IS THE CAMERA'S (2026-09-08, owner decision): frozen on
  //   the frame its control points sit on, in the camera settings, and watched
  //   by the server in the background from then on. This page only READS it —
  //   by the watch the row records, else the newest run on this source — and
  //   draws its verdict over the picture and the map. Nothing is frozen here.
  const watchRefId = camera.desired?.watch?.ref_id ?? null;
  const references = useDriftReferences();
  const monitors = useDriftMonitors(!dataOnly);
  const driftReference = useMemo(() => {
    const items = references.data ?? [];
    return (
      items.find((r) => r.ref_id === watchRefId) ??
      items.find((r) => r.source === camera.source) ??
      null
    );
  }, [references.data, watchRefId, camera.source]);
  const driftMonitor = useMemo(() => {
    const items = monitors.data ?? [];
    return (
      items.find((m) => m.ref_id === watchRefId) ??
      items.find((m) => m.source === camera.source && m.status === 'running') ??
      items.find((m) => m.source === camera.source) ??
      null
    );
  }, [monitors.data, watchRefId, camera.source]);
  const driftVerdict: DriftVerdict | null = driftMonitor?.last ?? null;
  const driftFrozen = watchRefId !== null || driftReference !== null;
  const driftWatching = driftMonitor?.status === 'running';
  const lastAlert = useRef<string | null>(null);
  useEffect(() => {
    if (driftVerdict === null) return;
    const confirmed =
      driftVerdict.confirmed &&
      (driftVerdict.state === 'MOVED' || driftVerdict.state === 'CHANGED');
    const key = `${driftVerdict.checked_utc}:${driftVerdict.state}`;
    if (confirmed && lastAlert.current !== key) {
      lastAlert.current = key;
      log('drift', `${driftVerdict.state}: ${driftVerdict.why}`, 'warn');
    }
  }, [driftVerdict, log]);

  const models = availability.data?.models ?? [];
  const classesLabel =
    classes.length === 0 || classes.length === (availability.data?.classes.length ?? 0)
      ? t('all classes')
      : `${classes.length} ${t('classes')}`;
  const stages = computeStages({
    feedStatus: feed.status,
    stats: feed.stats,
    detectorAvailable:
      availability.data === undefined ? null : availability.data.detector.available,
    detectorReason: availability.data?.detector.reason ?? null,
    detecting,
    run:
      detecting && detection.session !== null
        ? {
            fps: detection.session.fps,
            phase: detection.session.phase,
            width: detection.session.media_width,
            height: detection.session.media_height,
          }
        : null,
    lutSite,
    appliedLut,
    lutHasPose:
      lutSite === ''
        ? null
        : lutLibrary.data === undefined
          ? null
          : (chosenEntry?.has_pose ?? false),
    trackerStart,
    trackerType,
    driftFrozen,
    driftWatching,
    driftState: driftVerdict?.state ?? null,
    driftStatus: driftVerdict?.status ?? null,
    driftError: driftMonitor?.last_error ?? null,
    modelName: model || models[0] || '',
    classesLabel,
    conf,
    imgsz,
    settingsTo: `/cameras/${cameraId}/settings`,
  });
  const blocker = startBlocker(stages, detecting);

  // ★ One body for both kinds of run. `detect: false` is a TRACKING-ONLY run —
  //   no detector, no weights — started the moment the operator draws a box on a
  //   picture nothing is running on (2026-09-11, owner ask): the object they
  //   outlined is followed and placed, and nothing else is ever a box.
  const startBody = (detect: boolean): DetectionStartRequest => ({
    detect,
    source: camera.source,
      lut_site: lutSite || null,
      conf,
      imgsz,
      model: model || null,
      // ★ Manual tracking replaced the frame handoff here (2026-09-03): NEVER
      //   auto-lock. An older saved setup may still carry a nonzero trackerStart,
      //   which is why yamouneh tracked on its own — send 0 regardless.
      tracker_start_frame: 0,
      tracker_type: trackerType,
      classes: classes.length > 0 ? classes : null,
      centre_marks: centreMarks,
      steady_boxes: steadyBoxes,
      mark_rate_hz: markRateHz,
      // ★ The run is this camera's DESIRED state (1.3): the server restarts it
      //   after a restart, and Stop clears it. Only a server camera has an id
      //   the server knows.
      camera_id: isServerCameraId(camera.id) ? camera.id : null,
  });
  const start = (): void => {
    apply();
    detection.start(startBody(true));
  };
  // The box drawn before any run existed: sent the moment the tracking-only run
  // it started is running. A ref, not state — nothing renders from it.
  const pendingBox = useRef<{ x1: number; y1: number; x2: number; y2: number } | null>(null);
  const startTrackingOnly = (box: { x1: number; y1: number; x2: number; y2: number }): void => {
    pendingBox.current = box;
    detection.start(startBody(false));
  };
  useEffect(() => {
    if (pendingBox.current === null) return;
    if (detection.session?.status === 'running') {
      const box = pendingBox.current;
      pendingBox.current = null;
      detection.trackBox(box);
    } else if (detection.session?.status === 'failed' || detection.startError !== null) {
      pendingBox.current = null;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detection.session?.status, detection.startError]);
  const [errorDismissed, setErrorDismissed] = useState<string | null>(null);
  const startError =
    detection.startError !== null && detection.startError !== errorDismissed
      ? detection.startError
      : null;
  useEffect(() => {
    if (detection.startError !== null && detection.startError !== errorDismissed) {
      log('error', `${t('Start refused:')} ${detection.startError}`, 'error');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detection.startError]);

  const onFix = (action: NonNullable<StageState['fix']>['action']): void => {
    if (action === 'reconnect') feed.reconnect();
    else if (action === 'apply') apply();
  };

  // ── selection: video ↔ map ↔ table ─────────────────────────────────────────
  const [selection, setSelection] = useState<Selection | null>(null);
  // ★ ONE stream of marks for map + table, whatever their origin: the app's own
  //   detections, the integration's data feed, or both — the data marks keep
  //   their own track ids, so the per-track colours read the same way.
  const marks = useMemo(
    () =>
      provides === 'camera'
        ? detection.marks
        : provides === 'data'
          ? dataFeed.marks
          : [...detection.marks, ...dataFeed.marks],
    [provides, detection.marks, dataFeed.marks],
  );
  const selectedMarkIndex = useMemo(() => {
    if (selection === null) return null;
    if (selection.markIndex !== null) return selection.markIndex;
    if (selection.trackId === null) return null;
    for (let i = marks.length - 1; i >= 0; i -= 1)
      if (marks[i].track_id === selection.trackId) return i;
    return null;
  }, [selection, marks]);
  const selectedTrack =
    selection === null
      ? null
      : (selection.trackId ??
        (selectedMarkIndex === null ? null : (marks[selectedMarkIndex]?.track_id ?? null)));

  // ★ Manual tracking (2026-09-03): the server's state, from the session poll.
  const tracking = detection.session?.tracking_on ?? false;
  const trackedIds = detection.session?.tracked_ids ?? [];
  const primaryTrack = detection.session?.primary_track_id ?? null;
  // ★ Tracks as the organising key (2026-09-11, owner ask): the operator's names
  //   for them, the table's track filter, and the DRAW-A-BOX tool that follows
  //   any object the operator outlines on the picture.
  const trackNames = detection.session?.track_names ?? {};
  const [trackFilter, setTrackFilter] = useState<number | null>(null);
  const [boxToolOn, setBoxToolOn] = useState(false);

  // ── the map's centre: the run's own table, else the applied table's site ────
  const providersQuery = useProviders();
  const chosenProviderId = useMapStore((st) => st.providerId);
  const mapProvider = useMemo(() => {
    const items = providersQuery.data?.items ?? [];
    const byChoice = chosenProviderId ? items.find((p) => p.name === chosenProviderId) : undefined;
    const usable =
      byChoice && byChoice.configured && byChoice.allowed !== false ? byChoice : undefined;
    return usable ?? items.find((p) => p.is_default) ?? items[0];
  }, [providersQuery.data, chosenProviderId]);
  const sessionCenter = useMemo((): [number, number] | null => {
    const c = detection.session?.lut_summary?.center;
    return Array.isArray(c) && c.length === 2 ? [Number(c[0]), Number(c[1])] : null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detection.session?.session_id]);
  const chosenCenter = useMemo((): [number, number] | null => {
    const c = chosenEntry?.center;
    return Array.isArray(c) && c.length === 2 ? [Number(c[0]), Number(c[1])] : null;
  }, [chosenEntry]);
  const appliedCenter = useMemo((): [number, number] | null => {
    const c = appliedEntry?.center;
    return Array.isArray(c) && c.length === 2 ? [Number(c[0]), Number(c[1])] : null;
  }, [appliedEntry]);
  // A data feed carries ABSOLUTE coordinates — no LUT involved — so the camera's
  // own registered spot is an honest centre when no table gives a better one.
  const cameraCenter = useMemo(
    (): [number, number] | null => (provides !== 'camera' ? [camera.lat, camera.lon] : null),
    [provides, camera.lat, camera.lon],
  );
  const center = sessionCenter ?? chosenCenter ?? appliedCenter ?? cameraCenter;
  // ★ TWO PANELS, SIDE BY SIDE. Once the map has a site it stands beside the
  //   picture as its own panel (on a wide screen, unless docked below); the deck
  //   under the video then keeps the detections table and the events log.
  const mapReady = mapProvider !== undefined && center !== null;

  // ── the map in its own window (a second screen) ───────────────────────────
  // ★ Transient on purpose: a window is a thing that exists now, not a setting.
  const [mapWindow, setMapWindow] = useState<Window | null>(null);
  const mapPopped = mapWindow !== null;
  const channel = useRef<BroadcastChannel | null>(null);
  const latest = useRef({
    session: null as string | null,
    lut: '',
    selectedIndex: null as number | null,
  });
  latest.current = {
    session: detection.session?.session_id ?? null,
    lut: lutSite,
    selectedIndex: selectedMarkIndex,
  };
  const marksRef = useRef(marks);
  marksRef.current = marks;
  useEffect(() => {
    const ch = openMapChannel(cameraId);
    channel.current = ch;
    if (ch === null) return undefined;
    ch.onmessage = (e: MessageEvent) => {
      const m: unknown = e.data;
      if (!isMapWindowMessage(m)) return;
      if (m.type === 'hello') ch.postMessage({ type: 'state', ...latest.current });
      else if (m.type === 'select')
        setSelection({
          origin: 'map',
          trackId: marksRef.current[m.index]?.track_id ?? null,
          markIndex: m.index,
        });
      else if (m.type === 'closed') setMapWindow(null);
    };
    return () => {
      ch.close();
      channel.current = null;
    };
  }, [cameraId]);
  // Whatever changes, the window hears it.
  const sessionIdForMap = detection.session?.session_id ?? null;
  useEffect(() => {
    if (!mapPopped) return;
    channel.current?.postMessage({
      type: 'state',
      session: sessionIdForMap,
      lut: lutSite,
      selectedIndex: selectedMarkIndex,
    });
  }, [mapPopped, sessionIdForMap, lutSite, selectedMarkIndex]);
  // Belt to the channel's brace: a window closed by the OS may never say goodbye.
  useEffect(() => {
    if (mapWindow === null) return undefined;
    const idt = window.setInterval(() => {
      if (mapWindow.closed) setMapWindow(null);
    }, 1000);
    return () => window.clearInterval(idt);
  }, [mapWindow]);
  // Leaving the camera closes its map window — a map of nothing on screen two is a ghost.
  useEffect(() => () => mapWindow?.close(), [mapWindow]);
  const popOutMap = (): void => {
    const w = openMapWindow(cameraId, { session: sessionIdForMap, lut: lutSite });
    if (w === null) {
      notify(t('The map window was blocked — allow pop-ups for this app and try again.'), {
        severity: 'error',
      });
      return;
    }
    setMapWindow(w);
  };
  const bringMapBack = (): void => {
    mapWindow?.close();
    setMapWindow(null);
  };

  const sideMap = wide && mapBeside && mapReady && !mapPopped;
  const deckTabs: readonly DeckTab[] =
    sideMap || mapPopped ? ['detections', 'events'] : ['map', 'detections', 'events'];
  const popOutButton = (
    <Tooltip title={t('Open the map in its own window')}>
      <IconButton size="small" onClick={popOutMap} aria-label={t('Open the map in its own window')}>
        <OpenInNewOutlinedIcon fontSize="small" />
      </IconButton>
    </Tooltip>
  );

  // ── recording: the stream + the run's attribute table, one library folder ──
  const [recording, setRecording] = useState<RecordingRead | null>(null);
  const [recordBusy, setRecordBusy] = useState(false);
  // ★ A recording OUTLIVES the page on purpose (a recorder is not a tab) —
  //   re-entering the camera finds it and the button shows REC again.
  useEffect(() => {
    let cancelled = false;
    liveApi
      .activeRecording(camera.source)
      .then((rec) => {
        if (!cancelled) setRecording(rec);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [camera.source]);
  const toggleRecord = (): void => {
    if (recordBusy) return;
    setRecordBusy(true);
    if (recording !== null) {
      liveApi
        .stopRecording(recording.recording_id)
        .then((done) => {
          setRecording(null);
          log(
            'capture',
            `${t('Recording saved:')} ${done.folder} — ${done.marks} ${t('marks')}.`,
            'ok',
          );
          notify(`${t('Recording saved to the library:')} ${done.path}`, { severity: 'success' });
        })
        .catch((e) => notify(e instanceof Error ? e.message : String(e), { severity: 'error' }))
        .finally(() => setRecordBusy(false));
    } else {
      liveApi
        .startRecording(camera.source, camera.name)
        .then((rec) => {
          setRecording(rec);
          log('capture', t('Recording started.'), 'ok');
        })
        .catch((e) => notify(e instanceof Error ? e.message : String(e), { severity: 'error' }))
        .finally(() => setRecordBusy(false));
    }
  };

  // ── capture ─────────────────────────────────────────────────────────────────
  const [captureOpen, setCaptureOpen] = useState(false);
  const [captureName, setCaptureName] = useState('');
  const [saveDir, setSaveDir] = useState('');
  const isDevice = !/^(https?|rtsp):\/\//i.test(camera.source);
  const capture = useMutation({
    mutationFn: (opts: LiveCaptureOptions) =>
      isDevice
        ? liveApi.captureDeviceFrame(camera.source, opts)
        : liveApi.captureFrame(camera.source, opts),
    onSuccess: (frame) => {
      setCaptureOpen(false);
      log(
        'capture',
        `${t('Frame captured')} ${frame.filename}${frame.saved_to ? ` → ${frame.saved_to}` : ''}`,
        'ok',
      );
      notify(
        `${t('Frame captured')} (${frame.width}×${frame.height}) — ${frame.filename}${frame.saved_to ? ` · ${t('saved to')} ${frame.saved_to}` : ''}. ${t('Open in project: Projects → From library.')}`,
        { severity: 'success' },
      );
    },
    onError: (err) => {
      const msg = err instanceof ApiError ? err.message : String(err);
      log('capture', `${t('Capture failed:')} ${msg}`, 'error');
      notify(msg, { severity: 'error' });
    },
  });

  const runStartedMs =
    detection.session === null ? NaN : new Date(detection.session.started_at).getTime();
  const fpsMeasurable =
    feed.status === 'live' && (feed.mode === 'canvas' || feed.mode === 'connecting');

  const inspector = (
    <Inspector
      stages={stages}
      draft={draft}
      onChange={onChange}
      availability={availability.data}
      stats={feed.stats}
      fpsMeasurable={fpsMeasurable}
      running={detecting}
      run={detection.session}
      onFix={onFix}
      drift={{
        verdict: driftVerdict,
        frozen: driftFrozen,
        watching: driftWatching,
        lastError: driftMonitor?.last_error ?? null,
        frozenFromLabel: driftReference?.frozen_from_label ?? null,
        // The range the alert threshold is stated at — the far end of the scene,
        // which is where a small rotation moves a point the furthest.
        refRangeM: driftReference?.ref_range_m ?? null,
        settingsTo: `/cameras/${cameraId}/settings`,
      }}
    />
  );

  const mapDeck = (
    <MapDeck
      marks={marks}
      center={center}
      provider={mapProvider}
      lutSite={lutSite}
      settingsTo={`/cameras/${cameraId}/settings`}
      selectedIndex={selectedMarkIndex}
      onSelect={(i) =>
        setSelection({
          origin: 'map',
          trackId: marks[i]?.track_id ?? null,
          markIndex: i,
        })
      }
      driftVerdict={driftVerdict}
      prediction={predictPoint}
      predictionPinned={livePredict.pinned}
    />
  );

  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        // ★ FILL WHAT THE SHELL GIVES, never `calc(100dvh - 96px)` (2026-09-01).
        //   The old calc assumed exactly 96px of chrome above; at a different
        //   display size the assumption drifted and the page ran past (or short
        //   of) the window — dead space below the deck, top bars scrolling away.
        //   The shell's <main> is already a flex column sized to the viewport;
        //   this page simply takes all of it.
        flex: 1,
        minHeight: 0,
      }}
    >
      <MonitorHeader
        camera={camera}
        dataOnly={dataOnly}
        status={
          dataOnly
            ? dataFeed.feed?.status === 'running'
              ? 'live'
              : dataFeed.feed?.status === 'failed'
                ? 'refused'
                : dataFeed.feed?.status === 'stopped'
                  ? 'lost'
                  : 'connecting'
            : detecting
              ? 'live'
              : feed.status
        }
        dirty={dirty}
        detecting={detecting}
        trackingOnly={detection.session?.detect === false}
        starting={detection.starting}
        runStartedAt={detecting && Number.isFinite(runStartedMs) ? runStartedMs : null}
        startBlocker={blocker}
        startError={startError}
        onDismissError={() => setErrorDismissed(detection.startError)}
        onApply={apply}
        onStart={start}
        onStop={detection.stop}
        trackedCount={trackedIds.length}
        onCapture={() => {
          setCaptureName(camera.name);
          setCaptureOpen(true);
        }}
        captureBusy={capture.isPending}
        recordingStartedAt={recording !== null ? new Date(recording.started_at).getTime() : null}
        recordBusy={recordBusy}
        onToggleRecord={toggleRecord}
        onOpenLibrary={() => navigate('/videos')}
        // ★ The door back into the setup. Hidden only while the wide panel is
        //   already on screen — an Edit button beside the open editor is noise.
        onEditSettings={
          dataOnly || (wide && inspectorOpen)
            ? undefined
            : () => (wide ? setInspectorOpen(true) : setSheetOpen(true))
        }
      />
      {feed.formatWarning !== null && feed.status === 'live' && (
        <Alert severity="info" sx={{ borderRadius: 0 }}>
          {feed.formatWarning}
        </Alert>
      )}
      {/* ★ THE MARKS SAY SO THEMSELVES (1.3): every mark carries the drift verdict
          at the instant it was placed. While the run is stamping MOVED / CHANGED,
          the map is drawing coordinates the monitor has just said are in doubt —
          they are still drawn (the detection happened), and this line says why
          they should not be trusted until the camera is re-aimed and re-frozen. */}
      {detecting &&
        detection.session !== null &&
        DRIFT_ALERT_STAMPS.includes(detection.session.drift_status ?? 'unwatched') && (
          <Alert severity="warning" sx={{ borderRadius: 0 }} data-testid="drift-alert-banner">
            <b>
              {detection.session.drift_status === 'moved'
                ? t('Camera moved:')
                : t('Optics changed:')}
            </b>{' '}
            {t(
              'the marks being placed carry that verdict — their coordinates are in doubt until the camera is re-aimed and the reference re-frozen.',
            )}{' '}
            ({detection.session.marks_under_alert ?? 0} {t('so far')})
          </Alert>
        )}

      <Box sx={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'row' }}>
        <Box sx={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
          {/* ★ ONE ROW, TWO EQUALS: the picture and the map share the row and its
              height; the seam between them moves the ratio (half and half by
              default); the deck runs under BOTH. */}
          <Box
            ref={rowRef}
            data-testid="monitor-row"
            sx={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'row' }}
          >
            <Box
              sx={{
                flex: sideMap ? `${1 - mapFraction} 1 0px` : '1 1 0px',
                minWidth: 0,
                minHeight: 0,
                display: 'flex',
                flexDirection: 'column',
              }}
            >
              {dataOnly ? (
                <DataFeedPanel
                  feed={dataFeed.feed}
                  latest={dataFeed.marks[dataFeed.marks.length - 1] ?? null}
                  error={dataFeed.error}
                />
              ) : (
                <VideoHero
                  cameraName={camera.name}
                  previewUrl={previewUrl}
                  detectionStreamUrl={
                    detecting && detection.session !== null
                      ? `${API_BASE_URL}/detection/sessions/${detection.session.session_id}/stream`
                      : null
                  }
                  mode={feed.mode}
                  status={feed.status}
                  streamError={feed.streamError}
                  canvasRef={canvasRef}
                  onImgError={feed.reportImgFailed}
                  onReconnect={feed.reconnect}
                  // ★ Only while the run is ON. A stopped session still holds its
                  //   final frame's boxes, and passing them here left a ghost
                  //   "car 38% · #1" painted over the LIVE preview after Stop
                  //   (seen 2026-09-01). The run's history stays in the deck;
                  //   the picture goes back to being just the picture.
                  latest={
                    detecting && detection.session !== null ? detection.session.latest : null
                  }
                  piLatest={senderBoxes}
                  onSenderBoxClick={onSenderBoxClick}
                  driftVerdict={driftVerdict}
                  toggles={overlays}
                  onToggle={toggleOverlay}
                  selectedTrack={selectedTrack}
                  onSelectBox={(trackId) =>
                    setSelection({ origin: 'video', trackId, markIndex: null })
                  }
                  trackingMode={tracking}
                  primaryTrack={primaryTrack}
                  onTrackAt={(u, v) => detection.trackAt(u, v)}
                  onLockAt={(u, v) => detection.trackAt(u, v, true)}
                  trackNames={trackNames}
                  trackBox={
                    detecting || feed.status === 'live'
                      ? {
                          on: boxToolOn,
                          onToggle: () => setBoxToolOn((v) => !v),
                          mediaSize:
                            detection.session !== null && detection.session.media_width > 0
                              ? { w: detection.session.media_width, h: detection.session.media_height }
                              : null,
                          // ★ The tool STAYS ON until its chip is pressed again
                          //   (owner ask 2026-09-11): an operator marking several
                          //   targets must not re-arm it for every one.
                          onDraw: (box) => {
                            // ★ A box on a picture nothing runs on STARTS a
                            //   tracking-only run and sends the box to it.
                            if (detecting) detection.trackBox(box);
                            else startTrackingOnly(box);
                          },
                        }
                      : undefined
                  }
                  sinceLastFrameS={sinceLastFrameS}
                  predict={{
                    available: predictAvailable,
                    on: predictOn,
                    onToggle: () => setPredictOn((v) => !v),
                    live: livePredict,
                    onCopied: onPredictCopied,
                  }}
                />
              )}
            </Box>

            {sideMap && (
              <>
                <Splitter
                  orientation="vertical"
                  ariaLabel={t('Resize the map')}
                  valueNow={Math.round(mapFraction * 100)}
                  // Dragging the seam LEFT grows the map — as a share of the row.
                  onDragDelta={(d) => {
                    const width = rowRef.current?.clientWidth ?? 0;
                    if (width > 0) setMapFraction(mapFraction - d / width);
                  }}
                />
                <Box
                  component="section"
                  aria-label={t('Satellite map')}
                  data-testid="side-map"
                  sx={{
                    flex: `${mapFraction} 1 0px`,
                    minWidth: 0,
                    minHeight: 0,
                    display: 'flex',
                    flexDirection: 'column',
                    borderInlineStart: '1px solid var(--hairline)',
                    bgcolor: 'var(--bg-elevated)',
                  }}
                >
                  <Stack
                    direction="row"
                    alignItems="center"
                    spacing={1}
                    sx={{
                      height: 40,
                      px: 1.5,
                      flexShrink: 0,
                      borderBottom: '1px solid var(--hairline)',
                    }}
                  >
                    <MapOutlinedIcon fontSize="small" sx={{ color: 'var(--accent)' }} />
                    <Typography variant="subtitle2" sx={{ flex: 1, minWidth: 0 }} noWrap>
                      {t('Satellite map')}
                    </Typography>
                    {marks.length > 0 && (
                      <Typography variant="caption" className="le-mono" color="text.secondary">
                        {marks.length} {t('marks')}
                      </Typography>
                    )}
                    {popOutButton}
                    <Tooltip title={t('Dock the map below the video')}>
                      <IconButton
                        size="small"
                        onClick={() => setMapBeside(false)}
                        aria-label={t('Dock the map below the video')}
                      >
                        <VerticalAlignBottomOutlinedIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </Stack>
                  <Box sx={{ flex: 1, minHeight: 0, position: 'relative' }}>{mapDeck}</Box>
                </Box>
              </>
            )}
          </Box>

          {mapPopped && (
            <Stack
              direction="row"
              alignItems="center"
              spacing={1}
              role="status"
              sx={{
                px: 1.5,
                py: 0.5,
                flexShrink: 0,
                borderTop: '1px solid var(--hairline)',
                bgcolor: 'var(--accent-quiet)',
              }}
            >
              <MapOutlinedIcon fontSize="small" sx={{ color: 'var(--accent)' }} />
              <Typography variant="caption" sx={{ flex: 1, minWidth: 0 }} noWrap>
                {t('The satellite map is open in its own window.')}
              </Typography>
              <Button size="small" onClick={bringMapBack} sx={{ textTransform: 'none' }}>
                {t('Bring it back')}
              </Button>
            </Stack>
          )}

          <BottomDeck
            resizable={wide}
            counts={{ detections: marks.length, events: events.length }}
            tabs={deckTabs}
            actions={
              mapReady && !mapPopped && !sideMap ? (
                <>
                  {wide && (
                    <Tooltip title={t('Place the map beside the video')}>
                      <IconButton
                        size="small"
                        onClick={() => setMapBeside(true)}
                        aria-label={t('Place the map beside the video')}
                      >
                        <VerticalSplitOutlinedIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  )}
                  {popOutButton}
                </>
              ) : undefined
            }
          >
            {(tab) =>
              tab === 'map' ? (
                mapDeck
              ) : tab === 'detections' ? (
                <DetectionsDeck
                  marks={marks}
                  runStartedMs={runStartedMs}
                  selectedIndex={selectedMarkIndex}
                  onSelect={(i) =>
                    setSelection({
                      origin: 'table',
                      trackId: marks[i]?.track_id ?? null,
                      markIndex: i,
                    })
                  }
                  cameraName={camera.name}
                  trackNames={trackNames}
                  onRenameTrack={(id, name) => detection.nameTrack(id, name)}
                  trackFilter={trackFilter}
                  onTrackFilterChange={setTrackFilter}
                />
              ) : (
                <EventsDeck events={events} onClear={clear} />
              )
            }
          </BottomDeck>
        </Box>

        {!dataOnly && wide && inspectorOpen && (
          <>
            <Splitter
              orientation="vertical"
              ariaLabel={t('Resize the inspector')}
              valueNow={Math.round((inspectorPx / 560) * 100)}
              // Dragging the seam LEFT grows the inspector.
              onDragDelta={(d) => setInspectorPx(inspectorPx - d)}
            />
            <Box
              sx={{
                width: inspectorPx,
                flexShrink: 0,
                borderInlineStart: '1px solid var(--hairline)',
                bgcolor: 'var(--bg-elevated)',
                minHeight: 0,
                display: 'flex',
                flexDirection: 'column',
              }}
            >
              {/* ★ The panel can now FOLD (its settings are saved per camera and
                  the header's Edit settings reopens it), so it carries its own
                  close — before, it had no reason to. */}
              <Stack
                direction="row"
                alignItems="center"
                spacing={1}
                sx={{
                  height: 40,
                  px: 1.5,
                  flexShrink: 0,
                  borderBottom: '1px solid var(--hairline)',
                }}
              >
                <TuneOutlinedIcon fontSize="small" sx={{ color: 'var(--accent)' }} />
                <Typography variant="subtitle2" sx={{ flex: 1, minWidth: 0 }} noWrap>
                  {t('Detection settings')}
                </Typography>
                <Tooltip title={t('Close the settings panel')}>
                  <IconButton
                    size="small"
                    onClick={() => setInspectorOpen(false)}
                    aria-label={t('Close the settings panel')}
                  >
                    <CloseOutlinedIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              </Stack>
              <Box sx={{ flex: 1, minHeight: 0 }}>{inspector}</Box>
            </Box>
          </>
        )}
      </Box>

      {!dataOnly && !wide && (
        <Drawer
          anchor="right"
          open={sheetOpen}
          onClose={() => setSheetOpen(false)}
          PaperProps={{ sx: { width: 360 } }}
        >
          {inspector}
        </Drawer>
      )}

      {/* ── capture dialog: name + optional save folder (the tab's own flow) ── */}
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
              helperText={t(
                'Saved into the live-capture library. Letters, numbers, spaces — the rest is tidied for the filename.',
              )}
            />
            {hasNativeDirectoryPicker() && (
              <Box>
                <Button
                  variant="outlined"
                  startIcon={<FolderOpenOutlinedIcon />}
                  onClick={() => void pickDirectoryNative().then((dir) => dir && setSaveDir(dir))}
                >
                  {saveDir ? t('Change folder…') : t('Also save to a folder…')}
                </Button>
                {saveDir && (
                  <Typography
                    variant="caption"
                    color="text.secondary"
                    sx={{ display: 'block', mt: 1 }}
                  >
                    {t('A copy will be saved to:')} {saveDir}
                  </Typography>
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
            onClick={() =>
              capture.mutate({
                name: captureName.trim() || undefined,
                saveDir: saveDir || undefined,
              })
            }
            disabled={capture.isPending}
          >
            {capture.isPending ? t('Capturing…') : t('Capture')}
          </Button>
          <Button size="small" onClick={() => navigate('/cameras')} sx={{ display: 'none' }} />
        </DialogActions>
      </Dialog>
    </Box>
  );
}

export default CameraMonitorPage;

// Kept for callers that still reason about preview-ability by URL shape.
export { canPreviewInBrowser };
