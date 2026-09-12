/**
 * `drift/useDriftPlayback.ts` — judge the clip WHILE it plays.
 *
 * ★ The overlay is only "live" if the verdicts are. While the `<video>` plays,
 *   this asks the server to check the frame at the player's current second,
 *   about once a second — never overlapping (a slow 4K seek must not pile up),
 *   and never while paused (a paused clip is judged by Check now, by hand).
 *
 * ★ Takes the ELEMENT, not a ref: the player mounts and re-keys with the applied
 *   clip, and an effect that read `ref.current` once would miss it.
 */

import { useEffect, useRef, useState } from 'react';

import { driftApi, type DriftVerdict } from '../../api/drift';
import { openEffectScope } from '../../lib/async';

export function useDriftPlayback(
  video: HTMLVideoElement | null,
  refId: string | undefined,
  enabled: boolean,
  everyMs = 1200,
): DriftVerdict | null {
  const [verdict, setVerdict] = useState<DriftVerdict | null>(null);
  const busy = useRef(false);

  useEffect(() => {
    setVerdict(null);
    if (video === null || refId === undefined || !enabled) return undefined;
    let timer: number | null = null;
    // ★ A check that outlives this effect must not paint the previous clip's
    //   answer over the next one: abort it, and ignore it if it lands anyway.
    const scope = openEffectScope();

    const tick = (): void => {
      if (busy.current || video.paused || video.ended) return;
      busy.current = true;
      const at = Math.round(video.currentTime * 10) / 10;
      driftApi
        .check(refId, at, scope.signal)
        .then((v) => {
          if (!scope.cancelled) setVerdict(v);
        })
        .catch(() => undefined)
        .finally(() => {
          busy.current = false;
        });
    };
    const start = (): void => {
      if (timer !== null) return;
      tick();
      timer = window.setInterval(tick, everyMs);
    };
    const stop = (): void => {
      if (timer !== null) {
        window.clearInterval(timer);
        timer = null;
      }
    };

    video.addEventListener('play', start);
    video.addEventListener('pause', stop);
    video.addEventListener('ended', stop);
    if (!video.paused) start();
    return () => {
      scope.close();
      busy.current = false;
      stop();
      video.removeEventListener('play', start);
      video.removeEventListener('pause', stop);
      video.removeEventListener('ended', stop);
    };
  }, [video, refId, enabled, everyMs]);

  return verdict;
}
