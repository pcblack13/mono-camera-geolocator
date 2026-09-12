/**
 * `image/AnnotationLayer.tsx` — the Konva layer that renders every landmark, the
 * selected shape's editable vertices, the in-progress rubber-band, and the live
 * linked correspondence marker. 50-frontend.md §2.10 / SCOPE.md §5.
 *
 * ★★ EVERY POINT IS SELECTABLE, EDITABLE AND DRAGGABLE (the client's mandate). A
 *    point body drags as a whole (`move_annotation`); a polygon/polyline exposes a
 *    `VertexHandle` per vertex (`move_vertex`) and drags as a whole through its body.
 *
 * ★★ THE CONVERSION BOUNDARY. Konva hands back DISPLAY-space coordinates on every
 *    drag; this layer converts them to ORIGINAL image px with `displayToImage` before
 *    emitting anything upward, so the parent only ever sees the stored coordinate
 *    frame (§8.6). There is no other conversion path for edits.
 *
 * ★★ THE CORRESPONDENCE MARKER (SCOPE.md §5). While a correspondence is open the
 *    photo pane shows a live linked marker in the shared correspondence colour,
 *    draggable and re-committable. It is fed from `correspondenceStore.openMarkers`
 *    — an `is_committed: false` value that can never be mistaken for a real GCP,
 *    because a committed GCP lives only in React Query (L7, and the §5 invariant).
 *
 * ★ Chrome is inverse-scaled by `1 / stageScale`, so handles and strokes stay a
 *   constant on-screen size across the whole zoom range.
 */

import { useMemo } from 'react';
import { Circle, Group, Layer, Line, RegularPolygon } from 'react-konva';
import type { KonvaEventObject } from 'konva/lib/Node';

import { linkedGcpId } from '../../lib/gcpLink';
import type { AnnotationRead } from '../../types/annotation';
import type { GcpSummary } from '../../types/gcp';
import type { GeoJsonGeometry } from '../../types/geo';
import type { Point2D } from '../../types/common';
import type { InProgressShape } from '../../store/annotationStore';
import type { OpenCorrespondenceMarkers } from '../../store/correspondenceStore';
import {
  MANUAL_SOURCE_COLOR,
  MARKER_OUTLINE,
  NO_RESULT_COLOR,
  confidenceColor,
  gcpConfidenceBand,
  type ThemeMode,
} from '../../theme/confidence';
import { tokens } from '../../theme/tokens';
import { displayToImage, imageToDisplay } from '../../lib/viewport/transform';
import { AnnotationShape } from './AnnotationShape';
import { unlinkedGcps } from './unlinkedGcps';
import { VertexHandle } from './VertexHandle';

export interface AnnotationLayerProps {
  annotations: AnnotationRead[];
  gcps: GcpSummary[];
  /** `D`. */
  displayScale: number;
  /** `s`. */
  stageScale: number;
  selectedIds: string[];
  hoveredId: string | null;
  readOnly: boolean;
  mode: ThemeMode;
  /** The half-drawn polygon/polyline (outside the command system). */
  inProgress: InProgressShape | null;
  /** The open correspondence's linked markers, or `null` when none is open. */
  correspondence: OpenCorrespondenceMarkers | null;
  /** The shared colour that matches the map pane's marker for this correspondence. */
  correspondenceColor: string;
  /** One colour for every mark on the PHOTOGRAPH; null = the meaningful defaults. */
  photoColor?: string | null;
  /** Per-point overrides, keyed by GCP id (or annotation id for plain landmarks). */
  pointColors?: Record<string, string>;

  onSelect: (id: string, additive: boolean) => void;
  onHover: (id: string | null) => void;
  /** ORIGINAL-px delta of a whole annotation. */
  onMoveAnnotationEnd: (id: string, originalDelta: { dx: number; dy: number }) => void;
  /** New ORIGINAL-px position of one vertex. */
  onMoveVertexEnd: (id: string, ringIndex: number, vertexIndex: number, original: Point2D) => void;
  /** New ORIGINAL-px position of the correspondence's photo endpoint. */
  onCorrespondencePhotoDragEnd: (original: Point2D) => void;
}

/** The rings of a geometry, so vertex handles have one code path. */
function ringsOf(g: GeoJsonGeometry): [number, number][][] {
  switch (g.type) {
    case 'Point':
      return [[g.coordinates]];
    case 'LineString':
      return [g.coordinates];
    case 'Polygon':
      return g.coordinates;
    case 'MultiPolygon':
      return g.coordinates.flat();
  }
}

/**
 * Resolve the fill/stroke colour and GCP-ness for one mark on the PHOTOGRAPH.
 *
 * Precedence, most specific first:
 *   1. this point's OWN colour (`pointColors`, keyed by GCP id where it has one, so
 *      one point looks the same on the photograph and the map);
 *   2. `photoColor` — the surveyor's colour for everything drawn on the photograph;
 *   3. the default, which MEANS something: a control point's colour is its confidence
 *      band, and a landmark's is its provenance.
 */
function resolveColor(
  annotation: AnnotationRead,
  gcpById: Map<string, GcpSummary>,
  mode: ThemeMode,
  photoColor: string | null,
  pointColors: Record<string, string>,
): { color: string; isGcp: boolean } {
  const linkedId = linkedGcpId(annotation);
  if (linkedId !== null) {
    const gcp = gcpById.get(linkedId);
    if (gcp) {
      const own = pointColors[gcp.id] ?? pointColors[annotation.id];
      return {
        color: own ?? photoColor ?? confidenceColor(gcpConfidenceBand(gcp), mode),
        isGcp: true,
      };
    }
  }
  // A plain landmark: blue (the manual-provenance accent), not green — green is earned.
  return {
    color:
      pointColors[annotation.id] ??
      photoColor ??
      (annotation.is_gcp_candidate ? MANUAL_SOURCE_COLOR[mode] : NO_RESULT_COLOR[mode]),
    isGcp: false,
  };
}

export function AnnotationLayer({
  annotations,
  gcps,
  displayScale,
  stageScale,
  selectedIds,
  hoveredId,
  readOnly,
  mode,
  inProgress,
  correspondence,
  correspondenceColor,
  photoColor = null,
  pointColors = {},
  onSelect,
  onHover,
  onMoveAnnotationEnd,
  onMoveVertexEnd,
  onCorrespondencePhotoDragEnd,
}: AnnotationLayerProps): JSX.Element {
  const invScale = 1 / (stageScale || 1);
  const outline = MARKER_OUTLINE[mode];

  const gcpById = useMemo(() => {
    const m = new Map<string, GcpSummary>();
    for (const g of gcps) m.set(g.id, g);
    return m;
  }, [gcps]);

  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);

  // The single selected editable shape (vertex handles are shown for one at a time).
  const soleSelected =
    selectedIds.length === 1 ? (annotations.find((a) => a.id === selectedIds[0]) ?? null) : null;

  return (
    <Layer>
      {annotations
        .filter((a) => !a.is_deleted)
        .map((a) => {
          const { color, isGcp } = resolveColor(a, gcpById, mode, photoColor, pointColors);
          return (
            <AnnotationShape
              key={a.id}
              annotation={a}
              displayScale={displayScale}
              invScale={invScale}
              selected={selectedSet.has(a.id)}
              hovered={hoveredId === a.id}
              readOnly={readOnly}
              color={color}
              outline={outline}
              isGcp={isGcp}
              onSelect={(additive) => onSelect(a.id, additive)}
              onHover={(h) => onHover(h ? a.id : null)}
              onMoveEnd={({ dx, dy }) => {
                // DISPLAY-space delta → ORIGINAL-space delta.
                const d = displayToImage({ x: dx, y: dy }, displayScale);
                onMoveAnnotationEnd(a.id, { dx: d.x, dy: d.y });
              }}
            />
          );
        })}

      {/* ★ Bare-click GCPs — committed points with no landmark annotation. Drawn from
          the GCP's own ORIGINAL-space pixel, coloured by its confidence band, so a
          committed point stays visible on the photograph it was placed on. */}
      {unlinkedGcps(annotations, gcps).map((g) => {
        const d = imageToDisplay(g.image_px, displayScale);
        const color =
          pointColors[g.id] ?? photoColor ?? confidenceColor(gcpConfidenceBand(g), mode);
        const r = tokens.annotation.pointRadius * invScale;
        return (
          <Group key={`gcp-${g.id}`} listening={false}>
            <RegularPolygon
              x={d.x}
              y={d.y}
              sides={4}
              radius={r * 1.6}
              rotation={45}
              fill={color}
              stroke={outline}
              strokeWidth={1.5 * invScale}
            />
            <Circle x={d.x} y={d.y} radius={Math.max(1.2 * invScale, r * 0.35)} fill={outline} />
          </Group>
        );
      })}

      {/* Editable vertices of the single selected polygon/polyline. */}
      {!readOnly &&
        soleSelected &&
        soleSelected.geom_type !== 'point' &&
        ringsOf(soleSelected.geometry).map((ring, ringIndex) =>
          ring.map(([x, y], vertexIndex) => {
            // On a closed polygon ring the last position duplicates the first; a
            // handle for it would be a phantom on top of vertex 0 (isRingClosed).
            const isClosingDuplicate =
              soleSelected.geom_type === 'polygon' && vertexIndex === ring.length - 1;
            if (isClosingDuplicate) return null;
            const d = imageToDisplay({ x, y }, displayScale);
            return (
              <VertexHandle
                key={`${soleSelected.id}-${ringIndex}-${vertexIndex}`}
                x={d.x}
                y={d.y}
                invScale={invScale}
                color={MANUAL_SOURCE_COLOR[mode]}
                outline={outline}
                draggable
                ariaLabel={`Vertex ${vertexIndex + 1}`}
                onDragEnd={(dp) => {
                  const orig = displayToImage(dp, displayScale);
                  onMoveVertexEnd(soleSelected.id, ringIndex, vertexIndex, orig);
                }}
              />
            );
          }),
        )}

      {/* The in-progress rubber-band (outside the command system, §4.3). */}
      {inProgress && (
        <InProgressPreview
          shape={inProgress}
          displayScale={displayScale}
          invScale={invScale}
          mode={mode}
        />
      )}

      {/* SCOPE.md §5 — the live linked correspondence marker (photo endpoint). */}
      {correspondence && correspondence.image_px && (
        <CorrespondenceMarker
          imagePx={correspondence.image_px}
          displayScale={displayScale}
          invScale={invScale}
          color={correspondenceColor}
          outline={outline}
          awaiting={correspondence.awaiting}
          draggable={!readOnly}
          onDragEnd={(dp) => onCorrespondencePhotoDragEnd(displayToImage(dp, displayScale))}
        />
      )}
    </Layer>
  );
}

// ─────────────────────────────────────────────────────────────────────────────

function InProgressPreview({
  shape,
  displayScale,
  invScale,
  mode,
}: {
  shape: InProgressShape;
  displayScale: number;
  invScale: number;
  mode: ThemeMode;
}): JSX.Element {
  const color = MANUAL_SOURCE_COLOR[mode];
  const pts: number[] = [];
  for (const v of shape.vertices) {
    const d = imageToDisplay(v, displayScale);
    pts.push(d.x, d.y);
  }
  if (shape.previewVertex) {
    const d = imageToDisplay(shape.previewVertex, displayScale);
    pts.push(d.x, d.y);
  }
  const closing =
    shape.kind === 'polygon' && shape.vertices.length >= 2
      ? imageToDisplay(shape.vertices[0]!, displayScale)
      : null;

  return (
    <Group listening={false}>
      <Line
        points={pts}
        stroke={color}
        strokeWidth={tokens.annotation.strokeWidth * invScale}
        dash={[6 * invScale, 4 * invScale]}
        lineJoin="round"
      />
      {closing && pts.length >= 4 && (
        <Line
          points={[pts[pts.length - 2]!, pts[pts.length - 1]!, closing.x, closing.y]}
          stroke={color}
          strokeWidth={tokens.annotation.strokeWidth * invScale}
          dash={[3 * invScale, 4 * invScale]}
          opacity={0.5}
        />
      )}
      {shape.vertices.map((v, i) => {
        const d = imageToDisplay(v, displayScale);
        return (
          <Circle
            key={i}
            x={d.x}
            y={d.y}
            radius={tokens.annotation.vertexRadius * invScale}
            fill={color}
            stroke={MARKER_OUTLINE[mode]}
            strokeWidth={tokens.annotation.outlineWidth * invScale}
          />
        );
      })}
    </Group>
  );
}

function CorrespondenceMarker({
  imagePx,
  displayScale,
  invScale,
  color,
  outline,
  awaiting,
  draggable,
  onDragEnd,
}: {
  imagePx: { x: number; y: number };
  displayScale: number;
  invScale: number;
  color: string;
  outline: string;
  awaiting: 'photo' | 'map' | 'confidence' | null;
  draggable: boolean;
  onDragEnd: (displayPoint: { x: number; y: number }) => void;
}): JSX.Element {
  const p = imageToDisplay(imagePx, displayScale);
  const r = (tokens.annotation.pointRadiusSelected + 2) * invScale;
  // A pulsing/ghosted ring while the surveyor is being asked for the OTHER endpoint.
  const pending = awaiting !== null;
  const handle = (e: KonvaEventObject<DragEvent>): void =>
    onDragEnd({ x: e.target.x(), y: e.target.y() });

  return (
    <Group>
      <Circle
        x={p.x}
        y={p.y}
        radius={r * 1.9}
        stroke={color}
        strokeWidth={tokens.annotation.outlineWidth * invScale}
        dash={pending ? [4 * invScale, 4 * invScale] : undefined}
        opacity={0.7}
        listening={false}
      />
      <RegularPolygon
        x={p.x}
        y={p.y}
        sides={4}
        radius={r}
        rotation={45}
        fill={color}
        stroke={outline}
        strokeWidth={tokens.annotation.outlineWidth * invScale}
        hitStrokeWidth={tokens.annotation.hitStrokeWidth * invScale}
        draggable={draggable}
        onDragEnd={handle}
        shadowColor={outline}
        shadowBlur={6 * invScale}
        shadowOpacity={0.9}
      />
    </Group>
  );
}
