/**
 * `hooks/useSenders.ts` — cameras heard announcing themselves on the network.
 *
 * ★ THE CABLE IS THE SETUP (2026-09-09, owner ask). A camera that detects on its
 *   own hardware broadcasts everything needed to talk to it — its address, its
 *   size, its command port, and where it stands on the ground. So plugging it in
 *   should be the whole of installation: the app hears it, shows it, and one
 *   click connects. Nothing typed, nothing started in the right order.
 *
 * ★ POLLED, NOT PUSHED. The list is a two-second poll rather than a socket
 *   because that is all it needs to be: a camera appears within two seconds of
 *   being plugged in and disappears within four of being unplugged, and a poll
 *   cannot get stuck half-open the way a socket can.
 */

import { useCallback, useEffect, useState } from 'react';

import { liveApi, type SenderRead } from '../api/live';

/** Slow enough to be free, fast enough that plugging a cable feels immediate. */
const POLL_MS = 2000;

export interface SendersState {
  items: SenderRead[];
  /** True until the first answer — so the panel can say "looking" once, not blink. */
  loading: boolean;
  /** The API refused or was unreachable. The network being empty is not an error. */
  error: string | null;
  refresh: () => void;
}

export function useSenders(enabled = true): SendersState {
  const [items, setItems] = useState<SenderRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  const refresh = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    if (!enabled) return undefined;
    let cancelled = false;
    const controller = new AbortController();

    const tick = async (): Promise<void> => {
      try {
        const answer = await liveApi.senders(controller.signal);
        if (cancelled) return;
        setItems(answer.items);
        setError(null);
      } catch (exc) {
        if (cancelled) return;
        // ★ AN EMPTY NETWORK IS NOT A FAILURE. Only a refused or unreachable API
        //   is, and the two must not look alike: "no cameras found" is the
        //   normal state of an unplugged cable and needs no red banner.
        setError(exc instanceof Error ? exc.message : String(exc));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void tick();
    const id = window.setInterval(() => void tick(), POLL_MS);
    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(id);
    };
  }, [enabled, nonce]);

  return { items, loading, error, refresh };
}

/** ★ THE ONE PLACE THAT KNOWS A SENDER-BACKED CAMERA'S SOURCE SHAPE. A camera
 *  connected this way plays from the app's own reader, so its source is our URL
 *  and the sender id is inside it. Anything else — an ordinary IP camera, a
 *  capture device — returns null and the sender-specific UI stays out of the way. */
export function senderIdFromSource(source: string | null | undefined): string | null {
  const match = /\/live\/senders\/([^/]+)\/stream(?:$|\?)/.exec((source ?? '').trim());
  return match === null ? null : decodeURIComponent(match[1]);
}
