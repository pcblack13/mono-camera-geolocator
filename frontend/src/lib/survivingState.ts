/**
 * `lib/survivingState.ts` — `useState` that outlives a remount.
 *
 * ★ WHY. Switching the app's language REMOUNTS the whole tree (`main.tsx` keys it
 *   by language — the honest way to make every plain `t()` re-read). A remount
 *   throws away every `useState` in the app, and on the detection pages that was
 *   the surveyor's WORK: the run they were watching, its marks, the settings they
 *   had dialled in (seen 2026-08-28: "when I change the language it refreshes the
 *   whole page and I lose my work"). A hard reload loses it too, and that one is
 *   fair — this keeps it across anything short of that.
 *
 * ★ HOW. The value lives in a module-level map keyed by a name the caller chooses,
 *   and the component subscribes to it. Same API as `useState`; the difference is
 *   that mounting again with the same key finds the value where it was left.
 *
 * ★ WHAT IT IS NOT. Not persistence (nothing reaches localStorage — a reload is a
 *   fresh start), and not a store for server data (that is React Query's). Use it
 *   for in-flight interaction state a remount must not destroy, and give each
 *   page its own key prefix so two pages never share a slot by accident.
 */

import { useCallback, useRef, useSyncExternalStore } from 'react';

type Listener = () => void;

const values = new Map<string, unknown>();
const listeners = new Map<string, Set<Listener>>();

function notify(key: string): void {
  for (const l of listeners.get(key) ?? []) l();
}

/** Read without subscribing — for callbacks that must see the latest value. */
export function peekSurvivingState<T>(key: string, initial: T): T {
  return values.has(key) ? (values.get(key) as T) : initial;
}

/** Write without a component — for cleanups that run after unmount. */
export function setSurvivingState<T>(key: string, next: T | ((prev: T) => T), initial: T): void {
  const prev = peekSurvivingState(key, initial);
  const value = typeof next === 'function' ? (next as (p: T) => T)(prev) : next;
  if (Object.is(value, prev) && values.has(key)) return;
  values.set(key, value);
  notify(key);
}

/** Forget every slot — tests, and nothing else. */
export function __resetSurvivingState(): void {
  values.clear();
  for (const key of listeners.keys()) notify(key);
}

/**
 * `useState`, keyed. `initial` is used only the first time a key is seen.
 *
 * ```ts
 * const [videoId, setVideoId] = useSurvivingState('detection.video.videoId', '');
 * ```
 */
export function useSurvivingState<T>(
  key: string,
  initial: T,
): [T, (next: T | ((prev: T) => T)) => void] {
  const subscribe = useCallback(
    (listener: Listener) => {
      let set = listeners.get(key);
      if (!set) {
        set = new Set();
        listeners.set(key, set);
      }
      set.add(listener);
      return () => {
        set.delete(listener);
      };
    },
    [key],
  );
  // `initial` may be an object literal — a fresh identity every render — so it is
  // read through a ref rather than made a dependency.
  const initialRef = useRef(initial);
  const get = useCallback(() => peekSurvivingState(key, initialRef.current), [key]);
  const value = useSyncExternalStore(subscribe, get, get);
  const set = useCallback(
    (next: T | ((prev: T) => T)) => setSurvivingState(key, next, initialRef.current),
    [key],
  );
  return [value, set];
}
