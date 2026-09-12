/**
 * `gcp/GcpTable.tsx` — THE MANDATED GCP TABLE. 50-frontend §2.22, §8.8 item 1.
 *
 * ★ The mandated columns — Point ID · Image X · Image Y · Latitude · Longitude ·
 *   Confidence — in that order, then Source · Accuracy · an action cell. It is also the
 *   ACCESSIBLE representation of the canvas (§8.8): everything on the image and the map
 *   is here, in a real, navigable, semantic HTML table.
 *
 * ★ DEFAULT SORT: **confidence ascending** — the points needing attention come first;
 *   burying them below the good ones is a safety failure (§2.22).
 *
 * ★ Selecting a row cross-highlights both other panes (`selectionStore`, origin
 *   `'table'`, so the map reveals it; §3.5). Shift-click selects the range in the
 *   CURRENT sort order — the table is the only thing that knows that order, so it
 *   resolves `'range'` itself via `selectMany`.
 *
 * ★ THE §5 INVARIANT: this reads only committed GCPs (`useGcpRows` → React Query, L7).
 *   An OPEN correspondence is never here — the empty state points the surveyor at how
 *   to create one.
 */

import { useCallback, useMemo, useState } from 'react';
import Box from '@mui/material/Box';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import TableSortLabel from '@mui/material/TableSortLabel';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import Dialog from '@mui/material/Dialog';
import DialogTitle from '@mui/material/DialogTitle';
import DialogContent from '@mui/material/DialogContent';
import DialogContentText from '@mui/material/DialogContentText';
import DialogActions from '@mui/material/DialogActions';
import { useTheme } from '@mui/material/styles';
import useMediaQuery from '@mui/material/useMediaQuery';

import { useColorMode } from '../../theme';
import type { Uuid } from '../../types/common';
import type { GcpTableRow as GcpTableRowModel } from '../../types/gcp';
import { useCorrespondenceStore, useSelectionStore, useWorkspaceStore } from '../../store';
import type { SelectionMode, SelectionRef } from '../../store';
import { GcpCardList } from './GcpCardList';
import { GcpTableRow } from './GcpTableRow';
import { GcpTableToolbar } from './GcpTableToolbar';
import { useGcpRows } from './gcpRows';
import { useDeleteGcp } from '../../api/hooks/useGcps';
import { useNotify } from '../common/Notifications';
import { t } from '../../i18n';
import { useShallow } from 'zustand/react/shallow';

export interface GcpTableProps {
  imageId: Uuid;
  /** Forwarded to the toolbar for the project-scoped KML import. */
  projectId: Uuid;
  /** DEFERRED — no match result exists in this build (SCOPE.md §1). Kept for the seam. */
  matchResultId: Uuid | null;
}

type SortKey = 'code' | 'name' | 'image_x' | 'image_y' | 'lat' | 'lon' | 'accuracy';
type SortDir = 'asc' | 'desc';

function sortValue(row: GcpTableRowModel, key: SortKey): number | string {
  switch (key) {
    case 'code':
      return row.code ?? '~'; // nulls sort last
    case 'name':
      return row.landmark_name ?? '~'; // unnamed sort last
    case 'image_x':
      return row.image_px.x;
    case 'image_y':
      return row.image_px.y;
    case 'lat':
      return row.lat;
    case 'lon':
      return row.lon;
    case 'accuracy':
      return row.total_ce90_m;
  }
}

export function GcpTable({
  imageId,
  projectId,
  matchResultId: _matchResultId,
}: GcpTableProps): JSX.Element {
  const theme = useTheme();
  const { mode: themeMode } = useColorMode();
  const isSmall = useMediaQuery(theme.breakpoints.down('sm'));

  const { rows, total, isLoading, isError, isEmpty } = useGcpRows(imageId);

  const coordinateFormat = useWorkspaceStore((s) => s.coordinateFormat);
  const setCoordinateFormat = useWorkspaceStore((s) => s.setCoordinateFormat);

  const select = useSelectionStore((s) => s.select);
  const selectMany = useSelectionStore((s) => s.selectMany);
  const setHovered = useSelectionStore((s) => s.setHovered);
  const reopen = useCorrespondenceStore((s) => s.reopen);

  const [sortKey, setSortKey] = useState<SortKey>('code');
  const [sortDir, setSortDir] = useState<SortDir>('asc');

  const sortedRows = useMemo(() => {
    const copy = [...rows];
    copy.sort((a, b) => {
      const va = sortValue(a, sortKey);
      const vb = sortValue(b, sortKey);
      let cmp: number;
      if (typeof va === 'string' && typeof vb === 'string') cmp = va.localeCompare(vb);
      else cmp = (va as number) - (vb as number);
      return sortDir === 'asc' ? cmp : -cmp;
    });
    return copy;
  }, [rows, sortKey, sortDir]);

  const toggleSort = (key: SortKey): void => {
    if (key === sortKey) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else {
      setSortKey(key);
      setSortDir('asc');
    }
  };

  const onSelect = useCallback(
    (id: string, mode: SelectionMode, linkedId: string | null) => {
      if (mode === 'range') {
        // The table owns the order, so it resolves the range and calls selectMany.
        const anchorId = useSelectionStore.getState().anchorId;
        // `r.id` is a branded `Uuid`; widen to `string[]` so the `string` args from
        // the shared `onSelect` signature index cleanly (Uuid is assignable to string).
        const ids: string[] = sortedRows.map((r) => r.id);
        const from = anchorId ? ids.indexOf(anchorId) : -1;
        const to = ids.indexOf(id);
        if (from !== -1 && to !== -1) {
          const [lo, hi] = from <= to ? [from, to] : [to, from];
          const refs: SelectionRef[] = sortedRows.slice(lo, hi + 1).map((r) => ({
            kind: 'gcp',
            id: r.id,
            linkedId: r.linked_annotation_id,
          }));
          selectMany(refs, 'table');
          return;
        }
      }
      select({ kind: 'gcp', id, linkedId }, mode, 'table');
    },
    [sortedRows, select, selectMany],
  );

  const onHover = useCallback(
    (ref: { id: string; linkedId: string | null } | null) =>
      setHovered(ref ? { kind: 'gcp', id: ref.id, linkedId: ref.linkedId } : null),
    [setHovered],
  );

  const onAdjust = useCallback(
    (id: string) => {
      const row = rows.find((r) => r.id === id);
      if (!row) return;
      // ★ SCOPE.md §5 re-open: the map marker becomes draggable and re-committable.
      //   `landmark_client_id` takes the linked annotation id — for a hydrated
      //   annotation the client id equals the server id (annotationStore).
      reopen({
        image_id: imageId,
        gcp_id: id as Uuid,
        image_px: row.image_px,
        lat_lon: { lat: row.lat, lon: row.lon },
        declared_confidence: row.declared_confidence,
        landmark_client_id: row.linked_annotation_id,
        note: null,
        // Carry the current name so the edit panel pre-fills it (only shown for a bare GCP).
        gcp_name: row.linked_annotation_id === null ? row.landmark_name : null,
      });
      // Highlight it (origin 'table' so the map reveals it).
      select({ kind: 'gcp', id, linkedId: row.linked_annotation_id }, 'replace', 'table');
    },
    [rows, imageId, reopen, select],
  );

  // ── delete — a hard, irreversible remove, so it goes through a confirm dialog ──
  const deleteGcp = useDeleteGcp(imageId);
  const notify = useNotify();
  const [pendingDelete, setPendingDelete] = useState<{ id: Uuid; label: string } | null>(null);

  const onDelete = useCallback(
    (id: string) => {
      const row = rows.find((r) => r.id === id);
      setPendingDelete({
        id: id as Uuid,
        label: row?.code ?? row?.landmark_name ?? id.slice(0, 8),
      });
    },
    [rows],
  );

  const confirmDelete = useCallback(() => {
    if (!pendingDelete) return;
    const { id, label } = pendingDelete;
    deleteGcp.mutate(id, {
      onSuccess: () => notify(`Deleted GCP ${label}.`, { severity: 'success' }),
      onError: () => notify('Could not delete the GCP.', { severity: 'error' }),
      onSettled: () => setPendingDelete(null),
    });
  }, [pendingDelete, deleteGcp, notify]);

  // ── the bulk bar (Phase 4 leftover, delivered): appears on multi-select ─────
  //   Shift/Ctrl-click already builds the selection; this is the bar that makes a
  //   multi-selection DO something. Deletions run sequentially — the server has no
  //   bulk endpoint, and one honest failure must stop the run, not vanish into a
  //   fire-and-forget loop.
  const selectedGcpIds = useSelectionStore(
    useShallow((st) => st.selected.filter((r) => r.kind === 'gcp').map((r) => r.id)),
  );
  const clearSelection = useSelectionStore((st) => st.clear);
  const [bulkConfirm, setBulkConfirm] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);

  const confirmBulkDelete = useCallback(() => {
    void (async () => {
      setBulkBusy(true);
      let done = 0;
      try {
        for (const id of selectedGcpIds) {
          // eslint-disable-next-line no-await-in-loop -- sequential on purpose: see note above
          await deleteGcp.mutateAsync(id as Uuid);
          done += 1;
        }
        notify(t('Deleted {n} ground control points.').replace('{n}', String(done)), {
          severity: 'success',
        });
        clearSelection();
      } catch {
        notify(
          t('Stopped after deleting {n} — the next delete failed.').replace('{n}', String(done)),
          { severity: 'error' },
        );
      } finally {
        setBulkBusy(false);
        setBulkConfirm(false);
      }
    })();
  }, [selectedGcpIds, deleteGcp, notify, clearSelection]);

  const latLabel = coordinateFormat === 'utm' ? 'Northing' : 'Latitude';
  const lonLabel = coordinateFormat === 'utm' ? 'Easting' : 'Longitude';
  // ★ DD+UTM+Z adds a UTM Zone column and a Z (elevation) column. Source column removed.
  const showZoneZ = coordinateFormat === 'ddutmz';

  const columns: { key: SortKey | null; label: string; align?: 'right' }[] = [
    { key: 'code', label: 'Point ID' },
    { key: 'name', label: 'Name' },
    { key: 'image_x', label: 'Image X', align: 'right' },
    { key: 'image_y', label: 'Image Y', align: 'right' },
    { key: 'lat', label: latLabel, align: 'right' },
    { key: 'lon', label: lonLabel, align: 'right' },
    ...(showZoneZ
      ? ([
          { key: null, label: 'Zone' },
          { key: null, label: 'Z (m)', align: 'right' },
        ] as { key: SortKey | null; label: string; align?: 'right' }[])
      : []),
    { key: 'accuracy', label: 'Accuracy', align: 'right' },
    { key: null, label: '' },
  ];

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <GcpTableToolbar
        projectId={projectId}
        imageId={imageId}
        total={total}
        coordinateFormat={coordinateFormat}
        onCoordinateFormatChange={setCoordinateFormat}
      />

      {isLoading ? (
        <Box sx={{ p: 2 }}>
          <Typography color="text.secondary">{t('Loading ground control points…')}</Typography>
        </Box>
      ) : isError ? (
        <Box sx={{ p: 2 }}>
          <Typography color="error">{t('Could not load ground control points.')}</Typography>
        </Box>
      ) : isEmpty ? (
        <Box sx={{ p: 3, textAlign: 'center' }}>
          <Typography color="text.secondary">
            {t(
              'No ground control points yet. Mark a landmark in the photo, then click the matching spot on the map to place one.',
            )}
          </Typography>
        </Box>
      ) : isSmall ? (
        <Box sx={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
          <GcpCardList
            rows={sortedRows}
            coordinateFormat={coordinateFormat}
            themeMode={themeMode}
            onSelect={onSelect}
            onAdjust={onAdjust}
            onDelete={onDelete}
          />
        </Box>
      ) : (
        <TableContainer sx={{ flex: 1, minHeight: 0 }}>
          <Table stickyHeader size="small" aria-label={t('Ground control points')}>
            <TableHead>
              <TableRow>
                {columns.map((c, i) => (
                  <TableCell
                    key={c.label || `col-${i}`}
                    align={c.align}
                    sortDirection={c.key === sortKey ? sortDir : false}
                  >
                    {c.key ? (
                      <TableSortLabel
                        active={c.key === sortKey}
                        direction={c.key === sortKey ? sortDir : 'asc'}
                        onClick={() => toggleSort(c.key as SortKey)}
                      >
                        {c.label}
                      </TableSortLabel>
                    ) : (
                      c.label
                    )}
                  </TableCell>
                ))}
              </TableRow>
            </TableHead>
            <TableBody>
              {sortedRows.map((row) => (
                <GcpTableRow
                  key={row.id}
                  row={row}
                  coordinateFormat={coordinateFormat}
                  themeMode={themeMode}
                  onSelect={onSelect}
                  onHover={onHover}
                  onAdjust={onAdjust}
                  onDelete={onDelete}
                />
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <Dialog
        open={pendingDelete !== null}
        onClose={() => setPendingDelete(null)}
        maxWidth="xs"
        fullWidth
      >
        <DialogTitle>{t('Delete this ground control point?')}</DialogTitle>
        <DialogContent>
          <DialogContentText>
            GCP <strong>{pendingDelete?.label}</strong>{' '}
            {t(
              'will be permanently removed. This cannot be undone. If it was placed from a landmark, that landmark stays in the photo.',
            )}
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => setPendingDelete(null)}
            color="inherit"
            disabled={deleteGcp.isPending}
          >
            {t('Cancel')}
          </Button>
          <Button
            onClick={confirmDelete}
            color="error"
            variant="contained"
            disabled={deleteGcp.isPending}
          >
            {deleteGcp.isPending ? 'Deleting…' : 'Delete'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* ── the bulk action bar: slides up when two or more points are selected.
          One bar, one count, two actions — a multi-selection that can DO nothing
          is a trap the shift-click taught the user to walk into. */}
      {selectedGcpIds.length >= 2 && (
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            gap: 1,
            px: 1.5,
            py: 0.75,
            borderTop: '1px solid var(--hairline-strong)',
            bgcolor: 'var(--bg-inset)',
          }}
        >
          <Typography className="le-mono" sx={{ fontSize: 11.5, flex: 1 }}>
            {t('{n} selected').replace('{n}', String(selectedGcpIds.length))}
          </Typography>
          <Button size="small" onClick={clearSelection} disabled={bulkBusy}>
            {t('Clear')}
          </Button>
          <Button
            size="small"
            color="error"
            variant="outlined"
            onClick={() => setBulkConfirm(true)}
            disabled={bulkBusy}
          >
            {t('Delete selected')}
          </Button>
        </Box>
      )}

      <Dialog open={bulkConfirm} onClose={() => !bulkBusy && setBulkConfirm(false)}>
        <DialogTitle>
          {t('Delete {n} ground control points?').replace('{n}', String(selectedGcpIds.length))}
        </DialogTitle>
        <DialogContent>
          <DialogContentText>
            {t(
              'They will be permanently removed. This cannot be undone. Landmarks placed from the photo stay in the photo.',
            )}
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setBulkConfirm(false)} color="inherit" disabled={bulkBusy}>
            {t('Cancel')}
          </Button>
          <Button onClick={confirmBulkDelete} color="error" variant="contained" disabled={bulkBusy}>
            {bulkBusy ? t('Deleting…') : t('Delete selected')}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
