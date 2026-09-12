/**
 * `image/LivePredictController.tsx` — the engine behind LIVE cursor prediction (1.2.6).
 *
 * ★ Headless. Mounted in the photo pane, it watches the viewer's cursor (ORIGINAL image
 *   px, from `viewerStore.cursorImagePos`) and, while the live-predict mode is on, asks
 *   the auto-GCP locator where that pixel lands on the ground — writing the answer to
 *   `predictionStore` for the map's `PredictionLayer` to draw. No correspondence is
 *   opened and nothing is ever committed: this is a look-only aid.
 *
 * ★ THROTTLED, and it calls `imageCameraApi.estimate` DIRECTLY rather than through
 *   `useEstimateFromPixel`. The hook toasts pose warnings once per photo — right for the
 *   commit flow, wrong for a hover that fires many times a second. A stale-response guard
 *   (`seqRef`) means only the newest estimate wins, so a slow reply for an old pixel can
 *   never overwrite a fresh one. A ray that misses the terrain (sky, off-DEM) clears the
 *   ghost instead of raising an error on every hover.
 */

import { useEffect, useRef } from 'react';

import { imageCameraApi } from '../../api/imageCamera';
import { usePredictionStore } from '../../store/predictionStore';
import { useViewerStore } from '../../store/viewerStore';
import { GCP_REVEAL_ZOOM, useMapStore } from '../../store/mapStore';
import type { Uuid } from '../../types/common';

/** Minimum gap between estimate calls while the cursor moves. */
const THROTTLE_MS = 150;

/**
 * ★ THE MAP FOLLOWS THE CURSOR (field request): each accepted estimate re-centres
 *   the satellite pane on the predicted ground point, zooming IN to the GCP reveal
 *   zoom if the map was wider — never zooming a deliberately close view back out.
 *   `setView`'s epsilon guard makes a stationary cursor a no-op, and the throttle
 *   above already paces this to a walkable rhythm.
 */
function followPrediction(lat: number, lon: number): void {
  const map = useMapStore.getState();
  map.setView(
    { center: { lat, lon }, zoom: Math.max(map.view.zoom, GCP_REVEAL_ZOOM), bounds: null },
    'table',
  );
}

export function LivePredictController({ imageId }: { imageId: Uuid }): null {
  const active = usePredictionStore((s) => s.active);
  const setPrediction = usePredictionStore((s) => s.setPrediction);
  const setPending = usePredictionStore((s) => s.setPending);
  const cursor = useViewerStore((s) => s.cursorImagePos);

  const seqRef = useRef(0);
  const lastRunRef = useRef(0);
  const timerRef = useRef<number | null>(null);
  const cursorRef = useRef(cursor);
  cursorRef.current = cursor;

  useEffect(() => {
    if (!active) return;
    if (!cursor) {
      // Cursor left the photo → drop the ghost marker.
      setPrediction(null);
      return;
    }

    const run = (): void => {
      lastRunRef.current = Date.now();
      const c = cursorRef.current;
      if (!c) return;
      const mySeq = ++seqRef.current;
      setPending(true);
      imageCameraApi
        .estimate(imageId, { u: c.x, v: c.y })
        .then((r) => {
          if (mySeq === seqRef.current) {
            setPrediction({ lat: r.lat, lon: r.lon });
            followPrediction(r.lat, r.lon);
          }
        })
        .catch(() => {
          if (mySeq === seqRef.current) setPrediction(null);
        })
        .finally(() => {
          if (mySeq === seqRef.current) setPending(false);
        });
    };

    const elapsed = Date.now() - lastRunRef.current;
    if (elapsed >= THROTTLE_MS) {
      run();
    } else {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
      timerRef.current = window.setTimeout(run, THROTTLE_MS - elapsed);
    }

    return () => {
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [active, cursor, imageId, setPrediction, setPending]);

  // A late response must never write after teardown (image change / unmount).
  useEffect(
    () => () => {
      seqRef.current += 1;
    },
    [],
  );

  return null;
}

export default LivePredictController;
