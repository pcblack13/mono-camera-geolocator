/**
 * `map/MapPanel.tsx` — the mandated right-hand 2D satellite pane. 50-frontend §2.16.
 *
 * ★ THE CONTAINER. It reads the stores and queries and passes plain data down to the
 *   pure/leaf map components. It owns:
 *   - provider + basemap resolution (default is KEYLESS Esri, L2);
 *   - the GCP marker layer (committed rows from React Query — L7);
 *   - MANUAL GCP MODE's map half (SCOPE.md §5): the click that captures EPSG:4326, the
 *     live linked draft marker, the crosshair, the zoom + GSD + achievable-accuracy
 *     readout, and the commit panel;
 *   - cross-pane REVEAL: a GCP selected in the table/image flies into view here, but a
 *     selection made ON the map never yanks the map (§3.5, gated on `focusOrigin`).
 *
 * ★ Deferred, honestly (SCOPE.md §4 rule 4): the confidence-heatmap toggle is disabled
 *   with the honest tooltip — the heatmap is a product of automatic matching, which is
 *   off in this build.
 */

import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Box from '@mui/material/Box';
import IconButton from '@mui/material/IconButton';
import Tooltip from '@mui/material/Tooltip';
import TuneOutlinedIcon from '@mui/icons-material/TuneOutlined';
import Typography from '@mui/material/Typography';
import { useTheme } from '@mui/material/styles';
import useMediaQuery from '@mui/material/useMediaQuery';
import OpenInFullIcon from '@mui/icons-material/OpenInFull';
import CloseFullscreenIcon from '@mui/icons-material/CloseFullscreen';
import LocalFireDepartmentOutlinedIcon from '@mui/icons-material/LocalFireDepartmentOutlined';

import { useGcps, useImage, useProjectDem, useProviders } from '../../api/hooks';
import { useAccuracyState } from '../../api/hooks/useAccuracy';
import { ErrorHeatOverlay } from './ErrorHeatOverlay';
import { AccuracySettingsPanel } from '../accuracy/AccuracySettingsPanel';
import { HeatmapHistoryMenu } from '../accuracy/HeatmapHistoryMenu';
import { useColorMode } from '../../theme';
import { confidenceColor, gcpConfidenceBand } from '../../lib/confidence';
import {
  useCorrespondenceStore,
  useMapStore,
  useOfflineCacheStore,
  useSelectionStore,
  useWorkspaceStore,
} from '../../store';
import type { Uuid } from '../../types/common';
import type { LatLon, ProviderId } from '../../types/geo';

import { BasemapSwitcher } from './BasemapSwitcher';
import { CorrespondenceLayer } from './CorrespondenceLayer';
import { PredictionLayer } from './PredictionLayer';
import { GcpMarkerLayer } from './GcpMarkerLayer';
import { LocationHintControl } from './LocationHintControl';
import { OfflineCacheLayer } from './OfflineCacheLayer';
import { AutoCacheStatusChip } from './AutoCacheStatusChip';
import { OfflineCachePanel } from './OfflineCachePanel';
import { ViewportCacheReporter } from './ViewportCacheReporter';
import { MapAccuracyReadout } from './MapAccuracyReadout';
import { CursorCoordinateReadout } from './CursorCoordinateReadout';
import { CursorElevationReadout } from './CursorElevationReadout';
import { DrawingBanner } from './DrawingBanner';
import { DEFAULT_EXAGGERATION } from './terrainDefaults';
import { ViewModeSwitch, type MapViewMode } from './ViewModeSwitch';
import { useCursorElevation } from './useCursorElevation';
import { ProviderAttribution } from './ProviderAttribution';
import { SatelliteMap } from './SatelliteMap';
import { accuracyFromMetresPerPixel, clampBasemapToKinds, estimateClickAccuracy } from './tileMath';
import { gcpBounds } from '../../lib/geo/gcpBounds';
import { t } from '../../i18n';

export interface MapPanelProps {
  /**
   * ★ Re-open this project's workspace setup (elevation source + imagery). Optional so
   * the panel keeps working in surfaces that have no setup step — CompareView, tests.
   */
  onOpenSetup?: () => void;
  imageId: Uuid | null;
  /**
   * ★ The project whose DEM the cursor readout samples. Optional so the panel keeps
   * working in surfaces that have no project context (CompareView, tests) — there the
   * readout simply stays idle rather than sampling some other project's raster.
   */
  projectId?: Uuid | null;
  /** DEFERRED in this build — no match result exists (SCOPE.md §1). Kept for the seam. */
}

// ★ LAZY, AND FOR A MEASURED REASON. maplibre-gl is ~800 kB — larger than the rest of
//   the workspace put together — and 3D is an optional viewing aid that many sessions
//   never open. Loading it eagerly made WorkspacePage 944 kB; behind this boundary the
//   cost is paid only by someone who actually switches to 3D.
const Terrain3DMap = lazy(() =>
  import('./Terrain3DMap').then((m) => ({ default: m.Terrain3DMap })),
);

const CHROME_Z = 1000;

/** Shown while the 3D bundle downloads. Says what is happening, not just that it is. */
function TerrainLoading(): JSX.Element {
  return (
    <Box
      sx={{
        width: '100%',
        height: '100%',
        display: 'grid',
        placeItems: 'center',
        color: 'text.secondary',
      }}
    >
      <Typography variant="body2">{t('Loading the 3D terrain view…')}</Typography>
    </Box>
  );
}

export function MapPanel({ imageId, projectId = null, onOpenSetup }: MapPanelProps): JSX.Element {
  // ── the measured error, on the pane where the next point gets placed ─────────
  // ★ Shown as soon as a measurement exists, because the loop produced it without
  //   being asked and its whole purpose is to change where the surveyor clicks next.
  //   Off is one click away — it is an overlay on their working surface.
  const accuracyQuery = useAccuracyState(imageId);
  const accuracyState = accuracyQuery.data;
  const [showErrorHeat, setShowErrorHeat] = useState(true);
  const { elevation: cursorElevation, onCursorMove: onCursorMoveElevation } =
    useCursorElevation(projectId);

  // ★ The POSITION is immediate; the ELEVATION is debounced (a DEM sample per
  //   mousemove would saturate the API — see `useCursorElevation`). One handler
  //   feeds both, so the two readouts never disagree about which point they mean.
  const [cursorAt, setCursorAt] = useState<LatLon | null>(null);
  const onCursorMove = useCallback(
    (at: LatLon | null): void => {
      setCursorAt(at);
      onCursorMoveElevation(at);
    },
    [onCursorMoveElevation],
  );
  const coordinateFormat = useWorkspaceStore((s) => s.coordinateFormat);

  // ★ 2D is the default and stays so. It owns every GCP layer, the offline cache and
  //   the footprint; 3D is an additional way to LOOK at the site, not a replacement
  //   for the pane the product's core interaction runs in.
  const [viewMode, setViewMode] = useState<MapViewMode>('2d');
  const [exaggeration, setExaggeration] = useState(DEFAULT_EXAGGERATION);
  // ★ Measured under the pointer by the 3D pane. Null in 2D, and null in 3D whenever the
  //   ray misses the ground (above the horizon there is nothing to be precise about).
  const [groundScale3d, setGroundScale3d] = useState<number | null>(null);

  // ★ Asked up front, not discovered from a failed tile: without a DEM the 3D view
  //   renders flat ground that looks entirely real, so the control must be disabled
  //   with its reason BEFORE it is clicked (SCOPE.md §4 rule 4).
  const projectDemQuery = useProjectDem(projectId);
  const theme = useTheme();
  const { mode: themeMode } = useColorMode();
  const reducedMotion = useMediaQuery('(prefers-reduced-motion: reduce)');

  // ── stores ──────────────────────────────────────────────────────────────────
  const view = useMapStore((s) => s.view);
  const seq = useMapStore((s) => s.seq);
  const lastOrigin = useMapStore((s) => s.lastOrigin);
  const basemap = useMapStore((s) => s.basemap);
  const providerId = useMapStore((s) => s.providerId);
  const locationHint = useMapStore((s) => s.locationHint);
  const setView = useMapStore((s) => s.setView);
  const setBasemap = useMapStore((s) => s.setBasemap);
  const setProvider = useMapStore((s) => s.setProvider);
  const setLocationHint = useMapStore((s) => s.setLocationHint);
  const flyToGcp = useMapStore((s) => s.flyToGcp);
  const fitBounds = useMapStore((s) => s.fitBounds);

  // ★ Reactive, unlike the `getState()` reads in the click handlers: the CURSOR and
  //   the banner must change the instant drawing starts, not on the next click.
  const cacheDrawing = useOfflineCacheStore((s) => s.drawing);
  const cachePoints = useOfflineCacheStore((s) => s.points.length);

  const corrStatus = useCorrespondenceStore((s) => s.status);
  const corrLatLon = useCorrespondenceStore((s) => s.lat_lon);
  const corrOpen = corrStatus !== 'idle';
  const placing = corrOpen && corrStatus !== 'committing';

  const selected = useSelectionStore((s) => s.selected);
  const focusOrigin = useSelectionStore((s) => s.focusOrigin);
  const selectGcp = useSelectionStore((s) => s.select);

  // ── queries ─────────────────────────────────────────────────────────────────
  const providersQuery = useProviders();
  const providers = useMemo(() => providersQuery.data?.items ?? [], [providersQuery.data]);
  const gcpsQuery = useGcps(imageId);
  const gcps = useMemo(() => gcpsQuery.data?.items ?? [], [gcpsQuery.data]);
  const imageQuery = useImage(imageId);
  const exifGps = useMemo(
    (): LatLon | null =>
      imageQuery.data?.gps ? { lat: imageQuery.data.gps.lat, lon: imageQuery.data.gps.lon } : null,
    [imageQuery.data?.gps],
  );

  const activeProvider = useMemo(() => {
    const byChoice = providerId ? providers.find((p) => p.name === providerId) : undefined;
    // ★ A PERSISTED choice must still be USABLE to win. `providerId` outlives server
    //   config changes (localStorage), so a provider chosen last month can be banned
    //   (LE_ALLOWED_PROVIDERS) or unconfigured today — honouring it would point every
    //   tile at a 403/503 and render the "blank map" with no error anywhere. The
    //   switcher can only SELECT usable providers, so falling back to the server
    //   default here is the same rule applied to remembered state.
    const usable =
      byChoice && byChoice.configured && byChoice.allowed !== false ? byChoice : undefined;
    return usable ?? providers.find((p) => p.is_default) ?? providers[0];
  }, [providers, providerId]);

  // ★ HEAL an impossible (provider, kind) pair — `clampBasemapToKinds` explains why one
  //   can exist at all. Clamp in the STORE, not just in the render: the switcher must
  //   show the kind actually being served, and the healed value must persist.
  const activeKinds = activeProvider?.capabilities.kinds;
  useEffect(() => {
    const healed = clampBasemapToKinds(basemap, activeKinds);
    if (healed !== basemap) setBasemap(healed);
  }, [activeKinds, basemap, setBasemap]);

  // ★ Detaching the DEM while 3D is open no longer ejects to 2D: Terrain3DMap swaps to
  //   the GLOBAL terrarium fallback in place and labels the surface change on-screen.
  //   The eject existed because the alternative was silent flat ground; that
  //   alternative is gone.
  useEffect(() => {
    // ★ A stale 3D scale must never survive into 2D: it would show a pitched-camera
    //   precision beside a nadir map.
    if (viewMode === '2d' && groundScale3d !== null) setGroundScale3d(null);
  }, [viewMode, groundScale3d]);

  useEffect(() => {
    // ★ MODE-SWITCH HYGIENE, two pieces:
    //   1. An offline-cache draw only exists in 2D (`OfflineCacheLayer` is a Leaflet
    //      layer) — but `drawing === true` swallows EVERY map click. Entering 3D with
    //      a draw open used to leave the pane silently unclickable; the draw dies
    //      with the mode instead.
    //   2. The cursor-elevation readout keeps its last value across a switch (the
    //      unmounting pane fires no mouseout) — clear it, the same honesty rule the
    //      in-pane mouseout applies.
    if (viewMode === '3d' && useOfflineCacheStore.getState().drawing) {
      useOfflineCacheStore.getState().reset();
    }
    onCursorMove(null);
  }, [viewMode, onCursorMove]);

  // ── cross-pane reveal: table/image selection → map fly (never map→map) ────────
  const selectedGcpId = useMemo(() => {
    // A GCP ref names the GCP directly; a landmark ref (from a click on the photo) names
    // its GCP through linkedId. Resolve BOTH so clicking a landmark also flies the map.
    const gcpRef = selected.find((r) => r.kind === 'gcp');
    if (gcpRef) return gcpRef.id;
    const annRef = selected.find((r) => r.kind === 'annotation' && r.linkedId !== null);
    return annRef?.linkedId ?? null;
  }, [selected]);

  useEffect(() => {
    if (selectedGcpId === null || focusOrigin === 'map') return;
    const gcp = gcps.find((g) => g.id === selectedGcpId);
    if (gcp) flyToGcp({ lat: gcp.lat, lon: gcp.lon });
  }, [selectedGcpId, focusOrigin, gcps, flyToGcp]);

  // ── one-time fly when a new image loads: ONTO ITS CONTROL POINTS ─────────────
  // ★ OPEN ON THE WORK (owner ask 2026-09-10). A frame that already has points
  //   opens the map framed on them — where the surveyor pointed — with a margin;
  //   a single point at the reveal zoom. Only a frame with NO points falls back
  //   to the photo's EXIF fix. The decision waits for the points query to answer,
  //   so a frame never opens on the wrong place and then jumps.
  const flownForImage = useRef<string | null>(null);
  useEffect(() => {
    if (imageId === null || flownForImage.current === imageId) return;
    if (!gcpsQuery.isSuccess && !gcpsQuery.isError) return; // still asking
    const box = gcpBounds(gcps.map((g) => ({ lat: g.lat, lon: g.lon })));
    if (box !== null) {
      flownForImage.current = imageId;
      if (gcps.length === 1) flyToGcp({ lat: gcps[0].lat, lon: gcps[0].lon });
      else fitBounds(box, 'image');
      return;
    }
    if (exifGps === null) return;
    flownForImage.current = imageId;
    setView({ center: exifGps, zoom: 16, bounds: null }, 'image');
  }, [imageId, exifGps, setView, gcps, gcpsQuery.isSuccess, gcpsQuery.isError, fitBounds, flyToGcp]);

  // ── map click: place/move the correspondence, else clear selection ────────────
  const onMapClick = useCallback((at: LatLon) => {
    // ★ While drawing an offline-cache area, OfflineCacheLayer captures the click to append a
    //   vertex — defer to it so a click never places a GCP or clears the selection too.
    if (useOfflineCacheStore.getState().drawing) return;
    const corr = useCorrespondenceStore.getState();
    if (corr.status !== 'idle' && corr.status !== 'committing') {
      corr.setMapPoint(at);
      return;
    }
    const sel = useSelectionStore.getState();
    if (sel.selected.length > 0) sel.clear();
  }, []);

  const onViewChange = useCallback(
    (v: typeof view, origin: Parameters<typeof setView>[1]) => setView(v, origin),
    [setView],
  );

  // ── maximise the map (CSS, so overlays/portals keep working; Esc exits) ────────
  // Leaflet re-measures via SatelliteMap's InvalidateSizeWatcher when the container grows.
  const [maximized, setMaximized] = useState(false);
  useEffect(() => {
    if (!maximized) return;
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') setMaximized(false);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [maximized]);

  const activeColor = theme.palette.primary.main;
  const outline = theme.palette.confidence.outline;

  // ── accuracy preview at the point being aimed at ──────────────────────────────
  const estimate = useMemo(() => {
    if (!activeProvider) return null;

    // ★★ IN 3D THE SCALE IS MEASURED, NOT DERIVED. `estimateClickAccuracy` computes
    //    metres-per-pixel from latitude and zoom, which describes a straight-down map. A
    //    pitched camera breaks that badly: a pixel near the horizon covers far more ground
    //    than one at screen centre, so the 2D figure would report a click precision several
    //    times better than the surveyor actually achieved. The 3D pane unprojects two
    //    adjacent pixels and reports the real number; we use it whenever we have it.
    if (viewMode === '3d' && groundScale3d !== null) {
      return accuracyFromMetresPerPixel(groundScale3d, activeProvider.capabilities.georef_ce90_m);
    }

    const at = corrLatLon ?? view.center;
    // ★ NOT the provider's tile_size_px. Leaflet's screen scale is 256·2^zoom CSS px
    //   for EVERY tile size — `tileSize`/`zoomOffset` change which tiles fill that
    //   scale, not the scale itself. Passing 512 here halved the reported GSD and the
    //   click term with it: a flattering, wrong accuracy preview on a survey tool.
    return estimateClickAccuracy(at, view.zoom, activeProvider.capabilities.georef_ce90_m);
  }, [activeProvider, corrLatLon, view.center, view.zoom, viewMode, groundScale3d]);

  // ★ Same band helpers the 2D markers use, so the panes cannot disagree about a colour.
  const gcps3d = useMemo(
    () =>
      gcps.map((g) => ({
        id: g.id,
        lat: g.lat,
        lon: g.lon,
        code: g.code,
        color: confidenceColor(gcpConfidenceBand(g), themeMode),
      })),
    [gcps, themeMode],
  );

  if (imageId === null) {
    return (
      <Box sx={{ height: '100%', display: 'grid', placeItems: 'center', p: 2 }}>
        <Typography color="text.secondary" align="center">
          {t('Select an image to place ground control points on the map.')}
        </Typography>
      </Box>
    );
  }

  if (!activeProvider) {
    return (
      <Box sx={{ height: '100%', display: 'grid', placeItems: 'center', p: 2 }}>
        <Typography color="text.secondary">
          {providersQuery.isError ? 'Imagery providers are unavailable.' : 'Loading imagery…'}
        </Typography>
      </Box>
    );
  }

  return (
    <Box
      sx={{
        'position': 'relative',
        'height': '100%',
        'width': '100%',
        'overflow': 'hidden',
        // ★ Crosshair while a correspondence is open — precise placement (SCOPE.md §5).
        //   BOTH engines: Leaflet's container in 2D and MapLibre's canvas in 3D — the
        //   3D pane used to keep its grab hand during the one interaction that needs
        //   a crosshair. `!important` outranks MapLibre's own inline canvas cursor.
        '& .leaflet-container, & .maplibregl-canvas':
          placing || cacheDrawing ? { cursor: 'crosshair !important' } : undefined,
        // ★ Maximised: cover the viewport as a fixed, high-z pane (zIndex below MUI's modal
        //   layer, 1300, so dialogs/tooltips still render on top).
        ...(maximized
          ? { position: 'fixed', inset: 0, zIndex: 1200, height: '100vh', width: '100vw' }
          : {}),
      }}
    >
      {cacheDrawing && <DrawingBanner count={cachePoints} />}
      {viewMode === '3d' ? (
        <Suspense fallback={<TerrainLoading />}>
          <Terrain3DMap
            projectId={projectId}
            hasProjectDem={
              projectDemQuery.data?.active === true && projectDemQuery.data.project_id === projectId
            }
            providerId={activeProvider.name}
            basemap={basemap}
            initialView={view}
            exaggeration={exaggeration}
            maxZoom={activeProvider.capabilities.max_zoom}
            tileSizePx={activeProvider.capabilities.tile_size_px}
            onMapClick={onMapClick}
            onCursorMove={onCursorMove}
            onViewChange={(v) => setView(v, 'user')}
            gcps={gcps3d}
            draft={corrLatLon}
            onSelectGcp={(id) => selectGcp({ kind: 'gcp', id, linkedId: null }, 'replace', 'map')}
            onGroundScale={setGroundScale3d}
          />
        </Suspense>
      ) : (
        <SatelliteMap
          initialView={view}
          view={view}
          seq={seq}
          lastOrigin={lastOrigin}
          providerId={activeProvider.name}
          basemap={basemap}
          capabilities={{
            min_zoom: activeProvider.capabilities.min_zoom,
            max_zoom: activeProvider.capabilities.max_zoom,
            tile_size_px: activeProvider.capabilities.tile_size_px,
            native_max_zoom: activeProvider.capabilities.native_max_zoom,
            native_resolution_status: activeProvider.capabilities.native_resolution_status,
          }}
          reducedMotion={reducedMotion}
          onViewChange={onViewChange}
          onMapClick={onMapClick}
          onCursorMove={onCursorMove}
        >
          {/* ★ UNDER the markers: it must never hide a point or swallow the click that
            places one. */}
          {showErrorHeat && accuracyState?.measurement != null && (
            <ErrorHeatOverlay
              imageId={imageId}
              grid={accuracyState.measurement.grid}
              /*
               * ★ THE CORRECTED WINNER — the technique's own convention.
               *
               *   The reference generator plots `sols[best_key(...)].err`: the
               *   candidate that won on held-out ground, captioned "after automatic
               *   correction" beside a grey "was" carrying the RAW median. So the
               *   field drawn here is the corrected one, and the toolbar states both
               *   numbers — a corrected surface shown without the number it came from
               *   would overstate what the survey currently achieves.
               *
               *   ★ Note the division of labour, which belongs to the technique and is
               *     not ours to change: the RAW field decides WHERE THE NEXT POINT GOES
               *     (it is the only thing that says where the error actually lives
               *     before anything is fixed — see `_run_suggest`, which passes the raw
               *     Stage D result), while the CORRECTED field is what gets drawn.
               */
              stage={accuracyState.adoption?.stage ?? accuracyState.solutions?.best ?? 'raw'}
              availableLayers={accuracyState.layers}
            />
          )}
          <GcpMarkerLayer gcps={gcps} themeMode={themeMode} />
          <CorrespondenceLayer activeColor={activeColor} outline={outline} />
          <PredictionLayer activeColor={activeColor} />
          <OfflineCacheLayer color={activeColor} />
          <ViewportCacheReporter
            providerId={activeProvider.name}
            kind={basemap}
            zoomShift={activeProvider.capabilities.tile_size_px === 512 ? 1 : 0}
            cacheable={
              activeProvider.configured !== false && !activeProvider.capabilities.supports_offline
            }
            projectId={projectId}
          />
        </SatelliteMap>
      )}

      {/* ── chrome: pointer-events pass through except on the controls themselves ──
          ★ dir="ltr", deliberately (2026-09-01). The map beneath is an LtrIsland with
          Leaflet's zoom control pinned to the PHYSICAL top-left; this overlay's
          "flex-end keeps the top-left clear" contract is physical too. In Arabic the
          document flips flex-end to the left, which parked the control cluster ON
          the +/- control. The chrome shares the map's geometry, so it shares its
          direction — Arabic text inside still shapes RTL via bidi. */}
      <Box
        dir="ltr"
        sx={{
          position: 'absolute',
          inset: 0,
          zIndex: CHROME_Z,
          pointerEvents: 'none',
          p: 1,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
        }}
      >
        {/* top row — right-aligned so Leaflet's own zoom control keeps the top-left corner.
            ★ The row itself is pointer-events:none; only the control CLUSTER is auto, so the
            row's empty left half does NOT sit over (and swallow clicks to) the +/- control. */}
        <Box
          sx={{
            pointerEvents: 'none',
            display: 'flex',
            justifyContent: 'flex-end',
          }}
        >
          <Box
            sx={{
              pointerEvents: 'auto',
              display: 'flex',
              gap: 0.5,
              alignItems: 'flex-start',
              justifyContent: 'flex-end',
              flexWrap: 'wrap',
            }}
          >
            {/* ★ The error heat toggle sits with the map's own controls, not in a
              panel elsewhere: it is a layer ON this pane, so it is switched here. It
              appears only once a measurement exists — a control for nothing is noise. */}
            {accuracyState?.measurement != null &&
              accuracyState.measurement.grid.web_bounds != null && (
                <Tooltip
                  title={
                    showErrorHeat
                      ? 'Hide the measured error heat map'
                      : `Show the measured error heat map (median ${
                          accuracyState.measurement.median_error_m?.toFixed(1) ?? '?'
                        } m)`
                  }
                >
                  <IconButton
                    size="small"
                    onClick={() => setShowErrorHeat((v) => !v)}
                    aria-label={
                      showErrorHeat ? 'Hide the error heat map' : 'Show the error heat map'
                    }
                    color={showErrorHeat ? 'primary' : 'default'}
                    sx={{
                      'bgcolor': 'background.paper',
                      '&:hover': { bgcolor: 'background.paper' },
                    }}
                  >
                    <LocalFireDepartmentOutlinedIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              )}
            {/* ★ The history sits WITH the layer it is a history OF — switching the heat
                on and looking at the runs that produced it are one train of thought;
                the settings cluster on the right is a different one. */}
            {imageId !== null && <HeatmapHistoryMenu imageId={imageId} />}
            <ViewModeSwitch
              mode={viewMode}
              onModeChange={setViewMode}
              // ★ Always true now: without a project DEM the 3D pane renders the global
              //   AWS/Mapzen surface (labelled as such) instead of being disabled.
              terrainAvailable
              exaggeration={exaggeration}
              onExaggerationChange={setExaggeration}
            />
            <BasemapSwitcher
              basemap={basemap}
              availableKinds={activeProvider.capabilities.kinds}
              onBasemapChange={setBasemap}
              providers={providers}
              activeProviderId={activeProvider.name as ProviderId}
              onProviderChange={setProvider}
            />
            <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'flex-start' }}>
              {/* ★ Settings-flavoured controls cluster on the RIGHT with the pin:
                the left of the row keeps only the view controls (2D/3D, layers,
                provider), so each side reads as one family. */}
              {/* ★ The error-measurement family, beside the map's own settings: the
                  heat overlay lives on this pane, so its settings and its history do
                  too. Both appear only when there is something to configure or to
                  look back at. */}
              {imageId !== null && <AccuracySettingsPanel imageId={imageId} />}
              {onOpenSetup && (
                <Tooltip title={t('Map settings — imagery and basemap')}>
                  <IconButton
                    size="small"
                    onClick={onOpenSetup}
                    aria-label={t('Map settings')}
                    sx={{
                      'bgcolor': 'background.paper',
                      'boxShadow': 2,
                      '&:hover': { bgcolor: 'action.hover' },
                    }}
                  >
                    <TuneOutlinedIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              )}
              {/* ★ COMPARE REMOVED (1.2.6). Its two interesting modes — Linked and
                Swipe — are produced by automatic matching, which this build defers,
                so the control offered one usable option ("Independent") that is
                simply the normal side-by-side layout. A toggle whose only working
                setting is the status quo is chrome, not a feature. */}
              <LocationHintControl
                hint={locationHint}
                exifGps={exifGps}
                onChange={setLocationHint}
                onFlyTo={(p, zoom) => flyToGcp(p, zoom)}
                onFrameBounds={(b) => fitBounds(b, 'user')}
              />
              <OfflineCachePanel
                providerId={activeProvider.name as ProviderId}
                kind={basemap}
                cacheable={activeProvider.configured !== false}
                color={activeColor}
              />
              <AutoCacheStatusChip />
              <Tooltip title={maximized ? 'Exit full screen (Esc)' : 'Maximize map'}>
                <IconButton
                  size="small"
                  onClick={() => setMaximized((m) => !m)}
                  aria-label={maximized ? 'Exit full screen' : 'Maximize map'}
                  sx={{
                    'bgcolor': 'background.paper',
                    'boxShadow': 2,
                    '&:hover': { bgcolor: 'background.paper' },
                  }}
                >
                  {maximized ? (
                    <CloseFullscreenIcon fontSize="small" color="primary" />
                  ) : (
                    <OpenInFullIcon fontSize="small" />
                  )}
                </IconButton>
              </Tooltip>
            </Box>
          </Box>
        </Box>

        {/* The commit editor lives in the left inspector panel (AnnotationInspector) — the
            map no longer floats a duplicate over the imagery. */}

        {/* bottom row */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end' }}>
          <Box sx={{ pointerEvents: 'auto', display: 'flex', alignItems: 'flex-end', gap: 1 }}>
            {estimate ? (
              <MapAccuracyReadout zoom={view.zoom} estimate={estimate} active={placing} />
            ) : null}
            {/* ★ Horizontal precision and vertical source, side by side: the two halves of
                what a GCP placed here would actually be worth. */}
            {/* ★ Where the pointer IS, beside what a point there would be worth. */}
            <CursorCoordinateReadout at={cursorAt} format={coordinateFormat} />
            <CursorElevationReadout elevation={cursorElevation} />
          </Box>
          <Box sx={{ pointerEvents: 'auto' }}>
            <ProviderAttribution
              attribution={activeProvider.attribution}
              providerLabel={activeProvider.title}
              compact
            />
          </Box>
        </Box>
      </Box>
    </Box>
  );
}
