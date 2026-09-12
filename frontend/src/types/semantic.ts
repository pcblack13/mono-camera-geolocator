/**
 * Semantic features — mirrors `backend/app/schemas/semantic.py` (§6.2).
 *
 * ★★ DEFERRED (SCOPE.md §4): semantic detection (field borders, roads, canals,
 *    trees, greenhouses, buildings, water, crop rows) is an ABC only.
 *    `POST /images/{id}/segment` is registered and documented and returns `501`
 *    with a `feature: "deferred"` marker. The `semantic_features` table IS created
 *    exactly as specified — it simply holds no rows.
 */

import type { IsoDateTime, Uuid } from './common';
import type { GeoJsonGeometry } from './geo';
import type { FeatureDetectorName } from './match';
import type { AnnotationKind } from './annotation';

/** Identical to the `semantic_class` PG enum (§5.3). Parity leg 3 with `ai_engine`. */
export type SemanticClass =
  | 'field_border'
  | 'road'
  | 'irrigation_canal'
  | 'tree'
  | 'tree_line'
  | 'greenhouse'
  | 'building'
  | 'water_body'
  | 'crop_row'
  | 'bare_soil'
  | 'vegetation'
  | 'shadow'
  | 'unknown';

/**
 * ★ `ck_semantic_features_space_xor` binds this to the geometry columns:
 *   `image_pixel` ⇒ `pixel_geom` set and `geo_geom` null; `satellite_geo` ⇒ the
 *   reverse. It is the constraint that makes the invariant mechanical rather than
 *   reviewer-dependent.
 */
export type FeatureSpace = 'image_pixel' | 'satellite_geo';

export type SegmentBackend = 'classical' | 'sam' | 'dinov2';

/** Run-length encoding of a binary mask, row-major. */
export interface MaskRle {
  /** `[height, width]`. */
  size: [number, number];
  counts: number[];
  order: 'row_major';
}

export interface SemanticFeatureRead {
  id: Uuid;
  image_id: Uuid;
  /** Set IFF `space === 'satellite_geo'`. */
  match_result_id: Uuid | null;
  /** Set IFF `detector === 'manual'`. */
  source_annotation_id: Uuid | null;
  class: SemanticClass;
  space: FeatureSpace;
  detector: FeatureDetectorName;
  model_version: string | null;
  /**
   * ★ IMAGE PIXELS, `[x, y]`, y-down, SRID 0 — the same GeoJSON-shaped-but-not-
   *   geographic trap as `AnnotationRead.geometry`. Non-null IFF
   *   `space === 'image_pixel'`.
   */
  pixel_geom: GeoJsonGeometry | null;
  /** EPSG:4326, `[lon, lat]`. Non-null IFF `space === 'satellite_geo'`. */
  geo_geom: GeoJsonGeometry | null;
  /** ★ 0–1 (note: NOT the 0–100 GCP scale). */
  confidence: number;
  area_px: number | null;
  /** ★ TRUE ground metres². */
  area_m2: number | null;
  length_m: number | null;
  attributes: Record<string, unknown>;
  /**
   * ★ Embeddings are NOT stored in Postgres — `pgvector` is not in the mandated
   *   stack and DINOv2 descriptors are a poor fit for a row store. They are written
   *   as `.npy`/FAISS artifacts and referenced BY PATH here.
   */
  embedding_meta: Record<string, unknown> | null;
  created_at: IsoDateTime;
}

export interface SemanticFeatureSummary {
  id: Uuid;
  image_id: Uuid;
  class: SemanticClass;
  space: FeatureSpace;
  detector: FeatureDetectorName;
  confidence: number;
  area_px: number | null;
  area_m2: number | null;
}

/** A user click that seeds an interactive segmentation (SAM's prompt model). */
export interface SegmentPoint {
  x: number;
  y: number;
  /** `true` = "include this", `false` = "exclude this". */
  is_positive: boolean;
}

/** ★ DEFERRED — `POST /images/{image_id}/segment` returns `501` (SCOPE.md §4). */
export interface SegmentRequest {
  backend?: SegmentBackend;
  classes?: SemanticClass[] | null;
  space?: FeatureSpace;
  match_result_id?: Uuid | null;
  points?: SegmentPoint[] | null;
  min_confidence?: number;
  /** Convert the detected feature into an annotation of this kind on accept. */
  as_annotation_kind?: AnnotationKind | null;
}

export interface SemanticFilters {
  class?: SemanticClass | SemanticClass[];
  space?: FeatureSpace;
  detector?: FeatureDetectorName;
  confidence__gte?: number;
  match_result_id?: Uuid;
  sort?: string;
  limit?: number;
  offset?: number;
}
