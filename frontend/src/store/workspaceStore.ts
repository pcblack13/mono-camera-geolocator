/**
 * `workspaceStore` — CONTRACT.md §8.5 / 50-frontend.md §3.4.
 *
 * Owns: `paneSizes` · `inspectorOpen` · `dockOpen` · `activeTab` · `versionDrawerOpen`
 * · `coordinateFormat`.
 *
 * ★ **Persisted IN FULL, `version: 1`, with a validating `merge` that discards
 *   unknown shapes** (§8.5). This is the one store where the whole state is a
 *   preference: where the surveyor put the splitter is theirs, and it should survive
 *   a reload.
 */

import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';

import type { CoordinateFormat } from '../types/common';
import { SUGGESTION_DEFAULT } from '../theme/dataColors';

export type WorkspaceTab = 'image' | 'map' | 'points';

export interface PaneSizes {
  /** Flexible, fractional. */
  imageFr: number;
  mapFr: number;
  /** Fixed, CSS px. */
  inspectorPx: number;
  dockPx: number;
}

export interface WorkspaceState {
  paneSizes: PaneSizes;
  inspectorOpen: boolean;
  dockOpen: boolean;
  activeTab: WorkspaceTab;
  versionDrawerOpen: boolean;
  /** ★ How coordinates render (`lib/geo/format.ts`). Persisted, so `utm` must work. */
  coordinateFormat: CoordinateFormat;
  /**
   * ★ How many regions the accuracy loop should rank for the next control point.
   *   A preference, so it persists: a surveyor who wants one instruction rather than a
   *   menu of four wants that on every photograph, not once.
   */
  suggestionLimit: number;
  /**
   * ★ The nine range zones drawn on the photograph after a measurement, and how
   *   strongly. On by default: the measurement exists to be looked at, and the frame
   *   is where the surveyor is looking. Opacity is a preference — a surveyor placing
   *   points wants a faint tint, one reading a result wants a strong one.
   */
  zoneOverlay: boolean;
  /** Fill opacity, 0–100. Upstream's default is 45. */
  zoneOpacity: number;
  /**
   * ★ Does the accuracy loop measure BY ITSELF after every control point?
   *
   *   Default OFF, deliberately. Measuring spends a satellite mosaic and minutes of
   *   compute, and the loop used to start one the moment a project with four points
   *   was OPENED — work the surveyor never asked for, on a photograph they may have
   *   opened only to look at. With this off nothing measures until the Measure button
   *   is pressed; with it on the old per-point cycle returns for surveys that want it.
   */
  autoMeasure: boolean;
  /**
   * ★ "Reduce animation" as a SETTING, not only an OS preference: field laptops
   *   are not all fast, and the machine's owner is not always the OS account's.
   *   tokens.css collapses every duration to 0ms when the document carries
   *   `data-reduce-motion` — this flag is what stamps it.
   */
  reduceMotion: boolean;
  /**
   * ★ FOCUS MODE (Phase 4): one pane fills the workspace, the other rides in a
   *   picture-in-picture corner. TRANSIENT by design — a reload restores the full
   *   layout, because arriving into a maximised pane with no memory of choosing it
   *   reads as a broken workspace, not a preference.
   */
  focusPane: 'image' | 'map' | null;
  /** Photo left / map right by default; true mirrors the two. Persisted. */
  panesSwapped: boolean;
  /** The colour of the suggestion boxes on the photograph. */
  suggestionColor: string;
  /**
   * ★ NAMED BY SURFACE, not by data model (2026-08-20). These were `landmarkColor`
   *   and `gcpColor`, which meant "an annotation with no GCP" and "an annotation with
   *   one" — a distinction the code cares about and nobody else does. A surveyor says
   *   "the points on the photo" and "the points on the map", so that is what these
   *   are: one colour per SURFACE, each covering every mark drawn there.
   *
   *   NULL — the default — keeps the meaningful colouring: a control point's colour
   *   IS its confidence band (green high → red unreliable), so a flat colour trades
   *   an accuracy reading for legibility. Offered explicitly, never silently: the
   *   control says which of the two is in force, and the band's glyph and dash
   *   pattern keep encoding it either way ("never colour alone").
   */
  photoMarkColor: string | null;
  mapMarkColor: string | null;
  /**
   * ★ ONE POINT, ONE COLOUR — overriding both of the above for a single mark.
   *
   *   Keyed by GCP id where the mark HAS one, so colouring a point colours it on the
   *   photograph AND the map: it is one physical thing seen from two sides, and a
   *   surveyor who marks it red to find it again means both. Plain landmarks key by
   *   their annotation id.
   *
   *   Kept with the workspace, i.e. on THIS computer — it is a way of seeing, not
   *   survey data, so it does not travel with the project or into an export.
   */
  pointColors: Record<string, string>;

  setPaneSizes: (p: Partial<PaneSizes>) => void;
  resetPaneSizes: () => void;
  toggleInspector: () => void;
  toggleDock: () => void;
  setActiveTab: (t: WorkspaceTab) => void;
  setVersionDrawerOpen: (v: boolean) => void;
  setCoordinateFormat: (f: CoordinateFormat) => void;
  setSuggestionLimit: (n: number) => void;
  setZoneOverlay: (v: boolean) => void;
  setZoneOpacity: (n: number) => void;
  setAutoMeasure: (v: boolean) => void;
  setReduceMotion: (v: boolean) => void;
  setFocusPane: (p: 'image' | 'map' | null) => void;
  toggleSwapPanes: () => void;
  setSuggestionColor: (c: string) => void;
  setPhotoMarkColor: (c: string | null) => void;
  setMapMarkColor: (c: string | null) => void;
  /** `null` clears this point's own colour and returns it to the surface's. */
  setPointColor: (id: string, c: string | null) => void;
  resetMarkerColors: () => void;
}

const DEFAULT_PANE_SIZES: PaneSizes = { imageFr: 1, mapFr: 1, inspectorPx: 280, dockPx: 240 };

const DEFAULTS = {
  paneSizes: DEFAULT_PANE_SIZES,
  inspectorOpen: true,
  dockOpen: true,
  activeTab: 'image' as WorkspaceTab,
  versionDrawerOpen: false,
  coordinateFormat: 'dd' as CoordinateFormat,
  suggestionLimit: 1,
  zoneOverlay: true,
  zoneOpacity: 45,
  autoMeasure: false,
  reduceMotion: false,
  focusPane: null as 'image' | 'map' | null,
  panesSwapped: false,
  // The magenta the suggestion layer was born with — deliberately unlike any
  // confidence colour or correspondence marker.
  suggestionColor: SUGGESTION_DEFAULT,
  photoMarkColor: null,
  mapMarkColor: null,
  pointColors: {} as Record<string, string>,
};

/** `#rgb` / `#rrggbb`, the only shapes every surface here can parse (Konva, Leaflet
 *  divIcon HTML, MapLibre paint, and `hexToRgba` for the polygon fills). */
const HEX = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;
const hexOr = (v: unknown, fallback: string): string =>
  typeof v === 'string' && HEX.test(v) ? v : fallback;
const hexOrNull = (v: unknown): string | null => (typeof v === 'string' && HEX.test(v) ? v : null);

/**
 * ★ Bounds, applied on write AND on rehydrate.
 *
 *   A persisted `inspectorPx: 0` from a mis-drag — or a payload hand-edited in
 *   devtools — would restore a workspace with an invisible inspector and no way to
 *   get it back, and the user would reasonably conclude the app is broken. Clamping
 *   is cheap; a wedged layout is a support ticket.
 */
const PANE_BOUNDS = {
  imageFr: [0.2, 5] as const,
  mapFr: [0.2, 5] as const,
  inspectorPx: [200, 640] as const,
  dockPx: [120, 720] as const,
};

const clampNum = (v: number, lo: number, hi: number): number => (v < lo ? lo : v > hi ? hi : v);

function clampPaneSizes(p: Partial<PaneSizes> | undefined): PaneSizes {
  const src = { ...DEFAULT_PANE_SIZES, ...(p ?? {}) };
  const pick = (k: keyof PaneSizes): number => {
    const v = src[k];
    const [lo, hi] = PANE_BOUNDS[k];
    return Number.isFinite(v) ? clampNum(v, lo, hi) : DEFAULT_PANE_SIZES[k];
  };
  return {
    imageFr: pick('imageFr'),
    mapFr: pick('mapFr'),
    inspectorPx: pick('inspectorPx'),
    dockPx: pick('dockPx'),
  };
}

const TABS: WorkspaceTab[] = ['image', 'map', 'points'];
const FORMATS: CoordinateFormat[] = ['dd', 'dms', 'utm'];

export const useWorkspaceStore = create<WorkspaceState>()(
  devtools(
    persist(
      (set) => ({
        ...DEFAULTS,

        setPaneSizes: (p) =>
          set(
            (s) => ({ paneSizes: clampPaneSizes({ ...s.paneSizes, ...p }) }),
            false,
            'workspace/setPaneSizes',
          ),

        resetPaneSizes: () =>
          set({ paneSizes: DEFAULT_PANE_SIZES }, false, 'workspace/resetPaneSizes'),

        toggleInspector: () =>
          set((s) => ({ inspectorOpen: !s.inspectorOpen }), false, 'workspace/toggleInspector'),
        toggleDock: () => set((s) => ({ dockOpen: !s.dockOpen }), false, 'workspace/toggleDock'),
        setActiveTab: (t) => set({ activeTab: t }, false, 'workspace/setActiveTab'),
        setVersionDrawerOpen: (v) =>
          set({ versionDrawerOpen: v }, false, 'workspace/setVersionDrawerOpen'),
        setCoordinateFormat: (f) =>
          set({ coordinateFormat: f }, false, 'workspace/setCoordinateFormat'),
        // Clamped on write as well as on rehydrate — the core refuses anything outside
        // 1..8, and a stored 0 would ask for a suggestion run that returns nothing.
        setSuggestionLimit: (n) =>
          set(
            { suggestionLimit: clampNum(Math.round(n), 1, 8) },
            false,
            'workspace/setSuggestionLimit',
          ),
        setZoneOverlay: (v) => set({ zoneOverlay: v }, false, 'workspace/setZoneOverlay'),
        setZoneOpacity: (n) =>
          set({ zoneOpacity: clampNum(Math.round(n), 0, 100) }, false, 'workspace/setZoneOpacity'),
        setAutoMeasure: (v) => set({ autoMeasure: v }, false, 'workspace/setAutoMeasure'),
        setReduceMotion: (v) => set({ reduceMotion: v }, false, 'workspace/setReduceMotion'),
        setFocusPane: (p) => set({ focusPane: p }, false, 'workspace/setFocusPane'),
        toggleSwapPanes: () =>
          set((s) => ({ panesSwapped: !s.panesSwapped }), false, 'workspace/toggleSwapPanes'),
        // Validated on write as well as on rehydrate: a colour that no renderer can
        // parse is an invisible marker, which reads as data loss rather than a style.
        setSuggestionColor: (c) =>
          set(
            { suggestionColor: hexOr(c, DEFAULTS.suggestionColor) },
            false,
            'workspace/setSuggestionColor',
          ),
        setPhotoMarkColor: (c) =>
          set(
            { photoMarkColor: c === null ? null : hexOrNull(c) },
            false,
            'workspace/setPhotoMarkColor',
          ),
        setMapMarkColor: (c) =>
          set(
            { mapMarkColor: c === null ? null : hexOrNull(c) },
            false,
            'workspace/setMapMarkColor',
          ),
        setPointColor: (id, c) =>
          set(
            (st) => {
              const next = { ...st.pointColors };
              const valid = c === null ? null : hexOrNull(c);
              // Clearing DELETES the key rather than storing null — the map is a set
              // of overrides, and an entry that means "no override" is a slow leak.
              if (valid === null) delete next[id];
              else next[id] = valid;
              return { pointColors: next };
            },
            false,
            'workspace/setPointColor',
          ),
        resetMarkerColors: () =>
          set(
            {
              suggestionColor: DEFAULTS.suggestionColor,
              photoMarkColor: DEFAULTS.photoMarkColor,
              mapMarkColor: DEFAULTS.mapMarkColor,
              pointColors: {},
            },
            false,
            'workspace/resetMarkerColors',
          ),
      }),
      {
        name: 'landexplorer.workspace',
        version: 1,
        // ★ The validating merge §8.5 mandates. Every field is checked against its
        //   domain and falls back to the default — never trusted because it parsed.
        merge: (persisted, current) => {
          const p = persisted as Partial<WorkspaceState> | undefined;
          if (!p || typeof p !== 'object') return current;
          return {
            ...current,
            paneSizes: clampPaneSizes(p.paneSizes),
            inspectorOpen:
              typeof p.inspectorOpen === 'boolean' ? p.inspectorOpen : DEFAULTS.inspectorOpen,
            dockOpen: typeof p.dockOpen === 'boolean' ? p.dockOpen : DEFAULTS.dockOpen,
            activeTab: p.activeTab && TABS.includes(p.activeTab) ? p.activeTab : DEFAULTS.activeTab,
            // ★ Deliberately NOT restored: a drawer that reopens on every load is
            //   noise, and it is a transient inspection surface, not a preference.
            versionDrawerOpen: false,
            coordinateFormat:
              p.coordinateFormat && FORMATS.includes(p.coordinateFormat)
                ? p.coordinateFormat
                : DEFAULTS.coordinateFormat,
            suggestionLimit:
              typeof p.suggestionLimit === 'number' && Number.isFinite(p.suggestionLimit)
                ? clampNum(Math.round(p.suggestionLimit), 1, 8)
                : DEFAULTS.suggestionLimit,
            zoneOverlay: typeof p.zoneOverlay === 'boolean' ? p.zoneOverlay : DEFAULTS.zoneOverlay,
            zoneOpacity:
              typeof p.zoneOpacity === 'number' && Number.isFinite(p.zoneOpacity)
                ? clampNum(Math.round(p.zoneOpacity), 0, 100)
                : DEFAULTS.zoneOpacity,
            autoMeasure: typeof p.autoMeasure === 'boolean' ? p.autoMeasure : DEFAULTS.autoMeasure,
            reduceMotion:
              typeof p.reduceMotion === 'boolean' ? p.reduceMotion : DEFAULTS.reduceMotion,
            // ★ Deliberately NOT restored — see the field's own note.
            focusPane: null,
            panesSwapped:
              typeof p.panesSwapped === 'boolean' ? p.panesSwapped : DEFAULTS.panesSwapped,
            suggestionColor: hexOr(p.suggestionColor, DEFAULTS.suggestionColor),
            photoMarkColor: hexOrNull(p.photoMarkColor),
            mapMarkColor: hexOrNull(p.mapMarkColor),
            // Every stored override re-validated: one unpaintable value would draw
            // an invisible point, which reads as a LOST point.
            pointColors: Object.fromEntries(
              Object.entries((p.pointColors ?? {}) as Record<string, unknown>).flatMap(
                ([id, c]) => {
                  const hex = hexOrNull(c);
                  return hex === null ? [] : [[id, hex] as const];
                },
              ),
            ),
          };
        },
      },
    ),
    { name: 'workspaceStore' },
  ),
);
