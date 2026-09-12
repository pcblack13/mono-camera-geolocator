/**
 * Matching — mirrors `backend/app/schemas/matching.py` (§6.2), field for field.
 *
 * ★★ SCOPE.md §1: THE AUTOMATIC MATCHING ENGINE IS DEFERRED. These types are
 *    complete and honest, and `POST /images/{id}/match` is **registered and
 *    documented** but returns `501 Not Implemented` with the uniform error envelope
 *    and a `feature: "deferred"` marker (SCOPE.md §4 rule 3). It must not 404 — the
 *    feature is planned, not absent — and must not fake a result.
 *
 *    The types stay because the seam must be real, not decorative: re-enabling the
 *    engine must require zero changes outside `ai_engine/` plus flipping the
 *    endpoints from 501 to live (SCOPE.md §7). `MatchResultRead` is also the shape
 *    a GeoTIFF short-circuit produces, which IS built (SCOPE.md §3).
 */

import type { IsoDateTime, Uuid, WarningItem } from './common';
import type { BBox, GeoJsonPolygon, GeoTransform, Homography, LatLon, ProviderId } from './geo';

// ─────────────────────────────────────────────────────────────────────────────
// Component names — identical to the PG enums (§5.3)
// ─────────────────────────────────────────────────────────────────────────────

export type ExtractorName = 'sift' | 'orb' | 'akaze' | 'brisk' | 'asift' | 'superpoint' | 'dinov2';

export type MatcherName = 'bf' | 'flann' | 'superglue' | 'lightglue' | 'loftr';

/**
 * ★ `estimator` ALWAYS means the robust-fit METHOD (`RansacConfig.method` /
 *   `HomographyMethod`), never a component registry key, and it never reaches
 *   `Registry.resolve` (§6.1). The registry key is `AiEngineConfig.estimator_backend`
 *   and is not exposed.
 */
export type EstimatorName = 'ransac' | 'usac_magsac' | 'lmeds' | 'prosac' | 'usac_accurate' | 'lsq';

export type FeatureDetectorName = 'classical_cv' | 'sam' | 'dinov2' | 'manual' | 'other';

/**
 * A property of the QUERY IMAGE, not of a window (§4).
 *
 * ★ SCOPE.md §2 is the reason the engine is deferred and this enum is the reason
 *   stated compactly: a planar homography is only strictly valid for a planar scene
 *   or pure rotation, and `oblique_raw` / `ground_horizon` violate both.
 */
export type ViewRegime =
  | 'nadir'
  | 'oblique_rectifiable'
  | 'oblique_raw'
  | 'ground_horizon'
  | 'unknown';

/** Advisory; the UI badges them. */
export type QualityFlag =
  | 'low_inliers'
  | 'low_inlier_ratio'
  | 'degenerate_homography'
  | 'reflected_homography'
  | 'high_reproj_error'
  | 'low_semantic_evidence'
  | 'geotiff_georeference_disagreement'
  | 'few_landmarks'
  | 'zoom_clamped';

// ─────────────────────────────────────────────────────────────────────────────
// Request
// ─────────────────────────────────────────────────────────────────────────────

/**
 * ★ Resolution order is normative and server-side (§6.2): `aoi` → `center + radius_m`
 *   → `use_image_gps` + EXIF GPS → `use_image_gps` + GeoTIFF bounds → project `aoi`
 *   → `422 SEARCH_HINT_REQUIRED`.
 *
 * ★ NEVER a global search. A worldwide SIFT search is not a slow feature; it is a
 *   nonexistent one — 2¹⁸² ≈ 6.87×10¹⁰ tiles ≈ 1 PB per photo. There is no budget
 *   in which it terminates.
 */
export interface SearchHint {
  center?: LatLon | null;
  /** ★ 50..50000 → else 422. Above 50 km the tile count is absurd at any useful zoom. */
  radius_m?: number;
  /** 1–3 entries, each within the provider's min..max → else `422 ZOOM_OUT_OF_RANGE`. */
  zoom_levels?: number[] | null;
  use_image_gps?: boolean;
  /** Valid, ≤ 1000 vertices, area ≤ 2500 km². */
  aoi?: GeoJsonPolygon | null;
}

export interface MatchOptions {
  /** 1..1024 */
  max_tiles?: number;
  max_candidates?: number;
  /** ★ 0..100. Candidates below are dropped. */
  min_confidence?: number;
  ratio_test?: number;
  cross_check?: boolean;
  ransac_threshold_px?: number;
  ransac_max_iters?: number;
  ransac_confidence?: number;
  min_inliers?: number;
  max_keypoints?: number;
  window_size_px?: number;
  /** ★ 0.5 — the 512px footprint guarantee (§4.19). */
  overlap_ratio?: number;
  /** ★ Pins RANSAC's RNG → bit-reproducible. */
  seed?: number | null;
  /**
   * ★ 30 .. `LE_CELERY_TASK_SOFT_TIME_LIMIT` (default 600). Over the cap →
   *   `422 TIMEOUT_EXCEEDS_LIMIT` with `details.max_timeout_s`. The API does not
   *   accept a promise the worker cannot keep.
   */
  timeout_s?: number;
}

/** Keys fixed, values ≥ 0, MUST sum to 1.0 ± 1e-6 → else 422. */
export interface ScoreWeights {
  feature: number;
  geometric: number;
  landmark: number;
  semantic: number;
}

/**
 * ★ DEFERRED (SCOPE.md §1). `POST /images/{image_id}/match` returns `501`.
 *
 * ★ Any enum value is accepted here, INCLUDING unavailable ones: an explicitly
 *   requested missing weight (`matcher: 'superglue'`) is a `202` + fallback +
 *   `WarningItem`, never an error (L11). Only an explicitly requested unconfigured
 *   PROVIDER is refusable (`503`) — imagery changes the answer's provenance, a
 *   matcher changes only its accuracy.
 */
export interface MatchRequest {
  search_hint?: SearchHint;
  /** `null` ⇒ the project default. */
  provider?: ProviderId | null;
  extractor?: ExtractorName | null;
  matcher?: MatcherName | null;
  estimator?: EstimatorName | null;
  use_semantic?: boolean;
  /** Pins the annotation set matched against. */
  annotation_revision_seq?: number | null;
  /** Subset to match against. */
  annotation_ids?: Uuid[] | null;
  options?: MatchOptions;
  score_weights?: ScoreWeights;
}

// ─────────────────────────────────────────────────────────────────────────────
// Result
// ─────────────────────────────────────────────────────────────────────────────

export interface MatchTileRef {
  z: number;
  x: number;
  y: number;
  quadkey: string | null;
}

export interface MatchStats {
  query_keypoints: number;
  train_keypoints: number;
  raw_matches: number;
  good_matches: number;
  inlier_count: number;
  inlier_ratio: number;
  reproj_error_px: number | null;
  tiles_fetched: number;
  placeholder_fraction: number;
  elapsed_ms: number;
}

/**
 * ★ Score renormalisation is EXPLICIT. With no deep models,
 *   `semantic_similarity_score` is `null` and its weight is redistributed over the
 *   remaining three. Without `renormalized: true`, an 87.3 on a weightless box and
 *   an 87.3 on a GPU box would be quietly incomparable. Stating it makes the
 *   number's meaning inspectable.
 */
export interface MatchScores {
  feature_similarity_score: number | null;
  geometric_consistency_score: number | null;
  landmark_consistency_score: number | null;
  semantic_similarity_score: number | null;
  /** ★ 0–100. */
  overall_confidence: number;
  weights_used: ScoreWeights;
  renormalized: boolean;
  renormalization_note: string | null;
  calibrated: boolean;
  calibration_id: string;
}

export interface MatchResultRead {
  id: Uuid;
  match_job_id: Uuid;
  image_id: Uuid;
  rank: number;
  is_selected: boolean;
  /** A recompute writes a NEW row rather than mutating the old one — keeping the
   *  RESTRICT provenance chain intact and the original answer inspectable forever. */
  parent_match_result_id: Uuid | null;

  provider: ProviderId;
  tile: MatchTileRef | null;
  tile_bounds: GeoJsonPolygon;
  center: LatLon;
  satellite_image_url: string | null;
  satellite_checksum: string | null;
  satellite_size_px: [number, number] | null;
  /** ★ TRUE ground metres per pixel, cos(φ)-corrected. */
  gsd_m: number | null;
  georef_ce90_m: number | null;
  /** `true` ⇒ survey-grade georeferencing (i.e. `local_orthophoto`). */
  is_authoritative: boolean;

  /** 9 floats, ROW-MAJOR. `null` for a manual/GeoTIFF result — there is no homography. */
  homography: Homography | null;
  /** 6 floats, GDAL order. */
  sat_geotransform: GeoTransform | null;
  /** ★ AUTHORITATIVE and NOT always 3857 — a UTM code for `local_orthophoto`. */
  sat_geotransform_srid: number;
  /**
   * ★ Ships in the payload, deliberately. The image-pixel → world chain is two
   *   composed transforms with two different memory-layout conventions, and getting
   *   either backwards yields coordinates that look plausible and are wrong by
   *   hundreds of metres. A one-line statement of the chain costs 200 bytes and
   *   prevents the single most expensive mistake a consumer of this API can make.
   */
  transform_note: string;

  imagery_captured_at: IsoDateTime | null;
  /** ★ NOT optional — a ToS obligation. */
  attribution: string;
  terms_url: string | null;

  stats: MatchStats;
  scores: MatchScores;
  view_regime: ViewRegime;
  degeneracy_gate: number;
  degeneracy_report: Record<string, unknown>;

  /**
   * ★ `degraded`/`warnings` live at the RESULT level, not just the job level.
   *   Results outlive jobs in the UI; a candidate reviewed a week later must still
   *   say it came from the fallback path.
   */
  degraded: boolean;
  degradation_reason: string | null;
  warnings: WarningItem[];

  gcp_count: number;
  /** ★ `/api/v1/match-results/{id}/gcps` — endpoint 64. */
  gcps_url: string;
  quality_flags: QualityFlag[];
  created_at: IsoDateTime;
}

export interface MatchResultSummary {
  id: Uuid;
  match_job_id: Uuid;
  image_id: Uuid;
  rank: number;
  is_selected: boolean;
  provider: ProviderId;
  center: LatLon;
  overall_confidence: number;
  gcp_count: number;
  degraded: boolean;
  quality_flags: QualityFlag[];
  created_at: IsoDateTime;
}

export interface MatchResultSelectRequest {
  confirm: boolean;
}

export interface MatchFilters {
  match_job_id?: Uuid;
  is_selected?: boolean;
  confidence__gte?: number;
  sort?: string;
  limit?: number;
  offset?: number;
}

export interface SatelliteImageParams {
  width?: number;
  height?: number;
  format?: 'png' | 'jpeg';
}

/** BBox re-exported for consumers that only import this module. */
export type { BBox };
