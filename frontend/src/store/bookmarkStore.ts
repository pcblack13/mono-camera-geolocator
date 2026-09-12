/**
 * `store/bookmarkStore.ts` — which GCP tables the surveyor has starred.
 *
 * ★ A "GCP table" is one photograph's set of committed GCPs — the thing the editor's
 *   table pane shows and the exports serialize. Its identity is therefore the IMAGE id:
 *   one photograph, one table, whatever project it lives in.
 *
 * ★ CLIENT STATE ONLY (ADR-013): a bookmark is a reading aid, not survey data — it
 *   changes nothing about any coordinate and travels into no export. It persists per
 *   machine the same way the basemap choice does. If bookmarks ever need to follow the
 *   user across machines, that is the moment they become a backend column, not before.
 */

import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';

interface BookmarkState {
  /** Image ids of the bookmarked GCP tables. A record, so lookup is O(1). */
  byImage: Record<string, true>;
  toggle: (imageId: string) => void;
}

export const useBookmarkStore = create<BookmarkState>()(
  devtools(
    persist(
      (set) => ({
        byImage: {},

        toggle: (imageId) =>
          set(
            (s) => {
              const next = { ...s.byImage };
              if (next[imageId]) {
                delete next[imageId];
              } else {
                next[imageId] = true;
              }
              return { byImage: next };
            },
            false,
            'bookmarks/toggle',
          ),
      }),
      {
        name: 'landexplorer.gcpTableBookmarks',
        version: 1,
        partialize: (s) => ({ byImage: s.byImage }),
        /**
         * Rehydrated defensively, like every persisted store here: only string keys
         * mapping to `true` survive. A deleted image's stale id is harmless — it simply
         * never matches a row again.
         */
        merge: (persisted, current) => {
          const raw = (persisted as { byImage?: unknown } | undefined)?.byImage;
          const clean: Record<string, true> = {};
          if (raw && typeof raw === 'object') {
            for (const [id, value] of Object.entries(raw)) {
              if (value === true) clean[id] = true;
            }
          }
          return { ...current, byImage: clean };
        },
      },
    ),
    { name: 'gcpTableBookmarks' },
  ),
);
