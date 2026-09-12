/**
 * `lib/monitor/geojson.ts` — THE ONE PLACE `{lat, lon}` BECOMES `[lon, lat]`.
 *
 * ★ GeoJSON and MapLibre take positions as `[longitude, latitude]`; everything else
 *   in this app names its fields (`lat`, `lon`) precisely so the order can never be
 *   transposed by accident. The flip happens here, in one function with a unit
 *   test, and nowhere else in the monitor — a camera registered at 33.83 N, 35.54 E
 *   must land in Lebanon, not in the Indian Ocean.
 */

import type { CameraStatusState, RegisteredCamera } from '../../store/cameraRegistryStore';

/** A GeoJSON position from named fields. The flip. */
export function toLonLat(p: { lat: number; lon: number }): [number, number] {
  return [p.lon, p.lat];
}

export interface CameraFeatureProps {
  id: string;
  name: string;
  status: CameraStatusState;
  /** Ranked so a circle layer can pick a colour with a `match` expression. */
  heading_deg: number | null;
}

/** Every registered camera as a point feature, carrying its last-known status. */
export function camerasToFeatureCollection(
  cameras: readonly RegisteredCamera[],
  statusOf: (id: string) => CameraStatusState,
): GeoJSON.FeatureCollection<GeoJSON.Point, CameraFeatureProps> {
  return {
    type: 'FeatureCollection',
    features: cameras.map((c) => ({
      type: 'Feature',
      id: c.id,
      geometry: { type: 'Point', coordinates: toLonLat(c) },
      properties: {
        id: c.id,
        name: c.name,
        status: statusOf(c.id),
        heading_deg: c.heading_deg ?? null,
      },
    })),
  };
}

const EARTH_RADIUS_M = 6378137;

/**
 * A point `distanceM` from `origin` along `bearingDeg` — the great-circle formula.
 * Named fields in, named fields out; `toLonLat` does the flip at the edge.
 */
export function destinationPoint(
  origin: { lat: number; lon: number },
  bearingDeg: number,
  distanceM: number,
): { lat: number; lon: number } {
  const δ = distanceM / EARTH_RADIUS_M;
  const θ = (bearingDeg * Math.PI) / 180;
  const φ1 = (origin.lat * Math.PI) / 180;
  const λ1 = (origin.lon * Math.PI) / 180;
  const φ2 = Math.asin(Math.sin(φ1) * Math.cos(δ) + Math.cos(φ1) * Math.sin(δ) * Math.cos(θ));
  const λ2 =
    λ1 +
    Math.atan2(Math.sin(θ) * Math.sin(δ) * Math.cos(φ1), Math.cos(δ) - Math.sin(φ1) * Math.sin(φ2));
  return { lat: (φ2 * 180) / Math.PI, lon: (((λ2 * 180) / Math.PI + 540) % 360) - 180 };
}

/**
 * The field-of-view wedge a camera sweeps, as a polygon: apex at the camera,
 * `fovDeg` wide about `headingDeg`, reaching `radiusM` out.
 */
export function fovWedge(
  camera: { lat: number; lon: number },
  headingDeg: number,
  fovDeg: number,
  radiusM: number,
  steps = 12,
): GeoJSON.Polygon {
  const half = fovDeg / 2;
  const ring: [number, number][] = [toLonLat(camera)];
  for (let i = 0; i <= steps; i += 1) {
    const bearing = headingDeg - half + (fovDeg * i) / steps;
    ring.push(toLonLat(destinationPoint(camera, bearing, radiusM)));
  }
  ring.push(toLonLat(camera));
  return { type: 'Polygon', coordinates: [ring] };
}

/** Every camera that states a heading, as its wedge. */
export function wedgesToFeatureCollection(
  cameras: readonly RegisteredCamera[],
  radiusM = 400,
): GeoJSON.FeatureCollection<GeoJSON.Polygon, { id: string }> {
  return {
    type: 'FeatureCollection',
    features: cameras
      .filter((c) => typeof c.heading_deg === 'number')
      .map((c) => ({
        type: 'Feature',
        geometry: fovWedge(c, c.heading_deg as number, c.fov_deg ?? 60, radiusM),
        properties: { id: c.id },
      })),
  };
}
