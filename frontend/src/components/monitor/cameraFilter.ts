/**
 * `monitor/cameraFilter.ts` — the fleet's one filter, shared by the globe's list
 * and the grid's wall.
 *
 * ★ ONE RULE, TWO VIEWS (2026-09-07, owner ask). "Live" is a camera whose last
 *   observation was a frame; "Lost" is one that dropped or was refused — the same
 *   split `selectLiveCount` / `selectLostCount` count in the HUD, so the toggle
 *   and the numbers above it can never disagree. A camera nobody has probed yet is
 *   `unknown`: it is neither live nor lost, and shows only under "All".
 */

import type { CameraStatus, CameraStatusState } from '../../store/cameraRegistryStore';

export type CameraFilter = 'all' | 'live' | 'lost';

/** Does this state belong to that filter? */
export function matchesFilter(state: CameraStatusState, filter: CameraFilter): boolean {
  if (filter === 'all') return true;
  if (filter === 'live') return state === 'live';
  return state === 'lost' || state === 'refused';
}

/** The state a camera is in, defaulting to `unknown` for one never probed. */
export function statusOf(
  statuses: Readonly<Record<string, CameraStatus>>,
  id: string,
): CameraStatusState {
  return statuses[id]?.state ?? 'unknown';
}
