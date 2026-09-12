/**
 * `map/GcpMarkerLayer.tsx` — the committed GCPs on the map. 50-frontend §2.17.
 *
 * ★ Maps `GcpRead[]` → {@link GcpMarker}. It holds NO selection state itself; each
 *   marker subscribes narrowly (§3.5), so a click re-renders only the two markers
 *   whose selected-ness flipped, never the whole layer.
 *
 * ★ THE §5 INVARIANT, structurally: this layer renders only rows from React Query —
 *   i.e. COMMITTED GCPs. The open (uncommitted) correspondence is a different type
 *   from a different store and is rendered by `CorrespondenceLayer`. *"Uncommitted
 *   correspondences must never appear"* here because they are not representable here.
 */

import { GcpMarker } from './GcpMarker';
import type { ThemeMode } from '../../theme';
import type { GcpRead } from '../../types/gcp';
import { useSelectionStore, useWorkspaceStore } from '../../store';
import type { SelectionMode } from '../../store';

export interface GcpMarkerLayerProps {
  gcps: GcpRead[];
  themeMode: ThemeMode;
}

export function GcpMarkerLayer({ gcps, themeMode }: GcpMarkerLayerProps): JSX.Element {
  // One colour for every marker on the map; null keeps the confidence-band
  // colouring. A point's OWN colour (set from the inspector) beats it.
  const mapMarkColor = useWorkspaceStore((s) => s.mapMarkColor);
  const pointColors = useWorkspaceStore((s) => s.pointColors);
  const select = useSelectionStore((s) => s.select);
  const setHovered = useSelectionStore((s) => s.setHovered);

  const onSelect = (id: string, mode: SelectionMode, linkedId: string | null): void =>
    select({ kind: 'gcp', id, linkedId }, mode, 'map');

  const onHover = (ref: { id: string; linkedId: string | null } | null): void =>
    setHovered(ref ? { kind: 'gcp', id: ref.id, linkedId: ref.linkedId } : null);

  return (
    <>
      {gcps.map((gcp) => (
        <GcpMarker
          key={gcp.id}
          gcp={gcp}
          themeMode={themeMode}
          mapColor={pointColors[gcp.id] ?? mapMarkColor}
          onSelect={onSelect}
          onHover={onHover}
        />
      ))}
    </>
  );
}
