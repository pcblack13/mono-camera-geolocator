/**
 * `lut/LutImportDialog.tsx` — file a lookup table this app did not build.
 *
 * ★ WHY IT IS ONE DIALOG, NOT FOUR. Every page that puts a detection on the map —
 *   live stream, video detection, drift monitor — picks its table BY NAME out of one
 *   library (`GET /lut/library`). So "let me use my own LUT here" and "add a LUT to
 *   the library" are the same act, and importing from any of those pages files the
 *   bundle in the one library the others read. The caller passes `onImported` and
 *   selects the returned `site_name` immediately; nobody has to go to the generator
 *   page and come back.
 *
 * ★ WHAT CAN BE DROPPED IN. Both halves of this app's own export story: the
 *   payload-only `.zip` it hands out (`lat.npy` + `lon.npy`), and a FULL bundle —
 *   zip or folder — carrying its manifest. A full bundle keeps its pose, DEM
 *   checksum and validation report; a payload-only one gets a synthesised manifest
 *   and is honest about being thin (see the note this dialog shows on success).
 *
 * ★ THREE WAYS IN, because the desktop has to be able to do what the browser
 *   cannot. Desktop picks a PATH — a 150 MB bundle never touches the HTTP body, and
 *   a bundle FOLDER (which cannot be uploaded at all) works too. A browser tab
 *   uploads the zip with a real progress bar. Drag-and-drop lands in the same place.
 *
 * ★ THE SERVER IS THE AUTHORITY ON WHETHER A FILE IS A LUT. It checks shape, dtype
 *   and that the values are decimal degrees — a table in projected metres would not
 *   fail, it would place every mark plausibly and wrongly. This dialog shows those
 *   refusals verbatim rather than pre-judging the file.
 */

import { useEffect, useRef, useState, type ChangeEvent, type DragEvent, type JSX } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import Alert from '@mui/material/Alert';
import AlertTitle from '@mui/material/AlertTitle';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import LinearProgress from '@mui/material/LinearProgress';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import FolderOpenOutlinedIcon from '@mui/icons-material/FolderOpenOutlined';
import UploadFileOutlinedIcon from '@mui/icons-material/UploadFileOutlined';

import { lutApi, type LutLibraryEntry } from '../../api/lut';
import { qk } from '../../api/queryKeys';
import {
  browseNativeOrInput,
  hasNativeDirectoryPicker,
  hasNativePathPicker,
  pickDirectoryNative,
  pickFilePathsNative,
} from '../../lib/nativeFilePicker';
import { ApiError } from '../../types/common';
import { useNotify } from '../common/Notifications';
import { t } from '../../i18n';

/** What the user chose: bytes to upload, or a path the local API opens itself. */
type Chosen =
  | { kind: 'file'; name: string; file: File }
  | { kind: 'path'; name: string; path: string };

const ZIP_FILTERS = [{ name: 'LUT bundle (.zip)', extensions: ['zip'] }];

/** `yammone_lut.zip` → `yammone`; `arsal_lut` → `arsal`. Same rule the server uses. */
export function siteNameFromPick(name: string): string {
  const stem = name.replace(/\.zip$/i, '');
  return stem
    .replace(/_lut$/i, '')
    .replace(/[^A-Za-z0-9_-]+/g, '_')
    .replace(/^_+|_+$/g, '');
}

export interface LutImportDialogProps {
  open: boolean;
  onClose: () => void;
  /**
   * The imported bundle, once it is in the library. Callers with a LUT picker use
   * this to select it straight away — the whole point of importing from their page.
   */
  onImported?: (entry: LutLibraryEntry) => void;
}

export function LutImportDialog({ open, onClose, onImported }: LutImportDialogProps): JSX.Element {
  const notify = useNotify();
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement | null>(null);

  const [chosen, setChosen] = useState<Chosen | null>(null);
  const [siteName, setSiteName] = useState('');
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  // ★ Only offered after the server has said the name is taken — an overwrite
  //   checkbox on an empty form invites replacing a working table by accident.
  const [clash, setClash] = useState(false);

  useEffect(() => {
    if (!open) {
      setChosen(null);
      setSiteName('');
      setError(null);
      setClash(false);
      setSent(null);
      setBusy(false);
    }
  }, [open]);

  const accept = (next: Chosen): void => {
    setChosen(next);
    setError(null);
    setClash(false);
    setSiteName(siteNameFromPick(next.name));
  };

  // ★ Native-first, path-first: the in-page GTK chooser crashes the desktop app
  //   (see lib/nativeFilePicker), and a full-resolution bundle is ~150 MB — the
  //   local API opens it from disk instead of taking it over HTTP.
  const browse = (): void => {
    if (hasNativePathPicker()) {
      void pickFilePathsNative(ZIP_FILTERS, false).then((picked) => {
        if (picked && picked.length > 0) {
          accept({ kind: 'path', name: picked[0].name, path: picked[0].path });
        }
      });
      return;
    }
    browseNativeOrInput(
      inputRef.current,
      ZIP_FILTERS,
      (files) => {
        if (files.length > 0) accept({ kind: 'file', name: files[0].name, file: files[0] });
      },
      false,
      (skipped) => skipped.forEach((s) => notify(`${s.name}: ${s.reason}`, { severity: 'error' })),
    );
  };

  /** The unzipped route: a bundle FOLDER off a USB stick, opened where it lies. */
  const browseFolder = (): void => {
    void pickDirectoryNative().then((path) => {
      if (path) {
        const name =
          path
            .replace(/[\\/]+$/, '')
            .split(/[\\/]/)
            .pop() ?? path;
        accept({ kind: 'path', name, path });
      }
    });
  };

  const submit = (overwrite: boolean): void => {
    if (!chosen) return;
    setBusy(true);
    setError(null);
    setSent(null);
    lutApi
      .import(
        {
          ...(chosen.kind === 'file' ? { file: chosen.file } : { source_path: chosen.path }),
          site_name: siteName.trim() === '' ? undefined : siteName.trim(),
          overwrite,
        },
        { onProgress: (bytes) => setSent(bytes) },
      )
      .then(async (entry) => {
        await queryClient.invalidateQueries({ queryKey: qk.lut.library() });
        notify(
          entry.has_pose
            ? `“${entry.site_name}” is in the LUT library.`
            : `“${entry.site_name}” is in the LUT library — it carries no pose, so it can place detections but cannot serve the drift monitor.`,
          { severity: entry.has_pose ? 'success' : 'warning' },
        );
        onImported?.(entry);
        onClose();
      })
      .catch((err: unknown) => {
        // ★ The server's message names the exact problem ("these are not decimal
        //   degrees", "the archive holds no LUT bundle") — show it, do not summarise it.
        const status = err instanceof ApiError ? err.status : 0;
        setClash(status === 409);
        setError(err instanceof ApiError ? err.message : String(err));
      })
      .finally(() => {
        setBusy(false);
        setSent(null);
      });
  };

  const onDrop = (e: DragEvent<HTMLDivElement>): void => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) accept({ kind: 'file', name: file.name, file });
  };

  const total = chosen?.kind === 'file' ? chosen.file.size : 0;
  const percent = sent !== null && total > 0 ? Math.min(100, (sent / total) * 100) : null;

  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{t('Import a lookup table')}</DialogTitle>
      <DialogContent>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          {t(
            'Add a bundle built elsewhere — on another machine, or handed over with the camera. It joins the same library the live stream, video detection and drift monitor all pick from.',
          )}
        </Typography>

        <Box
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          sx={{
            p: 2.5,
            textAlign: 'center',
            borderRadius: 'var(--radius-lg)',
            border: '1px dashed',
            borderColor: dragging ? 'var(--accent)' : 'var(--hairline-strong)',
            bgcolor: dragging ? 'var(--bg-hover)' : 'transparent',
          }}
        >
          <Typography variant="body2" sx={{ mb: 1.5 }}>
            {chosen ? (
              <Box component="span" sx={{ fontFamily: 'var(--font-mono, monospace)' }}>
                {chosen.name}
              </Box>
            ) : (
              t('Drop a bundle .zip here, or choose one.')
            )}
          </Typography>
          <Stack direction="row" spacing={1} justifyContent="center">
            <Button
              size="small"
              variant="outlined"
              startIcon={<UploadFileOutlinedIcon />}
              onClick={browse}
              disabled={busy}
            >
              {t('Choose .zip')}
            </Button>
            {/* ★ Desktop only: the API shares this machine, so an UNZIPPED bundle
                folder can be imported where it lies. A browser cannot offer this. */}
            {hasNativeDirectoryPicker() && (
              <Button
                size="small"
                variant="outlined"
                startIcon={<FolderOpenOutlinedIcon />}
                onClick={browseFolder}
                disabled={busy}
              >
                {t('Choose folder')}
              </Button>
            )}
          </Stack>
          <input
            ref={inputRef}
            type="file"
            accept=".zip,application/zip"
            hidden
            onChange={(e: ChangeEvent<HTMLInputElement>) => {
              const file = e.target.files?.[0];
              if (file) accept({ kind: 'file', name: file.name, file });
              e.target.value = ''; // let the same file be picked again after an error
            }}
          />
        </Box>

        <TextField
          fullWidth
          size="small"
          label={t('Name in the library')}
          value={siteName}
          onChange={(e) => setSiteName(e.target.value)}
          disabled={busy}
          sx={{ mt: 2 }}
          helperText={
            siteName.trim() === ''
              ? t('Leave blank to use the bundle’s own name.')
              : `${t('Filed as')} ${siteName.trim()}_lut`
          }
        />

        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1.5 }}>
          {t(
            'A bundle that carries its manifest keeps its pose and validation report. One that is only lat.npy + lon.npy can place detections, but not serve the drift monitor.',
          )}
        </Typography>

        {busy && (
          <Box sx={{ mt: 2 }}>
            <LinearProgress
              variant={percent === null ? 'indeterminate' : 'determinate'}
              value={percent ?? 0}
            />
            <Typography variant="caption" color="text.secondary">
              {percent === null
                ? t('Checking the bundle…')
                : `${t('Uploading')} ${percent.toFixed(0)}%`}
            </Typography>
          </Box>
        )}

        {error !== null && (
          <Alert severity={clash ? 'warning' : 'error'} sx={{ mt: 2 }}>
            <AlertTitle>
              {clash ? t('That name is taken') : t('That bundle was not imported')}
            </AlertTitle>
            {error}
          </Alert>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>
          {t('Cancel')}
        </Button>
        {/* ★ Replacing is a SECOND, deliberate press — never a checkbox ticked before
            anyone knew there was a conflict. */}
        {clash && (
          <Button color="warning" onClick={() => submit(true)} disabled={busy}>
            {t('Replace it')}
          </Button>
        )}
        <Button
          variant="contained"
          onClick={() => submit(false)}
          disabled={busy || chosen === null}
        >
          {t('Import')}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

export default LutImportDialog;
