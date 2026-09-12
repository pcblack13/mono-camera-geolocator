/**
 * `desktop/zoom.js` — how big the UI is drawn, and why.
 *
 * ★ THE 50-INCH PROBLEM. A TV (or any 4K panel the OS reports at scale factor 1)
 *   gets the same 1× rendering a laptop gets, so every icon and label is drawn at
 *   laptop size on a screen watched from three metres. The fix is Chromium's own
 *   page zoom — the thing Ctrl + does — which scales layout, text, canvases and
 *   maps together and keeps every coordinate API consistent. This module holds
 *   the PURE part: the steps, the clamp, and the automatic choice from the
 *   display's size in device-independent pixels (a panel the OS already scales
 *   reports fewer DIPs and needs less from us).
 *
 * Pure, so `node --test zoom.test.js` pins it without Electron.
 */

'use strict';

/** The sizes the menu offers, as zoom factors. */
const ZOOM_STEPS = Object.freeze([0.9, 1, 1.1, 1.25, 1.5, 1.75, 2, 2.5]);
const MIN_ZOOM = ZOOM_STEPS[0];
const MAX_ZOOM = ZOOM_STEPS[ZOOM_STEPS.length - 1];

function clampZoom(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return 1;
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Math.round(n * 100) / 100));
}

/**
 * The zoom a display deserves when nobody has chosen one.
 *
 * `width`/`height` are the display's size in DIPs (Electron's `display.size`),
 * so a 4K panel at OS scale 2 reads as 1920×1080 and stays at 1×, while the
 * same panel at scale 1 reads as 3840×2160 and is drawn at 2×.
 */
function autoZoomFor(display) {
  const w = Number(display && display.width) || 0;
  const h = Number(display && display.height) || 0;
  const longest = Math.max(w, h);
  if (longest >= 3400) return 2;
  if (longest >= 2500) return 1.5;
  if (longest >= 2000) return 1.25;
  return 1;
}

/** The next step up (+1) or down (−1) from `current`, never past the ends. */
function stepZoom(current, direction) {
  const c = clampZoom(current);
  if (direction > 0) {
    const next = ZOOM_STEPS.find((s) => s > c + 1e-9);
    return next === undefined ? MAX_ZOOM : next;
  }
  const lower = ZOOM_STEPS.filter((s) => s < c - 1e-9);
  return lower.length === 0 ? MIN_ZOOM : lower[lower.length - 1];
}

/** A persisted preference: 'auto' or a factor; anything else becomes 'auto'. */
function normalisePreference(value) {
  if (value === 'auto') return 'auto';
  const n = Number(value);
  return Number.isFinite(n) && n >= MIN_ZOOM && n <= MAX_ZOOM ? clampZoom(n) : 'auto';
}

module.exports = { ZOOM_STEPS, MIN_ZOOM, MAX_ZOOM, clampZoom, autoZoomFor, stepZoom, normalisePreference };
