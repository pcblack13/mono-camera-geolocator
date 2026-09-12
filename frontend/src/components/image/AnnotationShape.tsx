/**
 * `image/AnnotationShape.tsx` (pure) — one annotation body, rendered in the Konva
 * scene. 50-frontend.md §2.10.
 *
 * ★★ COORDINATE DISCIPLINE (§8.6). The annotation's `geometry` and `pixel_*` are in
 *    ORIGINAL image pixels. This component positions Konva nodes in DISPLAY space via
 *    `imageToDisplay` (× `displayScale`); the Stage then applies the user's zoom/pan
 *    `s`/`(tx,ty)`. It NEVER uses `imageToStage` for a node position — that would
 *    double-apply the stage transform and drift the shape at 2× the pan rate (§5.2).
 *
 * ★ **Whole-shape move**: the body sits in a draggable `Group`. On drop, the Group's
 *   own `(x,y)` IS the DISPLAY-space delta; the parent converts it to ORIGINAL px
 *   (÷ displayScale) and emits exactly ONE `move_annotation` command (§4.4 rule 2 — a
 *   drag is one undo, not 400). During the drag nothing is written to any store.
 *
 * ★ Chrome (stroke, radius) is inverse-scaled by `invScale = 1/s` so it stays a
 *   constant on-screen size at every zoom (§2.10).
 */

import { Circle, Group, Line, RegularPolygon } from 'react-konva';
import type { KonvaEventObject } from 'konva/lib/Node';

import type { AnnotationRead } from '../../types/annotation';
import type { GeoJsonGeometry } from '../../types/geo';
import { tokens } from '../../theme/tokens';
import { imageToDisplay } from '../../lib/viewport/transform';

export interface AnnotationShapeProps {
  annotation: AnnotationRead;
  /** `D` — ORIGINAL px → DISPLAY px. */
  displayScale: number;
  /** `1 / stageScale` — keeps chrome a constant screen size. */
  invScale: number;
  selected: boolean;
  hovered: boolean;
  readOnly: boolean;
  /** Resolved fill/stroke colour (confidence band, provenance, or neutral). */
  color: string;
  /** The contrasting marker outline (§8.8 item 6). */
  outline: string;
  /** `true` when a committed GCP links this landmark — rendered as a diamond glyph. */
  isGcp: boolean;
  onSelect: (additive: boolean) => void;
  onHover: (hovered: boolean) => void;
  /** DISPLAY-space delta of the whole shape, at `pointerup`. */
  onMoveEnd: (displayDelta: { dx: number; dy: number }) => void;
}

/** Flatten one ring of ORIGINAL-px coords to a DISPLAY-space `[x0,y0,x1,y1,…]`. */
function ringToDisplayPoints(ring: [number, number][], displayScale: number): number[] {
  const out: number[] = [];
  for (const [x, y] of ring) {
    const d = imageToDisplay({ x, y }, displayScale);
    out.push(d.x, d.y);
  }
  return out;
}

/** `#RRGGBB` → `rgba(r,g,b,a)`, for a translucent polygon fill that lets imagery show through. */
function hexToRgba(hex: string, alpha: number): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return hex;
  const n = parseInt(m[1]!, 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

/** The exterior ring of a polygon, or the vertex list of a line. */
function primaryRing(geom: GeoJsonGeometry): [number, number][] {
  switch (geom.type) {
    case 'Point':
      return [geom.coordinates];
    case 'LineString':
      return geom.coordinates;
    case 'Polygon':
      return geom.coordinates[0] ?? [];
    case 'MultiPolygon':
      return geom.coordinates[0]?.[0] ?? [];
  }
}

export function AnnotationShape({
  annotation,
  displayScale,
  invScale,
  selected,
  hovered,
  readOnly,
  color,
  outline,
  isGcp,
  onSelect,
  onHover,
  onMoveEnd,
}: AnnotationShapeProps): JSX.Element {
  const stroke =
    (selected ? tokens.annotation.strokeWidthSelected : tokens.annotation.strokeWidth) * invScale;
  const outlineW = tokens.annotation.outlineWidth * invScale;
  const hitStroke = tokens.annotation.hitStrokeWidth * invScale;
  const draggable = !readOnly && selected;

  const handleClick = (e: KonvaEventObject<MouseEvent>): void => {
    // Stage's own click handler clears selection; a shape click must not bubble to it.
    e.cancelBubble = true;
    onSelect(e.evt.shiftKey || e.evt.metaKey || e.evt.ctrlKey);
  };

  const handleDragEnd = (e: KonvaEventObject<DragEvent>): void => {
    const dx = e.target.x();
    const dy = e.target.y();
    // Snap the node back to its logical origin; the store now owns the new geometry.
    e.target.position({ x: 0, y: 0 });
    if (dx !== 0 || dy !== 0) onMoveEnd({ dx, dy });
  };

  const common = {
    stroke: color,
    strokeWidth: stroke,
    hitStrokeWidth: hitStroke,
    shadowColor: outline,
    shadowBlur: hovered || selected ? 6 * invScale : 0,
    shadowOpacity: 0.9,
    perfectDrawEnabled: false,
    onClick: handleClick,
    onTap: handleClick,
    onMouseEnter: () => onHover(true),
    onMouseLeave: () => onHover(false),
  } as const;

  let body: JSX.Element;

  if (annotation.geom_type === 'point') {
    const p = imageToDisplay({ x: annotation.pixel_x, y: annotation.pixel_y }, displayScale);
    const radius =
      (selected ? tokens.annotation.pointRadiusSelected : tokens.annotation.pointRadius) * invScale;
    body = isGcp ? (
      // A committed GCP landmark reads as a diamond, distinct from a plain point.
      <RegularPolygon
        {...common}
        x={p.x}
        y={p.y}
        sides={4}
        radius={radius * 1.3}
        rotation={45}
        fill={color}
        stroke={outline}
        strokeWidth={outlineW}
      />
    ) : (
      <Circle
        {...common}
        x={p.x}
        y={p.y}
        radius={radius}
        fill={color}
        stroke={outline}
        strokeWidth={outlineW}
      />
    );
  } else {
    const pts = ringToDisplayPoints(primaryRing(annotation.geometry), displayScale);
    const isPolygon = annotation.geom_type === 'polygon';
    body = (
      <Line
        {...common}
        points={pts}
        closed={isPolygon}
        // A translucent fill keeps the imagery legible under the shape; the stroke
        // carries the confidence colour at full strength.
        fill={isPolygon ? hexToRgba(color, hovered || selected ? 0.28 : 0.15) : undefined}
        fillEnabled={isPolygon}
        lineJoin="round"
        lineCap="round"
      />
    );
  }

  return (
    <Group draggable={draggable} onDragEnd={handleDragEnd} name={`annotation-${annotation.id}`}>
      {body}
    </Group>
  );
}
