/**
 * `map/FootprintLayer.tsx` (pure) — 50-frontend §2.16 component list.
 *
 * Draws the photo's estimated ground footprint as a polygon over the imagery.
 *
 * ★ SCOPE.md §1: the footprint is a product of **camera-pose estimation, which is
 *   DEFERRED**. In this build no `CameraPoseRead` exists, so `footprint` is `null` and
 *   this renders nothing. The component is kept so re-enabling the pose estimator
 *   costs the map pane no change (SCOPE.md §7) — it already has a home for the answer.
 *
 * **Pure.** Coordinates in, a `Polygon` out.
 */

import { Polygon } from 'react-leaflet';

import type { LatLon } from '../../types/geo';

export interface FootprintLayerProps {
  /** EPSG:4326 ring, or `null` when no camera pose is available (always, this build). */
  footprint: LatLon[] | null;
  visible: boolean;
  color: string;
}

export function FootprintLayer({
  footprint,
  visible,
  color,
}: FootprintLayerProps): JSX.Element | null {
  if (!visible || footprint === null || footprint.length < 3) return null;
  return (
    <Polygon
      positions={footprint.map((p) => [p.lat, p.lon] as [number, number])}
      pathOptions={{
        color,
        weight: 2,
        opacity: 0.8,
        fillOpacity: 0.08,
        dashArray: '6 4',
        interactive: false,
      }}
    />
  );
}
