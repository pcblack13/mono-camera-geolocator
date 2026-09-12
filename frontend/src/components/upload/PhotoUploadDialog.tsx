/**
 * `upload/PhotoUploadDialog.tsx` — single-photo upload WITH a target-resolution control
 * (§ resolution feature).
 *
 * ★ WHY A SEPARATE PATH FROM `BatchUploadDialog`. The batch flow enqueues files and
 *   starts uploading them immediately (concurrency 3) — there is no moment to set a
 *   per-file size before the bytes move, and re-plumbing the queue/store to defer start
 *   for a resolution edit would be invasive. The resolution feature explicitly permits
 *   supporting it on a single-photo path instead, so this dialog owns that path: pick
 *   ONE photo, read its natural dimensions in the browser, optionally choose a target
 *   size, then upload. Batch upload is unchanged.
 *
 * ★ Natural dimensions are read with `createImageBitmap(file)` (then `.close()`), which
 *   most browsers cannot do for TIFF/GeoTIFF — that degrades to "size unknown": the
 *   resolution control hides and the photo uploads at its native size. No GCP warning
 *   here: a fresh upload has none.
 *
 * ★ `target_width`/`target_height` are sent to `POST /images` ONLY when the user changed
 *   them from the original — an untouched upload is byte-for-byte the native file.
 */

import { useCallback, useEffect, useState, type JSX } from 'react';
import Button from '@mui/material/Button';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import LinearProgress from '@mui/material/LinearProgress';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import CloudUploadOutlinedIcon from '@mui/icons-material/CloudUploadOutlined';

import type { ApiError, Uuid } from '../../types/common';
import { isUploadAccepted, type ImageUploadForm } from '../../api/images';
import { useImageUpload } from '../../api/hooks/useImageUpload';
import { ResolutionFields } from '../image/ResolutionFields';
import { useNotify } from '../common/Notifications';
import { UploadDropzone } from './UploadDropzone';
import { t } from '../../i18n';

export interface PhotoUploadDialogProps {
  open: boolean;
  projectId: Uuid;
  onClose: () => void;
  onUploaded: (imageId: Uuid) => void;
}

interface Dims {
  width: number;
  height: number;
}

const ACCEPT = 'image/jpeg,image/png,image/tiff,image/tif';

export function PhotoUploadDialog({
  open,
  projectId,
  onClose,
  onUploaded,
}: PhotoUploadDialogProps): JSX.Element {
  const notify = useNotify();
  const upload = useImageUpload();

  const [file, setFile] = useState<File | null>(null);
  const [original, setOriginal] = useState<Dims | null>(null);
  const [target, setTarget] = useState<Dims>({ width: 0, height: 0 });
  const [progress, setProgress] = useState<number | null>(null);

  const reset = useCallback((): void => {
    setFile(null);
    setOriginal(null);
    setTarget({ width: 0, height: 0 });
    setProgress(null);
  }, []);

  // Fully reset each time the dialog closes so a re-open starts clean.
  useEffect(() => {
    if (!open) reset();
  }, [open, reset]);

  const onFiles = useCallback((files: File[]): void => {
    const picked = files[0];
    if (!picked) return;
    setFile(picked);
    setOriginal(null);
    setTarget({ width: 0, height: 0 });
    // Read natural dimensions in the browser; degrade to "unknown" on formats it
    // cannot decode (commonly TIFF/GeoTIFF).
    void createImageBitmap(picked)
      .then((bitmap) => {
        const dims = { width: bitmap.width, height: bitmap.height };
        bitmap.close();
        setOriginal(dims);
        setTarget(dims);
      })
      .catch(() => {
        setOriginal(null);
      });
  }, []);

  const resized =
    original !== null &&
    target.width >= 1 &&
    target.height >= 1 &&
    (target.width !== original.width || target.height !== original.height);

  const handleUpload = (): void => {
    if (!file || upload.isPending) return;
    const form: ImageUploadForm = { file, project_id: projectId };
    if (resized) {
      form.target_width = target.width;
      form.target_height = target.height;
    }
    setProgress(0);
    upload.mutate(
      {
        form,
        onProgress: (sent, total) => setProgress(total > 0 ? Math.min(1, sent / total) : 0),
      },
      {
        onSuccess: (response) => {
          const image = isUploadAccepted(response) ? response.image : response;
          notify(`Uploaded ${image.filename}.`, { severity: 'success' });
          onUploaded(image.id);
          onClose();
        },
        onError: (error) => {
          setProgress(null);
          const message = (error as ApiError)?.message ?? 'Upload failed.';
          notify(message, { severity: 'error' });
        },
      },
    );
  };

  return (
    <Dialog open={open} onClose={upload.isPending ? undefined : onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{t('Upload a photo with a chosen resolution')}</DialogTitle>
      <DialogContent dividers>
        <Stack spacing={2}>
          {!file ? (
            <UploadDropzone
              onFiles={onFiles}
              accept={ACCEPT}
              multiple={false}
              hint="JPEG, PNG, TIFF or GeoTIFF. One photo at a time, so you can set its size."
            />
          ) : (
            <>
              <Typography variant="body2" noWrap title={file.name}>
                {file.name}
              </Typography>

              {original !== null ? (
                <>
                  <Typography variant="body2" color="text.secondary">
                    Original:{' '}
                    <Typography component="span" variant="mono" sx={{ fontSize: 13 }}>
                      {original.width} × {original.height}
                    </Typography>
                  </Typography>
                  <ResolutionFields
                    originalWidth={original.width}
                    originalHeight={original.height}
                    width={target.width}
                    height={target.height}
                    onChange={(width, height) => setTarget({ width, height })}
                    disabled={upload.isPending}
                  />
                </>
              ) : (
                <Typography variant="body2" color="text.secondary">
                  {t(
                    'These dimensions could not be read in the browser, so this photo will upload at its native resolution.',
                  )}
                </Typography>
              )}

              {progress !== null && (
                <LinearProgress variant="determinate" value={Math.round(progress * 100)} />
              )}

              <Button
                variant="text"
                size="small"
                onClick={reset}
                disabled={upload.isPending}
                sx={{ alignSelf: 'flex-start' }}
              >
                {t('Choose a different photo')}
              </Button>
            </>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} color="inherit" disabled={upload.isPending}>
          {t('Cancel')}
        </Button>
        <Button
          onClick={handleUpload}
          variant="contained"
          disabled={!file || upload.isPending}
          startIcon={<CloudUploadOutlinedIcon />}
        >
          {upload.isPending
            ? 'Uploading…'
            : resized
              ? `Upload at ${target.width} × ${target.height}`
              : 'Upload'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

export default PhotoUploadDialog;
