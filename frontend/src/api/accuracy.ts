/**
 * `/accuracy/*` — measure a photograph's real geolocation error, then correct it.
 *
 * ★ WHAT THE NUMBERS MEAN, and the client must never imply more: every error here is
 *   measured against the satellite basemap, which carries its own georeferencing error
 *   of a few metres. `basemap_caveat` travels with the comparison for exactly that
 *   reason and is rendered, not dropped.
 *
 * ★ Three stages, three calls, because they have three different costs: `measure`
 *   (Stage D) is minutes and touches the network; `correct` (Stages E + F) is seconds
 *   over the stored measurement; `suggest` needs neither. All three are JOBS — they
 *   return a run to poll, and the durable result is read back from `state`.
 */

import type { Uuid } from '../types/common';
import { API_BASE_URL, fetchJson } from './client';

export type AccuracyRunKind = 'measure' | 'correct' | 'suggest';
export type AccuracyRunStatusValue = 'queued' | 'running' | 'succeeded' | 'failed';
/** The four competing answers, worst-to-best in the order they are shown. */
export type SolutionKey = 'raw' | 'pose' | 'field' | 'stagef';

export interface MeasureRequest {
  image_id: Uuid;
  provider?: string | null;
  gsd?: number;
  max_range?: number;
  tile?: number;
  stride?: number;
  sat_zoom?: number;
  mi_rescue?: boolean;
  fine_pass?: boolean;
  /**
   * ★ GRAZING GEOMETRY (2026-09-10). Every one of these defaults to the engine's
   *   own value, so omitting them all measures exactly what a request measured
   *   before they existed — that is what keeps an old measurement comparable with
   *   a new one. They exist for a fixed mast looking kilometres out, where a tile
   *   is SHEARED by terrain-height error rather than merely shifted.
   */
  /** A 'match' larger than this is refused as a false lock. 25 m suits a drone; at
   *  grazing incidence it censors real 26–30 m errors instead of reporting them. */
  max_shift?: number;
  /** Affine third chance for tiles the other two matchers rejected. Rescue only —
   *  a tile that already locked is never touched. */
  ecc_rescue?: boolean;
  /** Let the scene's geometry choose the tile size, overriding `tile`/`stride`. */
  tile_auto?: boolean;
  /** The terrain model's 1-sigma height error, metres. Scales `sigma_m` per tile. */
  sigma_dtm?: number;
  /** Above 0, drop tiles whose expected sigma exceeds this. 0 keeps them all. */
  reliability_max?: number;
  /** Raise `max_range` when it leaves under 85% of the visible ground inside it — a
   *  coverage rule, so a drone at 94–100% keeps its numbers and a mast whose circle
   *  holds 3% of what it sees gets a reach that contains its subject. */
  auto_reach?: boolean;
  /** Remove cloud in the satellite imagery from the content before matching. A lock
   *  on a cloud edge is not a geolocation error. Off by default — white roofs can
   *  trigger the mask; the run reports how many locked tiles sit on cloud either way. */
  cloud_mask?: boolean;
}

export interface CorrectRequest {
  image_id: Uuid;
  use_residual_field?: boolean;
  free_focal?: boolean;
}

export interface SuggestRequest {
  image_id: Uuid;
  count?: number;
  criterion?: 'ground' | 'dopt';
  box_frac?: number | null;
  stop_below_pct?: number;
}

export interface AccuracyRunStatus {
  run_id: string;
  kind: AccuracyRunKind;
  image_id: Uuid;
  project_id: Uuid;
  status: AccuracyRunStatusValue;
  progress_pct: number;
  message: string;
  started_at: string;
  finished_at: string | null;
  error: string | null;
  summary: Record<string, unknown> | null;
}

export interface AccuracyTile {
  x: number;
  y: number;
  tile_px: number;
  dE: number;
  dN: number;
  err: number;
  radial: number;
  tangential: number;
  range_m: number;
  response: number;
  method: 'phase' | 'mi' | 'fine' | 'ecc';
  /** False = this patch did NOT lock. Drawn grey, never as measured-and-fine. */
  ok: boolean;
  /**
   * ★ HOW MUCH THIS TILE'S NUMBER IS WORTH (2026-09-10). How far a metre of
   *   terrain-height error moves this tile's ground intersection — about 2 looking
   *   down from a drone, several times that along a mast's grazing sight line. Two
   *   tiles both reading 8 m are not equal evidence when one amplifies twice and
   *   the other six times. Null where the ground centre could not be read.
   */
  amplification: number | null;
  /** `amplification × sigma_dtm`: the error this tile carries from the terrain
   *  model alone, before anything the pose did. */
  sigma_m: number | null;
}

/**
 * What the scene's geometry does to terrain-height error, over the locked tiles.
 *
 * ★ Reported as a spread, not one number: the near and far ground of a grazing
 *   view amplify very differently and a median alone would hide it. Read `p90`
 *   when deciding whether a scene is measurable at all.
 */
export interface AccuracyAmplification {
  median: number;
  p90: number;
  max: number;
  tiles: number;
  /** The convention behind the figures — per locked tile, not per ground cell. */
  weighting: string;
  /** What `median` implies at this terrain model's 1-sigma: the floor under the
   *  measured error that no pose correction can lift. */
  expected_sigma_m: number;
  sigma_dtm_m: number;
}

/** One of the nine zones: a range band crossed with an image column. */
export interface AccuracyZoneCell {
  /** Index into `bands_m` — 0 is the nearest band. */
  band: number;
  column: 'L' | 'M' | 'R';
  /** How many locked tiles the number rests on. */
  tiles: number;
  /** Median error of those tiles. Null under `min_tiles`: the zone then has NO
   *  number, and it is drawn as a wash rather than a colour that reads as one. */
  median_error_m: number | null;
}

/**
 * The nine range zones traced on the photograph, and the error inside each.
 *
 * ★ THE MEASUREMENT PUT BACK IN THE FRAME. Stage D measures on the ground; the
 *   surveyor's question is asked at the photograph. Curves are in ORIGINAL photo
 *   pixels — the same convention the suggestion boxes use — and BEND with the
 *   terrain: a straight row would be wrong by hundreds of metres on any real slope.
 */
export interface AccuracyZones {
  width: number;
  height: number;
  /** The far edge of each band, metres of ground range — thirds of the farthest lock. */
  bands_m: number[];
  min_tiles: number;
  /** One contour per band, `[[u, v], ...]` left to right; null where that edge never
   *  crosses the frame. */
  curves: (number[][] | null)[];
  cells: AccuracyZoneCell[];
  /** The colour scale's two ends over the zones with data; null when none has any. */
  range_m: [number, number] | null;
}

/** What the coverage rule did with the requested reach. */
export interface AccuracyReach {
  requested_m: number;
  /** The reach that ran — the mosaic's radius and the ortho's extent. */
  used_m: number;
  /** Share of the visible ground inside the requested reach, 0..1. */
  coverage_requested: number;
  coverage_used: number;
  raised: boolean;
  min_coverage: number;
  cap_m: number;
  visible_samples: number;
}

/** Basemap cloud — how much of the content it is, and how many locks sit on it. */
export interface AccuracyCloud {
  masked: boolean;
  /** Share of the content the photograph covers that the mask calls cloud, 0..1. */
  content_fraction: number;
  /** Locked tiles with more than the threshold of their footprint on cloud. */
  locked_tiles_on_cloud: number;
  tile_fraction_threshold: number;
}

export interface AccuracyBand {
  band: string;
  tiles: number;
  median_error_m: number;
  dE: number;
  dN: number;
  radial: number;
  tangential: number;
}

export interface AccuracyGrid {
  width: number;
  height: number;
  gsd: number;
  origin_e: number;
  origin_n: number;
  heat_step: number;
  vmax_m: number;
  /**
   * Lat/lon corners of the WARPED heat layer (`heat_web_*`) — what the satellite pane
   * places it by. Null when too few tiles locked to draw one.
   */
  web_bounds: { south: number; west: number; north: number; east: number } | null;
  camera_x: number;
  camera_y: number;
}

export interface AccuracyMeasurement {
  measured_at: string;
  provider: string;
  params: Record<string, number | boolean>;
  tiles_total: number;
  tiles_locked: number;
  match_rate: number;
  median_error_m: number | null;
  bands: AccuracyBand[];
  methods: Record<string, number>;
  /** Null when nothing locked, or when no tile had a readable ground centre. */
  amplification?: AccuracyAmplification | null;
  /** Null when nothing locked, or when no band edge could be traced on the frame. */
  zones?: AccuracyZones | null;
  /** Null when the coverage rule was switched off for the run. */
  reach?: AccuracyReach | null;
  cloud?: AccuracyCloud | null;
  grid: AccuracyGrid;
  pose: {
    gcps_used?: number;
    reproj_mean_px?: number;
    reproj_max_px?: number;
    /** ★ What the solve did to the lens, when the focal was freed. */
    free_focal?: boolean;
    entered_focal_px?: number;
    solved_focal_px?: number;
  };
  warnings: string[];
  tiles: AccuracyTile[];
}

export interface CorrectionReport {
  n_pseudo_gcps: number;
  position_shift_m: number;
  azimuth_deg: number;
  tilt_down_deg: number;
  reproj_median_px: number;
  before_m: Record<string, number>;
  after_pose_m: Record<string, number>;
  after_full_m: Record<string, number>;
  residual_field: boolean;
  free_focal: boolean;
  /** ★ The gate. False = refining measured WORSE than doing nothing. */
  accepted: boolean;
  gate_reason: string;
}

export interface SolutionEntry {
  key: SolutionKey;
  label: string;
  colour: string;
  available: boolean;
  held_out: boolean;
  note: string;
  tiles: number;
  all_m: number | null;
  p95_m: number | null;
  worst20_share: number | null;
  bands: Record<string, number | null>;
}

export interface SolutionRow {
  band: string;
  values: Record<string, number | null>;
}

export interface SolutionsRead {
  corrected_at: string;
  use_residual_field: boolean;
  free_focal: boolean;
  best: SolutionKey;
  rows: SolutionRow[];
  entries: SolutionEntry[];
  stage_f: Record<string, number>;
  warnings: string[];
  basemap_caveat: string;
}

export interface SuggestRegion {
  rank: number;
  u: number;
  v: number;
  half_px: number;
  /** ★ The actionable number: how much predicted error a point here would remove. */
  cut_pct: number;
  score: number;
  range_m: number;
  slope: number;
  reasons: string[];
  short: string;
}

export interface SuggestionsRead {
  suggested_at: string;
  criterion: 'ground' | 'dopt';
  gcps_used: number;
  measured: boolean;
  max_range_m: number | null;
  best_cut_pct: number;
  stop_below_pct: number;
  verdict: 'converged' | 'keep_going';
  regions: SuggestRegion[];
}

/**
 * The stage this photograph stands on, once the surveyor has chosen one.
 *
 * ★ SCOPE — say it wherever this type is rendered: adopting changes what a **LUT
 *   build** stands on, and nothing else. Placed GCPs, exported coordinates and Auto GCP
 *   estimates keep using the pose solved from the control points themselves.
 */
export interface Adoption {
  stage: SolutionKey;
  label: string;
  adopted_at: string;
  corrected_at: string | null;
  all_m: number | null;
  p95_m: number | null;
  worst20_share: number | null;
  held_out: boolean;
  /** What the comparison recommended — beside the choice, never instead of it. */
  recommended: SolutionKey;
  matches_recommendation: boolean;
  gate_accepted: boolean;
  gate_reason: string | null;
  uses_refined_pose: boolean;
}

/**
 * Which pose the measurements are taken FROM.
 *
 * ★ After a correction is adopted, the next measurement starts from that pose — so its
 *   error is what the correction LEFT, not the error the control points alone produce.
 *   Two readings of "4 m" that answer different questions must be distinguishable, and
 *   this is what distinguishes them.
 */
export interface BasePose {
  source: 'gcps' | 'adopted';
  from_stage: SolutionKey | null;
  adopted_at: string | null;
  /** How many refinements deep. 0 = the control-point solve. */
  generation: number;
}

/**
 * How the RAW pose is solved from the control points.
 *
 * ★ `free_focal` solves one focal scale alongside the pose (fy follows fx at the
 *   entered ratio) instead of trusting the calibration exactly. Off by default: at
 *   grazing geometry focal trades off against tilt, so a freed focal can wander far
 *   from the calibrated value while the reprojection barely moves.
 */
export interface SolveOptions {
  free_focal: boolean;
}

/**
 * One archived measurement — an entry in the heat-map version history.
 *
 * ★ The loop re-measures after every control point, so the useful question stops being
 *   "how wrong is it" and becomes "is it improving, and where". That needs the earlier
 *   runs to still exist, with the numbers that describe them.
 */
export interface HeatmapVersion {
  version: string;
  measured_at: string;
  provider: string;
  params: Record<string, number | boolean>;
  tiles_total: number;
  tiles_locked: number;
  match_rate: number;
  /** The RAW measured median — what the pose in force was found to be wrong by. */
  median_error_m: number | null;
  bands: AccuracyBand[];
  /** How the tiles were matched — phase correlation, MI rescue, fine sub-tiles. */
  methods: Record<string, number>;
  /** What this run's geometry did to terrain-height error. Carried through the
   *  history because a re-measure after a new frame can change the geometry, and
   *  comparing two medians without it would compare two different scenes. */
  amplification?: AccuracyAmplification | null;
  /** The zones as they were on THIS run's frame — an older version's photo overlay. */
  zones?: AccuracyZones | null;
  reach?: AccuracyReach | null;
  cloud?: AccuracyCloud | null;
  /**
   * The ortho grid this run produced, including `vmax_m` (what the darkest red means)
   * and `web_bounds` — so an OLDER version can be placed on the satellite pane too.
   */
  grid: Partial<AccuracyGrid>;
  pose: Record<string, unknown>;
  warnings: string[];
  /** Present once this run was corrected: the winning stage and its numbers. */
  corrected: {
    best?: SolutionKey;
    label?: string | null;
    all_m?: number | null;
    p95_m?: number | null;
    worst20_share?: number | null;
    corrected_at?: string | null;
    warnings?: string[];
  } | null;
  gate: { accepted?: boolean | null; reason?: string | null } | null;
  layers: string[];
}

export interface AccuracyState {
  image_id: Uuid;
  measurement: AccuracyMeasurement | null;
  correction: CorrectionReport | null;
  solutions: SolutionsRead | null;
  suggestions: SuggestionsRead | null;
  adoption: Adoption | null;
  base_pose: BasePose;
  solve_options: SolveOptions;
  layers: string[];
  report_available: boolean;
  correction_available: boolean;
  active_run: AccuracyRunStatus | null;
}

export interface PixelQueryAnswer {
  key: SolutionKey;
  lat: number;
  lon: number;
  elevation_m: number;
  base: string | null;
}

export interface PixelQueryRead {
  answers: PixelQueryAnswer[];
  best: SolutionKey;
}

/** A rendered layer's URL — `<img src>`, not JSON. */
export function layerUrl(imageId: Uuid, name: string): string {
  return `${API_BASE_URL}/accuracy/images/${imageId}/layers/${name}`;
}

export function correctionUrl(imageId: Uuid): string {
  return `${API_BASE_URL}/accuracy/images/${imageId}/correction`;
}

export function reportUrl(imageId: Uuid): string {
  return `${API_BASE_URL}/accuracy/images/${imageId}/report`;
}

/** An archived layer's URL — `<img src>`, not JSON. */
export function historyLayerUrl(imageId: Uuid, version: string, name: string): string {
  return `${API_BASE_URL}/accuracy/images/${imageId}/history/${version}/layers/${name}`;
}

export const accuracyApi = {
  /** Every archived measurement, newest first. */
  history: (imageId: Uuid, signal?: AbortSignal): Promise<HeatmapVersion[]> =>
    fetchJson<HeatmapVersion[]>(`/accuracy/images/${imageId}/history`, { signal }),

  measure: (body: MeasureRequest, signal?: AbortSignal): Promise<AccuracyRunStatus> =>
    fetchJson<AccuracyRunStatus>('/accuracy/measure', { method: 'POST', body, signal }),

  correct: (body: CorrectRequest, signal?: AbortSignal): Promise<AccuracyRunStatus> =>
    fetchJson<AccuracyRunStatus>('/accuracy/correct', { method: 'POST', body, signal }),

  suggest: (body: SuggestRequest, signal?: AbortSignal): Promise<AccuracyRunStatus> =>
    fetchJson<AccuracyRunStatus>('/accuracy/suggest', { method: 'POST', body, signal }),

  run: (runId: string, signal?: AbortSignal): Promise<AccuracyRunStatus> =>
    fetchJson<AccuracyRunStatus>(`/accuracy/runs/${runId}`, { signal }),

  state: (imageId: Uuid, signal?: AbortSignal): Promise<AccuracyState> =>
    fetchJson<AccuracyState>(`/accuracy/images/${imageId}`, { signal }),

  /**
   * How the raw pose is solved. ★ Changing it CLEARS the stored measurement and
   * everything built on it — those numbers described a different solve.
   */
  setSolveOptions: (
    imageId: Uuid,
    options: SolveOptions,
    signal?: AbortSignal,
  ): Promise<SolveOptions> =>
    fetchJson<SolveOptions>(`/accuracy/images/${imageId}/solve-options`, {
      method: 'PUT',
      body: options,
      signal,
    }),

  /** Choose the stage this photograph stands on (idempotent — PUT). */
  adopt: (imageId: Uuid, stage: SolutionKey, signal?: AbortSignal): Promise<Adoption> =>
    fetchJson<Adoption>(`/accuracy/images/${imageId}/adoption`, {
      method: 'PUT',
      body: { stage },
      signal,
    }),

  /** Stop standing on a correction — back to the pose the GCPs alone imply. */
  clearAdoption: (imageId: Uuid, signal?: AbortSignal): Promise<void> =>
    fetchJson<void>(`/accuracy/images/${imageId}/adoption`, { method: 'DELETE', signal }),

  query: (
    imageId: Uuid,
    body: { u: number; v: number; target_height_m?: number },
    signal?: AbortSignal,
  ): Promise<PixelQueryRead> =>
    fetchJson<PixelQueryRead>(`/accuracy/images/${imageId}/query`, {
      method: 'POST',
      body,
      signal,
    }),
};
