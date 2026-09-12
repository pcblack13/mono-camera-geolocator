/**
 * `lib/async.ts` — two small disciplines for in-flight requests.
 *
 * ★ LAST WRITER MUST BE THE LATEST CALLER. An imperative "refresh" fired twice
 *   (mount, then a fast Remove) can resolve out of order and resurrect what was
 *   just removed. A sequence number per call, checked before every state write,
 *   makes the newest call the only one allowed to speak.
 *
 * ★ AN EFFECT'S REQUEST DIES WITH THE EFFECT. Poll ticks and playback checks that
 *   outlive their effect paint the previous clip's answer over the next one.
 *   `AbortController` + a cancelled flag closes both doors.
 */

import { useRef } from 'react';

export interface RequestSequence {
  /** Claim a ticket for a new call. */
  next: () => number;
  /** Is this ticket still the newest? Check before every state write. */
  isCurrent: (ticket: number) => boolean;
}

export function createSequence(): RequestSequence {
  let current = 0;
  return {
    next: () => {
      current += 1;
      return current;
    },
    isCurrent: (ticket) => ticket === current,
  };
}

/** The sequence as a hook — stable across renders.
 *
 * ★ ONE OBJECT FOR THE COMPONENT'S LIFETIME (2026-09-02). The first version
 * returned a fresh ``{ next, isCurrent }`` literal every render; any callback
 * that listed the sequence in its deps changed identity every render, and an
 * effect keyed on that callback re-ran FOREVER — ProjectDemCard's DEM probe
 * looped, hammering ``GET /projects/{id}/dem`` with its loading bar animating
 * on an idle page. The ref below is the same object every time, so depending
 * on it is free.
 */
export function useRequestSequence(): RequestSequence {
  const seq = useRef<RequestSequence | null>(null);
  if (seq.current === null) seq.current = createSequence();
  return seq.current;
}

export interface EffectScope {
  signal: AbortSignal;
  /** True once the effect that opened this scope has cleaned up. */
  readonly cancelled: boolean;
  /** The cleanup to return from the effect. */
  close: () => void;
}

/**
 * One scope per effect run: pass `scope.signal` to every request, guard every
 * `setState` with `!scope.cancelled`, and `return scope.close`.
 */
export function openEffectScope(): EffectScope {
  const controller = new AbortController();
  let cancelled = false;
  return {
    signal: controller.signal,
    get cancelled() {
      return cancelled;
    },
    close: () => {
      cancelled = true;
      controller.abort();
    },
  };
}
