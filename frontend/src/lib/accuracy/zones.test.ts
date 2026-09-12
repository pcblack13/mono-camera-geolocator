/**
 * The nine zones as polygons — the geometry the photo pane draws, pinned without a
 * canvas.
 */

import { describe, expect, it } from 'vitest';

import type { AccuracyZones } from '../../api/accuracy';
import { curveV, withAlpha, zoneFill, zonePolygons, zoneT } from './zones';

/** A 1200×800 frame: near edge at row 600, mid edge at 400, far edge at 200. */
function fixture(overrides: Partial<AccuracyZones> = {}): AccuracyZones {
  const flat = (v: number): number[][] => [
    [0, v],
    [600, v],
    [1200, v],
  ];
  const cells: AccuracyZones['cells'] = [];
  for (let band = 0; band < 3; band += 1) {
    for (const column of ['L', 'M', 'R'] as const) {
      cells.push({ band, column, tiles: 12, median_error_m: 4 + band * 2 });
    }
  }
  return {
    width: 1200,
    height: 800,
    bands_m: [400, 800, 1200],
    min_tiles: 5,
    curves: [flat(600), flat(400), flat(200)],
    cells,
    range_m: [4, 8],
    ...overrides,
  };
}

describe('curveV', () => {
  it('interpolates between the contour points and clamps at its ends', () => {
    const curve = [
      [0, 100],
      [100, 200],
    ];
    expect(curveV(curve, 50)).toBe(150);
    expect(curveV(curve, -10)).toBe(100);
    expect(curveV(curve, 500)).toBe(200);
  });
});

describe('zonePolygons', () => {
  it('bounds the nearest band by the frame bottom and every other by the band before', () => {
    const polys = zonePolygons(fixture());
    expect(polys).toHaveLength(9);
    const l1 = polys.find((p) => p.key === 'L1')!;
    const l2 = polys.find((p) => p.key === 'L2')!;
    const ys = (pts: number[]): number[] => pts.filter((_n, i) => i % 2 === 1);
    // L1: top contour at 600, bottom the frame at 800.
    expect(Math.min(...ys(l1.points))).toBe(600);
    expect(Math.max(...ys(l1.points))).toBe(800);
    // L2: between the 400 and 600 contours.
    expect(Math.min(...ys(l2.points))).toBe(400);
    expect(Math.max(...ys(l2.points))).toBe(600);
    // The label sits halfway between the two contours, mid-column.
    expect(l2.label).toEqual({ u: 200, v: 500 });
    expect(l2.heightPx).toBe(200);
    expect(l1.heightPx).toBe(200);
    expect(l2.rangeLabel).toBe('400–800 m');
  });

  it('keeps each column inside its third of the frame', () => {
    const polys = zonePolygons(fixture());
    const xs = (pts: number[]): number[] => pts.filter((_n, i) => i % 2 === 0);
    const m1 = polys.find((p) => p.key === 'M1')!;
    expect(Math.min(...xs(m1.points))).toBe(400);
    expect(Math.max(...xs(m1.points))).toBe(800);
  });

  it('leaves out a zone whose far edge never crossed the frame', () => {
    const polys = zonePolygons(fixture({ curves: [fixture().curves[0], fixture().curves[1], null] }));
    expect(polys).toHaveLength(6);
    expect(polys.some((p) => p.band === 2)).toBe(false);
  });

  it('normalises colour across the zones with data, and gives no-data zones no colour', () => {
    const z = fixture();
    z.cells[0] = { ...z.cells[0], tiles: 2, median_error_m: null };
    const polys = zonePolygons(z);
    expect(polys.find((p) => p.key === 'L1')!.t).toBeNull();
    expect(polys.find((p) => p.key === 'M1')!.t).toBe(0); // 4 m = the best
    expect(polys.find((p) => p.key === 'M3')!.t).toBe(1); // 8 m = the worst
    expect(polys.find((p) => p.key === 'M2')!.t).toBe(0.5);
  });
});

describe('colours', () => {
  it('zoneT is null without a scale, and clamps into 0..1', () => {
    expect(zoneT({ band: 0, column: 'L', tiles: 9, median_error_m: 5 }, null)).toBeNull();
    expect(zoneT({ band: 0, column: 'L', tiles: 9, median_error_m: 50 }, [4, 8])).toBe(1);
    expect(zoneT({ band: 0, column: 'L', tiles: 9, median_error_m: 6 }, [6, 6])).toBe(0);
  });

  it('zoneFill walks the shared heat ramp and carries the alpha', () => {
    expect(zoneFill(0, 0.45)).toBe('rgba(255, 247, 236, 0.450)');
    expect(zoneFill(1, 1)).toBe('rgba(127, 0, 0, 1.000)');
    expect(withAlpha('#ffffff', 2)).toBe('rgba(255, 255, 255, 1.000)');
  });
});
