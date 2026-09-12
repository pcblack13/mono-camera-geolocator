/**
 * `monitor/camera/DetectionOverlay.tsx` — boxes, track ids and the selection, on a
 * CANVAS sized to the picture.
 *
 * ★ ONE ELEMENT, THE PICTURE'S SIZE. The hero renders the stream contain-fit; this
 *   canvas is laid over the container, given the container's CSS size in device
 *   pixels, and draws every box through `containRect` — the same letterboxing the
 *   browser applied. Never a second video element; never an SVG guessing the fit.
 *
 * ★ Colours are the detector's own words: yellow = seen this frame, orange = the
 *   tracker's estimate; the selected box is ringed in the instrument cyan. Labels
 *   and ids are optional overlays the chips toggle.
 *
 * ★ ONE RENDERING OF EACH BOX (2026-08-31). While a run is on, the picture IS the
 *   detector's own MJPEG with the boxes burned in server-side, frame-synced by
 *   construction — and this canvas only polls at ~2 Hz, half a second behind the
 *   stream. Drawing its own boxes on top of the burned ones produced two slightly
 *   offset copies of every box wobbling against each other — the "duplicated,
 *   unstable annotations" of the owner's report. With `pictureHasBoxes` the canvas
 *   draws NOTHING the picture already shows: only the selection ring (cyan, a
 *   deliberate highlight) and the click-to-select hit-testing remain.
 */

import { useEffect, useRef, type JSX, type MouseEvent } from 'react';
import Box from '@mui/material/Box';

import type { DetectionLatest } from '../../../api/detection';
import { containRect, cssToMedia, mediaToCss } from '../../../lib/monitor/fit';
import type { OverlayToggles } from '../../../store/monitorLayoutStore';
import {
  DETECTION_BOX,
  DETECTION_BOX_PREDICTED,
  DETECTION_LOCKED,
  DETECTION_TRACKED,
} from '../../../theme/dataColors';
import { ON_MEDIA_SHADOW } from '../../../theme/paint';

export interface DetectionOverlayProps {
  latest: DetectionLatest | null;
  toggles: Pick<OverlayToggles, 'boxes' | 'labels' | 'tracks' | 'hud'>;
  /** The selected track id, if any. */
  selectedTrack: number | null;
  /** A click on a box (by track id, or by index when the box has none). */
  onSelect?: (trackId: number | null, index: number) => void;
  /** True while the picture itself carries burned-in boxes (a run's own MJPEG):
   *  the canvas then draws only the selection ring — see the header. */
  pictureHasBoxes?: boolean;
  /** ★ Manual tracking (2026-09-03). While on, a click TRACKS/untracks the object
   *  under it and a double-click LOCKS it as the primary — resolved server-side
   *  against the freshest frame, so a click reports a MEDIA pixel, not a box. */
  trackingMode?: boolean;
  /** The LOCKED primary's track id — ringed thick; other tracked ids ring thin. */
  primaryTrack?: number | null;
  onTrackAt?: (u: number, v: number) => void;
  onLockAt?: (u: number, v: number) => void;
}

export function DetectionOverlay({
  latest,
  toggles,
  selectedTrack,
  onSelect,
  pictureHasBoxes = false,
  trackingMode = false,
  primaryTrack = null,
  onTrackAt,
  onLockAt,
}: DetectionOverlayProps): JSX.Element {
  const ref = useRef<HTMLCanvasElement | null>(null);
  // ★ A double-click fires click,click,dblclick — so in tracking mode a single
  //   click waits briefly to see whether a lock (double-click) is coming, or it
  //   would track-then-untrack on every lock. Cleared by dblclick.
  const clickTimer = useRef<number | null>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return undefined;
    const draw = (): void => {
      const box = canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      const w = Math.round(box.width * dpr);
      const h = Math.round(box.height * dpr);
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
      }
      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      ctx.clearRect(0, 0, w, h);
      if (latest === null || latest.width <= 0 || latest.height <= 0) return;
      const fit = containRect(box.width, box.height, latest.width, latest.height);
      if (fit.scale <= 0) return;
      ctx.save();
      ctx.scale(dpr, dpr);
      const stroke = Math.max(1.5, 2 * fit.scale);
      ctx.font = `${Math.max(11, 12 * Math.min(1.4, fit.scale * 2))}px var(--font-mono, monospace)`;
      ctx.textBaseline = 'bottom';
      // ★ HUD look (2026-09-03): corner brackets framing the object, with a
      //   centre crosshair on the LOCKED target — the same shapes the server
      //   burns in (see backend hud.py). One path, stroked once.
      const hudBox = (
        bx1: number,
        by1: number,
        bx2: number,
        by2: number,
        reticle: boolean,
      ): void => {
        const arm = Math.max(6, Math.min(40, Math.round(Math.min(bx2 - bx1, by2 - by1) * 0.22)));
        ctx.beginPath();
        ctx.moveTo(bx1, by1); ctx.lineTo(bx1 + arm, by1);
        ctx.moveTo(bx1, by1); ctx.lineTo(bx1, by1 + arm);
        ctx.moveTo(bx2, by1); ctx.lineTo(bx2 - arm, by1);
        ctx.moveTo(bx2, by1); ctx.lineTo(bx2, by1 + arm);
        ctx.moveTo(bx1, by2); ctx.lineTo(bx1 + arm, by2);
        ctx.moveTo(bx1, by2); ctx.lineTo(bx1, by2 - arm);
        ctx.moveTo(bx2, by2); ctx.lineTo(bx2 - arm, by2);
        ctx.moveTo(bx2, by2); ctx.lineTo(bx2, by2 - arm);
        if (reticle) {
          const cx = (bx1 + bx2) / 2;
          const cy = (by1 + by2) / 2;
          const g = 4;
          const a = 11;
          ctx.moveTo(cx - g - a, cy); ctx.lineTo(cx - g, cy);
          ctx.moveTo(cx + g, cy); ctx.lineTo(cx + g + a, cy);
          ctx.moveTo(cx, cy - g - a); ctx.lineTo(cx, cy - g);
          ctx.moveTo(cx, cy + g); ctx.lineTo(cx, cy + g + a);
        }
        ctx.stroke();
      };
      latest.boxes.forEach((b) => {
        const [x1, y1] = mediaToCss(fit, b.x1, b.y1);
        const [x2, y2] = mediaToCss(fit, b.x2, b.y2);
        // ★ Orange = the visual TRACKER's estimate (has a track id). Steady-boxes
        //   coasting is also `predicted` but never tracked; colouring it orange
        //   read as "tracking is on" while it was off (2026-09-03 fix).
        const colour =
          b.predicted && b.track_id !== null ? DETECTION_BOX_PREDICTED : DETECTION_BOX;
        const selected = selectedTrack !== null && b.track_id === selectedTrack;
        // ★ Manual tracking rings (2026-09-03): the LOCKED primary thick, every
        //   other followed object thin — instant feedback over the ~0.5 s-lagged
        //   burned-in ring.
        const isPrimary = trackingMode && primaryTrack !== null && b.track_id === primaryTrack;
        const isTracked = trackingMode && b.track_id !== null && !isPrimary;
        const ring = selected || isPrimary || isTracked;
        // ★ LOCKED is GREEN, TRACKED (and a plain selection) is CYAN — the two are
        //   no longer the same colour (2026-09-03 owner ask). The burned stream
        //   carries the LOCKED / TRACKED word; this ring is the instant echo.
        const ringColour = isPrimary ? DETECTION_LOCKED : DETECTION_TRACKED;
        // ★ The picture already shows this box (burned in, frame-synced) —
        //   re-drawing it here is the double it took two reports to catch.
        if (pictureHasBoxes && !ring) return;
        if (toggles.boxes || ring) {
          ctx.lineWidth = isPrimary || selected ? stroke + 1 : stroke;
          ctx.strokeStyle = ring ? ringColour : colour;
          ctx.globalAlpha = isTracked ? 0.9 : 1;
          // ★ HUD is opt-in (2026-09-03): corner brackets + a locked crosshair when
          //   the HUD chip is on, the plain rectangle it always was otherwise.
          if (toggles.hud) hudBox(x1, y1, x2, y2, isPrimary);
          else ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
          ctx.globalAlpha = 1;
        }
        if (pictureHasBoxes) return; // the label is burned in too — ring only
        const parts: string[] = [];
        if (toggles.labels)
          parts.push(`${b.cls_name} ${(100 * b.score).toFixed(0)}%${b.placed ? ' ⌖' : ''}`);
        if (toggles.tracks && b.track_id !== null) parts.push(`#${b.track_id}`);
        if (parts.length > 0) {
          const text = parts.join(' ');
          const tw = ctx.measureText(text).width;
          const ty = Math.max(14, y1 - 2);
          ctx.fillStyle = ON_MEDIA_SHADOW;
          ctx.globalAlpha = 0.65;
          ctx.fillRect(x1, ty - 14, tw + 6, 16);
          ctx.globalAlpha = 1;
          ctx.fillStyle = ring ? ringColour : colour;
          ctx.fillText(text, x1 + 3, ty);
        }
      });
      ctx.restore();
    };
    draw();
    const ro = new ResizeObserver(draw);
    ro.observe(canvas);
    return () => ro.disconnect();
  }, [latest, toggles, selectedTrack, pictureHasBoxes, trackingMode, primaryTrack]);

  const mediaOf = (e: MouseEvent<HTMLCanvasElement>): [number, number] | null => {
    if (latest === null) return null;
    const rect = e.currentTarget.getBoundingClientRect();
    const fit = containRect(rect.width, rect.height, latest.width, latest.height);
    return cssToMedia(fit, e.clientX - rect.left, e.clientY - rect.top);
  };

  const onClick = (e: MouseEvent<HTMLCanvasElement>): void => {
    const media = mediaOf(e);
    if (media === null) return;
    const [u, v] = media;
    // ★ Tracking mode: the click TRACKS the object server-side (resolved against
    //   the freshest frame). Deferred briefly so a double-click can cancel it and
    //   LOCK instead — see clickTimer.
    if (trackingMode && onTrackAt) {
      if (clickTimer.current !== null) window.clearTimeout(clickTimer.current);
      clickTimer.current = window.setTimeout(() => {
        clickTimer.current = null;
        onTrackAt(u, v);
      }, 220);
      return;
    }
    if (!onSelect) return;
    // Highlight mode: the smallest box under the pointer wins — the aimed-at one.
    let best = -1;
    let bestArea = Number.POSITIVE_INFINITY;
    latest?.boxes.forEach((b, i) => {
      if (u >= b.x1 && u <= b.x2 && v >= b.y1 && v <= b.y2) {
        const area = (b.x2 - b.x1) * (b.y2 - b.y1);
        if (area < bestArea) {
          bestArea = area;
          best = i;
        }
      }
    });
    if (best >= 0 && latest) onSelect(latest.boxes[best].track_id, best);
  };

  const onDoubleClick = (e: MouseEvent<HTMLCanvasElement>): void => {
    // ★ A double-click otherwise SELECTS the page text under it — which painted
    //   the whole video blue (owner report 2026-09-03). Cancel that selection.
    e.preventDefault();
    window.getSelection?.()?.removeAllRanges();
    if (!trackingMode || !onLockAt) return;
    if (clickTimer.current !== null) {
      window.clearTimeout(clickTimer.current); // cancel the pending single-click track
      clickTimer.current = null;
    }
    const media = mediaOf(e);
    if (media !== null) onLockAt(media[0], media[1]);
  };

  return (
    <Box
      component="canvas"
      ref={ref}
      data-testid="detection-overlay"
      onClick={onClick}
      onDoubleClick={onDoubleClick}
      onMouseDown={(e) => {
        // A double-click's second mousedown starts a text selection before
        // dblclick fires — suppress it so the video never flashes blue.
        if (e.detail > 1) e.preventDefault();
      }}
      sx={{
        position: 'absolute',
        inset: 0,
        width: '100%',
        height: '100%',
        userSelect: 'none',
        WebkitUserSelect: 'none',
        pointerEvents: onSelect || trackingMode ? 'auto' : 'none',
        cursor: onSelect || trackingMode ? 'crosshair' : 'default',
      }}
    />
  );
}
