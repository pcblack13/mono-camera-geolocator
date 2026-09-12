/**
 * `image/ImportFromLibraryDialog.tsx` — reuse a captured photo in this project.
 *
 * ★ THE LIBRARY IS THE CAPTURE FOLDER (`~/Pictures/LandExplorer`): every video-frame
 *   capture drops a plain JPEG there precisely so one photograph can serve several
 *   projects. This dialog is the other half of that promise — browse the folder,
 *   tick the photos you need, import. No re-hunting files in an OS picker.
 *
 * ★ MULTI-SELECT, because the flow that motivated it is a PAIR (the same two
 *   calibration photos in every project). Imports run sequentially — each is a full
 *   upload server-side (dedupe + ingest), and firing twenty at once would just
 *   queue-thrash the ingest worker.
 *
 * ★ Imported photos arrive WITHOUT camera setup, like any fresh upload — the
 *   project page's gear (or first open) leads to their setup page, same as always.
 */

import { useState, type JSX } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Checkbox from '@mui/material/Checkbox';
import CircularProgress from '@mui/material/CircularProgress';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import Typography from '@mui/material/Typography';
import PhotoLibraryOutlinedIcon from '@mui/icons-material/PhotoLibraryOutlined';

import { captureLibraryApi } from '../../api/captureLibrary';
import { qk } from '../../api/queryKeys';
import { useNotify } from '../common/Notifications';
import { ApiError, type Uuid } from '../../types/common';
import type { ImageRead } from '../../types/image';
import { t } from '../../i18n';

export interface ImportFromLibraryDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: Uuid;
  /**
   * ★ Single-select mode, for callers that need ONE photo to continue with (the
   * image-setup page: a setup describes exactly one photograph). Picking a second
   * photo replaces the first instead of joining it.
   */
  single?: boolean;
  /** Called with the images that actually imported, in selection order. */
  onImported?: (imported: ImageRead[]) => void;
}

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

export function ImportFromLibraryDialog({
  open,
  onClose,
  projectId,
  single = false,
  onImported,
}: ImportFromLibraryDialogProps): JSX.Element {
  const notify = useNotify();
  const queryClient = useQueryClient();

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['capture-library'],
    queryFn: ({ signal }) => captureLibraryApi.list(signal),
    enabled: open,
    // The folder changes outside the app's knowledge (it is the user's) — refetch
    // whenever the dialog opens rather than trusting a stale cache.
    refetchOnMount: 'always',
  });

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [importing, setImporting] = useState(false);

  const toggle = (name: string): void => {
    setSelected((prev) => {
      if (single) return prev.has(name) ? new Set<string>() : new Set([name]);
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const close = (): void => {
    if (importing) return;
    setSelected(new Set());
    onClose();
  };

  const runImport = async (): Promise<void> => {
    const names = [...selected];
    setImporting(true);
    const importedImages: ImageRead[] = [];
    let imported = 0;
    let failed = 0;
    for (const name of names) {
      try {
        importedImages.push(await captureLibraryApi.importIntoProject(name, projectId));
        imported += 1;
      } catch (error) {
        failed += 1;
        const detail = error instanceof ApiError ? ` (${error.body.message})` : '';
        notify(`Could not import “${name}”${detail}`, { severity: 'error' });
      }
    }
    setImporting(false);
    if (imported > 0) {
      await queryClient.invalidateQueries({ queryKey: qk.images.list(projectId) });
      notify(
        imported === 1
          ? 'Imported 1 photo — it is in the project now.'
          : `Imported ${imported} photos — they are in the project now.`,
        { severity: failed > 0 ? 'warning' : 'success' },
      );
    }
    if (imported > 0) onImported?.(importedImages);
    if (failed === 0) {
      setSelected(new Set());
      onClose();
    }
  };

  const items = data?.items ?? [];

  return (
    <Dialog open={open} onClose={close} maxWidth="md" fullWidth>
      <DialogTitle>{t('Add from your capture library')}</DialogTitle>
      <DialogContent>
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 2 }}>
          {data?.folder
            ? `Photos captured from videos are saved to ${data.folder} — pick any to reuse in this project.`
            : 'Photos captured from videos are saved on this computer for reuse across projects.'}
        </Typography>

        {isLoading ? (
          <Box sx={{ display: 'grid', placeItems: 'center', py: 6 }}>
            <CircularProgress size={28} />
          </Box>
        ) : isError ? (
          <Alert
            severity="error"
            action={
              <Button color="inherit" size="small" onClick={() => void refetch()}>
                {t('Retry')}
              </Button>
            }
          >
            {t('Could not read the capture library.')}
          </Alert>
        ) : items.length === 0 ? (
          <Box sx={{ textAlign: 'center', py: 6, color: 'text.secondary' }}>
            <PhotoLibraryOutlinedIcon sx={{ fontSize: 40, mb: 1 }} />
            <Typography variant="body2">
              {t(
                'Nothing here yet. Capture frames from a video and they appear in this library automatically, ready to reuse in any project.',
              )}
            </Typography>
          </Box>
        ) : (
          <Box
            sx={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))',
              gap: 1.5,
            }}
          >
            {items.map((item) => {
              const checked = selected.has(item.filename);
              return (
                <Box
                  key={item.filename}
                  onClick={() => !importing && toggle(item.filename)}
                  role="checkbox"
                  aria-checked={checked}
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if ((e.key === 'Enter' || e.key === ' ') && !importing) {
                      e.preventDefault();
                      toggle(item.filename);
                    }
                  }}
                  sx={{
                    'position': 'relative',
                    'borderRadius': 1,
                    'overflow': 'hidden',
                    'cursor': importing ? 'default' : 'pointer',
                    'border': 2,
                    'borderColor': checked ? 'primary.main' : 'divider',
                    'transition': (t) => t.transitions.create('border-color'),
                    '&:hover': { borderColor: checked ? 'primary.main' : 'text.disabled' },
                  }}
                >
                  <Box
                    component="img"
                    src={captureLibraryApi.fileUrl(item.filename)}
                    alt={item.filename}
                    loading="lazy"
                    sx={{
                      width: '100%',
                      aspectRatio: '4 / 3',
                      objectFit: 'cover',
                      display: 'block',
                      bgcolor: 'action.hover',
                    }}
                  />
                  <Checkbox
                    checked={checked}
                    tabIndex={-1}
                    sx={{
                      'position': 'absolute',
                      'top': 2,
                      'right': 2,
                      'bgcolor': 'rgba(0,0,0,0.35)',
                      'borderRadius': 1,
                      'p': 0.25,
                      'color': 'common.white',
                      '&.Mui-checked': { color: 'primary.light' },
                    }}
                  />
                  <Box sx={{ p: 0.75 }}>
                    <Typography variant="caption" noWrap display="block" title={item.filename}>
                      {item.filename}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {formatSize(item.size_bytes)}
                    </Typography>
                  </Box>
                </Box>
              );
            })}
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={close} disabled={importing}>
          {t('Cancel')}
        </Button>
        <Button
          variant="contained"
          onClick={() => void runImport()}
          disabled={selected.size === 0 || importing}
          startIcon={
            importing ? (
              <CircularProgress size={16} color="inherit" />
            ) : (
              <PhotoLibraryOutlinedIcon />
            )
          }
        >
          {importing
            ? 'Importing…'
            : selected.size === 0
              ? 'Import'
              : `Import ${selected.size} photo${selected.size === 1 ? '' : 's'}`}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

export default ImportFromLibraryDialog;
