/**
 * Geographic + pixel vocabulary — mirrors `schemas/common.py` and `schemas/imagery.py` (§6.2).
 *
 * ★ THE CONVENTIONS, from §6.1, and they are load-bearing:
 *   - Image pixel space: `(x, y)`, origin TOP-LEFT, y-DOWN, floats (sub-pixel), SRID 0.
 *   - An integer coordinate is the pixel CENTRE (the OpenCV/SIFT convention).
 *   - World: EPSG:4326 decimal degrees, `lat` then `lon` in objects — but
 *     **`[lon, lat]` inside any GeoJSON** (RFC 7946 mandates x,y).
 *   - Distances: metres, suffix `_m`, ALWAYS true ground metres, never projected.
 *   - Angles: degrees, suffix `_deg`, 0 = TRUE North, clockwise.
 */

import type { IsoDateTime } from './common';

// ─────────────────────────────────────────────────────────────────────────────
// Points and boxes
// ─────────────────────────────────────────────────────────────────────────────

/** ★ `lat` then `lon`. This is NOT GeoJSON order — see `GeoJsonPoint`. */
export interface LatLon {
  /** [-90, 90] */
  lat: number;
  /** [-180, 180] */
  lon: number;
}

export interface LatLonAlt extends LatLon {
  altitude_m: number | null;
}

/**
 * A point in image OR satellite-mosaic pixel space. Which one is named by the
 * field that holds it (`image_px` vs `satellite_px`), never by this type.
 */
export interface PixelXY {
  x: number;
  y: number;
}

export interface PixelBox {
  min_x: number;
  min_y: number;
  max_x: number;
  max_y: number;
}

/** Wire form is the CSV string `"minlon,minlat,maxlon,maxlat"`; parsed to this. */
export interface BBox {
  min_lon: number;
  min_lat: number;
  max_lon: number;
  max_lat: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// Transforms
// ─────────────────────────────────────────────────────────────────────────────

/**
 * 9 floats, **ROW-MAJOR**, image pixel → satellite mosaic pixel (§6.1, §4.24).
 *
 * ★ Row-major everywhere — `H`, `Σ_H`, `A_h`, the DB, the API. Getting this
 *   backwards yields coordinates that look plausible and are wrong by hundreds
 *   of metres. `MatchResultRead.transform_note` ships the chain in the payload
 *   for exactly this reason.
 */
export type Homography = [number, number, number, number, number, number, number, number, number];

/**
 * 6 floats, **GDAL order** `[c, a, b, f, d, e]` — i.e.
 * `(origin_x, pixel_width, row_rotation, origin_y, col_rotation, pixel_height)`,
 * `pixel_height` negative for north-up rasters. Maps mosaic pixel → the CRS named
 * by `sat_geotransform_srid`.
 *
 * ★ `sat_geotransform_srid` is AUTHORITATIVE and is **not always 3857** — it is a
 *   UTM code for `local_orthophoto`, the highest-accuracy provider (§4.17).
 * ★ GDAL geotransform columns are pixel EDGES while our pixel coordinates are
 *   CENTRES: the bridge is `col_gdal = u_cv + 0.5` (§6.1).
 */
export type GeoTransform = [number, number, number, number, number, number];

/** An authority string, e.g. `"EPSG:4326"`. */
export type Crs = string;

// ─────────────────────────────────────────────────────────────────────────────
// GeoJSON (RFC 7946)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * ★ THE TRAP, named so it cannot be fallen into: `AnnotationRead.geometry` is
 *   GeoJSON-*shaped* but is NOT geographic — its `coordinates` are IMAGE PIXELS,
 *   `[x, y]`, y-down, SRID 0. A reader must not feed it to Leaflet expecting
 *   degrees. The API REJECTS any `crs` member on input and never emits one (§6.2).
 *
 * Geographic GeoJSON (`ProjectRead.aoi`, `MatchResultRead.tile_bounds`,
 * `CameraPoseRead.footprint`) carries `[lon, lat]`, in that order.
 */
export interface GeoJsonPoint {
  type: 'Point';
  coordinates: [number, number];
}

export interface GeoJsonLineString {
  type: 'LineString';
  coordinates: [number, number][];
}

export interface GeoJsonPolygon {
  type: 'Polygon';
  /** Exterior ring first, then holes. Each ring closed (first === last), ≥ 4 positions. */
  coordinates: [number, number][][];
}

export interface GeoJsonMultiPolygon {
  type: 'MultiPolygon';
  coordinates: [number, number][][][];
}

export type GeoJsonGeometry =
  | GeoJsonPoint
  | GeoJsonLineString
  | GeoJsonPolygon
  | GeoJsonMultiPolygon;

export interface GeoJsonFeature<P = Record<string, unknown>> {
  type: 'Feature';
  geometry: GeoJsonGeometry;
  properties: P;
  id?: string | number;
}

export interface GeoJsonFeatureCollection<P = Record<string, unknown>> {
  type: 'FeatureCollection';
  features: GeoJsonFeature<P>[];
}

// ─────────────────────────────────────────────────────────────────────────────
// Imagery providers (§6.2 `imagery.py`, §4.17)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * ★ Values ARE the registry keys of the `ImageryProvider` implementations, and are
 *   identical to the `imagery_provider` PG enum (§5.3).
 *
 * ★ There is deliberately NO `google_earth` member. Google Earth imagery is out of
 *   scope by client legal constraint, and making it UNREPRESENTABLE IN THE TYPE
 *   SYSTEM is the cheapest possible enforcement. Not a disabled flag: an absence.
 */
export type ProviderId =
  /** ★★ DEFAULT · KEYLESS (L2) */
  | 'esri_world_imagery'
  /** ★★ OFFLINE · HIGHEST ACCURACY — local GeoTIFF directory, keyless */
  | 'local_orthophoto'
  /** ★★ Deterministic synthetic tiles. NO NETWORK. The front door of offline mode. */
  | 'fixture'
  | 'mapbox_satellite'
  | 'bing_aerial'
  | 'sentinel_copernicus'
  /** Requires a key AND `LE_GOOGLE_TOS_ACKNOWLEDGED=true`. Never a default. */
  | 'google_maps_static'
  | 'google_map_tiles';

/**
 * ★ The mandated "2D map with satellite/hybrid/terrain".
 *
 * ★ MATCHING ALWAYS USES `satellite`, normatively (invariant I4). Labels and
 *   hillshade are for human eyes only; feeding a label-burned tile to SIFT would
 *   be a genuine accuracy regression.
 */
export type BasemapKind = 'satellite' | 'hybrid' | 'terrain';

export interface ProviderCapabilities {
  supports_tiles: boolean;
  supports_static_bbox: boolean;
  /** Works with the NIC unplugged. */
  supports_offline: boolean;
  /** Authority string of the geotransform this provider returns. NOT fixed at 3857. */
  native_crs: Crs;
  /** What the `BasemapSwitcher` may offer for this provider. */
  kinds: BasemapKind[];
  tile_size_px: number;
  min_zoom: number;
  max_zoom: number;
  /** Best-case GSD at `max_zoom`, metres. */
  typical_gsd_m: number | null;
  /** ★ The provider's absolute georeferencing error, CE90 metres. Always knowable. */
  georef_ce90_m: number;
  /** Gates whether `MatchResultRead.imagery_captured_at` is meaningful. */
  imagery_date_known: boolean;
  rate_limit_rps: number | null;
  requires_attribution: boolean;
  /** ★ Per provider TERMS — gates the disk/redis tile caches. */
  allows_caching: boolean;
  /** ★ May a rendered chip go into a PDF deliverable? */
  allows_derivative_export: boolean;
  max_static_px: [number, number] | null;
  supports_multispectral: boolean;
  bands: string[];
  /**
   * ★ Where NATIVE detail typically ends — distinct from `max_zoom` (what the provider
   * SERVES). Above this the tiles are upsampled: they look sharp but carry no new
   * information, and the map warns before a GCP is placed on interpolation. Null = unknown.
   */
  native_max_zoom: number | null;
  /** How `native_max_zoom` was obtained — never an estimate posing as a vendor fact. */
  native_resolution_status: 'known' | 'estimated' | 'unknown';
  /** Epistemic status of `typical_gsd_m`. */
  gsd_status: 'vendor_certified' | 'estimated' | 'unknown';
  /** Epistemic status of `georef_ce90_m`. */
  accuracy_status: 'vendor_certified' | 'estimated' | 'unknown';
}

/** ★ NOT optional — a ToS obligation. The text travels with the pixels (§4.17). */
export interface ProviderAttribution {
  text: string;
  terms_url: string | null;
  logo_url: string | null;
}

export interface ProviderHealth {
  status: 'up' | 'degraded' | 'down';
  configured: boolean;
  latency_ms: number | null;
  message: string | null;
  checked_at: IsoDateTime | null;
}

export interface ProviderCoverage {
  /** `null` ⇒ global. */
  bbox: BBox | null;
  note: string | null;
}

export interface ProviderInfo {
  name: ProviderId;
  title: string;
  /**
   * ★ `configured: false` never means "you may not request it" for a MATCHER — but
   *   for a PROVIDER it does: an explicitly requested unconfigured provider is a
   *   `503 PROVIDER_NOT_CONFIGURED` (L11 exception (a)). Imagery changes the
   *   answer's PROVENANCE; a matcher changes only its ACCURACY.
   */
  configured: boolean;
  /**
   * ★ The OPERATOR'S verdict, distinct from `configured` (the provider's own).
   *   `false` ⇒ `LE_ALLOWED_PROVIDERS`/`LE_IMAGERY_OFFLINE` bans it on this server
   *   (requesting it anyway is a 403). Optional only for wire-skew tolerance —
   *   servers that predate the field mean "allowed".
   */
  allowed?: boolean;
  requires_key: boolean;
  is_default: boolean;
  capabilities: ProviderCapabilities;
  attribution: ProviderAttribution;
  coverage: ProviderCoverage;
  health: ProviderHealth;
}

// ─────────────────────────────────────────────────────────────────────────────
// Map view state — client-only (§8.5 `mapStore`)
// ─────────────────────────────────────────────────────────────────────────────

export interface MapViewState {
  center: LatLon;
  zoom: number;
  bounds: BBox | null;
}

/**
 * ★ Which pane caused the current view. Reveal is gated on it (§8.5):
 *   `if (selected && focusOrigin !== 'map') flyToGcp()`. A pane never auto-scrolls
 *   in response to its OWN action — which is what prevents "the map fights me when
 *   I click it."
 */
export type ViewOrigin = 'image' | 'map' | 'table' | 'user' | 'sync';

/**
 * Where to search. Resolution order is normative (§6.2) and resolved SERVER-side:
 * `aoi` → `center + radius_m` → image EXIF GPS → GeoTIFF bounds → project AOI →
 * `422 SEARCH_HINT_REQUIRED`. **Never a global search.**
 */
export interface LocationHint {
  center: LatLon | null;
  radius_m: number | null;
  aoi: GeoJsonPolygon | null;
}

/** One hit from `GET /imagery/geocode` — a place-name search result. */
export interface GeocodeResult {
  display_name: string;
  lat: number;
  lon: number;
  category: string | null;
  /** Suggested framing bounds, when the geocoder returns one. */
  bbox: BBox | null;
}
