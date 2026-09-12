/**
 * Project elevation sampling — wire types for `/projects/{id}/elevation/sample`.
 *
 * ★ THE CASING LAW (§8.1 / L9): snake_case, because these are wire fields.
 *
 * ★ **`elevation_m: null` is a real answer, not a missing one.** A project with no DEM,
 *   a point outside coverage, and a nodata cell all return null — and never 0, because
 *   0 m is a genuine elevation that must stay distinguishable from "we do not know".
 *   `dem_attached` separates the first case from the other two: "you never attached a
 *   raster" is a setup step, "your DEM has no data here" is the terrain.
 */

import type { Uuid } from './common';

/** One coordinate to sample, EPSG:4326. */
export interface ElevationSamplePoint {
  lat: number;
  lon: number;
}

/** One point's answer, positionally aligned with the request. */
export interface SampledElevation {
  /** Metres above the vertical datum. ★ `null` when unknown — never 0 as a stand-in. */
  elevation_m: number | null;
  /**
   * `local_dem` | `copernicus_dem` | `srtm` | `exif` | `manual`.
   *
   * ★ Non-null **iff** `elevation_m` is. A source may never name a DEM that did not answer.
   */
  source: string | null;
  /** Vertical CE90 in metres, or null when unquantified. ★ Null is honest; 0 would not be. */
  vertical_ce90_m: number | null;
}

export interface ElevationSampleRequest {
  points: ElevationSamplePoint[];
}

export interface ElevationSampleResponse {
  results: SampledElevation[];
  /** Whether the project has a DEM at all — distinct from "the DEM answered null here". */
  dem_attached: boolean;
  with_elevation_count: number;
}

/** What the cursor readout renders. A discriminated union so no state can be forgotten. */
export type CursorElevation =
  | { kind: 'idle' }
  | { kind: 'loading' }
  /** The project has no DEM. Actionable: attach one in the workspace setup. */
  | { kind: 'no_dem' }
  /** A DEM is attached but has nothing here — outside coverage, or a nodata void. */
  | { kind: 'no_data' }
  | { kind: 'value'; elevation_m: number; source: string; vertical_ce90_m: number | null };

/** Convenience alias — the project a readout belongs to. */
export type ElevationProjectId = Uuid;
