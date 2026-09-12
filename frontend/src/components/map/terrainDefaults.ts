/**
 * Constants shared with the lazily-loaded 3D pane.
 *
 * ★ **This file exists so `MapPanel` can name a default without importing the 3D module.**
 *   `Terrain3DMap` pulls in maplibre-gl (~800 kB) and is behind `React.lazy` for exactly
 *   that reason; a plain `import { DEFAULT_EXAGGERATION } from './Terrain3DMap'` would
 *   drag the whole library back into the eager chunk and silently undo the split. Keeping
 *   the constant in a leaf module with no dependencies makes that impossible rather than
 *   merely discouraged.
 */

/**
 * Default vertical exaggeration for the 3D terrain.
 *
 * ★ 1.0 — true scale, deliberately not the flattering 1.5 most globe demos ship.
 * Exaggeration makes terrain legible but it is a *lie about slope*, and this is a survey
 * tool: a surveyor judging whether a hillside matches their photograph must be able to
 * trust the angle unless they changed it themselves.
 */
export const DEFAULT_EXAGGERATION = 1.0;

/**
 * ★ The deepest zoom the GLOBAL terrain source really has. The AWS/Mapzen terrarium
 * tileset's native detail ends at 14; the server refuses beyond it rather than
 * upsampling invented relief, and declaring a deeper maxzoom here would make MapLibre
 * request tiles that 422.
 */
export const GLOBAL_TERRAIN_MAX_ZOOM = 14;

/** Display credit for the global terrain — shown whenever it, not a project DEM, is
 *  the surface under the camera. Attribution is an obligation, not decoration. */
export const GLOBAL_TERRAIN_ATTRIBUTION =
  'Terrain: Mapzen/AWS Terrain Tiles — SRTM, 3DEP, GMTED2010 (NASA/USGS)';

/**
 * Which terrain tile template the 3D pane should use.
 *
 * ★ PROJECT DEM FIRST, GLOBAL AS FALLBACK. The project's own DEM is the surface its
 * GCPs sample Z from — when it exists, the 3D view must show THAT surface, not a
 * global ~30 m model that can disagree with it by a building's height. The global
 * source exists so a project with no DEM still gets real relief instead of the flat
 * plane it used to render.
 *
 * Pure data → data; unit-tested in terrain-source.test.ts.
 */
export function terrainTileTemplate(
  apiBaseUrl: string,
  projectId: string | null,
  hasProjectDem: boolean,
): string {
  if (projectId !== null && hasProjectDem) {
    return `${apiBaseUrl}/projects/${projectId}/terrain/{z}/{x}/{y}.png`;
  }
  return `${apiBaseUrl}/terrain/global/{z}/{x}/{y}.png`;
}
