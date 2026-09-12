/**
 * `workspace/Workspace.tsx` — the layout arbiter (50-frontend §2.4 / §1).
 *
 * ★ THE MANDATED ARRANGEMENT (§1.1): LEFT uploaded image · MIDDLE annotation tools ·
 *   RIGHT satellite map · BOTTOM matched-GCP dock. This component chooses the LAYOUT
 *   and fills the slots; it does not reimplement the panes. The image/annotation panes
 *   are IU-26's, the map/GCP panes IU-27's — composed here by their contract
 *   interfaces (§3 ownership map).
 *
 * ★ SPACE WINS OVER BREAKPOINT (§1.4): the effective mode is computed from a
 *   `ResizeObserver` on this container, not the breakpoint alone — "Breakpoints are a
 *   heuristic; available space is the truth." When the container cannot fit both pane
 *   minima it demotes to the tabbed layout regardless of window size.
 *
 *
 * ★ The `beforeunload` dirty guard (annotationStore note — "wired by IU-28") lives
 *   here: an unsaved survey draft must warn before the tab closes.
 */

import { useCallback, useEffect, useRef, useState, type JSX, type ReactNode } from 'react';
import { useShallow } from 'zustand/react/shallow';
import Box from '@mui/material/Box';
import Dialog from '@mui/material/Dialog';
import Drawer from '@mui/material/Drawer';
import { useTheme } from '@mui/material/styles';
import useMediaQuery from '@mui/material/useMediaQuery';

// ── IU-26 (image / annotation) — composed by contract ────────────────────────
import { ImagePanel } from '../image/ImagePanel';
import { ToolRail } from '../annotation/ToolRail';
import { AnnotationInspector } from '../annotation/AnnotationInspector';
// ── IU-27 (map / gcp) — composed by contract ─────────────────────────────────
import { MapPanel } from '../map/MapPanel';
import { clampBasemapToKinds } from '../map/tileMath';
import { GcpTable } from '../gcp/GcpTable';

import { useImage } from '../../api/hooks/useImages';
import { useProviders } from '../../api/hooks/useProviders';
import { useNotify } from '../common/Notifications';
import { useMapStore } from '../../store/mapStore';
import type { ProviderId } from '../../types/geo';
import { useAnnotationStore } from '../../store/annotationStore';
import { useCorrespondenceStore } from '../../store/correspondenceStore';
import { useProjectSetupStore } from '../../store/projectSetupStore';
import { useSelectionStore } from '../../store/selectionStore';
import { useWorkspaceStore } from '../../store/workspaceStore';
import type { Uuid } from '../../types/common';
import { t } from '../../i18n';
import { WorkspaceGrid } from './WorkspaceGrid';
import { PairingHud } from './PairingHud';
import { WorkspaceSetupPanel } from './WorkspaceSetupPanel';
import { WorkspaceTabs } from './WorkspaceTabs';

export interface WorkspaceProps {
  projectId: Uuid;
  imageId: Uuid | null;
}

// Minima from §1.4: image 320 + map 320 + rail 56 + two 6px seams.
const MIN_GRID_PX = 320 + 320 + 56 + 12;
const MIN_INLINE_INSPECTOR_PX = MIN_GRID_PX + 280;

/**
 * Live width of an element, via ResizeObserver — the "space wins" input (§1.4).
 *
 * ★ A CALLBACK REF, not an object ref: the root node is REPLACED when the layout flips
 *   from tabs to grid, and an observer bound once to the first node kept watching a
 *   detached element — later resizes were never seen, and the panes mounted twice.
 */
function useElementWidth(): [(el: HTMLElement | null) => void, number] {
  const [width, setWidth] = useState(0);
  const observer = useRef<ResizeObserver | null>(null);
  const ref = useCallback((el: HTMLElement | null) => {
    observer.current?.disconnect();
    observer.current = null;
    if (!el) return;
    setWidth(el.clientWidth);
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) setWidth(entry.contentRect.width);
    });
    ro.observe(el);
    observer.current = ro;
  }, []);
  return [ref, width];
}

export function Workspace({ projectId, imageId }: WorkspaceProps): JSX.Element {
  const theme = useTheme();
  const [containerRef, width] = useElementWidth();

  const isMdUp = useMediaQuery(theme.breakpoints.up('md'));
  const isSmUp = useMediaQuery(theme.breakpoints.up('sm'));

  const {
    paneSizes,
    inspectorOpen,
    dockOpen,
    activeTab,
    focusPane,
    panesSwapped,
    setPaneSizes,
    resetPaneSizes,
    toggleInspector,
    setActiveTab,
    setFocusPane,
  } = useWorkspaceStore(
    useShallow((s) => ({
      paneSizes: s.paneSizes,
      inspectorOpen: s.inspectorOpen,
      dockOpen: s.dockOpen,
      activeTab: s.activeTab,
      focusPane: s.focusPane,
      panesSwapped: s.panesSwapped,
      setPaneSizes: s.setPaneSizes,
      resetPaneSizes: s.resetPaneSizes,
      toggleInspector: s.toggleInspector,
      setActiveTab: s.setActiveTab,
      setFocusPane: s.setFocusPane,
    })),
  );
  // ★ Dismissing the drawer must close it whichever flag opened it: while a
  //   correspondence held it open, `toggleInspector` set inspectorOpen=true instead.
  const closeInspector = (): void => {
    if (inspectorOpen) toggleInspector();
  };

  const dirty = useAnnotationStore((s) => s.dirty);

  // ★ THE INSPECTOR COLUMN IS EARNED, NOT STANDING.
  //   It used to hold a permanent panel whose idle state was one paragraph and a
  //   "New GCP correspondence" button — a whole column of a three-pane workspace spent
  //   on a button that now sits in the photo's own header. It appears only when it has
  //   something to say: an open correspondence (the confidence + Commit step, which is
  //   the ONLY place a GCP can be committed) or a selected landmark to edit.
  const correspondenceOpen = useCorrespondenceStore((s) => s.status !== 'idle');
  const projectConfigured = useProjectSetupStore((s) => s.get(projectId).configured);
  const projectSetup = useProjectSetupStore((s) => s.get(projectId));

  // ★ APPLY the project's imagery choice — the setup dialog used to STORE it and
  //   nothing read it, so picking Google or Esri there changed nothing on the map.
  //   Entering a configured workspace seeds the map store from the project's setup;
  //   the BasemapSwitcher stays live afterwards for ad-hoc switching. A provider is
  //   seeded ONLY when the server reports it configured: pointing the map at keyless
  //   Google would render a blank grid of failed tiles, and the setup caveat already
  //   names the two variables that turn it on.
  const providersQuery = useProviders();
  const setMapProvider = useMapStore((s) => s.setProvider);
  const setMapBasemap = useMapStore((s) => s.setBasemap);
  const notify = useNotify();
  // One warning per (project, source): the effect re-runs on every query refresh, and
  // a fallback that nags on each one would train the surveyor to dismiss warnings.
  const warnedFallbackRef = useRef<string | null>(null);
  useEffect(() => {
    if (!projectConfigured) return;
    const wanted: ProviderId | null =
      projectSetup.source === 'google'
        ? // ★ Map Tiles, NOT the retired Static option: the setup panel's
          //   "configured" chip checks google_map_tiles, and pointing the map at
          //   the static endpoint would burn a watermark into every tile.
          ('google_map_tiles' as ProviderId)
        : projectSetup.source === 'sentinel'
          ? ('sentinel_copernicus' as ProviderId)
          : projectSetup.source === 'mapbox'
            ? ('mapbox_satellite' as ProviderId)
            : projectSetup.source === 'esri'
              ? ('esri_world_imagery' as ProviderId)
              : null; // 'offline': keep the provider whose tiles were cached
    // The kind seeded below may predate a provider change (Esri served hybrid/terrain;
    // Mapbox is satellite-only) — clamp it to what the seeded provider can draw, or
    // every tile request would be refused and the map would open blank.
    let seedBasemap = projectSetup.basemap;
    if (wanted) {
      const info = providersQuery.data?.items.find((x) => x.name === wanted);
      // `allowed !== false`: an operator-banned provider (LE_ALLOWED_PROVIDERS) is a
      // 403 server-side — as unusable as a missing key, and warned about identically.
      if (info?.configured && info.allowed !== false) {
        setMapProvider(wanted);
        seedBasemap = clampBasemapToKinds(seedBasemap, info.capabilities?.kinds);
      } else if (info !== undefined) {
        // ★ NEVER SILENT. The guard (don't point the map at an unconfigured provider)
        //   is correct; applying it without saying so read as "I picked Google and it
        //   stayed on the default". Name the choice, the fallback, and the fix.
        const key = `${projectId}:${projectSetup.source}`;
        if (warnedFallbackRef.current !== key) {
          warnedFallbackRef.current = key;
          const sourceLabel =
            projectSetup.source === 'google'
              ? 'Google Map Tiles'
              : projectSetup.source === 'mapbox'
                ? 'Mapbox Satellite'
                : projectSetup.source === 'esri'
                  ? 'Esri World Imagery'
                  : 'Sentinel/Copernicus';
          notify(
            `${sourceLabel} is not available on the server, so the map is using the ` +
              'default provider. Set its credentials in backend/.env and restart the ' +
              'API (details in the workspace settings dialog).',
            { severity: 'warning' },
          );
        }
      }
    }
    setMapBasemap(seedBasemap);
  }, [
    projectId,
    projectConfigured,
    projectSetup.source,
    projectSetup.basemap,
    providersQuery.data,
    setMapProvider,
    setMapBasemap,
    notify,
  ]);
  const reopenSetup = useProjectSetupStore((s) => s.reopen);
  const setProjectSetup = useProjectSetupStore((s) => s.set);
  const markConfigured = (id: Uuid): void => setProjectSetup(id, { configured: true });
  const hasSelection = useSelectionStore((s) => s.selected.length > 0);
  const inspectorHasContent = correspondenceOpen || hasSelection;

  // ── Phase 4: focus mode on the keyboard — ⇧F cycles, Esc exits ─────────────
  //   ⇧F, not F: plain F is the photograph's own "fit to view". Esc only acts
  //   while a pane is focused, so dialogs keep their close key untouched.
  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      const el = e.target as HTMLElement | null;
      const typing =
        el !== null &&
        (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable);
      if (typing) return;
      if (e.key.toLowerCase() === 'f' && e.shiftKey && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        const s = useWorkspaceStore.getState();
        s.setFocusPane(s.focusPane === null ? 'image' : s.focusPane === 'image' ? 'map' : null);
      } else if (e.key === 'Escape' && useWorkspaceStore.getState().focusPane !== null) {
        useWorkspaceStore.getState().setFocusPane(null);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // ── beforeunload guard while there is an unsaved draft (store note: IU-28) ──
  useEffect(() => {
    if (!dirty) return undefined;
    const handler = (e: BeforeUnloadEvent): void => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [dirty]);

  // ── the image's latest match (null in this build — matching deferred) ──
  const { data: image } = useImage(imageId);
  const matchResultId: Uuid | null = image?.latest_match?.match_result_id ?? null;

  // ── effective layout mode: space wins over breakpoint ──
  const canGrid = isMdUp && width >= MIN_GRID_PX;
  const inspectorInline = canGrid && width >= MIN_INLINE_INSPECTOR_PX;

  // The pane nodes — built ONCE and handed to whichever layout renders.
  const imagePane: ReactNode = imageId ? <ImagePanel imageId={imageId} /> : null;
  // ★ THE MAP SLOT IS UNCONDITIONAL. It held the setup panel for one revision and that
  //   was a mistake: anything that made `configured` momentarily false — a store
  //   rehydration, a re-render at the wrong moment — took the map off screen, and the
  //   surveyor lost the thing they were aiming at. Setup is a PROJECT-level decision made
  //   ONCE, so it belongs in a dialog OVER the workspace, not in the pane the workflow
  //   depends on. The map mounts once and stays mounted for the life of the workspace.
  const mapPane: ReactNode = (
    <MapPanel projectId={projectId} imageId={imageId} onOpenSetup={() => reopenSetup(projectId)} />
  );
  const dockPane: ReactNode = imageId ? (
    <GcpTable imageId={imageId} projectId={projectId} matchResultId={matchResultId} />
  ) : null;
  // ★ The undo/redo/delete rail appears ONLY while a GCP correspondence is open
  //   (1.2.6) — that is when marks are being placed and moved, so that is when the
  //   buttons mean something. Outside that stage they were dead chrome.
  const toolRail: ReactNode =
    imageId && correspondenceOpen ? <ToolRail orientation="vertical" /> : null;
  const inspector: ReactNode = imageId ? <Inspector imageId={imageId} /> : null;

  const dockHeight = paneSizes.dockPx;

  // ★ Setup is shown ONCE per project, over whatever layout is active — never in place
  //   of a pane. `configured` is set by the panel's own "Open the map"; the gear on the
  //   map header sets it back to false to reopen.
  const setupDialog: ReactNode = (
    <Dialog
      open={!projectConfigured}
      onClose={() => markConfigured(projectId)}
      maxWidth="sm"
      fullWidth
      scroll="body"
    >
      <WorkspaceSetupPanel projectId={projectId} />
    </Dialog>
  );

  // ── Tabbed (tablet / mobile, or too little space) ──
  if (!canGrid) {
    return (
      <Box ref={containerRef} sx={{ height: '100%', minHeight: 0, position: 'relative' }}>
        <PairingHud />
        <WorkspaceTabs
          activeTab={activeTab}
          onTabChange={setActiveTab}
          tabBarPosition={isSmUp ? 'top' : 'bottom'}
          badges={{}}
          imagePane={
            <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
              {toolRail}
              <Box sx={{ flex: 1, minHeight: 0 }}>{imagePane}</Box>
            </Box>
          }
          mapPane={mapPane}
          dock={dockPane}
        />
        {/* Inspector as a full-height temporary drawer below md (§1.5). */}
        <Drawer
          anchor="right"
          open={(inspectorOpen || correspondenceOpen) && inspectorHasContent}
          onClose={closeInspector}
        >
          <Box sx={{ width: 320, height: '100%' }}>{inspector}</Box>
        </Drawer>
        {setupDialog}
      </Box>
    );
  }

  // ── Focus mode (desktop): ONE pane fills the workspace, the other rides in a
  //    picture-in-picture corner. The dock steps aside — focus means canvas — and
  //    the inspector keeps its overlay drawer below, because it holds the only
  //    Commit button and focus must never make the core action unreachable.
  //    Clicking the PiP swaps which pane is focused: the miniature is a door,
  //    not a poster.
  if (canGrid && focusPane !== null) {
    const focused = focusPane === 'image' ? imagePane : mapPane;
    const other = focusPane === 'image' ? mapPane : imagePane;
    return (
      <Box ref={containerRef} sx={{ height: '100%', minHeight: 0, position: 'relative' }}>
        <Box sx={{ position: 'absolute', inset: 0 }}>{focused}</Box>
        <Box
          role="button"
          aria-label={t('Switch panes')}
          tabIndex={0}
          onClick={() => setFocusPane(focusPane === 'image' ? 'map' : 'image')}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              setFocusPane(focusPane === 'image' ? 'map' : 'image');
            }
          }}
          sx={{
            'position': 'absolute',
            'right': 12,
            'bottom': 12,
            'width': 300,
            'height': 190,
            'borderRadius': 'var(--radius-lg)',
            'overflow': 'hidden',
            'border': '1px solid var(--hairline-strong)',
            'boxShadow': 'var(--elev-popover)',
            'cursor': 'pointer',
            'zIndex': (t2) => t2.zIndex.appBar - 1,
            // The miniature is a viewport, not a control surface — its pane must
            // not eat the click that swaps focus.
            '& > *': { pointerEvents: 'none' },
          }}
        >
          {other}
        </Box>
        <PairingHud />
        <Drawer
          anchor="right"
          variant="temporary"
          open={correspondenceOpen && inspectorHasContent}
          onClose={closeInspector}
        >
          <Box sx={{ width: 300, height: '100%' }}>{inspector}</Box>
        </Drawer>
        {setupDialog}
      </Box>
    );
  }

  // ── Grid (desktop). Inspector inline at lg+, overlay drawer at md. ──
  return (
    <Box ref={containerRef} sx={{ height: '100%', minHeight: 0, position: 'relative' }}>
      <PairingHud />
      <WorkspaceGrid
        paneSizes={paneSizes}
        // ★ `correspondenceOpen` FORCES the panel open regardless of the user's toggle.
        //   It holds the confidence declaration and the Commit button — the only place a
        //   GCP can be committed — so a collapsed inspector would make the product's core
        //   action unreachable with no visible cause.
        inspectorOpen={
          inspectorInline && (inspectorOpen || correspondenceOpen) && inspectorHasContent
        }
        dockOpen={dockOpen}
        dockHeight={dockHeight}
        onResizeColumns={setPaneSizes}
        onResizeDock={(px) => setPaneSizes({ dockPx: px })}
        onResetColumns={resetPaneSizes}
        // ★ Swap exchanges the SLOTS, not the panes' internals: the splitter
        //   fractions follow the slot, which is what a mirrored layout means.
        imagePane={panesSwapped ? mapPane : imagePane}
        toolRail={toolRail}
        inspector={inspector}
        mapPane={panesSwapped ? imagePane : mapPane}
        dock={dockPane}
      />
      {!inspectorInline && (
        <Drawer
          anchor="right"
          variant="temporary"
          open={(inspectorOpen || correspondenceOpen) && inspectorHasContent}
          onClose={closeInspector}
        >
          <Box sx={{ width: 300, height: '100%' }}>{inspector}</Box>
        </Drawer>
      )}
      {setupDialog}
    </Box>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Middle-region wiring — pure IU-26 components bound to IU-25 stores.
//
// ★ These adapters keep `Workspace` a layout arbiter: they read the tool/annotation/
//   selection stores (all client state, IU-25) and pass the resulting controlled
//   props into the presentational toolbar/inspector. They add NO annotation
//   semantics of their own — every mutation goes through `annotationStore.execute`,
//   the single command sink (§4).
// ─────────────────────────────────────────────────────────────────────────────

// ToolRail lives in `annotation/ToolRail.tsx` — extracted so the fullscreen ImagePanel can
// mount its own instance without a Workspace↔ImagePanel import cycle.

function Inspector({ imageId }: { imageId: Uuid }): JSX.Element {
  // ★ `AnnotationInspector` is self-contained: it reads the selection, the annotation
  //   draft, and the `execute` command sink straight from the stores (§3.7). It needs
  //   only the image it is editing.
  //
  // ★ VERSION HISTORY REMOVED (1.2.6). The drawer it opened never had anything to
  //   show — annotation edits are autosaved and no version is ever written, so every
  //   visit read "No saved versions yet". `workspaceStore` keeps its
  //   `versionDrawerOpen` flag (persisted state other builds may hold); nothing sets
  //   it any more.
  return <AnnotationInspector imageId={imageId} />;
}

export default Workspace;
