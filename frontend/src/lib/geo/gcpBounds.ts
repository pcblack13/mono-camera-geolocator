/**
 * `lib/geo/gcpBounds.ts` — the box the map should open on when a frame has points.
 *
 * ★ OPEN ON THE WORK (owner ask 2026-09-10). A frame with control points opens
 *   the map on THOSE points — padded so the outermost ones are not glued to the
 *   pane's edge — not on a world view or on the photo's EXIF fix. One point is
 *   framed at the reveal zoom; none falls back to whatever else the panel knows.
 */

import type { BBox, LatLon } from '../../types/geo';

/** Fraction of the span added on every side; the floor keeps a tight cluster readable. */
const PAD = 0.2;
const MIN_HALF_SPAN_DEG = 0.0008; // ≈ 90 m

export function gcpBounds(points: readonly LatLon[]): BBox | null {
  if (points.length === 0) return null;
  let minLat = Infinity;
  let maxLat = -Infinity;
  let minLon = Infinity;
  let maxLon = -Infinity;
  for (const p of points) {
    if (!Number.isFinite(p.lat) || !Number.isFinite(p.lon)) continue;
    minLat = Math.min(minLat, p.lat);
    maxLat = Math.max(maxLat, p.lat);
    minLon = Math.min(minLon, p.lon);
    maxLon = Math.max(maxLon, p.lon);
  }
  if (!Number.isFinite(minLat)) return null;
  const halfLat = Math.max(((maxLat - minLat) / 2) * (1 + 2 * PAD), MIN_HALF_SPAN_DEG);
  const halfLon = Math.max(((maxLon - minLon) / 2) * (1 + 2 * PAD), MIN_HALF_SPAN_DEG);
  const cLat = (minLat + maxLat) / 2;
  const cLon = (minLon + maxLon) / 2;
  return {
    min_lat: Math.max(-90, cLat - halfLat),
    max_lat: Math.min(90, cLat + halfLat),
    min_lon: cLon - halfLon,
    max_lon: cLon + halfLon,
  };
}
