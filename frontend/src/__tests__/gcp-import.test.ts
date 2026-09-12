/**
 * `parseGcpFile` — the import half of the GCP round trip.
 *
 * ★ The contract test: a file in THIS APP'S OWN export shape (CSV headers
 *   `Image X`/`Image Y`/`Latitude`/`Longitude`; GeoJSON `pixel_col`/`pixel_row`
 *   properties) must import losslessly. Foreign spellings and honest skipping are
 *   pinned alongside.
 */

import { describe, expect, it } from 'vitest';

import { parseGcpCsv, parseGcpFile, parseGcpGeojson } from '../lib/gcpImport';

describe('CSV import', () => {
  it('★ round-trips this app’s own export columns', () => {
    const csv = [
      'Point ID,Name,Image X,Image Y,Latitude,Longitude,Accuracy',
      'abc123,P1,1744.5,626.6,34.113400,36.023500,±8 m',
      'def456,P2,2727.8,764.7,34.106700,36.021600,±8 m',
    ].join('\n');
    const { points, skipped } = parseGcpCsv(csv);
    expect(skipped).toEqual([]);
    expect(points).toEqual([
      { name: 'P1', image_x: 1744.5, image_y: 626.6, lat: 34.1134, lon: 36.0235 },
      { name: 'P2', image_x: 2727.8, image_y: 764.7, lat: 34.1067, lon: 36.0216 },
    ]);
  });

  it('accepts common foreign header spellings (pixel_x / lng)', () => {
    const csv = ['name,pixel_x,pixel_y,lat,lng', 'A,10,20,34.1,36.0'].join('\n');
    const { points } = parseGcpCsv(csv);
    expect(points).toHaveLength(1);
    expect(points[0]).toMatchObject({ image_x: 10, image_y: 20, lat: 34.1, lon: 36.0 });
  });

  it('handles quoted fields with embedded commas', () => {
    const csv = ['Name,Image X,Image Y,Latitude,Longitude', '"Gate, north",5,6,34.1,36.0'].join(
      '\n',
    );
    expect(parseGcpCsv(csv).points[0].name).toBe('Gate, north');
  });

  it('★ skips rows it cannot place, with named reasons', () => {
    const csv = [
      'Name,Image X,Image Y,Latitude,Longitude',
      'good,10,20,34.1,36.0',
      'no-pixels,,,34.2,36.1',
      'bad-lat,10,20,95,36.0',
    ].join('\n');
    const { points, skipped } = parseGcpCsv(csv);
    expect(points).toHaveLength(1);
    expect(skipped).toHaveLength(2);
    expect(skipped[0].reason).toContain('image pixel');
    expect(skipped[1].reason).toContain('out-of-range');
  });

  it('names the missing columns instead of importing nothing silently', () => {
    const { points, skipped } = parseGcpCsv('Name,Latitude,Longitude\nA,34.1,36.0');
    expect(points).toEqual([]);
    expect(skipped[0].reason).toContain('Image X');
  });
});

describe('the field tool project format (geolocation_gui gcps.csv)', () => {
  // The real header + representative rows from a `.geoproj/inputs/gcps/gcps.csv`.
  const FIELD_TOOL_CSV = [
    'id,name,u,v,lat,lon,offset_m,X,Y,Z,excluded,residual_px',
    '1,pt,2134.00,562.50,34.10745041,36.01832001,0.000,224949.066,3778085.316,1390.934,1,',
    '3,pt,1050.50,524.00,34.10748816,36.01769590,0.000,224891.597,3778091.185,1397.014,0,11.919',
    '14,pt,2495.45,379.34,34.10919112,36.02145348,0.000,225243.851,3778269.982,1370.671,0,24.775',
  ].join('\n');

  it('★ binds u/v as the pixel position — NEVER the UTM X/Y ground columns', () => {
    const { points } = parseGcpCsv(FIELD_TOOL_CSV);
    expect(points[0].image_x).toBe(1050.5);
    expect(points[0].image_y).toBe(524);
    // If X (Easting) had been bound as a pixel, this would be ~224891.
    expect(points[0].image_x).toBeLessThan(10000);
  });

  it('★ skips excluded=1 rows and says why — the surveyor already rejected them', () => {
    const { points, skipped } = parseGcpCsv(FIELD_TOOL_CSV);
    expect(points).toHaveLength(2);
    expect(skipped).toHaveLength(1);
    expect(skipped[0].row).toBe(2);
    expect(skipped[0].reason).toContain('excluded in the source project');
  });

  it('names points distinctly from the id column ("pt" thirty times names nothing)', () => {
    const { points } = parseGcpCsv(FIELD_TOOL_CSV);
    expect(points.map((p) => p.name)).toEqual(['pt-3', 'pt-14']);
  });

  it('carries the lat/lon through untouched', () => {
    const { points } = parseGcpCsv(FIELD_TOOL_CSV);
    expect(points[0].lat).toBeCloseTo(34.10748816, 8);
    expect(points[0].lon).toBeCloseTo(36.0176959, 8);
  });
});

describe('GeoJSON import', () => {
  it('★ round-trips this app’s own export properties', () => {
    const geojson = JSON.stringify({
      type: 'FeatureCollection',
      features: [
        {
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [36.0235, 34.1134, 1363.0] },
          properties: { label: 'P1', pixel_col: 1744.5, pixel_row: 626.6 },
        },
      ],
    });
    const { points, skipped } = parseGcpGeojson(geojson);
    expect(skipped).toEqual([]);
    expect(points[0]).toEqual({
      name: 'P1',
      image_x: 1744.5,
      image_y: 626.6,
      lat: 34.1134,
      lon: 36.0235,
    });
  });

  it('skips non-Point features and pixel-less features, named', () => {
    const geojson = JSON.stringify({
      type: 'FeatureCollection',
      features: [
        { type: 'Feature', geometry: { type: 'LineString', coordinates: [] }, properties: {} },
        {
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [36.0, 34.1] },
          properties: { name: 'world-only' },
        },
      ],
    });
    const { points, skipped } = parseGcpGeojson(geojson);
    expect(points).toEqual([]);
    expect(skipped).toHaveLength(2);
  });

  it('rejects garbage with a reason, never a throw', () => {
    expect(parseGcpGeojson('not json').skipped[0].reason).toContain('JSON');
  });
});

describe('dispatch', () => {
  it('routes .geojson/.json to the GeoJSON parser and everything else to CSV', () => {
    const gj = JSON.stringify({ type: 'FeatureCollection', features: [] });
    expect(parseGcpFile('points.geojson', gj).skipped[0].reason).toContain('features');
    expect(parseGcpFile('points.csv', 'a,b').skipped[0].reason).toContain('no data');
  });
});
