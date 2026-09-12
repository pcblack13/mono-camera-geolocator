/**
 * `lib/monitor/zoom.ts` — the zoom + pan geometry of the live video (pure).
 */

// ★ ZOOM IN, ZOOM OUT ON THE LIVE VIDEO (owner ask 2026-09-10). One layer holds
//   the picture, the frozen still and every overlay, and only that layer is
//   transformed — so boxes, the drift ghost and the predict reading stay on the
//   pixels they belong to at every zoom. The wheel zooms around the cursor, a
//   drag pans (a drag is not a click: the click that would follow is swallowed),
//   the buttons step, and the "×" chip resets. Everything is CSS: no second
//   decode, no second socket, the stream keeps flowing underneath.
export interface ZoomView {
  zoom: number;
  /** The pan, CSS px, applied before the scale (transform-origin: centre). */
  x: number;
  y: number;
}

export const ZOOM_STEP = 1.15;
export const MAX_ZOOM = 8;
export const HOME_VIEW: ZoomView = { zoom: 1, x: 0, y: 0 };


const clamp = (v: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, v));

/** Keeps the picture over the stage — it can never be dragged out of view. */
export function clampView(v: ZoomView, w: number, h: number): ZoomView {
  const zoom = clamp(v.zoom, 1, MAX_ZOOM);
  const mx = (w * (zoom - 1)) / 2;
  const my = (h * (zoom - 1)) / 2;
  return { zoom, x: clamp(v.x, -mx, mx), y: clamp(v.y, -my, my) };
}

/** Zoom by `factor` keeping the picture point under (cx, cy) — relative to the
 *  stage centre — where it is. */
export function zoomAround(v: ZoomView, factor: number, cx: number, cy: number, w: number, h: number): ZoomView {
  const zoom = clamp(v.zoom * factor, 1, MAX_ZOOM);
  if (zoom === v.zoom) return v;
  const k = zoom / v.zoom;
  return clampView({ zoom, x: cx - (cx - v.x) * k, y: cy - (cy - v.y) * k }, w, h);
}

/** Where the zoom layer sits on the stage, in stage CSS px. */
export function layerRect(v: ZoomView, w: number, h: number): { x: number; y: number; w: number; h: number } {
  return { x: v.x + (w - w * v.zoom) / 2, y: v.y + (h - h * v.zoom) / 2, w: w * v.zoom, h: h * v.zoom };
}
