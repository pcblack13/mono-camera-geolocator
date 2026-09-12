/**
 * `store/projectSetupStore.ts` — per-project workspace configuration.
 *
 * ★ **The map is not deployed until the surveyor has said what it should be.** Opening a
 *   workspace used to drop straight onto a live Esri basemap: tiles fetched, a provider
 *   chosen for you, and no statement anywhere about where the Z on a control point would
 *   come from. Those are two decisions with real consequences — one is a licence and a
 *   network dependency, the other is the third coordinate of every GCP in the project —
 *   and they belong to the project, not to a global default.
 *
 * ★ **Per project, keyed by project id.** Two surveys on two sites have no business
 *   sharing a basemap choice or an elevation surface. `mapStore` keeps the app-wide
 *   default (L7: `providerId` is a user CHOICE); this keeps the per-project override and
 *   the "has been set up" flag.
 *
 * ★ **Client state only** (§ ADR-013: Zustand for UI, React Query for server data). The
 *   DEM itself lives on the server — this holds no copy of it, only the fact that the
 *   surveyor has been through the setup for this project. `GET /projects/{id}/dem` is
 *   the truth about the DEM and is read through React Query at the point of use.
 */

import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';

import type { BasemapKind } from '../types/geo';

/** Which imagery a project's workspace uses. */
export type MapSourceKind = 'mapbox' | 'esri' | 'google' | 'sentinel' | 'offline';

export interface ProjectSetup {
  /** True once the surveyor has completed (or explicitly skipped) setup. */
  configured: boolean;
  /** Imagery source for this project's map. */
  source: MapSourceKind;
  /** satellite | hybrid | terrain. */
  basemap: BasemapKind;
}

export const DEFAULT_SETUP: ProjectSetup = {
  configured: false,
  // ★ Mapbox stays the DEFAULT (the product's chosen imagery, built-in token), but
  //   Esri is back as an offered OPTION (1.2.6): keyless, always available, and the
  //   right answer when Mapbox is unreachable or its coverage is weak for a site.
  //   The workspace seeds the map ONLY when the server reports the choice usable and
  //   warns otherwise — an unusable choice degrades loudly, never blankly.
  source: 'mapbox',
  basemap: 'satellite',
};

interface ProjectSetupState {
  /** Keyed by project id. */
  byProject: Record<string, ProjectSetup>;
  get: (projectId: string) => ProjectSetup;
  set: (projectId: string, patch: Partial<ProjectSetup>) => void;
  /** Re-open setup for a project — the gear button in the map header. */
  reopen: (projectId: string) => void;
}

export const useProjectSetupStore = create<ProjectSetupState>()(
  devtools(
    persist(
      (set, get) => ({
        byProject: {},

        get: (projectId) => get().byProject[projectId] ?? DEFAULT_SETUP,

        set: (projectId, patch) =>
          set(
            (s) => ({
              byProject: {
                ...s.byProject,
                [projectId]: { ...(s.byProject[projectId] ?? DEFAULT_SETUP), ...patch },
              },
            }),
            false,
            'projectSetup/set',
          ),

        reopen: (projectId) =>
          set(
            (s) => ({
              byProject: {
                ...s.byProject,
                [projectId]: { ...(s.byProject[projectId] ?? DEFAULT_SETUP), configured: false },
              },
            }),
            false,
            'projectSetup/reopen',
          ),
      }),
      {
        name: 'landexplorer.projectSetup',
        version: 1,
        partialize: (s) => ({ byProject: s.byProject }),
        /**
         * ★ A persisted record is rehydrated defensively: a `source` this build no longer
         *   offers must not leave a project pointing at a provider that cannot load.
         *   Anything unrecognised falls back to the default rather than to a blank map
         *   with no explanation. (`'esri'` is a valid source again since 1.2.6 —
         *   records from the era it was banned simply resume working.)
         */
        merge: (persisted, current) => {
          const raw = (persisted as { byProject?: Record<string, unknown> } | undefined)?.byProject;
          const clean: Record<string, ProjectSetup> = {};
          if (raw && typeof raw === 'object') {
            for (const [id, value] of Object.entries(raw)) {
              const v = value as Partial<ProjectSetup> | null;
              if (!v || typeof v !== 'object') continue;
              clean[id] = {
                configured: v.configured === true,
                source:
                  v.source === 'google' ||
                  v.source === 'offline' ||
                  v.source === 'sentinel' ||
                  v.source === 'mapbox' ||
                  v.source === 'esri'
                    ? v.source
                    : DEFAULT_SETUP.source,
                basemap:
                  v.basemap === 'hybrid' || v.basemap === 'terrain' || v.basemap === 'satellite'
                    ? v.basemap
                    : DEFAULT_SETUP.basemap,
              };
            }
          }
          return { ...current, byProject: clean };
        },
      },
    ),
    { name: 'projectSetup' },
  ),
);
