/**
 * `offlineCacheStore` — the draw-a-polygon-to-cache interaction (offline satellite prep).
 *
 * Owns the in-progress polygon the surveyor draws on the satellite map to mark an area to
 * download for offline use. Nothing here is persisted or sent to the API: the vertices are a
 * transient UI gesture, and the actual caching is done by the panel warming the tile proxy.
 *
 * ★ L7 — browser-only state.
 */

import { create } from 'zustand';

import type { LatLon } from '../types/geo';

export interface OfflineCacheState {
  /** True while the surveyor is clicking vertices on the map. */
  drawing: boolean;
  /** Polygon vertices, in click order. `[lat, lon]` is carried as {@link LatLon}. */
  points: LatLon[];

  /** Enter draw mode with a fresh, empty polygon. */
  startDrawing: () => void;
  /** Append a clicked vertex (ignored when not drawing). */
  addPoint: (p: LatLon) => void;
  /** Remove the last vertex. */
  undoPoint: () => void;
  /** Stop adding vertices but keep the polygon (needs ≥3 points to be usable). */
  finishDrawing: () => void;
  /** Exit draw mode and discard the polygon. */
  reset: () => void;
}

export const useOfflineCacheStore = create<OfflineCacheState>((set) => ({
  drawing: false,
  points: [],

  startDrawing: () => set({ drawing: true, points: [] }),
  addPoint: (p) => set((s) => (s.drawing ? { points: [...s.points, p] } : s)),
  undoPoint: () => set((s) => ({ points: s.points.slice(0, -1) })),
  // ★ Idempotent by design: called by the Done button AND implicitly by the start
  //   of a download, so neither path can leave the map armed for vertices.
  finishDrawing: () => set({ drawing: false }),
  reset: () => set({ drawing: false, points: [] }),
}));
