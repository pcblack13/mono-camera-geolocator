/**
 * `hooks/useLivePredict.ts` — point at the live picture, read the ground (2026-09-10).
 *
 * ★ THE GCP EDITOR'S LIVE PREDICT, FOR THE STREAM. There the cursor asks the
 *   solved station where a photograph pixel lands; here it asks the camera's
 *   LOOKUP TABLE — the same table every detection is placed through — so what
 *   the operator points at and what a mark would say are one answer. Throttled,
 *   with a stale-response guard (only the newest pixel's answer is kept), and
 *   look-only: nothing is stored, nothing becomes a mark.
 *
 * ★ PIN, THEN COPY. "Copy the coordinates under the cursor" cannot be a button —
 *   moving to the button moves the cursor. So a click on the picture PINS the
 *   reading (the reticle and the readout freeze there), the Copy button and the
 *   `c` key copy whatever is showing, and a second click unpins.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { lutApi, type LutLookup } from '../api/lut';

/** Minimum gap between lookups while the cursor moves. */
// ★ 80 ms (was 120): the table lookup is a memory-mapped array read, and the map
//   reticle glides between readings, so a faster cadence is pure smoothness.
export const PREDICT_THROTTLE_MS = 80;

export interface LivePrediction {
  /** The media pixel asked about. */
  u: number;
  v: number;
  placed: boolean;
  lat: number | null;
  lon: number | null;
  elevationM: number | null;
  reason: LutLookup['reason'];
}

export interface PixelAsk {
  u: number;
  v: number;
  /** The media's size, so the table is read at the right cell. */
  w: number;
  h: number;
}

export interface LivePredict {
  /** The reading under the cursor (or the pinned one), or null. */
  prediction: LivePrediction | null;
  pinned: boolean;
  pending: boolean;
  /** The cursor moved to a media pixel. */
  cursor: (ask: PixelAsk) => void;
  /** The cursor left the picture. */
  leave: () => void;
  /** Pin the reading at this pixel; a pin on the pinned pixel unpins. */
  pin: (ask: PixelAsk) => void;
  unpin: () => void;
  /** "lat, lon, elevation" — what Copy puts on the clipboard; null with nothing placed. */
  copyText: string | null;
  /** Copies `copyText`; resolves with what was copied, or null when there was nothing. */
  copy: () => Promise<string | null>;
}

export function formatPrediction(p: LivePrediction | null): string | null {
  if (p === null || !p.placed || p.lat === null || p.lon === null) return null;
  const z = p.elevationM === null ? '' : `, ${p.elevationM.toFixed(1)}`;
  return `${p.lat.toFixed(6)}, ${p.lon.toFixed(6)}${z}`;
}

export function useLivePredict(opts: {
  enabled: boolean;
  lutSite: string;
  projectId: string | null;
}): LivePredict {
  const { enabled, lutSite, projectId } = opts;
  const [prediction, setPrediction] = useState<LivePrediction | null>(null);
  const [pinned, setPinned] = useState(false);
  const [pending, setPending] = useState(false);
  const seqRef = useRef(0);
  const lastRunRef = useRef(0);
  const timerRef = useRef<number | null>(null);
  const askRef = useRef<PixelAsk | null>(null);
  const pinnedRef = useRef(false);
  pinnedRef.current = pinned;

  const run = useCallback((): void => {
    const ask = askRef.current;
    if (ask === null || lutSite === '') return;
    lastRunRef.current = Date.now();
    const mySeq = ++seqRef.current;
    setPending(true);
    lutApi
      .lookup(lutSite, { u: ask.u, v: ask.v, w: ask.w, h: ask.h, projectId })
      .then((r) => {
        if (mySeq !== seqRef.current) return;
        setPrediction({
          u: ask.u,
          v: ask.v,
          placed: r.placed,
          lat: r.lat,
          lon: r.lon,
          elevationM: r.elevation_m,
          reason: r.reason,
        });
      })
      .catch(() => {
        if (mySeq === seqRef.current) setPrediction(null);
      })
      .finally(() => {
        if (mySeq === seqRef.current) setPending(false);
      });
  }, [lutSite, projectId]);

  const schedule = useCallback((): void => {
    const elapsed = Date.now() - lastRunRef.current;
    if (elapsed >= PREDICT_THROTTLE_MS) {
      run();
      return;
    }
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      run();
    }, PREDICT_THROTTLE_MS - elapsed);
  }, [run]);

  const cursor = useCallback(
    (ask: PixelAsk): void => {
      if (!enabled || pinnedRef.current) return;
      askRef.current = ask;
      schedule();
    },
    [enabled, schedule],
  );

  const leave = useCallback((): void => {
    if (pinnedRef.current) return;
    askRef.current = null;
    seqRef.current += 1; // a late answer for a pixel the cursor left is dropped
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    setPending(false);
    setPrediction(null);
  }, []);

  const unpin = useCallback((): void => {
    setPinned(false);
  }, []);

  const pin = useCallback(
    (ask: PixelAsk): void => {
      if (!enabled) return;
      if (pinnedRef.current) {
        setPinned(false);
        askRef.current = ask;
        run();
        return;
      }
      askRef.current = ask;
      setPinned(true);
      run(); // the pinned reading is asked once more, un-throttled, at the exact pixel
    },
    [enabled, run],
  );

  // Off → nothing survives: no reticle, no pin, no answer in flight.
  useEffect(() => {
    if (enabled) return;
    seqRef.current += 1;
    askRef.current = null;
    setPinned(false);
    setPending(false);
    setPrediction(null);
  }, [enabled]);

  useEffect(
    () => () => {
      seqRef.current += 1;
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    },
    [],
  );

  const copyText = formatPrediction(prediction);
  const copy = useCallback(async (): Promise<string | null> => {
    if (copyText === null) return null;
    try {
      await navigator.clipboard.writeText(copyText);
    } catch {
      return null;
    }
    return copyText;
  }, [copyText]);

  return { prediction, pinned, pending, cursor, leave, pin, unpin, copyText, copy };
}

export default useLivePredict;
