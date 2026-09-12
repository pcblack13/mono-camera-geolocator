/**
 * `monitor/camera/VideoHero.tsx` — the picture, and everything drawn on it.
 *
 * ★ THE VIDEO IS THE HERO: it fills whatever the page leaves it, letterboxed on the
 *   media well. What sits on top is thin — the status chip, the overlay toggles at
 *   bottom-left, fullscreen / PiP / freeze at top-right — and everything drawn IN
 *   the picture (boxes, ids, the drift ghost) rides on one canvas overlay sized to
 *   the frame.
 *
 * ★ ONE MJPEG SOCKET. While a run is on, the picture is the detector's own stream
 *   (the device admits one opener; the boxes are burned in server-side); otherwise
 *   it is the live preview — canvas when measured, `<img>` when the source blocks
 *   reads. Never both. PiP moves THIS element into a Document Picture-in-Picture
 *   window where the browser offers one; there is no second player.
 *
 * ★ Freeze-frame copies the current picture onto a still canvas and shows that,
 *   while the stream keeps flowing underneath — a look, not a pause.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type JSX,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
} from 'react';
import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import IconButton from '@mui/material/IconButton';
import Stack from '@mui/material/Stack';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import AcUnitOutlinedIcon from '@mui/icons-material/AcUnitOutlined';
import CenterFocusStrongOutlinedIcon from '@mui/icons-material/CenterFocusStrongOutlined';
import HighlightAltOutlinedIcon from '@mui/icons-material/HighlightAltOutlined';
import ContentCopyOutlinedIcon from '@mui/icons-material/ContentCopyOutlined';
import PushPinOutlinedIcon from '@mui/icons-material/PushPinOutlined';
import FullscreenIcon from '@mui/icons-material/Fullscreen';
import FullscreenExitIcon from '@mui/icons-material/FullscreenExit';
import PictureInPictureAltOutlinedIcon from '@mui/icons-material/PictureInPictureAltOutlined';
import RefreshIcon from '@mui/icons-material/Refresh';
import UsbOffIcon from '@mui/icons-material/UsbOff';
import ZoomInIcon from '@mui/icons-material/ZoomIn';
import ZoomOutIcon from '@mui/icons-material/ZoomOut';

import type { DetectionLatest } from '../../../api/detection';
import type { DriftVerdict } from '../../../api/drift';
import type { FeedStatus, ViewMode } from '../../../hooks/useLiveFeed';
import type { LivePredict, PixelAsk } from '../../../hooks/useLivePredict';
import { containRect, cssToMedia, mediaToCss } from '../../../lib/monitor/fit';
import {
  HOME_VIEW,
  MAX_ZOOM,
  ZOOM_STEP,
  clampView,
  layerRect,
  zoomAround,
  type ZoomView,
} from '../../../lib/monitor/zoom';
import type { OverlayToggles } from '../../../store/monitorLayoutStore';
import { MEDIA_WELL, ON_MEDIA } from '../../../theme/paint';

/** The scrim under on-media chrome — dark in both themes, because the well is. */
const ON_MEDIA_SCRIM = 'rgba(0,0,0,0.6)';
import { DriftOverlay } from '../../drift/DriftOverlay';
import { CrosshairCursor } from '../../image/CrosshairCursor';
import { StreamImage } from '../../live/StreamImage';
import { t } from '../../../i18n';
import { DetectionOverlay } from './DetectionOverlay';

export interface VideoHeroProps {
  cameraName: string;
  /** The live preview URL (null while a run holds the source). */
  previewUrl: string | null;
  /** The detector's own MJPEG while a run is on. */
  detectionStreamUrl: string | null;
  mode: ViewMode;
  status: FeedStatus;
  streamError: string | null;
  canvasRef: RefObject<HTMLCanvasElement>;
  onImgError: () => void;
  onReconnect: () => void;
  latest: DetectionLatest | null;
  /** ★ The SENDER'S own boxes (2026-09-08) — a camera that detects on its own
   *  hardware, drawn the moment the picture appears with no run of ours. Null
   *  whenever one of our runs is on: two detectors on one picture is the
   *  "duplicated, unstable annotations" defect, and the page enforces it. */
  piLatest: DetectionLatest | null;
  /** A click on one of the SENDER'S boxes, by index into `piLatest.boxes`.
   *  Undefined leaves that overlay non-interactive. */
  onSenderBoxClick?: (index: number) => void;
  driftVerdict: DriftVerdict | null;
  toggles: OverlayToggles;
  onToggle: (k: keyof OverlayToggles) => void;
  selectedTrack: number | null;
  onSelectBox: (trackId: number | null, index: number) => void;
  /** ★ Manual tracking (2026-09-03): on while the operator is tracking; a click on
   *  the picture then tracks the object (double-click locks it as primary). */
  trackingMode?: boolean;
  primaryTrack?: number | null;
  onTrackAt?: (u: number, v: number) => void;
  onLockAt?: (u: number, v: number) => void;
  /** Seconds since the last frame, for the LOST chip. */
  sinceLastFrameS: number | null;
  /**
   * ★ LIVE PREDICT (2026-09-10, owner ask): point at any pixel of the stream
   *   and read where it lands, through the camera's lookup table — the GCP
   *   editor's live predict, for the live picture. Offered only when the camera
   *   has a table. While it is on, a surface over the picture takes the pointer:
   *   moving asks, a click pins, Copy (or `c`) copies "lat, lon, elevation".
   */
  predict?: VideoPredictProps;
  /**
   * ★ DRAW A BOX TO TRACK (2026-09-11, owner ask): outline any object on the
   *   picture and the tracker follows it — a click can only track what YOLO
   *   found; a box tracks what the operator SEES. Offered while a run is on.
   */
  trackBox?: VideoTrackBoxProps;
  /** The operator's names for tracks, for the labels on the picture. */
  trackNames?: Record<string, string>;
}

export interface VideoTrackBoxProps {
  on: boolean;
  onToggle: () => void;
  /** The drawn rectangle, in MEDIA pixels, corners ordered. */
  onDraw: (box: { x1: number; y1: number; x2: number; y2: number }) => void;
  /**
   * ★ The run's MEDIA size, when a run is on (owner report 2026-09-11: boxes
   *   landed far from where they were drawn). The picture shown during a run is
   *   the server's burned-in preview, resized to 1280 wide — its own pixel size
   *   is NOT the coordinate space the server tracks in. Same rule the box
   *   overlay follows: map through the media size, never the picture's.
   */
  mediaSize?: { w: number; h: number } | null;
}

export interface VideoPredictProps {
  /** The camera has a lookup table, so the tool can be offered. */
  available: boolean;
  on: boolean;
  onToggle: () => void;
  live: LivePredict;
  /** What Copy put on the clipboard (null when there was nothing to copy). */
  onCopied: (text: string | null) => void;
}

/** The picture's own pixel size — the canvas's, or the `<img>`'s natural size. */
function mediaSizeOf(stage: HTMLElement | null): { w: number; h: number } | null {
  const src = stage?.querySelector<HTMLCanvasElement | HTMLImageElement>(
    'canvas[data-picture], img[data-picture], img[data-detection-picture]',
  );
  if (!src) return null;
  const w = src instanceof HTMLImageElement ? src.naturalWidth : src.width;
  const h = src instanceof HTMLImageElement ? src.naturalHeight : src.height;
  return w > 0 && h > 0 ? { w, h } : null;
}

interface DocumentPiP {
  requestWindow: (opts?: { width?: number; height?: number }) => Promise<Window>;
}

function documentPiP(): DocumentPiP | null {
  const w = window as unknown as { documentPictureInPicture?: DocumentPiP };
  return w.documentPictureInPicture ?? null;
}

export function VideoHero(p: VideoHeroProps): JSX.Element {

  const stageRef = useRef<HTMLDivElement | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const [frozen, setFrozen] = useState<string | null>(null);
  const [pip, setPip] = useState<Window | null>(null);

  // ── live predict: the cursor on the picture, in media pixels ──
  const predict = p.predict;
  const predictOn = predict !== undefined && predict.available && predict.on;
  const [hoverCss, setHoverCss] = useState<{ x: number; y: number } | null>(null);
  // The surface's CSS size — the picker's crosshair draws hairlines across the
  // whole picture, so it needs the box, not just the point.
  const [surfaceSize, setSurfaceSize] = useState<{ w: number; h: number }>({ w: 0, h: 0 });
  const [mediaSize, setMediaSize] = useState<{ w: number; h: number } | null>(null);

  // ── zoom + pan ──
  const [view, setView] = useState<ZoomView>(HOME_VIEW);
  const viewRef = useRef<ZoomView>(view);
  viewRef.current = view;
  const [dragging, setDragging] = useState(false);
  const suppressClick = useRef(false);
  const stageBox = (): { w: number; h: number } => {
    const r = stageRef.current?.getBoundingClientRect();
    return { w: r?.width ?? 0, h: r?.height ?? 0 };
  };
  const zoomStep = (factor: number): void => {
    const { w, h } = stageBox();
    setView((v) => zoomAround(v, factor, 0, 0, w, h));
  };
  const resetZoom = (): void => setView(HOME_VIEW);
  // A source that is gone has nothing to zoom into: the message reads at 1:1.
  useEffect(() => {
    if (p.status === 'refused' || p.status === 'lost') setView(HOME_VIEW);
  }, [p.status]);
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return undefined;
    // ★ Native, non-passive: React registers wheel as passive, and a passive
    //   listener cannot stop the page from scrolling under the zoom.
    const onWheel = (e: WheelEvent): void => {
      e.preventDefault();
      const rect = stage.getBoundingClientRect();
      const cx = e.clientX - rect.left - rect.width / 2;
      const cy = e.clientY - rect.top - rect.height / 2;
      setView((v) =>
        zoomAround(v, e.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP, cx, cy, rect.width, rect.height),
      );
    };
    // ★ DRAG TO PAN, IN THE CAPTURE PHASE so it works through every overlay: a
    //   movement past 4 px becomes a drag, the stage captures the pointer, and
    //   the click that the release would produce is swallowed once — so a pan
    //   never selects a box, tracks an object or pins a reading by accident.
    let start: { x: number; y: number; px: number; py: number } | null = null;
    let dragged = false;
    const onDown = (e: PointerEvent): void => {
      if (e.button === 0 && viewRef.current.zoom <= 1) return; // nothing to pan
      if (e.button !== 0 && e.button !== 1) return;
      start = { x: e.clientX, y: e.clientY, px: viewRef.current.x, py: viewRef.current.y };
      dragged = false;
    };
    const onMove = (e: PointerEvent): void => {
      if (start === null) return;
      const dx = e.clientX - start.x;
      const dy = e.clientY - start.y;
      if (!dragged && Math.hypot(dx, dy) < 4) return;
      if (!dragged) {
        dragged = true;
        setDragging(true);
        try {
          stage.setPointerCapture(e.pointerId);
        } catch {
          /* jsdom */
        }
      }
      const rect = stage.getBoundingClientRect();
      const from = start;
      setView((v) => clampView({ zoom: v.zoom, x: from.px + dx, y: from.py + dy }, rect.width, rect.height));
    };
    const onUp = (e: PointerEvent): void => {
      if (start === null) return;
      if (dragged) {
        suppressClick.current = true;
        setDragging(false);
        try {
          stage.releasePointerCapture(e.pointerId);
        } catch {
          /* jsdom */
        }
      }
      start = null;
    };
    const onClickCapture = (e: MouseEvent): void => {
      if (!suppressClick.current) return;
      suppressClick.current = false;
      e.stopPropagation();
      e.preventDefault();
    };
    stage.addEventListener('wheel', onWheel, { passive: false });
    stage.addEventListener('pointerdown', onDown, true);
    stage.addEventListener('pointermove', onMove, true);
    stage.addEventListener('pointerup', onUp, true);
    stage.addEventListener('pointercancel', onUp, true);
    stage.addEventListener('click', onClickCapture, true);
    return () => {
      stage.removeEventListener('wheel', onWheel);
      stage.removeEventListener('pointerdown', onDown, true);
      stage.removeEventListener('pointermove', onMove, true);
      stage.removeEventListener('pointerup', onUp, true);
      stage.removeEventListener('pointercancel', onUp, true);
      stage.removeEventListener('click', onClickCapture, true);
    };
  }, []);
  /**
   * ★ THE COORDINATE SPACE EVERYTHING ON THE PICTURE IS IN. During a run the
   *   picture is a resized preview, so its own pixel size lies about the media;
   *   the run's frame size (from the latest payload, or the session) is the truth,
   *   and the raw feed's canvas is the truth only when nothing runs.
   */
  const mediaDims = useCallback((): { w: number; h: number } | null => {
    if (p.latest !== null && p.latest.width > 0 && p.latest.height > 0) {
      return { w: p.latest.width, h: p.latest.height };
    }
    const fromRun = p.trackBox?.mediaSize;
    if (fromRun && fromRun.w > 0 && fromRun.h > 0) return fromRun;
    return mediaSizeOf(stageRef.current);
  }, [p.latest, p.trackBox?.mediaSize]);

  /** The pointer's place → the media pixel under it (null off the picture). */
  const askAt = useCallback(
    (e: ReactPointerEvent<HTMLDivElement>): { ask: PixelAsk; css: { x: number; y: number } } | null => {
      const media = mediaDims();
      if (media === null) return null;
      setMediaSize((m) => (m !== null && m.w === media.w && m.h === media.h ? m : media));
      const rect = e.currentTarget.getBoundingClientRect();
      setSurfaceSize((sz) =>
        sz.w === rect.width && sz.h === rect.height ? sz : { w: rect.width, h: rect.height },
      );
      const css = { x: e.clientX - rect.left, y: e.clientY - rect.top };
      // ★ Through the ZOOM: the picture is contain-fit inside the zoom layer, and
      //   the layer is scaled and panned over the stage — so the pointer is taken
      //   into the layer first, then through the same fit the boxes use.
      const layer = layerRect(viewRef.current, rect.width, rect.height);
      const fit = containRect(layer.w, layer.h, media.w, media.h);
      const uv = cssToMedia(fit, css.x - layer.x, css.y - layer.y);
      if (uv === null) return null;
      return { ask: { u: uv[0], v: uv[1], w: media.w, h: media.h }, css };
    },
    [mediaDims],
  );
  // ── draw a box to track ──
  // ★ The drag lives in CSS pixels on the surface (so the rectangle is drawn
  //   where the pointer is, through any zoom) and is converted to MEDIA pixels
  //   only at release, through the same mapping the predict tool uses.
  const [boxDrag, setBoxDrag] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(
    null,
  );
  const boxOn = p.trackBox?.on === true;
  const onBoxDown = (e: ReactPointerEvent<HTMLDivElement>): void => {
    if (e.button !== 0) return;
    e.stopPropagation();
    e.currentTarget.setPointerCapture?.(e.pointerId);
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    setBoxDrag({ x0: x, y0: y, x1: x, y1: y });
  };
  const onBoxMove = (e: ReactPointerEvent<HTMLDivElement>): void => {
    if (boxDrag === null) return;
    const rect = e.currentTarget.getBoundingClientRect();
    setBoxDrag({ ...boxDrag, x1: e.clientX - rect.left, y1: e.clientY - rect.top });
  };
  const onBoxUp = (e: ReactPointerEvent<HTMLDivElement>): void => {
    if (boxDrag === null) return;
    e.stopPropagation();
    const drag = boxDrag;
    setBoxDrag(null);
    const media = mediaDims();
    if (media === null || p.trackBox === undefined) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const layer = layerRect(viewRef.current, rect.width, rect.height);
    const fit = containRect(layer.w, layer.h, media.w, media.h);
    const a = cssToMedia(fit, drag.x0 - layer.x, drag.y0 - layer.y);
    const b = cssToMedia(fit, drag.x1 - layer.x, drag.y1 - layer.y);
    if (a === null || b === null) return;
    const box = {
      x1: Math.min(a[0], b[0]),
      y1: Math.min(a[1], b[1]),
      x2: Math.max(a[0], b[0]),
      y2: Math.max(a[1], b[1]),
    };
    // ★ A CLICK IS NOT A BOX (owner, 2026-09-11): a bare press on the picture
    //   must draw nothing. A small target is outlined zoomed in.
    if (box.x2 - box.x1 < 4 || box.y2 - box.y1 < 4) return;
    p.trackBox.onDraw(box);
  };

  const onPredictMove = (e: ReactPointerEvent<HTMLDivElement>): void => {
    if (predict === undefined) return;
    const hit = askAt(e);
    setHoverCss(hit === null ? null : hit.css);
    if (hit === null) predict.live.leave();
    else predict.live.cursor(hit.ask);
  };
  const onPredictLeave = (): void => {
    setHoverCss(null);
    predict?.live.leave();
  };
  // A CLICK pins (not the press): a press that turns into a pan must not pin.
  const onPredictClick = (e: ReactPointerEvent<HTMLDivElement>): void => {
    if (predict === undefined) return;
    const hit = askAt(e);
    if (hit === null) return;
    predict.live.pin(hit.ask); // a pin while pinned releases and re-asks here
  };
  // The pinned reading's place on the stage follows the zoom and pan: it is
  // recomputed from the pinned PIXEL, never remembered as a screen position.
  const pinCss = useMemo((): { x: number; y: number } | null => {
    const reading = predict?.live.prediction ?? null;
    if (predict === undefined || !predict.live.pinned || reading === null) return null;
    if (mediaSize === null || surfaceSize.w <= 0 || surfaceSize.h <= 0) return null;
    const layer = layerRect(view, surfaceSize.w, surfaceSize.h);
    const fit = containRect(layer.w, layer.h, mediaSize.w, mediaSize.h);
    const [x, y] = mediaToCss(fit, reading.u, reading.v);
    return { x: layer.x + x, y: layer.y + y };
  }, [predict, mediaSize, surfaceSize, view]);
  // `c` copies whatever the readout shows — the cursor cannot reach a button
  // without leaving the pixel it is reading.
  useEffect(() => {
    if (!predictOn || predict === undefined) return undefined;
    const onKey = (e: KeyboardEvent): void => {
      if (e.key !== 'c' || e.ctrlKey || e.metaKey || e.altKey) return;
      const target = e.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      void predict.live.copy().then(predict.onCopied);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [predictOn, predict]);
  const reading = predict?.live.prediction ?? null;
  const readout =
    !predictOn
      ? null
      : reading === null
        ? t('Point at the picture')
        : reading.placed && reading.lat !== null && reading.lon !== null
          ? `px ${reading.u.toFixed(0)}, ${reading.v.toFixed(0)} · ${reading.lat.toFixed(6)}, ${reading.lon.toFixed(6)} · z ${
              reading.elevationM === null ? '—' : `${reading.elevationM.toFixed(1)} m`
            }`
          : reading.reason === 'off_table'
            ? t('Outside the table')
            : t('Sky, or ground the table does not cover');

  useEffect(() => {
    const onChange = (): void => setFullscreen(document.fullscreenElement === stageRef.current);
    document.addEventListener('fullscreenchange', onChange);
    return () => document.removeEventListener('fullscreenchange', onChange);
  }, []);

  const toggleFullscreen = (): void => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else if (stageRef.current) void stageRef.current.requestFullscreen();
  };

  /** Copy the current picture — whichever element is showing it — to a still. */
  const freeze = useCallback((): void => {
    if (frozen !== null) {
      setFrozen(null);
      return;
    }
    const stage = stageRef.current;
    if (!stage) return;
    const src = stage.querySelector<HTMLCanvasElement | HTMLImageElement>(
      'canvas[data-picture], img[data-picture]',
    );
    if (!src) return;
    const w = src instanceof HTMLImageElement ? src.naturalWidth : src.width;
    const h = src instanceof HTMLImageElement ? src.naturalHeight : src.height;
    if (w <= 0 || h <= 0) return;
    const still = document.createElement('canvas');
    still.width = w;
    still.height = h;
    try {
      still.getContext('2d')?.drawImage(src, 0, 0);
      setFrozen(still.toDataURL('image/jpeg', 0.85));
    } catch {
      // a cross-origin <img> taints the canvas — a freeze is not possible there
      setFrozen(null);
    }
  }, [frozen]);

  const togglePip = async (): Promise<void> => {
    if (pip !== null) {
      pip.close();
      setPip(null);
      return;
    }
    const api = documentPiP();
    const stage = stageRef.current;
    if (api === null || stage === null) return;
    const win = await api.requestWindow({ width: 640, height: 360 });
    // ★ The SAME element moves; nothing is re-created, no second socket opens.
    const placeholder = document.createElement('div');
    stage.parentElement?.insertBefore(placeholder, stage);
    win.document.body.style.margin = '0';
    win.document.body.style.background = MEDIA_WELL;
    win.document.body.append(stage);
    win.addEventListener('pagehide', () => {
      placeholder.replaceWith(stage);
      setPip(null);
    });
    setPip(win);
  };

  const pipAvailable = documentPiP() !== null;
  const live = p.status === 'live';
  const chip =
    p.status === 'connecting'
      ? { label: t('connecting…'), bg: 'var(--status-warn)', fg: 'var(--text-inverse)' }
      : p.status === 'live'
        ? { label: 'LIVE', bg: 'var(--status-ok)', fg: 'var(--text-inverse)' }
        : p.status === 'lost'
          ? {
              label: `${t('LOST')}${p.sinceLastFrameS !== null ? ` · ${p.sinceLastFrameS}s` : ''}`,
              bg: 'var(--status-error)',
              fg: ON_MEDIA,
            }
          : p.status === 'refused'
            ? { label: t('REFUSED'), bg: 'var(--status-error)', fg: ON_MEDIA }
            : null;

  return (
    <Box
      ref={stageRef}
      data-testid="video-hero"
      sx={{
        position: 'relative',
        flex: 1,
        minHeight: 240,
        bgcolor: MEDIA_WELL,
        overflow: 'hidden',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        cursor: dragging ? 'grabbing' : view.zoom > 1 && !predictOn ? 'grab' : undefined,
        touchAction: 'none',
      }}
    >
      {/* ── the zoom layer: the picture and everything drawn on it ── */}
      <Box
        data-zoom-layer
        data-testid="zoom-layer"
        sx={{
          position: 'absolute',
          inset: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          transformOrigin: 'center center',
        }}
        // Inline, not sx: the transform changes on every wheel tick and drag
        // move, and each distinct sx value would mint a new stylesheet class.
        style={{
          transform:
            view.zoom === 1 ? undefined : `translate(${view.x}px, ${view.y}px) scale(${view.zoom})`,
          willChange: view.zoom === 1 ? undefined : 'transform',
        }}
      >
      {/* ── the picture ── */}
      {p.detectionStreamUrl !== null ? (
        <StreamImage
          src={p.detectionStreamUrl}
          alt={`${t('Detecting')}: ${p.cameraName}`}
          dataPicture
          style={{ display: 'block', width: '100%', height: '100%', objectFit: 'contain' }}
        />
      ) : p.status === 'refused' ? (
        <Stack alignItems="center" spacing={1} sx={{ py: 6, px: 3, textAlign: 'center' }}>
          <UsbOffIcon sx={{ fontSize: 40, color: 'var(--status-error)' }} />
          <Typography variant="subtitle2" sx={{ color: 'var(--status-error)' }}>
            {t('This source could not be opened')}
          </Typography>
          <Typography variant="caption" sx={{ color: ON_MEDIA, opacity: 0.7, maxWidth: 520 }}>
            {p.streamError}
          </Typography>
          {/* ★ Not a dead end (2026-09-02): the feed retries by itself every 10 s,
              and the button is for the operator who just replugged the cable. */}
          <Typography variant="caption" sx={{ color: ON_MEDIA, opacity: 0.5 }}>
            {t('Retrying automatically — or press Reconnect after replugging.')}
          </Typography>
          <IconButton
            size="small"
            onClick={p.onReconnect}
            aria-label={t('Reconnect')}
            sx={{ color: ON_MEDIA }}
          >
            <RefreshIcon />
          </IconButton>
        </Stack>
      ) : p.status === 'lost' ? (
        <Stack alignItems="center" spacing={1} sx={{ py: 6, px: 3, textAlign: 'center' }}>
          <UsbOffIcon sx={{ fontSize: 40, color: 'var(--status-warn)' }} />
          <Typography variant="subtitle2" sx={{ color: 'var(--status-warn)' }}>
            {t('Stream disconnected')}
          </Typography>
          <Typography variant="caption" sx={{ color: ON_MEDIA, opacity: 0.6, maxWidth: 460 }}>
            {t('Frames stopped arriving from')} <b>{p.cameraName}</b>
            {t(
              '. This is not a delay — the video has stopped. Reconnect the device (or check the camera) and press Reconnect.',
            )}
          </Typography>
          <IconButton
            size="small"
            onClick={p.onReconnect}
            aria-label={t('Reconnect')}
            sx={{ color: ON_MEDIA }}
          >
            <RefreshIcon />
          </IconButton>
        </Stack>
      ) : p.mode === 'img' ? (
        // ★ StreamImage, not a bare <img> (2026-09-02): it blanks src on unmount,
        //   which is what actually aborts a zombie MJPEG download that would
        //   otherwise hold a DEVICE against the next viewer.
        <StreamImage
          src={p.previewUrl ?? ''}
          alt={`${t('Live stream')}: ${p.cameraName}`}
          onError={p.onImgError}
          dataPicture
          style={{ display: 'block', width: '100%', height: '100%', objectFit: 'contain' }}
        />
      ) : (
        <canvas
          ref={p.canvasRef}
          data-picture
          style={{ display: 'block', width: '100%', height: '100%', objectFit: 'contain' }}
          aria-label={`${t('Live stream')}: ${p.cameraName}`}
        />
      )}

      {/* ── the still, over the flowing picture ── */}
      {frozen !== null && (
        <Box
          component="img"
          src={frozen}
          alt={t('Frozen frame')}
          sx={{
            position: 'absolute',
            inset: 0,
            width: '100%',
            height: '100%',
            objectFit: 'contain',
          }}
        />
      )}

      {/* ── everything drawn IN the picture ── */}
      <DetectionOverlay
        latest={p.latest}
        toggles={p.toggles}
        selectedTrack={p.selectedTrack}
        onSelect={p.onSelectBox}
        pictureHasBoxes={p.detectionStreamUrl !== null}
        trackingMode={p.trackingMode}
        primaryTrack={p.primaryTrack}
        onTrackAt={p.onTrackAt}
        onLockAt={p.onLockAt}
      />
      {/* ★ The sender's own boxes, ON TOP so the click reaches them. It never
          coexists with a run of ours (the page gates it on `detecting`), so the
          canvas below has nothing to draw and nothing to be stolen from.
          `onSelect`, not `trackingMode`: tracking mode rings every box that has
          an id, which would paint the sender's UNtracked detections as though
          we were already following them. */}
      {p.piLatest !== null && (
        <DetectionOverlay
          latest={p.piLatest}
          toggles={p.toggles}
          selectedTrack={null}
          pictureHasBoxes={p.detectionStreamUrl !== null}
          onSelect={
            p.onSenderBoxClick === undefined
              ? undefined
              : (_trackId, index) => p.onSenderBoxClick?.(index)
          }
        />
      )}
      {p.toggles.drift && <DriftOverlay verdict={p.driftVerdict} />}
      </Box>

      {/* ── draw a box to track: the surface that takes the drag ── */}
      {boxOn && p.trackBox !== undefined && (
        <Box
          data-testid="track-box-surface"
          role="application"
          aria-label={t('Draw a box to track')}
          onPointerDown={onBoxDown}
          onPointerMove={onBoxMove}
          onPointerUp={onBoxUp}
          onPointerCancel={() => setBoxDrag(null)}
          sx={{ position: 'absolute', inset: 0, cursor: 'crosshair', zIndex: 6, touchAction: 'none' }}
        >
          {boxDrag !== null && (
            <Box
              data-testid="track-box-rubber"
              sx={{
                position: 'absolute',
                left: Math.min(boxDrag.x0, boxDrag.x1),
                top: Math.min(boxDrag.y0, boxDrag.y1),
                width: Math.abs(boxDrag.x1 - boxDrag.x0),
                height: Math.abs(boxDrag.y1 - boxDrag.y0),
                border: '2px dashed var(--accent)',
                bgcolor: 'var(--accent-ghost, transparent)',
                pointerEvents: 'none',
              }}
            />
          )}
          {boxDrag === null && (
            <Typography
              variant="caption"
              sx={{
                position: 'absolute',
                left: 8,
                bottom: 40,
                px: 1,
                py: 0.25,
                borderRadius: 1,
                bgcolor: ON_MEDIA_SCRIM,
                color: ON_MEDIA,
                pointerEvents: 'none',
              }}
            >
              {t('Drag a box around the object to track it')}
            </Typography>
          )}
        </Box>
      )}

      {/* ── live predict: the surface that reads the cursor, and its readout ── */}
      {predictOn && predict !== undefined && (
        <>
          <Box
            data-testid="predict-surface"
            role="application"
            aria-label={t('Live predict')}
            onPointerMove={onPredictMove}
            onPointerLeave={onPredictLeave}
            onClick={onPredictClick}
            sx={{ position: 'absolute', inset: 0, cursor: 'crosshair', zIndex: 5 }}
          >
            {/* ★ THE SAME CROSSHAIR AS THE GCP PICKER (owner ask 2026-09-10): hairlines
                across the whole picture, a ring and a centre dot — pixel-sharp at
                any size, and never in the way of the click it is aiming. */}
            {hoverCss !== null && (
              <CrosshairCursor
                visible
                x={hoverCss.x}
                y={hoverCss.y}
                width={surfaceSize.w}
                height={surfaceSize.h}
                color={ON_MEDIA}
              />
            )}
            {pinCss !== null && (
              <Box
                aria-hidden
                data-testid="predict-pin"
                sx={{
                  position: 'absolute',
                  left: pinCss.x - 7,
                  top: pinCss.y - 7,
                  width: 14,
                  height: 14,
                  borderRadius: '50%',
                  border: '2px solid var(--accent)',
                  bgcolor: 'rgba(53,200,216,0.25)',
                  pointerEvents: 'none',
                  zIndex: 3,
                  '&::after': {
                    content: '""',
                    position: 'absolute',
                    left: 4,
                    top: 4,
                    width: 2,
                    height: 2,
                    borderRadius: '50%',
                    bgcolor: 'var(--accent)',
                  },
                }}
              />
            )}
          </Box>
          <Stack
            direction="row"
            spacing={0.5}
            alignItems="center"
            role="status"
            aria-live="polite"
            data-testid="predict-readout"
            onPointerDown={(e) => e.stopPropagation()}
            sx={{
              position: 'absolute',
              bottom: 40,
              insetInlineEnd: 8,
              zIndex: 6,
              px: 1,
              py: 0.25,
              borderRadius: 1,
              bgcolor: ON_MEDIA_SCRIM,
              color: ON_MEDIA,
              fontFamily: 'var(--font-mono)',
              fontSize: 12,
              maxWidth: 'calc(100% - 16px)',
            }}
          >
            <CenterFocusStrongOutlinedIcon sx={{ fontSize: 16, color: 'var(--accent)' }} />
            <Box component="span" sx={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {readout}
            </Box>
            {predict.live.pending && (
              <Box component="span" sx={{ opacity: 0.6 }}>
                …
              </Box>
            )}
            {predict.live.pinned && (
              <Tooltip title={t('Pinned — click the picture to release')}>
                <PushPinOutlinedIcon sx={{ fontSize: 15, color: 'var(--accent)' }} />
              </Tooltip>
            )}
            <Tooltip title={t('Copy the coordinates (c)')}>
              <span>
                <IconButton
                  size="small"
                  disabled={predict.live.copyText === null}
                  onClick={() => void predict.live.copy().then(predict.onCopied)}
                  aria-label={t('Copy the coordinates')}
                  sx={{ color: ON_MEDIA, p: 0.25 }}
                >
                  <ContentCopyOutlinedIcon sx={{ fontSize: 15 }} />
                </IconButton>
              </span>
            </Tooltip>
          </Stack>
        </>
      )}

      {/* ── top-right: status + window controls ── */}
      <Stack
        direction="row"
        spacing={0.5}
        // ★ Above the predict surface (z 5): the window controls must stay clickable
        //   while the tool has the picture.
        sx={{ position: 'absolute', top: 8, insetInlineEnd: 8, zIndex: 7 }}
      >
        {chip !== null && (
          <Chip
            size="small"
            label={chip.label}
            sx={{ bgcolor: chip.bg, color: chip.fg, fontFamily: 'var(--font-mono)', fontSize: 11 }}
          />
        )}
        <Tooltip title={t('Zoom out')}>
          <span>
            <IconButton
              size="small"
              onClick={() => zoomStep(1 / ZOOM_STEP)}
              disabled={view.zoom <= 1}
              aria-label={t('Zoom out')}
              sx={{ bgcolor: ON_MEDIA_SCRIM, color: ON_MEDIA }}
            >
              <ZoomOutIcon fontSize="small" />
            </IconButton>
          </span>
        </Tooltip>
        {view.zoom !== 1 && (
          <Tooltip title={t('Reset zoom')}>
            <Chip
              size="small"
              label={`${view.zoom.toFixed(1)}×`}
              onClick={resetZoom}
              aria-label={t('Reset zoom')}
              data-testid="zoom-chip"
              sx={{
                bgcolor: ON_MEDIA_SCRIM,
                color: 'var(--accent)',
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
              }}
            />
          </Tooltip>
        )}
        <Tooltip title={t('Zoom in')}>
          <span>
            <IconButton
              size="small"
              onClick={() => zoomStep(ZOOM_STEP)}
              disabled={view.zoom >= MAX_ZOOM}
              aria-label={t('Zoom in')}
              sx={{ bgcolor: ON_MEDIA_SCRIM, color: ON_MEDIA }}
            >
              <ZoomInIcon fontSize="small" />
            </IconButton>
          </span>
        </Tooltip>
        <Tooltip title={frozen !== null ? t('Unfreeze') : t('Freeze frame')}>
          <span>
            <IconButton
              size="small"
              onClick={freeze}
              disabled={!live && p.detectionStreamUrl === null}
              aria-label={frozen !== null ? t('Unfreeze') : t('Freeze frame')}
              aria-pressed={frozen !== null}
              sx={{
                bgcolor: ON_MEDIA_SCRIM,
                color: frozen !== null ? 'var(--accent)' : ON_MEDIA,
              }}
            >
              <AcUnitOutlinedIcon fontSize="small" />
            </IconButton>
          </span>
        </Tooltip>
        <Tooltip
          title={
            pipAvailable
              ? t('Picture in picture')
              : t('Picture in picture is not supported in this browser')
          }
        >
          <span>
            <IconButton
              size="small"
              onClick={() => void togglePip()}
              disabled={!pipAvailable}
              aria-label={t('Picture in picture')}
              aria-pressed={pip !== null}
              sx={{ bgcolor: ON_MEDIA_SCRIM, color: ON_MEDIA }}
            >
              <PictureInPictureAltOutlinedIcon fontSize="small" />
            </IconButton>
          </span>
        </Tooltip>
        <Tooltip title={fullscreen ? t('Exit fullscreen') : t('Fullscreen')}>
          <IconButton
            size="small"
            onClick={toggleFullscreen}
            aria-label={fullscreen ? t('Exit fullscreen') : t('Fullscreen')}
            sx={{ bgcolor: ON_MEDIA_SCRIM, color: ON_MEDIA }}
          >
            {fullscreen ? (
              <FullscreenExitIcon fontSize="small" />
            ) : (
              <FullscreenIcon fontSize="small" />
            )}
          </IconButton>
        </Tooltip>
      </Stack>

      {/* ── bottom-left: what is drawn ── */}
      <Stack
        direction="row"
        spacing={0.5}
        // ★ Above the predict surface too — a real click on "Predict" must switch the
        //   tool OFF, not pin a reading under the chip (seen 2026-09-10).
        sx={{ position: 'absolute', bottom: 8, insetInlineStart: 8, zIndex: 7 }}
      >
        {(
          [
            ['boxes', 'Boxes'],
            ['labels', 'Labels'],
            ['tracks', 'Tracks'],
            ['hud', 'HUD'],
            ['drift', 'Drift ghost'],
            ['piBoxes', 'Sender boxes'],
          ] as const
        ).map(([k, label]) => (
          // ★ The chips work THROUGH a run too (2026-09-01). The run's boxes are
          //   burned into the stream itself (frame-synced), and the page pushes
          //   these toggles INTO the session — the burn then draws only what is
          //   asked, taking effect on the next frame. One rendering per box,
          //   steerable at all times; the greyed-out state is gone.
          <Chip
            key={k}
            size="small"
            label={t(label)}
            onClick={() => p.onToggle(k)}
            variant={p.toggles[k] ? 'filled' : 'outlined'}
            role="switch"
            aria-checked={p.toggles[k]}
            sx={{
              height: 24,
              fontSize: 11,
              bgcolor: ON_MEDIA_SCRIM,
              color: p.toggles[k] ? 'var(--accent)' : ON_MEDIA,
              opacity: p.toggles[k] ? 1 : 0.75,
              borderColor: 'var(--hairline-strong)',
            }}
          />
        ))}
        {p.trackBox !== undefined && (
          <Chip
            size="small"
            icon={<HighlightAltOutlinedIcon sx={{ fontSize: 14 }} />}
            label={t('Track box')}
            onClick={p.trackBox.onToggle}
            variant={boxOn ? 'filled' : 'outlined'}
            role="switch"
            aria-checked={boxOn}
            sx={{
              'height': 24,
              'fontSize': 11,
              'bgcolor': ON_MEDIA_SCRIM,
              'color': boxOn ? 'var(--accent)' : ON_MEDIA,
              'opacity': boxOn ? 1 : 0.75,
              'borderColor': 'var(--hairline-strong)',
              '& .MuiChip-icon': { color: 'inherit' },
            }}
          />
        )}
        {predict !== undefined && predict.available && (
          <Chip
            size="small"
            icon={<CenterFocusStrongOutlinedIcon sx={{ fontSize: 14 }} />}
            label={t('Predict')}
            onClick={predict.onToggle}
            variant={predict.on ? 'filled' : 'outlined'}
            role="switch"
            aria-checked={predict.on}
            sx={{
              'height': 24,
              'fontSize': 11,
              'bgcolor': ON_MEDIA_SCRIM,
              'color': predict.on ? 'var(--accent)' : ON_MEDIA,
              'opacity': predict.on ? 1 : 0.75,
              'borderColor': 'var(--hairline-strong)',
              '& .MuiChip-icon': { color: 'inherit' },
            }}
          />
        )}
      </Stack>
    </Box>
  );
}
