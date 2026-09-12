/**
 * `cameras/CaptureFrameDialog.tsx` — choose the frame from INSIDE the live camera.
 *
 * ★ OWNER ASK (2026-09-09). "Capture from the camera now" used to grab a frame
 *   blind — whatever the camera showed at the instant the button was pressed. The
 *   surveyor wants to LOOK first: this opens the live picture, they press
 *   "Capture this frame" at the moment they want, see the frozen result, and only
 *   then decide — use it, or try again. Nothing is adopted until they say so.
 *
 * ★ THE CAPTURE IS THE SERVER'S, on purpose. The frame must land in the capture
 *   library as a file the project can import, and a device camera admits one
 *   opener — the server grabs from the same feed the preview shows (the handover
 *   the monitor page's Capture already relies on), so what the surveyor sees is
 *   what is captured, within a frame or two.
 *
 * ★ The live `<img>` releases its stream on unmount (`StreamImage`), and the
 *   dialog unmounts its content when closed — no zombie connection holds the
 *   camera after the surveyor leaves.
 */

import { useEffect, useState, type JSX } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import CircularProgress from '@mui/material/CircularProgress';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import PhotoCameraOutlinedIcon from '@mui/icons-material/PhotoCameraOutlined';
import ReplayOutlinedIcon from '@mui/icons-material/ReplayOutlined';
import CheckOutlinedIcon from '@mui/icons-material/CheckOutlined';

import { captureLibraryApi } from '../../api/captureLibrary';
import { liveApi, type LiveFrameCaptured } from '../../api/live';
import { previewSrcForSource } from '../../hooks/useLiveFeed';
import { t } from '../../i18n';
import { LtrIsland } from '../common/LtrIsland';
import { StreamImage } from '../live/StreamImage';

export interface CaptureFrameDialogProps {
  open: boolean;
  /** The camera's video source — a URL or a local device. */
  source: string;
  /** A local device (HDMI / USB) rather than a network stream. */
  device: boolean;
  /** The capture's name in the library — the camera's name. */
  name: string;
  onClose: () => void;
  /** The surveyor chose this frame: import it and make it the camera's. */
  onUse: (shot: LiveFrameCaptured) => Promise<void>;
}

type Phase = 'live' | 'capturing' | 'frozen' | 'adopting';

export function CaptureFrameDialog({
  open,
  source,
  device,
  name,
  onClose,
  onUse,
}: CaptureFrameDialogProps): JSX.Element {
  const [phase, setPhase] = useState<Phase>('live');
  const [shot, setShot] = useState<LiveFrameCaptured | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [streamLost, setStreamLost] = useState(false);
  // Bumped to re-open the stream after a failure — a fresh <img>, a fresh connection.
  const [attempt, setAttempt] = useState(0);

  // A fresh dialog every time it opens: no stale frozen frame from last time.
  useEffect(() => {
    if (!open) return;
    setPhase('live');
    setShot(null);
    setError(null);
    setStreamLost(false);
  }, [open]);

  const busy = phase === 'capturing' || phase === 'adopting';

  const capture = async (): Promise<void> => {
    setPhase('capturing');
    setError(null);
    try {
      const captured = device
        ? await liveApi.captureDeviceFrame(source, { name })
        : await liveApi.captureFrame(source, { name });
      setShot(captured);
      setPhase('frozen');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setPhase('live');
    }
  };

  const use = async (): Promise<void> => {
    if (shot === null) return;
    setPhase('adopting');
    setError(null);
    try {
      await onUse(shot);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setPhase('frozen');
    }
  };

  const frozen = phase === 'frozen' || phase === 'adopting';

  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="md" fullWidth>
      <DialogTitle>
        {frozen ? t('The captured frame') : t('Capture a frame from the camera')}
      </DialogTitle>
      <DialogContent>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
          {frozen
            ? t('This is the frame that was captured. Use it as the camera’s frame, or go back to the live picture and try again.')
            : t('The live picture. Press “Capture this frame” at the moment you want.')}
        </Typography>
        {/* ★ A picture is geometry: it stays LTR under Arabic (the app mirrors). */}
        <LtrIsland>
          <Box
            data-testid="capture-frame-picture"
            data-phase={phase}
            sx={{
              position: 'relative',
              width: '100%',
              aspectRatio: '16 / 9',
              bgcolor: 'var(--bg-inset)',
              borderRadius: 'var(--radius-md)',
              border: '1px solid var(--hairline)',
              overflow: 'hidden',
              display: 'grid',
              placeItems: 'center',
            }}
          >
            {frozen && shot !== null ? (
              <img
                // ★ The library's own URL builder: the API's `file_url` already carries
                //   the `/api/v1` prefix, so prefixing it again broke the picture (seen
                //   2026-09-09 on the first real capture).
                src={captureLibraryApi.fileUrl(shot.filename)}
                alt={t('The captured frame')}
                style={{ width: '100%', height: '100%', objectFit: 'contain' }}
              />
            ) : streamLost ? (
              <Stack spacing={1} alignItems="center">
                <Typography variant="body2" color="text.secondary">
                  {t('The stream could not be opened.')}
                </Typography>
                <Button
                  size="small"
                  variant="outlined"
                  onClick={() => {
                    setStreamLost(false);
                    setAttempt((n) => n + 1);
                  }}
                >
                  {t('Retry')}
                </Button>
              </Stack>
            ) : (
              <StreamImage
                key={attempt}
                src={previewSrcForSource(source)}
                alt={t('Live picture')}
                style={{ width: '100%', height: '100%', objectFit: 'contain' }}
                onError={() => setStreamLost(true)}
              />
            )}
            {!frozen && !streamLost && (
              <Box
                sx={{
                  position: 'absolute',
                  top: 8,
                  left: 8,
                  px: 0.75,
                  py: 0.25,
                  borderRadius: 'var(--radius-sm)',
                  bgcolor: 'var(--status-ok)',
                  color: 'var(--on-status)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: 11,
                  letterSpacing: '0.06em',
                }}
              >
                {t('LIVE')}
              </Box>
            )}
          </Box>
        </LtrIsland>
        {shot !== null && frozen && (
          <Typography variant="caption" color="text.secondary" className="le-mono" sx={{ mt: 1, display: 'block' }}>
            {shot.filename} · {shot.width} × {shot.height}
          </Typography>
        )}
        {error !== null && (
          <Typography variant="caption" sx={{ color: 'var(--status-error)', display: 'block', mt: 1 }}>
            {error}
          </Typography>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>
          {t('Cancel')}
        </Button>
        {frozen ? (
          <>
            <Button
              startIcon={<ReplayOutlinedIcon />}
              disabled={busy}
              onClick={() => {
                setShot(null);
                setPhase('live');
              }}
            >
              {t('Try again')}
            </Button>
            <Button
              variant="contained"
              startIcon={
                phase === 'adopting' ? (
                  <CircularProgress size={14} color="inherit" />
                ) : (
                  <CheckOutlinedIcon />
                )
              }
              disabled={busy}
              onClick={() => void use()}
            >
              {phase === 'adopting' ? t('Saving…') : t('Use this frame')}
            </Button>
          </>
        ) : (
          <Button
            variant="contained"
            startIcon={
              phase === 'capturing' ? (
                <CircularProgress size={14} color="inherit" />
              ) : (
                <PhotoCameraOutlinedIcon />
              )
            }
            disabled={busy || streamLost}
            onClick={() => void capture()}
          >
            {phase === 'capturing' ? t('Capturing…') : t('Capture this frame')}
          </Button>
        )}
      </DialogActions>
    </Dialog>
  );
}
