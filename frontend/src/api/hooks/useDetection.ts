/**
 * Live detection over the stream the panel is already playing.
 *
 * ★ ONE HOOK OWNS THE LIFECYCLE. The session lives server-side; this polls its
 *   status while it runs (the overlay wants ~2 Hz, and the boxes ride in the status
 *   payload) and accumulates marks INCREMENTALLY via the `since` cursor — a session
 *   that has placed thousands of marks must not re-send them all every second.
 *
 * ★ Stopping the session on unmount is deliberate: detection holds the camera and
 *   burns CPU on every frame. A run nobody is watching is cost without a customer —
 *   unlike a measurement, its value IS the live view.
 *
 * ★ …BUT NOT ON A REMOUNT. Switching the language remounts the whole tree, and
 *   the old unmount-stop killed the run the surveyor was watching and threw away
 *   its marks (2026-08-28). The run's state now lives in surviving slots keyed by
 *   the page (`useSurvivingState`), and the stop is scheduled with a short GRACE:
 *   if the same page mounts again inside it — a language switch takes milliseconds
 *   — it reclaims the run and cancels the stop. Navigating away for real still
 *   stops the run, just a second and a half later.
 */

import { useCallback, useEffect, useRef } from 'react';
import { useMutation, useQuery, type UseQueryResult } from '@tanstack/react-query';

import {
  detectionApi,
  type DetectionAvailability,
  type DetectionMark,
  type DetectionSession,
  type DetectionStartRequest,
} from '../detection';
import { qk } from '../queryKeys';
import { openEffectScope } from '../../lib/async';
import { peekSurvivingState, setSurvivingState, useSurvivingState } from '../../lib/survivingState';
import { ApiError } from '../../types/common';

const POLL_MS = 500;
/** How long an unmounted run waits to be reclaimed before it is stopped. */
const STOP_GRACE_MS = 1500;
/** Which page owns a run — each has its own surviving slots and its own grace timer. */
export type DetectionPageKey = 'video' | 'live';
const pendingStops = new Map<DetectionPageKey, number>();

export function useDetectionAvailability(): UseQueryResult<DetectionAvailability> {
  return useQuery({
    queryKey: qk.detection.availability(),
    queryFn: ({ signal }) => detectionApi.availability(signal),
    // The answer changes only when someone installs packages or copies weights —
    // not something to re-ask on every focus.
    staleTime: 60_000,
  });
}

export interface LiveDetection {
  session: DetectionSession | null;
  marks: DetectionMark[];
  starting: boolean;
  startError: string | null;
  start: (body: DetectionStartRequest) => void;
  stop: () => void;
  /** ★ Take over a session started ELSEWHERE (the wall, another window) — or
   *  null to let go of a tracked session that belongs to a different camera
   *  (the run keeps running; only this page's view of it changes). */
  adopt: (session: DetectionSession | null) => void;
  /** File runs only — holds between frames; the next poll reflects `paused`. */
  setPaused: (paused: boolean) => void;
  /** ★ Manual tracking (2026-09-03). Turn the tracker on/off; click an object to
   *  track/untrack it (media pixels); double-click / lock=true promotes it to the
   *  highlighted primary; setLock sets/clears the primary by id. */
  setTracking: (on: boolean) => void;
  trackAt: (u: number, v: number, lock?: boolean) => void;
  setLock: (trackId: number | null) => void;
  /** ★ Track what the operator DREW (2026-09-11): a box in media pixels, any object. */
  trackBox: (box: { x1: number; y1: number; x2: number; y2: number }, name?: string) => void;
  /** ★ Name a track — "#3" → "white pickup". Empty clears. */
  nameTrack: (trackId: number, name: string) => void;
}

export function useLiveDetection(page: DetectionPageKey = 'live'): LiveDetection {
  const [session, setSession] = useSurvivingState<DetectionSession | null>(
    `detection.${page}.session`,
    null,
  );
  const [marks, setMarks] = useSurvivingState<DetectionMark[]>(`detection.${page}.marks`, []);
  // The `since` cursor and the id the stop targets also survive — a reclaimed run
  // must continue appending marks from where it was, not re-fetch them all.
  const cursorKey = `detection.${page}.cursor`;
  const idKey = `detection.${page}.sessionId`;
  const cursor = useRef(peekSurvivingState(cursorKey, 0));
  const setCursor = (n: number): void => {
    cursor.current = n;
    setSurvivingState(cursorKey, n, 0);
  };

  // ★ Reclaim: a mount inside the grace window cancels the pending stop.
  useEffect(() => {
    const pending = pendingStops.get(page);
    if (pending !== undefined) {
      window.clearTimeout(pending);
      pendingStops.delete(page);
    }
  }, [page]);

  const startMutation = useMutation({
    mutationFn: (body: DetectionStartRequest) => detectionApi.start(body),
    onSuccess: (created) => {
      setCursor(0);
      setMarks([]);
      setSession(created);
      setSurvivingState<string | null>(idKey, created.session_id, null);
    },
  });

  const adopt = useCallback(
    (adopted: DetectionSession | null): void => {
      setCursor(0);
      setMarks([]);
      setSession(adopted);
      setSurvivingState<string | null>(idKey, adopted?.session_id ?? null, null);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- setCursor is stable by construction
    [idKey, setMarks, setSession],
  );

  const stop = useCallback((): void => {
    const id = peekSurvivingState<string | null>(idKey, null);
    if (id !== null) void detectionApi.stop(id).catch(() => undefined);
    setSurvivingState<string | null>(idKey, null, null);
    // The session object is kept: its final counts and error are the run's result.
  }, [idKey]);

  const setPaused = useCallback(
    (paused: boolean): void => {
      const id = peekSurvivingState<string | null>(idKey, null);
      if (id === null) return;
      // The response carries the flipped flag; showing it immediately beats
      // waiting half a poll for the button to change face.
      void detectionApi
        .pause(id, paused)
        .then((fresh) => setSession(fresh))
        .catch(() => undefined);
    },
    [idKey, setSession],
  );

  const setTracking = useCallback(
    (on: boolean): void => {
      const id = peekSurvivingState<string | null>(idKey, null);
      if (id === null) return;
      void detectionApi
        .setTracking(id, on)
        .then((fresh) => setSession(fresh))
        .catch(() => undefined);
    },
    [idKey, setSession],
  );

  const trackAt = useCallback(
    (u: number, v: number, lock = false): void => {
      const id = peekSurvivingState<string | null>(idKey, null);
      if (id === null) return;
      // The click is applied a frame later, server-side; the poll reflects it.
      void detectionApi.track(id, { u, v, lock }).then(setSession).catch(() => undefined);
    },
    [idKey, setSession],
  );

  const trackBox = useCallback(
    (box: { x1: number; y1: number; x2: number; y2: number }, name?: string): void => {
      const id = peekSurvivingState<string | null>(idKey, null);
      if (id === null) return;
      void detectionApi
        .trackBox(id, { ...box, name: name ?? null })
        .then(setSession)
        .catch(() => undefined);
    },
    [idKey, setSession],
  );

  const nameTrack = useCallback(
    (trackId: number, name: string): void => {
      const id = peekSurvivingState<string | null>(idKey, null);
      if (id === null) return;
      void detectionApi.nameTrack(id, trackId, name).then(setSession).catch(() => undefined);
    },
    [idKey, setSession],
  );

  const setLock = useCallback(
    (trackId: number | null): void => {
      const id = peekSurvivingState<string | null>(idKey, null);
      if (id === null) return;
      void detectionApi.lock(id, trackId).then(setSession).catch(() => undefined);
    },
    [idKey, setSession],
  );

  // ── the poll ───────────────────────────────────────────────────────────────
  const active =
    session !== null && (session.status === 'starting' || session.status === 'running');
  useEffect(() => {
    if (!active || session === null) return undefined;
    const id = session.session_id;
    // ★ Three disciplines: a tick never overlaps a slow one (else the same mark
    //   batch is appended twice), a transient error is retried by the next tick
    //   (only a 404 — the session is gone — ends the run), and a response that
    //   lands after this effect closed (stop → start) is dropped, not adopted.
    const scope = openEffectScope();
    let inFlight = false;
    const timer = setInterval(() => {
      if (inFlight) return;
      inFlight = true;
      void (async () => {
        try {
          const fresh = await detectionApi.get(id, scope.signal);
          if (scope.cancelled || fresh.session_id !== id) return;
          setSession(fresh);
          if (fresh.marks_total > cursor.current) {
            const batch = await detectionApi.marks(id, cursor.current);
            if (scope.cancelled) return;
            setCursor(batch.next_index);
            if (batch.marks.length > 0) setMarks((old) => [...old, ...batch.marks]);
          }
        } catch (err) {
          if (scope.cancelled) return;
          // A vanished session (API restart) surfaces as 404 forever — stop asking.
          // Anything else (a timeout, a 502 from a busy encoder) is retried next tick.
          if (err instanceof ApiError && err.status === 404) {
            setSession((s) =>
              s === null || s.session_id !== id
                ? s
                : { ...s, status: 'failed', error: 'the session was lost (API restarted?)' },
            );
          }
        } finally {
          inFlight = false;
        }
      })();
    }, POLL_MS);
    return () => {
      clearInterval(timer);
      scope.close();
    };
  }, [active, session === null ? null : session.session_id]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── stop on unmount: an unwatched run is cost without a customer ───────────
  //    (after the grace — see the header; a remount reclaims it in time)
  useEffect(
    () => () => {
      const pending = pendingStops.get(page);
      if (pending !== undefined) window.clearTimeout(pending);
      pendingStops.set(
        page,
        window.setTimeout(() => {
          pendingStops.delete(page);
          stop();
        }, STOP_GRACE_MS),
      );
    },
    [page, stop],
  );

  return {
    session,
    marks,
    starting: startMutation.isPending,
    startError:
      startMutation.error == null
        ? null
        : startMutation.error instanceof Error
          ? startMutation.error.message
          : 'the session could not be started.',
    start: (body) => startMutation.mutate(body),
    adopt,
    stop,
    setPaused,
    setTracking,
    trackAt,
    setLock,
    trackBox,
    nameTrack,
  };
}
