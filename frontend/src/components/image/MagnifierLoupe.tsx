/**
 * `image/MagnifierLoupe.tsx` (pure) — 50-frontend.md §1.5 invariant 6 / §2.10.
 *
 * ★★ THE MOST IMPORTANT MOBILE AFFORDANCE. A fingertip is ~10 mm and a GCP must land
 *    on the right pixel; on a coarse pointer, tapping in `point` mode opens this loupe
 *    offset above the touch, showing a magnified view with a crosshair, and the point
 *    commits at the crosshair on `pointerup` — never at the raw touch centroid.
 *
 * ★ A DOM overlay (§5.2), so it is unaffected by the stage transform. It samples the
 *   Stage's own `<canvas>` (`sourceCanvas`) with `drawImage`, which already reflects
 *   zoom/pan and the CSS brightness/contrast filter — the surveyor magnifies exactly
 *   what they see.
 *
 * ★ The readout is the ORIGINAL image pixel (`imagePoint`), the coordinate that will
 *   be stored (§8.6) — not the display or screen value.
 */

import { useEffect, useRef } from 'react';

import type { Point2D } from '../../types/common';
import { ON_MEDIA, ON_MEDIA_SHADOW } from '../../theme/paint';

export interface MagnifierLoupeProps {
  visible: boolean;
  /** Stage-container (screen) coords of the touch — the sampling centre. */
  stagePoint: Point2D;
  /** ORIGINAL image px, for the readout. */
  imagePoint: Point2D;
  /** Default 4. */
  magnification?: number;
  /** Default 56 CSS px. */
  radius?: number;
  /** The Stage's native canvas element to sample. */
  sourceCanvas: HTMLCanvasElement | null;
  color: string;
}

export function MagnifierLoupe({
  visible,
  stagePoint,
  imagePoint,
  magnification = 4,
  radius = 56,
  sourceCanvas,
  color,
}: MagnifierLoupeProps): JSX.Element | null {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (!visible || !sourceCanvas) return;
    const dest = canvasRef.current;
    if (!dest) return;
    const ctx = dest.getContext('2d');
    if (!ctx) return;

    const size = radius * 2;
    // The Stage canvas is backed at devicePixelRatio; map CSS px → backing px.
    const dpr = sourceCanvas.width / (sourceCanvas.clientWidth || sourceCanvas.width);
    const src = size / magnification;

    ctx.clearRect(0, 0, size, size);
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(
      sourceCanvas,
      (stagePoint.x - src / 2) * dpr,
      (stagePoint.y - src / 2) * dpr,
      src * dpr,
      src * dpr,
      0,
      0,
      size,
      size,
    );

    // Crosshair at the loupe centre — the exact pixel that will commit.
    ctx.strokeStyle = color;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(radius, 0);
    ctx.lineTo(radius, size);
    ctx.moveTo(0, radius);
    ctx.lineTo(size, radius);
    ctx.stroke();
  }, [visible, sourceCanvas, stagePoint.x, stagePoint.y, magnification, radius, color]);

  if (!visible) return null;

  const size = radius * 2;
  // Offset the loupe above the touch so the finger does not cover it.
  const left = stagePoint.x - radius;
  const top = stagePoint.y - size - 24;

  return (
    <div
      aria-hidden
      style={{
        position: 'absolute',
        left,
        top,
        width: size,
        height: size,
        borderRadius: '50%',
        overflow: 'hidden',
        border: `2px solid ${color}`,
        boxShadow: '0 2px 12px rgba(0,0,0,0.4)',
        pointerEvents: 'none',
        zIndex: 4,
      }}
    >
      <canvas ref={canvasRef} width={size} height={size} style={{ width: size, height: size }} />
      <div
        style={{
          position: 'absolute',
          bottom: 2,
          left: 0,
          right: 0,
          textAlign: 'center',
          fontFamily: 'JetBrains Mono, monospace',
          fontSize: 10,
          color: ON_MEDIA,
          textShadow: `0 1px 2px ${ON_MEDIA_SHADOW}`,
        }}
      >
        {imagePoint.x.toFixed(0)}, {imagePoint.y.toFixed(0)}
      </div>
    </div>
  );
}
