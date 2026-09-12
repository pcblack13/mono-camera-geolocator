/**
 * `components/gcp/` barrel — IU-27 (fe-map).
 *
 * The mandated GCP table (Point ID · Image X · Image Y · Latitude · Longitude ·
 * Confidence) + its cells and small-screen form. `GcpTable` is the container the dock
 * mounts; the rest are its parts.
 */

export { GcpTable } from './GcpTable';
export type { GcpTableProps } from './GcpTable';
export { GcpTableRow } from './GcpTableRow';
export type { GcpTableRowProps } from './GcpTableRow';
export { GcpCardList } from './GcpCardList';
export type { GcpCardListProps } from './GcpCardList';
export { ImportKmlDialog } from './ImportKmlDialog';
export type { ImportKmlDialogProps } from './ImportKmlDialog';
export { GcpTableToolbar } from './GcpTableToolbar';
export type { GcpTableToolbarProps } from './GcpTableToolbar';
export { CoordinateCell } from './CoordinateCell';
export type { CoordinateCellProps } from './CoordinateCell';

export { useGcpRows, toGcpTableRow } from './gcpRows';
export type { UseGcpRowsResult } from './gcpRows';
