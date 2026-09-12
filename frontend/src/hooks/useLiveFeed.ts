/**
 * `hooks/useLiveFeed.ts` — the live player's state machine, extracted from the tab.
 *
 * ★ THE PLAYER READS THE STREAM ITSELF when it can: http(s) MJPEG is fetched and
 *   parsed frame-by-frame (JPEG SOI/EOI scan) onto a canvas, which is what makes
 *   the FPS a MEASURED number — frames actually decoded per second — never a guess.
 *   When the source refuses cross-origin reads, the caller falls back to a plain
 *   `<img>` (browsers render MJPEG natively there) and FPS is honestly "not
 *   measurable".
 *
 * ★ EVERYTHING ELSE GOES THROUGH THE SERVER'S RE-STREAM (`GET /live/stream`):
 *   RTSP cameras and LOCAL capture devices, re-served as http MJPEG by the backend.
 *
 * ★ FOUR TRUTHS, TOLD APART (1.2.6): `connecting` (nothing yet), `canvas`/`img`
 *   (live), `lost` (frames WERE flowing and stopped — the 6 s stall watchdog), and
 *   a server REFUSAL (`streamError`, the server's verbatim `{error:{message}}`),
 *   which is not a disconnect and must never share its words.
 *
 * Moved here verbatim from `live/LiveStreamTab.tsx` so the globe's per-camera page
 * and the legacy tab run ONE state machine. The tab's tests exercise it through the
 * tab; `use-live-feed.test.ts` exercises it directly.
 */

import { useCallback, useEffect, useRef, useState, type RefObject } from 'react';

import { fetchStream } from '../api/client';
import { liveApi } from '../api/live';

// ─────────────────────────────────────────────────────────────────────────────
// Source rules
// ─────────────────────────────────────────────────────────────────────────────

/** The host part of a camera URL for a default name — never throws (`new URL` rejects
 *  e.g. a port above 65535, and a throw here silently swallowed the click). */
export function hostOf(url: string): string {
  try {
    return new URL(url.replace(/^rtsp:/i, 'http:')).hostname || url;
  } catch {
    return url;
  }
}

/** http(s) can be read/shown by the browser; anything else needs the re-stream. */
export function canPreviewInBrowser(url: string): boolean {
  return /^https?:\/\//i.test(url.trim());
}

/** The URL looks like a camera the server can read (mirror of the server's check). */
export function looksLikeStreamUrl(url: string): boolean {
  return /^(https?|rtsp):\/\/\S+/i.test(url.trim());
}

/** What the panel selects: a saved network URL, or a scanned local device. */
export interface ActiveSource {
  /** Chip identity — the saved source's id, or the device id. */
  key: string;
  kind: 'url' | 'device';
  name: string;
  /** The URL (kind 'url') or the device id (kind 'device') the server opens. */
  src: string;
}

/**
 * Where the PLAYER reads from. Direct for http(s) MJPEG (no server load, and the
 * source's own CORS decides measured-vs-img mode); the server's MJPEG re-stream
 * for everything else — rtsp and local devices — which the browser cannot read.
 */
export function previewSrcFor(active: ActiveSource): string {
  if (active.kind === 'url' && canPreviewInBrowser(active.src)) return active.src;
  return liveApi.proxyStreamUrl(active.src);
}

/** A registered camera's source string → the player's URL. Same rule, no chip. */
export function previewSrcForSource(source: string): string {
  return canPreviewInBrowser(source) ? source : liveApi.proxyStreamUrl(source);
}

// ─────────────────────────────────────────────────────────────────────────────
// The reader
// ─────────────────────────────────────────────────────────────────────────────

export interface StreamStats {
  /** Decoded frames per second over the last 2 s window; null = not measurable. */
  fps: number | null;
  width: number | null;
  height: number | null;
  frames: number;
  startedAt: number | null;
  /**
   * ★ What is actually ARRIVING, stated from evidence, never guessed: the response's
   * Content-Type ("MJPEG" for multipart, "JPEG snapshot" for a one-shot endpoint),
   * plus the SOURCE codec the server reports for its re-streams
   * (`X-Live-Source-Codec`). Null = not observable (the `<img>` fallback renders
   * without exposing headers to us).
   */
  encoding: string | null;
}

/**
 * ★ `lost` IS NOT `dead` (1.2.6). `dead` = nothing selected. `lost` = we WERE
 *   receiving frames and they stopped — the capture card was unplugged, the camera
 *   was switched off, the network dropped. A frozen last frame is indistinguishable
 *   from a slow one; without this state the surveyor reads a stale image as live.
 */
export type ViewMode = 'connecting' | 'canvas' | 'img' | 'dead' | 'lost';

/**
 * ★ How long a started stream may go frame-less before we call it disconnected.
 *   Generous enough for a stuttering 1 fps source, short enough that nobody stares
 *   at a frozen frame wondering. A yanked USB cable usually just STOPS — the read
 *   never returns and never errors — so a timer is the only honest detector.
 */
export const STALL_MS = 6000;

export const EMPTY_STATS: StreamStats = {
  fps: null,
  width: null,
  height: null,
  frames: 0,
  startedAt: null,
  encoding: null,
};

/** The one word the status pill shows, derived from mode + the two flags. */
export type FeedStatus = 'idle' | 'connecting' | 'live' | 'lost' | 'refused';

export interface LiveFeed {
  mode: ViewMode;
  stats: StreamStats;
  reconnect: () => void;
  /** The server's verbatim refusal, or null. */
  streamError: string | null;
  formatWarning: string | null;
  /** Report the `<img>` fallback's load error — its only disconnect signal. */
  reportImgFailed: () => void;
  imgFailed: boolean;
  status: FeedStatus;
  /** Epoch ms of the last decoded frame (canvas mode); null otherwise. */
  lastFrameAt: number | null;
}

/**
 * Fetch-and-parse an MJPEG stream onto a canvas; report measured stats.
 *
 * ★ Falls back rather than fails: a source that blocks cross-origin reads (no CORS
 * headers) rejects the fetch — the caller then shows a plain `<img>`, which the
 * browser may still render, and FPS honestly becomes "not measurable".
 */
export interface LiveFeedOptions {
  /**
   * ★ RUN BEFORE EVERY ATTEMPT — the first open, the Reconnect arrow and the
   *   10 s self-retry alike (2026-09-10). A sender-backed camera plays from the
   *   app's OWN reader, which exists only after `POST /senders/{id}/connect`;
   *   after a relaunch (or a "Connect" the operator never clicked on this
   *   machine) the stream URL answers "not connected" for ever, and pressing
   *   Reconnect only re-fetched the same refused URL. The page passes the
   *   connect call here, so every attempt first ensures the reader exists.
   *   A rejection is the refusal: its message is shown verbatim and the stream
   *   is not fetched (the server's "no camera is announcing itself as …" is the
   *   sentence the operator needs, not a second-hand "not connected").
   */
  prepare?: () => Promise<void>;
}

export function useLiveFeed(
  url: string | null,
  canvas: RefObject<HTMLCanvasElement>,
  options: LiveFeedOptions = {},
): LiveFeed {
  const [mode, setMode] = useState<ViewMode>('connecting');
  // Read through a ref so a new closure never restarts a healthy stream.
  const prepareRef = useRef(options.prepare);
  prepareRef.current = options.prepare;
  const [stats, setStats] = useState<StreamStats>(EMPTY_STATS);
  const [attempt, setAttempt] = useState(0);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [formatWarning, setFormatWarning] = useState<string | null>(null);
  const [imgFailed, setImgFailed] = useState(false);
  const [lastFrameAt, setLastFrameAt] = useState<number | null>(null);
  const lastFrameRef = useRef<number | null>(null);

  const reconnect = useCallback(() => {
    setImgFailed(false);
    setAttempt((a) => a + 1);
  }, []);
  const reportImgFailed = useCallback(() => setImgFailed(true), []);

  useEffect(() => setImgFailed(false), [url]);

  useEffect(() => {
    setStats(EMPTY_STATS);
    setStreamError(null);
    setFormatWarning(null);
    lastFrameRef.current = null;
    setLastFrameAt(null);
    if (!url) {
      setMode('dead');
      return undefined;
    }
    setMode('connecting');

    const aborter = new AbortController();
    let alive = true;
    const frameTimes: number[] = [];
    let frames = 0;
    let size: { w: number; h: number } | null = null;
    let encoding: string | null = null;
    let continuous = false; // multipart stream (vs a one-shot snapshot endpoint)
    let lastFrameAtMono = performance.now();
    const startedAt = Date.now();

    /** Frames were flowing and stopped → disconnected. Stop reading and SAY so. */
    const declareLost = (): void => {
      if (!alive) return;
      alive = false;
      aborter.abort();
      setMode('lost');
    };

    // Stats flush at 2 Hz — never re-render per frame.
    const flush = setInterval(() => {
      if (!alive) return;
      const cutoff = performance.now() - 2000;
      while (frameTimes.length > 0 && frameTimes[0] < cutoff) frameTimes.shift();
      setStats({
        fps: frames > 0 ? frameTimes.length / 2 : null,
        width: size?.w ?? null,
        height: size?.h ?? null,
        frames,
        startedAt,
        encoding,
      });
      setLastFrameAt(lastFrameRef.current);
      // ★ THE WATCHDOG. Only armed once a CONTINUOUS stream has actually delivered a
      //   frame: before that there is nothing to have lost, and a snapshot endpoint
      //   legitimately stops after one.
      if (continuous && frames > 0 && performance.now() - lastFrameAtMono > STALL_MS) {
        clearInterval(flush);
        declareLost();
      }
    }, 500);

    (async () => {
      try {
        const prepare = prepareRef.current;
        if (prepare !== undefined) {
          try {
            await prepare();
          } catch (exc) {
            if (alive) {
              setStreamError(exc instanceof Error ? exc.message : String(exc));
              setMode('dead');
            }
            return;
          }
          if (!alive) return;
        }
        const res = await fetchStream(url, aborter.signal);
        if (!res.ok) {
          // ★ The server REFUSED. Report its reason and stop — retrying the same
          //   URL in an <img> would only fail again and hide why.
          let detail = `The server refused this source (HTTP ${res.status}).`;
          try {
            // ★ THIS API'S ERROR ENVELOPE IS `{error: {code, message, …}}` — not
            //   FastAPI's bare `{detail}`. Reading only `detail` threw away the one
            //   sentence that explains the refusal.
            const body = (await res.json()) as {
              error?: { message?: string };
              detail?: string;
              message?: string;
            };
            detail = body.error?.message ?? body.detail ?? body.message ?? detail;
          } catch {
            // non-JSON body — the status line above is the honest summary
          }
          if (alive) {
            setStreamError(detail);
            setMode('dead');
          }
          return;
        }
        if (!res.body) throw new Error('the response carried no stream body.');

        const contentType = res.headers.get('content-type') ?? '';
        const sourceCodec = res.headers.get('x-live-source-codec');
        const rawNote = res.headers.get('x-live-format-warning');
        if (rawNote && alive) setFormatWarning(rawNote);
        if (/multipart\/x-mixed-replace/i.test(contentType)) {
          continuous = true; // arms the stall watchdog once frames start
          encoding =
            sourceCodec && sourceCodec.toUpperCase() !== 'MJPEG'
              ? `MJPEG (re-encoded from ${sourceCodec.toUpperCase()})`
              : 'MJPEG';
        } else if (/image\/jpe?g/i.test(contentType)) {
          encoding = 'JPEG snapshot';
        }
        const reader = res.body.getReader();
        let buf = new Uint8Array(0);

        for (;;) {
          const { done, value } = await reader.read();
          if (done || !alive) break;
          const next = new Uint8Array(buf.length + value.length);
          next.set(buf);
          next.set(value, buf.length);
          buf = next;

          // Scan for complete JPEGs: SOI (FFD8) … EOI (FFD9).
          for (;;) {
            let soi = -1;
            for (let i = 0; i + 1 < buf.length; i += 1) {
              if (buf[i] === 0xff && buf[i + 1] === 0xd8) {
                soi = i;
                break;
              }
            }
            if (soi < 0) {
              if (buf.length > 1 << 20) buf = new Uint8Array(0);
              break;
            }
            let eoi = -1;
            for (let i = soi + 2; i + 1 < buf.length; i += 1) {
              if (buf[i] === 0xff && buf[i + 1] === 0xd9) {
                eoi = i + 2;
                break;
              }
            }
            if (eoi < 0) {
              if (buf.length - soi > 20 << 20) buf = new Uint8Array(0);
              break;
            }

            const jpeg = buf.slice(soi, eoi);
            buf = buf.slice(eoi);
            try {
              const bitmap = await createImageBitmap(new Blob([jpeg], { type: 'image/jpeg' }));
              const c = canvas.current;
              if (c && alive) {
                if (c.width !== bitmap.width || c.height !== bitmap.height) {
                  c.width = bitmap.width;
                  c.height = bitmap.height;
                }
                c.getContext('2d')?.drawImage(bitmap, 0, 0);
                size = { w: bitmap.width, h: bitmap.height };
                frames += 1;
                lastFrameAtMono = performance.now();
                lastFrameRef.current = Date.now();
                frameTimes.push(lastFrameAtMono);
                if (frames === 1) setMode('canvas');
              }
              bitmap.close();
            } catch {
              // one undecodable frame is a glitch, not a failure
            }
          }
        }
        // ★ The stream ENDED. Three different truths, told apart rather than merged:
        //   · no frames at all      → probably CORS; let the <img> fallback try.
        //   · a snapshot endpoint   → ending is normal; keep the frame we showed.
        //   · a continuous stream   → the source went away. THAT is a disconnect.
        if (!alive) return;
        if (frames === 0) setMode('img');
        else if (continuous) declareLost();
      } catch {
        // ★ Mid-stream failure with frames already on screen is a DISCONNECT, not a
        //   CORS problem — falling back to <img> there would silently retry a dead
        //   device and leave a frozen frame looking live.
        if (!alive) return;
        if (frames > 0) declareLost();
        else setMode('img');
      }
    })();

    return () => {
      alive = false;
      clearInterval(flush);
      aborter.abort();
    };
  }, [url, attempt, canvas]);

  const refused = streamError !== null;

  // ★ SELF-HEALING REFUSAL (2026-09-02). A refused source used to be a dead end:
  //   an unplugged camera came back on the bus and the page sat on "refused"
  //   until the operator left and re-entered. While a URL is wanted and the
  //   source refuses, retry quietly every 10 s — replugging the camera (or the
  //   HDMI signal returning) revives the picture by itself. `attempt` in the
  //   deps re-arms the timer even when the retry fails with the identical
  //   message (same-string state writes don't re-render).
  useEffect(() => {
    if (!refused || url === null) return undefined;
    const id = window.setTimeout(() => reconnect(), 10_000);
    return () => window.clearTimeout(id);
  }, [refused, attempt, url, reconnect]);

  const disconnected = !refused && (mode === 'lost' || (mode === 'img' && imgFailed));
  const status: FeedStatus =
    url === null || mode === 'dead'
      ? refused
        ? 'refused'
        : 'idle'
      : refused
        ? 'refused'
        : disconnected
          ? 'lost'
          : mode === 'connecting'
            ? 'connecting'
            : 'live';

  return {
    mode,
    stats,
    reconnect,
    streamError,
    formatWarning,
    reportImgFailed,
    imgFailed,
    status,
    lastFrameAt,
  };
}
