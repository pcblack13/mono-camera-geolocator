/**
 * Uploaded imagery — mirrors `backend/app/schemas/image.py` (§6.2), field for field.
 */

import type { IsoDateTime, Uuid, WarningItem } from './common';
import type { JobRead } from './job';

export type ImageStatus = 'uploaded' | 'processing' | 'ready' | 'failed';

export type VariantName = 'thumbnail' | 'preview' | 'full' | 'original';

/**
 * ★ §12 C-36 / §8.6. THE frontend's load-bearing requirement.
 *
 * Without `original_width` the client cannot compute `D = width / original_width`
 * and the ENTIRE coordinate model of §8.6 collapses. The server ALWAYS sends both,
 * non-null, on every variant.
 *
 * The failure this prevents: the naive viewer reads `stage.getPointerPosition()`,
 * divides by scale, subtracts pan, and stores DISPLAY pixels. That silently
 * disagrees with the backend (which computed features on the ORIGINAL) and every
 * annotation jumps by `D₁/D₂` when a variant swaps. It survives development
 * because `D ≈ 1` on small test images and detonates on the first real 5000px
 * upload.
 */
export interface ImageVariant {
  name: VariantName;
  url: string;
  /** This variant's raster width. */
  width: number;
  height: number;
  /** ★ ALWAYS the full-resolution width. Never null. */
  original_width: number;
  /** ★ ALWAYS the full-resolution height. Never null. */
  original_height: number;
  /** ★ `= width / original_width`. THE `D` of §8.6. Server-computed. */
  display_scale: number;
  size_bytes: number | null;
}

export interface GpsMetadata {
  lat: number;
  lon: number;
  altitude_m: number | null;
  direction_deg: number | null;
  /** Horizontal positional error, metres. */
  hpe_m: number | null;
  source: 'exif' | 'manual';
}

export interface CameraMetadata {
  make: string | null;
  model: string | null;
  lens_model: string | null;
  focal_length_mm: number | null;
  focal_length_35mm: number | null;
  sensor_width_mm: number | null;
  f_number: number | null;
}

export interface ImageUrls {
  /** ★ `storage_path` is NEVER serialised — it is a server-controlled path. Clients get this. */
  file: string;
  thumbnail: string | null;
  preview: string | null;
  metadata: string;
}

export interface ImageCounts {
  annotations: number;
  gcps: number;
  match_jobs: number;
}

export interface LatestMatchRef {
  match_job_id: Uuid;
  match_result_id: Uuid | null;
  status: string;
  overall_confidence: number | null;
  created_at: IsoDateTime;
}

export interface ImageRead {
  id: Uuid;
  project_id: Uuid;
  filename: string;
  /** ★ Determined by MAGIC BYTES, never by the client. The part header and the
   *  filename extension are both untrusted and recorded only as advisory metadata. */
  mime_type: string;
  size_bytes: number;
  checksum_sha256: string;
  /** ★ POST orientation normalisation (see the note on `ImageMetadataRead.exif`). */
  width: number;
  height: number;
  band_count: number;
  status: ImageStatus;
  /**
   * ★ `true` IFF GDAL reports a non-null projection AND a geotransform that is NOT
   *   the identity `(0,1,0,0,0,1)`. That second condition matters — GDAL hands back
   *   the identity transform for plain TIFFs, and a naive `if (gt)` marks every
   *   scanned TIFF as georeferenced at the equator.
   *
   * ★ SCOPE.md §3: a georeferenced upload short-circuits to exact GCPs with no
   *   matching at all.
   */
  is_geotiff: boolean;
  /** `null` when the photograph carries no GPS at all. */
  gps: GpsMetadata | null;
  camera: CameraMetadata;
  captured_at: IsoDateTime | null;
  notes: string | null;
  metadata: Record<string, unknown>;
  /**
   * ★ Provenance when this image was CAPTURED FROM A VIDEO frame (§ video feature).
   *   `null` for a normally-uploaded photograph. `source_video_time_s` is the second
   *   in the source video the frame was grabbed at.
   */
  source_video_id: Uuid | null;
  source_video_time_s: number | null;
  urls: ImageUrls;
  /** ★ REQUIRED. See `ImageVariant`. */
  variants: ImageVariant[];
  counts: ImageCounts;
  latest_match: LatestMatchRef | null;
  warnings: WarningItem[];
  uploaded_at: IsoDateTime;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
  deleted_at: IsoDateTime | null;
}

/** List projection. Deliberately omits `variants`, `metadata` and `exif`. */
export interface ImageSummary {
  id: Uuid;
  project_id: Uuid;
  filename: string;
  status: ImageStatus;
  width: number;
  height: number;
  size_bytes: number;
  is_geotiff: boolean;
  thumbnail_url: string | null;
  annotation_count: number;
  gcp_count: number;
  /**
   * ★ Provenance for a frame captured from a video — mirrors `ImageRead`. OPTIONAL on
   *   the summary: the backend may omit it from the list projection, and the UI treats
   *   absent and `null` identically (no "from video" chip). Never distinguishes them.
   */
  source_video_id?: Uuid | null;
  source_video_time_s?: number | null;
  captured_at: IsoDateTime | null;
  uploaded_at: IsoDateTime;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

export interface FileMetadata {
  filename: string;
  mime_type: string;
  size_bytes: number;
  checksum_sha256: string;
}

export interface RasterMetadata {
  width: number;
  height: number;
  band_count: number;
  dtype: string;
  color_interpretation: string[];
  has_alpha: boolean;
}

export interface GeoTiffMetadata {
  crs: string | null;
  /** GDAL order — see `GeoTransform` in `geo.ts`. */
  geotransform: number[] | null;
  /** `[min_lon, min_lat, max_lon, max_lat]` in EPSG:4326. */
  bounds: [number, number, number, number] | null;
  gsd_m: number | null;
  nodata: number | null;
  overview_count: number;
}

export interface CaptureMetadata {
  captured_at: IsoDateTime | null;
  /** ★ The ORIGINAL EXIF orientation tag, preserved verbatim. */
  orientation: number | null;
  orientation_normalized: boolean;
}

export interface DerivedMetadata {
  variants: ImageVariant[];
  histogram_url: string | null;
}

/**
 * `GET /images/{id}/metadata`.
 *
 * ★ `exif` — the verbatim blob, hundreds of tags including embedded thumbnails —
 *   is NOT in `ImageRead`. It lives here and only here.
 *
 * ★ EXIF orientation is normalised at ingest and `ImageRead.width`/`height` are
 *   stored POST-rotation. If they were not, Konva, OpenCV `imread`, GDAL and the
 *   PDF exporter would each independently re-apply the tag — and they do not agree
 *   with each other — so annotation pixel coordinates would mean different things
 *   in different components, corrupting GCP output. The original block is preserved
 *   here (including the original `Orientation`), so nothing is lost.
 */
export interface ImageMetadataRead {
  id: Uuid;
  image_id: Uuid;
  file: FileMetadata;
  raster: RasterMetadata;
  camera: CameraMetadata;
  gps: GpsMetadata | null;
  capture: CaptureMetadata;
  geotiff: GeoTiffMetadata | null;
  derived: DerivedMetadata;
  /** The verbatim EXIF block. */
  exif: Record<string, unknown>;
  metadata: Record<string, unknown>;
  warnings: WarningItem[];
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

/** PATCH — UNSET semantics: omit a key to leave it untouched (§6.1). */
export interface ImageUpdate {
  filename?: string | null | undefined;
  notes?: string | null | undefined;
  captured_at?: IsoDateTime | null | undefined;
  metadata?: Record<string, unknown> | null | undefined;
}

/** Query params for `GET /projects/{id}/images`. */
export interface ImageFilters {
  status?: ImageStatus | ImageStatus[];
  is_geotiff?: boolean;
  q?: string;
  include_deleted?: boolean;
  sort?: string;
  limit?: number;
  offset?: number;
}

/**
 * `202` from `POST /images` when the upload exceeds `LE_ASYNC_INGEST_THRESHOLD_BYTES`
 * (50 MB): the row is inserted `status='processing'` and an `ingest` job is enqueued.
 */
export interface ImageUploadAccepted {
  image: ImageRead;
  job: JobRead;
}
