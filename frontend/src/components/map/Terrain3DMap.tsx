/**
 * `map/Terrain3DMap.tsx` — the tilted terrain view. MapLibre GL, not Leaflet.
 *
 * The 2D pane (`SatelliteMap`) is raster Leaflet and is documented **2D ONLY** by the task
 * brief: north-up, no bearing, no tilt. That constraint is right for the pane that owns
 * the GCP layers, the offline cache and the footprint — a WebGL rewrite of all of it would
 * risk the product's core interaction for a viewing angle. So this is an *additional*
 * view, mounted beside that one, and the 2D pane keeps every layer it has.
 *
 * ★ **WHY A SECOND MAP LIBRARY AT ALL.** Matching an oblique ground-level photograph
 *   against a nadir basemap is the hard part of manual GCP work: a wall you can see the
 *   face of from the ground is a thin line from directly above. Tilting the terrain lets
 *   the surveyor look at the site from roughly the camera's own attitude, which is the
 *   whole reason a desktop globe gets used for this. Leaflet cannot do it at any price.
 *
 * ★★ **THE MESH IS A PICTURE. IT IS NOT THE Z.** The heights rendered here come from
 *    `/projects/{id}/terrain/{z}/{x}/{y}.png` — resampled, quantised to 1/256 m, and with
 *    voids filled at sea level so the surface does not tear. **No GCP elevation is ever
 *    read from this view.** A committed point's Z comes from the sampling endpoint, which
 *    answers `null` where there is no data and carries a vertical CE90. The readout in
 *    this pane calls that same endpoint, so what the surveyor reads is the authoritative
 *    number even while looking at the approximate surface.
 *
 * ★ **TERRAIN IS ONLY AS GOOD AS THE PROJECT'S DEM.** With no DEM attached the terrain
 *   source 404s every tile, MapLibre renders flat ground, and this component says so
 *   plainly rather than presenting a flat world as though it were the terrain.
 *
 * ★ **NO EXTERNAL STYLE URL.** MapLibre's usual `style: 'https://…'` would fetch a
 *   third-party style document and whatever sources it names. The style here is an inline
 *   object whose only raster source is our own tile proxy, so this pane cannot become a
 *   back door to an imagery provider the operator did not choose (`docs/legal/
 *   imagery-terms.md` §1) and it keeps working fully offline.
 */

import { useCallback, useEffect, useRef, useState, type JSX } from 'react';
import maplibregl, { type Map as MapLibreMap } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';

import { API_BASE_URL } from '../../api/client';
import { LtrIsland } from '../common/LtrIsland';
import {
  DEFAULT_EXAGGERATION,
  GLOBAL_TERRAIN_ATTRIBUTION,
  GLOBAL_TERRAIN_MAX_ZOOM,
  terrainTileTemplate,
} from './terrainDefaults';
import { useMapStore } from '../../store/mapStore';
import type { LatLon, MapViewState } from '../../types/geo';
import type { Uuid } from '../../types/common';
import { ON_MEDIA, TERRAIN_3D } from '../../theme/paint';

/**
 * MEASURED ground metres per screen pixel at a screen point, under the live camera.
 *
 * ★★ **THE ONLY HONEST WAY TO GET THIS IN A TILTED VIEW.** The 2D formula
 *    (`circumference · cos(lat) / worldPx`) describes a straight-down map and is simply
 *    false under pitch: near the horizon one pixel can cover tens of metres while a pixel
 *    at screen centre covers one. Unprojecting two adjacent pixels and measuring the
 *    ground distance between them asks the camera what the scale actually is, wherever
 *    the pointer happens to be.
 *
 * Returns null when the ray misses the globe — above the horizon there is no ground, and
 * a click there has no ground precision to report.
 */
function groundMetresPerPixel(map: MapLibreMap, point: maplibregl.Point): number | null {
  try {
    const here = map.unproject(point);
    const oneRight = map.unproject(new maplibregl.Point(point.x + 1, point.y));
    const metres = here.distanceTo(oneRight);
    return Number.isFinite(metres) && metres > 0 ? metres : null;
  } catch {
    return null;
  }
}

/** Source ids, referenced by the terrain and layer declarations below. */
const IMAGERY_SOURCE = 'le-imagery';
const TERRAIN_SOURCE = 'le-terrain';
const GCP_SOURCE = 'le-gcps';
const DRAFT_SOURCE = 'le-draft';

/** An empty source payload — layers are declared once and fed data as it arrives. */
const EMPTY_FC: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };

/**
 * ★ `setTerrain` MUST NOT RUN WHILE THE CAMERA IS MOVING. MapLibre 4.7.1 froze the
 * whole map when terrain is (re)enabled during an active easing — upstream issue
 * maplibre-gl-js#6011, reproduced on 4.7.1. Fixed upstream in the 5.x line (now in use — upgraded for the broader terrain freeze/crash fixes), but the deferral is kept: it costs nothing and guards against regressions. A user who opens 3D and
 * immediately wheel-zooms lands in that window: the style's 'load' fires mid-easing,
 * the load handler enables terrain, and the map locks up ("scroll to zoom and it
 * freezes"). Deferring to 'moveend' sidesteps the bug; the listener dies with the
 * instance, so a deferred call can never land on a removed map.
 */
function setTerrainSafely(instance: MapLibreMap, apply: (map: MapLibreMap) => void): void {
  if (instance.isMoving()) {
    instance.once('moveend', () => setTerrainSafely(instance, apply));
    return;
  }
  apply(instance);
}

/** Committed GCPs → the geojson source payload. Pure; used at load AND on updates. */
function toGcpFc(gcps: readonly Terrain3DGcp[]): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: gcps.map((g) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [g.lon, g.lat] },
      properties: { id: g.id, label: g.code ?? '', color: g.color },
    })),
  };
}

function toDraftFc(draft: LatLon | null): GeoJSON.FeatureCollection {
  return draft === null
    ? EMPTY_FC
    : {
        type: 'FeatureCollection',
        features: [
          {
            type: 'Feature',
            geometry: { type: 'Point', coordinates: [draft.lon, draft.lat] },
            properties: {},
          },
        ],
      };
}

// ★ DEFAULT_EXAGGERATION lives in `./terrainDefaults` and is deliberately NOT
//   re-exported from here: this module is behind React.lazy, and a re-export would
//   let a caller pull maplibre-gl back into the eager chunk by importing a constant.

/**
 * A GCP as this pane needs it — position, label, and its already-resolved band colour.
 *
 * ★ The colour is passed IN rather than computed here. `MapPanel` derives it with the
 *   same `confidenceColor`/`gcpConfidenceBand` helpers the 2D markers use, so the two
 *   panes cannot drift into disagreeing about what band a point is in.
 */
export interface Terrain3DGcp {
  id: string;
  lat: number;
  lon: number;
  code: string | null;
  color: string;
}

export interface Terrain3DMapProps {
  /** The project whose DEM supplies the terrain when it has one. */
  projectId: Uuid | null;
  /**
   * ★ Whether the project has its OWN DEM attached. True → terrain is the survey
   * surface GCPs sample Z from. False (or no project) → the global AWS/Mapzen
   * terrarium fallback (~30 m; visualisation, not survey) so the pane shows real
   * relief instead of the flat plane it used to render.
   */
  hasProjectDem?: boolean;
  /** Imagery provider id, draped over the terrain — the same tiles the 2D pane uses. */
  providerId: string;
  basemap: string;
  /** Initial camera. Shared with the 2D pane so switching views does not move the map. */
  initialView: MapViewState;
  /** Vertical exaggeration; 1.0 is true scale. */
  exaggeration?: number;
  maxZoom: number;
  /**
   * The provider's tile edge in pixels (`capabilities.tile_size_px`). MapLibre picks
   * the tile zoom from this: declaring 256 for a 512-px provider requests one zoom
   * level deeper than needed — 4× the tile count, which is 4× the bill on per-tile
   * providers (Mapbox). Geography is unaffected either way.
   */
  tileSizePx?: number;
  /** A click on the terrain, EPSG:4326 — feeds the same correspondence flow as 2D. */
  onMapClick?: (at: LatLon) => void;
  /** Pointer position, EPSG:4326; null when it leaves the canvas. */
  onCursorMove?: (at: LatLon | null) => void;
  /** Camera changes, so the 2D pane can follow. */
  onViewChange?: (view: MapViewState) => void;

  /** Committed GCPs, drawn on the terrain surface. */
  gcps?: readonly Terrain3DGcp[];
  /** The open correspondence's map half, if one is placed — the draft marker. */
  draft?: LatLon | null;
  /** Selecting a marker, so the table and photo panes follow as they do in 2D. */
  onSelectGcp?: (id: string) => void;
  /**
   * MEASURED ground metres per screen pixel under the pointer.
   *
   * ★ Reported because the 2D formula cannot be reused here — see
   * `tileMath.accuracyFromMetresPerPixel`. Under pitch a pixel near the horizon covers
   * far more ground than one at screen centre, so the honest figure has to be measured
   * from the live camera rather than derived from latitude and zoom.
   */
  onGroundScale?: (metresPerPixel: number | null) => void;
}

export function Terrain3DMap({
  projectId,
  providerId,
  basemap,
  initialView,
  exaggeration = DEFAULT_EXAGGERATION,
  maxZoom,
  tileSizePx = 256,
  onMapClick,
  onCursorMove,
  onViewChange,
  gcps = [],
  draft = null,
  onSelectGcp,
  onGroundScale,
  hasProjectDem = false,
}: Terrain3DMapProps): JSX.Element {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<MapLibreMap | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  // ★ Handlers live in a ref so the map is built ONCE. Putting them in the effect's
  //   dependency list would tear down and rebuild the WebGL context — and every tile it
  //   has fetched — on each parent render.
  const handlers = useRef({ onMapClick, onCursorMove, onViewChange, onSelectGcp, onGroundScale });
  handlers.current = { onMapClick, onCursorMove, onViewChange, onSelectGcp, onGroundScale };

  // ★ Exaggeration is read through a ref inside the async `load` handler, not captured.
  //   `load` can fire well after mount; a captured value would apply whatever the slider
  //   read at construction time and silently ignore any change made while tiles loaded.
  //   Keeping it out of the build effect's deps is also what stops the WebGL context
  //   being destroyed and rebuilt every time the slider moves.
  const exaggerationRef = useRef(exaggeration);
  // ★ Read inside the once-only 'load' handler, so it must be a ref — the map is
  //   deliberately built a single time and closures see mount-time props.
  const terrainModeRef = useRef(hasProjectDem);
  terrainModeRef.current = hasProjectDem;
  exaggerationRef.current = exaggeration;

  // ★ Captured once. The camera is uncontrolled after mount, for the reason
  //   `SatelliteMap` documents: a controlled camera fights the user's own gestures.
  const seed = useRef(initialView).current;

  // ★ THE 3D PANE FOLLOWS THE STORE TOO. It used to read the view once at mount, so a
  //   GCP row click, Go-to-location or the EXIF button moved the 2D map and left this
  //   one where it was. Same rule as `MapViewSync`: each store `seq` is applied once,
  //   and a change the map itself produced ('user'/'map') is never echoed back.
  const storeSeq = useMapStore((s) => s.seq);
  const storeOrigin = useMapStore((s) => s.lastOrigin);
  const storeView = useMapStore((s) => s.view);
  const appliedSeq = useRef(storeSeq);
  useEffect(() => {
    if (storeSeq === appliedSeq.current) return;
    appliedSeq.current = storeSeq;
    if (storeOrigin === 'user' || storeOrigin === 'map') return;
    const instance = map.current;
    if (instance === null) return;
    const { lat, lon } = storeView.center;
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || !Number.isFinite(storeView.zoom)) return;
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
    instance.flyTo({ center: [lon, lat], zoom: storeView.zoom, duration: reduce ? 0 : 600 });
  }, [storeSeq, storeOrigin, storeView]);

  // ★ The CURRENT data, readable from the once-only 'load' closure. Without this the
  //   sources were seeded empty and the setData effects had already run (and bailed)
  //   before the style existed — committed GCPs vanished every time 3D was entered.
  const dataRef = useRef({ gcps, draft });
  dataRef.current = { gcps, draft };

  // ★ Where the camera WAS when a rebuild (basemap/provider change) tore the map
  //   down — so the new map resumes there instead of jumping back to the mount-time
  //   seed with pitch reset.
  const resumeViewRef = useRef<{
    center: [number, number];
    zoom: number;
    pitch: number;
    bearing: number;
  } | null>(null);

  useEffect(() => {
    if (container.current === null) return undefined;

    let instance: MapLibreMap;
    try {
      instance = new maplibregl.Map({
        container: container.current,
        // ★ Inline style, no network fetch. See the header note.
        style: {
          version: 8,
          sources: {
            [IMAGERY_SOURCE]: {
              type: 'raster',
              tiles: [
                `${window.location.origin}${API_BASE_URL}/imagery/tiles/${providerId}/{z}/{x}/{y}?kind=${encodeURIComponent(basemap)}`,
              ],
              tileSize: tileSizePx,
              maxzoom: maxZoom,
              // Attribution is a ToS obligation rendered by `ProviderAttribution`, always
              // visible and non-dismissible — never MapLibre's dismissible control.
              attribution: '',
            },
          },
          layers: [
            // A neutral base so a missing tile reads as "not loaded", not as terrain.
            {
              id: 'background',
              type: 'background',
              paint: { 'background-color': TERRAIN_3D.background },
            },
            { id: 'imagery', type: 'raster', source: IMAGERY_SOURCE },
          ],
        },
        center: resumeViewRef.current?.center ?? [seed.center.lon, seed.center.lat],
        zoom: resumeViewRef.current?.zoom ?? seed.zoom,
        pitch: resumeViewRef.current?.pitch ?? 60,
        bearing: resumeViewRef.current?.bearing ?? 0,
        maxZoom,
        attributionControl: false,
      });
    } catch (error) {
      // ★ WebGL can be absent (software rendering, a locked-down machine, some VMs).
      //   That is a real field condition and must degrade to a message, not a blank pane.
      setFailed(error instanceof Error ? error.message : 'WebGL is unavailable in this browser.');
      return undefined;
    }

    map.current = instance;
    // ★ 'top-LEFT', matching the 2D pane — NOT top-right.
    //   `MapPanel`'s chrome layer is a full-bleed overlay at zIndex 1000 whose top row is
    //   deliberately right-aligned "so Leaflet's own zoom control keeps the top-left
    //   corner". That cluster has pointerEvents:'auto', so a NavigationControl placed
    //   top-right lands UNDERNEATH it: the zoom buttons are both hidden and unclickable,
    //   which reads to the user as "3D will not zoom". The two panes must put their zoom
    //   control in the same corner, and the corner the chrome leaves free is the left one.
    instance.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-left');

    instance.on('load', () => {
      // ★ Added after load: a terrain source referenced before the style is ready throws.
      //   Project DEM when one is attached; the global terrarium fallback otherwise —
      //   a project without a DEM used to render a FLAT plane here.
      instance.addSource(TERRAIN_SOURCE, {
        type: 'raster-dem',
        tiles: [
          `${window.location.origin}${API_BASE_URL}${terrainTileTemplate('', projectId, terrainModeRef.current)}`,
        ],
        tileSize: 256,
        // ★ Terrarium, matching `gis.dem.terrain` AND the AWS tileset. Declaring the
        //   wrong encoding decodes every height into a different number and renders
        //   plausible nonsense.
        encoding: 'terrarium',
        maxzoom: GLOBAL_TERRAIN_MAX_ZOOM,
        attribution: '',
      });
      setTerrainSafely(instance, (m) =>
        m.setTerrain({ source: TERRAIN_SOURCE, exaggeration: exaggerationRef.current }),
      );
    });

    // ★ Marker layers are added on `styledata`, not `load`: they must exist even when
    //   projectId is null (no DEM ⇒ no terrain source, but GCPs still have coordinates
    //   and must still be visible). Guarded so repeated style events do not re-add.
    instance.on('load', () => {
      if (instance.getSource(GCP_SOURCE) === undefined) {
        instance.addSource(GCP_SOURCE, { type: 'geojson', data: EMPTY_FC });
        instance.addLayer({
          id: 'gcp-halo',
          type: 'circle',
          source: GCP_SOURCE,
          paint: {
            'circle-radius': 9,
            'circle-color': TERRAIN_3D.markerHalo,
            'circle-opacity': 0.35,
          },
        });
        instance.addLayer({
          id: 'gcp-dot',
          type: 'circle',
          source: GCP_SOURCE,
          paint: {
            // Colour comes from the feature, computed by the same confidence helpers the
            // 2D markers use — the two panes must never disagree about a point's band.
            'circle-radius': 6,
            'circle-color': ['get', 'color'],
            'circle-stroke-width': 2,
            'circle-stroke-color': TERRAIN_3D.markerStroke,
          },
        });
        // ★ NO TEXT LABELS IN 3D, deliberately. Any `text-field` requires the style
        //   to name a `glyphs` server — MapLibre validates this and refuses the layer
        //   (it never rendered; it just errored on every build). This style is
        //   deliberately self-contained (no external fetches, works offline), and
        //   shipping a glyph server for point codes is not worth it: the dots carry
        //   the confidence colour, and clicking one selects it in the table where its
        //   code and name are readable. If labels are ever wanted here, the honest
        //   path is serving glyph PBFs from our own backend, not a remote URL.
      }

      if (instance.getSource(DRAFT_SOURCE) === undefined) {
        instance.addSource(DRAFT_SOURCE, { type: 'geojson', data: EMPTY_FC });
        instance.addLayer({
          id: 'draft-point',
          type: 'circle',
          source: DRAFT_SOURCE,
          paint: {
            // Deliberately unlike a committed GCP: this point is NOT saved yet, and a
            // draft that looked identical to a committed row would be read as one.
            'circle-radius': 8,
            'circle-color': TERRAIN_3D.draftFill,
            'circle-stroke-width': 3,
            'circle-stroke-color': TERRAIN_3D.draftStroke,
          },
        });
      }

      // ★ Apply the data that exists RIGHT NOW — the props arrived before the style.
      (instance.getSource(GCP_SOURCE) as maplibregl.GeoJSONSource | undefined)?.setData(
        toGcpFc(dataRef.current.gcps ?? []),
      );
      (instance.getSource(DRAFT_SOURCE) as maplibregl.GeoJSONSource | undefined)?.setData(
        toDraftFc(dataRef.current.draft ?? null),
      );

      instance.on('click', 'gcp-dot', (e) => {
        const id = e.features?.[0]?.properties?.id;
        if (typeof id === 'string') handlers.current.onSelectGcp?.(id);
      });
      instance.on('mouseenter', 'gcp-dot', () => {
        instance.getCanvas().style.cursor = 'pointer';
      });
      instance.on('mouseleave', 'gcp-dot', () => {
        instance.getCanvas().style.cursor = '';
      });
    });

    // ★ A 404 from the terrain source is EXPECTED — it is how "no DEM here" is spelled,
    //   and MapLibre renders flat ground for that tile. Swallowing only that case keeps
    //   the console usable while still surfacing real style/source failures.
    instance.on('error', (event) => {
      const status = (event.error as { status?: number } | undefined)?.status;
      if (status === 404) return;
      // eslint-disable-next-line no-console
      console.warn('[terrain3d]', event.error);
    });

    // ★ WEBGL CONTEXT LOSS IS THE ONE FAILURE THAT LOOKS LIKE A CRASH.
    //   The GPU driver can reset, or the browser can reclaim a context when too many
    //   exist — toggling 2D/3D repeatedly is exactly how a user provokes that. MapLibre
    //   does not throw when it happens; it simply stops painting, so the pane goes black
    //   and freezes with no error anywhere. Since `new maplibregl.Map` already succeeded,
    //   the constructor's try/catch cannot help: this arrives as an EVENT, later.
    //   Surfacing it through the same `failed` state turns a silent black rectangle into
    //   a message that says what happened and what to do.
    const canvas = instance.getCanvas();
    const onContextLost = (event: Event): void => {
      // Prevent the default so the browser will attempt a restore at all.
      event.preventDefault();
      setFailed(
        'The 3D view lost its graphics context (the GPU driver reset, or too many 3D ' +
          'views were open). Switch back to 2D and re-open 3D to rebuild it.',
      );
    };
    const onContextRestored = (): void => setFailed(null);
    canvas.addEventListener('webglcontextlost', onContextLost);
    canvas.addEventListener('webglcontextrestored', onContextRestored);

    instance.on('click', (e) => {
      // ★ A click on a GCP dot is a SELECTION, not a placement: MapLibre fires both
      //   the layer-scoped and the map-level handler, and with a correspondence open
      //   the map-level one would silently relocate the draft onto the clicked GCP.
      //   (2D never had this — Leaflet markers do not bubble clicks to the map.)
      if (
        instance.getLayer('gcp-dot') !== undefined &&
        instance.queryRenderedFeatures(e.point, { layers: ['gcp-dot'] }).length > 0
      ) {
        return;
      }
      handlers.current.onMapClick?.({ lat: e.lngLat.lat, lon: e.lngLat.lng });
    });
    // ★★ THE CURSOR READOUTS MUST NOT RUN PER MOUSEMOVE EVENT. THIS IS WHY 3D WOULD NOT PAN.
    //
    //    `groundMetresPerPixel` calls `map.unproject()` twice. With terrain enabled that is
    //    NOT the cheap inverse-matrix multiply it is on a flat map: MapLibre must raycast
    //    the terrain mesh, which it does by reading back the coords framebuffer with
    //    `gl.readPixels`. A readback stalls the GPU pipeline — it is among the most
    //    expensive calls in WebGL.
    //
    //    `mousemove` fires at pointer-polling rate (125-1000 Hz on a gaming mouse). Two
    //    readbacks plus two React state updates per event, while MapLibre is simultaneously
    //    trying to re-render the terrain for the drag, starves the drag of frames entirely:
    //    the map appears frozen under a "grab" cursor. 2D never showed this because Leaflet
    //    has no terrain and no readback.
    //
    //    Two guards, both necessary:
    //      1. SKIP WHILE THE CAMERA IS MOVING. Mid-drag the readouts are meaningless anyway —
    //         they answer "what is under my cursor", and during a pan the user is moving the
    //         map, not inspecting a spot. This is what makes dragging smooth.
    //      2. COALESCE TO ONE FRAME. Even plain hovering must not exceed one readback per
    //         frame, or a fast mouse over static terrain does the same damage.
    let camMoving = false;
    let pending: { lngLat: { lat: number; lng: number }; point: maplibregl.Point } | null = null;
    let frame = 0;

    const flush = (): void => {
      frame = 0;
      const ev = pending;
      pending = null;
      if (ev === null || camMoving) return;
      handlers.current.onCursorMove?.({ lat: ev.lngLat.lat, lon: ev.lngLat.lng });
      handlers.current.onGroundScale?.(groundMetresPerPixel(instance, ev.point));
    };

    instance.on('movestart', () => {
      camMoving = true;
      pending = null;
      // ★ Drop the readouts rather than freezing them. A "Z 1361.6 m" chip left on screen
      //   while the map slides underneath is stating a fact about a place the cursor is no
      //   longer over — the same reason `mouseout` reports null instead of going quiet.
      handlers.current.onCursorMove?.(null);
      handlers.current.onGroundScale?.(null);
    });
    instance.on('moveend', () => {
      camMoving = false;
    });

    instance.on('mousemove', (e) => {
      if (camMoving) return;
      pending = { lngLat: e.lngLat, point: e.point };
      if (frame === 0) frame = requestAnimationFrame(flush);
    });
    instance.on('mouseout', () => {
      pending = null;
      if (frame !== 0) {
        cancelAnimationFrame(frame);
        frame = 0;
      }
      handlers.current.onCursorMove?.(null);
      handlers.current.onGroundScale?.(null);
    });
    instance.on('moveend', () => {
      const c = instance.getCenter();
      handlers.current.onViewChange?.({
        center: { lat: c.lat, lon: c.lng },
        zoom: instance.getZoom(),
        // ★ null, not the MapLibre bounds: `bounds` in this app means "fit to THIS box",
        //   and reporting the camera's current extent every time it settles would make
        //   the 2D pane re-fit itself to wherever 3D happened to be looking.
        bounds: null,
      });
    });

    return () => {
      if (frame !== 0) cancelAnimationFrame(frame);
      canvas.removeEventListener('webglcontextlost', onContextLost);
      canvas.removeEventListener('webglcontextrestored', onContextRestored);
      // ★ Remember where the camera is: a basemap/provider change rebuilds the map,
      //   and the rebuild must resume HERE, not at the mount-time seed.
      const c = instance.getCenter();
      resumeViewRef.current = {
        center: [c.lng, c.lat],
        zoom: instance.getZoom(),
        pitch: instance.getPitch(),
        bearing: instance.getBearing(),
      };
      instance.remove();
      map.current = null;
    };
    // Rebuild only on the things that define the map itself, never on handler identity.
  }, [basemap, maxZoom, projectId, providerId, seed, tileSizePx]);

  // ★ GCPs flow in through `setData`, never by re-adding the layer. Re-adding would
  //   drop the click handlers bound to it and reset paint state on every query refetch.
  // ★ Both effects RETRY on 'idle' when the style is mid-load instead of silently
  //   dropping the update — `isStyleLoaded()` is routinely false while any tile is
  //   in flight, and a dropped update never came back (the props' identity is stable
  //   across refetches). The idle callback re-reads `dataRef`, so it always applies
  //   the LATEST data, never the closure's.
  useEffect(() => {
    const instance = map.current;
    if (instance === null) return;
    const apply = (): void => {
      const source = instance.getSource(GCP_SOURCE) as maplibregl.GeoJSONSource | undefined;
      source?.setData(toGcpFc(dataRef.current.gcps ?? []));
    };
    if (instance.isStyleLoaded() && instance.getSource(GCP_SOURCE) !== undefined) apply();
    else instance.once('idle', apply);
  }, [gcps]);

  useEffect(() => {
    const instance = map.current;
    if (instance === null) return;
    const apply = (): void => {
      const source = instance.getSource(DRAFT_SOURCE) as maplibregl.GeoJSONSource | undefined;
      source?.setData(toDraftFc(dataRef.current.draft ?? null));
    };
    if (instance.isStyleLoaded() && instance.getSource(DRAFT_SOURCE) !== undefined) apply();
    else instance.once('idle', apply);
  }, [draft]);

  // ★ The DEM can be attached/detached while the 3D pane is open (workspace setup is a
  //   dialog over it). Swap the terrain source in place rather than rebuilding the map:
  //   clear terrain -> remove source -> re-add with the other template.
  useEffect(() => {
    const instance = map.current;
    if (instance === null) return;
    const swap = (): void => {
      const wanted = `${window.location.origin}${API_BASE_URL}${terrainTileTemplate('', projectId, terrainModeRef.current)}`;
      const existing = instance.getSource(TERRAIN_SOURCE) as { tiles?: string[] } | undefined;
      if (existing === undefined || existing.tiles?.[0] === wanted) return;
      setTerrainSafely(instance, (m) => {
        m.setTerrain(null);
        m.removeSource(TERRAIN_SOURCE);
        m.addSource(TERRAIN_SOURCE, {
          type: 'raster-dem',
          tiles: [wanted],
          tileSize: 256,
          encoding: 'terrarium',
          maxzoom: GLOBAL_TERRAIN_MAX_ZOOM,
          attribution: '',
        });
        m.setTerrain({ source: TERRAIN_SOURCE, exaggeration: exaggerationRef.current });
      });
    };
    // ★ `isStyleLoaded()` is false whenever tiles are in flight; a DEM attach that
    //   landed in that window used to be dropped forever, leaving the surface label
    //   describing a terrain the map was not showing. Retry on 'idle' — the swap
    //   re-reads the ref, no-ops when already right, so a stale retry is harmless.
    if (instance.isStyleLoaded()) swap();
    else instance.once('idle', swap);
  }, [hasProjectDem, projectId]);

  // Exaggeration is a live property — changing it must not rebuild the context.
  useEffect(() => {
    const instance = map.current;
    // ★ No projectId guard: the global fallback terrain is just as exaggeratable —
    //   the old guard left the slider dead on project-less surfaces.
    if (instance === null || !instance.isStyleLoaded()) return;
    if (instance.getSource(TERRAIN_SOURCE) !== undefined) {
      setTerrainSafely(instance, (m) =>
        m.setTerrain({ source: TERRAIN_SOURCE, exaggeration: exaggerationRef.current }),
      );
    }
  }, [exaggeration]);

  const resize = useCallback(() => map.current?.resize(), []);
  useEffect(() => {
    const element = container.current;
    if (element === null) return undefined;
    // Same reason `SatelliteMap` observes its parent: a grid cell can resize without the
    // 100%-sized child's own box changing, and the canvas keeps its mount-time size.
    const observer = new ResizeObserver(resize);
    observer.observe(element);
    if (element.parentElement) observer.observe(element.parentElement);
    return () => observer.disconnect();
  }, [resize]);

  // ★ The container div is ALWAYS mounted, and the failure message is an OVERLAY.
  //   Rendering the error INSTEAD of the container used to detach the live map: after
  //   a WebGL context loss the browser would restore the context, `failed` cleared —
  //   and the fresh empty container had no map attached, leaving a permanently blank
  //   pane. With the container stable, a restored context simply resumes painting.
  return (
    // ★ MapLibre island — see LtrIsland: the canvas geometry stays LTR under the
    //   mirrored Arabic chrome.
    <LtrIsland>
      <div style={{ position: 'relative', width: '100%', height: '100%' }}>
        <div ref={container} style={{ width: '100%', height: '100%' }} />
        {failed !== null && (
          <div
            style={{
              position: 'absolute',
              inset: 0,
              display: 'grid',
              placeItems: 'center',
              padding: 24,
              textAlign: 'center',
              font: '14px system-ui',
              background: 'rgba(11,11,12,0.92)',
              color: ON_MEDIA,
              zIndex: 2,
            }}
          >
            <span>
              The 3D view hit a graphics problem ({failed}). If it does not recover by itself,
              switch back to 2D and re-open 3D — the 2D map is unaffected.
            </span>
          </div>
        )}
        {/* ★ WHICH SURFACE AM I LOOKING AT — always answered. A project DEM is the
          survey surface; the global fallback is ~30 m visualisation. Conflating them
          is exactly the kind of quiet substitution this product refuses elsewhere,
          and the global source's licence asks for its credit. */}
        <div
          style={{
            position: 'absolute',
            left: 8,
            bottom: 6,
            padding: '2px 8px',
            borderRadius: 4,
            background: 'rgba(0,0,0,0.55)',
            color: ON_MEDIA,
            font: '11px system-ui',
            pointerEvents: 'none',
          }}
        >
          {hasProjectDem
            ? 'Terrain: project DEM (survey surface)'
            : `${GLOBAL_TERRAIN_ATTRIBUTION} — visualisation only`}
        </div>
      </div>
    </LtrIsland>
  );
}
