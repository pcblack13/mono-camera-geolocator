/**
 * `store/monitorLayoutStore.ts` — where the operator put the monitor page's seams.
 *
 * ★ A PREFERENCE, PERSISTED — the `workspaceStore` rule. The inspector's width and
 *   the bottom deck's height are the surveyor's; a reload must find them. Same
 *   validating merge, same bounds-on-write-and-on-rehydrate: a persisted `deckPx: 0`
 *   would restore a page with no deck and no handle to get it back.
 *
 * ★ Focus mode (the globe's `F`) is TRANSIENT, as the workspace's is: arriving into
 *   a hidden HUD with no memory of choosing it reads as a broken page.
 */

import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';

export type DeckTab = 'map' | 'detections' | 'events';

/** The monitor's entry view: cameras on the Earth, or as a wall of live tiles. */
export type MonitorView = 'globe' | 'grid';

export interface OverlayToggles {
  boxes: boolean;
  labels: boolean;
  tracks: boolean;
  drift: boolean;
  /** HUD look — corner brackets + locked-target crosshair. Opt-in (2026-09-03). */
  hud: boolean;
  /** ★ The SENDER'S own boxes (2026-09-08). A camera whose data source is a GEO1
   *  bridge already detected on its own hardware; this draws those boxes the
   *  moment the picture appears, with no run of ours. Mutually exclusive with a
   *  detection run by construction — see `CameraMonitorPage`. */
  piBoxes: boolean;
}

export interface MonitorLayoutState {
  inspectorPx: number;
  inspectorOpen: boolean;
  /**
   * ★ THE MAP SITS BESIDE THE PICTURE (2026-08-30) — two panels in ONE ROW, the
   *   same height, once a lookup table gives it a site; the deck runs under both.
   *   `false` docks it back into the deck.
   */
  mapBeside: boolean;
  /** The map's share of that row's width — half by default; the seam moves it. */
  mapFraction: number;
  deckPx: number;
  deckOpen: boolean;
  deckTab: DeckTab;
  overlays: OverlayToggles;
  /** Globe or grid — how /monitor shows the fleet (2026-09-02). */
  monitorView: MonitorView;
  /** The globe's right HUD panel. */
  hudOpen: boolean;
  /** ★ Borders and place names on the globe (2026-09-10). */
  placesVisible: boolean;
  /** Transient: hide every HUD element (the globe's `F`). */
  focusMode: boolean;

  setInspectorPx: (px: number) => void;
  setInspectorOpen: (v: boolean) => void;
  setMapBeside: (v: boolean) => void;
  setMapFraction: (fraction: number) => void;
  setDeckPx: (px: number) => void;
  setDeckOpen: (v: boolean) => void;
  setDeckTab: (t: DeckTab) => void;
  toggleOverlay: (k: keyof OverlayToggles) => void;
  setMonitorView: (v: MonitorView) => void;
  setHudOpen: (v: boolean) => void;
  setPlacesVisible: (v: boolean) => void;
  setFocusMode: (v: boolean) => void;
  resetLayout: () => void;
}

const BOUNDS = {
  inspectorPx: [280, 560] as const,
  deckPx: [160, 720] as const,
  mapFraction: [0.25, 0.75] as const,
};
const clamp = (v: number, [lo, hi]: readonly [number, number], fallback: number): number =>
  Number.isFinite(v) ? Math.min(hi, Math.max(lo, v)) : fallback;

const DEFAULTS = {
  inspectorPx: 360,
  inspectorOpen: true,
  mapBeside: true,
  mapFraction: 0.5,
  deckPx: 300,
  deckOpen: true,
  deckTab: 'map' as DeckTab,
  overlays: {
    boxes: true,
    labels: true,
    tracks: true,
    drift: true,
    hud: false,
    piBoxes: true,
  } as OverlayToggles,
  monitorView: 'globe' as MonitorView,
  hudOpen: true,
  placesVisible: true,
  focusMode: false,
};

const TABS: DeckTab[] = ['map', 'detections', 'events'];

export const useMonitorLayoutStore = create<MonitorLayoutState>()(
  devtools(
    persist(
      (set) => ({
        ...DEFAULTS,
        setInspectorPx: (px) =>
          set(
            { inspectorPx: clamp(px, BOUNDS.inspectorPx, DEFAULTS.inspectorPx) },
            false,
            'monitorLayout/setInspectorPx',
          ),
        setInspectorOpen: (v) => set({ inspectorOpen: v }, false, 'monitorLayout/setInspectorOpen'),
        setMapBeside: (v) => set({ mapBeside: v }, false, 'monitorLayout/setMapBeside'),
        setMapFraction: (fraction) =>
          set(
            { mapFraction: clamp(fraction, BOUNDS.mapFraction, DEFAULTS.mapFraction) },
            false,
            'monitorLayout/setMapFraction',
          ),
        setDeckPx: (px) =>
          set(
            { deckPx: clamp(px, BOUNDS.deckPx, DEFAULTS.deckPx) },
            false,
            'monitorLayout/setDeckPx',
          ),
        setDeckOpen: (v) => set({ deckOpen: v }, false, 'monitorLayout/setDeckOpen'),
        setDeckTab: (t) => set({ deckTab: t }, false, 'monitorLayout/setDeckTab'),
        toggleOverlay: (k) =>
          set(
            (s) => ({ overlays: { ...s.overlays, [k]: !s.overlays[k] } }),
            false,
            'monitorLayout/toggleOverlay',
          ),
        setMonitorView: (v) => set({ monitorView: v }, false, 'monitorLayout/setMonitorView'),
        setHudOpen: (v) => set({ hudOpen: v }, false, 'monitorLayout/setHudOpen'),
        setPlacesVisible: (v) => set({ placesVisible: v }, false, 'monitorLayout/setPlacesVisible'),
        setFocusMode: (v) => set({ focusMode: v }, false, 'monitorLayout/setFocusMode'),
        resetLayout: () => set({ ...DEFAULTS }, false, 'monitorLayout/reset'),
      }),
      {
        name: 'le.monitorLayout.v1',
        version: 1,
        partialize: (s) => ({
          inspectorPx: s.inspectorPx,
          inspectorOpen: s.inspectorOpen,
          mapBeside: s.mapBeside,
          mapFraction: s.mapFraction,
          deckPx: s.deckPx,
          deckOpen: s.deckOpen,
          deckTab: s.deckTab,
          overlays: s.overlays,
          hudOpen: s.hudOpen,
          placesVisible: s.placesVisible,
          monitorView: s.monitorView,
        }),
        merge: (persisted, current) => {
          const p = persisted as Partial<MonitorLayoutState> | undefined;
          if (!p || typeof p !== 'object') return current;
          const bool = (v: unknown, d: boolean): boolean => (typeof v === 'boolean' ? v : d);
          const o = (p.overlays ?? {}) as Partial<OverlayToggles>;
          return {
            ...current,
            inspectorPx: clamp(Number(p.inspectorPx), BOUNDS.inspectorPx, DEFAULTS.inspectorPx),
            inspectorOpen: bool(p.inspectorOpen, DEFAULTS.inspectorOpen),
            mapBeside: bool(p.mapBeside, DEFAULTS.mapBeside),
            mapFraction: clamp(Number(p.mapFraction), BOUNDS.mapFraction, DEFAULTS.mapFraction),
            deckPx: clamp(Number(p.deckPx), BOUNDS.deckPx, DEFAULTS.deckPx),
            deckOpen: bool(p.deckOpen, DEFAULTS.deckOpen),
            deckTab: p.deckTab && TABS.includes(p.deckTab) ? p.deckTab : DEFAULTS.deckTab,
            overlays: {
              boxes: bool(o.boxes, true),
              labels: bool(o.labels, true),
              tracks: bool(o.tracks, true),
              drift: bool(o.drift, true),
              hud: bool(o.hud, false),
              piBoxes: bool(o.piBoxes, true),
            },
            hudOpen: bool(p.hudOpen, DEFAULTS.hudOpen),
            placesVisible: bool(p.placesVisible, DEFAULTS.placesVisible),
            monitorView: p.monitorView === 'grid' ? 'grid' : 'globe',
            focusMode: false,
          };
        },
      },
    ),
    { name: 'monitorLayoutStore' },
  ),
);
