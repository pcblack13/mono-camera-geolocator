/**
 * ★ Slippy-tile / Web-Mercator math for the map pane — SCOPE.md §5's honest accuracy.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * ★ WHY THIS LIVES IN `components/map/` AND NOT `lib/`.
 *
 *   `lib/**` is IU-25's. This unit (IU-27) owns `components/map/**`. The functions
 *   here are a *rendering* concern — they turn the live map zoom into the
 *   ground-sample-distance and the achievable click accuracy the surveyor sees as
 *   they aim (SCOPE.md §5: *"the ground-sample-distance / achievable-accuracy at the
 *   current zoom shown honestly to the surveyor as they click"*). They are co-located
 *   with the only pane that uses them.
 *
 * ★ **THIS IS A PREVIEW, NOT THE STORED NUMBER.** The authoritative `GcpAccuracy` is
 *   computed server-side from the imagery GSD and click precision on commit
 *   (`gis/accuracy.py`, SCOPE.md §5) and returned on the `GcpRead`. This estimate
 *   exists so the surveyor can judge, *before* clicking, whether this zoom is good
 *   enough — it is deliberately labelled as an estimate at every render site and is
 *   never sent to the server, stored, or exported.
 * ─────────────────────────────────────────────────────────────────────────────
 *
 * **Pure.** No React, no Leaflet, no store. Unit-testable in isolation.
 */

import type { BasemapKind, LatLon } from '../../types/geo';

/** WGS84 equatorial radius, metres — the sphere Web Mercator tiles are cut on. */
export const EARTH_RADIUS_M = 6378137;

/** `2 · π · R` — one full trip round the equator at the Mercator scale, metres. */
export const EARTH_CIRCUMFERENCE_M = 2 * Math.PI * EARTH_RADIUS_M;

/**
 * ★ The surveyor's pointing precision, in *screen* pixels, feeding the click-error
 *   term. Three CSS px is a conservative, defensible figure for a deliberate click
 *   with a crosshair cursor on a static basemap — not one px (over-optimistic, it
 *   ignores hand tremor and edge ambiguity) and not ten (a careless drag).
 *
 * ★ It is a *screen* pixel, converted to ground metres through {@link metresPerPixel}
 *   at the live zoom — which is exactly why zooming in tightens the estimate and is
 *   the honest incentive to zoom before committing.
 */
export const CLICK_PRECISION_PX = 3;

/**
 * ★ A 2-D 90 %-radius (CE90) is `2.146 · σ`. Everything on `GcpAccuracy` is CE90
 *   (`types/gcp.ts`), so the preview must be too or it would not be comparable to the
 *   number the server later returns.
 */
export const CE90_SIGMA = 2.146;

/**
 * Ground metres spanned by ONE screen pixel at a given latitude and zoom.
 *
 * ★ Web Mercator: the projection stretches away from the equator by `1 / cos(lat)`,
 *   so a pixel at 60°N covers half the ground it does at the equator. Ignoring the
 *   `cos(lat)` — the single most common slippy-map error — would over-report accuracy
 *   at high latitude, which is the wrong direction to be wrong (L12).
 *
 * @param lat      latitude in degrees; clamped to Mercator's ±85.05° validity.
 * @param zoom     the slippy zoom level (may be fractional — Leaflet allows it).
 * @param tileSize the provider's tile edge in px (`ProviderCapabilities.tile_size_px`,
 *                 256 for almost everything, 512 for some retina providers).
 */
export function metresPerPixel(lat: number, zoom: number, tileSize = 256): number {
  const clampedLat = Math.min(85.05112878, Math.max(-85.05112878, lat));
  const worldPx = tileSize * 2 ** zoom;
  return (EARTH_CIRCUMFERENCE_M * Math.cos((clampedLat * Math.PI) / 180)) / worldPx;
}

export interface ClickAccuracyEstimate {
  /** Ground metres per screen pixel at the live view — the "GSD at this zoom". */
  mpp_m: number;
  /** The click-precision term, CE90 ground metres. Shrinks as you zoom in. */
  click_ce90_m: number;
  /** The imagery provider's absolute georeferencing error, CE90 metres. Fixed. */
  georef_ce90_m: number;
  /** ★ `sqrt(click² + georef²)` — the headline preview, mirroring `total_ce90_m`. */
  total_ce90_m: number;
  /** ★ Which term dominates — the field that tells the surveyor what to fix. */
  dominant_term: 'landmark_click' | 'georeference';
}

/**
 * The live accuracy preview for a click at `at`, on a provider whose georeferencing
 * error is `georefCe90M`, at the current `zoom`.
 *
 * ★ Combines in quadrature exactly as `GcpAccuracy.total_ce90_m` does, so the preview
 *   and the committed value are on the same scale and the surveyor is never surprised
 *   by the number that lands on the row.
 */
export function estimateClickAccuracy(
  at: LatLon,
  zoom: number,
  georefCe90M: number,
  tileSize = 256,
  clickPx = CLICK_PRECISION_PX,
): ClickAccuracyEstimate {
  return accuracyFromMetresPerPixel(metresPerPixel(at.lat, zoom, tileSize), georefCe90M, clickPx);
}

/**
 * The same estimate, from a **measured** ground-metres-per-pixel rather than a derived one.
 *
 * ★★ **THIS EXISTS BECAUSE THE NADIR ASSUMPTION BREAKS UNDER TILT.**
 *    {@link metresPerPixel} is `circumference · cos(lat) / worldPx` — the ground covered
 *    by one pixel of a flat, straight-down map. In the 3D pane the camera is pitched, so
 *    a pixel near the horizon covers *far* more ground than one at the centre of the
 *    screen: the same screen distance is a very different ground distance depending on
 *    where you clicked. Reusing the 2D number there would report a click precision several
 *    times better than the surveyor actually achieved — a flattering, wrong accuracy on a
 *    survey deliverable, which is precisely the failure this codebase is built to avoid.
 *
 *    The 3D pane measures the real figure by unprojecting two adjacent screen pixels and
 *    taking the ground distance between them, then calls this. One implementation of the
 *    quadrature, two ways of learning the scale.
 *
 * @param mpp        ground metres per screen pixel, however it was obtained.
 * @param georefCe90M the provider's absolute georeferencing error, CE90 metres.
 * @param clickPx    pointing precision in pixels.
 */
export function accuracyFromMetresPerPixel(
  mpp: number,
  georefCe90M: number,
  clickPx = CLICK_PRECISION_PX,
): ClickAccuracyEstimate {
  const clickSigma = clickPx * mpp;
  const clickCe90 = CE90_SIGMA * clickSigma;
  const georef = Number.isFinite(georefCe90M) && georefCe90M >= 0 ? georefCe90M : 0;
  const total = Math.sqrt(clickCe90 * clickCe90 + georef * georef);
  return {
    mpp_m: mpp,
    click_ce90_m: clickCe90,
    georef_ce90_m: georef,
    total_ce90_m: total,
    dominant_term: clickCe90 >= georef ? 'landmark_click' : 'georeference',
  };
}

/**
 * The proxy tile URL template for Leaflet's `TileLayer`.
 *
 * ★ SCOPE.md / L2: **tiles come from the BACKEND PROXY, never a provider directly** —
 *   that is what keeps API keys server-side (CONTRACT §7.2, endpoint 52). Leaflet
 *   substitutes `{z}`/`{x}`/`{y}`; the browser-facing proxy is standard slippy
 *   `{z}/{x}/{y}` (the backend handles any provider-specific axis order, e.g. Esri's
 *   `{z}/{y}/{x}`, internally). `kind` selects satellite / hybrid / terrain.
 *
 * @param apiBaseUrl `API_BASE_URL` from `api/client.ts` (default `/api/v1`).
 */
export function proxyTileUrl(apiBaseUrl: string, provider: string, kind: string): string {
  return `${apiBaseUrl}/imagery/tiles/${provider}/{z}/{x}/{y}?kind=${encodeURIComponent(kind)}`;
}

/**
 * The basemap kind actually drawable on a provider serving `kinds` — `basemap` itself
 * when served, else the provider's first (canonical) kind.
 *
 * ★ WHY THIS EXISTS. The basemap choice is PERSISTED and survives provider changes, so
 *   a kind one provider served can outlive a switch to a provider that cannot draw it
 *   (Esri served hybrid/terrain; Mapbox is satellite-only). The server then rightly
 *   refuses every tile (`TileOutOfRangeError` → 4xx) and the map renders as markers
 *   floating on blank ground. Every seam that pairs a provider with a kind clamps
 *   through here. Unknown capabilities (`undefined`, still loading) clamp to nothing —
 *   claiming a kind is unservable before the server has said so would be a guess.
 */
export function clampBasemapToKinds(
  basemap: BasemapKind,
  kinds: readonly BasemapKind[] | undefined,
): BasemapKind {
  if (!kinds || kinds.length === 0 || kinds.includes(basemap)) return basemap;
  return kinds[0];
}

/**
 * Is the map zoomed past the provider's native imagery resolution?
 *
 * ★ `mapZoom` is the LEAFLET zoom; a 512-px provider's zoom bounds all shift by +1
 *   (`zoomShift`, see `SatelliteMap`), so the native boundary must shift with them.
 *   `null` native zoom = unknown → never claim overzoom we cannot substantiate.
 */
export function beyondNativeResolution(
  mapZoom: number,
  zoomShift: number,
  nativeMaxZoom: number | null | undefined,
): boolean {
  if (nativeMaxZoom === null || nativeMaxZoom === undefined) return false;
  return mapZoom > nativeMaxZoom + zoomShift;
}

// ── slippy-tile ↔ lon/lat, for offline area caching ──────────────────────────

/** A Web-Mercator tile address at a zoom level (standard XYZ / slippy convention). */
export interface TileXYZ {
  z: number;
  x: number;
  y: number;
}

/** Longitude → tile column at zoom `z` (fractional; floor for the tile index). */
export function lonToTileX(lon: number, z: number): number {
  return ((lon + 180) / 360) * 2 ** z;
}

/** Latitude → tile row at zoom `z` (fractional; floor for the tile index). */
export function latToTileY(lat: number, z: number): number {
  const r = (lat * Math.PI) / 180;
  return ((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2) * 2 ** z;
}

/** Tile column → longitude of the tile's west edge. */
export function tileXToLon(x: number, z: number): number {
  return (x / 2 ** z) * 360 - 180;
}

/** Tile row → latitude of the tile's north edge. */
export function tileYToLat(y: number, z: number): number {
  const n = Math.PI - (2 * Math.PI * y) / 2 ** z;
  return (180 / Math.PI) * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)));
}

/** Ray-casting point-in-polygon. `polygon` is a ring of `[lat, lon]` vertices. */
export function pointInPolygon(lat: number, lon: number, polygon: [number, number][]): boolean {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const [latI, lonI] = polygon[i];
    const [latJ, lonJ] = polygon[j];
    const intersect =
      lonI > lon !== lonJ > lon && lat < ((latJ - latI) * (lon - lonI)) / (lonJ - lonI) + latI;
    if (intersect) inside = !inside;
  }
  return inside;
}

/** Do the open segments (a→b) and (c→d) cross? Points are `[lat, lon]`. */
function segmentsCross(
  a: [number, number],
  b: [number, number],
  c: [number, number],
  d: [number, number],
): boolean {
  const o = (p: [number, number], q: [number, number], r: [number, number]): number =>
    (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]);
  const o1 = o(a, b, c);
  const o2 = o(a, b, d);
  const o3 = o(c, d, a);
  const o4 = o(c, d, b);
  return o1 * o2 < 0 && o3 * o4 < 0;
}

/**
 * Does the tile rectangle overlap `polygon`? Handles all size relationships: tile larger
 * than the area (a polygon vertex sits inside the tile), tile smaller than the area (a tile
 * corner sits inside the polygon), and partial overlap (an edge crossing).
 */
function tileOverlapsPolygon(
  north: number,
  south: number,
  west: number,
  east: number,
  polygon: [number, number][],
): boolean {
  // Any tile corner inside the polygon → overlap (covers tile ⊆ polygon).
  const corners: [number, number][] = [
    [north, west],
    [north, east],
    [south, west],
    [south, east],
  ];
  for (const [lat, lon] of corners) if (pointInPolygon(lat, lon, polygon)) return true;
  // Any polygon vertex inside the tile rect → overlap (covers polygon ⊆ tile).
  for (const [lat, lon] of polygon) {
    if (lat <= north && lat >= south && lon >= west && lon <= east) return true;
  }
  // Any polygon edge crossing any tile edge → partial overlap.
  const edges: [[number, number], [number, number]][] = [
    [corners[0], corners[1]],
    [corners[1], corners[3]],
    [corners[3], corners[2]],
    [corners[2], corners[0]],
  ];
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    for (const [e0, e1] of edges) if (segmentsCross(polygon[j], polygon[i], e0, e1)) return true;
  }
  return false;
}

/**
 * Every tile whose rectangle OVERLAPS `polygon`, across the inclusive zoom band
 * `[zMin, zMax]`. `polygon` is a ring of `[lat, lon]` vertices.
 *
 * ★ Rectangle-overlap, NOT centre-in-polygon: a small area (smaller than a low-zoom tile)
 *   must still cache the one tile that covers it, or the map would have nothing to show
 *   offline at that zoom. `cap` bounds the returned list — the caller warns and lets the
 *   surveyor shrink the area or the detail rather than downloading tens of thousands.
 */
export function tilesForPolygon(
  polygon: [number, number][],
  zMin: number,
  zMax: number,
  cap = 50_000,
): { tiles: TileXYZ[]; capped: boolean } {
  const tiles: TileXYZ[] = [];
  if (polygon.length < 3) return { tiles, capped: false };
  const lats = polygon.map((p) => p[0]);
  const lons = polygon.map((p) => p[1]);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const minLon = Math.min(...lons);
  const maxLon = Math.max(...lons);

  for (let z = zMin; z <= zMax; z++) {
    const n = 2 ** z;
    const xLo = Math.max(0, Math.floor(lonToTileX(minLon, z)));
    const xHi = Math.min(n - 1, Math.floor(lonToTileX(maxLon, z)));
    // Tile Y grows southward, so maxLat gives the smaller Y.
    const yLo = Math.max(0, Math.floor(latToTileY(maxLat, z)));
    const yHi = Math.min(n - 1, Math.floor(latToTileY(minLat, z)));
    for (let x = xLo; x <= xHi; x++) {
      for (let y = yLo; y <= yHi; y++) {
        const north = tileYToLat(y, z);
        const south = tileYToLat(y + 1, z);
        const west = tileXToLon(x, z);
        const east = tileXToLon(x + 1, z);
        if (tileOverlapsPolygon(north, south, west, east, polygon)) {
          tiles.push({ z, x, y });
          if (tiles.length >= cap) return { tiles, capped: true };
        }
      }
    }
  }
  return { tiles, capped: false };
}
