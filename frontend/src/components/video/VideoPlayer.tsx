/**
 * `video/VideoPlayer.tsx` — the frame-capture core.
 *
 * ★ A video is a FRAME SOURCE, not a timeline (design is final). The surveyor plays,
 *   pauses, scrubs, and at a chosen second CAPTURES that frame. The capture becomes a
 *   real `images` row in the project; the player STAYS PUT so the next frame can be
 *   captured without re-finding the timestamp.
 *
 * ★ TWO SCRUBBERS, ONE JOB. Native `<video>` (Range-served src) gives smooth playback
 *   and instant seeking for formats the browser can decode (MP4 previews best). For
 *   AVI/MKV/some MOV the browser fires `error`; we then hide the `<video>` and drive a
 *   SERVER-FRAME scrubber — an `<img>` whose src is `GET /videos/{id}/frame?t=`. Either
 *   way "pick a second and capture" works for every format.
 *
 * ★ `currentTime` is BROWSER-ONLY transient state — it lives here, never in a store or
 *   a query (L7). It is kept in sync with the element via `timeupdate`/`seeked`.
 */

import { useCallback, useEffect, useRef, useState, type FormEvent, type JSX } from 'react';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import CircularProgress from '@mui/material/CircularProgress';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import IconButton from '@mui/material/IconButton';
import LinearProgress from '@mui/material/LinearProgress';
import MenuItem from '@mui/material/MenuItem';
import Slider from '@mui/material/Slider';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import NavigateBeforeIcon from '@mui/icons-material/NavigateBefore';
import NavigateNextIcon from '@mui/icons-material/NavigateNext';
import FullscreenIcon from '@mui/icons-material/Fullscreen';
import FullscreenExitIcon from '@mui/icons-material/FullscreenExit';
import PauseIcon from '@mui/icons-material/Pause';
import PhotoCameraIcon from '@mui/icons-material/PhotoCamera';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';

import { videosApi } from '../../api/videos';
import { useCaptureFrame } from '../../api/hooks/useVideos';
import { useNotify } from '../common/Notifications';
import { ApiError } from '../../types/common';
import type { Video } from '../../types/video';
import { t } from '../../i18n';
import { useProjects } from '../../api/hooks/useProjects';
import { asUuid, type Uuid } from '../../types/common';
import FormControl from '@mui/material/FormControl';
import InputLabel from '@mui/material/InputLabel';
import Select from '@mui/material/Select';

export interface VideoPlayerProps {
  video: Video;
}

const DEFAULT_FPS = 30;
/** If the browser has not even fetched metadata after this long, treat as undecodable. */
const CANPLAY_TIMEOUT_MS = 12_000;

function clamp(value: number, min: number, max: number): number {
  if (Number.isNaN(value)) return min;
  return Math.min(Math.max(value, min), max);
}

/** `m:ss.s` — the precise readout. */
function formatPrecise(t: number): string {
  const safe = Number.isFinite(t) && t > 0 ? t : 0;
  const m = Math.floor(safe / 60);
  const s = safe - m * 60;
  return `${m}:${s.toFixed(1).padStart(4, '0')}`;
}

/** `m:ss` — chips and confirmations. */
function formatClock(t: number): string {
  const safe = Number.isFinite(t) && t > 0 ? t : 0;
  const m = Math.floor(safe / 60);
  const s = Math.floor(safe - m * 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

/** Accepts `12`, `12.5` (seconds) or `mm:ss` / `mm:ss.s`. Returns null on garbage. */
function parseTimeInput(raw: string): number | null {
  const text = raw.trim();
  if (text === '') return null;
  if (text.includes(':')) {
    const parts = text.split(':');
    if (parts.length !== 2) return null;
    const mm = Number(parts[0]);
    const ss = Number(parts[1]);
    if (!Number.isFinite(mm) || !Number.isFinite(ss) || ss < 0) return null;
    return mm * 60 + ss;
  }
  const n = Number(text);
  return Number.isFinite(n) ? n : null;
}

function captureErrorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.body.message;
  return 'Could not capture this frame. Try again in a moment.';
}

export function VideoPlayer({ video }: VideoPlayerProps): JSX.Element {
  const notify = useNotify();
  const captureFrame = useCaptureFrame();

  const videoRef = useRef<HTMLVideoElement>(null);
  const canPlaySeen = useRef(false);

  // ── which bytes can this browser actually play? ────────────────────────────
  // ★ HEVC (every recent drone default) is undecodable in browsers, so the server
  //   derives an H.264 preview (`app.tasks.transcoding`). Three states:
  //     · native codec        → play the ORIGINAL (`urls.file`)
  //     · HEVC, preview ready → play the PREVIEW; capture still reads the original
  //     · HEVC, no preview    → server-frame scrubber now, swap in the preview the
  //                             moment the poll (`useVideo`) reports it exists
  const isHevc = /hevc|h265|hvc1|hev1/i.test(video.codec ?? '');
  const playbackSrc = isHevc
    ? video.preview_available
      ? videosApi.previewUrl(video.id)
      : null
    : videosApi.fileUrl(video.id);

  // ★ Duration seeds from the server's `duration_s` and is upgraded to the element's
  //   own `duration` once metadata loads — the fallback path never gets that event, so
  //   the server value is what keeps its scrubber's range honest.
  // ★ "Did my step land yet?" A frame-step commands a seek and the element then
  //   fetches + decodes before the new frame paints — a beat of silence in which
  //   pressing again felt ignored. `seeking`/`seeked` (and `waiting`/`playing` for
  //   mid-play stalls) bracket exactly that window. The indicator waits 150 ms
  //   before showing so an instant local seek never flashes.
  const [seekPending, setSeekPending] = useState(false);
  const [showLoading, setShowLoading] = useState(false);
  useEffect(() => {
    if (!seekPending) {
      setShowLoading(false);
      return undefined;
    }
    const id = window.setTimeout(() => setShowLoading(true), 150);
    return () => window.clearTimeout(id);
  }, [seekPending]);

  const [duration, setDuration] = useState<number>(
    Number.isFinite(video.duration_s) && video.duration_s > 0 ? video.duration_s : 0,
  );
  const [currentTime, setCurrentTime] = useState(0);
  const [paused, setPaused] = useState(true);
  const [fallback, setFallback] = useState(false);
  const [frameError, setFrameError] = useState(false);
  const [seekField, setSeekField] = useState('');

  const fps = Number.isFinite(video.fps) && video.fps > 0 ? video.fps : DEFAULT_FPS;
  const frameStep = 1 / fps;

  // ★ How far one arrow press moves, in FRAMES. 1 is the precision default; the
  //   bigger strides are for walking a long clip without dragging the slider —
  //   drone footage barely changes frame-to-frame, so hunting a moment at 1-frame
  //   steps meant dozens of presses for one second of ground.
  const [stepFrames, setStepFrames] = useState(1);

  // ── seeking ──────────────────────────────────────────────────────────────────
  const seekTo = useCallback(
    (t: number) => {
      const target = clamp(t, 0, duration || t);
      setCurrentTime(target);
      // ★ A failed frame must not LATCH: the error branch unmounts the <img>, so the
      //   onLoad that would clear the flag can never fire again. One unreadable
      //   timestamp then kills every later preview. Each new seek is a new request and
      //   starts innocent.
      setFrameError(false);
      const el = videoRef.current;
      if (el && !fallback) {
        el.currentTime = target;
      }
    },
    [duration, fallback],
  );

  /**
   * ★ FRAME STEPS GO BY INDEX AND LAND ON THE FRAME'S CENTRE — `(idx ± 1 + 0.5) / fps`
   *   — never by `currentTime ± 1/fps`.
   *
   *   After a seek the element reports a time at or vanishingly near a frame BOUNDARY.
   *   Subtracting exactly one frame-duration from a boundary lands on the previous
   *   boundary — ambiguous territory where the decoder is free to display the SAME
   *   frame again, and with a metadata fps that differs a hair from the real one
   *   (29.97 vs 30) the error compounds each press. The visible symptom: forward
   *   stepping mostly works, BACKWARD stepping does nothing. Stepping the integer frame
   *   index and aiming at the centre of the target frame is unambiguous in both
   *   directions, on both the native and the server-frame path.
   */
  const stepFrame = useCallback(
    (direction: 1 | -1) => {
      const el = videoRef.current;
      if (el && !fallback && !el.paused) el.pause();
      const idx = Math.round(currentTime * fps - 0.5); // the frame currently displayed
      const target = (idx + direction * stepFrames + 0.5) / fps;
      seekTo(target);
    },
    [currentTime, fallback, fps, seekTo, stepFrames],
  );

  const onSeekSubmit = useCallback(
    (e: FormEvent) => {
      e.preventDefault();
      const parsed = parseTimeInput(seekField);
      if (parsed === null) {
        notify('Enter a time as seconds (12.5) or mm:ss (0:12).', { severity: 'warning' });
        return;
      }
      seekTo(parsed);
    },
    [seekField, seekTo, notify],
  );

  const togglePlay = useCallback(() => {
    const el = videoRef.current;
    if (!el) return;
    if (el.paused) {
      // ★ Only "cannot play this at all" earns the JPEG fallback. An AbortError (a
      //   quick pause, a src swap) or an autoplay refusal is not that — falling back
      //   on those replaced a playable video with the scrubber for the session.
      void el.play().catch((err: unknown) => {
        if ((err as { name?: string } | null)?.name === 'NotSupportedError') setFallback(true);
      });
    } else {
      el.pause();
    }
  }, []);

  // ── fullscreen ─────────────────────────────────────────────────────────────────
  // ★ The WRAPPER goes fullscreen, not the <video>: the scrubber, frame-steppers and
  //   the capture button must stay usable at full size — a bare fullscreen video with
  //   no way to capture would be a cinema, not a surveying tool.
  const rootRef = useRef<HTMLDivElement>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  useEffect(() => {
    const onChange = (): void => setIsFullscreen(document.fullscreenElement === rootRef.current);
    document.addEventListener('fullscreenchange', onChange);
    return () => document.removeEventListener('fullscreenchange', onChange);
  }, []);
  const toggleFullscreen = useCallback(() => {
    if (document.fullscreenElement === rootRef.current) {
      void document.exitFullscreen();
    } else {
      rootRef.current?.requestFullscreen().catch(() => {
        notify('Fullscreen is not available in this browser.', { severity: 'warning' });
      });
    }
  }, [notify]);

  // ── native <video> → state sync ────────────────────────────────────────────────
  const onLoadedMetadata = useCallback(() => {
    const el = videoRef.current;
    if (el && Number.isFinite(el.duration) && el.duration > 0) setDuration(el.duration);
  }, []);
  const onTimeUpdate = useCallback(() => {
    const el = videoRef.current;
    if (el) setCurrentTime(el.currentTime);
  }, []);
  const onSeeking = useCallback(() => setSeekPending(true), []);
  const onSeeked = useCallback(() => {
    setSeekPending(false);
    onTimeUpdate();
  }, [onTimeUpdate]);
  const onCanPlay = useCallback(() => {
    canPlaySeen.current = true;
  }, []);
  const onError = useCallback(() => setFallback(true), []);

  // ★ `canplay` never firing is the OTHER undecodable signal. If after the timeout the
  //   element is still at readyState 0 (nothing loaded) and has not errored, fall back.
  useEffect(() => {
    if (fallback) return undefined;
    const id = window.setTimeout(() => {
      const el = videoRef.current;
      if (!canPlaySeen.current && el && el.readyState === 0) setFallback(true);
    }, CANPLAY_TIMEOUT_MS);
    return () => window.clearTimeout(id);
  }, [fallback]);

  // Reset transient state if the component is reused for another video id.
  useEffect(() => {
    setFrameError(false);
    setCurrentTime(0);
    setPaused(true);
  }, [video.id]);

  // ★ Src decides the mode DIRECTLY: with nothing playable there is no reason to
  //   mount a <video> and wait 12 s for a timeout — and when the poll flips
  //   `preview_available`, this same effect swaps the scrubber for real playback.
  useEffect(() => {
    canPlaySeen.current = false;
    setFallback(playbackSrc === null);
    setFrameError(false);
    setSeekPending(false);
  }, [playbackSrc]);

  // ── capture ────────────────────────────────────────────────────────────────────
  // ★ CAPTURE ASKS FOR A NAME FIRST. The dialog freezes the timestamp when it opens
  //   (`nameTime`), so the photo is the frame the surveyor was LOOKING at even if the
  //   video plays on underneath. After capture we land on the PROJECT page — the photo
  //   sits there like any other, and its setup is one click away on its card's gear.
  const [naming, setNaming] = useState(false);
  const [nameTime, setNameTime] = useState(0);
  const [captureName, setCaptureName] = useState('');
  // ★ A library-only clip (no project) asks which project the photograph goes to.
  const needsProject = video.project_id === null;
  const [captureProject, setCaptureProject] = useState<string>('');
  const projectsQuery = useProjects({ limit: 100, sort: 'name' });
  const targetProject: Uuid | null =
    video.project_id ?? (captureProject === '' ? null : asUuid(captureProject));

  const openNaming = useCallback(() => {
    const t = Math.round(currentTime * 10) / 10;
    const stem = video.filename.replace(/\.[^.]+$/, '') || 'frame';
    setNameTime(t);
    setCaptureName(`${stem}_t${t}`);
    setNaming(true);
  }, [currentTime, video.filename]);

  const confirmCapture = useCallback(() => {
    const trimmed = captureName.trim();
    if (targetProject === null) return;
    captureFrame.mutate(
      {
        videoId: video.id,
        projectId: targetProject,
        // ★ Blank name → omit it; the server then uses its own default rather than
        //   storing an empty string it would have to invent an answer for.
        body: {
          t_seconds: nameTime,
          filename: trimmed === '' ? null : trimmed,
          // The clip's own project is the server's default; only a library-only clip
          // needs to say where the photograph goes.
          project_id: needsProject ? targetProject : undefined,
        },
      },
      {
        // ★ STAY HERE. Capturing used to jump to the project page, but a session is
        //   rarely one frame — the surveyor is walking the clip collecting several,
        //   and being ejected after each one meant re-navigating and re-finding the
        //   timestamp every time. The toast confirms the photo landed in the
        //   project; the player stays exactly where it was, ready for the next one.
        onSuccess: (image) => {
          setNaming(false);
          notify(
            `Captured “${image.filename}” — in the project, and saved to your ` +
              'Pictures/LandExplorer folder for reuse in other projects.',
            { severity: 'success' },
          );
        },
        onError: (error) => notify(captureErrorMessage(error), { severity: 'error' }),
      },
    );
  }, [captureFrame, captureName, nameTime, video.id, targetProject, needsProject, notify]);

  // Round the fallback frame request to 0.1s: fewer distinct URLs, cacheable, still smooth.
  // ★ And DEBOUNCED: a slider drag sweeps dozens of 0.1s buckets, and each distinct img
  //   src is a full open+seek+decode of the source video on the server. Rendering only
  //   where the scrubber RESTS turns a drag from a queue of expensive requests into one.
  //   The previous frame stays visible (dimmed) while the next loads, so scrubbing reads
  //   as "seeking" rather than flashing white.
  const [settledTime, setSettledTime] = useState(0);
  const [frameLoading, setFrameLoading] = useState(false);
  useEffect(() => {
    if (!fallback) return undefined;
    const id = window.setTimeout(() => {
      setSettledTime(Math.round(currentTime * 10) / 10);
      setFrameLoading(true);
    }, 200);
    return () => window.clearTimeout(id);
  }, [fallback, currentTime]);
  const frameSrc = videosApi.frameUrl(video.id, settledTime);
  const sliderMax = duration > 0 ? duration : Math.max(currentTime, 1);

  return (
    <Stack
      ref={rootRef}
      spacing={2}
      // ★ In fullscreen the browser pins this element to the viewport; the surface
      //   grows to fill what the scrubber and controls leave, letterboxing the frame.
      sx={isFullscreen ? { bgcolor: 'background.default', p: 2, overflow: 'auto' } : undefined}
    >
      {/* ── the frame surface ─────────────────────────────────────────────────── */}
      <Box
        sx={{
          position: 'relative',
          bgcolor: 'common.black',
          borderRadius: 1,
          overflow: 'hidden',
          ...(isFullscreen
            ? { flexGrow: 1, minHeight: 0 }
            : {
                aspectRatio:
                  video.width > 0 && video.height > 0
                    ? `${video.width} / ${video.height}`
                    : '16 / 9',
              }),
          display: 'grid',
          placeItems: 'center',
        }}
      >
        {!fallback ? (
          // Field video has no captions track (jsx-a11y plugin not installed; no disable needed).
          <video
            ref={videoRef}
            src={playbackSrc ?? undefined}
            preload="metadata"
            playsInline
            // ★ Kills the floating badge CHROME injects mid-frame on every playing
            //   video (its picture-in-picture affordance) — it hovered over the
            //   imagery being inspected and reads as part of our UI. PiP makes no
            //   sense for a frame-capture tool anyway: the work happens HERE.
            disablePictureInPicture
            onClick={togglePlay}
            onLoadedMetadata={onLoadedMetadata}
            onTimeUpdate={onTimeUpdate}
            onSeeking={onSeeking}
            onSeeked={onSeeked}
            onWaiting={onSeeking}
            onPlaying={onSeeked}
            onCanPlay={onCanPlay}
            onPlay={() => setPaused(false)}
            onPause={() => setPaused(true)}
            onError={onError}
            style={{
              width: '100%',
              height: '100%',
              objectFit: 'contain',
              display: 'block',
              cursor: 'pointer',
            }}
          />
        ) : frameError ? (
          <Stack spacing={1} alignItems="center" sx={{ color: 'grey.500', p: 4 }}>
            <Typography variant="body2">{t('No preview available at this second.')}</Typography>
            <Typography variant="caption">
              {t('You can still capture the frame — the server renders it on capture.')}
            </Typography>
          </Stack>
        ) : (
          <Box
            component="img"
            src={frameSrc}
            alt={`Frame at ${formatPrecise(currentTime)}`}
            onError={() => {
              setFrameError(true);
              setFrameLoading(false);
            }}
            onLoad={() => {
              setFrameError(false);
              setFrameLoading(false);
            }}
            sx={{
              width: '100%',
              height: '100%',
              objectFit: 'contain',
              display: 'block',
              opacity: frameLoading ? 0.5 : 1,
              transition: 'opacity 120ms',
            }}
          />
        )}
        {/* ★ The seek-loading highlight: a progress strip along the top plus a gentle
            dim. NOT centred — the paused play badge owns the centre — and pointer-
            transparent so it never eats the click. The fallback scrubber reuses it
            (`frameLoading`), so both paths speak one loading language. */}
        {((!fallback && showLoading) || (fallback && frameLoading)) && (
          <>
            <Box
              sx={{
                position: 'absolute',
                inset: 0,
                bgcolor: 'rgba(0,0,0,0.25)',
                pointerEvents: 'none',
              }}
            />
            <LinearProgress
              sx={{ position: 'absolute', top: 0, left: 0, right: 0, pointerEvents: 'none' }}
              aria-label={t('Loading the frame at the new position')}
            />
          </>
        )}

        {/* ★ Click-to-play affordance: a video that is sitting paused SAYS so. The
            badge ignores the pointer — the click lands on the video underneath. */}
        {!fallback && paused && (
          <Box
            sx={{
              position: 'absolute',
              inset: 0,
              display: 'grid',
              placeItems: 'center',
              pointerEvents: 'none',
            }}
          >
            <Box
              sx={{
                width: 72,
                height: 72,
                borderRadius: '50%',
                bgcolor: 'rgba(0,0,0,0.55)',
                display: 'grid',
                placeItems: 'center',
                color: 'common.white',
              }}
            >
              <PlayArrowIcon sx={{ fontSize: 44 }} />
            </Box>
          </Box>
        )}

        <Tooltip title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}>
          <IconButton
            onClick={toggleFullscreen}
            aria-label={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
            // ★ Bottom-right, the corner every video player keeps this in — it was
            //   floating at the frame's edge, over the imagery being inspected.
            sx={{
              'position': 'absolute',
              'bottom': 8,
              'right': 8,
              'color': 'common.white',
              'bgcolor': 'rgba(0,0,0,0.45)',
              '&:hover': { bgcolor: 'rgba(0,0,0,0.7)' },
            }}
          >
            {isFullscreen ? <FullscreenExitIcon /> : <FullscreenIcon />}
          </IconButton>
        </Tooltip>
      </Box>

      {fallback && isHevc && (
        <Alert severity="info" variant="outlined">
          {/* ★ ".mp4" is only the CONTAINER — the codec inside this one is HEVC
              (H.265), which browsers cannot decode. Say so, and say what is being
              done about it, or "play does nothing" reads as a bug. */}
          Preparing this video for playback… Its .mp4 container holds HEVC (H.265), which browsers
          can’t decode, so a playable copy is being prepared on the server — playback switches on
          here automatically when it’s ready (a few minutes for a 4K clip). Seeking and capturing
          already work, and captures always use the original at full quality.
        </Alert>
      )}
      {fallback && !isHevc && (
        <Alert severity="info" variant="outlined">
          {t(
            'This format can’t play in the browser. Seeking and capturing still work: frames are rendered on the server.',
          )}
        </Alert>
      )}
      {!fallback && isHevc && (
        <Typography variant="caption" color="text.secondary">
          Playing the 1080p preview — captured frames always come from the{' '}
          {video.height >= 2160 ? '4K ' : ''}original at full quality.
        </Typography>
      )}

      {/* ── scrubber + readout ────────────────────────────────────────────────── */}
      <Box>
        <Slider
          value={clamp(currentTime, 0, sliderMax)}
          min={0}
          max={sliderMax}
          step={frameStep}
          onChange={(_e, value) => seekTo(Array.isArray(value) ? value[0] : value)}
          aria-label={t('Seek video position')}
          getAriaValueText={(v) => formatPrecise(v)}
          valueLabelDisplay="auto"
          valueLabelFormat={(v) => formatPrecise(v)}
        />
        <Stack direction="row" justifyContent="space-between">
          <Typography variant="mono" color="text.secondary">
            {formatPrecise(currentTime)}
          </Typography>
          <Typography variant="mono" color="text.secondary">
            {formatPrecise(duration)}
          </Typography>
        </Stack>
      </Box>

      {/* ── transport controls ────────────────────────────────────────────────── */}
      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        spacing={2}
        alignItems={{ xs: 'stretch', sm: 'center' }}
      >
        <Stack direction="row" spacing={1} alignItems="center">
          {!fallback && (
            <Tooltip title={paused ? 'Play' : 'Pause'}>
              <IconButton
                onClick={togglePlay}
                aria-label={paused ? 'Play video' : 'Pause video'}
                color="primary"
              >
                {paused ? <PlayArrowIcon /> : <PauseIcon />}
              </IconButton>
            </Tooltip>
          )}
          <Tooltip title={stepFrames === 1 ? 'Back one frame' : `Back ${stepFrames} frames`}>
            <span>
              <IconButton
                onClick={() => stepFrame(-1)}
                aria-label={`Step back ${stepFrames} frame${stepFrames === 1 ? '' : 's'}`}
                disabled={currentTime <= 0}
              >
                <NavigateBeforeIcon />
              </IconButton>
            </span>
          </Tooltip>
          {/* ★ The stride lives BETWEEN the arrows it governs — one glance says
              "these buttons move by this much". */}
          <TextField
            select
            size="small"
            value={stepFrames}
            onChange={(e) => setStepFrames(Number(e.target.value))}
            aria-label={t('Frames per step')}
            sx={{ width: 104 }}
          >
            {[1, 5, 10, 30, 60].map((n) => (
              <MenuItem key={n} value={n}>
                {n === 1 ? '1 frame' : `${n} frames`}
              </MenuItem>
            ))}
          </TextField>
          <Tooltip title={stepFrames === 1 ? 'Forward one frame' : `Forward ${stepFrames} frames`}>
            <span>
              <IconButton
                onClick={() => stepFrame(1)}
                aria-label={`Step forward ${stepFrames} frame${stepFrames === 1 ? '' : 's'}`}
                disabled={duration > 0 && currentTime >= duration}
              >
                <NavigateNextIcon />
              </IconButton>
            </span>
          </Tooltip>
        </Stack>

        {/* ★ The explicitly-requested "go to second" control. */}
        <Stack
          component="form"
          onSubmit={onSeekSubmit}
          direction="row"
          spacing={1}
          alignItems="center"
        >
          <TextField
            size="small"
            label={t('Go to second')}
            placeholder={t('e.g. 12.5 or 0:12')}
            value={seekField}
            onChange={(e) => setSeekField(e.target.value)}
            inputProps={{
              'aria-label': 'Go to a time in seconds or mm:ss',
              'inputMode': 'decimal',
            }}
            sx={{ width: 160 }}
          />
          <Button type="submit" variant="outlined">
            Go
          </Button>
        </Stack>

        <Box sx={{ flex: 1 }} />

        <Button
          variant="contained"
          startIcon={
            captureFrame.isPending ? (
              <CircularProgress size={16} color="inherit" />
            ) : (
              <PhotoCameraIcon />
            )
          }
          onClick={openNaming}
          disabled={captureFrame.isPending}
          aria-label={`Capture the frame at ${formatClock(currentTime)}`}
        >
          {captureFrame.isPending
            ? 'Capturing…'
            : `Capture this frame (${formatClock(currentTime)})`}
        </Button>
      </Stack>

      {/* ── name the photo, then capture ──────────────────────────────────── */}
      <Dialog
        open={naming}
        onClose={captureFrame.isPending ? undefined : () => setNaming(false)}
        maxWidth="xs"
        fullWidth
        // ★ Portals mount on <body>, and everything outside a fullscreened element is
        //   NOT RENDERED while fullscreen is active — the dialog must live inside it.
        container={() => rootRef.current}
      >
        <DialogTitle>{t('Name this photo')}</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            {t('The frame at')} <strong>{formatClock(nameTime)}</strong>{' '}
            {t(
              'becomes a photograph in the project. Leave the extension off — “.jpg” is added for you.',
            )}
          </Typography>
          {needsProject && (
            <FormControl size="small" fullWidth sx={{ mb: 2 }}>
              <InputLabel id="capture-project">{t('Project for this photograph')}</InputLabel>
              <Select
                labelId="capture-project"
                label={t('Project for this photograph')}
                value={captureProject}
                onChange={(e) => setCaptureProject(String(e.target.value))}
                disabled={captureFrame.isPending}
              >
                {(projectsQuery.data?.items ?? []).map((p) => (
                  <MenuItem key={p.id} value={p.id}>
                    {p.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          )}
          <TextField
            autoFocus
            fullWidth
            label={t('Photo name')}
            value={captureName}
            onChange={(e) => setCaptureName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !captureFrame.isPending) confirmCapture();
            }}
            disabled={captureFrame.isPending}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setNaming(false)} disabled={captureFrame.isPending}>
            {t('Cancel')}
          </Button>
          <Button
            variant="contained"
            onClick={confirmCapture}
            disabled={captureFrame.isPending || targetProject === null}
            startIcon={
              captureFrame.isPending ? (
                <CircularProgress size={16} color="inherit" />
              ) : (
                <PhotoCameraIcon />
              )
            }
          >
            {captureFrame.isPending ? 'Capturing…' : 'Capture'}
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}

export default VideoPlayer;
