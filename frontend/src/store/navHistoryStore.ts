/**
 * `store/navHistoryStore.ts` — where the user actually came from.
 *
 * ★ WHY NOT `navigate(-1)`. The browser's own history is not a trail through THIS
 *   app: after a deep link it steps out of the app entirely, and it cannot tell you
 *   the NAME of what it would land on — so a button reading "Back to …" could not
 *   be written from it. This store keeps the app's own visit stack, which makes the
 *   destination both nameable and guaranteed to be inside the app.
 *
 * ★ WHY NOT THE STRUCTURAL PARENT (the previous behaviour). Every page's parent was
 *   Home, so arriving at the DEM page from the Workspace offered "Back to Home" —
 *   true to the hierarchy, useless as navigation. The structural parent survives as
 *   the FALLBACK for a cold entry (deep link, reload), where there is no previous
 *   page and "up" is the only honest answer.
 *
 * ★ The stack is a stack, not a log: revisiting the page below the top POPS rather
 *   than pushing, so A → B → back → B does not accumulate, and repeated
 *   back-presses walk out the way the user walked in.
 */

import { create } from 'zustand';

/** Deepest sensible trail; beyond this the oldest entries are dropped. */
const MAX_DEPTH = 20;

interface NavHistoryState {
  /**
   * Visited in-app locations, oldest first; the last entry is the CURRENT page.
   * ★ Each entry is `pathname + search`, not the pathname alone: `?tab=videos` is
   * WHICH PAGE the user was on (the Video editor, not Projects), so dropping it
   * sent them back to the wrong tab.
   */
  stack: string[];
  /** Record a navigation. Idempotent for the current path. */
  visit: (path: string) => void;
  /**
   * Record a REDIRECT — a `<Navigate replace>` — by overwriting the top entry.
   *
   * ★ THE TRAP THIS CLOSES. A redirect replaces the current page rather than
   * following it: the editor URL that instantly forwards to `/setup` was being
   * pushed as its own step, so "back" landed on it and was immediately redirected
   * forward again — the button looked dead. A replaced entry never becomes a
   * destination, which is exactly what `replace` means.
   */
  replaceVisit: (path: string) => void;
  /** The path to go back to, or null when this is the first page of the session. */
  previous: () => string | null;
}

export const useNavHistoryStore = create<NavHistoryState>()((set, get) => ({
  stack: [],
  visit: (path) =>
    set((state) => {
      const { stack } = state;
      const top = stack[stack.length - 1];
      if (top === path) return state; // same page (a re-render, or a query-only change)
      // ★ Going BACK: the user landed on the page below the top, so unwind instead
      //   of growing the trail — otherwise back-and-forth would build an infinite
      //   ping-pong the button could never walk out of.
      if (stack.length >= 2 && stack[stack.length - 2] === path) {
        return { stack: stack.slice(0, -1) };
      }
      const next = [...stack, path];
      return { stack: next.length > MAX_DEPTH ? next.slice(next.length - MAX_DEPTH) : next };
    }),
  replaceVisit: (path) =>
    set((state) => {
      const { stack } = state;
      if (stack.length === 0) return { stack: [path] };
      if (stack[stack.length - 1] === path) return state;
      return { stack: [...stack.slice(0, -1), path] };
    }),
  previous: () => {
    const { stack } = get();
    return stack.length >= 2 ? stack[stack.length - 2] : null;
  },
}));
