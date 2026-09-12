/**
 * `hooks/useMonitorEvents.ts` — what happened on this camera, in order.
 *
 * ★ THE LOG IS WHAT THE OPERATOR READS WHEN SOMETHING WENT WRONG: stream lost and
 *   recovered, a run started and stopped, a reference frozen, a drift alert — each
 *   with its timestamp, in the page's own words. Kept per camera in a surviving
 *   slot so a language switch (which remounts the tree) does not erase the record;
 *   capped so a night of reconnects does not grow without bound.
 */

import { useCallback } from 'react';

import { useSurvivingState } from '../lib/survivingState';

export type MonitorEventKind = 'stream' | 'detection' | 'drift' | 'capture' | 'reference' | 'error';

export interface MonitorEvent {
  at: number;
  kind: MonitorEventKind;
  message: string;
  /** Tone: warn/error events are highlighted in the deck. */
  tone?: 'ok' | 'warn' | 'error';
}

const MAX_EVENTS = 500;

export function useMonitorEvents(cameraId: string): {
  events: MonitorEvent[];
  log: (kind: MonitorEventKind, message: string, tone?: MonitorEvent['tone']) => void;
  clear: () => void;
} {
  const [events, setEvents] = useSurvivingState<MonitorEvent[]>(`monitor.events.${cameraId}`, []);
  const log = useCallback(
    (kind: MonitorEventKind, message: string, tone?: MonitorEvent['tone']) =>
      setEvents((prev) => {
        const next = [...prev, { at: Date.now(), kind, message, tone }];
        return next.length > MAX_EVENTS ? next.slice(next.length - MAX_EVENTS) : next;
      }),
    [setEvents],
  );
  const clear = useCallback(() => setEvents([]), [setEvents]);
  return { events, log, clear };
}
