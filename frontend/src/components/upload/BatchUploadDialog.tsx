/**
 * `upload/BatchUploadDialog.tsx` — multi-image upload (50-frontend §2.25, SCOPE.md §3).
 *
 * ★ Batch UPLOAD is fully built (SCOPE.md §3); only batch MATCHING is deferred. This
 *   dialog is the built half: a dropzone plus a queue of `BatchUploadRow`s, capped at
 *   concurrency 3 by `uploadStore` (field cellular is the design target).
 *
 * ★ THE SEAM (§2.25 / IU-24 `useUploaderRegistration`): the queue, ordering,
 *   concurrency and per-item progress are `uploadStore`'s; the transport is IU-24's,
 *   registered by `useUploaderRegistration`. This container does NOT open its own
 *   `fetch`/XHR — "an XMLHttpRequest opened from a store would be a second,
 *   unauthenticated API client with no ErrorEnvelope parsing and no request id."
 *
 * ★ CLIENT-SIDE PRE-VALIDATION before any byte is sent — MIME allowlist and max
 *   bytes, read from the server's own reported limits (`useCapabilities`). Failing
 *   fast locally is a courtesy on a slow link; the server re-validates authoritatively.
 *
 * ★ `processing` → `done`: a small image is ingested synchronously, a large one via a
 *   job (§8.4). Either way the store sits in `processing` until the row's image reports
 *   `ready`; `ProcessingWatcher` polls the image and calls `markProcessed`, so "Ready"
 *   never lies.
 */

import { useCallback, useEffect, useMemo, type JSX } from 'react';
import { useShallow } from 'zustand/react/shallow';
import Button from '@mui/material/Button';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

import { useUploaderRegistration } from '../../api/hooks/useImageUpload';
import { useImage } from '../../api/hooks/useImages';
import { useCapabilities } from '../../api/hooks/useCapabilities';
import { useUploadStore } from '../../store/uploadStore';
import type { UploadItem } from '../../store/uploadStore';
import type { Uuid } from '../../types/common';
import { useNotify } from '../common/Notifications';
import { UploadDropzone } from './UploadDropzone';
import { BatchUploadRow } from './BatchUploadRow';
import { t } from '../../i18n';

export interface BatchUploadDialogProps {
  open: boolean;
  projectId: Uuid;
  onClose: () => void;
  onComplete: (imageIds: Uuid[]) => void;
}

const ACCEPTED_MIME = new Set(['image/jpeg', 'image/png', 'image/tiff', 'image/tif']);
const FALLBACK_MAX_BYTES = 200 * 1024 * 1024; // matches index.html's stated limit
const TERMINALISH = new Set(['done', 'error', 'cancelled']);

/** Polls one uploaded image until its server-side ingest reaches a terminal status. */
function ProcessingWatcher({
  clientId,
  imageId,
  onProcessed,
}: {
  clientId: string;
  imageId: Uuid;
  onProcessed: (clientId: string) => void;
}): null {
  const query = useImage(imageId);
  const status = query.data?.status;

  useEffect(() => {
    if (status === 'ready' || status === 'failed') {
      onProcessed(clientId);
      return undefined;
    }
    const id = window.setInterval(() => void query.refetch(), 2000);
    return () => window.clearInterval(id);
  }, [status, clientId, imageId, onProcessed, query]);

  return null;
}

export function BatchUploadDialog({
  open,
  projectId,
  onClose,
  onComplete,
}: BatchUploadDialogProps): JSX.Element {
  const notify = useNotify();
  const { data: capabilities } = useCapabilities();
  const maxBytes = capabilities?.limits.upload_max_bytes ?? FALLBACK_MAX_BYTES;

  // ★ Register IU-24's transport with the queue for the lifetime of this project view.
  useUploaderRegistration(projectId);

  const { items, enqueue, start, retry, remove, clearCompleted, markProcessed } = useUploadStore(
    useShallow((s) => ({
      items: s.items,
      enqueue: s.enqueue,
      start: s.start,
      retry: s.retry,
      remove: s.remove,
      clearCompleted: s.clearCompleted,
      markProcessed: s.markProcessed,
    })),
  );

  const onFiles = useCallback(
    (files: File[]) => {
      const accepted: File[] = [];
      const rejected: string[] = [];
      for (const file of files) {
        if (file.type && !ACCEPTED_MIME.has(file.type)) {
          rejected.push(`${file.name}: unsupported format`);
        } else if (file.size > maxBytes) {
          rejected.push(`${file.name}: exceeds ${Math.round(maxBytes / (1024 * 1024))} MB`);
        } else {
          accepted.push(file);
        }
      }
      if (rejected.length > 0) {
        notify(`Skipped ${rejected.length} file(s): ${rejected.join('; ')}`, {
          severity: 'warning',
        });
      }
      if (accepted.length > 0) {
        enqueue(accepted);
        start();
      }
    },
    [enqueue, start, maxBytes, notify],
  );

  const allTerminal =
    items.length > 0 && items.every((i) => TERMINALISH.has(i.status) || i.status === 'processing');
  const readyIds = useMemo<Uuid[]>(
    () => items.filter((i) => i.imageId !== null).map((i) => i.imageId as Uuid),
    [items],
  );

  const processing = items.filter(
    (i): i is UploadItem & { imageId: Uuid } => i.status === 'processing' && i.imageId !== null,
  );

  const handleDone = useCallback(() => {
    onComplete(readyIds);
    clearCompleted();
    onClose();
  }, [onComplete, readyIds, clearCompleted, onClose]);

  const uploadingCount = items.filter(
    (i) => i.status === 'uploading' || i.status === 'queued',
  ).length;

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{t('Upload field photographs')}</DialogTitle>
      <DialogContent dividers>
        <Stack spacing={2}>
          <UploadDropzone
            onFiles={onFiles}
            hint={`JPEG, PNG, TIFF or GeoTIFF up to ${Math.round(maxBytes / (1024 * 1024))} MB. Up to 3 upload at once.`}
          />

          {items.length > 0 && (
            <Stack>
              <Typography variant="overline" color="text.secondary">
                Queue ({items.length})
              </Typography>
              {items.map((item) => (
                <BatchUploadRow key={item.clientId} item={item} onRetry={retry} onRemove={remove} />
              ))}
            </Stack>
          )}

          {/* Per-image ingest watchers — render nothing, poll to move processing → done. */}
          {processing.map((item) => (
            <ProcessingWatcher
              key={`watch-${item.clientId}`}
              clientId={item.clientId}
              imageId={item.imageId}
              onProcessed={markProcessed}
            />
          ))}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} color="inherit">
          {uploadingCount > 0 ? 'Continue in background' : 'Cancel'}
        </Button>
        <Button
          variant="contained"
          onClick={handleDone}
          disabled={!allTerminal || readyIds.length === 0}
        >
          Done{readyIds.length > 0 ? ` (${readyIds.length})` : ''}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

export default BatchUploadDialog;
