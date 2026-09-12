/**
 * `hooks/useDataFeedStatus.ts` — is this data integration actually receiving?
 *
 * ★ THE WALL MUST NOT SAY "0 LIVE" WHILE A BOARD IS SENDING (2026-09-07, before
 *   the Raspberry Pi test). A video tile probes itself: its `<img>` either shows
 *   a frame or errors. A DATA tile has no picture to probe, so nothing set its
 *   state and the fleet counted it as unknown — with a Live filter beside those
 *   counts, a working board would have been filtered out of its own wall.
 *
 * ★ STATUS ONLY. `useDataFeed` (the camera's page) also pulls every mark, which
 *   is right for one open camera and wrong for a wall of them. This hook ensures
 *   the feed exists — the server is idempotent per source — and polls its status,
 *   writing the same registry state a video probe writes. No marks travel.
 */

import { useEffect } from 'react';

import { liveApi } from '../api/live';
import { useCameraRegistryStore } from '../store/cameraRegistryStore';

const POLL_MS = 3000;
/** Silence longer than this means the board stopped sending, whatever it claims. */
const STALE_MS = 15_000;

export function useDataFeedStatus(cameraId: string, source: string | null, enabled: boolean): void {
  const setStatus = useCameraRegistryStore((s) => s.setStatus);

  useEffect(() => {
    if (!enabled || source === null || source === '') return undefined;
    let cancelled = false;
    let feedId: string | null = null;

    const tick = async (): Promise<void> => {
      try {
        if (feedId === null) {
          const started = await liveApi.startDataFeed(source, cameraId);
          if (cancelled) return;
          feedId = started.feed_id;
        }
        const feed = await liveApi.dataFeed(feedId);
        if (cancelled) return;
        // ★ `last_mark_at` is epoch SECONDS, 0 until the first line arrives.
        const silentFor = feed.last_mark_at > 0 ? Date.now() - feed.last_mark_at * 1000 : Infinity;
        if (feed.status === 'failed') setStatus(cameraId, 'refused', feed.error ?? undefined);
        else if (feed.status === 'stopped') setStatus(cameraId, 'lost');
        else if (feed.lines_ok > 0 && silentFor < STALE_MS) setStatus(cameraId, 'live');
        else if (feed.lines_ok > 0) setStatus(cameraId, 'lost');
        else setStatus(cameraId, 'connecting');
      } catch {
        if (cancelled) return;
        // A vanished feed id (a server restart) heals by starting one next tick.
        feedId = null;
        setStatus(cameraId, 'lost');
      }
    };

    void tick();
    const id = window.setInterval(() => void tick(), POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [cameraId, source, enabled, setStatus]);
}
