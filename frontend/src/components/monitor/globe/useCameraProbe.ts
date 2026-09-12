/**
 * `monitor/globe/useCameraProbe.ts` — a five-second look at ONE camera.
 *
 * ★ THE GLOBE MUST NOT OPEN A SOCKET PER CAMERA. Hovering a marker mounts a single
 *   `<img>` on the camera's preview URL (http MJPEG directly, everything else via
 *   the server's re-stream) for up to five seconds: the first frame → `live`, a load
 *   error → `lost`, five seconds of nothing → `lost`. Leaving the marker unmounts
 *   it. One probe at a time — a new hover cancels the old.
 *
 * ★ An `<img src>` is not a `fetch()` (§6), and it cannot read the server's
 *   refusal envelope — so a probe can say lost, never refused. The detail page,
 *   which reads the body, is the one that records `refused` with the message.
 */

import { useEffect, useRef } from 'react';

import { previewSrcForSource } from '../../../hooks/useLiveFeed';
import { useCameraRegistryStore } from '../../../store/cameraRegistryStore';

export const PROBE_MS = 5000;

export function useCameraProbe(hoveredId: string | null): void {
  const setStatus = useCameraRegistryStore((s) => s.setStatus);
  const source = useCameraRegistryStore((s) =>
    hoveredId === null ? undefined : s.cameras.find((c) => c.id === hoveredId)?.source,
  );
  const imgRef = useRef<HTMLImageElement | null>(null);

  useEffect(() => {
    if (hoveredId === null || source === undefined) return undefined;
    const id = hoveredId;
    setStatus(id, 'connecting');
    const img = new Image();
    imgRef.current = img;
    let settled = false;
    const settle = (state: 'live' | 'lost'): void => {
      if (settled) return;
      settled = true;
      setStatus(id, state);
    };
    img.onload = () => settle('live');
    img.onerror = () => settle('lost');
    const timer = window.setTimeout(() => settle('lost'), PROBE_MS);
    img.src = previewSrcForSource(source);
    return () => {
      window.clearTimeout(timer);
      // ★ Clearing `src` is what actually closes an MJPEG connection the browser
      //   would otherwise keep until garbage collection (see live/StreamImage).
      img.onload = null;
      img.onerror = null;
      img.src = '';
      imgRef.current = null;
      // A probe that was cut short says nothing: the last-known status stands.
      if (!settled) {
        const prev = useCameraRegistryStore.getState().statuses[id];
        if (prev?.state === 'connecting') setStatus(id, 'unknown');
      }
    };
  }, [hoveredId, source, setStatus]);
}
