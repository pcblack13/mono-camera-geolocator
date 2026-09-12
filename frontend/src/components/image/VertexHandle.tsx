/**
 * `image/VertexHandle.tsx` (pure) — a draggable vertex of a polygon/polyline.
 * 50-frontend.md §2.10.
 *
 * ★ **Chrome is inverse-scaled.** The handle is authored in DISPLAY coordinates
 *   (a Stage child), so the Stage scale `s` is the only transform still applied to
 *   it — a handle that should read ~8 CSS px is drawn at `size * invScale` where
 *   `invScale = 1 / s`. This keeps it a constant on-screen target at 0.1× and at 40×,
 *   which is exactly where a naive implementation produces invisible handles when
 *   zoomed out and boulder-sized ones when zoomed in (§2.10).
 *
 * ★ Positions are handed up in DISPLAY coords on drag; the caller converts to
 *   ORIGINAL px with `displayToImage` before it ever touches a command or the store —
 *   there is no other conversion path (§8.6).
 */

import { Rect } from 'react-konva';
import type { KonvaEventObject } from 'konva/lib/Node';

import { tokens } from '../../theme/tokens';

export interface VertexHandleProps {
  /** DISPLAY-space coordinates (= ORIGINAL × displayScale). */
  x: number;
  y: number;
  /** `1 / stageScale` — the factor that keeps the handle a constant screen size. */
  invScale: number;
  color: string;
  outline: string;
  draggable: boolean;
  ariaLabel: string;
  onDragMove?: (displayPoint: { x: number; y: number }) => void;
  onDragEnd?: (displayPoint: { x: number; y: number }) => void;
  onDblClick?: () => void;
}

export function VertexHandle({
  x,
  y,
  invScale,
  color,
  outline,
  draggable,
  ariaLabel,
  onDragMove,
  onDragEnd,
  onDblClick,
}: VertexHandleProps): JSX.Element {
  const r = tokens.annotation.vertexRadius * invScale;
  const stroke = tokens.annotation.outlineWidth * invScale;
  const hit = tokens.annotation.hitStrokeWidth * invScale;

  const pos = (e: KonvaEventObject<DragEvent>): { x: number; y: number } => ({
    x: e.target.x(),
    y: e.target.y(),
  });

  return (
    <Rect
      x={x}
      y={y}
      // Centre the square on the vertex: offset by half its side.
      offsetX={r}
      offsetY={r}
      width={r * 2}
      height={r * 2}
      cornerRadius={r * 0.4}
      fill={color}
      stroke={outline}
      strokeWidth={stroke}
      hitStrokeWidth={hit}
      draggable={draggable}
      onDragMove={onDragMove ? (e) => onDragMove(pos(e)) : undefined}
      onDragEnd={onDragEnd ? (e) => onDragEnd(pos(e)) : undefined}
      onDblClick={onDblClick}
      onDblTap={onDblClick}
      name={ariaLabel}
      perfectDrawEnabled={false}
    />
  );
}
