/**
 * `hooks/useDataFeed.ts` — a detection-DATA integration, live on the page.
 *
 * ★ Some integrations send detections instead of pictures (2026-09-02): a
 *   serial/UART sensor, a Pi running its own detector. This hook keeps such a
 *   feed alive while the page shows it: ensure-started on mount (the server is
 *   idempotent per source), polled on a cursor (only NEW marks travel), and the
 *   feed keeps running server-side when the page closes — a data logger is not
 *   a tab, walking away must not stop the recording.
 */

import { useEffect, useRef, useState } from 'react';

import { liveApi, type DataFeedRead } from '../api/live';
import type { DetectionMark } from '../api/detection';

const POLL_MS = 1000;
/** The client keeps a bounded tail, like the map's own marks. */
const MAX_CLIENT_MARKS = 20_000;

export interface DataFeedState {
  feed: DataFeedRead | null;
  marks: DetectionMark[];
  /** A start/poll failure the page should show — null while healthy. */
  error: string | null;
}

export function useDataFeed(source: string | null, cameraId?: string | null): DataFeedState {
  const [feed, setFeed] = useState<DataFeedRead | null>(null);
  const [marks, setMarks] = useState<DetectionMark[]>([]);
  const [error, setError] = useState<string | null>(null);
  const cursorRef = useRef(0);

  useEffect(() => {
    if (source === null || source === '') return undefined;
    let cancelled = false;
    let feedId: string | null = null;
    cursorRef.current = 0;
    setMarks([]);
    setFeed(null);

    const tick = async (): Promise<void> => {
      try {
        if (feedId === null) {
          const started = await liveApi.startDataFeed(source, cameraId ?? null);
          if (cancelled) return;
          feedId = started.feed_id;
          setFeed(started);
        }
        const [status, page] = await Promise.all([
          liveApi.dataFeed(feedId),
          liveApi.dataFeedMarks(feedId, cursorRef.current),
        ]);
        if (cancelled) return;
        setFeed(status);
        if (page.marks.length > 0) {
          cursorRef.current = page.next_index;
          setMarks((prev) => [...prev, ...page.marks].slice(-MAX_CLIENT_MARKS));
        }
        setError(null);
      } catch (e) {
        if (cancelled) return;
        // A vanished feed id (server restart) heals by re-starting next tick.
        feedId = null;
        setError(e instanceof Error ? e.message : String(e));
      }
    };

    void tick();
    const id = window.setInterval(() => void tick(), POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [source, cameraId]);

  return { feed, marks, error };
}
