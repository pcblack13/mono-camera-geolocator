/**
 * `store/guideProgressStore.ts` — which steps of the workflow guide the surveyor has
 * ticked off.
 *
 * ★ A GUIDE THAT REMEMBERS. Ticking a step is the reader's own note ("done that"),
 *   not a fact about the project, so it lives here — browser-only, persisted, keyed
 *   by the step's TITLE (stable across reorderings) rather than its index.
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export interface GuideProgressState {
  done: string[];
  isDone: (title: string) => boolean;
  toggle: (title: string) => void;
  reset: () => void;
}

export const useGuideProgressStore = create<GuideProgressState>()(
  persist(
    (set, get) => ({
      done: [],
      isDone: (title) => get().done.includes(title),
      toggle: (title) =>
        set((s) => ({
          done: s.done.includes(title) ? s.done.filter((x) => x !== title) : [...s.done, title],
        })),
      reset: () => set({ done: [] }),
    }),
    {
      name: 'landexplorer.guideProgress',
      version: 1,
      partialize: (s) => ({ done: s.done }),
      merge: (persisted, current) => {
        const raw = (persisted as { done?: unknown } | undefined)?.done;
        const done = Array.isArray(raw)
          ? raw.filter((x): x is string => typeof x === 'string')
          : [];
        return { ...current, done };
      },
    },
  ),
);
