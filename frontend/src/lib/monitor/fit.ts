/**
 * `lib/monitor/fit.ts` — where a contain-fit picture actually lands in its box.
 *
 * ★ The video hero renders the stream `object-fit: contain`; the detection boxes
 *   arrive in SOURCE-MEDIA pixels. To draw a box on a canvas the size of the box,
 *   the canvas needs the same letterboxing the browser applied — this is that
 *   arithmetic, pure, with a unit test, so the overlay can never drift from the
 *   picture by a rounding of its own.
 */

export interface FitRect {
  /** Offset of the picture inside the container, CSS px. */
  x: number;
  y: number;
  /** The picture's rendered size, CSS px. */
  width: number;
  height: number;
  /** Media px → CSS px. */
  scale: number;
}

export function containRect(
  containerW: number,
  containerH: number,
  mediaW: number,
  mediaH: number,
): FitRect {
  if (containerW <= 0 || containerH <= 0 || mediaW <= 0 || mediaH <= 0) {
    return { x: 0, y: 0, width: 0, height: 0, scale: 0 };
  }
  const scale = Math.min(containerW / mediaW, containerH / mediaH);
  const width = mediaW * scale;
  const height = mediaH * scale;
  return { x: (containerW - width) / 2, y: (containerH - height) / 2, width, height, scale };
}

/** A media-pixel point → the CSS pixel it lands on. */
export function mediaToCss(fit: FitRect, u: number, v: number): [number, number] {
  return [fit.x + u * fit.scale, fit.y + v * fit.scale];
}

/** A CSS pixel inside the container → media pixels (null outside the picture). */
export function cssToMedia(fit: FitRect, x: number, y: number): [number, number] | null {
  if (fit.scale <= 0) return null;
  const u = (x - fit.x) / fit.scale;
  const v = (y - fit.y) / fit.scale;
  if (x < fit.x || y < fit.y || x > fit.x + fit.width || y > fit.y + fit.height) return null;
  return [u, v];
}
