/**
 * Whether a project has an elevation source — `GET /projects/{id}/dem`.
 *
 * ★ **Gates the 3D view, and that is the point.** With no DEM every terrain tile 404s and
 *   the 3D pane renders dead flat — working software confidently showing you flat ground,
 *   which is the most misleading outcome available. SCOPE.md §4 rule 4 requires the
 *   control be disabled with an honest reason *before* it is clicked, and that needs this
 *   answer up front rather than discovered from a failed tile.
 *
 * ★ A project without a DEM is a **normal state**, not an error: `active: false` comes
 *   back 200. Z is strictly opt-in per project, and a project that never attached a raster
 *   records honest `NULL` elevations.
 */

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import type { Uuid } from '../../types/common';
import type { DemActiveResponse } from '../../types/dem';
import { demApi } from '../dem';
import { qk } from '../queryKeys';

/**
 * `GET /projects/{id}/dem`.
 *
 * `staleTime: 5 min` — a DEM is attached by a deliberate upload, not by background
 * activity, and the mutation paths invalidate this key directly.
 */
export function useProjectDem(projectId: Uuid | null): UseQueryResult<DemActiveResponse> {
  return useQuery({
    queryKey: qk.projectDem(projectId!),
    queryFn: ({ signal }) => demApi.projectDem(projectId!, signal),
    enabled: projectId !== null,
    staleTime: 5 * 60_000,
  });
}
