/**
 * `dem/DemLibraryPanel.tsx` — the processed-DEM library, listed for reuse.
 *
 * ★ ONE COMPONENT, TWO HOMES. On the DEM processing page it is the side panel
 *   ("what have I already processed?"); inside the image-setup dialog it is the
 *   picker ("use one of those for THIS project"). Same list, same adoption call —
 *   the only difference is whether a `projectId` is present, which turns each row's
 *   action on.
 *
 * ★ Adoption is SERVER-SIDE re-processing of the library file (with reprojection
 *   auto-skipped for already-metric tiles), so a "used" DEM is byte-for-byte the
 *   project's own copy — deleting the library entry later cannot strand a project.
 */

import { useState, type JSX } from 'react';
import { useQuery } from '@tanstack/react-query';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import CircularProgress from '@mui/material/CircularProgress';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogContentText from '@mui/material/DialogContentText';
import DialogTitle from '@mui/material/DialogTitle';
import IconButton from '@mui/material/IconButton';
import List from '@mui/material/List';
import ListItem from '@mui/material/ListItem';
import ListItemIcon from '@mui/material/ListItemIcon';
import ListItemText from '@mui/material/ListItemText';
import Stack from '@mui/material/Stack';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import TerrainOutlinedIcon from '@mui/icons-material/TerrainOutlined';

import { demLibraryApi } from '../../api/demLibrary';
import { qk } from '../../api/queryKeys';
import { useNotify } from '../common/Notifications';
import { ApiError, type Uuid } from '../../types/common';
import { t } from '../../i18n';
import { ErrorState } from '../ui';

export interface DemLibraryPanelProps {
  /** When given, every row offers "Use for this project" (adoption). */
  projectId?: Uuid | null;
  /**
   * ★ When given (with `projectId`), adoption targets THIS image instead of the whole
   *   project — the library row's "Use" button attaches the DEM to one photograph.
   */
  imageId?: Uuid | null;
  /** Called after a successful adoption — refresh whatever shows the project DEM. */
  onAdopted?: (filename: string) => void;
  /** Bumped by the parent to force a refetch (e.g. after a processing run). */
  refreshKey?: number;
  /**
   * ★ MANAGE MODE (1.2.6): each row also offers delete (with a confirm). On the DEM
   *   processing page — the library's home — this is on; inside the adoption dialogs
   *   it stays off, so a picker never doubles as a destroyer.
   */
  allowDelete?: boolean;
}

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

export function DemLibraryPanel({
  projectId = null,
  imageId = null,
  onAdopted,
  refreshKey = 0,
  allowDelete = false,
}: DemLibraryPanelProps): JSX.Element {
  const notify = useNotify();
  const [adopting, setAdopting] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: qk.demLibrary.list(refreshKey),
    queryFn: ({ signal }) => demLibraryApi.list(signal),
    refetchOnMount: 'always', // the folder is the user's; never trust a stale cache
  });

  const adopt = async (filename: string): Promise<void> => {
    if (projectId === null) return;
    setAdopting(filename);
    try {
      if (imageId !== null) {
        await demLibraryApi.adoptIntoImage(filename, projectId, imageId);
        notify(`“${filename}” is now this image's elevation source.`, { severity: 'success' });
      } else {
        await demLibraryApi.adoptIntoProject(filename, projectId);
        notify(`“${filename}” is now this project's elevation source.`, { severity: 'success' });
      }
      onAdopted?.(filename);
    } catch (error) {
      const detail = error instanceof ApiError ? ` (${error.body.message})` : '';
      notify(`Could not use “${filename}”${detail}`, { severity: 'error' });
    } finally {
      setAdopting(null);
    }
  };

  const confirmDelete = async (): Promise<void> => {
    if (pendingDelete === null) return;
    setDeleting(true);
    try {
      await demLibraryApi.remove(pendingDelete);
      notify(`“${pendingDelete}” deleted from the DEM library.`, { severity: 'success' });
      setPendingDelete(null);
      await refetch();
    } catch (error) {
      const detail = error instanceof ApiError ? ` (${error.body.message})` : '';
      notify(`Could not delete “${pendingDelete}”${detail}`, { severity: 'error' });
    } finally {
      setDeleting(false);
    }
  };

  const items = data?.items ?? [];

  return (
    <Box>
      <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
        {t('Processed DEM library')}
      </Typography>
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1.5 }}>
        {data?.folder
          ? `Every processed DEM is saved to ${data.folder}, ready to reuse.`
          : 'Every processed DEM is saved on this computer, ready to reuse.'}
      </Typography>

      {isLoading ? (
        <Box sx={{ display: 'grid', placeItems: 'center', py: 4 }}>
          <CircularProgress size={22} />
        </Box>
      ) : isError ? (
        <ErrorState
          message={t('Could not read the DEM library.')}
          action={{ label: t('Retry'), onClick: () => void refetch() }}
        />
      ) : items.length === 0 ? (
        <Typography variant="caption" color="text.secondary">
          {t(
            'Nothing here yet — process a DEM and its output appears in this library automatically.',
          )}
        </Typography>
      ) : (
        <List dense disablePadding>
          {items.map((item) => (
            <ListItem
              key={item.filename}
              disableGutters
              sx={{ alignItems: 'flex-start' }}
              secondaryAction={
                projectId !== null || allowDelete ? (
                  <Stack direction="row" spacing={0.5} alignItems="center">
                    {projectId !== null && (
                      <Button
                        size="small"
                        variant="outlined"
                        disabled={adopting !== null || deleting}
                        onClick={() => void adopt(item.filename)}
                        startIcon={
                          adopting === item.filename ? (
                            <CircularProgress size={12} color="inherit" />
                          ) : undefined
                        }
                      >
                        {adopting === item.filename ? 'Using…' : 'Use'}
                      </Button>
                    )}
                    {allowDelete && (
                      <Tooltip title={t('Delete from the library')}>
                        <span>
                          <IconButton
                            size="small"
                            aria-label={`Delete ${item.filename}`}
                            disabled={adopting !== null || deleting}
                            onClick={() => setPendingDelete(item.filename)}
                            sx={{ '&:hover': { color: 'error.main' } }}
                          >
                            <DeleteOutlineIcon fontSize="small" />
                          </IconButton>
                        </span>
                      </Tooltip>
                    )}
                  </Stack>
                ) : undefined
              }
            >
              <ListItemIcon sx={{ minWidth: 32, mt: 0.5 }}>
                <TerrainOutlinedIcon fontSize="small" color="action" />
              </ListItemIcon>
              <ListItemText
                primary={item.filename}
                primaryTypographyProps={{ variant: 'body2', noWrap: true, title: item.filename }}
                secondary={[
                  item.output_crs,
                  item.pixel_size_m !== null ? `${item.pixel_size_m.toFixed(1)} m/px` : null,
                  formatSize(item.size_bytes),
                ]
                  .filter(Boolean)
                  .join(' · ')}
                secondaryTypographyProps={{ variant: 'caption' }}
                sx={{ pr: (projectId !== null ? 7 : 0) + (allowDelete ? 4 : 0) }}
              />
            </ListItem>
          ))}
        </List>
      )}

      {/* ★ Delete confirms first — a library entry is the reusable master copy.
          Projects that adopted it keep their OWN copies, and the dialog says so. */}
      <Dialog
        open={pendingDelete !== null}
        onClose={() => {
          if (!deleting) setPendingDelete(null);
        }}
        maxWidth="xs"
        fullWidth
      >
        <DialogTitle>{t('Delete this DEM from the library?')}</DialogTitle>
        <DialogContent>
          <DialogContentText>
            <strong>{pendingDelete}</strong>{' '}
            {t(
              'will be removed from the DEM library folder on this computer. Projects and images already using it keep their own copies and are not affected — but processing it again later would start from the raw tile.',
            )}
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPendingDelete(null)} disabled={deleting}>
            {t('Keep it')}
          </Button>
          <Button
            color="error"
            variant="contained"
            onClick={() => void confirmDelete()}
            disabled={deleting}
            startIcon={deleting ? <CircularProgress size={14} color="inherit" /> : undefined}
          >
            {deleting ? 'Deleting…' : 'Delete'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

export default DemLibraryPanel;
