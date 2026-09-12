/**
 * Which surface does the 3D pane stand on? Project DEM first, global fallback second.
 */

import { describe, expect, it } from 'vitest';

import { GLOBAL_TERRAIN_MAX_ZOOM, terrainTileTemplate } from '../components/map/terrainDefaults';

const P = '11111111-2222-3333-4444-555555555555';

describe('terrainTileTemplate', () => {
  it('★ a project WITH a DEM gets ITS OWN surface — the one GCPs sample Z from', () => {
    expect(terrainTileTemplate('/api/v1', P, true)).toBe(
      `/api/v1/projects/${P}/terrain/{z}/{x}/{y}.png`,
    );
  });

  it('★ no project DEM → the global fallback, not flat ground', () => {
    expect(terrainTileTemplate('/api/v1', P, false)).toBe('/api/v1/terrain/global/{z}/{x}/{y}.png');
  });

  it('no project at all → global fallback', () => {
    expect(terrainTileTemplate('/api/v1', null, true)).toBe(
      '/api/v1/terrain/global/{z}/{x}/{y}.png',
    );
  });

  it("max zoom matches the tileset's real detail (server refuses beyond it)", () => {
    expect(GLOBAL_TERRAIN_MAX_ZOOM).toBe(14);
  });
});
