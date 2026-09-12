/**
 * `projectSettingsDraftStore` — the Project-settings form survives the DEM excursion.
 *
 * ★ SAME LESSON AS `imageSetupDraftStore` (1.2.6): "Process new DEM…" unmounts the
 *   page, and local state dies with it — a typed name/description was silently gone
 *   when the surveyor came back from processing. This session-scoped store mirrors
 *   the two fields while they are EDITABLE (a read-only visit plants no draft) and
 *   is cleared by every deliberate exit (save, cancel, skip), so only a mid-edit
 *   excursion leaves one behind. A present draft also re-opens the page UNLOCKED —
 *   the surveyor was editing when they left.
 *
 * ★ L7 — browser-only, in-memory: gone with the session, never persisted.
 */

import { create } from 'zustand';

export interface ProjectSettingsDraft {
  name: string;
  description: string;
}

interface ProjectSettingsDraftState {
  byKey: Record<string, ProjectSettingsDraft>;
  set: (key: string, draft: ProjectSettingsDraft) => void;
  clear: (key: string) => void;
}

export const useProjectSettingsDraftStore = create<ProjectSettingsDraftState>((set) => ({
  byKey: {},
  set: (key, draft) => set((s) => ({ byKey: { ...s.byKey, [key]: draft } })),
  clear: (key) =>
    set((s) => {
      if (!(key in s.byKey)) return s;
      const next = { ...s.byKey };
      delete next[key];
      return { byKey: next };
    }),
}));
