/**
 * `annotation/VersionHistoryDrawer.tsx` — 50-frontend.md §2.15 / SCOPE.md §3
 * ("version history for annotations and project revisions is BUILT").
 *
 * A right-anchored temporary `Drawer` listing the image's annotation versions
 * newest-first: version number, actor, timestamp, operation, and change summary.
 * Hovering a row previews that version on the canvas (`onPreview`); restoring is an
 * undoable revision restore (`onRestore`) and never destroys history — it appends
 * (§4.6, `types/annotation.ts`).
 *
 * ★ TYPE NOTES, resolved against IU-23's schemas (which override 50-frontend, §0):
 *   - An annotation VERSION id is a JSON **number** (`annotation_versions.id` is
 *     `BIGSERIAL`), not a `Uuid` — 50-frontend's `Uuid` props are void here.
 *   - RESTORE operates on a project **revision** (`revision_id: Uuid`), because a
 *     restore rewinds the whole annotation set, not one row. Rows without a
 *     `revision_id` (rare, legacy) are not restorable and are shown disabled.
 */

import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Divider from '@mui/material/Divider';
import Drawer from '@mui/material/Drawer';
import IconButton from '@mui/material/IconButton';
import List from '@mui/material/List';
import ListItem from '@mui/material/ListItem';
import ListItemButton from '@mui/material/ListItemButton';
import ListItemText from '@mui/material/ListItemText';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import CloseIcon from '@mui/icons-material/Close';
import RestoreIcon from '@mui/icons-material/Restore';

import type { Uuid } from '../../types/common';
import { useImageAnnotationVersions } from '../../api/hooks/useRevisions';
import { t } from '../../i18n';

export interface VersionHistoryDrawerProps {
  open: boolean;
  imageId: Uuid;
  /** The version currently previewed, or `null` for the live working draft. */
  currentVersionId: number | null;
  onClose: () => void;
  /** `null` returns to the working draft. */
  onPreview: (versionId: number | null) => void;
  /** Restore appends a new revision; a null `revisionId` means the row is not restorable. */
  onRestore: (revisionId: Uuid) => void;
}

function formatTs(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export function VersionHistoryDrawer({
  open,
  imageId,
  currentVersionId,
  onClose,
  onPreview,
  onRestore,
}: VersionHistoryDrawerProps): JSX.Element {
  const { data, isLoading } = useImageAnnotationVersions(open ? imageId : null);
  const versions = data?.items ?? [];

  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={onClose}
      PaperProps={{ sx: { width: 340, maxWidth: '90vw' } }}
    >
      <Stack direction="row" alignItems="center" sx={{ px: 2, py: 1.5 }}>
        <Typography variant="subtitle1" sx={{ flex: 1 }}>
          {t('Version history')}
        </Typography>
        <IconButton onClick={onClose} aria-label={t('Close version history')} size="small">
          <CloseIcon fontSize="small" />
        </IconButton>
      </Stack>
      <Divider />

      {isLoading ? (
        <Box sx={{ p: 2 }}>
          <Typography variant="body2" color="text.secondary">
            {t('Loading history…')}
          </Typography>
        </Box>
      ) : versions.length === 0 ? (
        <Box sx={{ p: 2 }}>
          <Typography variant="body2" color="text.secondary">
            {t('No saved versions yet. Edits are autosaved and will appear here.')}
          </Typography>
        </Box>
      ) : (
        <List
          dense
          onMouseLeave={() => onPreview(null)}
          subheader={
            currentVersionId !== null ? (
              <Box sx={{ px: 2, py: 1 }}>
                <Button size="small" onClick={() => onPreview(null)}>
                  {t('Return to working draft')}
                </Button>
              </Box>
            ) : undefined
          }
        >
          {versions.map((v) => (
            <ListItem
              key={v.id}
              disablePadding
              secondaryAction={
                <IconButton
                  edge="end"
                  aria-label={`Restore version ${v.version_no}`}
                  disabled={v.revision_id === null}
                  onClick={() => v.revision_id && onRestore(v.revision_id)}
                >
                  <RestoreIcon fontSize="small" />
                </IconButton>
              }
            >
              <ListItemButton
                selected={currentVersionId === v.id}
                onMouseEnter={() => onPreview(v.id)}
                onClick={() => onPreview(v.id)}
              >
                <ListItemText
                  primary={`v${v.version_no} · ${v.op}`}
                  secondary={
                    <>
                      {v.actor_id ?? 'unknown'} · {formatTs(v.created_at)}
                      {v.summary.fields_changed.length > 0 && (
                        <>
                          {' · '}
                          {v.summary.fields_changed.join(', ')}
                        </>
                      )}
                    </>
                  }
                />
              </ListItemButton>
            </ListItem>
          ))}
        </List>
      )}
    </Drawer>
  );
}
