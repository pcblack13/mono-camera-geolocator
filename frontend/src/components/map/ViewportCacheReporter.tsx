/**
 * `map/ViewportCacheReporter.tsx` — tells the backend where the surveyor is looking.
 *
 * ★ THE WHOLE AUTOMATIC-CACHING CLIENT IS THIS REPORT. The backend owns tile
 *   enumeration, the priority queue, limits and the downloads (through the same
 *   ImageryService/cache/rate-limiter as everything else); this component only detects
 *   a SETTLED viewport (debounced `moveend`/`zoomend` — never per-mousemove), converts
 *   the map zoom to the PROVIDER zoom (minus the 512px `zoomShift` — the same +1 trap
 *   as everywhere else), posts it, and polls status while tiles are queued.
 *
 * ★ Renders nothing. Mount inside the `<MapContainer>` (it needs `useMap`).
 *
 * ★ OFFLINE: when `navigator.onLine` is false, no reports are posted — cached tiles
 *   keep serving through the proxy, and the chip says caching is paused. When the
 *   network returns, ONE report for the CURRENT viewport is posted (never a replay of
 *   everywhere the user went while offline).
 */

import { useCallback, useEffect, useRef } from 'react';
import { useMap, useMapEvents } from 'react-leaflet';

import { autoCacheApi } from '../../api/offline';
import { useAutoCacheStore } from '../../store/autoCacheStore';
import type { BasemapKindStr } from '../../api/offline';

export interface ViewportCacheReporterProps {
  providerId: string;
  kind: string;
  /** 1 for 512px providers (map zoom runs one ahead of provider zoom), else 0. */
  zoomShift: number;
  /** False for providers that cannot be fetched (local/offline) — nothing to cache. */
  cacheable: boolean;
  projectId?: string | null;
}

/** Debounce for settled viewports — long enough to skip flings, short enough to feel live. */
const DEBOUNCE_MS = 700;
/** Status poll cadence while the backend still has queued tiles. */
const POLL_MS = 2_000;

export function ViewportCacheReporter({
  providerId,
  kind,
  zoomShift,
  cacheable,
  projectId = null,
}: ViewportCacheReporterProps): null {
  const map = useMap();
  const timer = useRef<number | null>(null);
  const setStatus = useAutoCacheStore((s) => s.setStatus);
  const setOnline = useAutoCacheStore((s) => s.setOnline);

  const report = useCallback((): void => {
    const { enabled, online } = useAutoCacheStore.getState();
    if (!enabled || !online || !cacheable) return;
    const bounds = map.getBounds();
    const zoom = Math.round(map.getZoom()) - zoomShift;
    autoCacheApi
      .reportViewport({
        provider: providerId,
        kind: kind as BasemapKindStr,
        west: bounds.getWest(),
        south: bounds.getSouth(),
        east: bounds.getEast(),
        north: bounds.getNorth(),
        zoom,
        project_id: projectId,
      })
      .then(setStatus)
      .catch(() => undefined); // background feature: a failed report is silence, not an error
  }, [map, providerId, kind, zoomShift, cacheable, projectId, setStatus]);

  const schedule = useCallback((): void => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(report, DEBOUNCE_MS);
  }, [report]);

  useMapEvents({ moveend: schedule, zoomend: schedule });

  // Initial viewport (map ready), and re-report when provider/kind/project change.
  useEffect(() => {
    schedule();
    return () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    };
  }, [schedule]);

  // Browser online/offline — pause reports offline; ONE current-viewport report on return.
  useEffect(() => {
    const goOnline = (): void => {
      setOnline(true);
      schedule();
    };
    const goOffline = (): void => setOnline(false);
    window.addEventListener('online', goOnline);
    window.addEventListener('offline', goOffline);
    return () => {
      window.removeEventListener('online', goOnline);
      window.removeEventListener('offline', goOffline);
    };
  }, [schedule, setOnline]);

  // Poll while the backend is still downloading, so the chip's numbers move.
  const queued = useAutoCacheStore((s) => s.status?.queued_tiles ?? 0);
  const truncated = useAutoCacheStore((s) => s.status?.truncated ?? false);
  const hadQueue = useRef(false);
  useEffect(() => {
    if (queued > 0) {
      hadQueue.current = true;
      const poll = window.setInterval(() => {
        autoCacheApi
          .getStatus()
          .then(setStatus)
          .catch(() => undefined);
      }, POLL_MS);
      return () => window.clearInterval(poll);
    }
    // ★ PROGRESSIVE FULL-DETAIL: a drained queue with `truncated` means the last
    //   report was one CHUNK of a larger area (deep zooms fill 500 tiles at a time).
    //   Re-report the same viewport to queue the next chunk — the loop ends when the
    //   backend reports truncated=false (area complete) or queues nothing (a session
    //   limit), and `hadQueue` guards against re-reporting without progress.
    if (truncated && hadQueue.current) {
      hadQueue.current = false;
      schedule();
    }
    return undefined;
  }, [queued, truncated, schedule, setStatus]);

  return null;
}

export default ViewportCacheReporter;
