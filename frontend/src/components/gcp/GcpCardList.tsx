/**
 * `gcp/GcpCardList.tsx` (pure) — the GCP table's small-screen form. 50-frontend §2.22.
 *
 * Below `sm` the six-column table cannot breathe, so `GcpTable` delegates here: one
 * card per GCP carrying the same data (Point ID, coordinates, confidence, source,
 * accuracy) and the same adjust action. It is the SAME system of record, not a lesser
 * view (§8.8 item 1).
 *
 * ★ Each card subscribes narrowly to `selectionStore` (§3.5), so a selection lights up
 *   exactly one card without re-rendering the list.
 */

import Box from '@mui/material/Box';
import Card from '@mui/material/Card';
import CardActionArea from '@mui/material/CardActionArea';
import Chip from '@mui/material/Chip';
import IconButton from '@mui/material/IconButton';
import Typography from '@mui/material/Typography';
import EditLocationAltIcon from '@mui/icons-material/EditLocationAlt';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';

import type { ThemeMode } from '../../theme';
import { MANUAL_SOURCE_COLOR, gcpConfidenceBand } from '../../theme';
import type { CoordinateFormat } from '../../types/common';
import type { GcpTableRow as GcpTableRowModel } from '../../types/gcp';
import { formatAccuracy } from '../../lib/geo/format';
import { isSelectedSelector, useSelectionStore } from '../../store';
import type { SelectionMode } from '../../store';
import { CoordinateCell } from './CoordinateCell';

export interface GcpCardListProps {
  rows: GcpTableRowModel[];
  coordinateFormat: CoordinateFormat;
  themeMode: ThemeMode;
  onSelect: (id: string, mode: SelectionMode, linkedId: string | null) => void;
  onAdjust: (id: string) => void;
  onDelete: (id: string) => void;
}

interface CardProps {
  row: GcpTableRowModel;
  coordinateFormat: CoordinateFormat;
  themeMode: ThemeMode;
  onSelect: GcpCardListProps['onSelect'];
  onAdjust: GcpCardListProps['onAdjust'];
  onDelete: GcpCardListProps['onDelete'];
}

function GcpCard({
  row,
  coordinateFormat,
  themeMode,
  onSelect,
  onAdjust,
  onDelete,
}: CardProps): JSX.Element {
  const selected = useSelectionStore(isSelectedSelector(row.id));
  const band = gcpConfidenceBand(row);
  const linkedId = row.linked_annotation_id ?? null;
  const p = { lat: row.lat, lon: row.lon };

  return (
    <Card
      variant="outlined"
      sx={{ borderColor: selected ? 'primary.main' : undefined, borderWidth: selected ? 2 : 1 }}
    >
      <CardActionArea onClick={() => onSelect(row.id, 'replace', linkedId)} sx={{ p: 1 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 1, minWidth: 0 }}>
            <Typography variant="mono" sx={{ fontWeight: 700 }}>
              {row.code ?? row.id.slice(0, 8)}
            </Typography>
            <Typography
              variant="body2"
              sx={{
                fontSize: 13,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                color: row.landmark_name ? 'text.secondary' : 'text.disabled',
              }}
              title={row.landmark_name ?? undefined}
            >
              {row.landmark_name ?? '—'}
            </Typography>
          </Box>
          <Chip
            size="small"
            label={row.source === 'manual' ? 'Observed' : 'Inferred'}
            variant="outlined"
            sx={{
              height: 20,
              borderColor: row.source === 'manual' ? MANUAL_SOURCE_COLOR[themeMode] : undefined,
              color: row.source === 'manual' ? MANUAL_SOURCE_COLOR[themeMode] : undefined,
            }}
          />
        </Box>
        <Box sx={{ display: 'flex', gap: 2, mt: 0.5 }}>
          <CoordinateCell
            p={p}
            axis="lat"
            format={coordinateFormat}
            total_ce90_m={row.total_ce90_m}
            band={band}
          />
          <CoordinateCell
            p={p}
            axis="lon"
            format={coordinateFormat}
            total_ce90_m={row.total_ce90_m}
            band={band}
          />
        </Box>
        <Box sx={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', mt: 0.5 }}>
          <Typography variant="mono" sx={{ fontSize: 12, color: 'text.secondary' }}>
            {formatAccuracy(row.total_ce90_m)}
          </Typography>
        </Box>
      </CardActionArea>
      <Box sx={{ display: 'flex', justifyContent: 'flex-end', px: 1, pb: 0.5 }}>
        <IconButton
          size="small"
          aria-label={`Adjust ${row.code ?? row.id}`}
          onClick={() => onAdjust(row.id)}
        >
          <EditLocationAltIcon fontSize="small" />
        </IconButton>
        <IconButton
          size="small"
          aria-label={`Delete ${row.code ?? row.id}`}
          onClick={() => onDelete(row.id)}
          sx={{ '&:hover': { color: 'error.main' } }}
        >
          <DeleteOutlineIcon fontSize="small" />
        </IconButton>
      </Box>
    </Card>
  );
}

export function GcpCardList({
  rows,
  coordinateFormat,
  themeMode,
  onSelect,
  onAdjust,
  onDelete,
}: GcpCardListProps): JSX.Element {
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, p: 1 }}>
      {rows.map((row) => (
        <GcpCard
          key={row.id}
          row={row}
          coordinateFormat={coordinateFormat}
          themeMode={themeMode}
          onSelect={onSelect}
          onAdjust={onAdjust}
          onDelete={onDelete}
        />
      ))}
    </Box>
  );
}
