/**
 * `hooks/useSourceBoxes.ts` — the boxes a SENDER is already drawing, for our overlay.
 *
 * ★ WHY A SENDER'S BOXES ARE WORTH DRAWING (2026-09-08). A camera on a board that
 *   detects on its own hardware has already done the work by the time the picture
 *   reaches us. Making the operator press Start detection — and making this
 *   machine run YOLO on a picture whose objects are already found — is doing the
 *   job twice and showing nothing for the wait. So a sender's boxes appear the
 *   moment the picture does, with no run at all.
 *
 * ★ TWO CHANNELS, NOT ONE. The camera's DATA SOURCE (its NDJSON feed) carries the
 *   sender's detections and they become marks and durable `detection_events`
 *   rows: that is the record, and it is paced for evidence. This hook polls a
 *   different endpoint for what is on screen RIGHT NOW, keeps it in React state
 *   and stores none of it. One channel could not serve both — fast enough to draw
 *   is fast enough to turn the mark table over in minutes.
 *
 * ★ POLLED AT THE OVERLAY'S OWN RATE, and only while `enabled`. The page turns it
 *   off whenever one of our own runs is on, because two detectors drawing on one
 *   picture is exactly the "duplicated, unstable annotations" defect that
 *   `DetectionOverlay`'s `pictureHasBoxes` exists to prevent.
 */

import { useEffect, useState } from 'react';

import type { DetectionLatest } from '../api/detection';
import { liveApi } from '../api/live';

/** ~4 Hz: fast enough that a box tracks a walking person, slow enough that the
 *  sender is answering a poll rather than serving a second video stream. */
const POLL_MS = 250;

/** ★ THE ONE PLACE THAT KNOWS A BRIDGE'S URL SHAPE. A GEO1 bridge serves its
 *  detections feed at `…/detections.ndjson` and the matching box snapshot at
 *  `…/boxes.json`. A data source that is not recognisably a bridge (a serial
 *  port, a board with its own scheme) returns null and the feature simply does
 *  not appear — never a guessed URL, and never a request we cannot justify. */
export function boxesUrlFor(dataSource: string | null | undefined): string | null {
  const src = (dataSource ?? '').trim();
  if (!src.startsWith('http://') && !src.startsWith('https://')) return null;
  if (!src.endsWith('/detections.ndjson')) return null;
  return `${src.slice(0, -'/detections.ndjson'.length)}/boxes.json`;
}

/** The same bridge's command endpoint. Null for a data source that is not
 *  recognisably a bridge — the click UI then simply does not arm. */
export function trackUrlFor(dataSource: string | null | undefined): string | null {
  const boxes = boxesUrlFor(dataSource);
  return boxes === null ? null : `${boxes.slice(0, -'/boxes.json'.length)}/track`;
}

/**
 * The sender's freshest boxes as a `DetectionLatest`, or null when there is
 * nothing trustworthy to draw.
 *
 * A quiet or unreachable sender answers with zero width/height; that becomes
 * null here rather than an empty box list, so the overlay draws nothing instead
 * of clearing and redrawing an empty canvas four times a second.
 */
export function useSourceBoxes(url: string | null, enabled: boolean): DetectionLatest | null {
  const [latest, setLatest] = useState<DetectionLatest | null>(null);

  useEffect(() => {
    if (!enabled || url === null) {
      setLatest(null);
      return undefined;
    }
    let cancelled = false;
    const controller = new AbortController();

    const tick = async (): Promise<void> => {
      try {
        const answer = await liveApi.sourceBoxes(url, controller.signal);
        if (cancelled) return;
        // Zero size means the sender said nothing useful: the overlay cannot
        // letterbox a box without the picture it was measured against.
        if (answer.width <= 0 || answer.height <= 0) {
          setLatest(null);
          return;
        }
        setLatest({
          seq: answer.seq,
          frame_index: answer.frame_index,
          time_s: answer.time_s,
          width: answer.width,
          height: answer.height,
          boxes: answer.boxes,
        });
      } catch {
        if (cancelled) return;
        // A nudged cable must not blank the picture's annotation on one miss;
        // the next tick either heals it or the sender really is gone.
        setLatest(null);
      }
    };

    void tick();
    const id = window.setInterval(() => void tick(), POLL_MS);
    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(id);
    };
  }, [url, enabled]);

  return latest;
}

/**
 * The same thing for a camera the app reads ITSELF — no bridge, no URL to derive.
 *
 * ★ ONE HOOK PER TRANSPORT, NOT ONE HOOK WITH A MODE. The bridge path derives a
 *   URL from the camera's data source; this one is handed a sender id and asks
 *   the app's own endpoint. Folding both into a single hook with a branch inside
 *   would hide which of the two a camera is actually using — and that is exactly
 *   the thing you want to be able to see when a picture does not appear.
 */
export function useSenderBoxes(
  senderId: string | null,
  enabled: boolean,
): DetectionLatest | null {
  const [latest, setLatest] = useState<DetectionLatest | null>(null);

  useEffect(() => {
    if (!enabled || senderId === null) {
      setLatest(null);
      return undefined;
    }
    let cancelled = false;
    const controller = new AbortController();

    const tick = async (): Promise<void> => {
      try {
        const answer = await liveApi.senderBoxes(senderId, controller.signal);
        if (cancelled) return;
        if (answer.width <= 0 || answer.height <= 0) {
          setLatest(null);
          return;
        }
        setLatest({
          seq: answer.seq,
          frame_index: answer.frame_index,
          time_s: answer.time_s,
          width: answer.width,
          height: answer.height,
          boxes: answer.boxes,
        });
      } catch {
        if (cancelled) return;
        setLatest(null);
      }
    };

    void tick();
    const id = window.setInterval(() => void tick(), POLL_MS);
    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(id);
    };
  }, [senderId, enabled]);

  return latest;
}
