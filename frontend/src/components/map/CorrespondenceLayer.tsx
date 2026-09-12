/**
 * ★★ `map/CorrespondenceLayer.tsx` — THE LIVE LINKED MAP MARKER. SCOPE.md §5.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * ★ ADDED in the spirit of the tree (§2), like `correspondenceStore` itself: manual
 *   GCP mode is SCOPE.md's core interaction and the contract's map component list —
 *   written for an automatic engine — has no home for the open correspondence's map
 *   endpoint. Flagged in the IU-27 report.
 *
 * ★ SCOPE.md §5: *"Both panes show a live linked marker with a matching colour/ID
 *   while the correspondence is open"* and *"either endpoint can be dragged and
 *   re-committed"*. This is the MAP endpoint of that pair:
 *     - it reads the open draft ONLY through `openMarkers` (the sanctioned path);
 *     - it is styled distinctly (`is_committed: false`) so it can never be mistaken
 *       for a committed GCP — DASHED, in the active-correspondence accent, never the
 *       band colour;
 *     - it is DRAGGABLE, and a drop re-commits the coordinate via `setMapPoint`.
 *
 * ★ THE §5 INVARIANT: this marker is NOT a GCP and is not representable as one. It
 *   comes from `correspondenceStore`, which holds no `GcpRead`, so nothing here can
 *   leak into the GCP table or an export.
 * ─────────────────────────────────────────────────────────────────────────────
 */

import { useMemo } from 'react';
import { Marker } from 'react-leaflet';
import L from 'leaflet';

import { openMarkers, useCorrespondenceStore } from '../../store';

export interface CorrespondenceLayerProps {
  /** The active-correspondence accent — the SAME colour the photo pane uses for the
   *  linked marker (both panes read `theme.palette.primary.main`; see IU-27 report). */
  activeColor: string;
  outline: string;
}

const SIZE = 24;

function draftIcon(activeColor: string, outline: string, pulsing: boolean): L.DivIcon {
  const r = SIZE / 2 - 3;
  const pulse = pulsing
    ? `<circle cx="${SIZE / 2}" cy="${SIZE / 2}" r="${r}" fill="${activeColor}" opacity="0.25">
         <animate attributeName="r" values="${r};${r + 6};${r}" dur="1.4s" repeatCount="indefinite"/>
         <animate attributeName="opacity" values="0.35;0;0.35" dur="1.4s" repeatCount="indefinite"/>
       </circle>`
    : '';
  // Dashed hollow ring + centre dot = "a draft you can still move", never a solid
  // committed marker. Crosshair ticks aid precise re-placement.
  const svg = `
    <svg width="${SIZE}" height="${SIZE}" viewBox="0 0 ${SIZE} ${SIZE}">
      ${pulse}
      <circle cx="${SIZE / 2}" cy="${SIZE / 2}" r="${r}" fill="none"
              stroke="${activeColor}" stroke-width="2.5" stroke-dasharray="3 3" />
      <circle cx="${SIZE / 2}" cy="${SIZE / 2}" r="${r}" fill="none"
              stroke="${outline}" stroke-width="1" stroke-dasharray="3 3" opacity="0.6" />
      <circle cx="${SIZE / 2}" cy="${SIZE / 2}" r="2" fill="${activeColor}" stroke="${outline}" stroke-width="0.75" />
    </svg>`;
  return L.divIcon({
    className: 'le-correspondence-marker',
    html: svg,
    iconSize: [SIZE, SIZE],
    iconAnchor: [SIZE / 2, SIZE / 2],
  });
}

export function CorrespondenceLayer({
  activeColor,
  outline,
}: CorrespondenceLayerProps): JSX.Element | null {
  const markers = useCorrespondenceStore(openMarkers);
  const setMapPoint = useCorrespondenceStore((s) => s.setMapPoint);

  const pulsing = markers?.awaiting === 'confidence' ? false : true;
  const icon = useMemo(
    () => draftIcon(activeColor, outline, pulsing),
    [activeColor, outline, pulsing],
  );

  // Nothing open, or the map endpoint not yet placed → no marker (the crosshair guides
  // the first click; see MapPanel). `openMarkers` returns null when idle.
  if (markers === null || markers.lat_lon === null) return null;

  return (
    <Marker
      position={[markers.lat_lon.lat, markers.lat_lon.lon]}
      icon={icon}
      draggable
      zIndexOffset={2000}
      keyboard={false}
      alt="Open correspondence — drag to refine, then commit"
      eventHandlers={{
        dragend: (e) => {
          const ll = (e.target as L.Marker).getLatLng();
          setMapPoint({ lat: ll.lat, lon: ll.lng });
        },
      }}
    />
  );
}
