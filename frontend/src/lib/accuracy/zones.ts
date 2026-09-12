/**
 * `lib/accuracy/zones.ts` — the nine range zones as polygons on the photograph.
 *
 * Pure geometry, so it can be pinned by a test without a canvas. The server traces
 * the iso-range contours (that needs the terrain); this turns them into the fills,
 * labels and colours the photo pane draws, in ORIGINAL photo pixels.
 *
 * ★ A ZONE IS BOUNDED BY TWO CONTOURS, NOT TWO ROWS. Its top is the far edge of its
 *   band, its bottom the far edge of the band before it (the frame's bottom for the
 *   nearest band). Both bend with the terrain, so the polygon is sampled along the
 *   column rather than drawn as a box.
 *
 * ★ COLOUR IS NORMALISED ACROSS THE ZONES THAT HAVE DATA — the pale end is the best
 *   zone and the deep end the worst — because the overlay exists to be compared
 *   zone against zone. The absolute level carries the terrain floor and the basemap's
 *   own offset; the differences are what say where the geolocation is weak.
 */

import type { AccuracyZoneCell, AccuracyZones } from '../../api/accuracy';
import { HEAT_STOPS } from '../../theme/dataColors';

export const ZONE_COLUMNS = ['L', 'M', 'R'] as const;

/** How many points sample each contour across a column — enough to follow a ridge. */
const SAMPLES_PER_COLUMN = 26;

export interface ZonePolygon {
  key: string;
  band: number;
  column: (typeof ZONE_COLUMNS)[number];
  /** Flat `[x0, y0, x1, y1, …]` in original photo pixels, ready for a Konva line. */
  points: number[];
  /** Where the label sits — mid-column, halfway between the two contours. */
  label: { u: number; v: number };
  /** The zone's height at mid-column, original px — how much room a label has. */
  heightPx: number;
  tiles: number;
  medianErrorM: number | null;
  /** 0 = the best zone, 1 = the worst. Null when the zone has no number. */
  t: number | null;
  /** "L1", "M2" … — the zone's short name. */
  name: string;
  /** "0–357 m" — the band's ground range. */
  rangeLabel: string;
}

/** Row of a contour at column `u`, by linear interpolation between its points. */
export function curveV(curve: number[][], u: number): number {
  const pts = [...curve].sort((a, b) => a[0] - b[0]);
  if (pts.length === 0) return Number.NaN;
  if (u <= pts[0][0]) return pts[0][1];
  const last = pts[pts.length - 1];
  if (u >= last[0]) return last[1];
  for (let i = 1; i < pts.length; i += 1) {
    const [u0, v0] = pts[i - 1];
    const [u1, v1] = pts[i];
    if (u <= u1) {
      const f = u1 === u0 ? 0 : (u - u0) / (u1 - u0);
      return v0 + (v1 - v0) * f;
    }
  }
  return last[1];
}

/** A zone's position on the shared scale, or null when it has no number. */
export function zoneT(cell: AccuracyZoneCell, range: [number, number] | null): number | null {
  if (cell.median_error_m === null || range === null) return null;
  const [lo, hi] = range;
  if (hi <= lo) return 0;
  return Math.max(0, Math.min(1, (cell.median_error_m - lo) / (hi - lo)));
}

function parseHex(hex: string): [number, number, number] {
  return [
    parseInt(hex.slice(1, 3), 16),
    parseInt(hex.slice(3, 5), 16),
    parseInt(hex.slice(5, 7), 16),
  ];
}

/** A theme hex with an alpha, as an `rgba()` string Konva can fill with. */
export function withAlpha(hex: string, alpha: number): string {
  const [r, g, b] = parseHex(hex);
  return `rgba(${r}, ${g}, ${b}, ${Math.max(0, Math.min(1, alpha)).toFixed(3)})`;
}

/** The heat ramp at `t` (0..1) with the given alpha (0..1), as an `rgba()` string. */
export function zoneFill(t: number, alpha: number): string {
  const idx = Math.min(Math.max(t, 0) * (HEAT_STOPS.length - 1), HEAT_STOPS.length - 1.001);
  const lo = Math.floor(idx);
  const fr = idx - lo;
  const a = parseHex(HEAT_STOPS[lo]);
  const b = parseHex(HEAT_STOPS[lo + 1]);
  const mix = a.map((v, i) => Math.round(v * (1 - fr) + b[i] * fr));
  return `rgba(${mix[0]}, ${mix[1]}, ${mix[2]}, ${Math.max(0, Math.min(1, alpha)).toFixed(3)})`;
}

/**
 * The polygons to draw. A zone whose far edge, or whose near edge, never crossed the
 * frame is left out — there is nothing to bound it.
 */
export function zonePolygons(zones: AccuracyZones): ZonePolygon[] {
  const { width, height, bands_m: bands, curves, cells, range_m: range } = zones;
  const out: ZonePolygon[] = [];
  const colWidth = width / 3;
  for (const cell of cells) {
    const top = curves[cell.band];
    if (!top) continue;
    const below = cell.band === 0 ? null : curves[cell.band - 1];
    if (cell.band > 0 && !below) continue;
    const ci = ZONE_COLUMNS.indexOf(cell.column);
    const x0 = ci * colWidth;
    const x1 = (ci + 1) * colWidth;
    const xs = Array.from(
      { length: SAMPLES_PER_COLUMN },
      (_, i) => x0 + ((x1 - x0) * i) / (SAMPLES_PER_COLUMN - 1),
    );
    const topPts = xs.map((x) => [x, curveV(top, x)]);
    const botPts = xs.map((x) => [x, below ? curveV(below, x) : height]);
    const points = [...topPts, ...botPts.reverse()].flat();
    const uMid = (x0 + x1) / 2;
    const vFar = curveV(top, uMid);
    const vNear = below ? curveV(below, uMid) : height;
    const near = cell.band === 0 ? 0 : bands[cell.band - 1];
    out.push({
      key: `${cell.column}${cell.band + 1}`,
      band: cell.band,
      column: cell.column,
      points,
      label: { u: uMid, v: (vFar + vNear) / 2 },
      heightPx: Math.max(0, vNear - vFar),
      tiles: cell.tiles,
      medianErrorM: cell.median_error_m,
      t: zoneT(cell, range),
      name: `${cell.column}${cell.band + 1}`,
      rangeLabel: `${Math.round(near)}–${Math.round(bands[cell.band])} m`,
    });
  }
  return out;
}
