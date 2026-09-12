/**
 * `autoCacheStore` — automatic viewport caching UI state.
 *
 * ★ The BACKEND owns the queue, limits and session; this store holds only what the map
 *   chrome renders: the user's on/off preference (persisted — a surveyor who turned
 *   background downloads off must stay off across reloads), the latest status the
 *   backend returned, and the browser's own online flag.
 *
 * ★ `enabled` here is the USER's toggle. The effective state also honours the server's
 *   `LE_IMAGERY_AUTO_CACHE_ENABLED` — the reporter simply never posts when this is off,
 *   and the PUT keeps the backend's runtime flag in sync so its workers stand down too.
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';

import type { AutoCacheStatus } from '../api/offline';

export interface AutoCacheState {
  /** The user's toggle (persisted). Default ON — conservative limits make ON safe. */
  enabled: boolean;
  /** Latest backend status; null before the first report. */
  status: AutoCacheStatus | null;
  /** `navigator.onLine`, kept live by the reporter's event listeners. */
  online: boolean;
  setEnabled: (enabled: boolean) => void;
  setStatus: (status: AutoCacheStatus | null) => void;
  setOnline: (online: boolean) => void;
}

export const useAutoCacheStore = create<AutoCacheState>()(
  persist(
    (set) => ({
      enabled: true,
      status: null,
      online: typeof navigator === 'undefined' ? true : navigator.onLine,
      setEnabled: (enabled) => set({ enabled }),
      setStatus: (status) => set({ status }),
      setOnline: (online) => set({ online }),
    }),
    {
      name: 'le-auto-cache',
      // Only the preference persists; status/online are live values.
      partialize: (s) => ({ enabled: s.enabled }),
    },
  ),
);
