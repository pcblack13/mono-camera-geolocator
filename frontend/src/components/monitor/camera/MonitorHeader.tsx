/**
 * `monitor/camera/MonitorHeader.tsx` — the sticky header: name, place, status, and
 * the two actions that matter.
 *
 * ★ THE HEADER SAYS WHAT STATE THE PAGE IS IN. Draft changes tint it VIOLET and the
 *   button reads "Apply changes"; a run tints it CYAN with an elapsed counter; a
 *   refused start is a BANNER under it with the server's verbatim words and a copy
 *   button — never a toast that disappears.
 */

import { useEffect, useState, type JSX } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import IconButton from '@mui/material/IconButton';
import Stack from '@mui/material/Stack';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import CameraAltOutlinedIcon from '@mui/icons-material/CameraAltOutlined';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import PlayArrowRoundedIcon from '@mui/icons-material/PlayArrowRounded';
import FiberManualRecordIcon from '@mui/icons-material/FiberManualRecord';
import GpsFixedIcon from '@mui/icons-material/GpsFixed';
import StopCircleOutlinedIcon from '@mui/icons-material/StopCircleOutlined';
import VideoLibraryOutlinedIcon from '@mui/icons-material/VideoLibraryOutlined';
import StopRoundedIcon from '@mui/icons-material/StopRounded';
import TuneOutlinedIcon from '@mui/icons-material/TuneOutlined';

import type { FeedStatus } from '../../../hooks/useLiveFeed';
import type { RegisteredCamera } from '../../../store/cameraRegistryStore';
import { t } from '../../../i18n';

export interface MonitorHeaderProps {
  camera: RegisteredCamera;
  /** ★ A data-only integration (serial/UART, a Pi's feed): there is no video to
   *  capture, no detector to start, no drift reference to freeze — those buttons
   *  leave; the feed panel reports the feed's own state (2026-09-02). */
  dataOnly?: boolean;
  status: FeedStatus;
  dirty: boolean;
  detecting: boolean;
  /** ★ The run is tracking-only (no detector): the chip says so, not "detecting". */
  trackingOnly?: boolean;
  starting: boolean;
  /** Epoch ms the run started, for the elapsed counter. */
  runStartedAt: number | null;
  startBlocker: string | null;
  startError: string | null;
  onDismissError: () => void;
  onApply: () => void;
  onStart: () => void;
  onStop: () => void;
  /** ★ Manual tracking, ARMED WITH THE RUN (2026-09-08): no button arms it any
   *  more — the operator clicks detected objects. This only tells how many are
   *  followed right now, so the header can say so beside Stop. */
  trackedCount: number;
  onCapture: () => void;
  captureBusy: boolean;
  /** ★ RECORD (2026-09-02): saves the stream as watched + the run's attribute
   *  table into one library folder. Null = not recording; a number = epoch ms
   *  the recording started (drives the elapsed counter). */
  recordingStartedAt: number | null;
  /** True while a stop is finalizing (video + CSV being written). */
  recordBusy: boolean;
  onToggleRecord: () => void;
  /** Opens the recordings library dialog. */
  onOpenLibrary: () => void;
  /**
   * Opens the settings editor (the wide panel, or the sheet below 1280 px).
   * Absent while the wide panel is already open — a door beside an open door.
   */
  onEditSettings?: () => void;
}

function Elapsed({ since }: { since: number }): JSX.Element {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);
  const s = Math.max(0, Math.floor((now - since) / 1000));
  const mm = String(Math.floor(s / 60)).padStart(2, '0');
  const ss = String(s % 60).padStart(2, '0');
  return (
    <Typography variant="mono" component="span" sx={{ fontSize: 12, direction: 'ltr' }}>
      {mm}:{ss}
    </Typography>
  );
}

export function MonitorHeader(p: MonitorHeaderProps): JSX.Element {
  const tint = p.detecting ? 'var(--status-busy)' : p.dirty ? 'var(--status-draft)' : null;
  const live = p.status === 'live';
  const copy = (): void => {
    if (p.startError) void navigator.clipboard?.writeText(p.startError);
  };
  return (
    <Box
      component="header"
      sx={{
        position: 'sticky',
        top: 0,
        zIndex: 3,
        bgcolor: 'var(--bg-elevated)',
        borderBottom: '1px solid var(--hairline)',
        boxShadow: tint ? `inset 0 -2px 0 0 ${tint}` : 'none',
      }}
    >
      <Stack direction="row" alignItems="center" spacing={1.5} sx={{ px: 1.5, height: 48 }}>
        <Tooltip title={t('Back to the globe')}>
          <IconButton
            component={RouterLink}
            to="/monitor"
            size="small"
            aria-label={t('Back to the globe')}
          >
            <ArrowBackIcon fontSize="small" />
          </IconButton>
        </Tooltip>
        <Typography variant="subtitle1" sx={{ fontWeight: 600 }} noWrap>
          {p.camera.name}
        </Typography>
        <Typography
          variant="mono"
          sx={{ fontSize: 12, color: 'var(--text-secondary)', direction: 'ltr' }}
        >
          {p.camera.lat.toFixed(5)}, {p.camera.lon.toFixed(5)}
        </Typography>
        {/* ★ NO STATUS PILL HERE (owner ask 2026-09-10). The picture already
            carries LIVE / LOST · Ns / REFUSED in its own corner, and a data-only
            camera carries the same word in its feed panel — the header said it a
            second time, beside the name, where it read as chrome. */}
        {p.detecting && p.runStartedAt !== null && (
          <Stack
            direction="row"
            spacing={0.75}
            alignItems="center"
            sx={{ color: 'var(--status-busy)' }}
          >
            <Typography variant="caption">{t(p.trackingOnly ? 'tracking' : 'detecting')}</Typography>
            <Elapsed since={p.runStartedAt} />
          </Stack>
        )}
        {p.dirty && !p.detecting && (
          <Typography variant="caption" sx={{ color: 'var(--status-draft)' }}>
            {t('unsaved changes')}
          </Typography>
        )}
        {/* ★ "setup saved" is gone too (owner ask 2026-09-10): a camera that is
            set up is the ordinary case, and a badge for the ordinary case is
            noise. "unsaved changes" above still speaks, because that one is not
            ordinary and the operator must act on it. */}
        <Box sx={{ flex: 1 }} />
        {p.onEditSettings && (
          <Button
            size="small"
            variant="outlined"
            startIcon={<TuneOutlinedIcon />}
            onClick={p.onEditSettings}
            sx={{ whiteSpace: 'nowrap' }}
          >
            {t('Edit settings')}
          </Button>
        )}
        {/* ★ Capture stays live THROUGH a detection run (owner decision
            2026-09-01): the server taps the running session's own raw frames
            rather than opening the device twice. It only waits for the stream.
            The drift watch has no button here any more (2026-09-08): it is the
            camera's own, frozen on its frame in the settings, and this page
            only reads its verdict. */}
        {p.dataOnly && (
          <Typography variant="caption" sx={{ color: 'var(--text-secondary)' }}>
            {t('data feed — points land on the map as they arrive')}
          </Typography>
        )}
        {!p.dataOnly && (
          <>
            <Tooltip
              title={
                p.recordingStartedAt !== null
                  ? t('Stop recording — the folder gets the video and the CSV')
                  : live
                    ? t('Record the stream and the detections into the library')
                    : t('Needs the stream live')
              }
            >
              <span>
                <Button
                  size="small"
                  variant={p.recordingStartedAt !== null ? 'contained' : 'outlined'}
                  color={p.recordingStartedAt !== null ? 'error' : 'primary'}
                  startIcon={
                    p.recordingStartedAt !== null ? (
                      <StopCircleOutlinedIcon />
                    ) : (
                      <FiberManualRecordIcon sx={{ color: 'var(--status-error)' }} />
                    )
                  }
                  onClick={p.onToggleRecord}
                  disabled={(!live && p.recordingStartedAt === null) || p.recordBusy}
                  sx={{ whiteSpace: 'nowrap' }}
                >
                  {p.recordBusy ? (
                    t('Saving…')
                  ) : p.recordingStartedAt !== null ? (
                    <>
                      {t('REC')}&nbsp;
                      <Elapsed since={p.recordingStartedAt} />
                    </>
                  ) : (
                    t('Record')
                  )}
                </Button>
              </span>
            </Tooltip>
            <Tooltip title={t('Recorded videos')}>
              <IconButton size="small" onClick={p.onOpenLibrary} aria-label={t('Recorded videos')}>
                <VideoLibraryOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
            <Tooltip title={live ? '' : t('Capture needs the stream live')}>
              <span>
                <Button
                  size="small"
                  variant="outlined"
                  startIcon={<CameraAltOutlinedIcon />}
                  onClick={p.onCapture}
                  disabled={!live || p.captureBusy}
                  sx={{ whiteSpace: 'nowrap' }}
                >
                  {p.captureBusy ? t('Capturing…') : t('Capture')}
                </Button>
              </span>
            </Tooltip>
            {/* ★ Tracking is armed with the run (2026-09-08, owner decision): no
            button starts it — the operator clicks detected objects in the video.
            While objects are followed, the header says how many. */}
            {p.detecting && p.trackedCount > 0 && (
              <Tooltip title={t('Objects being followed — click one in the video to release it')}>
                <Stack
                  direction="row"
                  spacing={0.5}
                  alignItems="center"
                  data-testid="tracking-count"
                  sx={{
                    px: 1,
                    height: 30,
                    borderRadius: 'var(--radius-md)',
                    border: '1px solid var(--hairline)',
                    color: 'var(--text-secondary)',
                    whiteSpace: 'nowrap',
                  }}
                >
                  <GpsFixedIcon sx={{ fontSize: 16 }} />
                  <Typography variant="caption">
                    {t('Tracking')} · {p.trackedCount}
                  </Typography>
                </Stack>
              </Tooltip>
            )}
            {p.detecting ? (
              <Button
                size="small"
                variant="contained"
                color="warning"
                startIcon={<StopRoundedIcon />}
                onClick={p.onStop}
                sx={{ whiteSpace: 'nowrap' }}
              >
                {t('Stop')}
              </Button>
            ) : p.dirty ? (
              <Button
                size="small"
                variant="contained"
                startIcon={<TuneOutlinedIcon />}
                onClick={p.onApply}
                sx={{
                  bgcolor: 'var(--status-draft)',
                  color: 'var(--text-inverse)',
                  whiteSpace: 'nowrap',
                }}
              >
                {t('Apply changes')}
              </Button>
            ) : (
              <Tooltip title={p.startBlocker ?? ''}>
                <span>
                  <Button
                    size="small"
                    variant="contained"
                    startIcon={<PlayArrowRoundedIcon />}
                    onClick={p.onStart}
                    disabled={p.startBlocker !== null || p.starting}
                    sx={{ whiteSpace: 'nowrap' }}
                  >
                    {p.starting ? t('Starting…') : t('Start detection')}
                  </Button>
                </span>
              </Tooltip>
            )}
          </>
        )}
      </Stack>
      {p.startError !== null && (
        <Alert
          severity="error"
          onClose={p.onDismissError}
          sx={{ borderRadius: 0, borderTop: '1px solid var(--hairline)' }}
          action={
            <Stack direction="row" spacing={0.5}>
              <Tooltip title={t('Copy')}>
                <IconButton
                  size="small"
                  color="inherit"
                  onClick={copy}
                  aria-label={t('Copy the error')}
                >
                  <ContentCopyIcon fontSize="small" />
                </IconButton>
              </Tooltip>
              <Button color="inherit" size="small" onClick={p.onDismissError}>
                {t('Dismiss')}
              </Button>
            </Stack>
          }
        >
          <b>{t('The server refused to start detection:')}</b> {p.startError}
        </Alert>
      )}
    </Box>
  );
}
