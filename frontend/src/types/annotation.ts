/**
 * Annotations + revisions — mirrors `backend/app/schemas/annotation.py` and
 * `revision.py` (§6.2), field for field.
 *
 * ★ `RevisionSummary` lives in `common.ts`, not here — matching the Python move
 *   (§6.2). `RevisionRead` — the fat one — stays here.
 */

import type { IsoDateTime, RevisionSummary, Uuid, WarningItem } from './common';
import type { GeoJsonGeometry, GeoJsonPoint } from './geo';

/** Identical to the `annotation_kind` PG enum (§5.3). */
export type AnnotationKind =
  | 'generic'
  | 'field_corner'
  | 'field_border'
  | 'road'
  | 'road_intersection'
  | 'irrigation_canal'
  | 'tree'
  | 'tree_line'
  | 'greenhouse'
  | 'building'
  | 'building_corner'
  | 'water_body'
  | 'pole_or_pylon'
  | 'fence_post'
  | 'crop_row'
  | 'other';

export type AnnotationGeomType = 'point' | 'polyline' | 'polygon';

export type AnnotationOp = 'create' | 'update' | 'delete' | 'restore';

export interface AnnotationStyle {
  color?: string;
  fill_opacity?: number;
  stroke_width?: number;
}

export interface AnnotationRead {
  id: Uuid;
  image_id: Uuid;
  kind: AnnotationKind;
  geom_type: AnnotationGeomType;
  /** Representative point; `== the point` for `geom_type === 'point'`. */
  pixel_x: number;
  pixel_y: number;
  /**
   * ★ GeoJSON-SHAPED but IMAGE PIXELS: `[x, y]`, y-down, SRID 0 — **not
   *   `[lon, lat]`**. The shape is already understood by every client library and
   *   by Konva's serializer, while the CRS is unambiguously declared by the
   *   resource being image-scoped. To make the trap impossible to fall into, the
   *   API REJECTS any `crs` member on input (`422 ANNOTATION_GEOMETRY_INVALID`)
   *   and never emits one. **Do not feed this to Leaflet expecting degrees.**
   */
  geometry: GeoJsonGeometry;
  label: string | null;
  description: string | null;
  /**
   * ★ 0–1 — the SURVEYOR'S OWN certainty, typed into the annotation tool.
   *
   * ★ THE TWO CONFIDENCE SCALES ARE DELIBERATE AND MUST NOT BE UNIFIED (§6.1).
   *   This is 0–1 and is a human assertion. `GcpRead.confidence` is 0–100. They
   *   mean different things, are produced by different actors, and are NEVER
   *   compared. Any client rendering a "confidence" bar must read the field's
   *   scale from the field, not guess.
   */
  confidence: number;
  ordering: number;
  style: Record<string, unknown>;
  attributes: Record<string, unknown>;
  /** → ETag. Required on update/delete for optimistic locking. */
  version_no: number;
  revision_seq: number;
  is_deleted: boolean;
  /**
   * ★ Derived: `kind ∈ {field_corner, road_intersection, building_corner}`.
   *   There is deliberately NO `geom_type === 'point'` clause: the representative
   *   point IS the candidate location for any geometry type — that is what it is
   *   for — and `gcps.landmark_id → annotations.id` is FK'd to the general table
   *   so that "a polygon corner can be a GCP" works.
   */
  is_gcp_candidate: boolean;
  /**
   * ★ ALL GCPs derived from this annotation, ordered by `match_results.rank ASC`.
   *   Empty when none. It is a ONE-TO-MANY: `uq_gcps_landmark_match` permits one
   *   GCP per landmark PER MATCH RESULT, losing candidates are kept, and a
   *   recompute writes a NEW `match_results` row.
   */
  gcp_ids: Uuid[];
  /**
   * ★ The GCP whose match_result has `is_selected = true`, else `null`. This is
   *   what the canvas link actually wants. Two fields because there are genuinely
   *   two questions: "which one is live?" and "what else exists?".
   */
  gcp_id: Uuid | null;
  created_by: string | null;
  updated_by: string | null;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

/**
 * Validation mirrors the DDL CHECKs so a violation is a clean 422, not a `23514`:
 * `geom_type` matches `geometry.type` · polyline ≥ 2 pts · polygon exterior ring
 * ≥ 4 pts and closed · `ST_IsValid` · 2D only · all coords within
 * `[0, width] × [0, height]` (`422 ANNOTATION_OUT_OF_BOUNDS`) · `confidence ∈ [0,1]`
 * · ≤ 2000 per image · ≤ 10 000 vertices.
 */
export interface AnnotationCreate {
  kind: AnnotationKind;
  geom_type: AnnotationGeomType;
  geometry: GeoJsonGeometry;
  pixel_x?: number;
  pixel_y?: number;
  label?: string | null;
  description?: string | null;
  confidence?: number;
  ordering?: number;
  style?: Record<string, unknown>;
  attributes?: Record<string, unknown>;
}

/** PATCH — UNSET semantics: omit a key to leave it untouched (§6.1). */
export interface AnnotationUpdate {
  kind?: AnnotationKind | undefined;
  geom_type?: AnnotationGeomType | undefined;
  geometry?: GeoJsonGeometry | undefined;
  pixel_x?: number | undefined;
  pixel_y?: number | undefined;
  label?: string | null | undefined;
  description?: string | null | undefined;
  confidence?: number | undefined;
  ordering?: number | undefined;
  style?: Record<string, unknown> | undefined;
  attributes?: Record<string, unknown> | undefined;
}

export interface AnnotationSummary {
  id: Uuid;
  image_id: Uuid;
  kind: AnnotationKind;
  geom_type: AnnotationGeomType;
  pixel_x: number;
  pixel_y: number;
  label: string | null;
  confidence: number;
  is_gcp_candidate: boolean;
  gcp_id: Uuid | null;
  version_no: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// Bulk upsert — the ONE write path for the canvas (§6.2)
// ─────────────────────────────────────────────────────────────────────────────

export interface AnnotationBulkUpsertItem {
  /** Must be null for `create`. */
  id: Uuid | null;
  op: AnnotationOp;
  /** Required for update/delete/restore. */
  version_no?: number | null;
  /** Temp id echoed back so the store can swap `tmp-17` → the real UUID. */
  client_ref?: string | null;
  kind?: AnnotationKind;
  geom_type?: AnnotationGeomType;
  geometry?: GeoJsonGeometry;
  pixel_x?: number;
  pixel_y?: number;
  label?: string | null;
  description?: string | null;
  confidence?: number;
  ordering?: number;
  style?: Record<string, unknown>;
  attributes?: Record<string, unknown>;
}

/**
 * ★ `PUT` on the collection is correct here: the request declares the DESIRED STATE
 *   of the image's annotation set; it is idempotent. Six separate PATCHes would
 *   produce six revisions (making undo useless), six round trips, and a
 *   partially-saved canvas if the fourth fails.
 *
 * ★ Atomicity: ALL-OR-NOTHING. A partial save on a survey annotation set is worse
 *   than no save — the surveyor believes the canvas matches the database when it
 *   does not.
 */
export interface AnnotationBulkUpsertRequest {
  mode?: 'merge' | 'replace';
  base_revision_seq?: number | null;
  revision_label?: string | null;
  client_op_id?: string | null;
  /** 1–2000 items. */
  items: AnnotationBulkUpsertItem[];
}

export interface AnnotationBulkUpsertResultItem {
  id: Uuid;
  client_ref: string | null;
  op: AnnotationOp;
  /**
   * ★ `unchanged` is returned when an update is byte-identical to current state,
   *   and NO revision event is written. Without this, an idle canvas auto-saving
   *   every 30 s inflates the undo stack with thousands of no-op events.
   */
  status: 'created' | 'updated' | 'deleted' | 'restored' | 'unchanged';
  version_no: number;
}

export interface AnnotationApplyCounts {
  created: number;
  updated: number;
  deleted: number;
  restored: number;
  unchanged: number;
}

export interface AnnotationBulkUpsertResponse {
  revision: RevisionSummary;
  applied: AnnotationApplyCounts;
  items: AnnotationBulkUpsertResultItem[];
  /**
   * ★ THE FULL RESULTING LIVE SET. Costs one query and removes an entire class of
   *   desync — the client replaces its store wholesale instead of reconciling deltas.
   */
  annotations: AnnotationRead[];
  warnings: WarningItem[];
}

// ─────────────────────────────────────────────────────────────────────────────
// Version history (§6.2 `revision.py`)
// ─────────────────────────────────────────────────────────────────────────────

export interface AnnotationVersionChangeSummary {
  fields_changed: string[];
  vertex_delta: number | null;
  moved_px: number | null;
}

/**
 * ★ `id` is a JSON **number**, not a UUID string. `annotation_versions.id` is
 *   `BIGSERIAL` — the ONE resource-id asymmetry in the API (§6.1), called out in
 *   every schema that touches it.
 */
export interface AnnotationVersionSummary {
  id: number;
  annotation_id: Uuid;
  image_id: Uuid;
  revision_id: Uuid | null;
  op: AnnotationOp;
  version_no: number;
  actor_id: string | null;
  client_op_id: string | null;
  created_at: IsoDateTime;
  summary: AnnotationVersionChangeSummary;
  /** Both null unless `include_payloads=true`. */
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
}

/**
 * ★ Per the DDL CHECK: `before` is null IFF `op === 'create'`; `after` is null IFF
 *   `op === 'delete'`. The invariant is stated in the OpenAPI description so client
 *   code can rely on it.
 */
export interface AnnotationVersionRead extends AnnotationVersionSummary {
  /** RFC 6902 JSON Patch. */
  diff: Record<string, unknown>[];
  pixel_geom_after: GeoJsonGeometry | GeoJsonPoint | null;
}

export interface RevisionSnapshot {
  annotations: AnnotationRead[];
  seq: number;
}

export interface RevisionDiffSummary {
  created: number;
  updated: number;
  deleted: number;
  restored: number;
}

export interface RevisionRead extends RevisionSummary {
  snapshot: RevisionSnapshot | null;
  /**
   * ★ Tells the truth about cost: `stored` = read straight from
   *   `project_revisions.snapshot`; `replayed` = materialised from the nearest
   *   preceding checkpoint. Replay is capped at 5000 events →
   *   `422 REVISION_REPLAY_TOO_EXPENSIVE`. A history endpoint that can spin for
   *   40 s is a DoS on your own database.
   */
  snapshot_source: 'stored' | 'replayed';
  events: AnnotationVersionSummary[];
  diff_summary: RevisionDiffSummary;
  restorable: boolean;
}

export interface RevisionCreate {
  label?: string | null;
  is_checkpoint?: boolean;
}

/**
 * ★ Restore is FORWARD-ONLY. It computes the delta from current state to the target
 *   and applies it as a NEW revision, emitting normal events — so a restore is
 *   itself undoable. Rewinding `current_revision_seq` would orphan every event
 *   above it and make the log lie. An append-only log that gets rewound is not an
 *   audit log.
 *
 * ★ Restore NEVER touches GCPs, only annotations. It warns `GCPS_NOW_STALE` and
 *   leaves them.
 */
export interface RevisionRestoreRequest {
  confirm: boolean;
  label?: string | null;
}

export interface RevisionRestoreResponse {
  revision: RevisionSummary;
  annotations: AnnotationRead[];
  warnings: WarningItem[];
}

export interface AnnotationVersionFilters {
  annotation_id?: Uuid;
  op?: AnnotationOp | AnnotationOp[];
  include_payloads?: boolean;
  /**
   * ★ THE ONE keyset exception (§6.2): switches to keyset mode for the undo stack's
   *   infinite scroll, where `offset` would skip events as new ones land.
   *   `offset` + `before_id` together → `422 PARAM_CONFLICT`.
   */
  before_id?: number;
  limit?: number;
  offset?: number;
}
