/**
 * `store/monitorSettingsStore.ts` — each camera's live-detection setup, remembered.
 *
 * ★ WHY IT EXISTS. The monitor's dials (model, lookup table, confidence, detail,
 *   tracker, classes) used to live in ONE set of session slots shared by every
 *   camera — walking from camera A to camera B carried A's setup along, and a
 *   reload lost both. An operator with ten cameras was re-entering ten setups
 *   every morning. This store keys the setup BY CAMERA and persists it
 *   (`le.monitorSettings.v1`), so re-entering a camera finds it ready to start.
 *
 * ★ WHAT IS SAVED IS WHAT WAS APPLIED. The page writes here on Apply/Start — never
 *   on every keystroke — so what comes back tomorrow is the setup that actually
 *   ran, not an abandoned half-edit.
 *
 * ★ VALIDATING MERGE, like every persisted store here: a corrupt entry is dropped
 *   and counted, never allowed to crash the boot or feed NaN into a slider.
 */

import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';

/** The raw dials, exactly as the page snapshots them on Apply. */
export interface SavedMonitorSettings {
  model: string;
  lutSite: string;
  classes: number[];
  /** 0 < conf ≤ 1. */
  conf: number;
  /** The CHOICE, not the resolved size — null means "the device default". */
  imgszChoice: number | null;
  trackerStart: number;
  trackerType: string;
  /** Opt-in ground-contact correction (1.3). Old entries lack it → false. */
  centreMarks: boolean;
  /** Steady boxes — smooth/debounce the overlay. Old entries lack it → true. */
  steadyBoxes: boolean;
  /** ★ Marks per second, per object (2026-09-11). 0 = one per frame. OPTIONAL:
   *  a setup saved before this existed has no opinion, and gets the default. */
  markRateHz?: number;
  /** ISO — when the operator last applied this setup. */
  savedAt: string;
}

/** Re-judge one persisted entry — anything off-shape is dropped, never repaired. */
export function reviveSettings(raw: unknown): SavedMonitorSettings | null {
  if (!raw || typeof raw !== 'object') return null;
  const r = raw as Record<string, unknown>;
  if (typeof r.model !== 'string' || typeof r.lutSite !== 'string') return null;
  if (typeof r.trackerType !== 'string' || r.trackerType.trim() === '') return null;
  if (typeof r.conf !== 'number' || !Number.isFinite(r.conf) || r.conf <= 0 || r.conf > 1)
    return null;
  const imgszChoice =
    r.imgszChoice === null
      ? null
      : typeof r.imgszChoice === 'number' && Number.isFinite(r.imgszChoice)
        ? r.imgszChoice
        : undefined;
  if (imgszChoice === undefined) return null;
  if (
    typeof r.trackerStart !== 'number' ||
    !Number.isFinite(r.trackerStart) ||
    r.trackerStart < 0
  )
    return null;
  if (!Array.isArray(r.classes) || !r.classes.every((c) => typeof c === 'number')) return null;
  const savedAt =
    typeof r.savedAt === 'string' && !Number.isNaN(Date.parse(r.savedAt))
      ? r.savedAt
      : new Date(0).toISOString();
  return {
    model: r.model,
    lutSite: r.lutSite,
    classes: r.classes,
    conf: r.conf,
    imgszChoice,
    trackerStart: Math.round(r.trackerStart),
    trackerType: r.trackerType,
    centreMarks: r.centreMarks === true,
    // Default ON: only an explicit false (the operator turned it off) survives.
    steadyBoxes: r.steadyBoxes !== false,
    savedAt,
  };
}

export interface MonitorSettingsState {
  /** Keyed by camera id (the server's UUID since 1.3; a ULID before). */
  byCamera: Record<string, SavedMonitorSettings>;

  save: (cameraId: string, settings: Omit<SavedMonitorSettings, 'savedAt'>) => void;
  /** Called when a camera leaves the registry — its setup goes with it. */
  forget: (cameraId: string) => void;
  /** The one-time 1.3 migration: a camera's setup follows it from its browser
   *  ULID to its server UUID, so nothing is re-entered. No-op when unknown. */
  rekey: (fromId: string, toId: string) => void;
}

export const useMonitorSettingsStore = create<MonitorSettingsState>()(
  devtools(
    persist(
      (set) => ({
        byCamera: {},

        save: (cameraId, settings) =>
          set(
            (s) => ({
              byCamera: {
                ...s.byCamera,
                [cameraId]: { ...settings, savedAt: new Date().toISOString() },
              },
            }),
            false,
            'monitorSettings/save',
          ),

        forget: (cameraId) =>
          set(
            (s) => {
              if (!(cameraId in s.byCamera)) return s;
              const byCamera = { ...s.byCamera };
              delete byCamera[cameraId];
              return { byCamera };
            },
            false,
            'monitorSettings/forget',
          ),

        rekey: (fromId, toId) =>
          set(
            (s) => {
              if (fromId === toId || !(fromId in s.byCamera)) return s;
              const byCamera = { ...s.byCamera };
              byCamera[toId] = byCamera[fromId];
              delete byCamera[fromId];
              return { byCamera };
            },
            false,
            'monitorSettings/rekey',
          ),
      }),
      {
        name: 'le.monitorSettings.v1',
        version: 1,
        partialize: (s) => ({ byCamera: s.byCamera }),
        merge: (persisted, current) => {
          const raw = (persisted as { byCamera?: unknown } | undefined)?.byCamera;
          if (!raw || typeof raw !== 'object') return current;
          const byCamera: Record<string, SavedMonitorSettings> = {};
          let dropped = 0;
          for (const [id, entry] of Object.entries(raw as Record<string, unknown>)) {
            const revived = reviveSettings(entry);
            if (revived === null) {
              dropped += 1;
              continue;
            }
            byCamera[id] = revived;
          }
          if (dropped > 0) {
            // eslint-disable-next-line no-console
            console.warn(`monitor settings: dropped ${dropped} corrupt entr(y/ies) on load`);
          }
          return { ...current, byCamera };
        },
      },
    ),
    { name: 'monitorSettingsStore' },
  ),
);

export const selectSettingsFor =
  (cameraId: string) =>
  (s: MonitorSettingsState): SavedMonitorSettings | undefined =>
    s.byCamera[cameraId];
