/**
 * `gcp/GcpTableRow.tsx` — one row of the mandated GCP table. 50-frontend §2.22.
 *
 * ★ THE SIX MANDATED COLUMNS, IN ORDER: Point ID · Image X · Image Y · Latitude ·
 *   Longitude · Confidence — then Source, Accuracy, and a trailing action cell.
 *
 * ★ SCOPE.md §5 — SOURCE IS GLANCEABLE. The Source chip states whether the coordinate
 *   is an OBSERVED (manual) or INFERRED (automatic) one at a glance. Every row is
 *   `manual` in this build; the tool must never imply otherwise.
 *
 * ★ Selecting a row cross-highlights BOTH other panes via `selectionStore` (§3.5). Like
 *   the map markers, the row subscribes with a NARROW BOOLEAN selector so selecting one
 *   row does not re-render the whole table. The tree marks it "(pure)"; §3.5's narrow
 *   subscription is the correctness requirement and it wins.
 */

import { useEffect, useRef } from 'react';
import Box from '@mui/material/Box';
import IconButton from '@mui/material/IconButton';
import TableCell from '@mui/material/TableCell';
import TableRow from '@mui/material/TableRow';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import EditLocationAltIcon from '@mui/icons-material/EditLocationAlt';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import EditIcon from '@mui/icons-material/Edit';
import CloseIcon from '@mui/icons-material/Close';

import type { ThemeMode } from '../../theme';
import { MANUAL_SOURCE_COLOR, confidenceColor, gcpConfidenceBand } from '../../theme';
import type { CoordinateFormat } from '../../types/common';
import type { GcpTableRow as GcpTableRowModel } from '../../types/gcp';
import { formatAccuracy, toUtm } from '../../lib/geo/format';

/** UTM zone designation for the DD+UTM+Z Zone column, e.g. `37N`; `—` outside UTM's range. */
function utmZoneLabel(p: { lat: number; lon: number }): string {
  const u = toUtm(p);
  return u ? `${u.zone}${u.hemisphere}` : '—';
}
import {
  isHoveredSelector,
  isSelectedSelector,
  useSelectionStore,
  useWorkspaceStore,
} from '../../store';
import type { SelectionMode } from '../../store';
import { CoordinateCell } from './CoordinateCell';
import { t } from '../../i18n';

export interface GcpTableRowProps {
  row: GcpTableRowModel;
  coordinateFormat: CoordinateFormat;
  themeMode: ThemeMode;
  onSelect: (id: string, mode: SelectionMode, linkedId: string | null) => void;
  onHover: (ref: { id: string; linkedId: string | null } | null) => void;
  onAdjust: (id: string) => void;
  onDelete: (id: string) => void;
}

function modeFromEvent(e: {
  shiftKey: boolean;
  metaKey: boolean;
  ctrlKey: boolean;
}): SelectionMode {
  return e.shiftKey ? 'range' : e.metaKey || e.ctrlKey ? 'add' : 'replace';
}

export function GcpTableRow({
  row,
  coordinateFormat,
  themeMode,
  onSelect,
  onHover,
  onAdjust,
  onDelete,
}: GcpTableRowProps): JSX.Element {
  const selected = useSelectionStore(isSelectedSelector(row.id));
  const hovered = useSelectionStore(isHoveredSelector(row.id));
  const focusOrigin = useSelectionStore((s) => s.focusOrigin);

  // This point's own colour, and what it would be drawn in without one — so the
  // well opens on the real colour rather than an arbitrary starting point.
  const ownColor = useWorkspaceStore((st) => st.pointColors[row.id]);
  const mapMarkColor = useWorkspaceStore((st) => st.mapMarkColor);
  const setPointColor = useWorkspaceStore((st) => st.setPointColor);

  const band = gcpConfidenceBand(row);
  const effectiveColor = mapMarkColor ?? confidenceColor(band, themeMode);
  const linkedId = row.linked_annotation_id ?? null;
  const p = { lat: row.lat, lon: row.lon };

  // ★ Cross-pane REVEAL: when this row becomes selected from the photo or the map (not
  //   from a click in the table itself), scroll it into view so the surveyor is taken to
  //   the GCP they just clicked on a marker. Highlight alone is not enough if the row is
  //   scrolled out of the dock.
  const rowRef = useRef<HTMLTableRowElement>(null);
  useEffect(() => {
    if (selected && focusOrigin !== 'table' && rowRef.current) {
      rowRef.current.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }, [selected, focusOrigin]);

  return (
    <TableRow
      ref={rowRef}
      hover
      selected={selected}
      tabIndex={0}
      aria-selected={selected}
      onClick={(e) => onSelect(row.id, modeFromEvent(e), linkedId)}
      onMouseEnter={() => onHover({ id: row.id, linkedId })}
      onMouseLeave={() => onHover(null)}
      onKeyDown={(e) => {
        // ★ Keys pressed ON an inner button (Adjust, Delete) belong to that button:
        //   swallowing them here selected the row and cancelled the button's click.
        if (e.target !== e.currentTarget) return;
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onSelect(row.id, modeFromEvent(e), linkedId);
        } else if (e.key === 'a' || e.key === 'A') {
          e.preventDefault();
          onAdjust(row.id);
        } else if (e.key === 'Delete' || e.key === 'Backspace') {
          e.preventDefault();
          onDelete(row.id);
        }
      }}
      sx={{
        cursor: 'pointer',
        outline: hovered && !selected ? '2px solid' : undefined,
        outlineColor: 'primary.main',
        outlineOffset: '-2px',
      }}
    >
      {/* Point ID */}
      <TableCell>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
          {/* ★ EVERY point can be coloured, and this table is the only list that
              holds every one: a control point placed straight on the map has no
              landmark, so the annotation inspector never sees it. The well sits in
              the identity cell rather than a new column — the column set is
              mandated, and identity is what a colour marks. */}
          <Tooltip
            title={ownColor === undefined ? 'Give this point its own colour' : 'Custom colour'}
          >
            <Box
              component="input"
              type="color"
              value={ownColor ?? effectiveColor}
              onClick={(e: React.MouseEvent) => e.stopPropagation()}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                e.stopPropagation();
                setPointColor(row.id, e.target.value);
              }}
              aria-label={`Colour for point ${row.code ?? row.id.slice(0, 8)}`}
              sx={{
                'width': 16,
                'height': 16,
                'p': 0,
                'flexShrink': 0,
                'border': ownColor === undefined ? 1 : 2,
                'borderColor': ownColor === undefined ? 'divider' : 'text.primary',
                'borderRadius': '3px',
                'bgcolor': 'transparent',
                'cursor': 'pointer',
                '&::-webkit-color-swatch-wrapper': { p: 0 },
                '&::-webkit-color-swatch': { border: 'none', borderRadius: '2px' },
              }}
            />
          </Tooltip>
          {ownColor !== undefined && (
            <Tooltip title={t('Back to the default colour')}>
              <IconButton
                size="small"
                sx={{ p: 0.125 }}
                aria-label={t("Clear this point's colour")}
                onClick={(e) => {
                  e.stopPropagation();
                  setPointColor(row.id, null);
                }}
              >
                <CloseIcon sx={{ fontSize: 12 }} />
              </IconButton>
            </Tooltip>
          )}
          <Typography variant="mono" sx={{ fontSize: 13, fontWeight: 600 }}>
            {row.code ?? row.id.slice(0, 8)}
          </Typography>
          {row.manually_adjusted ? (
            <Tooltip title={t('Edited after placement')}>
              <EditIcon sx={{ fontSize: 13, color: MANUAL_SOURCE_COLOR[themeMode] }} />
            </Tooltip>
          ) : null}
          {row.is_stale ? (
            <Tooltip title="Stale — a linked landmark changed. Re-verify before use.">
              <WarningAmberIcon sx={{ fontSize: 13, color: 'warning.main' }} />
            </Tooltip>
          ) : null}
          {!row.pixel_accuracy_within_ceiling ? (
            <Tooltip
              title={`Pixel error ${row.residual_px?.toFixed(2) ?? '?'}px exceeds the ${row.pixel_accuracy_ceiling_px}px accuracy ceiling — re-check this point.`}
            >
              <ErrorOutlineIcon sx={{ fontSize: 13, color: 'error.main' }} />
            </Tooltip>
          ) : null}
        </Box>
      </TableCell>

      {/* Name — the linked landmark's free-text label; em-dash when unlinked/unnamed. */}
      <TableCell>
        <Typography
          variant="body2"
          sx={{
            fontSize: 13,
            maxWidth: 160,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            color: row.landmark_name ? 'text.primary' : 'text.disabled',
          }}
          title={row.landmark_name ?? undefined}
        >
          {row.landmark_name ?? '—'}
        </Typography>
      </TableCell>

      {/* Image X / Y — 1 decimal, never rounded for storage (§8.6). */}
      <TableCell align="right">
        <Typography variant="mono" sx={{ fontSize: 13 }}>
          {row.image_px.x.toFixed(1)}
        </Typography>
      </TableCell>
      <TableCell align="right">
        <Typography variant="mono" sx={{ fontSize: 13 }}>
          {row.image_px.y.toFixed(1)}
        </Typography>
      </TableCell>

      {/* Latitude / Longitude — precision policy applied per §8.7. */}
      <TableCell align="right">
        <CoordinateCell
          p={p}
          axis="lat"
          format={coordinateFormat}
          total_ce90_m={row.total_ce90_m}
          band={band}
        />
      </TableCell>
      <TableCell align="right">
        <CoordinateCell
          p={p}
          axis="lon"
          format={coordinateFormat}
          total_ce90_m={row.total_ce90_m}
          band={band}
        />
      </TableCell>

      {/* ★ DD+UTM+Z only: the UTM Zone, and Z (elevation in metres). */}
      {coordinateFormat === 'ddutmz' && (
        <>
          <TableCell>
            <Typography variant="mono" sx={{ fontSize: 13, whiteSpace: 'nowrap' }}>
              {utmZoneLabel(p)}
            </Typography>
          </TableCell>
          <TableCell align="right">
            <Typography variant="mono" sx={{ fontSize: 13 }} title={t('Elevation (Z)')}>
              {row.elevation_m != null ? row.elevation_m.toFixed(2) : '—'}
            </Typography>
          </TableCell>
        </>
      )}

      {/* Accuracy — the CE90 radius. */}
      <TableCell align="right">
        <Typography variant="mono" sx={{ fontSize: 13, whiteSpace: 'nowrap' }}>
          {formatAccuracy(row.total_ce90_m)}
        </Typography>
      </TableCell>

      {/* Action */}
      <TableCell align="center" padding="none">
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Tooltip title={t('Adjust this GCP (A)')}>
            <IconButton
              size="small"
              aria-label={`Adjust ${row.code ?? row.id}`}
              onClick={(e) => {
                e.stopPropagation();
                onAdjust(row.id);
              }}
            >
              <EditLocationAltIcon fontSize="small" />
            </IconButton>
          </Tooltip>
          <Tooltip title={t('Delete this GCP (Del)')}>
            <IconButton
              size="small"
              aria-label={`Delete ${row.code ?? row.id}`}
              onClick={(e) => {
                e.stopPropagation();
                onDelete(row.id);
              }}
              sx={{ '&:hover': { color: 'error.main' } }}
            >
              <DeleteOutlineIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </Box>
      </TableCell>
    </TableRow>
  );
}
