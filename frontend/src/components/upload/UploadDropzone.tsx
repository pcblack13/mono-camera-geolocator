/**
 * `upload/UploadDropzone.tsx` — the drop target (50-frontend §2.25 / §8.1).
 *
 * ★ (pure). It captures files and hands them up; it owns no queue, no transport and
 *   no store. The queue is `uploadStore` (IU-25), the transport is IU-24, and the
 *   validation policy is the dialog's — this component only turns a drop or a browse
 *   into a `File[]`.
 *
 * ★ Copy states what belongs here and the limits, per §8.1: "Drop a field photograph
 *   here, or browse." A blank dashed box teaches nothing.
 */

import { useCallback, useId, useRef, useState, type DragEvent, type JSX } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import CloudUploadOutlinedIcon from '@mui/icons-material/CloudUploadOutlined';
import { alpha } from '@mui/material/styles';
import {
  browseNativeOrInput,
  filtersFromAccept,
  hasNativePathPicker,
  pickFilePathsNative,
  type NativePickedPath,
} from '../../lib/nativeFilePicker';
import { t } from '../../i18n';

export interface UploadDropzoneProps {
  onFiles: (files: File[]) => void;
  /**
   * ★ When given AND the desktop path picker exists, the Browse button picks PATHS
   *   (`{name, path, size}`, no bytes) and calls this instead of `onFiles` — the
   *   multi-GB route (videos, rasters): the local API opens the path directly,
   *   where the bytes-over-IPC route hard-fails above its ceiling. Drag-and-drop
   *   still delivers `File`s (disk-backed blobs stream fine) via `onFiles`.
   */
  onPaths?: (paths: NativePickedPath[]) => void;
  /** The `accept` attribute + drop filter, e.g. 'image/jpeg,image/png,image/tiff'. */
  accept?: string;
  multiple?: boolean;
  disabled?: boolean;
  /** Secondary line under the prompt, e.g. "JPEG/PNG/TIFF up to 200 MB." */
  hint?: string;
  compact?: boolean;
}

const DEFAULT_ACCEPT = 'image/jpeg,image/png,image/tiff,image/tif';

export function UploadDropzone({
  onFiles,
  onPaths,
  accept = DEFAULT_ACCEPT,
  multiple = true,
  disabled = false,
  hint = 'JPEG, PNG, TIFF or GeoTIFF.',
  compact = false,
}: UploadDropzoneProps): JSX.Element {
  const inputRef = useRef<HTMLInputElement>(null);
  const inputId = useId();
  const [dragActive, setDragActive] = useState(false);

  const emit = useCallback(
    (list: FileList | null) => {
      if (!list || list.length === 0) return;
      onFiles(Array.from(list));
    },
    [onFiles],
  );

  const onDrop = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setDragActive(false);
      if (disabled) return;
      emit(e.dataTransfer.files);
    },
    [disabled, emit],
  );

  const onDragOver = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      if (!disabled) setDragActive(true);
    },
    [disabled],
  );

  return (
    <Box
      onDrop={onDrop}
      onDragOver={onDragOver}
      onDragLeave={() => setDragActive(false)}
      sx={(theme) => ({
        border: '2px dashed',
        borderColor: dragActive ? 'primary.main' : 'divider',
        borderRadius: 2,
        bgcolor: dragActive ? alpha(theme.palette.primary.main, 0.06) : 'transparent',
        p: compact ? 2 : 4,
        textAlign: 'center',
        transition: theme.transitions.create(['border-color', 'background-color']),
        opacity: disabled ? 0.5 : 1,
        pointerEvents: disabled ? 'none' : 'auto',
      })}
    >
      <input
        ref={inputRef}
        id={inputId}
        type="file"
        accept={accept}
        multiple={multiple}
        hidden
        onChange={(e) => {
          emit(e.target.files);
          e.target.value = '';
        }}
      />
      <Stack spacing={compact ? 1 : 1.5} alignItems="center">
        <CloudUploadOutlinedIcon
          sx={{ fontSize: compact ? 32 : 48, color: 'text.disabled' }}
          aria-hidden
        />
        <Typography variant={compact ? 'body2' : 'subtitle1'}>
          {t('Drop a field photograph here, or')}
        </Typography>
        <Button
          variant="outlined"
          onClick={(e) => {
            // ★ Native-first. preventDefault stops the label-for behaviour from
            //   ALSO opening the in-page chooser (the one that crashes GTK).
            e.preventDefault();
            // ★ PATH route when the caller supports it (multi-GB uploads) — same
            //   dialogs, but no bytes cross IPC; the local API reads the disk.
            if (onPaths && hasNativePathPicker()) {
              void pickFilePathsNative(filtersFromAccept(accept, 'Files'), multiple).then(
                (picked) => {
                  if (picked && picked.length > 0) onPaths(picked);
                },
              );
              return;
            }
            browseNativeOrInput(
              inputRef.current,
              filtersFromAccept(accept, 'Photographs'),
              onFiles,
              multiple,
            );
          }}
          disabled={disabled}
          component="label"
          htmlFor={inputId}
        >
          {t('Browse files')}
        </Button>
        {hint !== '' && (
          <Typography variant="caption" color="text.secondary">
            {hint}
          </Typography>
        )}
      </Stack>
    </Box>
  );
}

export default UploadDropzone;
