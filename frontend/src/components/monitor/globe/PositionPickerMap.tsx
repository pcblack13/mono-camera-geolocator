/**
 * `monitor/globe/PositionPickerMap.tsx` — click the map, get the camera's spot.
 *
 * ★ WHY IT EXISTS. The add-camera form asked for latitude and longitude as bare
 *   numbers — a wall for anyone who doesn't carry coordinates in their head. This
 *   little map turns the question around: point at where the camera stands, and
 *   the numbers write themselves.
 *
 * ★ LAZY BY CONTRACT. The globe page is MapLibre; this picker is Leaflet. It is
 *   loaded through `React.lazy` ONLY when the operator opens the picker, so the
 *   dialog itself ships no second map engine (the same budget rule every lazy
 *   note in `router.tsx` states).
 *
 * ★ Tiles come from the backend proxy (`proxyTileUrl`) — keys stay server-side —
 *   and the whole surface sits in an `LtrIsland`: Leaflet computes left-to-right
 *   geometry, so the Arabic mirror stops at its fence.
 */

import { useEffect, type JSX } from 'react';
import { CircleMarker, MapContainer, TileLayer, useMap, useMapEvents } from 'react-leaflet';

import 'leaflet/dist/leaflet.css';

import { API_BASE_URL } from '../../../api/client';
import { LtrIsland } from '../../common/LtrIsland';
import { proxyTileUrl } from '../../map/tileMath';
import { GLOBE } from '../../../theme/paint';
import type { LatLon } from '../../../types/geo';

export interface PositionPickerMapProps {
  /** The currently entered position, when the fields hold a valid one. */
  value: LatLon | null;
  /** Where to start looking when nothing is entered yet (e.g. the fleet's midpoint). */
  fallbackCenter: LatLon;
  provider: string;
  onPick: (p: LatLon) => void;
}

/**
 * Keeps Leaflet's size honest when its CONTAINER changes — and wakes a map that
 * was born hidden.
 *
 * ★ THE SETUP TABLE MOUNTS THIS MAP INSIDE A HIDDEN PANEL (2026-09-10). Leaflet
 *   measures its box once, at creation; created under `display: none` it
 *   measures 0×0, and when the row is opened it paints a stub of tiles in one
 *   corner with the pin nowhere — the "crashed map" the owner saw. Leaflet
 *   only re-measures on a window resize, so a `ResizeObserver` on the container
 *   (and its parent — a 100%-sized box in a grid cell can keep its own size
 *   while the cell changes) calls `invalidateSize()` whenever the box changes.
 *   The FIRST time the box has a real size the view is set again as well:
 *   a map that measured 0×0 at creation has no usable pixel origin, so
 *   `invalidateSize` alone leaves it looking at the wrong place.
 */
function FitToContainer({ center, zoom }: { center: LatLon; zoom: number }): null {
  const map = useMap();
  useEffect(() => {
    const el = map.getContainer();
    let sized = el.clientWidth > 0 && el.clientHeight > 0;
    const resize = (): void => {
      map.invalidateSize({ animate: false });
      if (!sized && el.clientWidth > 0 && el.clientHeight > 0) {
        sized = true;
        map.setView([center.lat, center.lon], zoom, { animate: false });
      }
    };
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    if (el.parentElement) ro.observe(el.parentElement);
    const raf = requestAnimationFrame(resize);
    const timer = window.setTimeout(resize, 300);
    return () => {
      ro.disconnect();
      cancelAnimationFrame(raf);
      window.clearTimeout(timer);
    };
    // ★ The centre/zoom only matter for the one-off wake-up; a later pick moves
    //   the pin, not the view, so the watcher is not re-armed per pick.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- armed once per map
  }, [map]);
  return null;
}

function ClickToPick({ onPick }: { onPick: (p: LatLon) => void }): null {
  useMapEvents({
    click: (e) => onPick({ lat: e.latlng.lat, lon: e.latlng.lng }),
  });
  return null;
}

export function PositionPickerMap(p: PositionPickerMapProps): JSX.Element {
  const center = p.value ?? p.fallbackCenter;
  const zoom = p.value !== null ? 15 : 5;
  return (
    <LtrIsland>
      <MapContainer
        center={[center.lat, center.lon]}
        zoom={zoom}
        style={{ height: 240, width: '100%', borderRadius: 8, cursor: 'crosshair' }}
        attributionControl={false}
      >
        <TileLayer url={proxyTileUrl(API_BASE_URL, p.provider, 'satellite')} maxZoom={19} />
        <FitToContainer center={center} zoom={zoom} />
        <ClickToPick onPick={p.onPick} />
        {p.value !== null && (
          <CircleMarker
            center={[p.value.lat, p.value.lon]}
            radius={8}
            // ★ The globe's "live" cyan — the pin means the same thing everywhere.
            pathOptions={{ color: GLOBE.live, weight: 2, fillColor: GLOBE.live, fillOpacity: 0.4 }}
          />
        )}
      </MapContainer>
    </LtrIsland>
  );
}

export default PositionPickerMap;
