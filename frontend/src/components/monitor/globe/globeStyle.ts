/**
 * `monitor/globe/globeStyle.ts` — the globe's inline MapLibre style. NO NETWORK.
 *
 * ★ COPIED FROM `Terrain3DMap`'S PATTERN, for the same reason: `style: 'https://…'`
 *   would fetch a third-party style document and whatever sources, glyphs and
 *   sprites it names. This style is an object whose ONLY source is our own tile
 *   proxy — `GET /api/v1/imagery/tiles/{provider}/{z}/{x}/{y}` — resolved through the
 *   same provider rule every other map uses. No glyphs (so no `symbol` layers with
 *   text: counts and names are HTML, drawn by React), no sprite, no fonts.
 *
 * ★ OFFLINE IS A STATE, NOT AN ERROR. With `LE_IMAGERY_OFFLINE=true` and an empty
 *   cache the proxy answers 204 for every tile; MapLibre draws nothing there and the
 *   background — space — shows through. The globe still renders, the markers still
 *   land, and the only host ever asked is the API.
 */

import type { ExpressionSpecification, StyleSpecification } from 'maplibre-gl';

import { GLOBE } from '../../../theme/paint';

export const GLOBE_IMAGERY_SOURCE = 'le-imagery';
export const CAMERA_SOURCE = 'le-cameras';
export const WEDGE_SOURCE = 'le-wedges';

export const LAYER_CLUSTERS = 'le-camera-clusters';
export const LAYER_CLUSTER_HALO = 'le-camera-cluster-halo';
export const LAYER_CAMERAS = 'le-camera-points';
export const LAYER_CAMERA_HALO = 'le-camera-halo';
export const LAYER_WEDGES = 'le-camera-wedges';

// ── places: borders and names, from the app's own static files (2026-09-10) ──
export const PLACES_SOURCES = {
  countries: 'le-countries',
  countryLabels: 'le-country-labels',
  provinces: 'le-provinces',
  provinceLabels: 'le-province-labels',
  regions: 'le-regions',
  places: 'le-places',
} as const;
export const PLACE_LAYERS = [
  'le-country-borders',
  'le-province-borders',
  'le-continent-labels',
  'le-region-labels',
  'le-country-labels',
  'le-province-labels',
  'le-city-dots',
  'le-city-labels',
] as const;
/** The area being drawn for the offline cache, and its vertices. */
export const CACHE_SOURCE = 'le-cache-area';
export const LAYER_CACHE_FILL = 'le-cache-fill';
export const LAYER_CACHE_LINE = 'le-cache-line';
export const LAYER_CACHE_VERTICES = 'le-cache-vertices';
/** The one font the globe's labels use — glyphs shipped under /glyphs (offline). */
export const GLOBE_FONT = 'Noto Sans Regular';

/** Clusters form above this many markers in view (the brief's "~8"). */
export const CLUSTER_MIN_POINTS = 8;

export interface GlobeStyleInputs {
  apiBaseUrl: string;
  /**
   * ★ NULL = NO IMAGERY. The providers list could not be read (the API is down, or
   *   every provider is banned) — the globe still renders: space, the atmosphere and
   *   the markers. A camera's position does not depend on a basemap.
   */
  provider: { id: string; tileSizePx: number; maxZoom: number } | null;
  /** The provider's imagery kind — `satellite` for every provider this app ships. */
  kind: string;
  /** `ar` shows the Arabic country names Natural Earth carries; anything else, English. */
  lang?: string;
  /** Start with the place layers hidden (the HUD's toggle). */
  placesVisible?: boolean;
}

/** The empty payload the camera sources are declared with; data is fed after load. */
export const EMPTY_FC: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };

/** The country name in the UI's language, falling back to English. */
function countryName(lang: string | undefined): ExpressionSpecification {
  return lang === 'ar'
    ? (['coalesce', ['get', 'name_ar'], ['get', 'name']] as ExpressionSpecification)
    : (['get', 'name'] as ExpressionSpecification);
}

/** A static file of the app's own — same origin, cached by the browser, works offline. */
function geo(name: string): string {
  return `${window.location.origin}/geo/${name}.geojson`;
}

export function buildGlobeStyle(i: GlobeStyleInputs): StyleSpecification {
  const vis = { visibility: (i.placesVisible === false ? 'none' : 'visible') as 'none' | 'visible' };
  const halo = { 'text-halo-color': GLOBE.labelHalo, 'text-halo-width': 1.2 };
  return {
    version: 8,
    // ★ Label glyphs from the app's own static files: no glyph server, no network.
    glyphs: `${window.location.origin}/glyphs/{fontstack}/{range}.pbf`,
    // ★ THE GLOBE. MapLibre ≥5 projects the same raster tiles onto a sphere; nothing
    //   else changes — the tile proxy does not know or care.
    projection: { type: 'globe' },
    // Atmosphere on: a thin glow at the limb, fading as the camera closes in.
    sky: {
      'atmosphere-blend': ['interpolate', ['linear'], ['zoom'], 0, 1, 5, 1, 7, 0],
    },
    sources: {
      ...(i.provider === null
        ? {}
        : {
            [GLOBE_IMAGERY_SOURCE]: {
              type: 'raster' as const,
              tiles: [
                `${window.location.origin}${i.apiBaseUrl}/imagery/tiles/${i.provider.id}/{z}/{x}/{y}?kind=${encodeURIComponent(i.kind)}`,
              ],
              tileSize: i.provider.tileSizePx,
              maxzoom: i.provider.maxZoom,
              // Attribution is a ToS obligation the HUD renders, always visible — never
              // MapLibre's dismissible control.
              attribution: '',
            },
          }),
      // ★ PLACES (owner ask 2026-09-10): countries, provinces, cities, continents
      //   and regions — Natural Earth, public domain, shipped with the app. The
      //   polygons draw the borders; the label points are separate files so a
      //   country's name sits where a cartographer put it, not at a centroid that
      //   can fall in the sea. Label points arrive from GlobeMap (derived once).
      [PLACES_SOURCES.countries]: { type: 'geojson', data: geo('countries') },
      [PLACES_SOURCES.countryLabels]: { type: 'geojson', data: EMPTY_FC },
      [PLACES_SOURCES.provinces]: { type: 'geojson', data: geo('provinces') },
      [PLACES_SOURCES.provinceLabels]: { type: 'geojson', data: geo('province-labels') },
      [PLACES_SOURCES.regions]: { type: 'geojson', data: geo('regions') },
      [PLACES_SOURCES.places]: { type: 'geojson', data: geo('places') },
      [CACHE_SOURCE]: { type: 'geojson', data: EMPTY_FC },
      [WEDGE_SOURCE]: { type: 'geojson', data: EMPTY_FC },
      [CAMERA_SOURCE]: {
        type: 'geojson',
        data: EMPTY_FC,
        cluster: true,
        clusterMinPoints: CLUSTER_MIN_POINTS,
        clusterRadius: 40,
        clusterMaxZoom: 9,
      },
    },
    layers: [
      // ★ The background layer paints the SPHERE (space is the container behind it), so
      //   it is the Earth's colour: with no imagery — offline, empty cache — the globe
      //   still reads as a planet against the void, not as a crescent of atmosphere.
      { id: 'earth', type: 'background', paint: { 'background-color': GLOBE.earth } },
      ...(i.provider === null
        ? []
        : [{ id: 'imagery', type: 'raster' as const, source: GLOBE_IMAGERY_SOURCE }]),
      // ── places: under the cameras, over the imagery ──
      {
        id: 'le-country-borders',
        type: 'line',
        source: PLACES_SOURCES.countries,
        layout: { ...vis, 'line-join': 'round' },
        paint: {
          'line-color': GLOBE.border,
          'line-width': ['interpolate', ['linear'], ['zoom'], 1, 0.4, 5, 1, 9, 1.6],
        },
      },
      {
        id: 'le-province-borders',
        type: 'line',
        source: PLACES_SOURCES.provinces,
        minzoom: 3.5,
        layout: vis,
        paint: {
          'line-color': GLOBE.borderMinor,
          'line-width': 0.7,
          'line-dasharray': [3, 2],
        },
      },
      {
        id: 'le-continent-labels',
        type: 'symbol',
        source: PLACES_SOURCES.regions,
        filter: ['==', ['get', 'kind'], 'continent'],
        maxzoom: 3,
        layout: {
          ...vis,
          'text-field': ['upcase', ['get', 'name']],
          'text-font': [GLOBE_FONT],
          'text-size': ['interpolate', ['linear'], ['zoom'], 0.5, 12, 2.5, 20],
          'text-letter-spacing': 0.3,
          'text-allow-overlap': false,
        },
        paint: { 'text-color': GLOBE.label, ...halo },
      },
      {
        id: 'le-region-labels',
        type: 'symbol',
        source: PLACES_SOURCES.regions,
        filter: ['==', ['get', 'kind'], 'subregion'],
        minzoom: 2.2,
        maxzoom: 4.2,
        layout: {
          ...vis,
          'text-field': ['upcase', ['get', 'name']],
          'text-font': [GLOBE_FONT],
          'text-size': 11,
          'text-letter-spacing': 0.2,
        },
        paint: { 'text-color': GLOBE.labelQuiet, ...halo },
      },
      {
        id: 'le-country-labels',
        type: 'symbol',
        source: PLACES_SOURCES.countryLabels,
        minzoom: 2.2,
        maxzoom: 9,
        layout: {
          ...vis,
          'text-field': countryName(i.lang),
          'text-font': [GLOBE_FONT],
          'text-size': ['interpolate', ['linear'], ['zoom'], 2, 10, 6, 15],
          'text-transform': 'uppercase',
          'text-letter-spacing': 0.1,
          'symbol-sort-key': ['-', 0, ['coalesce', ['get', 'pop'], 0]],
        },
        paint: { 'text-color': GLOBE.label, ...halo },
      },
      {
        id: 'le-province-labels',
        type: 'symbol',
        source: PLACES_SOURCES.provinceLabels,
        minzoom: 5,
        layout: {
          ...vis,
          'text-field': ['get', 'name'],
          'text-font': [GLOBE_FONT],
          'text-size': 11,
          'text-letter-spacing': 0.08,
        },
        paint: { 'text-color': GLOBE.labelQuiet, ...halo },
      },
      {
        id: 'le-city-dots',
        type: 'circle',
        source: PLACES_SOURCES.places,
        minzoom: 3.5,
        layout: vis,
        paint: {
          'circle-color': GLOBE.cityDot,
          'circle-radius': ['case', ['==', ['get', 'capital'], 1], 3.5, 2.2],
          'circle-stroke-color': GLOBE.cityDotStroke,
          'circle-stroke-width': 1,
        },
      },
      {
        id: 'le-city-labels',
        type: 'symbol',
        source: PLACES_SOURCES.places,
        minzoom: 3.5,
        layout: {
          ...vis,
          'text-field': ['get', 'name'],
          'text-font': [GLOBE_FONT],
          'text-size': ['case', ['==', ['get', 'capital'], 1], 12.5, 11],
          'text-anchor': 'left',
          'text-offset': [0.6, 0],
          'text-optional': true,
          // Bigger cities win the collision; the file's own rank breaks ties.
          'symbol-sort-key': ['-', 0, ['coalesce', ['get', 'pop'], 0]],
        },
        paint: { 'text-color': GLOBE.label, ...halo },
      },
      // ── the offline-cache area being drawn ──
      {
        id: LAYER_CACHE_FILL,
        type: 'fill',
        source: CACHE_SOURCE,
        filter: ['==', ['geometry-type'], 'Polygon'],
        paint: { 'fill-color': GLOBE.live, 'fill-opacity': 0.12 },
      },
      {
        id: LAYER_CACHE_LINE,
        type: 'line',
        source: CACHE_SOURCE,
        filter: ['!=', ['geometry-type'], 'Point'],
        paint: {
          'line-color': GLOBE.live,
          'line-width': 2,
          'line-dasharray': ['case', ['boolean', ['get', 'drawing'], false], ['literal', [2, 2]], ['literal', [1, 0]]],
        },
      },
      {
        id: LAYER_CACHE_VERTICES,
        type: 'circle',
        source: CACHE_SOURCE,
        filter: ['==', ['geometry-type'], 'Point'],
        paint: {
          'circle-color': GLOBE.live,
          'circle-radius': 4,
          'circle-stroke-color': GLOBE.vertexStroke,
          'circle-stroke-width': 1.5,
        },
      },
      {
        id: LAYER_WEDGES,
        type: 'fill',
        source: WEDGE_SOURCE,
        paint: { 'fill-color': GLOBE.wedge, 'fill-opacity': 0.18 },
      },
      {
        id: LAYER_CLUSTER_HALO,
        type: 'circle',
        source: CAMERA_SOURCE,
        filter: ['has', 'point_count'],
        paint: {
          'circle-color': GLOBE.cluster,
          'circle-opacity': 0.18,
          'circle-radius': ['+', 14, ['*', 1.5, ['sqrt', ['get', 'point_count']]]],
        },
      },
      {
        id: LAYER_CLUSTERS,
        type: 'circle',
        source: CAMERA_SOURCE,
        filter: ['has', 'point_count'],
        paint: {
          'circle-color': GLOBE.cluster,
          'circle-radius': ['+', 6, ['*', 1.2, ['sqrt', ['get', 'point_count']]]],
          'circle-stroke-color': GLOBE.markerStroke,
          'circle-stroke-width': 1,
        },
      },
      {
        id: LAYER_CAMERA_HALO,
        type: 'circle',
        source: CAMERA_SOURCE,
        filter: ['!', ['has', 'point_count']],
        paint: {
          'circle-color': statusColour(),
          'circle-opacity': ['match', ['get', 'status'], 'unknown', 0.08, 0.22],
          'circle-radius': 12,
        },
      },
      {
        id: LAYER_CAMERAS,
        type: 'circle',
        source: CAMERA_SOURCE,
        filter: ['!', ['has', 'point_count']],
        paint: {
          'circle-color': statusColour(),
          'circle-opacity': ['match', ['get', 'status'], 'unknown', 0.55, 1],
          'circle-radius': 5,
          'circle-stroke-color': GLOBE.markerStroke,
          'circle-stroke-width': 1.5,
        },
      },
    ],
  };
}

/** Colour = status: cyan live · amber connecting · red lost/refused · dim never opened. */
function statusColour(): ExpressionSpecification {
  return [
    'match',
    ['get', 'status'],
    'live',
    GLOBE.live,
    'connecting',
    GLOBE.connecting,
    'lost',
    GLOBE.lost,
    'refused',
    GLOBE.lost,
    GLOBE.unknown,
  ] as ExpressionSpecification;
}
