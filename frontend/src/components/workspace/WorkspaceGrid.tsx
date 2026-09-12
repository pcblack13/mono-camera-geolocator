/**
 * `workspace/WorkspaceGrid.tsx` — the desktop 3-pane + dock layout (50-frontend §1.4 / §2.5). **(pure)**
 *
 * ★ CSS Grid template, exactly §1.4:
 *     `grid-template-columns: <imageFr> 6px 56px <inspectorPx> 6px <mapFr>`
 *   image and map are FRACTIONAL (window resize redistributes proportionally); the
 *   rail and inspector are FIXED px. The bottom dock is a fixed-px row under a
 *   horizontal splitter.
 *
 * ★ Pure: sizes in, callbacks out, slots for content — so the layout storybooks and
 *   tests with coloured `<div>`s and no Konva/Leaflet. The px→fr conversion reads the
 *   container's own width at drag time (a deterministic measurement, not state), so
 *   the parent only has to persist the returned `PaneSizes`.
 *
 * ★ The seam semantics: the LEFT splitter drags the image pane's edge (image grows /
 *   map shrinks); the RIGHT splitter drags the map pane's edge (map grows / image
 *   shrinks). Each pane is resized from its own edge — the intuitive model. The
 *   parent store clamps every proposed size (§8.5), so this component never has to
 *   know the bounds.
 */

import { useCallback, useRef, type JSX, type ReactNode } from 'react';
import Box from '@mui/material/Box';

import type { PaneSizes } from '../../store/workspaceStore';
import { Splitter } from './Splitter';

export interface WorkspaceGridProps {
  paneSizes: PaneSizes;
  inspectorOpen: boolean;
  dockOpen: boolean;
  dockHeight: number;
  onResizeColumns: (next: PaneSizes) => void;
  onResizeDock: (nextPx: number) => void;
  onResetColumns?: () => void;
  imagePane: ReactNode;
  toolRail: ReactNode;
  inspector: ReactNode;
  mapPane: ReactNode;
  dock: ReactNode;
}

const RAIL_PX = 56;
const SPLITTER_PX = 6;

export function WorkspaceGrid({
  paneSizes,
  inspectorOpen,
  dockOpen,
  dockHeight,
  onResizeColumns,
  onResizeDock,
  onResetColumns,
  imagePane,
  toolRail,
  inspector,
  mapPane,
  dock,
}: WorkspaceGridProps): JSX.Element {
  const colsRef = useRef<HTMLDivElement>(null);
  const { imageFr, mapFr, inspectorPx } = paneSizes;
  // ★ THE RAIL COLUMN EXISTS ONLY WHILE THERE IS A RAIL (owner ask 2026-09-10).
  //   It was a standing 56 px strip between the photo and the map even when the
  //   rail had nothing to show (outside a correspondence) — an empty window the
  //   operator could only stare at. Like the inspector, it is 0 px until earned.
  const railPx = toolRail ? RAIL_PX : 0;

  /** Flexible width available to the two fr columns, in px, right now. */
  const flexPx = useCallback((): number => {
    const total = colsRef.current?.clientWidth ?? 0;
    const fixed = railPx + (inspectorOpen ? inspectorPx : 0) + SPLITTER_PX;
    return Math.max(1, total - fixed);
  }, [inspectorOpen, inspectorPx, railPx]);

  // Positive delta grows `image` and shrinks `map` by the same fr amount.
  //
  // ★ SNAP AT THE MIDLINE (Phase 4 leftover, delivered). A 50/50 split is the
  //   posture surveyors keep returning to — photo and map as equals — and hitting
  //   it freehand on a 6px seam is fiddly. Within ±12px of equal the seam settles
  //   onto exactly half; one more pixel of drag breaks free again, so the snap is
  //   a detent, not a trap.
  const shiftFr = useCallback(
    (deltaPx: number) => {
      const totalFr = imageFr + mapFr;
      const px = flexPx();
      const perPx = totalFr / px;
      let nextImage = imageFr + deltaPx * perPx;
      const SNAP_PX = 12;
      const half = totalFr / 2;
      if (Math.abs((nextImage - half) / perPx) <= SNAP_PX) nextImage = half;
      onResizeColumns({
        ...paneSizes,
        imageFr: nextImage,
        mapFr: totalFr - nextImage,
      });
    },
    [imageFr, mapFr, flexPx, onResizeColumns, paneSizes],
  );

  const leftValueNow = (imageFr / (imageFr + mapFr)) * 100;

  // ★ ONE SEAM (owner ask 2026-09-10): the splitter on the photo's side resizes
  //   both panes; the second one, on the map's side, did the same job in the
  //   other direction and was one more thing to grab by mistake. Gone.
  const gridTemplateColumns = `minmax(0, ${imageFr}fr) ${SPLITTER_PX}px ${railPx}px ${
    inspectorOpen ? `${inspectorPx}px` : '0px'
  } minmax(0, ${mapFr}fr)`;

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      <Box
        ref={colsRef}
        data-testid="workspace-columns"
        sx={{
          flex: 1,
          minHeight: 0,
          display: 'grid',
          gridTemplateRows: '100%',
        }}
        // Inline: it changes on every splitter drag.
        style={{ gridTemplateColumns }}
      >
        <PaneSlot>{imagePane}</PaneSlot>

        <Splitter
          orientation="vertical"
          ariaLabel="Resize image pane"
          valueNow={leftValueNow}
          onDragDelta={shiftFr}
          onReset={onResetColumns}
        />

        {/* Stays in the grid at 0 px when empty — see the note on the inspector cell. */}
        <Box sx={{ minWidth: 0, overflow: 'hidden', borderRight: railPx > 0 ? 1 : 0, borderColor: 'divider' }}>
          {toolRail}
        </Box>

        {/* ★ NEVER `display: none` ON A GRID CHILD.
            A none'd box is removed from grid LAYOUT entirely, so every later child
            shifts back one cell: the second splitter falls into the inspector's 0px
            column and THE MAP falls into the 6px splitter column — a six-pixel-wide
            map, which on screen reads as "the satellite map is gone" with a thin strip
            of imagery at the pane's left edge. The closed state is expressed by the
            COLUMN being 0px (see `gridTemplateColumns`); the child must stay in the
            grid to keep every pane in its own cell. */}
        <Box
          sx={{
            minWidth: 0,
            overflow: 'hidden',
            borderRight: inspectorOpen ? 1 : 0,
            borderColor: 'divider',
          }}
        >
          {inspectorOpen ? inspector : null}
        </Box>

        <PaneSlot>{mapPane}</PaneSlot>
      </Box>

      {dockOpen && (
        <>
          <Splitter
            orientation="horizontal"
            ariaLabel="Resize ground control point table"
            valueNow={50}
            // Dragging up (negative dy) grows the dock.
            onDragDelta={(d) => onResizeDock(dockHeight - d)}
          />
          <Box sx={{ flex: `0 0 ${dockHeight}px`, minHeight: 0, overflow: 'hidden' }}>{dock}</Box>
        </>
      )}
    </Box>
  );
}

/** A flexible pane cell: clips its own overflow, never lets the body scroll (§1.1). */
function PaneSlot({ children }: { children: ReactNode }): JSX.Element {
  return (
    <Box
      sx={{
        minWidth: 0,
        minHeight: 0,
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {children}
    </Box>
  );
}

export default WorkspaceGrid;
