/**
 * DEM processing — mirrors `schemas/dem.py` (§6.2).
 *
 * ★ These types describe the THREE-STAGE algorithm in `gis/dem`, and nothing else:
 *   crop to an AOI, reproject to metres, sample elevations. There is no `fill_sinks`
 *   and no `smoothing` level — the scaffold offered both and the pipeline implements
 *   neither. A control that does nothing is the UI equivalent of a fabricated number.
 *
 * ★ Wire fields are snake_case and are never renamed (§8.1 / L9).
 */

/** A corner or point, EPSG:4326. Accepts decimal degrees or any DMS spelling. */
export interface DemPoint {
  /** `34.127544`, `34°07'39.16"N`, or `34; 7; 39.16; N`. */
  lat: string | number;
  /** Same accepted spellings. */
  lon: string | number;
}

/** Resampling kernels the backend offers. `bilinear` is the default for elevation. */
export type DemResampling =
  | 'nearest'
  | 'bilinear'
  | 'cubic'
  | 'cubic_spline'
  | 'lanczos'
  | 'average'
  | 'mode';

/** What stage 1 did. */
export interface DemCropSummary {
  source_crs: string;
  tolerance: number;
  /** `[width, height]` in pixels. */
  output_size: [number, number];
  /** Source pixel size, in the SOURCE CRS's units — degrees, for a geographic DEM. */
  pixel_size: [number, number];
  /**
   * ★ True when the padded AOI reached past the DEM's edge. The area of interest is
   * NOT fully covered by this tile, so part of it has no elevation at all.
   */
  clipped: boolean;
  aoi_corners_lonlat: [number, number][];
}

/** What stage 2 did — `(λ, φ, H) → (E, N, H)`. */
export interface DemReprojectSummary {
  source_crs: string;
  target_crs: string;
  resampling: string;
  /** True when the UTM zone was chosen from the DEM centre rather than given. */
  auto_utm: boolean;
  source_pixel_size: [number, number];
  /** ★ The DEM's ground sample distance, TRUE metres. The number worth reading. */
  output_pixel_size_m: [number, number];
  output_size: [number, number];
  output_bounds_m: [number, number, number, number];
}

/** Elevation range of the processed DEM. `null` when every cell is void. */
export interface DemStatistics {
  min_m: number | null;
  max_m: number | null;
  mean_m: number | null;
  valid_cells: number;
  void_cells: number;
}

/** The camera station an AOI was built from, and the zone it fixes. */
export interface DemCameraSummary {
  lat: number;
  lon: number;
  /** Working radius, TRUE ground metres. */
  radius_m: number;
  /**
   * ★ The UTM zone the camera position falls in — DERIVED, never typed. A zone entered
   * by hand can be wrong; one taken from where the camera stood cannot.
   */
  utm_epsg: string;
}

/** `POST /dem/process` → the full record of one run. */
export interface DemProcessResponse {
  run_id: string;
  /** Present when the AOI came from a camera position + radius. */
  camera: DemCameraSummary | null;
  source_name: string;
  source_crs: string;
  output_crs: string;
  output_size: [number, number];
  /** `null` when the output is not in a ground-metre CRS. */
  output_pixel_size_m: [number, number] | null;
  output_bytes: number;
  crop: DemCropSummary | null;
  reproject: DemReprojectSummary | null;
  statistics: DemStatistics;
  /** The AOI polygon, WGS84, ready to draw on a map. */
  aoi_geojson: Record<string, unknown> | null;
  /** Honest notes: a clamped crop, a skipped stage, a void-heavy output. */
  warnings: string[];
  download_url: string;
  /**
   * ★ True when this run became the DEM new GCPs sample elevation from. Existing GCPs
   * are NOT re-sampled — a recorded elevation is an observation, not a live query.
   */
  is_elevation_source: boolean;
}

/** The multipart form `POST /dem/process` accepts. */
/**
 * What the DEM pages hold after a pick: browser bytes, or a desktop PATH.
 *
 * ★ The path variant exists because the desktop shell and the API share one
 * machine: a 3.8 GB tile shipped as bytes must survive IPC + several in-memory
 * copies + an HTTP body (it didn't — files over 2 GiB failed outright), while a
 * path costs nothing and the backend streams straight from disk.
 */
export type DemSource =
  | { kind: 'file'; name: string; size: number; file: File }
  | { kind: 'path'; name: string; size: number; path: string };

export interface DemProcessForm {
  /** The upload's bytes (browser route). Exactly one of `file`/`source_path`. */
  file?: File;
  /** Absolute path on the API's own machine (desktop route). */
  source_path?: string;
  /** ★ Adopt the output as this project's elevation source (with
   *  `set_as_elevation_source: true`) — the processing page's project mode. */
  project_id?: string;
  /**
   * ★ Adopt the output for ONE image instead of the whole project (needs `project_id`
   * too). That image's GCPs and auto-GCP raycast then read THIS DEM; every other image
   * keeps the project DEM — the image-overrides-project rule.
   */
  image_id?: string;
  /** At least 3 corners, or omitted to process the whole DEM. */
  aoi_corners?: DemPoint[];
  /**
   * ★ Camera station. All three together or none. When given they define the AOI (a
   * disc of `radius_m` around the station) AND fix the UTM zone, so `target_srid` is
   * unnecessary — the zone follows from where the camera stood.
   */
  camera_lat?: number;
  camera_lon?: number;
  radius_m?: number;
  /** Padding fraction around the AOI. `0.10` is 10%. */
  tolerance?: number;
  reproject?: boolean;
  /** Explicit projected EPSG code, or omitted to auto-pick the UTM zone. */
  target_srid?: number | null;
  /**
   * ★ NOT SURFACED IN THE UI. The server defaults to `bilinear`, which is the right
   * kernel for a continuous elevation surface; the API keeps the parameter because it
   * is part of the algorithm, but the page does not ask.
   */
  resampling?: DemResampling;
  /** ★ NOT SURFACED. Omitted means "preserve the source resolution", the safe default. */
  target_resolution_m?: number | null;
  /** Adopt this DEM as the GCP elevation source. Defaults to true server-side. */
  set_as_elevation_source?: boolean;
}

/** One sampled point — stage 3's row. */
export interface DemSampledPoint {
  name: string;
  lat: number;
  lon: number;
  x: number | null;
  y: number | null;
  /** ★ `null` and `0` are different claims: null means void or off-grid. */
  dem_z_m: number | null;
  offset_m: number;
  z_m: number | null;
  inside_dem: boolean;
  /** Elevation outside the plausible land-surface range. Reported, never dropped. */
  suspicious: boolean;
}

/** `POST /dem/{run_id}/sample` body. */
export interface DemSampleForm {
  points: DemPoint[];
  names?: string[];
  method?: 'bilinear' | 'nearest';
  offset_m?: number;
  output_crs?: string | null;
}

/** `POST /dem/{run_id}/sample` result. */
export interface DemSampleResponse {
  run_id: string;
  dem_crs: string;
  output_crs: string;
  method: string;
  offset_m: number;
  points: DemSampledPoint[];
  inside_count: number;
  with_elevation_count: number;
}

/** `GET /dem/active` — which DEM currently feeds GCP elevations. */
export interface DemActiveResponse {
  active: boolean;
  /**
   * ★ True when `LE_ELEVATION_PROVIDER=dem_run`. A DEM can be adopted while the
   * provider is off, in which case nothing samples it — reported, not hidden.
   */
  provider_enabled: boolean;
  path?: string | null;
  /** ★ Set when the DEM belongs to ONE project; null for the server-wide fallback. */
  project_id?: string | null;
  /** ★ Set when the DEM belongs to ONE image (the per-image override); null otherwise. */
  image_id?: string | null;
  run_id?: string | null;
  source_name?: string | null;
  adopted_at?: string | null;
  output_crs?: string | null;
  output_pixel_size_m?: number[] | null;
  /** Reported as `elevation_ce90_m` on every GCP sampled from this DEM. */
  vertical_ce90_m?: number | null;
  /** `unknown` unless declared. Orthometric vs ellipsoidal differ by ~20 m here. */
  vertical_datum?: string | null;
  statistics?: Record<string, unknown> | null;
}
