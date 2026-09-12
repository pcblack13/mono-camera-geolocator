/**
 * `store/liveSourcesStore.ts` — the operator's saved live-stream sources.
 *
 * ★ CLIENT STATE ONLY (ADR-013): a source is a bookmark to a camera (name + URL),
 *   not survey data — the server persists nothing about live sources. Captured
 *   FRAMES are the durable artefact, and they live in the capture library.
 */

import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';

export interface LiveSource {
  id: string;
  name: string;
  url: string;
}

interface LiveSourcesState {
  sources: LiveSource[];
  add: (name: string, url: string) => void;
  remove: (id: string) => void;
}

export const useLiveSourcesStore = create<LiveSourcesState>()(
  devtools(
    persist(
      (set) => ({
        sources: [],

        add: (name, url) =>
          set(
            (s) => ({
              sources: [
                ...s.sources,
                {
                  id: `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`,
                  name,
                  url,
                },
              ],
            }),
            false,
            'liveSources/add',
          ),

        remove: (id) =>
          set(
            (s) => ({ sources: s.sources.filter((x) => x.id !== id) }),
            false,
            'liveSources/remove',
          ),
      }),
      {
        name: 'landexplorer.liveSources',
        version: 1,
        partialize: (s) => ({ sources: s.sources }),
        /** Rehydrated defensively: only well-shaped {id,name,url} rows survive. */
        merge: (persisted, current) => {
          const raw = (persisted as { sources?: unknown } | undefined)?.sources;
          const clean: LiveSource[] = [];
          if (Array.isArray(raw)) {
            for (const v of raw) {
              const s = v as Partial<LiveSource> | null;
              if (
                s &&
                typeof s.id === 'string' &&
                typeof s.name === 'string' &&
                typeof s.url === 'string'
              ) {
                clean.push({ id: s.id, name: s.name, url: s.url });
              }
            }
          }
          return { ...current, sources: clean };
        },
      },
    ),
    { name: 'liveSources' },
  ),
);
