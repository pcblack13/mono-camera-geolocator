/**
 * KML/KMZ GCP import — the wire types for `/projects/{id}/gcps/import/kml/*`.
 *
 * ★ THE CASING LAW (§8.1 / L9): every field here is snake_case because every field
 *   here is a wire field. Nothing is renamed on the way in.
 *
 * ★ **An import can only MOVE an existing GCP.** `gcps.pixel_x`/`pixel_y` are NOT NULL —
 *   a GCP is a pairing between an image pixel and a ground coordinate, and a placemark
 *   carries only the ground half. That is why there is no "create" variant of
 *   {@link KmlImportMatch} and why {@link KmlImportUnmatched} is a report rather than an
 *   offer. To add a point, pair it in the workspace against the photo it belongs to.
 *
 * ★ **Preview and apply are two calls, and the split is the safety property.** The
 *   preview writes nothing; it is where the surveyor sees which points move and how far.
 *   `expected_match_count` carries their confirmation back so a file that changed between
 *   the two calls is refused (409 `IMPORT_FILE_CHANGED`) rather than silently applied.
 */

import type { Uuid } from './common';

/** How a placemark was tied to a GCP. `gcp_id` is an exact round trip, not a guess. */
export type KmlMatchStrategy = 'gcp_id' | 'code' | 'name';

/** One placemark that resolved to an existing GCP, with the movement it implies. */
export interface KmlImportMatch {
  gcp_id: Uuid;
  placemark_name: string | null;
  code: string | null;
  matched_by: KmlMatchStrategy;

  current_lat: number;
  current_lon: number;
  new_lat: number;
  new_lon: number;

  /** Ground distance between the two, TRUE metres. **The number to read first.** */
  offset_m: number;
  current_total_ce90_m: number | null;
  /**
   * The move is larger than the GCP's own error bar.
   *
   * ★ NOT an error and NOT blocked — refining a point past its stated accuracy is a
   * legitimate reason to import. Flagged so the surveyor confirms it deliberately.
   */
  exceeds_accuracy: boolean;

  current_elevation_m: number | null;
  /** ★ `null` when the file carried no altitude — never 0. Absent ≠ sea level. */
  new_elevation_m: number | null;
  /** Why an altitude present in the file will not be applied (e.g. `clampToGround`). */
  elevation_note: string | null;
}

/** A placemark that parsed but ties to no GCP here. ★ Never becomes a new GCP. */
export interface KmlImportUnmatched {
  placemark_name: string | null;
  lat: number;
  lon: number;
  elevation_m: number | null;
  reason: string;
}

/** A placemark the reader could not turn into a point at all. */
export interface KmlImportSkipped {
  placemark_name: string | null;
  reason: string;
}

/**
 * What an apply would do. **Writes nothing.**
 *
 * ★ Every placemark lands in exactly one of `matched` / `unmatched` / `skipped`, and
 *   every GCP the file did not mention is counted in `untouched_gcp_count` — so the
 *   totals account for the whole file and the whole project. A row cannot go missing
 *   between them unremarked, which is the property the dialog renders.
 */
export interface KmlImportPreview {
  filename: string | null;
  document_name: string | null;
  matched: KmlImportMatch[];
  unmatched: KmlImportUnmatched[];
  skipped: KmlImportSkipped[];
  untouched_gcp_count: number;
  /** Matches above the 1 mm no-op floor. The rest resolve to where they already are. */
  moved_count: number;
  exceeds_accuracy_count: number;
}

/** The confirm half. Sent as form fields beside the same file. */
export interface KmlImportApplyForm {
  file: File;
  /** The `matched.length` the surveyor confirmed. Mismatch ⇒ 409, never a silent apply. */
  expected_match_count?: number;
  /**
   * Write altitudes the file carries.
   *
   * ★ Recorded as `elevation_source: 'manual'` with a **NULL** vertical CE90: the
   * operator asserted the height and this system cannot say how wrong it is.
   */
  apply_elevation?: boolean;
  note?: string;
}

/** What actually changed. */
export interface KmlImportApplyResponse {
  adjusted_gcp_ids: Uuid[];
  elevation_written_count: number;
  /** Matches that resolved to the same position. A re-apply reports everything here. */
  unchanged_count: number;
  unmatched_count: number;
  skipped_count: number;
}
