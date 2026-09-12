/**
 * ★★ `image/ImageViewer.tsx` — the Konva `Stage`, and THE SINGLE COORDINATE
 *    CONVERSION SITE. 50-frontend.md §2.9 / §5 / SCOPE.md §5.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * ★★ THE ONE RULE THIS FILE ENFORCES (§8.6):
 *
 *    Pointer events arrive in stage-container coordinates. This component converts
 *    them to ORIGINAL image pixels **exactly once**, through
 *    `lib/viewport/transform.ts`'s `stageToImage`, and discards the raw stage point.
 *    The ORIGINAL-px result is what enters commands, the stores, correspondence, and
 *    the network. No other component may perform this conversion, and this component
 *    performs no OTHER coordinate arithmetic than delegating to the pure lib (§5).
 * ─────────────────────────────────────────────────────────────────────────────
 *
 * Owns: the wheel/pinch zoom-to-cursor, the drag-pan (routed through the store's one
 * clamp), the tool interactions (select / place point / draw polygon+polyline), the
 * manual-correspondence photo endpoint, and the accessible keyboard + listbox mirror
 * of the canvas (§8.8).
 *
 * Emits: undoable edits via `annotationStore.execute` (the command bus), selection
 * via `selectionStore`, and the correspondence photo point via `correspondenceStore`.
 * It never mutates a coordinate directly.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { Stage } from 'react-konva';
import type Konva from 'konva';
import type { KonvaEventObject } from 'konva/lib/Node';

import type { AnnotationRead } from '../../types/annotation';
import type { GcpSummary } from '../../types/gcp';
import type { GeoJsonGeometry } from '../../types/geo';
import type { Point2D, Uuid } from '../../types/common';
import { LtrIsland } from '../common/LtrIsland';
import { createAddAnnotation, createMoveAnnotation, createMoveVertex } from '../../lib/commands';
import { clampToImageBounds, effectiveScale, stageToImage } from '../../lib/viewport/transform';
import { useAnnotationStore, isGcpCandidateKind, newClientId } from '../../store/annotationStore';
import { useToolStore } from '../../store/toolStore';
import { useViewerStore } from '../../store/viewerStore';
import { adjustmentsToFilterCss } from '../../store/viewerStore';
import { useSelectionStore } from '../../store/selectionStore';
import { openMarkers, useCorrespondenceStore } from '../../store/correspondenceStore';
import { useColorMode } from '../../theme/ColorModeProvider';
import type { AccuracyZones, SuggestRegion } from '../../api/accuracy';
import { ImageLayer } from './ImageLayer';
import { ZoneLayer } from './ZoneLayer';
import { AnnotationLayer } from './AnnotationLayer';
import { SuggestionLayer } from './SuggestionLayer';
import { CrosshairCursor } from './CrosshairCursor';
import { MagnifierLoupe } from './MagnifierLoupe';
import { t } from '../../i18n';
import { ON_MEDIA } from '../../theme/paint';

export interface ImageViewerProps {
  image: HTMLImageElement | ImageBitmap;
  /** The loaded variant's raster dimensions (Konva.Image size). */
  displayWidth: number;
  displayHeight: number;
  /** Committed GCPs, for confidence colouring of linked landmarks. */
  gcps: GcpSummary[];
  /** The shared colour the map pane also uses for the open correspondence. */
  correspondenceColor: string;
  readOnly?: boolean;
  /**
   * Ranked regions for the NEXT control point, from the accuracy check. Empty (the
   * default) draws nothing — the surveyor has either not asked for them or hidden them.
   */
  suggestions?: readonly SuggestRegion[];
  /** The surveyor's suggestion-box colour. */
  suggestionColor?: string;
  /** One colour for every mark on the photograph; null = the defaults. */
  photoColor?: string | null;
  /** Per-point colour overrides. */
  pointColors?: Record<string, string>;
  /** The nine range zones from the last measurement. Null/undefined draws nothing. */
  zones?: AccuracyZones | null;
  /** Zone fill opacity, 0–100. */
  zoneOpacity?: number;
}

const nowIso = (): string => new Date().toISOString();

/**
 * A client-side point `AnnotationRead`, mirroring `annotationStore`'s own
 * `draftAnnotation` factory. The store commits polygons/polylines through
 * `commitShape`, but exposes no point action — a single point is created here and
 * dispatched as an ordinary undoable `add_annotation` (§4.3).
 */
function createPointAnnotation(imageId: Uuid, at: Point2D, label: string | null): AnnotationRead {
  const ts = nowIso();
  return {
    id: newClientId(),
    image_id: imageId,
    kind: 'generic',
    geom_type: 'point',
    pixel_x: at.x,
    pixel_y: at.y,
    geometry: { type: 'Point', coordinates: [at.x, at.y] },
    label,
    description: null,
    confidence: 1,
    ordering: 0,
    style: {},
    attributes: {},
    version_no: 0,
    revision_seq: 0,
    is_deleted: false,
    is_gcp_candidate: isGcpCandidateKind('generic'),
    gcp_ids: [],
    gcp_id: null,
    created_by: null,
    updated_by: null,
    created_at: ts as AnnotationRead['created_at'],
    updated_at: ts as AnnotationRead['updated_at'],
  };
}

/** Translate every coordinate of a geometry by an ORIGINAL-px delta. */
function translateGeometry(g: GeoJsonGeometry, dx: number, dy: number): GeoJsonGeometry {
  const t = ([x, y]: [number, number]): [number, number] => [x + dx, y + dy];
  switch (g.type) {
    case 'Point':
      return { type: 'Point', coordinates: t(g.coordinates) };
    case 'LineString':
      return { type: 'LineString', coordinates: g.coordinates.map(t) };
    case 'Polygon':
      return { type: 'Polygon', coordinates: g.coordinates.map((r) => r.map(t)) };
    case 'MultiPolygon':
      return {
        type: 'MultiPolygon',
        coordinates: g.coordinates.map((p) => p.map((r) => r.map(t))),
      };
  }
}

/** The axis-aligned bounds of a geometry, ORIGINAL px. */
function geometryBounds(g: GeoJsonGeometry): {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
} {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  const visit = ([x, y]: [number, number]): void => {
    if (x < minX) minX = x;
    if (y < minY) minY = y;
    if (x > maxX) maxX = x;
    if (y > maxY) maxY = y;
  };
  switch (g.type) {
    case 'Point':
      visit(g.coordinates);
      break;
    case 'LineString':
      g.coordinates.forEach(visit);
      break;
    case 'Polygon':
      g.coordinates.forEach((r) => r.forEach(visit));
      break;
    case 'MultiPolygon':
      g.coordinates.forEach((p) => p.forEach((r) => r.forEach(visit)));
      break;
  }
  return { minX, minY, maxX, maxY };
}

/** The nth ring of a geometry, ORIGINAL px. */
function ringAt(g: GeoJsonGeometry, ringIndex: number): [number, number][] | null {
  switch (g.type) {
    case 'Point':
      return ringIndex === 0 ? [g.coordinates] : null;
    case 'LineString':
      return ringIndex === 0 ? g.coordinates : null;
    case 'Polygon':
      return g.coordinates[ringIndex] ?? null;
    case 'MultiPolygon':
      return g.coordinates.flat()[ringIndex] ?? null;
  }
}

export function ImageViewer({
  image,
  displayWidth,
  displayHeight,
  gcps,
  correspondenceColor,
  readOnly = false,
  suggestions = [],
  suggestionColor,
  photoColor = null,
  pointColors,
  zones = null,
  zoneOpacity = 45,
}: ImageViewerProps): JSX.Element {
  const containerRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<Konva.Stage>(null);

  const { mode } = useColorMode();

  // ── viewer transform (the store owns the one clamp) ──────────────────────────
  const transform = useViewerStore((s) => s.transform);
  const displayScale = useViewerStore((s) => s.displayScale);
  const naturalSize = useViewerStore((s) => s.naturalSize);
  const viewport = useViewerStore((s) => s.viewport);
  const adjustments = useViewerStore((s) => s.adjustments);
  const setViewport = useViewerStore((s) => s.setViewport);
  const zoomAt = useViewerStore((s) => s.zoomAt);
  const panBy = useViewerStore((s) => s.panBy);
  const setCursorImagePos = useViewerStore((s) => s.setCursorImagePos);

  const filterCss = useMemo(() => adjustmentsToFilterCss(adjustments), [adjustments]);

  // ── interaction stores ───────────────────────────────────────────────────────
  const activeTool = useToolStore((s) => s.activeTool);
  const snapRadiusPx = useToolStore((s) => s.options.snapRadiusPx);
  const autoLabel = useToolStore((s) => s.options.autoLabel);
  const labelPrefix = useToolStore((s) => s.options.labelPrefix);

  const annotations = useAnnotationStore((s) => s.draft.annotations);
  const imageId = useAnnotationStore((s) => s.draft.image_id);
  const inProgress = useAnnotationStore((s) => s.inProgress);
  const execute = useAnnotationStore((s) => s.execute);
  const beginShape = useAnnotationStore((s) => s.beginShape);
  const extendShape = useAnnotationStore((s) => s.extendShape);
  const updatePreview = useAnnotationStore((s) => s.updatePreview);
  const commitShape = useAnnotationStore((s) => s.commitShape);
  const cancelShape = useAnnotationStore((s) => s.cancelShape);
  const allocateOrdinal = useAnnotationStore((s) => s.allocateOrdinal);

  const selected = useSelectionStore((s) => s.selected);
  const hovered = useSelectionStore((s) => s.hovered);
  const select = useSelectionStore((s) => s.select);
  const setHovered = useSelectionStore((s) => s.setHovered);
  const clearSelection = useSelectionStore((s) => s.clear);

  // ★ Shallow-compared: `openMarkers` builds a fresh object per call, and under
  //   Object.is equality every store change (each keystroke in the panel's Note
  //   field) re-rendered the whole canvas. The fields are primitives + stable refs,
  //   so shallow equality is exact.
  const correspondence = useCorrespondenceStore(useShallow(openMarkers));
  const setPhotoPoint = useCorrespondenceStore((s) => s.setPhotoPoint);
  const awaitingPhoto = correspondence?.awaiting === 'photo';

  const selectedIds = useMemo(() => selected.map((r) => r.id), [selected]);
  const hoveredId = hovered?.id ?? null;

  // ── local ephemeral: crosshair + loupe ───────────────────────────────────────
  const [cursorScreen, setCursorScreen] = useState<Point2D | null>(null);
  const [cursorImage, setCursorImage] = useState<Point2D | null>(null);
  const [loupeActive, setLoupeActive] = useState(false);
  // ★ THE PAN STATE MACHINE, in three pieces:
  //   `panArmedRef`  — pointerdown position; the pan is ARMED but not started, so a
  //                    1-2 px click jitter stays a CLICK (it used to become a pan and
  //                    silently swallow GCP placement clicks).
  //   `panRef`       — last position once the ~4 px threshold is crossed; pan ACTIVE.
  //   `isPanning`    — the same fact as STATE, because the cursor style is computed
  //                    during render and a ref mutation never re-renders (the old
  //                    'grabbing' cursor used to stick until the next mousemove).
  const panRef = useRef<{ x: number; y: number } | null>(null);
  const panArmedRef = useRef<{ x: number; y: number } | null>(null);
  const draggedRef = useRef(false);
  const [isPanning, setIsPanning] = useState(false);

  /** A pan can end anywhere — pointerup elsewhere, pointercancel, leaving the pane. */
  const endPan = (): void => {
    panRef.current = null;
    panArmedRef.current = null;
    setIsPanning(false);
  };

  // The pure conversion context. The STORE owns `D`; never rebuild it by hand.
  const ctx = useViewerStore((s) => s.context)();

  // ── viewport tracking ────────────────────────────────────────────────────────
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      setViewport(el.clientWidth, el.clientHeight);
    });
    ro.observe(el);
    setViewport(el.clientWidth, el.clientHeight);
    return () => ro.disconnect();
  }, [setViewport]);

  // ── wheel zoom: non-passive, imperative — React's onWheel cannot preventDefault ─
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent): void => {
      e.preventDefault();
      // Pointer in stage-container coords — computed from the event so it is correct
      // even if Konva has not seen a recent mousemove.
      const rect = el.getBoundingClientRect();
      const pointer = { x: e.clientX - rect.left, y: e.clientY - rect.top };
      // Notched mice report DOM_DELTA_LINE; normalise ×16 to trackpad-equivalent px.
      const unit = e.deltaMode === 1 ? 16 : 1;
      const dy = e.deltaY * unit;
      // Pinch is reported as wheel + ctrlKey, with smaller deltas.
      const k = e.ctrlKey ? 0.01 : 0.0015;
      const factor = Math.exp(-dy * k);
      zoomAt(pointer, factor);
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [zoomAt]);

  // ── pointer helpers ───────────────────────────────────────────────────────────
  const toImage = useCallback(
    (screen: Point2D): Point2D | null => {
      if (!ctx) return null;
      // ★ THE ONLY conversion site. Raw stage point in; ORIGINAL px out.
      return stageToImage(screen, ctx);
    },
    [ctx],
  );

  const pointerScreen = (): Point2D | null => {
    const p = stageRef.current?.getPointerPosition();
    return p ? { x: p.x, y: p.y } : null;
  };

  const isBackgroundTarget = (e: KonvaEventObject<unknown>): boolean => {
    const t = e.target;
    return t === t.getStage() || t.getClassName() === 'Image';
  };

  // ── commands ───────────────────────────────────────────────────────────────────
  const commitPointAt = useCallback(
    (imgPt: Point2D) => {
      if (!imageId || !naturalSize) return;
      const at = clampToImageBounds(imgPt, naturalSize);
      // ★ Share the store's monotonic ordinal so every point gets a DISTINCT label
      //   (P1, P2, P3…) — unique across deletes and across the point/shape mix.
      const label = autoLabel ? `${labelPrefix}${allocateOrdinal()}` : null;
      const annotation = createPointAnnotation(imageId, at, label);
      execute(createAddAnnotation(annotation, annotations.length));
      // ★ The just-placed point becomes the SOLE selection, so the inspector shows
      //   THIS point's fresh Name/Kind/pixel — not a stale previous mark.
      select({ kind: 'annotation', id: annotation.id, linkedId: null }, 'replace', 'image');
    },
    [
      imageId,
      naturalSize,
      autoLabel,
      labelPrefix,
      annotations.length,
      execute,
      select,
      allocateOrdinal,
    ],
  );

  const moveAnnotationBy = useCallback(
    (id: string, delta: { dx: number; dy: number }) => {
      const a = annotations.find((x) => x.id === id);
      if (!a || !naturalSize) return;

      if (a.geom_type === 'point') {
        const to = clampToImageBounds(
          { x: a.pixel_x + delta.dx, y: a.pixel_y + delta.dy },
          naturalSize,
        );
        const geomAfter: GeoJsonGeometry = { type: 'Point', coordinates: [to.x, to.y] };
        execute(
          createMoveAnnotation(
            a.id as Uuid,
            { x: a.pixel_x, y: a.pixel_y },
            to,
            a.geometry,
            geomAfter,
          ),
        );
        return;
      }

      // Whole-shape translate. Clamp the delta so the shape's bounds stay in-image
      // rather than distorting it by clamping each vertex independently.
      const b = geometryBounds(a.geometry);
      const dx = Math.min(Math.max(delta.dx, -b.minX), naturalSize.width - b.maxX);
      const dy = Math.min(Math.max(delta.dy, -b.minY), naturalSize.height - b.maxY);
      const geomAfter = translateGeometry(a.geometry, dx, dy);
      execute(
        createMoveAnnotation(
          a.id as Uuid,
          { x: a.pixel_x, y: a.pixel_y },
          { x: a.pixel_x + dx, y: a.pixel_y + dy },
          a.geometry,
          geomAfter,
        ),
      );
    },
    [annotations, naturalSize, execute],
  );

  const moveVertex = useCallback(
    (id: string, ringIndex: number, vertexIndex: number, original: Point2D) => {
      const a = annotations.find((x) => x.id === id);
      if (!a || !naturalSize) return;
      const ring = ringAt(a.geometry, ringIndex);
      if (!ring) return;
      const from = ring[vertexIndex];
      if (!from) return;
      const to = clampToImageBounds(original, naturalSize);

      execute(
        createMoveVertex(a.id as Uuid, ringIndex, vertexIndex, { x: from[0], y: from[1] }, to),
      );

      // ★ A closed polygon ring has `first === last`. Moving vertex 0 must also move
      //   the duplicated closing vertex or `isRingClosed` fails and the API rejects
      //   the save (`ANNOTATION_GEOMETRY_INVALID`). This is the one vertex whose edit
      //   is two commands; every other vertex is a single clean undo step.
      if (a.geom_type === 'polygon' && vertexIndex === 0) {
        const lastIndex = ring.length - 1;
        const last = ring[lastIndex];
        if (last) {
          execute(
            createMoveVertex(a.id as Uuid, ringIndex, lastIndex, { x: last[0], y: last[1] }, to),
          );
        }
      }
    },
    [annotations, naturalSize, execute],
  );

  // ── selection ───────────────────────────────────────────────────────────────
  const selectAnnotation = useCallback(
    (id: string, additive: boolean) => {
      const a = annotations.find((x) => x.id === id);
      // ★ The link to the GCP is `gcp_ids` (the server populates the plural list; `gcp_id`
      //   is always null). Without the first linked id here, clicking a landmark on the
      //   photo carries linkedId=null, so its GCP row never matches and the table/map never
      //   reveal it. A landmark has at most one GCP in this build, so [0] is the one.
      select(
        { kind: 'annotation', id, linkedId: a?.gcp_ids?.[0] ?? a?.gcp_id ?? null },
        additive ? 'add' : 'replace',
        'image',
      );
    },
    [annotations, select],
  );

  // ── stage pointer handlers ────────────────────────────────────────────────────
  const handlePointerDown = (e: KonvaEventObject<PointerEvent | MouseEvent>): void => {
    draggedRef.current = false;
    const screen = pointerScreen();
    if (!screen) return;

    // Coarse pointer + point/awaiting-photo → open the precision loupe (§1.5 inv. 6).
    if (
      e.evt instanceof PointerEvent &&
      e.evt.pointerType === 'touch' &&
      (activeTool === 'point' || awaitingPhoto)
    ) {
      setLoupeActive(true);
    }

    // Pan is ARMED only on the background, and only in cursor mode (other tools use
    // the click to place/extend). Shapes and handles capture their own drags. It
    // does not START until the pointer moves a real distance — see handlePointerMove.
    if (activeTool === 'cursor' && isBackgroundTarget(e)) {
      panArmedRef.current = screen;
    }
  };

  /** Movement below this is click jitter, not a pan (original-screen px). */
  const PAN_THRESHOLD_PX = 4;

  const handlePointerMove = (): void => {
    const screen = pointerScreen();
    if (!screen) return;
    setCursorScreen(screen);
    const img = toImage(screen);
    if (img) {
      setCursorImage(img);
      setCursorImagePos(img);
    }

    if (panRef.current) {
      draggedRef.current = true;
      panBy(screen.x - panRef.current.x, screen.y - panRef.current.y);
      panRef.current = screen;
      return;
    }
    if (panArmedRef.current) {
      const dx = screen.x - panArmedRef.current.x;
      const dy = screen.y - panArmedRef.current.y;
      if (Math.hypot(dx, dy) >= PAN_THRESHOLD_PX) {
        // The threshold is crossed: NOW it is a pan, not a click.
        draggedRef.current = true;
        setIsPanning(true);
        panBy(dx, dy);
        panRef.current = screen;
        panArmedRef.current = null;
      }
      return;
    }

    // Rubber-band the in-progress shape to the cursor.
    if (inProgress && img) updatePreview(img);
  };

  const handlePointerUp = (e: KonvaEventObject<PointerEvent | MouseEvent>): void => {
    const wasPanning = panRef.current !== null;
    endPan();
    setLoupeActive(false);

    const screen = pointerScreen();
    const img = screen ? toImage(screen) : null;

    // A pan is not a click.
    if (wasPanning && draggedRef.current) return;
    // A click that landed on a shape/handle is handled by that node, not the stage.
    if (!isBackgroundTarget(e)) return;
    if (!img) return;

    // ★ SCOPE.md §5 — while a correspondence awaits the photo endpoint, a background
    //   click sets it (does not place an annotation). The live linked marker follows.
    //   Clamped to the raster: a click in the letterbox must not store an off-image
    //   pixel as a GCP endpoint (point annotations already clamp; this now matches).
    if (awaitingPhoto) {
      setPhotoPoint(naturalSize ? clampToImageBounds(img, naturalSize) : img);
      return;
    }

    if (readOnly) return;

    switch (activeTool) {
      case 'cursor':
        clearSelection();
        break;
      case 'point':
        commitPointAt(img);
        break;
      case 'polygon':
      case 'polyline':
        handleShapeClick(activeTool, img);
        break;
    }
  };

  const handleShapeClick = (tool: 'polygon' | 'polyline', img: Point2D): void => {
    if (!inProgress) {
      beginShape(tool, img);
      return;
    }
    // Closing a polygon: click near the first vertex with ≥ 3 points. The tolerance
    // is a constant ~on-screen distance, converted to ORIGINAL px through the effective
    // scale so it is comfortable to hit at every zoom (snapRadiusPx is the floor).
    if (tool === 'polygon' && inProgress.vertices.length >= 3) {
      const first = inProgress.vertices[0]!;
      const eff = ctx ? effectiveScale(ctx) : 1;
      const tol = Math.max(snapRadiusPx, 12 / eff);
      const dist = Math.hypot(img.x - first.x, img.y - first.y);
      if (dist <= tol) {
        commitShape(true);
        return;
      }
    }
    extendShape(img);
  };

  const handleDblClick = (): void => {
    if (inProgress) commitShape(inProgress.kind === 'polygon');
  };

  // ── keyboard: accessible annotation (§8.8 item 5) ────────────────────────────
  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>): void => {
    if (e.key === 'Escape') {
      if (inProgress) cancelShape();
      else clearSelection();
      return;
    }
    if (e.key === 'Enter' && inProgress) {
      commitShape(inProgress.kind === 'polygon');
      return;
    }
    // Arrow keys nudge a virtual cursor and Enter places a point (§8.8 item 5).
    const step = e.ctrlKey ? 100 : e.shiftKey ? 10 : 1;
    const base =
      cursorImage ?? (naturalSize ? { x: naturalSize.width / 2, y: naturalSize.height / 2 } : null);
    if (!base) return;
    let moved: Point2D | null = null;
    if (e.key === 'ArrowLeft') moved = { x: base.x - step, y: base.y };
    else if (e.key === 'ArrowRight') moved = { x: base.x + step, y: base.y };
    else if (e.key === 'ArrowUp') moved = { x: base.x, y: base.y - step };
    else if (e.key === 'ArrowDown') moved = { x: base.x, y: base.y + step };
    if (moved && naturalSize) {
      e.preventDefault();
      const clamped = clampToImageBounds(moved, naturalSize);
      setCursorImage(clamped);
      setCursorImagePos(clamped);
    } else if (e.key === 'Enter' && !inProgress && !readOnly && cursorImage) {
      if (awaitingPhoto) setPhotoPoint(cursorImage);
      else if (activeTool === 'point') commitPointAt(cursorImage);
    }
  };

  const crosshairVisible =
    (activeTool === 'point' || awaitingPhoto || inProgress !== null) && cursorScreen !== null;

  const sourceCanvas = (): HTMLCanvasElement | null => {
    const stage = stageRef.current;
    if (!stage) return null;
    const el = stage.container().querySelector('canvas');
    return el ?? null;
  };

  const activeAnnotations = annotations.length;

  return (
    // ★ THE SINGLE COORDINATE SYSTEM stays left-to-right. The Konva stage and every
    //   overlay translate pointer positions into a left-origin space; the mirrored
    //   Arabic chrome must not run under it. See LtrIsland.
    <LtrIsland>
      <div
        ref={containerRef}
        role="application"
        aria-label={`${t('Image annotation canvas.')} ${activeAnnotations} ${t(activeAnnotations === 1 ? 'landmark marked.' : 'landmarks marked.')} ${t('Use arrow keys to move the cursor, Enter to place a point, Escape to cancel.')}`}
        tabIndex={0}
        onKeyDown={handleKeyDown}
        style={{
          position: 'relative',
          width: '100%',
          height: '100%',
          overflow: 'hidden',
          outline: 'none',
          touchAction: 'none',
          // ★ Placement mode WINS: while the correspondence awaits the photo click the
          //   cursor is a crosshair regardless of the annotation tool — this was the
          //   "crosshair sometimes appears, sometimes not" bug (it depended on which
          //   tool happened to be active when New GCP was pressed).
          cursor: awaitingPhoto
            ? 'crosshair'
            : activeTool === 'cursor'
              ? isPanning
                ? 'grabbing'
                : 'grab'
              : 'crosshair',
        }}
      >
        <Stage
          ref={stageRef}
          width={viewport.width || 1}
          height={viewport.height || 1}
          scaleX={transform.scale}
          scaleY={transform.scale}
          x={transform.x}
          y={transform.y}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          // ★ Leaving the pane ENDS the pan: Konva binds events to the stage element
          //   only, so a pointerup outside never reaches us — without this, re-entering
          //   with no button pressed resumed a stuck pan with a stuck 'grabbing' cursor.
          onMouseLeave={() => {
            endPan();
            setLoupeActive(false);
            setCursorScreen(null);
            setCursorImagePos(null);
          }}
          onPointerCancel={() => {
            endPan();
            setLoupeActive(false);
          }}
          onDblClick={handleDblClick}
          onDblTap={handleDblClick}
        >
          <ImageLayer
            image={image}
            displayWidth={displayWidth}
            displayHeight={displayHeight}
            filterCss={filterCss}
          />
          {/* ★ BELOW the annotations: the zones are the context the points sit in,
            never something to click, and a point must never disappear under a tint. */}
          <ZoneLayer
            zones={zones}
            opacity={zoneOpacity}
            displayScale={displayScale}
            stageScale={transform.scale}
          />
          <AnnotationLayer
            annotations={annotations}
            gcps={gcps}
            displayScale={displayScale}
            stageScale={transform.scale}
            selectedIds={selectedIds}
            hoveredId={hoveredId}
            readOnly={readOnly}
            mode={mode}
            inProgress={inProgress}
            correspondence={correspondence}
            correspondenceColor={correspondenceColor}
            photoColor={photoColor}
            pointColors={pointColors}
            onSelect={selectAnnotation}
            onHover={(id) =>
              setHovered(
                id
                  ? {
                      kind: 'annotation',
                      id,
                      linkedId: annotations.find((a) => a.id === id)?.gcp_ids?.[0] ?? null,
                    }
                  : null,
              )
            }
            onMoveAnnotationEnd={moveAnnotationBy}
            onMoveVertexEnd={moveVertex}
            onCorrespondencePhotoDragEnd={(p) => setPhotoPoint(p)}
          />
          {/* ★ ABOVE the annotations: a suggestion is a target for the NEXT point, so it
            must not be hidden behind the points already placed. It does not listen for
            events, so it cannot intercept the click it is asking for. */}
          <SuggestionLayer
            color={suggestionColor}
            regions={suggestions}
            displayScale={displayScale}
            stageScale={transform.scale}
          />
        </Stage>

        {/* DOM overlays — outside the Stage, unaffected by the stage transform (§5.2). */}
        {cursorScreen && (
          <CrosshairCursor
            visible={crosshairVisible}
            x={cursorScreen.x}
            y={cursorScreen.y}
            width={viewport.width}
            height={viewport.height}
            color={awaitingPhoto ? correspondenceColor : 'currentColor'}
          />
        )}
        {cursorScreen && cursorImage && (
          <MagnifierLoupe
            visible={loupeActive}
            stagePoint={cursorScreen}
            imagePoint={cursorImage}
            sourceCanvas={sourceCanvas()}
            color={awaitingPhoto ? correspondenceColor : ON_MEDIA}
          />
        )}

        {/* §8.8 item 3 — the visually-hidden listbox that mirrors the canvas for AT. */}
        <ul
          role="listbox"
          aria-label={t('Landmarks')}
          style={{
            position: 'absolute',
            width: 1,
            height: 1,
            overflow: 'hidden',
            clip: 'rect(0 0 0 0)',
            whiteSpace: 'nowrap',
            margin: -1,
            padding: 0,
            border: 0,
          }}
        >
          {annotations
            .filter((a) => !a.is_deleted)
            .map((a) => (
              <li
                key={a.id}
                role="option"
                aria-selected={selectedIds.includes(a.id)}
                tabIndex={-1}
                onClick={() => selectAnnotation(a.id, false)}
                aria-label={`${a.label ?? 'Landmark'} at x ${a.pixel_x.toFixed(0)}, y ${a.pixel_y.toFixed(0)}`}
              >
                {a.label ?? 'Landmark'}
              </li>
            ))}
        </ul>
      </div>
    </LtrIsland>
  );
}
