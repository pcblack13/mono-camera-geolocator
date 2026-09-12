/**
 * Offline Area Manager plumbing — pure logic, no DOM.
 *
 * ★ Pins: `formatBytes` (the storage estimate line), `beyondNativeResolution` (the
 *   512-px zoom-shift interaction with the overzoom warning — the same +1 trap the
 *   blank-Mapbox-map bug came from), and the client↔server polygon axis order.
 */

import { describe, expect, it } from 'vitest';

import { formatBytes } from '../api/offline';
import { beyondNativeResolution, tilesForPolygon } from '../components/map/tileMath';

describe('formatBytes', () => {
  it('formats the estimate line humanly', () => {
    expect(formatBytes(0)).toBe('0 B');
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(30_000)).toBe('29.3 KB');
    expect(formatBytes(1_825_361_101)).toBe('1.7 GB');
  });

  it('refuses to invent a size for garbage', () => {
    expect(formatBytes(-1)).toBe('—');
    expect(formatBytes(Number.NaN)).toBe('—');
  });
});

describe('beyondNativeResolution', () => {
  it('is false at or below the native boundary', () => {
    expect(beyondNativeResolution(19, 0, 19)).toBe(false);
    expect(beyondNativeResolution(18, 0, 19)).toBe(false);
  });

  it('is true past the boundary', () => {
    expect(beyondNativeResolution(20, 0, 19)).toBe(true);
  });

  it('★ shifts with the 512-px tile zoom offset — the map zoom runs one ahead', () => {
    // Mapbox: native ~z19 (provider zooms), 512px tiles → map zoom = provider + 1.
    expect(beyondNativeResolution(20, 1, 19)).toBe(false); // map z20 = provider z19: native
    expect(beyondNativeResolution(21, 1, 19)).toBe(true); // map z21 = provider z20: overzoom
  });

  it('never claims overzoom when the boundary is unknown', () => {
    expect(beyondNativeResolution(22, 0, null)).toBe(false);
    expect(beyondNativeResolution(22, 0, undefined)).toBe(false);
  });
});

describe('AOI polygon axis order', () => {
  it('client draw points ([lat, lon]) and the wire body ([lon, lat]) stay distinct', () => {
    // The draw store keeps {lat, lon}; tileMath takes [lat, lon]; the offline API body
    // takes [lon, lat] (GeoJSON). This pins the conversion the panel performs.
    const drawn = [
      { lat: 33.9, lon: 35.5 },
      { lat: 33.9, lon: 35.52 },
      { lat: 33.92, lon: 35.52 },
    ];
    const forTileMath: [number, number][] = drawn.map((p) => [p.lat, p.lon]);
    const forWire: [number, number][] = drawn.map((p) => [p.lon, p.lat]);
    const { tiles } = tilesForPolygon(forTileMath, 13, 13, 100);
    expect(tiles.length).toBeGreaterThan(0);
    expect(forWire[0]).toEqual([35.5, 33.9]); // lon first on the wire
  });
});
