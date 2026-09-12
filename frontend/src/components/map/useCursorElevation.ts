/**
 * `map/useCursorElevation.ts` — the project DEM's answer under the map cursor.
 *
 * ★ **DEBOUNCED, AND THAT IS NOT AN OPTIMISATION.** A `mousemove` handler fires tens of
 *   times a second; sampling per event would put a raster read behind every pixel of
 *   pointer travel and saturate the API for a number nobody can read mid-motion. The
 *   sample is taken once the pointer has *settled*, which is also the only moment the
 *   figure means anything to the surveyor.
 *
 * ★ **THE STALE-RESPONSE GUARD IS THE LOAD-BEARING PART.** Two samples in flight can
 *   return out of order, and a readout showing the elevation of a point the cursor left
 *   two seconds ago is worse than showing nothing — it is a plausible wrong number
 *   attached to the wrong place, which is this codebase's defining failure mode. Every
 *   request carries a sequence number and a late answer is discarded, not rendered.
 *
 * ★ **`null` is rendered as a state, never as a blank.** `no_dem` and `no_data` are
 *   different answers with different fixes and both are distinguishable from `loading`.
 *   Collapsing them to an empty chip would leave a surveyor unable to tell "attach a DEM"
 *   from "this spot has no coverage".
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { elevationApi } from '../../api/elevation';
import type { Uuid } from '../../types/common';
import type { CursorElevation } from '../../types/elevation';

/**
 * How long the pointer must sit still before a sample is taken.
 *
 * ★ Long enough that a pan across the map costs one request rather than fifty; short
 * enough that a surveyor deliberately hovering a feature is not left waiting. 250 ms is
 * roughly the pause a hand makes when it stops to look at something.
 */
const SETTLE_MS = 250;

export interface UseCursorElevationResult {
  elevation: CursorElevation;
  /** Feed pointer positions in. `null` means the pointer left the map. */
  onCursorMove: (at: { lat: number; lon: number } | null) => void;
}

export function useCursorElevation(projectId: Uuid | null): UseCursorElevationResult {
  const [elevation, setElevation] = useState<CursorElevation>({ kind: 'idle' });

  const timer = useRef<number | null>(null);
  const abort = useRef<AbortController | null>(null);
  // ★ Monotonic request id. Only the newest response is allowed to reach the UI.
  const seq = useRef(0);

  const cancelPending = useCallback(() => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
    abort.current?.abort();
    abort.current = null;
  }, []);

  const onCursorMove = useCallback(
    (at: { lat: number; lon: number } | null) => {
      cancelPending();

      if (at === null || projectId === null) {
        // ★ Bump the sequence so any in-flight answer is already stale when it lands.
        seq.current += 1;
        setElevation({ kind: 'idle' });
        return;
      }

      const mine = ++seq.current;
      setElevation({ kind: 'loading' });

      timer.current = window.setTimeout(() => {
        const controller = new AbortController();
        abort.current = controller;

        void elevationApi
          .sample(projectId, [{ lat: at.lat, lon: at.lon }], controller.signal)
          .then((response) => {
            if (mine !== seq.current) return; // a newer sample won
            const first = response.results[0];

            if (!response.dem_attached) {
              setElevation({ kind: 'no_dem' });
              return;
            }
            if (first === undefined || first.elevation_m === null || first.source === null) {
              setElevation({ kind: 'no_data' });
              return;
            }
            setElevation({
              kind: 'value',
              elevation_m: first.elevation_m,
              source: first.source,
              vertical_ce90_m: first.vertical_ce90_m,
            });
          })
          .catch(() => {
            if (mine !== seq.current) return;
            // ★ A failed sample reports "no data", not a number. There is no cached
            //   previous value to fall back on and inventing one is out of the question.
            setElevation({ kind: 'no_data' });
          });
      }, SETTLE_MS);
    },
    [cancelPending, projectId],
  );

  // Leaving the component mid-hover must not leave a timer or a fetch behind.
  useEffect(() => cancelPending, [cancelPending]);

  return { elevation, onCursorMove };
}
