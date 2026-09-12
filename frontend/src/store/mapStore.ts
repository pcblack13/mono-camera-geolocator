/**
 * `mapStore` — CONTRACT.md §8.5 / 50-frontend.md §3.4, §3.6.
 *
 * Owns: `view` · `lastOrigin` · `seq` · `basemap` · `providerId` · `heatmapEnabled` ·
 * `footprintVisible` · `locationHint` · `isDrawingHint`.
 * Persisted: `basemap`, `providerId`, `heatmapEnabled`, `footprintVisible`.
 *
 * ★ **`mapStore.view` is the single source of truth** (§3.6). Leaflet owns an
 *   imperative view, React a declarative one; reconciling them naively oscillates.
 *   `SatelliteMap` renders `<MapContainer>` UNCONTROLLED (`center`/`zoom` are initial
 *   values only) and delegates all reconciliation to `MapViewSync`.
 *
 * ★ L7 — `providerId` is a user CHOICE, not the provider list. `ProviderInfo[]`
 *   comes from `GET /providers` via React Query and is never held here.
 *
 * ★ TWO CONTRACT CORRECTIONS, applied deliberately (§0 precedence: CONTRACT > 50-frontend):
 *   1. `MapViewState` is `{center, zoom, bounds}` (`types/geo.ts`, IU-23). 50-frontend's
 *      `{center, zoom, bearing: 0}` is void — there is no `bearing` on the type, and
 *      Leaflet raster is north-up anyway, so the field asserted a capability that does
 *      not exist.
 *   2. `ViewOrigin` is `'image' | 'map' | 'table' | 'user' | 'sync'` (`types/geo.ts`).
 *      50-frontend's `'app'` member does not exist; `'user'` is its counterpart.
 */

import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';

import type {
  BBox,
  LatLon,
  LocationHint,
  MapViewState,
  ProviderId,
  ViewOrigin,
} from '../types/geo';
import type { BasemapKind } from '../types/geo';

/** §3.6 — Leaflet rounds coordinates; a naive equality check makes `setView` fire
 *  forever on a value that never converges. ~1 cm and 0.01 zoom are below any
 *  perceptible or meaningful threshold. */
export const VIEW_EPSILON_DEG = 1e-7;
export const VIEW_EPSILON_ZOOM = 0.01;

/** A sensible, non-committal starting view. Overridden the moment any hint resolves. */
const DEFAULT_VIEW: MapViewState = { center: { lat: 0, lon: 0 }, zoom: 2, bounds: null };

export interface MapState {
  view: MapViewState;
  /** ★ Who caused the current view. Reveal is gated on it (§3.5). */
  lastOrigin: ViewOrigin;
  /** ★ Monotonic; the anti-feedback token (§3.6). */
  seq: number;
  basemap: BasemapKind;
  /** `null` = the backend default, which is KEYLESS (`esri_world_imagery`, L2). */
  providerId: ProviderId | null;
  heatmapEnabled: boolean;
  footprintVisible: boolean;
  locationHint: LocationHint | null;
  isDrawingHint: boolean;

  setView: (v: MapViewState, origin: ViewOrigin) => void;
  /** ★ Takes primitives, NOT a `GcpRead` — L7 keeps server rows out of this store. */
  flyToGcp: (p: LatLon, zoom?: number) => void;
  fitBounds: (b: BBox, origin: ViewOrigin) => void;
  setBasemap: (b: BasemapKind) => void;
  setProvider: (id: ProviderId | null) => void;
  toggleHeatmap: () => void;
  toggleFootprint: () => void;
  setLocationHint: (h: LocationHint | null) => void;
  setDrawingHint: (v: boolean) => void;
}

/** §3.6 — the epsilon is doing real work. See {@link VIEW_EPSILON_DEG}. */
export function viewsEqual(a: MapViewState, b: MapViewState): boolean {
  return (
    Math.abs(a.center.lat - b.center.lat) < VIEW_EPSILON_DEG &&
    Math.abs(a.center.lon - b.center.lon) < VIEW_EPSILON_DEG &&
    Math.abs(a.zoom - b.zoom) < VIEW_EPSILON_ZOOM
  );
}

/** The zoom `flyToGcp` lands on: close enough to judge a landmark, wide enough for context. */
export const GCP_REVEAL_ZOOM = 18;

export const useMapStore = create<MapState>()(
  devtools(
    persist(
      (set, get) => ({
        view: DEFAULT_VIEW,
        lastOrigin: 'user',
        seq: 0,
        basemap: 'satellite',
        providerId: null,
        heatmapEnabled: false,
        footprintVisible: true,
        locationHint: null,
        isDrawingHint: false,

        /**
         * ★ Every write bumps `seq`. `flyTo` animates over ~500 ms and emits
         *   intermediate `move` events; a `moveend` carrying a stale `seq` is dropped
         *   by `MapViewSync`. Without it the animation's own events race the store.
         *
         * ★ No-op on an epsilon-equal view from the SAME origin, so a Leaflet
         *   rounding jitter cannot spin the downward effect forever.
         */
        setView: (v, origin) => {
          const s = get();
          if (origin === s.lastOrigin && viewsEqual(s.view, v)) return;
          set({ view: v, lastOrigin: origin, seq: s.seq + 1 }, false, `map/setView:${origin}`);
        },

        flyToGcp: (p, zoom = GCP_REVEAL_ZOOM) =>
          get().setView({ center: p, zoom, bounds: null }, 'table'),

        fitBounds: (b, origin) => {
          const center: LatLon = {
            lat: (b.min_lat + b.max_lat) / 2,
            lon: (b.min_lon + b.max_lon) / 2,
          };
          // ★ Leaflet computes the zoom that frames `bounds`; we carry the bounds and
          //   let it do that rather than guessing a zoom from a span here. A wrong
          //   guess frames the wrong area, which on a satellite pane is invisible.
          get().setView({ center, zoom: get().view.zoom, bounds: b }, origin);
        },

        setBasemap: (b) => set({ basemap: b }, false, 'map/setBasemap'),
        setProvider: (id) => set({ providerId: id }, false, 'map/setProvider'),
        toggleHeatmap: () =>
          set((s) => ({ heatmapEnabled: !s.heatmapEnabled }), false, 'map/toggleHeatmap'),
        toggleFootprint: () =>
          set((s) => ({ footprintVisible: !s.footprintVisible }), false, 'map/toggleFootprint'),
        setLocationHint: (h) => set({ locationHint: h }, false, 'map/setLocationHint'),
        setDrawingHint: (v) => set({ isDrawingHint: v }, false, 'map/setDrawingHint'),
      }),
      {
        name: 'landexplorer.map',
        version: 1,
        partialize: (s) => ({
          basemap: s.basemap,
          providerId: s.providerId,
          heatmapEnabled: s.heatmapEnabled,
          footprintVisible: s.footprintVisible,
        }),
        merge: (persisted, current) => {
          const p = persisted as Partial<MapState> | undefined;
          if (!p) return current;
          // ★ Validate rather than trust: an older build may have persisted a
          //   provider id this build no longer knows (or that was removed for ToS
          //   reasons). An unknown provider silently becomes the keyless default
          //   rather than a 422 the user cannot explain. L2 stays true.
          const basemaps: BasemapKind[] = ['satellite', 'hybrid', 'terrain'];
          return {
            ...current,
            basemap: p.basemap && basemaps.includes(p.basemap) ? p.basemap : current.basemap,
            providerId: typeof p.providerId === 'string' ? p.providerId : null,
            heatmapEnabled:
              typeof p.heatmapEnabled === 'boolean' ? p.heatmapEnabled : current.heatmapEnabled,
            footprintVisible:
              typeof p.footprintVisible === 'boolean'
                ? p.footprintVisible
                : current.footprintVisible,
          };
        },
      },
    ),
    { name: 'mapStore' },
  ),
);
