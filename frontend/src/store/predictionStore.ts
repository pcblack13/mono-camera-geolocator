/**
 * `predictionStore` — the LIVE cursor prediction (1.2.6). Browser-only, L7.
 *
 * ★ A deliberately tiny, separate store — NOT `correspondenceStore`. The live
 *   prediction is a look-only aid: as the surveyor moves the cursor over the
 *   photograph (Auto GCP on, camera solved), the auto-GCP locator estimates where that
 *   pixel lands on the ground and the map shows a ghost marker there. It is NEVER a GCP
 *   and NEVER committable — keeping it in its own store, holding only a `LatLon`, makes
 *   that impossible by construction (the §5 invariant, same reasoning as
 *   `correspondenceStore`: a preview the table cannot represent cannot leak into it).
 *
 * ★ `active` is the toggle the photo pane owns; `latLon` is the last estimate the
 *   controller wrote; `pending` is a request in flight (for a subtle busy hint). Turning
 *   the mode off clears the geometry so no stale ghost survives.
 */

import { create } from 'zustand';

import type { LatLon } from '../types/geo';

export interface PredictionState {
  /** The live-predict mode is on (toggled from the photo pane's header). */
  active: boolean;
  /** The last estimated ground point, or null (no cursor, off, or an estimate that missed). */
  latLon: LatLon | null;
  /** An estimate request is in flight. */
  pending: boolean;

  setActive: (active: boolean) => void;
  setPrediction: (latLon: LatLon | null) => void;
  setPending: (pending: boolean) => void;
  reset: () => void;
}

export const usePredictionStore = create<PredictionState>((set) => ({
  active: false,
  latLon: null,
  pending: false,

  // Turning the mode off drops any ghost marker and the busy flag with it.
  setActive: (active) =>
    set(active ? { active: true } : { active: false, latLon: null, pending: false }),
  setPrediction: (latLon) => set({ latLon }),
  setPending: (pending) => set({ pending }),
  reset: () => set({ active: false, latLon: null, pending: false }),
}));
