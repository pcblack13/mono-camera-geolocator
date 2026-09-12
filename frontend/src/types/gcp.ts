/**
 * Ground Control Points — ★ THE DELIVERABLE.
 *
 * Mirrors `backend/app/schemas/gcp.py` (§6.2 / §8.2) field for field, plus the
 * `source` discriminator mandated by `SCOPE.md §5`.
 *
 * ★ A GCP is a survey coordinate someone may dig, build, or file against (L12).
 *   Every honesty mechanism in this file exists for that sentence.
 */

import type { IsoDateTime, Uuid } from './common';
import type { PixelXY } from './geo';
import type { EstimatorName } from './match';

// ─────────────────────────────────────────────────────────────────────────────
// Provenance — SCOPE.md §5
// ─────────────────────────────────────────────────────────────────────────────

/**
 * ★ SCOPE.md §5: "The GCP records `source = 'manual'` so an automatic GCP can never
 *   be confused with an observed one downstream or in an export."
 *
 * - `manual`    — the surveyor marked the landmark in the photo and clicked the
 *                 same physical spot on the satellite map. **The coordinate is a
 *                 DIRECT OBSERVATION, not an inference.** Every GCP in this build.
 * - `automatic` — derived by the matching engine through an estimated homography.
 *                 **DEFERRED in this build** (SCOPE.md §1); no row will carry it.
 *                 The member exists so the seam is real: re-enabling the engine
 *                 must require zero changes outside `ai_engine/` (SCOPE.md §7).
 */
export type GcpSource = 'manual' | 'automatic';

/**
 * ★ SCOPE.md §5: "`confidence` in manual mode is a SURVEYOR-DECLARED value (a
 *   deliberate 1–5 / low-med-high judgement), NEVER a computed number."
 *
 * A discrete ordinal, not a continuum, because the surveyor's actual judgement is
 * discrete — "am I sure this is the same tank top?" has about five honest answers,
 * not a hundred. Offering a 0–100 slider for a human judgement would manufacture a
 * precision the human never claimed, which is the same failure `§8.7`'s decimal
 * truncation exists to prevent, one field over.
 *
 * `5` is the most certain. See `SURVEYOR_CONFIDENCE_SCALE` in `theme/confidence.ts`
 * for the labels, the colours and the numeric mapping.
 */
export type SurveyorConfidence = 1 | 2 | 3 | 4 | 5;

/**
 * ★ The COMPUTED band, derived from `GcpRead.confidence` (0–100) by
 *   `lib/confidence.ts`: `high ≥ 80` · `moderate ≥ 60` · `low ≥ 40` ·
 *   `unreliable < 40` (§8.7).
 *
 * ★ 50-frontend's `CONFIDENCE_THRESHOLDS = {high: 0.85, moderate: 0.65, low: 0.40}`
 *   is **VOID** (§8.5) — it was a 0–1 scale against a 0–100 value, which silently
 *   enabled the compare-mode gate on essentially EVERY match, including rejected
 *   ones. The thresholds are 80/60/40.
 */
export type ConfidenceBand = 'high' | 'moderate' | 'low' | 'unreliable';

export type GcpStaleReason =
  | 'landmark_moved'
  | 'landmark_deleted'
  | 'homography_superseded'
  | 'annotations_restored';

// ─────────────────────────────────────────────────────────────────────────────
// Accuracy (§4.20)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * ★ TWO ACCURACIES, ALWAYS. Reporting only the relative figure would tell a
 *   surveyor they have 0.3 m GCPs when they have 3 m GCPs.
 *
 * ★ EVERY NUMBER HERE IS CE90 — a 2-D 90% radius (`2.146σ`). No field mixes levels;
 *   `confidence_level` ships on the wire so it cannot be misread.
 *
 * ★ SCOPE.md §5: in manual mode these come from the imagery's ground-sample-distance
 *   and the click precision at the map's zoom level — **a real, defensible number**
 *   — not from a match score. There is no homography, so there is nothing to
 *   propagate.
 */
export interface GcpAccuracy {
  confidence_level: 'ce90';
  /** Our own fit / click, CE90, TRUE ground metres. */
  relative_ce90_m: number;
  /** The imagery provider's absolute georeferencing error. Always knowable. */
  georef_ce90_m: number;
  /** ★ `sqrt(relative² + georef²)`. **THE headline number.** */
  total_ce90_m: number;
  /** The error ellipse — null only for a legacy row. */
  semi_major_ce90_m: number | null;
  semi_minor_ce90_m: number | null;
  /** Major axis, 0 = North, clockwise. */
  azimuth_deg: number | null;
  /**
   * ★ Rendered as prose in the inspector — "your accuracy is limited by the
   *   basemap, not the match". It is the field that tells a surveyor what to FIX.
   */
  dominant_term: 'match' | 'georeference' | 'landmark_click' | 'rectification';
}

// ─────────────────────────────────────────────────────────────────────────────
// The GCP
// ─────────────────────────────────────────────────────────────────────────────

/** The algorithm's answer, kept forever. Written once and never again. */
export interface GcpOriginal {
  lat: number;
  lon: number;
  satellite_px: PixelXY;
  confidence: number;
}

export interface GcpLandmarkRef {
  id: Uuid;
  label: string | null;
  kind: string;
  pixel_x: number;
  pixel_y: number;
}

export interface GcpRead {
  id: Uuid;
  image_id: Uuid;
  match_result_id: Uuid;
  landmark_id: Uuid | null;
  /** `'GCP01'`. `^[A-Za-z0-9_\-]{1,32}$`, unique per image. */
  code: string | null;
  /** ★ The surveyor's free-text point name — the table's "Name" column. */
  name: string | null;

  /**
   * ★ ORIGINAL image pixel space — independent of viewer zoom, pan, or
   *   brightness/contrast. This conversion is normative and correctness-critical
   *   (§8.6, SCOPE.md §5). Sub-pixel: NEVER rounded for storage, rounded only for
   *   display.
   */
  image_px: PixelXY;
  /** Mosaic pixel space, origin top-left of the candidate mosaic, y-down. */
  satellite_px: PixelXY;

  lat: number;
  lon: number;
  /** ★ Always. Present so nobody has to assume. */
  crs: 'EPSG:4326';

  /**
   * ★ `null` is HONEST when no elevation provider resolved; `0` would not be.
   *   `elevation_source` may NEVER name a producer that did not run — the pair is
   *   bound by `ck_gcps_elevation_source_consistent`, and the job emits an
   *   `ELEVATION_UNAVAILABLE` warning (§4.27).
   */
  elevation_m: number | null;
  /** `local_dem` | `copernicus_dem` | `srtm` | `exif` | `manual` | `null`. */
  elevation_source: string | null;

  /**
   * ★ SCOPE.md §5. `manual` for every GCP in this build. See `GcpSource`.
   */
  source: GcpSource;

  /**
   * ★ 0–100.
   *
   * ★ WHAT THIS NUMBER MEANS DEPENDS ON `source`, and conflating the two cases is
   *   the failure this field's documentation exists to prevent:
   *
   *   - `source === 'manual'`   → the numeric REPRESENTATIVE of `declared_confidence`
   *     (see `SURVEYOR_CONFIDENCE_SCALE`). It is a HUMAN JUDGEMENT rendered as a
   *     number so the DB CHECK, the export column and the sort order all keep
   *     working. It is **not** measured, and `declared_confidence` is the field to
   *     read and to edit.
   *   - `source === 'automatic'` → the pipeline's computed score. DEFERRED
   *     (SCOPE.md §1) — no row carries this in this build.
   *
   * ★ Note this is 0–100 while `AnnotationRead.confidence` is 0–1. The two scales
   *   are deliberate and MUST NOT be unified (§6.1).
   */
  confidence: number;

  /**
   * ★ The surveyor's declared judgement. Non-null IFF `source === 'manual'` — which,
   *   in this build, is always (SCOPE.md §5).
   *
   * `null` when `source === 'automatic'`: an algorithm does not have a judgement,
   *   it has a score, and that is `confidence`.
   */
  declared_confidence: SurveyorConfidence | null;

  /** ★ An ALIAS of `accuracy.total_ce90_m`: serialised, never stored (§5.6). */
  horizontal_accuracy_m: number | null;
  accuracy: GcpAccuracy;

  /**
   * ★ `‖H · image_px − satellite_px‖` for THIS point. A job-level RMSE hides *the
   *   one bad correspondence* in an otherwise good match; this is how a surveyor
   *   finds it.
   *
   * ★ `null` in manual mode — there is no `H`, so there is no residual. `null` is
   *   the honest value; `0` would falsely claim a perfect fit.
   */
  residual_px: number | null;

  /**
   * ★ THE landmark pixel-accuracy ceiling (`top = 1 px`) — the largest per-point pixel
   *   error the product vouches for. Carried on every GCP so the UI shows the bar.
   */
  pixel_accuracy_ceiling_px: number;
  /**
   * ★ Whether this GCP's measured pixel error (`residual_px`) is within the ceiling. True
   *   when there is no residual to judge (manual mode); false only when a fit's residual
   *   exceeds `pixel_accuracy_ceiling_px` — the one point to re-check.
   */
  pixel_accuracy_within_ceiling: boolean;

  /**
   * ★ A manual ADJUSTMENT (refining a placed GCP) is distinct from a manual SOURCE.
   *   `source === 'manual'` says where the coordinate came from;
   *   `manually_adjusted` says it was moved after being placed.
   */
  manually_adjusted: boolean;
  /** Non-null IFF `manually_adjusted`. */
  original: GcpOriginal | null;
  /** `ST_Distance(original_geom, geom)` — geodesic, REAL metres. */
  adjustment_offset_m: number | null;
  adjusted_by: string | null;
  adjusted_at: IsoDateTime | null;
  adjustment_note: string | null;

  is_included_in_export: boolean;

  /**
   * ★ Staleness is a FLAG and never an auto-recompute. A GCP is a coordinate that
   *   may already be in a survey report, a contract, or a machine-control file.
   *   **It changes when a human decides it changes.** Every path that could
   *   invalidate a GCP marks it stale and says so; nothing recomputes it implicitly.
   */
  is_stale: boolean;
  stale_reason: GcpStaleReason | null;

  landmark: GcpLandmarkRef | null;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

export interface GcpSummary {
  id: Uuid;
  image_id: Uuid;
  code: string | null;
  image_px: PixelXY;
  lat: number;
  lon: number;
  source: GcpSource;
  confidence: number;
  declared_confidence: SurveyorConfidence | null;
  total_ce90_m: number;
  manually_adjusted: boolean;
  is_stale: boolean;
  is_included_in_export: boolean;
}

// ─────────────────────────────────────────────────────────────────────────────
// The mandated GCP table's view-model (§8.2 / §14 F-104)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * ★ THE SIX MANDATED COLUMNS, IN ORDER: Point ID · Image X/Y · Latitude ·
 *   Longitude · Confidence · Accuracy — plus a trailing action cell.
 *
 * ★ `total_ce90_m` is the error-radius column, **NEVER `relative_ce90_m`**.
 *   50-frontend's `GcpTableRow` was camelCase (void under C-08) AND carried
 *   `errorRadiusM`, which corresponds to NOTHING on `GcpRead` — while §8.7's
 *   precision truncation keys off `accuracy.total_ce90_m`. Picking the wrong one
 *   silently breaks the honesty mechanism.
 *
 * ★ This is a VIEW-MODEL, not a wire type — it is assembled client-side from
 *   `GcpRead`. Its field names still mirror the wire (L9) because every one of them
 *   IS a wire field; only `display_decimals` is computed.
 */
export interface GcpTableRow {
  id: Uuid;
  code: string | null;
  image_px: PixelXY;
  lat: number;
  lon: number;
  /** ★ SCOPE.md §5 — drives whether the Confidence cell reads a declared judgement
   *  or a computed score. In this build: always `manual`. */
  source: GcpSource;
  /** 0–100. See `GcpRead.confidence` for what it means per `source`. */
  confidence: number;
  declared_confidence: SurveyorConfidence | null;
  /** ★ The error-radius column. */
  total_ce90_m: number;
  /** ★ Z — elevation in metres (the DD+UTM+Z column). Null until the elevation algorithm runs. */
  elevation_m: number | null;
  manually_adjusted: boolean;
  is_stale: boolean;
  /** ★ False when this GCP's measured pixel error exceeds the 1px accuracy ceiling. */
  pixel_accuracy_within_ceiling: boolean;
  /** The pixel-accuracy ceiling (`top = 1px`), for the flag's tooltip. */
  pixel_accuracy_ceiling_px: number;
  /** Measured pixel error (null in manual mode). */
  residual_px: number | null;
  linked_annotation_id: Uuid | null;
  /**
   * ★ The linked landmark's free-text label, resolved client-side from the loaded
   *   annotations by `landmark_id` (`useGcpRows`). `null` when there is no landmark
   *   link or the landmark has no label — the table renders an em-dash.
   */
  landmark_name: string | null;
  /** ★ From `lib/geo/format.ts` (§8.7). A decimal digit IS a claim about accuracy. */
  display_decimals: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// Writes
// ─────────────────────────────────────────────────────────────────────────────

/**
 * `PATCH /gcps/{gcp_id}` — `If-Match` is **REQUIRED** (428 when absent).
 *
 * ★ THE TWO ADJUSTMENT MODES (§6.2), and the server closes the loop:
 *   - `lat`/`lon` only     → server derives `satellite_px` by the INVERSE chain.
 *   - `satellite_px` only  → server derives `lat`/`lon` by the FORWARD chain.
 *   - **both**             → forward-project and compare; beyond 0.5 m →
 *                            `422 GCP_ADJUSTMENT_AMBIGUOUS`.
 *   - neither (only `code`/`note`/flags) → metadata-only edit; does NOT set
 *                            `manually_adjusted`. **Renaming a GCP is not adjusting it.**
 *
 * ★ `image_px` is NOT adjustable here. Moving the point *on the photograph* is
 *   editing the annotation — `PATCH /annotations/{id}` — which marks this GCP
 *   stale. **Two endpoints, two meanings:** "the algorithm put the coordinate in
 *   the wrong place" vs. "I marked the wrong pixel". Allowing `image_px` here would
 *   silently fork `gcps.pixel_x` from `annotations.pixel_x` with no revision record.
 *
 * ★ `50-frontend`'s `POST /gcps/{id}/adjust` with `{imagePixel, latLon, pinned}` is
 *   **VOID** (§8.5) — that endpoint does not exist and `pinned` is on no schema and
 *   no table.
 *
 * ★ A manual adjustment does NOT set `confidence = 100`. Tempting, and wrong:
 *   overwriting it destroys the only record of how well the algorithm did, makes
 *   `?confidence__gte=70` meaningless, and asserts a certainty the human never
 *   claimed — a surveyor nudging a marker 3 m is *guessing better*, not measuring.
 *   Human certainty is carried by `manually_adjusted` + `adjustment_offset_m` +
 *   `adjusted_by` + the note.
 */
export interface GcpUpdate {
  lat?: number | undefined;
  lon?: number | undefined;
  satellite_px?: PixelXY | undefined;
  /** ★ (1.2.6) Move a BARE GCP's photo endpoint alongside lat/lon — ORIGINAL image
   *  px. 422 for a landmark-backed GCP (its photo mark lives on the annotation). */
  image_px?: PixelXY | undefined;
  code?: string | null | undefined;
  /** ★ Rename the point's free-text "Name". */
  name?: string | null | undefined;
  /** ★ SCOPE.md §5: the surveyor may revise their own declared judgement. */
  declared_confidence?: SurveyorConfidence | undefined;
  is_included_in_export?: boolean | undefined;
  adjustment_note?: string | null | undefined;
}

export interface GcpResetRequest {
  confirm: boolean;
}

/**
 * `POST /images/{id}/gcps/recompute` — **the only door**, and it is one a person opens.
 *
 * ★ DEFERRED SURFACE (SCOPE.md §4): `mode: 'rederive'` runs the full matching
 *   pipeline and therefore returns `501` in this build. `mode: 'refit'` re-fits a
 *   homography, which is also deferred. The request type is complete so the seam is
 *   real and re-enabling costs no caller a change (SCOPE.md §7).
 */
export interface GcpRecomputeRequest {
  match_result_id?: Uuid | null;
  mode?: 'refit' | 'rederive';
  /** 1..1000 */
  anchor_weight?: number;
  preserve_adjusted?: boolean;
  estimator?: EstimatorName | null;
  /** ★ `true` → synchronous `200 GcpRecomputeDryRun`. Otherwise `202 JobRead`. */
  dry_run?: boolean;
}

export interface GcpRecomputeDelta {
  gcp_id: Uuid;
  code: string | null;
  /** How far this point would move, in real ground metres. */
  offset_m: number;
  lat_before: number;
  lon_before: number;
  lat_after: number;
  lon_after: number;
  confidence_before: number;
  confidence_after: number;
}

export interface GcpRecomputeFitStats {
  inlier_count: number;
  inlier_ratio: number;
  rmse_px: number;
  anchor_count: number;
}

/**
 * ★ `dry_run` is not a nicety. "Recompute" moves coordinates the surveyor may have
 *   already reported; they get to see how far, and for which points, BEFORE
 *   committing.
 */
export interface GcpRecomputeDryRun {
  deltas: GcpRecomputeDelta[];
  fit: GcpRecomputeFitStats;
  max_offset_m: number;
  mean_offset_m: number;
  affected_count: number;
}

export interface GcpFilters {
  match_result_id?: Uuid;
  source?: GcpSource;
  confidence__gte?: number;
  confidence__lte?: number;
  manually_adjusted?: boolean;
  is_stale?: boolean;
  is_included_in_export?: boolean;
  q?: string;
  sort?: string;
  limit?: number;
  offset?: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// ★ The cross-project overview — `GET /gcps` (the dashboard map)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * ★ One GCP as it appears on the DASHBOARD MAP — every point the surveyor has
 *   placed, across every project, in one geographic view.
 *
 * ★ Deliberately NOT `GcpRead`. That type carries the full accuracy breakdown, the
 *   original/adjusted pair, the landmark ref and the staleness reasoning — none of
 *   which a pin on an overview map renders, and all of which would multiply the
 *   payload of a query whose whole point is "show me everything". It carries the
 *   denormalised `project_name` / `image_filename` so a marker popup does not fan
 *   out into N follow-up requests.
 *
 * ★ `total_ce90_m` is nullable here (unlike `GcpSummary`): the overview is read from
 *   a join that may predate an accuracy computation, and a fabricated zero would be
 *   a claim of perfect accuracy — the one lie this system must never tell (L12).
 */
export interface GcpOverview {
  id: Uuid;
  project_id: Uuid;
  project_name: string;
  image_id: Uuid;
  image_filename: string;
  code: string | null;
  landmark_name: string | null;
  lat: number;
  lon: number;
  confidence: number;
  source: GcpSource;
  total_ce90_m: number | null;
}

/** Query params for `GET /gcps`. All optional; the bare call returns everything. */
export interface GcpOverviewFilters {
  project_id?: Uuid;
  album_id?: Uuid;
  min_confidence?: number;
  limit?: number;
  offset?: number;
}
