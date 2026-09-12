/**
 * Exports — mirrors `backend/app/schemas/export.py` (§6.2), field for field.
 *
 * ★ SCOPE.md §3: exports are BUILT, in full — CSV, GeoJSON, Shapefile, KML, PDF.
 * ★ SCOPE.md §5: "Uncommitted correspondences must never appear in the GCP table
 *   or an export." The `filter` below is what the server persists to make that
 *   auditable.
 */

import type { CoordinateFormat, IsoDateTime, Uuid, WarningItem } from './common';
import type { GcpSource } from './gcp';
import type { JobStatus } from './job';

export type ExportFormat = 'csv' | 'geojson' | 'shapefile' | 'kml' | 'kmz' | 'pdf' | 'gpkg' | 'dxf';

export interface CsvExportOptions {
  delimiter?: ',' | ';' | '\t';
  include_header?: boolean;
  coordinate_format?: CoordinateFormat;
  /** ★ Full precision is ALWAYS available in the export — §8.7's truncation is a
   *  DISPLAY policy, not a data policy. Nothing is lost. */
  decimals?: number;
}

export interface ShapefileExportOptions {
  /** ★ 1024..32767. Reprojection happens server-side in `gis.crs`. */
  target_srid?: number;
  encoding?: string;
}

export interface KmlExportOptions {
  include_photo_overlay?: boolean;
  icon_scale?: number;
}

export interface DxfExportOptions {
  target_srid?: number;
  layer_name?: string;
}

export interface PdfExportOptions {
  include_map?: boolean;
  include_photo?: boolean;
  include_accuracy_table?: boolean;
  title?: string | null;
  author?: string | null;
  notes?: string | null;
}

export interface ExportOptions {
  csv?: CsvExportOptions;
  shapefile?: ShapefileExportOptions;
  kml?: KmlExportOptions;
  dxf?: DxfExportOptions;
  pdf?: PdfExportOptions;
  /** ★ 1024..32767, default 4326. */
  target_srid?: number;
}

/**
 * ★ Persisted with the export so "regenerate this export" is reproducible — and so
 *   a stale export whose `gcp_count` disagrees with today's GCP count is
 *   DETECTABLE, which is exactly the audit question a surveyor asks: *"is the file
 *   I sent the client still current?"*
 */
export interface ExportFilter {
  gcp_ids?: Uuid[] | null;
  match_result_id?: Uuid | null;
  source?: GcpSource | null;
  confidence__gte?: number | null;
  manually_adjusted?: boolean | null;
  include_stale?: boolean;
  only_included_in_export?: boolean;
}

export interface ExportRequest {
  format: ExportFormat;
  /** `null` ⇒ a whole-project export. */
  image_id?: Uuid | null;
  filter?: ExportFilter;
  options?: ExportOptions;
  /**
   * ★ Required when the set contains low-confidence points (§8.5.3). Every output
   *   format carries the confidence column plus a `low_confidence: true` flag, and
   *   the PDF report gets a full-width warning block on page 1.
   */
  acknowledge_low_confidence?: boolean;
}

export interface ExportRead {
  id: Uuid;
  project_id: Uuid;
  image_id: Uuid | null;
  format: ExportFormat;
  /** Reuses `JobStatus` values — `exports.status` is the `job_status` PG enum. */
  status: JobStatus;
  cancel_requested: boolean;
  /** `null` until `succeeded`. `storage_path` itself is never serialised. */
  download_url: string | null;
  filename: string | null;
  size_bytes: number | null;
  checksum_sha256: string | null;
  gcp_count: number | null;
  target_srid: number;
  options: ExportOptions;
  filter: ExportFilter;
  warnings: WarningItem[];
  error_message: string | null;
  requested_by: string | null;
  /** After this, the download is `410 EXPORT_EXPIRED` — gone, not missing. */
  expires_at: IsoDateTime | null;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

export interface ExportSummary {
  id: Uuid;
  format: ExportFormat;
  status: JobStatus;
  filename: string | null;
  size_bytes: number | null;
  gcp_count: number | null;
  download_url: string | null;
  expires_at: IsoDateTime | null;
  created_at: IsoDateTime;
}

export interface ExportFilters {
  format?: ExportFormat | ExportFormat[];
  status?: JobStatus | JobStatus[];
  image_id?: Uuid;
  sort?: string;
  limit?: number;
  offset?: number;
}
