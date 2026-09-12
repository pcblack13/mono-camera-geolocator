/**
 * Project elevation sampling — `POST /projects/{id}/elevation/sample`.
 *
 * ★ **Distinct from `dem.ts`.** That module drives the DEM *page*: uploading a raster,
 *   cropping it, reprojecting it, sampling a specific processing run. This one answers
 *   the workspace's question — *"what does this project say the elevation is here?"* —
 *   against whatever DEM the project has attached, with no run id in sight.
 *
 * ★ **Batched even for one point.** The server reads the raster once per request
 *   regardless of point count, so the cursor readout and a bulk query share one path. A
 *   single-point convenience call would be a second implementation of the one thing that
 *   must not drift.
 */

import type { Uuid } from '../types/common';
import type { ElevationSamplePoint, ElevationSampleResponse } from '../types/elevation';
import { fetchJson } from './client';

export const elevationApi = {
  /**
   * Sample this project's DEM at each point.
   *
   * Returns one result per input point, in order. A project with no DEM answers with
   * `dem_attached: false` and all-null elevations rather than an error — not having a
   * DEM is a legitimate state of the product, not a failure.
   */
  sample: (
    projectId: Uuid,
    points: ElevationSamplePoint[],
    signal?: AbortSignal,
  ): Promise<ElevationSampleResponse> =>
    fetchJson<ElevationSampleResponse>(`/projects/${projectId}/elevation/sample`, {
      method: 'POST',
      body: { points },
      signal,
    }),
};
