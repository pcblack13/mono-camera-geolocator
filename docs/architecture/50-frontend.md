# 50 — Frontend Architecture & UI/UX Design

**Owner:** Frontend Architect / UI-UX
**Status:** Design (no implementation code in this document)
**Stack (mandated, non-negotiable):** React 18 · TypeScript 5.x · Vite · Material UI v5 · Leaflet via `react-leaflet` v4 · Konva via `react-konva` v18 · TanStack Query v5 · Zustand v4

---

## 0. Design premises (read first)

Four premises drive every decision below. If a later section seems opinionated, it is because of one of these.

**P1 — The surveyor is the safety-critical user.** LandExplorer emits latitude/longitude that may end up in a cadastral record, a compliance filing, or a machine-guidance file. A low-confidence fix rendered in the same visual language as a high-confidence fix is a *defect*, not a cosmetic issue. Confidence is a first-class dimension of the UI, present at every layer: table, map, canvas, export. §8.6 defines the encoding; §8.5 defines the honest-failure states.

**P2 — Annotation coordinates live in ORIGINAL image pixel space. Always.** Every pixel coordinate that crosses the network boundary, enters a Zustand store, or is persisted to `annotation_versions` is expressed in the coordinate frame of the *original uploaded raster* — not the display variant, not the Konva stage, not the screen. Zoom, pan, fit-to-view, brightness, contrast, device pixel ratio, and window resize are all **presentation-only** and must be provably incapable of perturbing a stored coordinate. §5 specifies the two-stage transform and the exact conversion contract. This is the single highest-risk correctness area in the frontend.

**P3 — The frontend must run against a zero-config backend.** The default imagery provider is keyless (per the system constraint). The frontend therefore never hard-requires an API key, never hard-codes a provider, and renders attribution dynamically from what the backend reports (§2.16). No deep model weights exist on the dev machine, so the UI must treat "classical CV path" as the *normal* case and deep-model availability as *progressive enhancement* (§8.7).

**P4 — Server state and client state are disjoint sets.** Nothing that the server owns is duplicated into Zustand; nothing that is ephemeral UI state is round-tripped through React Query. The boundary is drawn explicitly in §3.0 and the one legitimate overlap (annotation draft) is handled with a documented hand-off protocol (§3.4).

---

## 1. The Workspace Layout

### 1.1 Mandated arrangement

| Region | Content |
| --- | --- |
| Left pane | Uploaded ground-level image (Konva canvas) |
| Middle | Annotation tools + contextual inspector |
| Right pane | Satellite 2D map (Leaflet) |
| Bottom dock | Matched GCP table — `Point ID │ Image X │ Image Y │ Latitude │ Longitude │ Confidence` |

The workspace is a **resizable 3-pane horizontal split with a resizable bottom dock**. It is a persistent, non-scrolling application shell: the page body never scrolls, each region manages its own overflow. This is a tool, not a document.

### 1.2 Desktop wireframe (`lg` and up, ≥1200px)

```
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ ☰  LandExplorer   │ Project: North Field Survey 07 ▾ │        ● Matching 62%  ⏱ 0:41   │ ⚙  ?  ◐  AH  │  AppShell / TopBar  (56px)
├────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ ┌───────────────────────────────────┬───┬──────────────────────────────────────────────────────────┐  │
│ │ IMAGE  field_north_0714.jpg       │   │ MAP                              [Satellite│Hybrid│Terr] │  │
│ │ 5472×3648 · EXIF GPS ✓            │ A │  ┌────────────────────────────────────────────────────┐  │  │
│ │ ┌───────────────────────────────┐ │ N │  │                    ▲ N                             │  │  │
│ │ │                               │ │ N │  │        ╭──────────────────╮                        │  │  │
│ │ │        ◈ P1                   │ │ O │  │        │  ◈ P1            │  ← matched footprint   │  │  │
│ │ │              ◈ P2             │ │ T │  │        │        ◈ P2      │    (homography quad)   │  │  │
│ │ │   ▱ hedge_polygon             │ │ A │  │        │   ◈ P3           │                        │  │  │
│ │ │                     ◈ P3      │ │ T │  │        ╰──────────────────╯                        │  │  │
│ │ │        ◈ P4 (low conf)        │ │ I │  │             ◈ P4 ⚠                                 │  │  │
│ │ │                               │ │ O │  │                                                    │  │  │
│ │ └───────────────────────────────┘ │ N │  │  ⊕ ⊖  ⛶                          [heatmap ▨ on]   │  │  │
│ │ ⊕ ⊖ ⛶ ⤢fit  ☀━━━●━━ ◐━━●━━━      │   │  └────────────────────────────────────────────────────┘  │  │
│ │ zoom 142%   x:2841 y:1903         │ R │  © Esri, Maxar, Earthstar Geographics   z14 · 41.87,-93.6│  │
│ └───────────────────────────────────┴─┬─┴──────────────────────────────────────────────────────────┘  │
│         ImagePanel (flex 1, min 320)  │ │           MapPanel (flex 1, min 320)                        │
│                              ToolRail ┘ └ 56px fixed + Inspector 280px collapsible                     │
├────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ ▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬  drag handle (horizontal splitter, 6px hit area)  ▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬  │
├────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ GROUND CONTROL POINTS  (4)          ⟳ re-match   ⇱ adjust   [ Export ▾ ]   ⚠ 1 point below threshold  │
│ ┌────────┬──────────┬──────────┬──────────────┬───────────────┬──────────────────────────────┐        │
│ │Point ID│  Image X │  Image Y │   Latitude   │   Longitude   │  Confidence                  │        │
│ ├────────┼──────────┼──────────┼──────────────┼───────────────┼──────────────────────────────┤        │
│ │  P1    │   1204.5 │    832.0 │  41.8721943  │  -93.6019887  │ ██████████░░  0.94  High     │        │
│ │  P2    │   2841.0 │   1903.5 │  41.8719002  │  -93.6011240  │ █████████░░░  0.88  High     │        │
│ │  P3    │    987.2 │   2455.8 │  41.8724110  │  -93.6027655  │ ███████░░░░░  0.71  Moderate │        │
│ │  P4    │   3902.7 │   3011.2 │  41.87        │  -93.60      │ ███░░░░░░░░░  0.31  ⚠ Unrel. │        │
│ └────────┴──────────┴──────────┴──────────────┴───────────────┴──────────────────────────────┘        │
│                                             GcpTable — bottom dock (default 240px, 120–60vh)           │
└────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

Note in row `P4`: latitude/longitude are **deliberately truncated to 2 decimals** and the row is flagged. Precision is a claim about accuracy; we do not make claims we cannot support. See §8.6.3.

### 1.3 The middle region

"Annotation tools" is decomposed into two pieces because a single wide middle pane would waste the horizontal budget that the image and map both need:

- **ToolRail** — 56px fixed vertical icon rail, always visible, holds the mode-selecting tools (cursor, point, polygon, polyline) and the history/destructive actions (undo, redo, delete). Never collapses; it is the primary interaction surface.
- **Inspector** — 280px collapsible panel, holds *contextual* controls for the current selection or tool: point label/notes, polygon vertex list, snapping options, landmark suggestions, match parameters. Collapses to zero via the rail's `«` affordance, remembered in `workspaceStore`.

Rationale: modes are muscle memory and must never move; properties are contextual and may be dismissed to reclaim space.

### 1.4 Splitter mechanics

Panes are laid out with CSS Grid on the workspace container:
`grid-template-columns: <imageFr> 6px 56px <inspectorPx> 6px <mapFr>`, driven from `workspaceStore.paneSizes`.

- Splitter hit area is 6px visual / 12px pointer (via `::before` inset expansion) — satisfies pointer-target guidance without a fat visual seam.
- Drag is `pointerdown` → `setPointerCapture` → `pointermove` (rAF-throttled) → `pointerup`. Sizes are stored as **fractional units** for the flexible panes (image/map) and **pixels** for fixed panes (rail/inspector), so window resize redistributes proportionally rather than starving one pane.
- Min widths: image 320px, map 320px. When the container cannot satisfy both minima plus rail plus inspector, the layout **auto-demotes to the `md` tabbed behavior** (§1.5) regardless of breakpoint. Breakpoints are a heuristic; available space is the truth.
- Double-clicking a splitter resets that seam to its default ratio (0.5 / 0.5).
- Splitters are keyboard-operable: `role="separator"`, `aria-orientation`, `aria-valuenow` (percentage), `tabindex="0"`, arrow keys nudge 2%, `Home`/`End` jump to min/max, `Enter` resets.
- Sizes persist to `localStorage` under `landexplorer.workspace.v1` and are validated on rehydration (a stale schema is discarded, not migrated blindly).

### 1.5 Responsive reflow — exact MUI breakpoints and rules

Standard MUI v5 breakpoints, unmodified: `xs:0, sm:600, md:900, lg:1200, xl:1536`.

| Range | Name | Layout |
| --- | --- | --- |
| `lg`+ (≥1200) | **Desktop workspace** | Full 3-pane split + bottom dock, as wireframed. Inspector open by default. |
| `md` (900–1199) | **Condensed workspace** | Image and Map remain side-by-side. Inspector **collapses to an overlay drawer** (temporary variant, right-anchored, scrims the map) rather than consuming grid width. Bottom dock default height drops to 180px. Table hides nothing but enables horizontal scroll. |
| `sm` (600–899) | **Tablet — tabbed panes** | Panes become a **tab set**: `[ Image │ Map │ Points ]`. One pane visible at a time, full-bleed. ToolRail becomes a **horizontal bottom toolbar** (above the tab bar) shown only on the Image tab. Bottom dock is promoted to the `Points` tab. Inspector = full-height temporary drawer. |
| `xs` (<600) | **Mobile — stacked tabs** | Same tab model as `sm`, plus: tab bar moves to the bottom (thumb zone), ToolRail becomes a horizontal scrollable chip row, Inspector becomes a **bottom sheet** (swipeable, 3 detents: peek 96px / half 50vh / full 90vh), GcpTable **abandons the grid** and renders as a card list (§2.10.3). Export becomes a full-screen dialog. |

**Reflow invariants** (these are the rules that make the reflow safe, not just responsive):

1. **The reflow never unmounts a pane.** Tabs are rendered with `keepMounted` and hidden via `visibility:hidden; position:absolute`, not conditional rendering. Unmounting the Konva stage would destroy the viewer transform, and unmounting the Leaflet map would destroy tile cache and force a re-fetch — costly on field cellular, and Leaflet is notoriously unhappy about remounting.
2. **Every pane calls `invalidateSize()` / `stage.batchDraw()` on becoming visible.** Leaflet computes tile layout from container size at mount; a hidden container has size 0. A `ResizeObserver` on each pane container drives this, so it also covers splitter drags and window resizes. Debounced 100ms trailing.
3. **Selection state survives the reflow.** `selectionStore` is layout-agnostic. Selecting `P3` on the Points tab and switching to the Map tab lands on a map already centred on `P3` (§3.5).
4. **Tab changes are derived, not duplicated.** `workspaceStore.activeTab` is only *read* at `sm`/`xs`. At `lg` all panes are visible and `activeTab` is inert — it is never cleared, so rotating a tablet from portrait to landscape and back restores the same tab.
5. **Touch targets ≥44×44 CSS px** below `md`. The ToolRail chips and the map controls are re-sized by the theme's component overrides, not by ad-hoc styles (§9.6).
6. **Precision affordance on touch.** Because a fingertip is ~10mm and a GCP must land on the right pixel, tapping the Image pane in `point` mode on a coarse pointer (`@media (pointer: coarse)`) opens a **magnifier loupe** offset above the touch point showing 4× zoom with a crosshair; the point commits on `pointerup`, at the crosshair, not at the raw touch centroid. This is the single most important mobile affordance in the product.

### 1.6 Side-by-side synchronized comparison mode

Toggled from the TopBar (`⇹ Compare`) or `C`. Purpose: let the surveyor visually verify that the homography actually maps the ground photo onto the satellite footprint — i.e. answer "is this the right field?" rather than trusting a number.

Compare mode replaces the 3-pane grid with a **dedicated two-up view** (image left, map right, 50/50, splitter draggable) and hides the ToolRail/Inspector (annotation is disabled while comparing — a read-only verification mode). The bottom dock stays.

Three sync modes, radio-selected in `compareStore.syncMode`:

- **`none`** — independent navigation. Escape hatch; always available.
- **`linked`** (default) — the panes are coupled *through the homography* `H` from the match result. `H` maps original-image pixels → WGS84 lon/lat (via the backend's returned 3×3 plus the provider CRS). Panning/zooming either pane drives the other:
  - Image → Map: take the image-pane viewport centre in original-pixel space, project with `H` → lat/lon, `map.setView(latlon)`. Zoom is coupled by matching **ground sample distance**: compute metres-per-screen-pixel in the image pane (from `H`'s local Jacobian at the viewport centre, scaled by the current stage scale) and choose the fractional Leaflet zoom whose `metersPerPixel` at that latitude is nearest. Leaflet is configured with `zoomSnap: 0` in compare mode so this is continuous rather than stepped.
  - Map → Image: inverse, using `H⁻¹`.
  - Feedback loops are prevented with an **origin token**: each sync write is tagged `{origin: 'image'|'map', seq}`; a pane ignores an incoming view update whose origin is itself, and a `syncing` flag suppresses re-emission for one frame. All sync writes are rAF-coalesced.
  - Available **only when a successful match with `confidence ≥ 0.40` exists**. Below that, `linked` is disabled with the tooltip "Linked view needs a valid match — the current fix is unreliable." We do not synchronize views using a homography we do not believe.
- **`swipe`** — the two panes render *in the same box*, the map warped under the image (or vice versa) via `H`, with a draggable vertical curtain. Implemented as: Leaflet renders normally; the image is drawn into an overlay Konva stage with the CSS transform derived from `H` (a projective 3×3 → `matrix3d()`), clipped to `x < curtainX`. This is the highest-value verification affordance — misalignment is instantly visible as a discontinuity at the curtain. Requires `confidence ≥ 0.40` as above.

Cross-pane visual sync in all modes: hovering a GCP marker in one pane pulses its counterpart in the other (§3.5); the homography footprint quad is drawn on the map; the reprojected satellite footprint corners are drawn on the image.

---

## 2. Component Tree

All paths are relative to `frontend/src/`. Every component is a function component; every props interface is exported from the component's own file. Components marked **(pure)** take no store dependency and are trivially unit-testable — this is the majority, by design: stores are read in container components and passed down.

```
src/
├── App.tsx
├── main.tsx
├── components/
│   ├── shell/
│   │   ├── AppShell.tsx                     AppShellProps
│   │   ├── TopBar.tsx                       TopBarProps
│   │   ├── ProjectSwitcher.tsx              ProjectSwitcherProps
│   │   ├── GlobalJobIndicator.tsx           GlobalJobIndicatorProps
│   │   └── ThemeModeToggle.tsx              (pure)
│   ├── workspace/
│   │   ├── Workspace.tsx                    WorkspaceProps
│   │   ├── WorkspaceGrid.tsx                WorkspaceGridProps            (pure)
│   │   ├── WorkspaceTabs.tsx                WorkspaceTabsProps            (pure)
│   │   ├── Splitter.tsx                     SplitterProps                 (pure)
│   │   ├── PaneHeader.tsx                   PaneHeaderProps               (pure)
│   │   └── CompareView.tsx                  CompareViewProps
│   ├── image/
│   │   ├── ImagePanel.tsx                   ImagePanelProps
│   │   ├── ImageViewer.tsx                  ImageViewerProps
│   │   ├── ImageLayer.tsx                   ImageLayerProps               (pure)
│   │   ├── AnnotationLayer.tsx              AnnotationLayerProps
│   │   ├── AnnotationShape.tsx              AnnotationShapeProps          (pure)
│   │   ├── VertexHandle.tsx                 VertexHandleProps             (pure)
│   │   ├── CrosshairCursor.tsx              CrosshairCursorProps          (pure)
│   │   ├── MagnifierLoupe.tsx               MagnifierLoupeProps           (pure)
│   │   ├── ViewerControls.tsx               ViewerControlsProps           (pure)
│   │   ├── BrightnessContrastControl.tsx    BrightnessContrastControlProps (pure)
│   │   └── ImageStatusBar.tsx               ImageStatusBarProps           (pure)
│   ├── annotation/
│   │   ├── AnnotationToolbar.tsx            AnnotationToolbarProps
│   │   ├── ToolButton.tsx                   ToolButtonProps               (pure)
│   │   ├── AnnotationInspector.tsx          AnnotationInspectorProps
│   │   ├── LandmarkSuggestions.tsx          LandmarkSuggestionsProps
│   │   ├── ManualAdjustMode.tsx             ManualAdjustModeProps
│   │   └── VersionHistoryDrawer.tsx         VersionHistoryDrawerProps
│   ├── map/
│   │   ├── MapPanel.tsx                     MapPanelProps
│   │   ├── SatelliteMap.tsx                 SatelliteMapProps
│   │   ├── BasemapSwitcher.tsx              BasemapSwitcherProps          (pure)
│   │   ├── GcpMarkerLayer.tsx               GcpMarkerLayerProps
│   │   ├── GcpMarker.tsx                    GcpMarkerProps                (pure)
│   │   ├── FootprintLayer.tsx               FootprintLayerProps           (pure)
│   │   ├── ConfidenceHeatmapLayer.tsx       ConfidenceHeatmapLayerProps
│   │   ├── MapViewSync.tsx                  MapViewSyncProps
│   │   ├── LocationHintControl.tsx          LocationHintControlProps
│   │   └── ProviderAttribution.tsx          ProviderAttributionProps      (pure)
│   ├── gcp/
│   │   ├── GcpTable.tsx                     GcpTableProps
│   │   ├── GcpTableRow.tsx                  GcpTableRowProps              (pure)
│   │   ├── GcpCardList.tsx                  GcpCardListProps              (pure)
│   │   ├── ConfidenceCell.tsx               ConfidenceCellProps           (pure)
│   │   ├── CoordinateCell.tsx               CoordinateCellProps           (pure)
│   │   └── GcpTableToolbar.tsx              GcpTableToolbarProps
│   ├── export/
│   │   ├── ExportMenu.tsx                   ExportMenuProps
│   │   ├── ExportDialog.tsx                 ExportDialogProps
│   │   └── LowConfidenceAcknowledgement.tsx LowConfidenceAcknowledgementProps (pure)
│   ├── job/
│   │   ├── JobProgress.tsx                  JobProgressProps              (pure)
│   │   ├── JobPhaseStepper.tsx              JobPhaseStepperProps          (pure)
│   │   └── JobErrorPanel.tsx                JobErrorPanelProps            (pure)
│   ├── upload/
│   │   ├── UploadDropzone.tsx               UploadDropzoneProps           (pure)
│   │   ├── BatchUploadDialog.tsx            BatchUploadDialogProps
│   │   └── BatchUploadRow.tsx               BatchUploadRowProps           (pure)
│   └── common/
│       ├── EmptyState.tsx                   EmptyStateProps               (pure)
│       ├── ErrorBoundary.tsx                ErrorBoundaryProps
│       ├── ConfidenceChip.tsx               ConfidenceChipProps           (pure)
│       ├── ConfidenceBar.tsx                ConfidenceBarProps            (pure)
│       ├── UncertaintyBadge.tsx             UncertaintyBadgeProps         (pure)
│       └── LiveRegion.tsx                   LiveRegionProps               (pure)
```

### 2.1 `shell/AppShell.tsx`

```ts
export interface AppShellProps {
  children: React.ReactNode;
}
```

**Responsibility.** Owns the top-level chrome and the providers that must sit above everything: `ThemeProvider` (§9), `CssBaseline`, `QueryClientProvider`, `SnackbarProvider`, the root `ErrorBoundary`, and the global `LiveRegion` (§8.8). Renders `TopBar` + `children` in a `100dvh` flex column with `overflow: hidden` — `dvh` not `vh`, because mobile Safari's collapsing URL bar makes `vh` wrong exactly when a surveyor is in a field. Registers the global keymap (§8.9) and mounts nothing else; it is deliberately thin.

### 2.2 `shell/TopBar.tsx`

```ts
export interface TopBarProps {
  projectId: Uuid | null;
  onToggleCompare: () => void;
  compareActive: boolean;
}
```

**Responsibility.** MUI `AppBar` (elevation 0, bottom divider). Left: menu toggle + wordmark. Centre-left: `ProjectSwitcher`. Centre-right: `GlobalJobIndicator`. Right: compare toggle, settings, help, `ThemeModeToggle`, avatar. Below `sm` the wordmark collapses to a mark and the job indicator collapses to a bare progress ring with an accessible label.

### 2.3 `shell/GlobalJobIndicator.tsx`

```ts
export interface GlobalJobIndicatorProps {
  jobId: Uuid | null;
}
```

**Responsibility.** The always-visible answer to "is the machine doing something?". Subscribes to `useMatchJob(jobId)` (§3.2). Renders a determinate `CircularProgress` + phase label + elapsed timer when the job is active; a success flash then auto-hide on completion; a persistent error chip (click → opens `JobErrorPanel`) on failure. It is the *only* component allowed to poll at the shell level, so polling cost is exactly one interval regardless of how many views want job status.

### 2.4 `workspace/Workspace.tsx`

```ts
export interface WorkspaceProps {
  projectId: Uuid;
  imageId: Uuid | null;
}
```

**Responsibility.** The layout switch. Reads `workspaceStore` + `useMediaQuery(theme.breakpoints.up('md'))` + a `ResizeObserver` on its own container, computes the effective layout mode (`'grid' | 'tabs'` — recall §1.4: space wins over breakpoint), and renders `WorkspaceGrid` or `WorkspaceTabs`. Renders `CompareView` instead when `compareStore.active`. Holds no data logic; a pure layout arbiter.

### 2.5 `workspace/WorkspaceGrid.tsx` **(pure)**

```ts
export interface WorkspaceGridProps {
  paneSizes: PaneSizes;
  inspectorOpen: boolean;
  dockHeight: number;
  onResizeColumns: (next: PaneSizes) => void;
  onResizeDock: (nextPx: number) => void;
  imagePane: React.ReactNode;
  toolRail: React.ReactNode;
  inspector: React.ReactNode;
  mapPane: React.ReactNode;
  dock: React.ReactNode;
}
```

**Responsibility.** CSS Grid template per §1.4. Renders `Splitter` between seams. Pure: sizes in, callbacks out, slots for content — so the layout can be storybooked and tested with coloured `<div>`s and no Konva/Leaflet.

### 2.6 `workspace/WorkspaceTabs.tsx` **(pure)**

```ts
export interface WorkspaceTabsProps {
  activeTab: WorkspaceTab;              // 'image' | 'map' | 'points'
  onTabChange: (tab: WorkspaceTab) => void;
  tabBarPosition: 'top' | 'bottom';
  badges: Partial<Record<WorkspaceTab, number | 'dot'>>;
  imagePane: React.ReactNode;
  mapPane: React.ReactNode;
  dock: React.ReactNode;
}
```

**Responsibility.** `keepMounted` tab host (§1.5 invariant 1) using visibility-hiding, not conditional rendering. Emits `onTabChange`; badges surface e.g. "3 points below threshold" on the Points tab so a mobile user is not required to be looking at the table to learn something is wrong.

### 2.7 `workspace/Splitter.tsx` **(pure)**

```ts
export interface SplitterProps {
  orientation: 'vertical' | 'horizontal';
  ariaLabel: string;
  valueNow: number;                     // 0..100, percentage of the flexible axis
  min?: number;
  max?: number;
  onDragDelta: (deltaPx: number) => void;
  onDragEnd?: () => void;
  onReset?: () => void;
  disabled?: boolean;
}
```

**Responsibility.** Pointer capture, rAF-throttled delta emission, keyboard operation, `role="separator"` semantics per §1.4. Emits *deltas*, not absolute sizes — the parent owns the sizing policy and clamping, so the splitter stays dumb and reusable for both axes.

### 2.8 `image/ImagePanel.tsx`

```ts
export interface ImagePanelProps {
  imageId: Uuid;
}
```

**Responsibility.** Container. Runs `useImage(imageId)` and `useImageDisplayVariant(imageId)`; handles loading skeleton / error / empty; composes `PaneHeader` + `ImageViewer` + `ViewerControls` + `ImageStatusBar`. Owns the decision of **which display variant to load** (§5.1) based on `devicePixelRatio` and pane size, and re-requests a higher variant when the user zooms past 100% of the current variant (progressive refinement — the cheap variant is never *replaced* in coordinate terms because all coordinates are original-space; only `displayScale` changes, and it changes atomically with the bitmap swap).

### 2.9 `image/ImageViewer.tsx`

```ts
export interface ImageViewerProps {
  variant: ImageDisplayVariant;         // carries width/height/url + originalWidth/originalHeight
  annotations: Annotation[];
  gcps: Gcp[];
  activeTool: ToolId;
  selectedIds: string[];
  hoveredId: string | null;
  readOnly?: boolean;
  onCommand: (cmd: AnnotationCommand) => void;
  onSelect: (ids: string[], mode: SelectionMode) => void;
  onHover: (id: string | null) => void;
}
```

**Responsibility.** The Konva `Stage`. Owns:
- The stage transform (`scale`, `x`, `y`) — read from and written to `viewerStore`, with the invariants of §5.
- Wheel/pinch zoom-to-cursor (§5.4), drag-pan with clamping (§5.5), fit-to-view (§5.6).
- The **two-stage coordinate conversion** (§5.2/5.3) — this component is the *only* place in the codebase permitted to convert between stage and image space. All conversions go through `lib/viewport/transform.ts`; the functions are pure and unit-tested, and no other component imports them for mutation purposes.
- Hit-testing delegation to Konva; translation of pointer events into `AnnotationCommand`s (never direct state mutation — §4).
- Layer order (bottom→top): `ImageLayer` → `AnnotationLayer` → overlay layer (`CrosshairCursor`, `MagnifierLoupe`, selection marquee).
- `role="application"` on the container with the ARIA contract of §8.8.

Explicitly **not** responsible for: what an annotation *means*, persistence, undo stacks. It emits commands.

### 2.10 Image sub-components

**`image/ImageLayer.tsx` (pure)**
```ts
export interface ImageLayerProps {
  image: HTMLImageElement | ImageBitmap;
  displayWidth: number;
  displayHeight: number;
  filterCss: string;                    // e.g. 'brightness(1.15) contrast(0.9)'
}
```
A dedicated `Layer` containing exactly one `Konva.Image`. Isolated onto its own layer *specifically* so the CSS filter of §6 applies to the imagery and not to the annotations. `listening={false}` — the image never needs hit detection, which halves the hit-graph cost on large rasters.

**`image/AnnotationLayer.tsx`**
```ts
export interface AnnotationLayerProps {
  annotations: Annotation[];
  gcps: Gcp[];
  scale: number;                        // stage scale — for inverse-scaling stroke widths & handles
  displayScale: number;                 // §5.1
  selectedIds: string[];
  hoveredId: string | null;
  activeTool: ToolId;
  readOnly: boolean;
  onCommand: (cmd: AnnotationCommand) => void;
  onSelect: (ids: string[], mode: SelectionMode) => void;
  onHover: (id: string | null) => void;
}
```
Renders one `AnnotationShape` per annotation and `VertexHandle`s for the selected one. **Inverse-scales all screen-affine chrome**: stroke widths, handle radii, hit-stroke widths, and label font sizes are divided by `(scale * displayScale)` so a vertex handle is always ~8 CSS px regardless of zoom. This is the correct way to keep chrome usable at 10% and at 800% zoom, and it is where naive implementations produce invisible handles when zoomed out and boulder-sized handles when zoomed in.

**`gcp/GcpCardList.tsx` (pure)** — referenced from §1.5, the `xs` rendering of the table:
```ts
export interface GcpCardListProps {
  rows: GcpTableRow[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onAdjust: (id: string) => void;
}
```
One MUI `Card` per GCP: Point ID + confidence chip in the header, a 2×2 grid of `Image X/Y` and `Lat/Lon` in the body, actions in the footer. A 6-column data grid at 375px is unreadable; a card list is the honest mobile representation of the same data.

**`image/ViewerControls.tsx` (pure)**
```ts
export interface ViewerControlsProps {
  scale: number;
  minScale: number;
  maxScale: number;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onFit: () => void;
  onActualSize: () => void;             // scale such that 1 original px = 1 CSS px
  onToggleFullscreen: () => void;
  isFullscreen: boolean;
  brightness: number;
  contrast: number;
  onBrightnessChange: (v: number) => void;
  onContrastChange: (v: number) => void;
  onResetAdjustments: () => void;
}
```

**`image/BrightnessContrastControl.tsx` (pure)** — two sliders + reset, `-100..+100` UI range mapped to CSS filter values per §6.4. Live `aria-valuetext` ("brightness 15% above normal").

**`image/MagnifierLoupe.tsx` (pure)**
```ts
export interface MagnifierLoupeProps {
  visible: boolean;
  stagePoint: Point2D;                  // stage coords of the touch
  imagePoint: Point2D;                  // ORIGINAL image px, for the readout
  magnification: number;                // default 4
  radius: number;                       // default 56 CSS px
  sourceCanvas: HTMLCanvasElement;
}
```
Per §1.5 invariant 6.

**`image/ImageStatusBar.tsx` (pure)** — zoom %, live cursor position **in original image pixels** (the readout that lets a surveyor sanity-check P2 at a glance), image dimensions, EXIF-GPS presence indicator.

### 2.11 `annotation/AnnotationToolbar.tsx`

```ts
export interface AnnotationToolbarProps {
  orientation: 'vertical' | 'horizontal';
  activeTool: ToolId;
  onToolChange: (tool: ToolId) => void;
  canUndo: boolean;
  canRedo: boolean;
  undoLabel: string | null;             // e.g. "Undo Add point P4"
  redoLabel: string | null;
  onUndo: () => void;
  onRedo: () => void;
  canDelete: boolean;
  onDelete: () => void;
  disabled?: boolean;
}
```

**Responsibility.** The ToolRail (§1.3). `ToggleButtonGroup` for the four modes (`cursor`, `point`, `polygon`, `polyline`), divider, then `undo`/`redo`/`delete`. Every button carries its shortcut in the tooltip (`V`, `P`, `G`, `L`, `⌘Z`, `⇧⌘Z`, `Del`) — discoverable shortcuts are how this tool becomes fast for a professional. Undo/redo tooltips name the *specific* action from the command's `label` (§4.1), so the user knows what they are about to undo before they do it. `orientation` prop is what lets the same component serve the desktop rail and the mobile chip row.

### 2.12 `annotation/AnnotationInspector.tsx`

```ts
export interface AnnotationInspectorProps {
  selection: Annotation[];
  gcpFor: (annotationId: string) => Gcp | undefined;
  onCommand: (cmd: AnnotationCommand) => void;
  onOpenVersionHistory: () => void;
}
```

**Responsibility.** Contextual properties. Empty selection → tool options + match settings. Single point → label, notes, original-pixel X/Y (**editable numeric fields** — typing an exact pixel emits `MoveAnnotationCommand`; surveyors have pixel coordinates from other tools and must be able to key them in), matched lat/lon (read-only) + confidence + error radius. Polygon/polyline → vertex list with per-vertex coords, close/open toggle, simplify. Multi-select → bulk label prefix, bulk delete.

### 2.13 `annotation/LandmarkSuggestions.tsx`

```ts
export interface LandmarkSuggestionsProps {
  imageId: Uuid;
  onAccept: (suggestion: LandmarkSuggestion) => void;
  onAcceptAll: (suggestions: LandmarkSuggestion[]) => void;
  onDismiss: (id: string) => void;
}
```

**Responsibility.** Optional assistive panel. Calls `useLandmarkSuggestions(imageId)` — a query that is **`enabled` only when the backend reports the capability** (`useModelCapabilities()`, §3.2). With no SAM/DINOv2 weights present the backend reports `suggestions: false` and this component renders a quiet, non-alarming explainer ("Automatic landmark suggestions need optional AI models, which aren't installed. Mark landmarks manually — accuracy is unaffected.") rather than an error. Per P3 this is the *expected* default state on a fresh machine, and the copy must not imply breakage. Accepting a suggestion emits an `AddAnnotationCommand` — i.e. suggestions are ordinary undoable edits, with `source: 'suggested'` retained on the annotation for provenance.

### 2.14 `annotation/ManualAdjustMode.tsx`

```ts
export interface ManualAdjustModeProps {
  gcpId: Uuid;
  matchResultId: Uuid;
  onCommit: (adjustment: GcpAdjustment) => void;
  onCancel: () => void;
}
```

**Responsibility.** The escape hatch for when the algorithm is close but wrong. Enters a focused sub-mode: the selected GCP's satellite marker becomes draggable on the map, the image marker becomes draggable on the canvas, and a live readout shows the resulting residual against the current homography. Committing sends `POST /api/v1/gcps/{id}/adjust` with `{ imagePixel?, latLon?, pinned: boolean }`. A pinned/adjusted GCP is visually distinct (a pin glyph, not a diamond) everywhere, its confidence is displayed as `manual` rather than a number, and — critically — the adjustment is recorded so exports can distinguish algorithmic fixes from human overrides. Adjustments participate in the same undo stack via `AdjustGcpCommand`.

### 2.15 `annotation/VersionHistoryDrawer.tsx`

```ts
export interface VersionHistoryDrawerProps {
  open: boolean;
  imageId: Uuid;
  currentVersionId: Uuid | null;
  onClose: () => void;
  onPreview: (versionId: Uuid | null) => void;   // null = return to working draft
  onRestore: (versionId: Uuid) => void;
}
```

**Responsibility.** Right-anchored temporary `Drawer` listing `annotation_versions` newest-first: version number, author, timestamp, annotation count, change summary, and whether a match was run against it. Hovering previews that version on the canvas as a ghost overlay (`onPreview`); restoring is itself an undoable command (`RestoreVersionCommand`) that replaces the working draft. Restoring never destroys history — it appends. §4.6 covers the persistence protocol.

### 2.16 `map/MapPanel.tsx` + `map/SatelliteMap.tsx`

```ts
export interface MapPanelProps {
  imageId: Uuid | null;
  matchResultId: Uuid | null;
}

export interface SatelliteMapProps {
  view: MapViewState;
  basemap: BasemapKind;                 // 'satellite' | 'hybrid' | 'terrain'
  providers: ProviderDescriptor[];      // from the backend; drives the switcher AND attribution
  activeProviderId: ProviderId;
  gcps: Gcp[];
  footprint: LatLon[] | null;
  heatmapEnabled: boolean;
  selectedId: string | null;
  hoveredId: string | null;
  locationHint: LocationHint | null;
  onViewChange: (view: MapViewState, origin: ViewOrigin) => void;
  onSelect: (id: string) => void;
  onHover: (id: string | null) => void;
  onLocationHintChange: (hint: LocationHint | null) => void;
}
```

**Responsibility.** `MapContainer` + `TileLayer`. Per P3 and the legal constraint, **the frontend never hard-codes a tile URL**. It renders whatever `ProviderDescriptor[]` the backend returns from `GET /api/v1/providers` — each descriptor carries `id`, `label`, `kinds` (which of satellite/hybrid/terrain it can serve), `tileUrlTemplate` (proxied through the backend, so keys never reach the browser), `minZoom`, `maxZoom`, `attributionHtml`, `requiresKey`, `available`. The `BasemapSwitcher` shows only `kinds` the active provider supports, and providers with `available: false` are listed but disabled with the reason ("Mapbox — set `MAPBOX_TOKEN` to enable"). Swapping a provider changes `tileUrlTemplate` and attribution and **nothing else** — no GCP, no homography, no query key for match results depends on the provider, which is the frontend's half of the "swapping providers must not change the matching algorithm" contract.

`SatelliteMap` is otherwise a thin, controlled wrapper: it takes `view` as a prop and reports changes up. Leaflet's imperative view state is reconciled by `MapViewSync` (§2.19).

### 2.17 `map/GcpMarkerLayer.tsx` / `map/GcpMarker.tsx` (pure)

```ts
export interface GcpMarkerProps {
  gcp: Gcp;
  selected: boolean;
  hovered: boolean;
  onSelect: (id: string) => void;
  onHover: (id: string | null) => void;
}
```

Renders a `Marker` with a `divIcon`: a diamond (algorithmic) or pin (manually adjusted) filled with the confidence colour (§8.6), the Point ID label, and — when `gcp.errorRadiusM` is present — a **`Circle` of that radius in metres**. The error circle is not decoration: it is the visual statement that the fix is a distribution, not a point. Low-confidence markers additionally get a dashed stroke and a `⚠`. Selected markers get a halo + `zIndexOffset` so they win the stacking contest.

### 2.18 `map/ConfidenceHeatmapLayer.tsx`

```ts
export interface ConfidenceHeatmapLayerProps {
  enabled: boolean;
  matchResultId: Uuid;
  opacity: number;                      // default 0.55
}
```

**Responsibility.** Visualizes *where the match is trustworthy across the footprint*, not just at the GCPs — a homography estimated from clustered correspondences is precise near the cluster and degrades outward, and the surveyor must see that. Fetches a coarse confidence grid (`useConfidenceGrid(matchResultId)` → `{ bounds, rows, cols, values: number[] }`), rasterizes it client-side into an offscreen canvas with the diverging confidence ramp (§8.6.2), and mounts it as a Leaflet `ImageOverlay` over `bounds`. Canvas render is memoized on `(matchResultId, opacity, themeMode)`; the grid is small (≤64×64) so this is cheap and needs no WebGL. `imageRendering: auto` lets the browser smooth it — a smoothed field correctly signals "this is an estimate", where hard grid cells would imply false precision. Toggled from the map controls, off by default, disabled when no match exists.

### 2.19 `map/MapViewSync.tsx`

```ts
export interface MapViewSyncProps {
  view: MapViewState;
  onViewChange: (view: MapViewState, origin: ViewOrigin) => void;
  syncing: boolean;
}
```

**Responsibility.** The single reconciliation point between Leaflet's imperative view and `mapStore` (§3.6). Child of `MapContainer`, uses `useMap()`. Downward: when the `view` prop differs from the live map beyond an epsilon (1e-7° / 0.01 zoom) *and* the change did not originate from the map, calls `map.setView`/`flyTo`. Upward: subscribes to `moveend`/`zoomend` and emits `onViewChange(..., 'map')`. Carries the origin token and epsilon guard that make the loop of §1.6 terminate. Renders `null`. Isolating this is what prevents the classic react-leaflet oscillation bug; no other component may call `map.setView`.

### 2.20 `map/LocationHintControl.tsx`

```ts
export interface LocationHintControlProps {
  hint: LocationHint | null;
  exifHint: LatLon | null;
  onChange: (hint: LocationHint | null) => void;
}
```

**Responsibility.** How the user narrows the search. Three sources, in priority order: EXIF GPS (auto-detected, offered as a one-click chip "Use photo GPS: 41.872, -93.602"), draw-a-box on the map, or typed coordinates / place search. Emits a `LocationHint = { kind: 'bbox'|'point'|'none', bbox?, center?, radiusM? }` into `mapStore`, consumed by the match mutation. This is the direct remedy for the `no_location_hint` failure of §8.5.1 — the control is where that error's CTA lands.

### 2.21 `map/ProviderAttribution.tsx` (pure)

```ts
export interface ProviderAttributionProps {
  provider: ProviderDescriptor;
  compact?: boolean;
}
```

**Responsibility.** Renders `provider.attributionHtml` — sanitized, links `rel="noopener noreferrer"` — in the map's bottom-right. **Non-dismissible and never conditionally hidden**: attribution is a licence condition for every provider we support, so it is structural, not a feature flag. `compact` truncates with a `…` that expands on tap for `xs`, which is the maximum compression permitted. If `provider.attributionHtml` is empty the component renders the provider label rather than nothing.

### 2.22 `gcp/GcpTable.tsx`

```ts
export interface GcpTableProps {
  matchResultId: Uuid | null;
  imageId: Uuid;
}

export interface GcpTableRowProps {
  row: GcpTableRow;
  selected: boolean;
  hovered: boolean;
  coordinateFormat: CoordinateFormat;   // 'decimal' | 'dms'
  onSelect: (id: string, mode: SelectionMode) => void;
  onHover: (id: string | null) => void;
  onAdjust: (id: string) => void;
}
```

**Responsibility.** The mandated table, exactly those six columns in that order, plus a trailing action cell. Virtualized above 200 rows. Sortable on every column; default sort **confidence ascending** — the points needing attention are the ones the surveyor must see first, and burying them below the good ones is a safety failure. Header shows a count and a warning summary when any row is below threshold. Row click → `selectionStore.select` (cross-highlights both panes, §3.5). Row hover → `setHovered`. Keyboard: full grid navigation, `Enter` to select, `A` to adjust. Below `sm` it delegates to `GcpCardList`.

`ConfidenceCell` (pure) renders `ConfidenceBar` + numeric + band label — three redundant encodings (length, colour, text) so the cell survives colour-blindness and greyscale printing.
`CoordinateCell` (pure) applies the **precision policy** of §8.6.3 and formats decimal/DMS.

### 2.23 `export/ExportMenu.tsx` + `ExportDialog.tsx`

```ts
export interface ExportMenuProps {
  matchResultId: Uuid | null;
  gcpCount: number;
  lowConfidenceCount: number;
  disabled?: boolean;
}

export interface ExportDialogProps {
  open: boolean;
  matchResultId: Uuid;
  format: ExportFormat;
  onClose: () => void;
}
```

**Responsibility.** `ExportMenu` is the split button: CSV, GeoJSON, Shapefile, KML, PDF report. `ExportDialog` collects options (CRS, coordinate format, whether to include the satellite image, whether to include low-confidence points, PDF report title/notes) and fires `useCreateExport`. Export is a **job**, not a download: the mutation returns an `ExportJob`, the dialog shows `JobProgress`, and completion yields a signed artifact URL. Rationale: Shapefile and PDF generation are slow and server-side; treating export as a job unifies the UX and stops a 30-second PDF from looking like a hang.

**`LowConfidenceAcknowledgement` (pure)** is mandatory in the dialog whenever `lowConfidenceCount > 0`: an explicit checkbox — "I understand that N of M points are below the reliability threshold and are not survey-grade" — gating the export button. This is P1 made concrete: the product will not let a surveyor *silently* export an unreliable fix. It never blocks the export; it refuses to let it happen unnoticed. Excluded/flagged points are marked in every output format.

### 2.24 `job/JobProgress.tsx` (pure)

```ts
export interface JobProgressProps {
  job: MatchJob | ExportJob;
  variant: 'inline' | 'panel' | 'compact';
  onCancel?: () => void;
  onRetry?: () => void;
}
```

**Responsibility.** The canonical job renderer, used by the shell indicator, the map's matching overlay, and the export dialog. Determinate bar when `progress` is known, indeterminate otherwise; `JobPhaseStepper` shows the pipeline phases (`queued → fetching_tiles → extracting_features → matching → estimating_homography → transforming → done`) so a 40-second wait is legible rather than opaque. `JobErrorPanel` renders the typed `JobError` with its specific remedy (§8.5).

### 2.25 `upload/BatchUploadDialog.tsx`

```ts
export interface BatchUploadDialogProps {
  open: boolean;
  projectId: Uuid;
  onClose: () => void;
  onComplete: (imageIds: Uuid[]) => void;
}
```

**Responsibility.** Multi-file dropzone (`UploadDropzone`, pure) + a queue of `BatchUploadRow`s. Concurrency capped at 3 (field cellular is the design target). Per-row: thumbnail, filename, size, EXIF-GPS badge, progress, retry, remove. Client-side pre-validation (MIME allowlist, max dimension, max bytes) before any byte is sent — failing fast locally is a courtesy on a slow link. Uploads use `XMLHttpRequest` for real `upload.onprogress` (fetch still has no upload progress). Uploads are **not** React Query mutations for progress purposes; they are managed in an `uploadStore` (§3.7) and *invalidate* the images query on completion — a documented exception to P4, justified because progress is high-frequency ephemeral client state that must not thrash the query cache.

### 2.26 `common/*` (all pure)

- **`EmptyState`** — `{ icon, title, description, primaryAction?, secondaryAction? }`. Used by every pane's zero-data state (§8.1).
- **`ErrorBoundary`** — `{ fallback, onError, resetKeys }`. Instantiated at three levels: root, per-pane, per-panel. A Konva crash must not take out the map, and vice versa.
- **`ConfidenceChip` / `ConfidenceBar` / `UncertaintyBadge`** — the single source of truth for confidence rendering (§8.6). No component computes a confidence colour inline; they all call `confidenceBand()`.
- **`LiveRegion`** — `{ politeness, message }`. The `aria-live` announcer for canvas actions (§8.8).

---

## 3. State Architecture

### 3.0 The boundary

| | Server state (TanStack Query) | Client state (Zustand) |
| --- | --- | --- |
| **Owns** | Projects, images, persisted annotation versions, jobs, match results, GCPs, exports, providers, model capabilities | Tool selection, in-flight annotation draft, undo/redo stacks, viewer transform, brightness/contrast, map view, selection/hover, pane sizes, compare mode, upload queue |
| **Lifetime** | Cache; discardable and re-fetchable | Session; some slices persisted to `localStorage` |
| **Truth** | The backend | The user's current interaction |
| **Sync** | HTTP + polling | Synchronous |

The rule: **if it survives a hard refresh on another machine, it is server state.** The one deliberate overlap is the annotation draft (§3.4).

### 3.1 Query key factory — `src/api/queryKeys.ts`

```ts
export const qk = {
  all: ['landexplorer'] as const,

  providers: () => [...qk.all, 'providers'] as const,
  capabilities: () => [...qk.all, 'capabilities'] as const,

  projects: {
    all:    () => [...qk.all, 'projects'] as const,
    lists:  () => [...qk.projects.all(), 'list'] as const,
    list:   (f: ProjectFilters) => [...qk.projects.lists(), f] as const,
    details:() => [...qk.projects.all(), 'detail'] as const,
    detail: (id: Uuid) => [...qk.projects.details(), id] as const,
  },

  images: {
    all:     () => [...qk.all, 'images'] as const,
    lists:   () => [...qk.images.all(), 'list'] as const,
    list:    (projectId: Uuid) => [...qk.images.lists(), projectId] as const,
    details: () => [...qk.images.all(), 'detail'] as const,
    detail:  (id: Uuid) => [...qk.images.details(), id] as const,
    variant: (id: Uuid, v: VariantName) => [...qk.images.detail(id), 'variant', v] as const,
    exif:    (id: Uuid) => [...qk.images.detail(id), 'exif'] as const,
  },

  annotations: {
    all:      () => [...qk.all, 'annotations'] as const,
    forImage: (imageId: Uuid) => [...qk.annotations.all(), 'image', imageId] as const,
    versions: (imageId: Uuid) => [...qk.annotations.forImage(imageId), 'versions'] as const,
    version:  (imageId: Uuid, versionId: Uuid) =>
                [...qk.annotations.versions(imageId), versionId] as const,
    latest:   (imageId: Uuid) => [...qk.annotations.forImage(imageId), 'latest'] as const,
  },

  suggestions: {
    all:      () => [...qk.all, 'suggestions'] as const,
    forImage: (imageId: Uuid) => [...qk.suggestions.all(), 'image', imageId] as const,
  },

  jobs: {
    all:    () => [...qk.all, 'jobs'] as const,
    lists:  () => [...qk.jobs.all(), 'list'] as const,
    list:   (f: JobFilters) => [...qk.jobs.lists(), f] as const,
    details:() => [...qk.jobs.all(), 'detail'] as const,
    detail: (id: Uuid) => [...qk.jobs.details(), id] as const,
  },

  matches: {
    all:      () => [...qk.all, 'matches'] as const,
    forImage: (imageId: Uuid) => [...qk.matches.all(), 'image', imageId] as const,
    detail:   (id: Uuid) => [...qk.matches.all(), 'detail', id] as const,
    candidates:(id: Uuid) => [...qk.matches.detail(id), 'candidates'] as const,
    grid:     (id: Uuid) => [...qk.matches.detail(id), 'confidence-grid'] as const,
  },

  gcps: {
    all:        () => [...qk.all, 'gcps'] as const,
    forMatch:   (matchId: Uuid) => [...qk.gcps.all(), 'match', matchId] as const,
    detail:     (id: Uuid) => [...qk.gcps.all(), 'detail', id] as const,
  },

  exports: {
    all:      () => [...qk.all, 'exports'] as const,
    forMatch: (matchId: Uuid) => [...qk.exports.all(), 'match', matchId] as const,
    detail:   (id: Uuid) => [...qk.exports.all(), 'detail', id] as const,
  },
} as const;
```

The hierarchy is what makes invalidation surgical: `invalidateQueries({ queryKey: qk.gcps.forMatch(m) })` refetches one match's points; `qk.images.detail(id)` invalidates that image *and* its variant/exif children by prefix. Every key descends from `qk.all`, so a logout is one `removeQueries({ queryKey: qk.all })`.

### 3.2 Queries

| Hook | Key | Notes |
| --- | --- | --- |
| `useProviders()` | `qk.providers()` | `staleTime: Infinity`, `gcTime: Infinity`. Provider list changes only on server config change. |
| `useModelCapabilities()` | `qk.capabilities()` | `staleTime: 5min`. Drives progressive enhancement (§8.7). |
| `useProject(id)` | `qk.projects.detail(id)` | |
| `useImages(projectId)` | `qk.images.list(projectId)` | |
| `useImage(id)` | `qk.images.detail(id)` | |
| `useImageDisplayVariant(id, v)` | `qk.images.variant(id, v)` | `staleTime: Infinity` — an immutable derived raster. |
| `useAnnotationVersions(imageId)` | `qk.annotations.versions(imageId)` | Drives `VersionHistoryDrawer`. |
| `useLatestAnnotations(imageId)` | `qk.annotations.latest(imageId)` | Seeds the draft store on mount (§3.4). |
| `useLandmarkSuggestions(imageId)` | `qk.suggestions.forImage(imageId)` | `enabled: capabilities.suggestions === true`. |
| `useMatchJob(jobId)` | `qk.jobs.detail(jobId)` | **Polling**, see below. |
| `useMatchResult(matchId)` | `qk.matches.detail(matchId)` | `staleTime: Infinity` — a completed match is immutable. |
| `useMatchCandidates(matchId)` | `qk.matches.candidates(matchId)` | Lazy; only when the candidates drawer opens. |
| `useConfidenceGrid(matchId)` | `qk.matches.grid(matchId)` | `enabled: heatmapEnabled`. |
| `useGcps(matchId)` | `qk.gcps.forMatch(matchId)` | Mutable — adjustments write here. |
| `useExport(exportId)` | `qk.exports.detail(exportId)` | Polling, same policy as jobs. |

**Job polling policy** (the only polling in the app):

```ts
refetchInterval: (query) => {
  const job = query.state.data;
  if (!job || isTerminal(job.status)) return false;          // stop dead on terminal
  const age = Date.now() - new Date(job.createdAt).getTime();
  if (age < 10_000) return 1_000;                            // responsive at the start
  if (age < 60_000) return 2_000;
  return 5_000;                                              // backed off for long jobs
},
refetchIntervalInBackground: false,                          // a hidden tab burns no server
```

Terminal statuses are `succeeded | failed | cancelled`. **`isTerminal` returning `false` is a load-bearing invariant** — a bug here produces an infinite poll on a dead job, which is the classic way this pattern fails. It is unit-tested against every `JobStatus` member with an exhaustive `switch` + `never` check, so adding a status to the union is a compile error until the poller is updated.

On transition to `succeeded`, the `onSuccess` of the job query invalidates `qk.matches.forImage(imageId)` and `qk.gcps.forMatch(...)`, which is what makes the table populate without any manual refresh. A `WebSocket`/SSE upgrade is a drop-in future replacement: the same `onSuccess` body runs from a push handler and `refetchInterval` drops to `false`. The polling shape is deliberately chosen so that swapping transports touches one file.

**Global defaults** (`src/api/queryClient.ts`): `staleTime: 30_000`, `gcTime: 5min`, `retry: (n, e) => !isClientError(e) && n < 3` (never retry a 4xx), exponential backoff capped at 10s, `refetchOnWindowFocus: false` (a surveyor tabbing back must not trigger a tile-fetch storm on cellular).

### 3.3 Mutations

| Hook | Endpoint | Invalidates / effects |
| --- | --- | --- |
| `useCreateProject()` | `POST /api/v1/projects` | `qk.projects.lists()` |
| `useUploadImage()` | `POST /api/v1/images` | `qk.images.list(projectId)` |
| `useDeleteImage()` | `DELETE /api/v1/images/{id}` | optimistic removal from `qk.images.list`; rollback on error |
| `useSaveAnnotationVersion()` | `POST /api/v1/images/{id}/annotations` | `qk.annotations.forImage(id)`; clears `annotationStore.dirty` |
| `useRestoreAnnotationVersion()` | `POST /api/v1/images/{id}/annotations/{v}/restore` | `qk.annotations.forImage(id)`; replaces draft |
| `useStartMatch()` | `POST /api/v1/matches` | sets `jobId`; primes `qk.jobs.detail(jobId)` with the returned job so the poller starts warm rather than with a loading flash |
| `useCancelJob()` | `POST /api/v1/jobs/{id}/cancel` | optimistic `status: 'cancelling'` |
| `useAdjustGcp()` | `POST /api/v1/gcps/{id}/adjust` | **optimistic** on `qk.gcps.forMatch(matchId)` |
| `useUpdateGcpLabel()` | `PATCH /api/v1/gcps/{id}` | optimistic |
| `useCreateExport()` | `POST /api/v1/exports` | `qk.exports.forMatch(matchId)`; primes the export job |

**Optimistic update contract** (identical in every optimistic mutation, so it can be reviewed once):

```
onMutate:   await cancelQueries(key)            // no in-flight refetch may clobber us
            const prev = getQueryData(key)
            setQueryData(key, applyPatch)
            return { prev }
onError:    setQueryData(key, ctx.prev)         // exact rollback
            enqueueSnackbar(error, { variant: 'error' })
onSettled:  invalidateQueries(key)              // server is the arbiter, always
```

`useAdjustGcp` is optimistic because dragging a marker must feel instant. But note what is *not* optimistic: the **recomputed lat/lon of the other GCPs**. Adjusting one point re-estimates the homography server-side and moves every other point. We cannot predict that client-side, so during the mutation the other rows render a subtle `pending` shimmer and their coordinates are **dimmed, not stale-but-confident**. Showing a confidently-rendered stale coordinate would violate P1. The adjusted point itself moves optimistically; its neighbours honestly say "recomputing".

### 3.4 Zustand stores — exact shapes

All stores live in `src/state/`, are created with `create<T>()(devtools(immer(...)))`, and expose actions as methods on the store (no external action creators). Persisted stores are wrapped in `persist` with an explicit `partialize` and `version`.

#### `src/state/toolStore.ts`

```ts
export type ToolId = 'cursor' | 'point' | 'polygon' | 'polyline';

export interface ToolOptions {
  snapToVertex: boolean;
  snapRadiusPx: number;          // in ORIGINAL image px
  closePolygonOnDoubleClick: boolean;
  autoLabel: boolean;            // auto-name P1, P2, ... on create
  labelPrefix: string;           // default 'P'
}

export interface ToolState {
  activeTool: ToolId;
  previousTool: ToolId;          // for space-bar temporary pan / hold-to-cursor
  options: ToolOptions;
  setTool: (t: ToolId) => void;
  restorePreviousTool: () => void;
  setOption: <K extends keyof ToolOptions>(k: K, v: ToolOptions[K]) => void;
}
```
Persisted: `options` only.

#### `src/state/annotationStore.ts`

The heart of the client state. Holds the **working draft** in original-image-pixel space, plus the undo/redo stacks.

```ts
export interface AnnotationDraftState {
  imageId: Uuid | null;
  baseVersionId: Uuid | null;        // the server version this draft descends from
  byId: Record<string, Annotation>;  // keyed by client-side nanoid
  order: string[];                   // z-order / creation order
  nextOrdinal: number;               // for auto-labelling P1, P2, ...
}

export interface InProgressShape {                 // the polygon/polyline being drawn
  kind: 'polygon' | 'polyline';
  vertices: Point2D[];                             // ORIGINAL image px
  previewVertex: Point2D | null;                   // rubber-band to cursor
}

export interface AnnotationState {
  draft: AnnotationDraftState;
  inProgress: InProgressShape | null;
  undoStack: AnnotationCommand[];
  redoStack: AnnotationCommand[];
  dirty: boolean;
  lastSavedAt: number | null;
  previewVersionId: Uuid | null;     // non-null = viewing history, draft is frozen

  // lifecycle
  hydrate: (imageId: Uuid, version: AnnotationVersion | null) => void;
  reset: () => void;

  // the ONLY mutation path (§4)
  execute: (cmd: AnnotationCommand) => void;
  undo: () => void;
  redo: () => void;
  canUndo: () => boolean;
  canRedo: () => boolean;
  peekUndoLabel: () => string | null;
  peekRedoLabel: () => string | null;

  // in-progress shape building
  beginShape: (kind: 'polygon' | 'polyline', at: Point2D) => void;
  extendShape: (at: Point2D) => void;
  updatePreview: (at: Point2D | null) => void;
  commitShape: (close: boolean) => void;           // emits AddAnnotationCommand
  cancelShape: () => void;

  // history preview
  setPreviewVersion: (id: Uuid | null) => void;

  markSaved: (versionId: Uuid) => void;
}
```

Notes:
- `inProgress` is deliberately **outside** the command system. A half-drawn polygon is not an edit; only `commitShape` produces an undoable `AddAnnotationCommand`. This is why `Escape` cancels a drawing without polluting the undo stack — and why undo after a completed polygon removes the whole polygon rather than one vertex, which is what users expect.
- Not persisted to `localStorage`. The draft is autosaved to the server (§4.6); a `localStorage` copy would create a second, conflicting source of truth. Instead a `beforeunload` guard fires when `dirty` and the last autosave is unflushed.

#### `src/state/viewerStore.ts`

```ts
export interface ViewerTransform {
  scale: number;                 // stage scale: display px -> screen px
  x: number;                     // stage translation, screen px
  y: number;
}

export interface ImageAdjustments {
  brightness: number;            // UI range -100..100, 0 = neutral
  contrast: number;              // UI range -100..100, 0 = neutral
}

export interface ViewerState {
  transform: ViewerTransform;
  displayScale: number;          // displayWidth / originalWidth  (§5.1) — NOT user-controlled
  viewport: { width: number; height: number };
  naturalSize: { width: number; height: number } | null;   // ORIGINAL dims
  adjustments: ImageAdjustments;
  isFullscreen: boolean;
  cursorImagePos: Point2D | null;      // ORIGINAL image px, for the status bar
  minScale: number;
  maxScale: number;

  setTransform: (t: ViewerTransform) => void;
  zoomAt: (stagePoint: Point2D, factor: number) => void;   // §5.4
  panBy: (dx: number, dy: number) => void;                 // §5.5
  fitToView: () => void;                                   // §5.6
  zoomToActualSize: () => void;
  zoomToImageRect: (rect: Rect) => void;                   // used by "locate GCP" (§3.5)
  setViewport: (w: number, h: number) => void;
  setImageSource: (natural: Size, displayScale: number) => void;
  setAdjustment: (k: keyof ImageAdjustments, v: number) => void;
  resetAdjustments: () => void;
  setFullscreen: (v: boolean) => void;
  setCursorImagePos: (p: Point2D | null) => void;
}
```
Persisted: `adjustments` only. The transform is per-image-session and resets to fit on image change.

`displayScale` living in the store — rather than being threaded as a prop — is deliberate: it is an input to *every* coordinate conversion, and a single store-owned value that changes atomically with `setImageSource` is far safer than a prop that can be stale by one render during a variant swap. See §5.1.

#### `src/state/mapStore.ts`

```ts
export type BasemapKind = 'satellite' | 'hybrid' | 'terrain';
export type ViewOrigin = 'map' | 'image' | 'app' | 'sync';

export interface MapViewState {
  center: LatLon;
  zoom: number;
  bearing: 0;                    // reserved; Leaflet raster is north-up (2D UX constraint)
}

export interface MapState {
  view: MapViewState;
  lastOrigin: ViewOrigin;
  seq: number;                   // monotonic; the anti-feedback token (§1.6)
  basemap: BasemapKind;
  providerId: ProviderId | null; // null = backend default (keyless)
  heatmapEnabled: boolean;
  footprintVisible: boolean;
  locationHint: LocationHint | null;
  isDrawingHint: boolean;

  setView: (v: MapViewState, origin: ViewOrigin) => void;
  flyToGcp: (gcp: Gcp) => void;
  fitBounds: (b: BBox, origin: ViewOrigin) => void;
  setBasemap: (b: BasemapKind) => void;
  setProvider: (id: ProviderId | null) => void;
  toggleHeatmap: () => void;
  toggleFootprint: () => void;
  setLocationHint: (h: LocationHint | null) => void;
  setDrawingHint: (v: boolean) => void;
}
```
Persisted: `basemap`, `providerId`, `heatmapEnabled`, `footprintVisible`.

#### `src/state/selectionStore.ts`

The cross-pane sync bus. Small on purpose — it is read by three panes and must not cause wide re-renders.

```ts
export type EntityKind = 'annotation' | 'gcp';
export type SelectionMode = 'replace' | 'toggle' | 'range';

export interface SelectionRef {
  kind: EntityKind;
  id: string;                    // annotation clientId or gcp Uuid
  linkedId: string | null;       // the gcp<->annotation counterpart
}

export interface SelectionState {
  selected: SelectionRef[];
  hovered: SelectionRef | null;
  anchorId: string | null;       // for shift-range selection in the table
  focusOrigin: 'image' | 'map' | 'table' | null;   // who initiated (§3.5)

  select: (ref: SelectionRef, mode: SelectionMode, origin: SelectionState['focusOrigin']) => void;
  selectMany: (refs: SelectionRef[], origin: SelectionState['focusOrigin']) => void;
  clear: () => void;
  setHovered: (ref: SelectionRef | null) => void;
  isSelected: (id: string) => boolean;
}
```

#### `src/state/workspaceStore.ts`

```ts
export type WorkspaceTab = 'image' | 'map' | 'points';

export interface PaneSizes {
  imageFr: number;               // flexible, fractional (default 1)
  mapFr: number;                 // flexible, fractional (default 1)
  inspectorPx: number;           // fixed (default 280)
  dockPx: number;                // fixed (default 240)
}

export interface WorkspaceState {
  paneSizes: PaneSizes;
  inspectorOpen: boolean;
  dockOpen: boolean;
  activeTab: WorkspaceTab;
  versionDrawerOpen: boolean;
  coordinateFormat: CoordinateFormat;

  setPaneSizes: (p: Partial<PaneSizes>) => void;
  resetPaneSizes: () => void;
  toggleInspector: () => void;
  toggleDock: () => void;
  setActiveTab: (t: WorkspaceTab) => void;
  setVersionDrawerOpen: (v: boolean) => void;
  setCoordinateFormat: (f: CoordinateFormat) => void;
}
```
Persisted in full, `version: 1`, with a validating `merge` that discards unknown shapes.

#### `src/state/compareStore.ts`

```ts
export type CompareSyncMode = 'none' | 'linked' | 'swipe';

export interface CompareState {
  active: boolean;
  syncMode: CompareSyncMode;
  curtainX: number;              // 0..1, for 'swipe'
  syncing: boolean;              // one-frame re-entrancy guard (§1.6)
  setActive: (v: boolean) => void;
  setSyncMode: (m: CompareSyncMode) => void;
  setCurtainX: (v: number) => void;
  beginSync: () => void;
  endSync: () => void;
}
```

#### `src/state/uploadStore.ts`

```ts
export type UploadStatus = 'queued' | 'uploading' | 'processing' | 'done' | 'error' | 'cancelled';

export interface UploadItem {
  clientId: string;
  file: File;
  previewUrl: string;            // object URL; revoked on removal
  status: UploadStatus;
  progress: number;              // 0..1
  bytesSent: number;
  imageId: Uuid | null;
  error: ApiError | null;
  exifHint: LatLon | null;
  xhr?: XMLHttpRequest;
}

export interface UploadState {
  items: UploadItem[];
  concurrency: number;           // default 3
  enqueue: (files: File[]) => void;
  start: () => void;
  cancel: (clientId: string) => void;
  retry: (clientId: string) => void;
  remove: (clientId: string) => void;
  clearCompleted: () => void;
}
```

### 3.5 Cross-pane selection & hover sync — how a row lights up three places

Selecting `P3` in the `GcpTable` must highlight it in the image *and* the map. The mechanism is one store and zero cross-component wiring:

1. `GcpTableRow` `onClick` → `selectionStore.select({ kind: 'gcp', id: gcpId, linkedId: annotationClientId }, 'replace', 'table')`.
2. Every pane subscribes with a **narrow selector**: `useSelectionStore(s => s.selected.some(r => r.id === myId || r.linkedId === myId))`. Zustand's default `Object.is` equality on a boolean means a row/marker/shape re-renders only when *its own* selected-ness flips — selecting P3 does not re-render P1's marker.
3. `AnnotationLayer` renders the linked annotation with the selected style and vertex handles.
4. `GcpMarkerLayer` renders the marker with a halo + raised z-index.
5. **Reveal on demand, driven by `focusOrigin`** — the subtle part. A selection made in the table should bring the point into view in *both* other panes; a selection made by clicking the map should not yank the map. So each pane runs an effect: `if (selected && focusOrigin !== 'map') mapStore.flyToGcp(gcp)` and `if (selected && focusOrigin !== 'image') viewerStore.zoomToImageRect(bboxAround(annotation))`. A pane never auto-scrolls in response to its own action, which is what prevents the "the map fights me when I click it" feeling.
6. On `sm`/`xs`, `zoomToImageRect`/`flyToGcp` are queued and applied on tab activation (via the same `ResizeObserver` visibility hook of §1.5), so tapping a card and switching to Map lands on the point.

Hover is the same path, `setHovered`, but throttled to one rAF and never triggering reveal. Hover produces a pulse animation in the counterpart panes.

`linkedId` is populated when the match result is loaded: each `Gcp` carries `sourceAnnotationId`, so the table row knows its annotation and vice-versa. This is the only join the frontend performs, and it is materialized once in a `useGcpRows(matchId)` selector hook rather than recomputed per component.

### 3.6 How the map "synchronizes with application state"

Leaflet owns an imperative view; React owns a declarative one. Reconciling them naively produces oscillation. The contract:

- **`mapStore.view` is the single source of truth.** `SatelliteMap` renders `<MapContainer>` **uncontrolled** (`center`/`zoom` are initial values only — Leaflet ignores prop changes for these anyway) and delegates all view reconciliation to `MapViewSync` (§2.19).
- **Downward** (`app → map`): `MapViewSync` diffs `view` against `map.getCenter()/getZoom()` with an epsilon and, if it differs *and* `lastOrigin !== 'map'`, calls `setView`/`flyTo`.
- **Upward** (`map → app`): `moveend`/`zoomend` → `setView(next, 'map')`. Because `lastOrigin` is now `'map'`, the downward effect no-ops. The loop terminates in one pass.
- **The epsilon is doing real work.** Leaflet rounds coordinates; a naive equality check makes `setView` fire forever on a value that never converges. `1e-7°` (~1cm) and `0.01` zoom are below any perceptible or meaningful threshold.
- **`seq`** guards the async case: `flyTo` animates over ~500ms and emits intermediate `move` events. Each `setView` bumps `seq`; a `moveend` carrying a stale `seq` is dropped.
- Compare mode's homography coupling (§1.6) writes with `origin: 'sync'`, which both panes treat as external — so a linked pan updates both without either re-emitting.

### 3.7 Re-render discipline

- Zustand subscriptions are always **selector-scoped**; `useStore()` with no selector is banned by lint rule (`no-restricted-syntax`).
- Object/array selectors use `useShallow`.
- The Konva stage does not re-render on every store change: `ImageViewer` subscribes to `transform` and passes it to Konva imperatively via `stageRef.current.scale()/position()` inside a `useLayoutEffect` for **drag/zoom frames**, and only commits to the store on gesture end. During a wheel-zoom or a drag, React renders zero times; the store is updated once at `pointerup`. This is what keeps a 5472×3648 image at 60fps.
- Same pattern for hover: transient hover is drawn by mutating Konva node attrs directly + `layer.batchDraw()`, with the store updated at rAF cadence only for cross-pane sync.

---

## 4. Undo / Redo — the command pattern

### 4.1 The `Command` interface

`src/lib/commands/types.ts`

```ts
export type CommandType =
  | 'annotation.add'
  | 'annotation.delete'
  | 'annotation.move'
  | 'annotation.edit'          // label/notes/metadata
  | 'annotation.vertex.add'
  | 'annotation.vertex.move'
  | 'annotation.vertex.delete'
  | 'annotation.reorder'
  | 'gcp.adjust'
  | 'version.restore';

export interface CommandContext {
  imageId: Uuid;
  now: number;
}

export interface Command<TPayload = unknown> {
  readonly id: string;                 // nanoid
  readonly type: CommandType;
  readonly label: string;              // human-readable: "Add point P4"
  readonly timestamp: number;
  readonly payload: TPayload;

  /** Merge window key. Two commands may coalesce only if both are non-null and equal. */
  readonly mergeKey: string | null;

  apply(draft: AnnotationDraftState, ctx: CommandContext): void;   // immer draft, mutate freely
  revert(draft: AnnotationDraftState, ctx: CommandContext): void;

  /** May `next` be absorbed into `this`? Called only when mergeKeys match. */
  canMerge?(next: Command): boolean;
  /** Return a NEW command representing this∘next. Must be pure. */
  merge?(next: Command): Command;

  /** Serialized form for the server's annotation_versions.change_log. */
  serialize(): SerializedCommand;
}

export interface SerializedCommand {
  id: string;
  type: CommandType;
  label: string;
  timestamp: number;
  payload: unknown;
}

export type AnnotationCommand = Command<any>;
```

**Design choice: `apply`/`revert` over `apply`/`inverse`.** Each command carries *both* the before-state and after-state fragments it needs in its payload, so `revert` is exact and self-contained — it does not have to reconstruct the prior state by inspecting the current one. This makes commands independently testable (`apply` then `revert` on any draft must be the identity — a property test asserts this for every command type against generated drafts) and immune to the classic bug where reverting depends on state that a later command changed.

### 4.2 Command payloads

`src/lib/commands/annotationCommands.ts` — one factory per type.

```ts
export interface AddAnnotationPayload    { annotation: Annotation; index: number }
export interface DeleteAnnotationPayload { annotations: Annotation[]; indices: number[] }   // bulk-capable
export interface MoveAnnotationPayload   { id: string; from: Point2D[]; to: Point2D[] }     // all vertices; point = length 1
export interface EditAnnotationPayload   { id: string; before: Partial<Annotation>; after: Partial<Annotation> }
export interface VertexAddPayload        { id: string; index: number; vertex: Point2D }
export interface VertexMovePayload       { id: string; index: number; from: Point2D; to: Point2D }
export interface VertexDeletePayload     { id: string; index: number; vertex: Point2D }
export interface ReorderPayload          { id: string; from: number; to: number }
export interface AdjustGcpPayload        { gcpId: Uuid; before: GcpAdjustment | null; after: GcpAdjustment }
export interface RestoreVersionPayload   { versionId: Uuid; before: AnnotationDraftState; after: AnnotationDraftState }

export const createAddAnnotation:    (a: Annotation, index?: number) => Command<AddAnnotationPayload>;
export const createDeleteAnnotations:(as: Annotation[], draft: AnnotationDraftState) => Command<DeleteAnnotationPayload>;
export const createMoveAnnotation:   (id: string, from: Point2D[], to: Point2D[]) => Command<MoveAnnotationPayload>;
export const createEditAnnotation:   (id: string, before: Partial<Annotation>, after: Partial<Annotation>) => Command<EditAnnotationPayload>;
export const createVertexAdd:        (id: string, index: number, v: Point2D) => Command<VertexAddPayload>;
export const createVertexMove:       (id: string, index: number, from: Point2D, to: Point2D) => Command<VertexMovePayload>;
export const createVertexDelete:     (id: string, index: number, v: Point2D) => Command<VertexDeletePayload>;
export const createAdjustGcp:        (gcpId: Uuid, before: GcpAdjustment | null, after: GcpAdjustment) => Command<AdjustGcpPayload>;
export const createRestoreVersion:   (versionId: Uuid, before: AnnotationDraftState, after: AnnotationDraftState) => Command<RestoreVersionPayload>;
```

**All `Point2D` values in every payload are ORIGINAL image pixels** (P2). A command never sees a stage coordinate; the conversion happens at the event boundary in `ImageViewer` and nowhere else.

`createDeleteAnnotations` takes the draft so it can capture indices for exact positional restore — undoing a delete must put the annotation back *where it was* in z-order, not append it.

### 4.3 Stack semantics

```
execute(cmd):
  1. if previewVersionId !== null -> reject (history preview is read-only)
  2. cmd.apply(draft)
  3. top = undoStack.at(-1)
     if top && top.mergeKey && top.mergeKey === cmd.mergeKey && top.canMerge?.(cmd):
        undoStack[len-1] = top.merge(cmd)          // coalesce, do NOT push
     else:
        undoStack.push(cmd)
        if undoStack.length > MAX_UNDO (200): undoStack.shift()
  4. redoStack = []                                 // new action forks the future
  5. dirty = true; scheduleAutosave()

undo():
  cmd = undoStack.pop(); if (!cmd) return
  cmd.revert(draft); redoStack.push(cmd)
  dirty = true; scheduleAutosave()

redo():
  cmd = redoStack.pop(); if (!cmd) return
  cmd.apply(draft); undoStack.push(cmd)
  dirty = true; scheduleAutosave()
```

- `MAX_UNDO = 200`, FIFO eviction. Commands hold small payloads (a polygon's vertices at worst), so 200 is bounded memory.
- **Stacks are cleared on `hydrate`** (image change / version restore establishes a new baseline). Carrying a stack across images would let an undo apply a command to an annotation that does not exist.
- `RestoreVersionCommand` is itself undoable — it snapshots the whole prior draft in its payload. Restoring a version and immediately undoing returns to exactly the pre-restore draft.
- Undo/redo are **not** invalidated by an autosave. Saving a version is a checkpoint, not a barrier; a surveyor may save and then undo. The next autosave simply records the newer state.

### 4.4 Coalescing drags

A drag emits `pointermove` at up to 120Hz. Pushing one `VertexMoveCommand` per event would make a single drag take 400 undos to reverse — a classic and infuriating bug.

Rules:
1. **`mergeKey` scopes the window**: `` `move:${annotationId}` `` / `` `vertex:${annotationId}:${index}` ``. Different targets never merge.
2. **The drag emits exactly one command at `pointerup`**, not per move. During the drag, `ImageViewer` mutates the Konva node directly (no store write, no command) and holds `dragStartPoints`. On `pointerup` it emits one `createMoveAnnotation(id, dragStartPoints, finalPoints)`. This alone solves the common case, and it is the primary mechanism.
3. **`canMerge` handles the rest** — keyboard nudges (`ArrowLeft` ×20) and Inspector numeric-field typing, which arrive as discrete commands. `canMerge` returns true when `mergeKey` matches **and** `next.timestamp - this.timestamp < 600ms`. `merge` produces `createMoveAnnotation(id, this.payload.from, next.payload.to)` — origin from the first, destination from the last. Twenty nudges collapse to one undo of the whole gesture; pausing for a second starts a new undo entry, which matches the user's mental model of a "gesture".
4. **Merging is only ever with `undoStack.at(-1)`.** Never scan deeper.
5. `EditAnnotationCommand` on a text field uses the same 600ms window with `` mergeKey = `edit:${id}:${field}` ``, so typing a label is one undo, not one-per-keystroke.
6. **Selection changes are not commands** and never enter the stack. Undo must not "undo" a click. (It *does* restore selection as a side effect: each command's `revert` also restores the selection that existed when it was created, stored in a non-payload field, because undoing a delete and not re-selecting the restored point is disorienting.)

### 4.5 Command → server: the persistence protocol

`annotation_versions` is append-only and stores **full snapshots plus a change log**, not a command stream. Rationale: snapshots make version restore O(1) and make the backend independent of frontend command semantics — the backend must never have to *replay* frontend commands to know what an annotation set is. The command log rides along as human-readable provenance (`change_log`), which is what powers the version drawer's "Added 3 points, moved P2" summary.

### 4.6 Autosave

```
scheduleAutosave():   debounce 2000ms trailing, plus a hard 30s max-wait ceiling
flushAutosave():      immediately on — blur of the window, tab change, match start,
                      export open, version drawer open, route change, beforeunload
```

`useSaveAnnotationVersion()` POSTs:

```jsonc
{
  "baseVersionId": "<the version this draft descends from, or null>",
  "annotations": [ /* full snapshot, ORIGINAL pixel coords */ ],
  "changeLog": [ /* SerializedCommand[] since baseVersionId */ ],
  "clientCommandCursor": "<id of the last command included>"
}
```

- Response returns the new `AnnotationVersion`; the store calls `markSaved(versionId)`, sets `baseVersionId = versionId`, clears `dirty`, and **truncates `changeLog` at `clientCommandCursor`** (the undo stack itself is untouched — §4.3).
- **Conflict**: if `baseVersionId` is not the server's head (another session saved), the server returns `409` with the head version. The UI does not silently merge and does not silently clobber. It surfaces a non-blocking banner — "This image was edited elsewhere. [Review changes] [Keep mine] [Take theirs]" — and pauses autosave until resolved. Annotations are survey inputs; a silent lost-update here is a data-integrity failure, not an inconvenience.
- **Match jobs always run against a saved version.** `useStartMatch` awaits `flushAutosave()` and sends the resulting `versionId`. This guarantees every `match_results` row references an immutable, reproducible annotation set — the reproducibility contract for the whole product. A match can always be explained by pointing at the exact version it consumed.

---

## 5. The Image Viewer math

> This section is the correctness core of the frontend. Everything here is implemented in `src/lib/viewport/transform.ts` as **pure functions with no React and no Konva imports**, and is exhaustively unit-tested (including property tests for round-trip identity). No component may inline any of this arithmetic.

### 5.1 The two-stage transform — why the naive version is wrong

A 5472×3648 upload is not what the browser draws. The backend produces **display variants** (`thumb` 512px, `preview` 2048px, `full` 4096px on the long edge) because pushing a 40MB raster to a tablet on cellular is not viable, and because Canvas has per-browser max-texture limits (Safari iOS will silently fail well below 16384px).

So there are **two** scales, and conflating them is *the* bug this section exists to prevent:

| Symbol | Meaning | Source |
| --- | --- | --- |
| `D` (`displayScale`) | `variant.width / original.width` — e.g. `2048/5472 = 0.37427...` | Server metadata; changes only on variant swap |
| `s` (`transform.scale`) | Konva stage scale — user zoom | `viewerStore` |
| `(tx, ty)` | Konva stage position — user pan, screen px | `viewerStore` |

Three coordinate spaces:

```
ORIGINAL image px  ──× D──▶  DISPLAY raster px  ──× s, + (tx,ty)──▶  STAGE/screen px
   (5472×3648)                   (2048×1365)                          (viewport)
   ▲ the ONLY space               ▲ what Konva.Image                   ▲ what pointer
     ever stored                    actually holds                       events give us
```

The Konva `Stage` has `scale = s` and `position = (tx, ty)`. The `Konva.Image` inside it is drawn at `(0,0)` with `width/height` equal to the **display variant's** dimensions. Therefore a stored annotation at original-pixel `(4000, 3000)` must be *rendered* at display coords `(4000·D, 3000·D)`, and Konva applies `s`/`(tx,ty)` on top.

**The naive bug**: read `stage.getPointerPosition()`, divide by `s`, subtract the pan, store it. That yields **display** pixels, not original pixels. It looks perfect until someone loads a different variant — then every annotation silently jumps by a factor of `D₁/D₂`. It also produces coordinates that disagree with the backend's, which computed features on the original. Because `D ≈ 1` on small test images, this bug reliably survives development and detonates on the first real 5000px upload.

**The rule**: `D` is in the pipeline **always**, even when it equals 1.

### 5.2 The conversion functions

`src/lib/viewport/transform.ts`

```ts
export interface Point2D { x: number; y: number }
export interface Size { width: number; height: number }
export interface Rect { x: number; y: number; width: number; height: number }

export interface ViewerTransform { scale: number; x: number; y: number }

/** Everything needed for a conversion. Passed explicitly — never read from a store here. */
export interface ViewportContext {
  transform: ViewerTransform;   // s, tx, ty
  displayScale: number;         // D
  naturalSize: Size;            // ORIGINAL dims
  viewport: Size;               // container CSS px
}

// ── Stage/screen  ->  ORIGINAL image ────────────────────────────────────────
export function stageToImage(p: Point2D, ctx: ViewportContext): Point2D;
//   display.x = (p.x - tx) / s
//   image.x   = display.x / D
//   ∴ image.x = (p.x - tx) / (s * D)
//     image.y = (p.y - ty) / (s * D)

// ── ORIGINAL image  ->  Stage/screen ────────────────────────────────────────
export function imageToStage(p: Point2D, ctx: ViewportContext): Point2D;
//   stage.x = p.x * D * s + tx
//   stage.y = p.y * D * s + ty

// ── ORIGINAL image  ->  DISPLAY raster (what Konva nodes are positioned in) ─
export function imageToDisplay(p: Point2D, D: number): Point2D;   // { x: p.x*D, y: p.y*D }
export function displayToImage(p: Point2D, D: number): Point2D;   // { x: p.x/D, y: p.y/D }

// ── Effective scale: ORIGINAL px -> screen px. The number to inverse-scale chrome by.
export function effectiveScale(ctx: ViewportContext): number;      // s * D

// ── Rect helpers
export function imageRectToStage(r: Rect, ctx: ViewportContext): Rect;
export function stageRectToImage(r: Rect, ctx: ViewportContext): Rect;

// ── Visible region of the ORIGINAL image, for culling and for compare-mode sync
export function visibleImageRect(ctx: ViewportContext): Rect;

// ── Guards
export function clampToImageBounds(p: Point2D, natural: Size): Point2D;
export function isWithinImage(p: Point2D, natural: Size): boolean;
```

**Critical rendering consequence.** `AnnotationLayer` positions Konva nodes in **display** space (`imageToDisplay`), because they are children of the Stage and Konva applies `s`/`(tx,ty)` for us. It must *not* use `imageToStage` for node positions — that would double-apply the stage transform. `imageToStage` exists for **DOM overlays** that live outside the Stage (tooltips, the loupe, HTML labels), which do not inherit the Konva transform. Getting this backwards produces annotations that drift at 2× the pan rate — a distinctive symptom worth naming here so a reviewer recognizes it instantly.

**The one place pointer events are converted:**

```
onPointerDown/Move/Up in ImageViewer:
   const sp = stage.getPointerPosition();      // stage container coords, DPR already handled by Konva
   const ip = stageToImage(sp, ctx);           // ORIGINAL image px  ← the ONLY conversion site
   // ip is what goes into commands, stores, and the network. sp is discarded.
```

**Device pixel ratio**: Konva handles DPR internally (`Konva.pixelRatio`), and `getPointerPosition()` returns CSS-pixel stage coordinates. DPR therefore never appears in these formulas. It is called out because hand-rolled canvas code needs it and a reader might expect it — introducing DPR here would be a bug.

**Round-trip invariant** (property-tested with fast-check over random `s ∈ [0.01, 40]`, `D ∈ (0, 1]`, `tx/ty ∈ [-10⁵, 10⁵]`, `p ∈ [0, 10⁵]²`):

```
stageToImage(imageToStage(p, ctx), ctx) ≈ p    within 1e-6
imageToStage(stageToImage(q, ctx), ctx) ≈ q    within 1e-6
```

Doubles carry ~15 significant digits; the largest realistic magnitudes are ~10⁵ px × 40 scale ≈ 4×10⁶, leaving ample headroom. 1e-6 px is a sub-nanometre claim on any real field of view — the tolerance is about float noise, not about accuracy.

**Sub-pixel policy**: image coordinates are **never rounded**. Stored as `number` (double), sent as JSON floats, displayed to 1 decimal. A homography estimated from integer-rounded correspondences carries needless error, and rounding at the UI layer would be a silent accuracy tax on every point. Round for display, never for storage.

### 5.3 Variant swapping without moving anything

When `ImagePanel` upgrades `preview` → `full`, `D` changes (0.374 → 0.749). If `s` were left alone, the image would visibly double in size. To keep the view *pinned*, compensate:

```
s' = s * (D_old / D_new)
```

`(tx, ty)` are unchanged **iff** the compensation is anchored at the stage origin — but the stage origin is the image's top-left, so a pure `s` compensation keeps the top-left pinned, not the viewport centre. The correct operation anchors at the viewport centre `c`:

```
c_img  = stageToImage(viewportCenter, ctx_old)     // capture BEFORE the swap, in ORIGINAL px
s'     = s * D_old / D_new
tx'    = c.x - c_img.x * D_new * s'
ty'    = c.y - c_img.y * D_new * s'
```

Because `c_img` is in **original** space it is invariant across the swap — which is precisely why P2 makes the whole system tractable. `setImageSource(natural, D_new)` performs this atomically with the bitmap swap in one store update, so no frame renders with mismatched `s`/`D`. **No annotation coordinate is touched.** This is the payoff of the two-stage design: variants become a pure presentation concern.

### 5.4 Zoom-to-cursor

The invariant: **the image point under the cursor does not move.**

```
zoomAt(pointer: Point2D /* stage container coords */, factor: number):
  1. before  = stageToImage(pointer, ctx)                    // ORIGINAL px under cursor
  2. sNext   = clamp(s * factor, minScale, maxScale)
  3. if sNext === s: return                                   // at a limit; do not translate
  4. tx' = pointer.x - before.x * D * sNext
     ty' = pointer.y - before.y * D * sNext
  5. setTransform(clampPan({ scale: sNext, x: tx', y: ty' }, ctx))
```

Step 4 is the algebra of "solve `imageToStage(before) = pointer` for `t` given `sNext`". Step 3 matters: at max zoom, continued wheeling must not translate — omitting it makes the image creep at the zoom limit.

Inputs:
- **Wheel**: `factor = exp(-deltaY * 0.0015)`, giving smooth exponential zoom and correct handling of both notched mice (`deltaMode: DOM_DELTA_LINE`, normalized ×16) and trackpads (`DOM_DELTA_PIXEL`). `preventDefault()` — the page must not scroll. Non-passive listener, attached imperatively (React's synthetic `onWheel` is passive in React 18 and cannot `preventDefault`).
- **Ctrl+wheel / pinch**: browsers report a pinch as `wheel` + `ctrlKey`. Same path, `factor = exp(-deltaY * 0.01)` (pinch deltas are smaller).
- **Touch pinch**: two-pointer gesture; `pointer` = midpoint of the two touches, `factor` = `currentDistance / startDistance`, re-baselined each frame. The midpoint also pans, so pinch-zoom and pan compose naturally, as users expect.
- **Buttons/keyboard**: `factor = 1.25` / `1/1.25`, `pointer` = viewport centre.

`minScale = min(fitScale * 0.5, 0.05)` — always allow zooming out past fit, never below 5%.
`maxScale = 40 / D` — capped so the user can reach 40× **original** pixels. Expressing the cap in original-pixel terms rather than stage terms keeps "max zoom" meaning the same thing regardless of which variant is loaded.

### 5.5 Pan clamping

Goal: the user can never lose the image off-screen, but can still bring any edge to the centre for annotating a corner (an unforgiving hard clamp makes edge points impossible to place accurately).

```
clampPan(t: ViewerTransform, ctx): ViewerTransform
  const sw = natural.width  * D * t.scale        // scaled content width, screen px
  const sh = natural.height * D * t.scale
  const mx = viewport.width  * OVERSCROLL        // OVERSCROLL = 0.5
  const my = viewport.height * OVERSCROLL

  x = sw <= viewport.width
        ? (viewport.width - sw) / 2                              // centre when it fits
        : clamp(t.x, viewport.width - sw - mx, mx)               // else bound with margin
  // y symmetric
```

- **Fits → centre, hard.** No free-floating small image; it looks broken.
- **Overflows → clamp with 50%-of-viewport overscroll.** The image can be pushed until half the viewport is empty, which puts any edge/corner at the viewport centre where the crosshair is most precise. Without this, corner GCPs cannot be placed accurately — the failure is real, not theoretical.
- Applied on **every** transform write (`zoomAt`, `panBy`, `fitToView`, variant swap). Enforced in `setTransform` in the store rather than at call sites, so it cannot be forgotten.
- Konva's `dragBoundFunc` is deliberately **not** used: it fires per drag frame with different semantics and would double-clamp against our own logic. Panning is implemented by handling stage drag ourselves and routing through `panBy` → `clampPan`. One clamp, one owner.

### 5.6 Fit-to-view

```
fitToView():
  const sw = viewport.width  / (natural.width  * D)      // note: * D — fit ORIGINAL to viewport
  const sh = viewport.height / (natural.height * D)
  const fit = min(sw, sh) * FIT_PADDING                  // FIT_PADDING = 0.95
  setTransform(clampPan({ scale: fit, x: 0, y: 0 }, ctx))   // clampPan centres it
```

`FIT_PADDING = 0.95` leaves a 5% gutter so edge annotations are not flush against the pane border.
`zoomToActualSize()` sets `scale = 1 / D`, making one **original** pixel equal one CSS pixel — the correct definition of "100%" for this product, and again only expressible because `D` is explicit.
`zoomToImageRect(r)` (used by §3.5's reveal): `scale = min(vw / (r.width * D), vh / (r.height * D)) * 0.8`, then translate so `r`'s centre is the viewport centre, then `clampPan`. The 0.8 gives context around the revealed point rather than a claustrophobic crop.

`fitToView` is called on: image load, variant swap where the previous transform was itself a fit (tracked by an `isFitted` flag, so a user's manual zoom is never overridden), fullscreen enter/exit, and the `F` key. A `ResizeObserver` on the container calls `setViewport` + re-fit-if-fitted, debounced 100ms.

---

## 6. Brightness / Contrast — CSS filters, not Konva filters

**Decision: CSS filters, applied to the image layer's canvas element only.**

### 6.1 The options

| | Konva filters (`Konva.Filters.Brighten/Contrast`) | CSS `filter` |
| --- | --- | --- |
| Mechanism | JS reads `ImageData`, mutates pixels, writes back. **Requires `node.cache()`** | GPU compositing at paint time |
| Cost per change | Full re-cache: allocate an offscreen canvas the size of the scaled node, re-run the filter over every pixel | Zero JS; a compositor property |
| At 2048×1365 | ~2.8M pixels × N filters per slider tick — tens of ms, main-thread, per frame | ~0 |
| Memory | An extra full-size canvas per cached node, re-allocated on zoom | None |
| Zoom interaction | Cache is resolution-dependent: it must be invalidated and re-run on scale change, or it renders blurry | Independent of transform entirely |
| Coordinate risk | **`cache()` introduces its own offset/pixelRatio frame.** Mis-set `cache({ x, y, width, height })` shifts the node's rendering relative to its logical position | **None** — a paint-time effect that cannot touch geometry |

### 6.2 Why CSS wins on the criterion that matters (P2)

The decisive argument is the coordinate one. `Konva.Node.cache()` rasterizes a node into a separate buffer with its **own** origin and pixel ratio, and the node then draws that buffer. It is a well-known source of subtle offset bugs, and it couples an *appearance* control to the *geometry* pipeline. A brightness slider must be incapable of moving a GCP by even a fraction of a pixel — and the strongest way to guarantee that is architectural, not vigilant: choose a mechanism that has no access to geometry. CSS `filter` is a paint-stage operation applied to the composited output of an element. It cannot perturb Konva's scene graph, its hit graph, or `getPointerPosition()`. The guarantee is structural.

The performance argument agrees: a slider drag at 60fps would demand a full re-cache per frame — 2.8M pixels of main-thread JS ×60 — which is simply not viable on a tablet. CSS filters are free.

### 6.3 The mechanism

Konva renders **each `Layer` to its own `<canvas>`**. That is exactly the seam needed:

```
ImageLayer   → Layer A → <canvas>  ← CSS filter applied here
AnnotationLayer → Layer B → <canvas>  ← untouched, annotations render at true colour
OverlayLayer → Layer C → <canvas>  ← untouched
```

Applied in a `useLayoutEffect` in `ImageLayer`:
`layerRef.current.getCanvas()._canvas.style.filter = filterCss` (equivalently, `getNativeCanvasElement()`).

This is why `ImageLayer` is a dedicated Layer holding exactly one node (§2.10) — the layer split exists *for* this. The alternative (filtering the whole stage container) would wash out annotation colours, destroying the confidence encoding of §8.6: a "high confidence green" marker under `brightness(1.6)` is no longer the green the legend promises. Filtering only the imagery keeps the semantic colours exact.

Konva's hit detection uses a separate hit canvas that is never filtered, so hit-testing is unaffected by construction.

### 6.4 Mapping and details

```
UI range: -100 .. 0 .. +100  (0 = neutral)
brightness CSS = 1 + (uiBrightness / 100) * 0.8      → 0.2 .. 1.0 .. 1.8
contrast   CSS = 1 + (uiContrast   / 100) * 0.8      → 0.2 .. 1.0 .. 1.8
filterCss = `brightness(${b}) contrast(${c})`
Neutral (0,0) → filterCss = 'none'    // omit the property entirely; no compositing layer at rest
```

Order matters: `brightness` then `contrast` (CSS filters compose left-to-right). Contrast-then-brightness clips shadows differently and looks wrong on the underexposed field photos that are the common case.

- Sliders write straight to `viewerStore.adjustments`; the CSS property updates in the same frame. No debounce needed, which is itself a benefit of the choice.
- `resetAdjustments()` and a `⌘⇧R` shortcut restore neutral. A non-neutral adjustment shows a persistent "Adjusted" chip in `ImageStatusBar` — the user must never forget they are looking at a modified rendering when judging a landmark.
- Persisted per-user (not per-image) in `viewerStore`; field conditions tend to be consistent across a shoot.
- **Adjustments are never sent to the backend and never affect matching.** The backend runs feature extraction on the original raster. If a user cannot see a landmark without +60 brightness, that is a signal worth surfacing — a future "the detector sees a darker image than you do" hint — but it must never silently change algorithm input. The slider is a human aid, not a preprocessing step.

**Escape hatch, documented:** if a future requirement needs a *true* pixel operation that the algorithm also consumes (e.g. CLAHE preview), it does **not** belong in the viewer. It belongs server-side as a new display variant with its own `D`, requested by the client. The viewer's filter stack stays presentation-only, permanently. This keeps §5's guarantees intact no matter what image processing gets added later.

---

## 7. TypeScript domain model & API client

### 7.1 `src/types/` — every interface

Mirrors the backend Pydantic v2 schemas 1:1. Generated types (`openapi-typescript` → `src/types/generated/api.d.ts`) are the *source*; these hand-written types are the **domain layer**, re-exported and refined (branded IDs, discriminated unions, `readonly` where the domain is immutable). Rationale: generated types alone leak transport shape into components and cannot express a discriminated union over `kind` the way we want. A CI check fails if the hand-written types drift from the generated ones.

#### `src/types/common.ts`
```ts
export type Uuid = string & { readonly __brand: 'Uuid' };
export type IsoDateTime = string & { readonly __brand: 'IsoDateTime' };
export interface Point2D { x: number; y: number }
export interface Size { width: number; height: number }
export interface Rect { x: number; y: number; width: number; height: number }
export interface Paginated<T> { items: T[]; total: number; page: number; pageSize: number }
export interface ApiError { code: ApiErrorCode; message: string; detail?: unknown; requestId?: string }
export type ApiErrorCode =
  | 'validation_error' | 'not_found' | 'conflict' | 'unauthorized' | 'forbidden'
  | 'rate_limited' | 'provider_unavailable' | 'internal_error';
export type CoordinateFormat = 'decimal' | 'dms';
export type Result<T, E = ApiError> = { ok: true; value: T } | { ok: false; error: E };
```

#### `src/types/geo.ts`
```ts
export interface LatLon { lat: number; lon: number }
export interface BBox { west: number; south: number; east: number; north: number }
export type Homography = readonly [
  readonly [number, number, number],
  readonly [number, number, number],
  readonly [number, number, number],
];
export interface MapViewState { center: LatLon; zoom: number; bearing: 0 }
export type ViewOrigin = 'map' | 'image' | 'app' | 'sync';
export type BasemapKind = 'satellite' | 'hybrid' | 'terrain';
export type ProviderId = string & { readonly __brand: 'ProviderId' };
export interface ProviderDescriptor {
  id: ProviderId;
  label: string;
  kinds: BasemapKind[];
  tileUrlTemplate: string;          // backend-proxied; never contains a key
  minZoom: number;
  maxZoom: number;
  tileSize: 256 | 512;
  attributionHtml: string;
  requiresKey: boolean;
  available: boolean;
  unavailableReason: string | null;
  isDefault: boolean;
}
export type LocationHint =
  | { kind: 'none' }
  | { kind: 'point'; center: LatLon; radiusM: number }
  | { kind: 'bbox'; bbox: BBox };
export type Crs = 'EPSG:4326' | 'EPSG:3857' | (string & {});
```

#### `src/types/image.ts`
```ts
export type VariantName = 'thumb' | 'preview' | 'full' | 'original';
export interface ImageDisplayVariant {
  name: VariantName;
  url: string;
  width: number;                    // variant dims
  height: number;
  originalWidth: number;            // ALWAYS present — the denominator of displayScale (§5.1)
  originalHeight: number;
  byteSize: number;
}
export interface ExifHint {
  gps: LatLon | null;
  altitudeM: number | null;
  headingDeg: number | null;
  capturedAt: IsoDateTime | null;
  cameraMake: string | null;
  cameraModel: string | null;
  focalLengthMm: number | null;
}
export interface ImageMetadata {
  width: number; height: number;
  mimeType: string; byteSize: number;
  checksumSha256: string;
  exif: ExifHint | null;
}
export interface UploadedImage {
  id: Uuid;
  projectId: Uuid;
  filename: string;
  status: 'uploading' | 'processing' | 'ready' | 'failed';
  metadata: ImageMetadata | null;
  variants: ImageDisplayVariant[];
  createdAt: IsoDateTime;
  failureReason: string | null;
}
```

#### `src/types/annotation.ts`
```ts
export type AnnotationKind = 'point' | 'polygon' | 'polyline';
export type AnnotationSource = 'manual' | 'suggested' | 'imported';
interface AnnotationBase {
  clientId: string;                 // nanoid; stable across the session
  serverId: Uuid | null;
  label: string;
  notes: string | null;
  source: AnnotationSource;
  createdAt: IsoDateTime;
  color: string | null;
}
export interface PointAnnotation    extends AnnotationBase { kind: 'point';    position: Point2D }
export interface PolygonAnnotation  extends AnnotationBase { kind: 'polygon';  vertices: Point2D[]; closed: true }
export interface PolylineAnnotation extends AnnotationBase { kind: 'polyline'; vertices: Point2D[]; closed: false }
export type Annotation = PointAnnotation | PolygonAnnotation | PolylineAnnotation;
// INVARIANT: every Point2D above is in ORIGINAL image pixel space. (§5.1)

export interface AnnotationVersion {
  id: Uuid;
  imageId: Uuid;
  versionNumber: number;
  parentVersionId: Uuid | null;
  annotations: Annotation[];
  changeLog: SerializedCommand[];
  authorId: Uuid | null;
  authorLabel: string;
  createdAt: IsoDateTime;
  annotationCount: number;
  summary: string;
  usedByMatchIds: Uuid[];
}
export interface LandmarkSuggestion {
  id: string;
  kind: AnnotationKind;
  geometry: Point2D | Point2D[];
  score: number;
  rationale: string;
  modelId: string;
}
```

#### `src/types/gcp.ts`
```ts
export type ConfidenceBand = 'high' | 'moderate' | 'low' | 'unreliable' | 'manual';
export interface GcpConfidence {
  score: number;                    // 0..1
  band: ConfidenceBand;
  inlierRatio: number | null;
  reprojectionErrorPx: number | null;
  supportCount: number | null;
}
export interface ErrorEllipse { semiMajorM: number; semiMinorM: number; orientationDeg: number }
export interface GcpAdjustment {
  imagePixel: Point2D | null;       // ORIGINAL px
  latLon: LatLon | null;
  pinned: boolean;
  adjustedBy: Uuid | null;
  adjustedAt: IsoDateTime;
  note: string | null;
}
export interface Gcp {
  id: Uuid;
  matchResultId: Uuid;
  pointId: string;                  // 'P1' — the Point ID column
  sourceAnnotationId: string;       // links to Annotation.clientId (§3.5)
  imagePixel: Point2D;              // ORIGINAL px
  latLon: LatLon;
  confidence: GcpConfidence;
  errorRadiusM: number | null;
  errorEllipse: ErrorEllipse | null;
  adjustment: GcpAdjustment | null;
  isManual: boolean;
}
export interface GcpTableRow {
  id: Uuid;
  pointId: string;
  imageX: number;
  imageY: number;
  latitude: number;
  longitude: number;
  confidence: GcpConfidence;
  errorRadiusM: number | null;
  isManual: boolean;
  linkedAnnotationId: string;
  displayPrecision: number;         // §8.6.3 — decimals permitted for THIS row
}
```

#### `src/types/match.ts`
```ts
export type FeatureExtractorId = 'sift' | 'orb' | 'superpoint' | 'dinov2' | 'loftr';
export type MatcherId = 'flann' | 'bf' | 'superglue' | 'lightglue' | 'loftr';
export interface MatchSettings {
  extractor: FeatureExtractorId;
  matcher: MatcherId;
  ransacThresholdPx: number;
  minInliers: number;
  maxCandidates: number;
  searchZoom: number;
}
export interface MatchRequest {
  imageId: Uuid;
  annotationVersionId: Uuid;
  locationHint: LocationHint;
  providerId: ProviderId | null;
  settings: Partial<MatchSettings>;
}
export interface SatelliteTileRef {
  providerId: ProviderId; z: number; x: number; y: number;
  bbox: BBox; url: string;
}
export interface MatchCandidate {
  id: Uuid; rank: number; score: number;
  bbox: BBox; centerLatLon: LatLon;
  inlierCount: number; previewUrl: string | null;
}
export interface MatchResult {
  id: Uuid;
  imageId: Uuid;
  annotationVersionId: Uuid;
  jobId: Uuid;
  status: 'succeeded' | 'low_confidence' | 'failed';
  homography: Homography | null;
  homographyInverse: Homography | null;
  overallConfidence: GcpConfidence;
  footprint: LatLon[] | null;
  satelliteImageUrl: string | null;
  satelliteBbox: BBox | null;
  providerId: ProviderId;
  providerAttribution: string;
  settingsUsed: MatchSettings;
  extractorUsed: FeatureExtractorId;      // may differ from requested — §8.7 fallback
  matcherUsed: MatcherId;
  fellBackToClassical: boolean;           // surfaced in the UI, honestly
  fallbackReason: string | null;
  gcpCount: number;
  createdAt: IsoDateTime;
  durationMs: number;
}
export interface ConfidenceGrid { bounds: BBox; rows: number; cols: number; values: number[] }
```

#### `src/types/job.ts`
```ts
export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'cancelling';
export type JobPhase =
  | 'queued' | 'fetching_tiles' | 'extracting_features' | 'matching'
  | 'estimating_homography' | 'transforming' | 'rendering' | 'done';
export type JobErrorCode =
  | 'no_location_hint' | 'match_failed' | 'low_confidence' | 'insufficient_annotations'
  | 'provider_unavailable' | 'provider_rate_limited' | 'tile_fetch_failed'
  | 'image_unreadable' | 'model_unavailable' | 'timeout' | 'cancelled' | 'internal_error';
export interface JobError { code: JobErrorCode; message: string; detail?: unknown; retryable: boolean }
export interface JobProgressInfo {
  phase: JobPhase; progress: number | null;   // null = indeterminate
  message: string | null;
  phaseIndex: number; phaseCount: number;
}
interface JobBase {
  id: Uuid; status: JobStatus; progress: JobProgressInfo;
  error: JobError | null;
  createdAt: IsoDateTime; startedAt: IsoDateTime | null; finishedAt: IsoDateTime | null;
}
export interface MatchJob  extends JobBase { kind: 'match';  imageId: Uuid; matchResultId: Uuid | null }
export interface ExportJob extends JobBase { kind: 'export'; matchResultId: Uuid; artifact: ExportArtifact | null }
export type Job = MatchJob | ExportJob;
export function isTerminal(s: JobStatus): boolean;   // exhaustive switch + never check (§3.2)
```

#### `src/types/export.ts`
```ts
export type ExportFormat = 'csv' | 'geojson' | 'shapefile' | 'kml' | 'pdf';
export interface ExportOptions {
  crs: Crs;
  coordinateFormat: CoordinateFormat;
  includeLowConfidence: boolean;
  includeSatelliteImage: boolean;
  includeConfidenceColumn: true;    // literal: never optional (P1)
  pdfTitle?: string;
  pdfNotes?: string;
}
export interface ExportRequest { matchResultId: Uuid; format: ExportFormat; options: ExportOptions }
export interface ExportArtifact {
  id: Uuid; format: ExportFormat; url: string; filename: string;
  byteSize: number; expiresAt: IsoDateTime; checksumSha256: string;
}
```

#### `src/types/project.ts`
```ts
export interface Project {
  id: Uuid; name: string; description: string | null;
  imageCount: number; matchCount: number;
  createdAt: IsoDateTime; updatedAt: IsoDateTime;
}
export interface ProjectSummary { id: Uuid; name: string; imageCount: number; updatedAt: IsoDateTime }
export interface ProjectFilters { search?: string; page?: number; pageSize?: number }
export interface JobFilters { status?: JobStatus[]; kind?: Job['kind']; imageId?: Uuid }
```

#### `src/types/capabilities.ts`
```ts
export interface ModelCapability {
  id: string; kind: 'extractor' | 'matcher' | 'segmenter' | 'embedder';
  available: boolean; reason: string | null; weightsPresent: boolean; device: 'cpu' | 'cuda' | null;
}
export interface ModelCapabilities {
  models: ModelCapability[];
  defaultExtractor: FeatureExtractorId;    // 'sift' out of the box (P3)
  defaultMatcher: MatcherId;               // 'flann' out of the box
  suggestions: boolean;                    // SAM/DINOv2 present?
  gpuAvailable: boolean;
}
```

#### `src/types/commands.ts`
Re-exports `Command`, `CommandType`, `SerializedCommand`, `AnnotationCommand` and all payload interfaces from §4.

#### `src/types/index.ts`
Barrel re-export of all of the above.

### 7.2 `src/api/` — one function per endpoint

```
src/api/
├── client.ts          // ky/fetch wrapper: baseUrl, auth header, ApiError normalization,
│                      // requestId propagation, 60s timeout, AbortSignal passthrough
├── queryKeys.ts       // §3.1
├── queryClient.ts     // defaults (§3.2)
├── projects.ts
├── images.ts
├── annotations.ts
├── suggestions.ts
├── matches.ts
├── jobs.ts
├── gcps.ts
├── exports.ts
├── providers.ts
├── capabilities.ts
└── hooks/             // the React Query hooks; api/*.ts stay framework-free & directly testable
    ├── useProjects.ts  useImages.ts  useAnnotations.ts  useSuggestions.ts
    ├── useMatches.ts   useJobs.ts    useGcps.ts         useExports.ts
    └── useProviders.ts useCapabilities.ts
```

```ts
// projects.ts
export function listProjects(f: ProjectFilters, s?: AbortSignal): Promise<Paginated<ProjectSummary>>;
export function getProject(id: Uuid, s?: AbortSignal): Promise<Project>;
export function createProject(body: { name: string; description?: string }): Promise<Project>;
export function updateProject(id: Uuid, body: Partial<Pick<Project,'name'|'description'>>): Promise<Project>;
export function deleteProject(id: Uuid): Promise<void>;

// images.ts
export function listImages(projectId: Uuid, s?: AbortSignal): Promise<UploadedImage[]>;
export function getImage(id: Uuid, s?: AbortSignal): Promise<UploadedImage>;
export function uploadImage(projectId: Uuid, file: File, onProgress: (p: number) => void, s?: AbortSignal): Promise<UploadedImage>;   // XHR (§2.25)
export function getImageVariant(id: Uuid, v: VariantName, s?: AbortSignal): Promise<ImageDisplayVariant>;
export function getImageExif(id: Uuid, s?: AbortSignal): Promise<ExifHint | null>;
export function deleteImage(id: Uuid): Promise<void>;

// annotations.ts
export function getLatestAnnotations(imageId: Uuid, s?: AbortSignal): Promise<AnnotationVersion | null>;
export function listAnnotationVersions(imageId: Uuid, s?: AbortSignal): Promise<AnnotationVersion[]>;
export function getAnnotationVersion(imageId: Uuid, versionId: Uuid, s?: AbortSignal): Promise<AnnotationVersion>;
export function createAnnotationVersion(imageId: Uuid, body: { baseVersionId: Uuid | null; annotations: Annotation[]; changeLog: SerializedCommand[]; clientCommandCursor: string | null }): Promise<AnnotationVersion>;
export function restoreAnnotationVersion(imageId: Uuid, versionId: Uuid): Promise<AnnotationVersion>;

// suggestions.ts
export function getLandmarkSuggestions(imageId: Uuid, s?: AbortSignal): Promise<LandmarkSuggestion[]>;

// matches.ts
export function startMatch(body: MatchRequest): Promise<MatchJob>;
export function getMatchResult(id: Uuid, s?: AbortSignal): Promise<MatchResult>;
export function listMatchesForImage(imageId: Uuid, s?: AbortSignal): Promise<MatchResult[]>;
export function getMatchCandidates(id: Uuid, s?: AbortSignal): Promise<MatchCandidate[]>;
export function getConfidenceGrid(id: Uuid, s?: AbortSignal): Promise<ConfidenceGrid>;

// jobs.ts
export function getJob(id: Uuid, s?: AbortSignal): Promise<Job>;
export function listJobs(f: JobFilters, s?: AbortSignal): Promise<Paginated<Job>>;
export function cancelJob(id: Uuid): Promise<Job>;

// gcps.ts
export function listGcps(matchResultId: Uuid, s?: AbortSignal): Promise<Gcp[]>;
export function getGcp(id: Uuid, s?: AbortSignal): Promise<Gcp>;
export function adjustGcp(id: Uuid, body: { imagePixel?: Point2D; latLon?: LatLon; pinned: boolean; note?: string }): Promise<{ gcp: Gcp; recomputed: Gcp[] }>;
export function updateGcp(id: Uuid, body: { pointId?: string }): Promise<Gcp>;
export function resetGcpAdjustment(id: Uuid): Promise<{ gcp: Gcp; recomputed: Gcp[] }>;

// exports.ts
export function createExport(body: ExportRequest): Promise<ExportJob>;
export function getExport(id: Uuid, s?: AbortSignal): Promise<ExportJob>;
export function listExports(matchResultId: Uuid, s?: AbortSignal): Promise<ExportJob[]>;

// providers.ts / capabilities.ts
export function listProviders(s?: AbortSignal): Promise<ProviderDescriptor[]>;
export function getCapabilities(s?: AbortSignal): Promise<ModelCapabilities>;
```

`adjustGcp` returning `{ gcp, recomputed }` is what makes §3.3's honest optimistic update possible: the server tells us exactly which other points moved, and the client can stop shimmering them precisely when it knows their new values.

`client.ts` normalizes every non-2xx into a typed `ApiError` (never a raw `Response`), so `retry: (n, e) => !isClientError(e)` and every error UI can switch on `code` rather than parse strings.

---

## 8. UX Flows

### 8.1 First-run empty state

No project → full-bleed `EmptyState`: illustration, "Create your first survey project", primary CTA, secondary "Learn how LandExplorer works" (opens a 4-step explainer). Project with no images → the workspace renders with all three panes visible but each in its own empty state, so the user learns the layout *before* having data in it:
- Image pane: `UploadDropzone` — "Drop a field photograph here, or browse. JPEG/PNG/TIFF up to 200MB."
- Map pane: world view at zoom 2 with the default keyless provider, attribution already visible, and a hint "The matching area will appear here."
- Dock: "Ground control points will appear here after a match."

The panes are never blank rectangles. Each empty state names what will occupy it.

### 8.2 The happy path

```
UPLOAD                ANNOTATE                MATCH                REVIEW              ADJUST            EXPORT
  │                      │                      │                    │                   │                 │
  ├ drop file            ├ pick point tool (P)  ├ set location hint  ├ table populates   ├ drag marker     ├ pick format
  ├ progress + EXIF chip ├ click landmarks      │  (EXIF chip / box) ├ sorted conf ASC   ├ live residual   ├ options
  ├ server processing    ├ auto-labelled P1..Pn ├ flush autosave     ├ click row →       ├ commit          ├ low-conf ack
  ├ variants ready       ├ autosave → version   ├ POST /matches      │  3-pane highlight ├ re-estimate     ├ job runs
  └ fit-to-view          └ ≥4 points → Match    ├ job polling        ├ compare mode      └ table updates   └ download
                            button enables      └ phases stream      └ verify visually
```

**Gating is honest, not arbitrary.** The Match button is disabled below 4 point annotations with the tooltip "A homography needs at least 4 points. You have 2." — it states the mathematical reason, not "please add more". At exactly 4 the button enables but carries a caution: "4 points give an exact fit with no way to measure error. 6+ lets LandExplorer estimate accuracy." That sentence is the difference between a tool that teaches and one that merely refuses. A surveyor who understands *why* will add the sixth point.

### 8.3 The job-running state

While a match runs:
- Map pane dims to 60% and shows a centred `JobProgress` panel (`variant: 'panel'`) with the `JobPhaseStepper`.
- Image pane stays **fully interactive** — annotation is not blocked; the job runs against an immutable saved version (§4.6), so further edits are safe and simply belong to the next version. Blocking here would be a pure loss.
- Dock shows a skeleton table with the correct column headers.
- Shell shows the `GlobalJobIndicator`, so navigating away does not lose the thread.
- Cancel is always available and optimistic (`status: 'cancelling'`).
- If a job exceeds 90s, the panel adds "Large search areas take longer. Narrowing the location hint speeds this up considerably." — actionable, not apologetic.

### 8.4 Progress semantics

`progress: null` renders **indeterminate**. We do not fake a determinate bar. A lying progress bar teaches users to distrust the whole UI, and the phases (`fetching_tiles → extracting_features → matching → …`) already convey real motion. `JobPhaseStepper` is the primary progress signal; the bar is secondary.

### 8.5 Failure states — the honesty requirements

Every failure renders through `JobErrorPanel` with a **cause**, a **consequence**, and a **specific next action**. No bare "Error" toasts on the critical path.

#### 8.5.1 `no_location_hint`

This is a *guidance* state, not an error. Reached when the user starts a match with no hint and no EXIF GPS.

> **Where should we search?**
> LandExplorer compares your landmarks against satellite imagery. Searching the entire planet isn't feasible — we need a starting area.
> **Choose one:**
> · **Use photo GPS** — *(shown only if EXIF present)* 41.8721, -93.6019
> · **Draw a search area** — draw a box on the map *(primary)*
> · **Enter coordinates or a place name**
> A tighter area matches faster and more accurately.

It is presented **before** the job is submitted (the Match button opens this dialog when no hint exists), never as a post-hoc failure — failing a user for something we could have asked first is bad design. `LocationHintControl` (§2.20) is embedded directly in the panel.

#### 8.5.2 `match_failed`

> **No match found**
> We compared your 6 landmarks against satellite imagery in the search area but couldn't find a consistent alignment.
> **This usually means one of:**
> · The search area doesn't contain the photographed location — *[Widen or move the area]*
> · The landmarks aren't distinguishable from above (e.g. a fence line, a wall face) — *[Review landmarks]* — prefer corners, isolated trees, tank tops, road junctions
> · The satellite imagery is older or newer than the photo — *[Try another provider]*
> · The viewing angle is too oblique for a planar match
> **No coordinates were produced.** ← stated plainly, in bold
> *[Adjust and retry]  [View diagnostics]*

The dock stays **empty**. It shows no rows. There is no partial result to display and inventing one would be a lie.

#### 8.5.3 `low_confidence` — the most important state in the product

The match *succeeded numerically* but the result is not trustworthy. The temptation is to present coordinates and let the number speak. That is exactly what P1 forbids.

`MatchResult.status = 'low_confidence'` triggers a **persistent, non-dismissible** banner above the dock:

> ⚠ **Low-confidence match — not survey-grade**
> This match is based on 5 of 6 landmarks with an inlier ratio of 0.34 and a mean reprojection error of 18.2 px. The coordinates below could be wrong by **tens of metres or more**.
> **Do not use these coordinates for survey, legal, or machine-guidance purposes without independent verification.**
> *[Compare with satellite view]  [Adjust points manually]  [Try a different area]  [Export anyway (marked low-confidence)]*

Concurrent enforcement across the whole UI:
- Every row's coordinate is **precision-truncated** (§8.6.3) — a 0.31-confidence fix renders `41.87`, not `41.8721943`. Rendering seven decimals on a fix that could be 50m off is the single most dangerous thing this UI could do, because the digits themselves are a claim of precision that overrides any banner. Truncation makes the honest claim *in the data*, where it cannot be dismissed.
- Map markers are dashed with `⚠` and their `errorRadiusM` circle is shown by default (not opt-in).
- The confidence heatmap auto-enables — the user should see the uncertainty field without asking.
- Compare mode `linked`/`swipe` are **disabled** below 0.40 (§1.6) — we will not synchronize views using a homography we don't believe.
- Export requires the acknowledgement checkbox (§2.23), and every output format carries the confidence column plus a `low_confidence: true` flag; the PDF report gets a full-width warning block on page 1.

#### 8.5.4 Other failures

| Code | Handling |
| --- | --- |
| `insufficient_annotations` | Prevented by the gate (§8.2); if it still arrives, panel names the count needed. |
| `provider_unavailable` | Banner + auto-fallback offer to the keyless default. "Mapbox didn't respond. [Retry] [Use Esri World Imagery instead]" |
| `provider_rate_limited` | Retry-after countdown; suggests the keyless provider. |
| `tile_fetch_failed` | Partial coverage shown on the map as a hatched region; the match is refused rather than run on holes. |
| `image_unreadable` | Surfaced at upload, not at match time. |
| `model_unavailable` | **Never fatal** (P3). The job succeeds on the classical path and the result carries `fellBackToClassical: true` — see §8.7. |
| `timeout` | Offers a narrower hint or a lower `searchZoom`. |

### 8.6 Confidence visual encoding

#### 8.6.1 Bands and thresholds

| Band | Range | Meaning to a surveyor | Light token | Dark token |
| --- | --- | --- | --- | --- |
| **High** | `≥ 0.85` | Usable; verify by sampling | `#1B7F4B` | `#4ADE80` |
| **Moderate** | `0.65 – 0.85` | Usable with verification | `#B45309` | `#FBBF24` |
| **Low** | `0.40 – 0.65` | Not survey-grade; verify every point | `#C2410C` | `#FB923C` |
| **Unreliable** | `< 0.40` | Treat as a guess | `#B91C1C` | `#F87171` |
| **Manual** | — | Human-placed; confidence not applicable | `#1D4ED8` | `#60A5FA` |

`confidenceBand(score): ConfidenceBand` in `src/lib/confidence.ts` is the **only** implementation of these thresholds. Thresholds are exported as `CONFIDENCE_THRESHOLDS` and used by the backend contract tests too, so the two never drift.

Four bands, not a continuous ramp, for the table/markers: a continuous colour cannot be read categorically, and the surveyor's actual decision is categorical ("do I trust this point?"). The continuous ramp is reserved for the heatmap, where the *field* is the message.

Design notes:
- **Green is never the default.** Absence of a match is grey, not green. Green must be earned.
- Manual is **blue, not green** — a human-placed point is not "high confidence", it is a different *kind* of claim, and conflating them would let a user's guess masquerade as an algorithmic result.
- Never colour alone: every confidence surface pairs colour with **text** (band name), and the table adds **bar length**. Deuteranopia/protanopia make the green/orange axis unreadable; the text label is the actual carrier of meaning and the colour is the accelerator. Verified with a deuteranopia simulation as part of the design review, and the palette above is chosen so the four bands remain distinguishable by lightness alone (L* ≈ 45 / 55 / 52 / 42 with distinct hue *and* differing bar lengths).

#### 8.6.2 Heatmap ramp

Continuous, perceptually uniform, **viridis-derived and reversed** so low confidence is the *attention-getting* end (yellow) rather than the pleasant end: `0.0 → #FDE725` (yellow, alarming in context), `0.5 → #21918C` (teal), `1.0 → #440154` (deep purple, "nothing to see here"). Opacity `0.55` over imagery. This inversion is deliberate — a heatmap where the good regions glow brightly trains the eye to look at exactly the wrong places. A legend with numeric stops is mandatory and always rendered with the layer; an unlabelled heatmap is decoration.

#### 8.6.3 Coordinate precision policy

**Displayed decimal places are a function of confidence and error radius**, computed in `src/lib/coordinates.ts`:

```
displayPrecision(errorRadiusM, band):
  band === 'unreliable'            -> 2    (~1.1 km)
  band === 'low'                   -> 4    (~11 m)
  errorRadiusM == null             -> 5
  errorRadiusM > 50                -> 3    (~110 m)
  errorRadiusM > 5                 -> 5    (~1.1 m)
  errorRadiusM > 0.5               -> 6    (~0.11 m)
  otherwise                        -> 7    (~1.1 cm)
```

Rationale: a decimal digit *is* a claim about accuracy — at the equator the 7th decimal is ~1.1cm. Printing `41.8721943` for a fix that could be 50m off is a fabricated precision claim, and it is the kind of number that gets pasted into a legal document. The full-precision value is always available on hover and in the export (with the confidence column adjacent), so nothing is lost — but the *default* rendering never over-claims. The tooltip states it explicitly: "Full precision: 41.8721943 — shown rounded because this point's estimated error is ±52 m."

### 8.7 Progressive enhancement — deep models absent (the default!)

Per P3, a fresh machine has no weights and the classical path is the norm. The UI's job is to make that feel like the product working, not the product broken:

- `useModelCapabilities()` drives the Inspector's match settings: unavailable models are listed but disabled, with the reason from `ModelCapability.reason` ("SuperGlue weights not found at `models/superglue.pth`") and a link to the docs. The user learns what exists and how to get it.
- Default extractor/matcher come **from the server** (`sift`/`flann`), never hard-coded in the frontend.
- If a job requested a deep model and the backend fell back, `MatchResult.fellBackToClassical = true` produces an **informational** (not warning) chip on the result: "Matched with SIFT + FLANN — SuperGlue weights weren't available. [Why?]". Informational because the result is legitimate; SIFT+RANSAC is a real algorithm with real accuracy, and framing the default path as a degradation would be both wrong and demoralizing.
- Nothing in the UI implies deep models are required. Copy consistently frames them as "optional accelerators".

### 8.8 Accessibility

**The canvas problem.** A Konva stage is one opaque `<canvas>` — invisible to assistive technology. The mitigations:

1. **The `GcpTable` is the accessible representation of the canvas.** Everything visible on the image is also in a real, navigable, semantic HTML table. This is the primary AT story, and it is a genuine one rather than a fallback: the table is not a lesser view, it is the same data in a form that both AT and sighted surveyors use as the system of record.
2. **Stage container**: `role="application"`, `aria-label="Image annotation canvas. 6 landmarks marked. Use arrow keys to navigate points, Enter to select."`, `tabIndex={0}`, and a visible focus ring.
3. **A visually-hidden live list** shadows the annotations: an `<ul>` positioned off-screen with one `<li role="option">` per annotation carrying `aria-label="Point P3 at x 987, y 2456, latitude 41.8724, longitude minus 93.6028, confidence 0.71 moderate"`. Roving `tabindex`; the container is `role="listbox"`. Focus here syncs to `selectionStore`, so a screen-reader user drives the same selection state as a mouse user — the panes highlight identically.
4. **`LiveRegion`** (`aria-live="polite"`) announces every command: "Added point P4 at 3902, 3011", "Undid move of P2", "Match complete. 6 points. 1 below threshold." Destructive/failure announcements use `assertive`.
5. **Full keyboard annotation.** `Tab` to the canvas → arrows move a virtual cursor (1px, `Shift` = 10px, `Ctrl` = 100px) → `Enter` places a point at the cursor. Placing points without a mouse is a hard requirement, not a nicety.
6. **Contrast**: all text ≥ 4.5:1; UI components and graphical objects ≥ 3:1 (WCAG 2.2 AA, 1.4.11). Confidence colours are chosen to pass **against both** the light surface and the dark surface, and — because markers sit on satellite imagery of arbitrary colour — every marker carries a 1.5px contrasting outline (`#FFF` in light, `#000` in dark) plus a subtle drop shadow. Colour on imagery cannot be assumed to have a background; the outline is what makes the contrast claim actually true.
7. **Motion**: `prefers-reduced-motion` disables `flyTo` animation (instant `setView`), marker pulses, and skeleton shimmer.
8. **Targets**: ≥24×24 CSS px everywhere (WCAG 2.2 AA, 2.5.8); ≥44×44 on coarse pointers.
9. **Focus is never trapped** except in modal dialogs, where it is trapped correctly and restored on close.
10. **The map**: Leaflet's keyboard nav is enabled; markers are focusable with `aria-label`s matching the table's.

### 8.9 Keyboard map

| Key | Action |
| --- | --- |
| `V` `P` `G` `L` | cursor / point / polygon / polyline |
| `Space` (hold) | temporary pan (restores previous tool on release) |
| `⌘Z` / `⌃Z` | undo |
| `⇧⌘Z` / `⌃Y` | redo |
| `Delete` / `Backspace` | delete selection |
| `Escape` | cancel in-progress shape → clear selection → exit sub-mode |
| `F` | fit to view |
| `1` | actual size (1 original px = 1 CSS px) |
| `+` / `-` | zoom in/out at centre |
| `C` | toggle compare mode |
| `H` | toggle confidence heatmap |
| `M` | start match |
| `⌘E` | export menu |
| `⌘S` | force autosave |
| `⌘K` | command palette |
| `?` | shortcut cheatsheet |
| `⇧⌘R` | reset brightness/contrast |
| `Tab` / `⇧Tab` | next/previous GCP (cycles the table, canvas, and map together) |

Shortcuts are suppressed when focus is in a text input. `⌘`/`⌃` is platform-detected.

---

## 9. Theme

`src/theme/` — `index.ts`, `tokens.ts`, `palette.ts`, `typography.ts`, `components.ts`, `confidence.ts`.

### 9.1 Principle

The chrome is desaturated and low-contrast **so that the imagery and the confidence colours are the only saturated things on screen**. In a tool whose entire job is judging photographs and communicating risk, a colourful UI is actively harmful: it competes with the imagery for attention and it dilutes the semantic weight of the confidence palette. Every colour in the chrome earns its place or is removed.

### 9.2 Design tokens (`tokens.ts`)

```ts
export const tokens = {
  radius:  { none: 0, sm: 4, md: 6, lg: 8, xl: 12, pill: 999 },
  spacing: 8,                                  // MUI base; theme.spacing(n) = 8n
  elevation: { panel: 0, dock: 1, drawer: 8, dialog: 16, tooltip: 24 },
  duration: { instant: 0, fast: 120, normal: 200, slow: 320, fly: 500 },
  easing: { standard: 'cubic-bezier(0.2, 0, 0, 1)', decel: 'cubic-bezier(0, 0, 0, 1)' },
  layout: {
    topBarHeight: 56, toolRailWidth: 56, inspectorWidth: 280,
    dockHeightDefault: 240, dockHeightMin: 120, paneMinWidth: 320, splitterSize: 6,
  },
  zIndex: { canvasOverlay: 10, mapControl: 400, dock: 1000, appBar: 1100, drawer: 1200, dialog: 1300, snackbar: 1400, tooltip: 1500 },
  annotation: {
    pointRadius: 6, pointRadiusSelected: 8, vertexRadius: 4,
    strokeWidth: 2, strokeWidthSelected: 3, hitStrokeWidth: 12,
    outlineWidth: 1.5,
  },
} as const;
```

`tokens.annotation` values are **CSS pixels after inverse-scaling** (§2.10) — they are the on-screen sizes, constant at every zoom.

### 9.3 Palette

Neutrals are a slightly blue-cool grey ramp (`grey.50 … grey.900`), because they sit adjacent to satellite imagery which is dominated by warm earth tones; a cool chrome recedes and lets the imagery come forward.

```
Light:  background.default #F5F6F7   background.paper #FFFFFF
        canvas backdrop   #E8EAED    divider #E0E3E7
        text.primary #1A1D21  text.secondary #5F6672
Dark:   background.default #12151A   background.paper #1A1E25
        canvas backdrop   #0A0C0F    divider #2A3038
        text.primary #E8EBEF  text.secondary #9AA3B0
primary   #2563EB / #60A5FA     (actions; deliberately NOT green — green is reserved for confidence)
secondary #64748B / #94A3B8
error/warning/info/success: MUI defaults, retuned to hit 4.5:1 on both surfaces
```

**Dark mode is the default in fullscreen/compare.** A bright chrome surrounding a photograph biases perception of that photograph's exposure — the surveyor is judging the image, and the frame must not lie to their eye. This is the same reason image editors are dark.

The canvas backdrop is deliberately darker than `background.default` in both modes, so the image's extent is unambiguous and edge annotations are legible against the void.

### 9.4 Typography

Inter (variable, self-hosted — no CDN, the app must work offline in a field) with a system fallback stack. **JetBrains Mono for all numerics**: every coordinate, pixel value, and confidence score renders in a tabular monospace, `font-variant-numeric: tabular-nums`. Non-tabular figures make a column of latitudes impossible to scan for anomalies, and scanning for anomalies is the surveyor's core review task in §8.2.

| Variant | Size / LH / Weight / Tracking | Use |
| --- | --- | --- |
| `h1` | 28 / 34 / 600 / -0.02em | page titles |
| `h2` | 22 / 28 / 600 / -0.01em | dialog titles |
| `h3` | 18 / 24 / 600 / 0 | pane headers |
| `subtitle1` | 15 / 20 / 600 | section labels |
| `subtitle2` | 13 / 18 / 600 / 0.02em | pane header eyebrow |
| `body1` | 15 / 22 / 400 | prose |
| `body2` | 13 / 20 / 400 | dense UI, table cells |
| `caption` | 12 / 16 / 400 | hints, attribution |
| `overline` | 11 / 16 / 600 / 0.08em | column headers |
| `button` | 14 / 20 / 600 / 0.01em, `textTransform: none` | all buttons |
| `mono` (custom) | 13 / 18 / 450, tabular-nums | **all coordinates & scores** |

`textTransform: none` globally. SHOUTING BUTTONS harm scannability and hurt localization.

### 9.5 Confidence scale in the theme (`confidence.ts`)

```ts
export const CONFIDENCE_THRESHOLDS = { high: 0.85, moderate: 0.65, low: 0.40 } as const;
export function confidenceBand(score: number, isManual: boolean): ConfidenceBand;
export function confidenceColor(band: ConfidenceBand, mode: 'light' | 'dark'): string;
export function confidenceLabel(band: ConfidenceBand): string;   // 'High' | 'Moderate' | ...
export function heatmapColor(v: number): [number, number, number, number];   // RGBA, §8.6.2
```

Exposed on the MUI theme as `theme.palette.confidence[band]` so `sx` can reach it without importing, but the functions above remain the single source of truth for the thresholds (§8.6.1).

### 9.6 Component overrides (`components.ts`)

- `MuiButton`: `disableElevation`, `radius.md`, `textTransform: none`.
- `MuiTooltip`: 400ms enter delay, always includes the shortcut hint.
- `MuiTableCell`: dense padding (`6px 12px`), `body2`; numeric columns get `mono` + `text-align: right` (right-aligned decimals make a misplaced digit visible at a glance).
- `MuiPaper`: `backgroundImage: none` (kills MUI's dark-mode elevation tint, which shifts panel colour with elevation and undermines the neutral-chrome principle).
- `MuiIconButton`: `minWidth/minHeight: 24px` (`44px` under `@media (pointer: coarse)`) — §8.8 item 8, enforced in the theme so no component can opt out.
- `MuiCssBaseline`: `overscroll-behavior: none` (kills pull-to-refresh over the canvas — a surveyor panning an image on a tablet must never accidentally reload the app and lose a draft), `touch-action: none` on stage containers, `user-select: none` on chrome, `-webkit-tap-highlight-color: transparent`.
- Focus ring: 2px `primary.main` with a 2px offset, via `:focus-visible` only.

---

## 10. Testing strategy for this layer

| Area | Approach |
| --- | --- |
| `lib/viewport/transform.ts` | **Unit + property tests (fast-check)**. Round-trip identity (§5.2), zoom-to-cursor invariance (the cursor's image point is fixed across any `factor`), clamp idempotence (`clampPan(clampPan(t)) === clampPan(t)`), variant-swap invariance (§5.3: the viewport-centre image point is unchanged). **This file has the highest test bar in the frontend.** |
| `lib/commands/*` | Property test: for every command type and any draft, `apply` then `revert` is the identity. Merge associativity for coalesced drags. |
| Stores | Plain unit tests — Zustand stores are testable outside React. |
| `lib/confidence.ts`, `lib/coordinates.ts` | Exhaustive table tests over band boundaries (`0.849999`, `0.85`, `0.850001`) and the precision policy. |
| Components | RTL + `@testing-library/user-event`. Konva via `react-konva` in a `jsdom` canvas mock; hit-testing tested at the `stageToImage` level rather than through the canvas. |
| React Query | MSW handlers per endpoint. Job polling tested with fake timers, including the terminal-status stop (§3.2). |
| Visual | Storybook + Chromatic on the pure components; the confidence palette gets a dedicated story rendering all bands × both modes × a deuteranopia filter. |
| E2E | Playwright against the compose stack: upload → annotate → match → export, plus the `low_confidence` and `no_location_hint` paths — the failure paths are E2E-tested precisely because they are the ones that matter most and are exercised least in manual testing. |
| A11y | `jest-axe` per component; Playwright + axe on the flows; manual NVDA/VoiceOver pass on the canvas listbox (§8.8). |

No test in this layer requires a GPU, model weights, or network access — per the environment constraints, MSW and fixtures cover everything.

---

## 11. Open questions for other workstreams

1. **Backend** — confirm `ImageDisplayVariant.originalWidth/Height` on every variant response. §5.1 depends on it absolutely; without it the frontend cannot compute `D` and P2 collapses.
2. **Backend** — confirm `adjustGcp` returns `{ gcp, recomputed }` (§7.2); §3.3's honest optimistic update depends on knowing exactly which points moved.
3. **Backend** — confirm `MatchResult.status` includes `'low_confidence'` as distinct from `'succeeded'`. The frontend treats it as a distinct state throughout §8.5.3; a bare score would force the threshold logic to live in two places.
4. **Backend/CV** — is `errorRadiusM` computable per-GCP out of the box on the classical path? §8.6.3's precision policy degrades gracefully without it (falls back to band-only), but is materially better with it.
5. **Backend** — `ConfidenceGrid` resolution: is ≤64×64 acceptable, or should the frontend request a resolution?
6. **Product** — the low-confidence export acknowledgement (§2.23): confirm the exact legal wording with the client.
7. **DevOps** — the tile proxy (§2.16) must terminate provider keys server-side; confirm the endpoint shape `GET /api/v1/tiles/{providerId}/{kind}/{z}/{x}/{y}` and its cache headers.
