/**
 * `video/VideoUploadDialog.tsx` — a single-file video upload with a progress bar.
 *
 * ★ A video goes to `POST /videos`, not `POST /images` — it is a frame source, and the
 *   server transcodes/indexes it differently. The image path (`BatchUploadDialog` +
 *   `uploadStore`) is untouched; this is the parallel, clearly-labelled video path.
 *
 * ★ ONE FILE AT A TIME. A field video is large; queueing several would saturate a
 *   tablet's uplink. The progress bar is honest (the `upload` XHR reports real bytes).
 */

import { useCallback, useState, type JSX } from 'react';
import Button from '@mui/material/Button';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import LinearProgress from '@mui/material/LinearProgress';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

import { useUploadVideo } from '../../api/hooks/useVideos';
import { UploadDropzone } from '../upload/UploadDropzone';
import { useNotify } from '../common/Notifications';
import { ApiError } from '../../types/common';
import type { Uuid } from '../../types/common';
import { t } from '../../i18n';

export interface VideoUploadDialogProps {
  open: boolean;
  /** `null` → the clip is kept in the library only, attached to no project. */
  projectId: Uuid | null;
  onClose: () => void;
  onUploaded: (videoId: Uuid) => void;
}

function uploadErrorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.body.message;
  return 'The video could not be uploaded. Check the connection and try again.';
}

export function VideoUploadDialog({
  open,
  projectId,
  onClose,
  onUploaded,
}: VideoUploadDialogProps): JSX.Element {
  const notify = useNotify();
  const uploadVideo = useUploadVideo();
  const [progress, setProgress] = useState<number | null>(null);
  const [filename, setFilename] = useState<string | null>(null);

  const onFiles = useCallback(
    (files: File[]) => {
      const file = files[0];
      if (!file) return;
      setFilename(file.name);
      setProgress(0);
      uploadVideo.mutate(
        {
          form: { file, project_id: projectId },
          onProgress: (sent, total) => setProgress(total > 0 ? sent / total : 0),
        },
        {
          onSuccess: (video) => {
            setProgress(null);
            setFilename(null);
            onUploaded(video.id);
          },
          onError: (error) => {
            setProgress(null);
            notify(uploadErrorMessage(error), { severity: 'error' });
          },
        },
      );
    },
    [projectId, uploadVideo, onUploaded, notify],
  );

  // ★ The desktop PATH route: a field video is routinely multiple GB, and the
  //   bytes-over-IPC picker refuses those (this dialog's Browse silently did
  //   nothing — the field report). The local API opens the path directly; there
  //   is no upload phase, so the bar goes straight to "Processing on the server…".
  const onPaths = useCallback(
    (picked: { name: string; path: string }[]) => {
      const p = picked[0];
      if (!p) return;
      setFilename(p.name);
      setProgress(null); // no bytes to count — indeterminate is the honest bar
      uploadVideo.mutate(
        { form: { source_path: p.path, filename: p.name, project_id: projectId } },
        {
          onSuccess: (video) => {
            setProgress(null);
            setFilename(null);
            onUploaded(video.id);
          },
          onError: (error) => {
            setProgress(null);
            notify(uploadErrorMessage(error), { severity: 'error' });
          },
        },
      );
    },
    [projectId, uploadVideo, onUploaded, notify],
  );

  const busy = uploadVideo.isPending;
  const pct = progress === null ? 0 : Math.round(progress * 100);

  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{t('Upload a field video')}</DialogTitle>
      <DialogContent dividers>
        <Stack spacing={2}>
          {projectId === null && (
            <Typography variant="body2" color="text.secondary">
              {t(
                'No project chosen — the clip goes to the video library only. You can still run detection and drift on it, and any frame you capture will ask which project it belongs to.',
              )}
            </Typography>
          )}
          {!busy && (
            <UploadDropzone
              onFiles={onFiles}
              onPaths={onPaths}
              accept="video/*"
              multiple={false}
              hint="MP4 previews best. AVI, MKV and MOV upload too — seek to a second and capture the frame."
            />
          )}
          {busy && (
            <Stack spacing={1}>
              <Typography variant="body2" noWrap title={filename ?? undefined}>
                Uploading {filename ?? 'video'}…
              </Typography>
              <LinearProgress
                variant={progress === null ? 'indeterminate' : 'determinate'}
                value={pct}
                aria-label={t('Video upload progress')}
              />
              <Typography variant="caption" color="text.secondary">
                {progress === null ? 'Processing on the server…' : `${pct}%`}
              </Typography>
            </Stack>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} color="inherit" disabled={busy}>
          {busy ? 'Uploading…' : 'Close'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

export default VideoUploadDialog;
