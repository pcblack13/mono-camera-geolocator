/**
 * The one lon/lat flip site, and what is built on it.
 *
 * ★ A camera at 33.8330 N, 35.5410 E must land EAST of Greenwich and NORTH of the
 *   equator in GeoJSON — `[35.541, 33.833]`, longitude first. Everything on the
 *   globe goes through `toLonLat`; this is the test that keeps it honest.
 */

import { describe, expect, it } from 'vitest';

import {
  camerasToFeatureCollection,
  destinationPoint,
  fovWedge,
  toLonLat,
} from '../lib/monitor/geojson';
import type { RegisteredCamera } from '../store/cameraRegistryStore';

const beirut: RegisteredCamera = {
  id: 'c1',
  name: 'Beirut roof',
  lat: 33.833,
  lon: 35.541,
  source: 'http://a/s',
  heading_deg: 90,
  created_at: '2026-08-28T00:00:00Z',
};

describe('toLonLat', () => {
  it('★ puts longitude first', () => {
    expect(toLonLat(beirut)).toEqual([35.541, 33.833]);
  });
});

describe('camerasToFeatureCollection', () => {
  it('lands the marker east of Greenwich and north of the equator, carrying its status', () => {
    const fc = camerasToFeatureCollection([beirut], () => 'live');
    const [lon, lat] = fc.features[0].geometry.coordinates;
    expect(lon).toBeGreaterThan(0);
    expect(lat).toBeGreaterThan(0);
    expect(fc.features[0].properties).toMatchObject({ id: 'c1', status: 'live', heading_deg: 90 });
  });
});

describe('fovWedge', () => {
  it('starts and ends at the camera, and reaches out along the heading', () => {
    const poly = fovWedge(beirut, 90, 60, 1000, 4);
    const ring = poly.coordinates[0];
    expect(ring[0]).toEqual(toLonLat(beirut));
    expect(ring[ring.length - 1]).toEqual(toLonLat(beirut));
    // Heading 90 = east: the wedge's middle point is east of the camera at the same latitude.
    const mid = destinationPoint(beirut, 90, 1000);
    expect(mid.lon).toBeGreaterThan(beirut.lon);
    expect(Math.abs(mid.lat - beirut.lat)).toBeLessThan(1e-4);
  });
});
