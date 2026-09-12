/**
 * Projects — mirrors `backend/app/schemas/project.py` (§6.2), field for field.
 */

import type { AlbumRef } from './album';
import type { IsoDateTime, Uuid } from './common';
import type { GeoJsonPolygon, ProviderId } from './geo';
import type { EstimatorName, ExtractorName, MatcherName } from './match';

/** The self-contained folder written by `POST /projects/{id}/export-folder`. */
export interface ProjectExportResult {
  folder: string;
  path: string;
  root: string;
  images: number;
  gcps: number;
  gcp_solves: number;
  luts: number;
  videos: number;
  has_dem: boolean;
  missing: string[];
}

export interface ProjectCounts {
  images: number;
  annotations: number;
  gcps: number;
  match_jobs: number;
  exports: number;
}

export interface ProjectRead {
  id: Uuid;
  /** 1–200, non-blank after strip. */
  name: string;
  description: string | null;
  /** RFC 7946, EPSG:4326, `[lon, lat]`, ≤ 1000 vertices, `ST_IsValid`, area ≤ 10 000 km². */
  aoi: GeoJsonPolygon | null;
  aoi_area_km2: number | null;
  /** ★ Default is the KEYLESS provider (L2). `docker compose up` with an empty
   *  `.env` yields a working satellite search. */
  default_provider: ProviderId;
  default_extractor: ExtractorName;
  default_matcher: MatcherName;
  default_estimator: EstimatorName;
  /** 10..50000 */
  default_search_radius_m: number;
  /** 10..21 */
  default_search_zoom: number;
  /** ≤ 20 tags, each ≤ 50 chars. */
  tags: string[];
  /** ≤ 16 KB serialised. */
  metadata: Record<string, unknown>;
  current_revision_seq: number;
  counts: ProjectCounts | null;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
  deleted_at: IsoDateTime | null;
}

/**
 * ★ Deliberately OMITS `aoi` and `counts`: a 1000-vertex polygon × 50 rows is a
 *   ~2 MB list response for a screen that renders names, and the full rollup costs
 *   5 aggregate subqueries per row. `image_count` alone is kept (one cheap
 *   correlated count).
 */
export interface ProjectSummary {
  id: Uuid;
  name: string;
  description: string | null;
  tags: string[];
  aoi_area_km2: number | null;
  image_count: number;
  /**
   * ★ EMBEDDED — every album this project belongs to (many-to-many). It is served
   *   with the row precisely so a project card can render its chips without N extra
   *   requests; it is the reason `AlbumRef` is thin.
   */
  albums: AlbumRef[];
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

export interface ProjectCreate {
  name: string;
  description?: string | null;
  aoi?: GeoJsonPolygon | null;
  default_provider?: ProviderId;
  default_extractor?: ExtractorName;
  default_matcher?: MatcherName;
  default_estimator?: EstimatorName;
  default_search_radius_m?: number;
  default_search_zoom?: number;
  tags?: string[];
  metadata?: Record<string, unknown>;
}

/**
 * PATCH — ★ UNSET-SENTINEL SEMANTICS (§6.1). This is the ONE place absent and null
 * differ:
 *   - `{"aoi": null}` **CLEARS** the AOI.
 *   - `{}` leaves it untouched and is a `400 EMPTY_PATCH`.
 *
 * Without the sentinel, nullable fields are un-clearable through PATCH — a real,
 * common bug. The client OMITS the key (via `JSON.stringify`, which drops
 * `undefined`) for "leave untouched", and never sends `null` for it.
 */
export interface ProjectUpdate {
  name?: string | undefined;
  description?: string | null | undefined;
  aoi?: GeoJsonPolygon | null | undefined;
  default_provider?: ProviderId | undefined;
  default_extractor?: ExtractorName | undefined;
  default_matcher?: MatcherName | undefined;
  default_estimator?: EstimatorName | undefined;
  default_search_radius_m?: number | undefined;
  default_search_zoom?: number | undefined;
  tags?: string[] | undefined;
  metadata?: Record<string, unknown> | undefined;
}

export interface ProjectFilters {
  q?: string;
  tags?: string[];
  /**
   * ★ Restrict to one album's members — the server-side equivalent of
   *   `GET /albums/{id}/projects`. It travels in the query, therefore in the query
   *   key, so each album's filtered list caches independently of "All albums".
   */
  album_id?: string;
  include_deleted?: boolean;
  /** `bbox=minlon,minlat,maxlon,maxlat`. Antimeridian-crossing → `422`. */
  bbox?: string;
  sort?: string;
  limit?: number;
  offset?: number;
}

export type { JobFilters } from './job';
