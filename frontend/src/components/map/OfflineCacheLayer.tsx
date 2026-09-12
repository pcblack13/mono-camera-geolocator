/**
 * `map/OfflineCacheLayer.tsx` — the polygon the surveyor draws to mark an area for offline
 * caching. Mount inside ANY `<MapContainer>` (the workspace `SatelliteMap` and the dashboard
 * `GcpOverviewMap` both use it).
 *
 * ★ SELF-CONTAINED VERTEX CAPTURE: while `offlineCacheStore.drawing`, a map click appends a
 *   vertex here — so the layer works in a bare map with no click plumbing of its own. In the
 *   workspace, `MapPanel.onMapClick` simply defers (returns early) while drawing, so a click
 *   is never handled twice. The polygon is closed with the panel's "Done" button, not a map
 *   double-click (Leaflet emits two `click`s before a `dblclick`, which would drop strays);
 *   we only suppress dblclick-ZOOM while drawing so a fast double-tap does not zoom the map.
 */

import { useEffect, type JSX } from 'react';
import { CircleMarker, Polygon, Polyline, useMapEvents } from 'react-leaflet';
import type { LatLngExpression } from 'leaflet';

import { useOfflineCacheStore } from '../../store';
import { ON_MEDIA } from '../../theme/paint';

export interface OfflineCacheLayerProps {
  /** Outline colour — the map's active accent. */
  color: string;
}

export function OfflineCacheLayer({ color }: OfflineCacheLayerProps): JSX.Element | null {
  const drawing = useOfflineCacheStore((s) => s.drawing);
  const points = useOfflineCacheStore((s) => s.points);

  // Read state via getState in the handler to avoid a stale closure across re-binds.
  const map = useMapEvents({
    click: (e) => {
      const st = useOfflineCacheStore.getState();
      if (st.drawing) st.addPoint({ lat: e.latlng.lat, lon: e.latlng.lng });
    },
  });

  useEffect(() => {
    if (drawing) map.doubleClickZoom.disable();
    else map.doubleClickZoom.enable();
    return () => {
      map.doubleClickZoom.enable();
    };
  }, [drawing, map]);

  if (points.length === 0) return null;

  const latlngs: LatLngExpression[] = points.map((p) => [p.lat, p.lon]);

  return (
    <>
      {points.length >= 3 ? (
        <Polygon
          positions={latlngs}
          pathOptions={{
            color,
            weight: 2,
            fillOpacity: 0.12,
            dashArray: drawing ? '5 5' : undefined,
          }}
        />
      ) : (
        <Polyline positions={latlngs} pathOptions={{ color, weight: 2, dashArray: '5 5' }} />
      )}
      {points.map((p, i) => (
        <CircleMarker
          key={`${p.lat},${p.lon},${i}`}
          center={[p.lat, p.lon]}
          radius={4}
          pathOptions={{ color, weight: 2, fillColor: ON_MEDIA, fillOpacity: 1 }}
        />
      ))}
    </>
  );
}

export default OfflineCacheLayer;
