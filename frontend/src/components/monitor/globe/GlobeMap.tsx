/**
 * `monitor/globe/GlobeMap.tsx` — the rotating Earth, one marker per camera.
 *
 * ★ MARKERS ARE GPU CIRCLES, NOT DOM. One GeoJSON source, clustered above eight in
 *   view, and three circle layers — halo, dot, cluster — so a registry of hundreds
 *   costs the globe nothing. What React draws is the ONE hover tooltip, positioned
 *   with `map.project`.
 *
 * ★ THE GLOBE OPENS NO SOCKETS. A marker's colour is the registry's last-known
 *   status; the hover probe (GlobePage) updates it. Nothing here touches a camera.
 *
 * ★ IDLE AUTO-ROTATE stops PERMANENTLY on the first interaction — a globe that
 *   resumes spinning under a pointer that paused is a globe fighting its user —
 *   and never starts at all under `prefers-reduced-motion`, where `flyTo` is also a
 *   jump.
 */

import { useEffect, useRef, useState, type JSX } from 'react';
import maplibregl, { type Map as MapLibreMap, type MapMouseEvent } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';

import { API_BASE_URL } from '../../../api/client';
import { LtrIsland } from '../../common/LtrIsland';
import type { ProviderInfo } from '../../../types/geo';
import type { CameraStatus, RegisteredCamera } from '../../../store/cameraRegistryStore';
import {
  camerasToFeatureCollection,
  wedgesToFeatureCollection,
} from '../../../lib/monitor/geojson';
import { t } from '../../../i18n';
import {
  CACHE_SOURCE,
  CAMERA_SOURCE,
  LAYER_CAMERAS,
  LAYER_CLUSTERS,
  PLACES_SOURCES,
  PLACE_LAYERS,
  WEDGE_SOURCE,
  buildGlobeStyle,
} from './globeStyle';
import { useOfflineCacheStore } from '../../../store/offlineCacheStore';
import type { LatLon } from '../../../types/geo';

export interface GlobeMapProps {
  cameras: readonly RegisteredCamera[];
  statuses: Readonly<Record<string, CameraStatus>>;
  /** Null = no imagery (providers unreadable); the globe still renders. */
  provider: ProviderInfo | null;
  /** A hover on a marker (and the leave). Drives the probe. */
  onHover: (id: string | null) => void;
  /** A click: after the intentional reveal (flyTo), navigate. */
  onOpen: (id: string) => void;
  /** Fly to this camera; bumped by the list panel. */
  flyTo: { id: string; seq: number } | null;
  /** ★ Fly to a searched place or typed coordinates (2026-09-10); bumped per search. */
  goTo?: { lat: number; lon: number; zoom: number; seq: number } | null;
  /** Borders and place names — the HUD's toggle. */
  placesVisible?: boolean;
  /** The UI language: Arabic country names when 'ar'. */
  lang?: string;
}

/** The offline-cache area as drawn: the polygon (or the open line) and its vertices. */
function cacheAreaFeatures(points: readonly LatLon[], drawing: boolean): GeoJSON.FeatureCollection {
  const ring = points.map((p) => [p.lon, p.lat] as [number, number]);
  const features: GeoJSON.Feature[] = points.map((p) => ({
    type: 'Feature',
    properties: { drawing },
    geometry: { type: 'Point', coordinates: [p.lon, p.lat] },
  }));
  if (ring.length >= 3) {
    features.push({
      type: 'Feature',
      properties: { drawing },
      geometry: { type: 'Polygon', coordinates: [[...ring, ring[0]]] },
    });
  } else if (ring.length === 2) {
    features.push({ type: 'Feature', properties: { drawing }, geometry: { type: 'LineString', coordinates: ring } });
  }
  return { type: 'FeatureCollection', features };
}

/** Country label points from the countries file: where a cartographer put them. */
function countryLabelPoints(fc: GeoJSON.FeatureCollection): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: fc.features
      .filter((f) => typeof f.properties?.lx === 'number' && typeof f.properties?.ly === 'number')
      .map((f) => ({
        type: 'Feature',
        properties: {
          name: f.properties?.name,
          name_ar: f.properties?.name_ar,
          pop: f.properties?.pop ?? 0,
        },
        geometry: { type: 'Point', coordinates: [f.properties?.lx as number, f.properties?.ly as number] },
      })),
  };
}

/** The brief's zoom: the whole Earth with room to breathe. */
const HOME_ZOOM = 1.2;
const REVEAL_ZOOM = 11;

/** `[lon, lat]` to open on — the cameras' centroid, else a default. */
function homeCenter(cameras: readonly RegisteredCamera[]): [number, number] {
  if (cameras.length === 0) return [20, 30];
  const lon = cameras.reduce((a, c) => a + c.lon, 0) / cameras.length;
  const lat = cameras.reduce((a, c) => a + c.lat, 0) / cameras.length;
  return [lon, lat];
}

function reducedMotion(): boolean {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
}

function ageOf(at: number): string {
  if (at === 0) return t('never opened');
  const s = Math.max(0, Math.round((Date.now() - at) / 1000));
  if (s < 60) return `${s} s ${t('ago')}`;
  if (s < 3600) return `${Math.round(s / 60)} min ${t('ago')}`;
  return `${Math.round(s / 3600)} h ${t('ago')}`;
}

export function GlobeMap({
  cameras,
  statuses,
  provider,
  onHover,
  onOpen,
  flyTo,
  goTo = null,
  placesVisible = true,
  lang = 'en',
}: GlobeMapProps): JSX.Element {
  const container = useRef<HTMLDivElement | null>(null);
  const map = useRef<MapLibreMap | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [tip, setTip] = useState<{ id: string; x: number; y: number } | null>(null);
  // The latest data, readable from the once-only load closure.
  const dataRef = useRef({ cameras, statuses });
  dataRef.current = { cameras, statuses };
  const callbacks = useRef({ onHover, onOpen });
  callbacks.current = { onHover, onOpen };
  /** Stops the idle rotation — a search or a fly-to must not fight the spin. */
  const spinStop = useRef<() => void>(() => undefined);
  const drawing = useOfflineCacheStore((s) => s.drawing);
  const cachePoints = useOfflineCacheStore((s) => s.points);

  const caps = provider?.capabilities ?? null;

  // ── the map ─────────────────────────────────────────────────────────────────
  useEffect(() => {
    if (container.current === null) return undefined;
    let instance: MapLibreMap;
    try {
      instance = new maplibregl.Map({
        container: container.current,
        style: buildGlobeStyle({
          apiBaseUrl: API_BASE_URL,
          provider:
            provider === null || caps === null
              ? null
              : { id: provider.name, tileSizePx: caps.tile_size_px, maxZoom: caps.max_zoom },
          kind: 'satellite',
          lang,
          placesVisible,
        }),
        // Open on the cameras, when there are any: their centroid is the operator's
        // theatre; an empty registry opens on the Mediterranean, where this app lives.
        center: homeCenter(dataRef.current.cameras),
        zoom: HOME_ZOOM,
        maxZoom: caps?.max_zoom ?? 18,
        attributionControl: false,
      });
    } catch (error) {
      // ★ WebGL can be absent (software rendering, a locked-down machine). A field
      //   condition — degrade to a sentence, not a blank page.
      setFailed(error instanceof Error ? error.message : 'WebGL is unavailable in this browser.');
      return undefined;
    }
    map.current = instance;
    instance.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right');

    const feed = (): void => {
      const { cameras: cs, statuses: st } = dataRef.current;
      const src = instance.getSource(CAMERA_SOURCE) as maplibregl.GeoJSONSource | undefined;
      src?.setData(camerasToFeatureCollection(cs, (id) => st[id]?.state ?? 'unknown'));
      const wedges = instance.getSource(WEDGE_SOURCE) as maplibregl.GeoJSONSource | undefined;
      wedges?.setData(wedgesToFeatureCollection(cs));
    };
    instance.on('load', feed);
    // ★ The country NAMES sit on Natural Earth's label points, read once from the
    //   same file the borders come from (the browser serves it from cache).
    const labelCountries = (): void => {
      fetch(`${window.location.origin}/geo/countries.geojson`)
        .then((r) => (r.ok ? (r.json() as Promise<GeoJSON.FeatureCollection>) : Promise.reject(new Error(String(r.status)))))
        .then((fc) => {
          const src = instance.getSource(PLACES_SOURCES.countryLabels) as maplibregl.GeoJSONSource | undefined;
          src?.setData(countryLabelPoints(fc));
        })
        .catch(() => undefined); // no names is a degraded globe, not a broken one
    };
    instance.on('load', labelCountries);

    // ── hover: one tooltip, one probe ──────────────────────────────────────────
    let hovered: string | null = null;
    const onMove = (e: MapMouseEvent): void => {
      const hits = instance.queryRenderedFeatures(e.point, { layers: [LAYER_CAMERAS] });
      const id = hits.length > 0 ? String(hits[0].properties?.id ?? '') : '';
      if (id !== '' && id !== hovered) {
        hovered = id;
        instance.getCanvas().style.cursor = 'pointer';
        callbacks.current.onHover(id);
      } else if (id === '' && hovered !== null) {
        hovered = null;
        instance.getCanvas().style.cursor = '';
        callbacks.current.onHover(null);
      }
      setTip(id === '' ? null : { id, x: e.point.x, y: e.point.y });
    };
    const onLeave = (): void => {
      if (hovered !== null) {
        hovered = null;
        callbacks.current.onHover(null);
      }
      setTip(null);
    };
    instance.on('mousemove', onMove);
    instance.getCanvas().addEventListener('mouseleave', onLeave);

    // ── click: reveal, then open ───────────────────────────────────────────────
    const onClick = (e: MapMouseEvent): void => {
      // ★ DRAWING THE OFFLINE-CACHE AREA (moved here from the dashboard map,
      //   2026-09-10): while the panel is in draw mode every click is a vertex —
      //   nothing underneath is opened.
      const cache = useOfflineCacheStore.getState();
      if (cache.drawing) {
        cache.addPoint({ lat: e.lngLat.lat, lon: e.lngLat.lng });
        return;
      }
      const hits = instance.queryRenderedFeatures(e.point, { layers: [LAYER_CAMERAS] });
      if (hits.length > 0) {
        const id = String(hits[0].properties?.id ?? '');
        const geom = hits[0].geometry;
        if (id !== '' && geom.type === 'Point') {
          const [lon, lat] = geom.coordinates as [number, number];
          const duration = reducedMotion() ? 0 : 900;
          instance.flyTo({ center: [lon, lat], zoom: REVEAL_ZOOM, duration });
          if (duration === 0) callbacks.current.onOpen(id);
          else instance.once('moveend', () => callbacks.current.onOpen(id));
        }
        return;
      }
      const clusters = instance.queryRenderedFeatures(e.point, { layers: [LAYER_CLUSTERS] });
      if (clusters.length > 0) {
        const geom = clusters[0].geometry;
        if (geom.type === 'Point') {
          instance.easeTo({
            center: geom.coordinates as [number, number],
            zoom: instance.getZoom() + 2,
            duration: reducedMotion() ? 0 : 500,
          });
        }
      }
    };
    instance.on('click', onClick);

    // ── idle rotation ──────────────────────────────────────────────────────────
    let raf: number | null = null;
    let rotating = !reducedMotion();
    const stop = (): void => {
      rotating = false;
      if (raf !== null) window.cancelAnimationFrame(raf);
      raf = null;
    };
    const spin = (): void => {
      if (!rotating) return;
      const c = instance.getCenter();
      instance.setCenter([c.lng + 0.03, c.lat]);
      raf = window.requestAnimationFrame(spin);
    };
    if (rotating) raf = window.requestAnimationFrame(spin);
    spinStop.current = stop;
    const stoppers = ['mousedown', 'wheel', 'touchstart', 'keydown'] as const;
    stoppers.forEach((ev) => instance.getCanvas().addEventListener(ev, stop, { passive: true }));

    return () => {
      stop();
      stoppers.forEach((ev) => instance.getCanvas().removeEventListener(ev, stop));
      instance.getCanvas().removeEventListener('mouseleave', onLeave);
      instance.remove();
      map.current = null;
    };
    // The provider decides the tiles — a change rebuilds the map, as Terrain3DMap does.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- lang/placesVisible are applied live below
  }, [provider?.name, caps?.tile_size_px, caps?.max_zoom, lang]);

  // ── the offline-cache area, as it is drawn ──────────────────────────────────
  useEffect(() => {
    const instance = map.current;
    if (instance === null) return;
    const apply = (): void => {
      const src = instance.getSource(CACHE_SOURCE) as maplibregl.GeoJSONSource | undefined;
      src?.setData(cacheAreaFeatures(cachePoints, drawing));
      instance.getCanvas().style.cursor = drawing ? 'crosshair' : '';
      if (drawing) instance.doubleClickZoom.disable();
      else instance.doubleClickZoom.enable();
    };
    if (instance.isStyleLoaded()) apply();
    else instance.once('load', apply);
  }, [cachePoints, drawing]);

  // ── places on / off ─────────────────────────────────────────────────────────
  useEffect(() => {
    const instance = map.current;
    if (instance === null) return;
    const apply = (): void => {
      for (const id of PLACE_LAYERS) {
        if (instance.getLayer(id)) instance.setLayoutProperty(id, 'visibility', placesVisible ? 'visible' : 'none');
      }
    };
    if (instance.isStyleLoaded()) apply();
    else instance.once('load', apply);
  }, [placesVisible]);

  // ── fly to a searched place ─────────────────────────────────────────────────
  useEffect(() => {
    const instance = map.current;
    if (instance === null || goTo === null) return;
    spinStop.current();
    instance.flyTo({ center: [goTo.lon, goTo.lat], zoom: goTo.zoom, duration: reducedMotion() ? 0 : 1400 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [goTo?.seq]);

  // ── data updates after load ─────────────────────────────────────────────────
  useEffect(() => {
    const instance = map.current;
    if (instance === null) return;
    const apply = (): void => {
      const src = instance.getSource(CAMERA_SOURCE) as maplibregl.GeoJSONSource | undefined;
      src?.setData(camerasToFeatureCollection(cameras, (id) => statuses[id]?.state ?? 'unknown'));
      const wedges = instance.getSource(WEDGE_SOURCE) as maplibregl.GeoJSONSource | undefined;
      wedges?.setData(wedgesToFeatureCollection(cameras));
    };
    if (instance.isStyleLoaded()) apply();
    else instance.once('load', apply);
  }, [cameras, statuses]);

  // ── fly to a camera from the list ───────────────────────────────────────────
  useEffect(() => {
    const instance = map.current;
    if (instance === null || flyTo === null) return;
    const cam = cameras.find((c) => c.id === flyTo.id);
    if (!cam) return;
    spinStop.current();
    instance.flyTo({ center: [cam.lon, cam.lat], zoom: 8, duration: reducedMotion() ? 0 : 900 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flyTo?.seq]);

  const tipCamera = tip === null ? undefined : cameras.find((c) => c.id === tip.id);
  const tipStatus = tip === null ? undefined : statuses[tip.id];

  return (
    // ★ MapLibre island — the globe's canvas and its cursor-anchored tooltip
    //   (`left: tip.x`) both assume LTR geometry. See LtrIsland.
    <LtrIsland>
      <Box sx={{ position: 'absolute', inset: 0, bgcolor: 'var(--bg-canvas)' }}>
        {/* ★ `width/height: 100%`, not `inset: 0`: MapLibre's stylesheet gives the
          container `position: relative`, which turns an inset box into a 0-px one
          (seen 2026-08-28 — a globe rendering into a 300-px default canvas). */}
        <Box ref={container} data-testid="globe-map" sx={{ width: '100%', height: '100%' }} />
        {failed !== null && (
          <Box sx={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', p: 3 }}>
            <Typography
              variant="body2"
              color="text.secondary"
              sx={{ maxWidth: 420, textAlign: 'center' }}
            >
              {t('The globe needs WebGL, which this browser does not provide.')} {failed}
            </Typography>
          </Box>
        )}
        {tip !== null && tipCamera !== undefined && (
          <Box
            role="tooltip"
            sx={{
              position: 'absolute',
              left: tip.x + 14,
              top: tip.y + 14,
              pointerEvents: 'none',
              px: 1.25,
              py: 0.75,
              borderRadius: 'var(--radius-md, 8px)',
              bgcolor: 'var(--scrim-hud)',
              border: '1px solid var(--hairline)',
              backdropFilter: 'blur(4px)',
              minWidth: 180,
            }}
          >
            <Typography variant="subtitle2" sx={{ lineHeight: 1.2 }}>
              {tipCamera.name}
            </Typography>
            <Typography variant="mono" sx={{ display: 'block', fontSize: 12, direction: 'ltr' }}>
              {tipCamera.lat.toFixed(5)}, {tipCamera.lon.toFixed(5)}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {t(tipStatus?.state ?? 'unknown')} · {ageOf(tipStatus?.at ?? 0)}
            </Typography>
          </Box>
        )}
      </Box>
    </LtrIsland>
  );
}
