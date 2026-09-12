/**
 * ★★ Ground Control Points — endpoints 38–42 and 64 (§7), **plus the manual-mode
 *    create that §7 does not have**. THE DELIVERABLE.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * ★★ THE GAP, AND WHY THIS MODULE FILLS IT.
 *
 *   §7 has **no `POST` that creates a GCP**. Endpoints 38/39 read, 40 patches, 41
 *   resets, 42 recomputes, 64 lists by match result — every one of them presupposes
 *   that GCPs come into existence *as a side effect of a match job*. That was true of
 *   the system CONTRACT.md describes.
 *
 *   **SCOPE.md overrides it.** The matching engine is deferred, and manual GCP mode
 *   — *"photo pixel ↔ map click → lat/lon"* — is *"now the product's core
 *   interaction"* (SCOPE.md §5). With no create endpoint the product cannot produce
 *   a single GCP, which makes every other endpoint in this file a reader of an empty
 *   table. So `POST /images/{image_id}/gcps` is **added**, in the spirit of §7's
 *   nesting (`gcps.py` `router_image`, exactly where endpoints 38 and 42 already
 *   live), and flagged in the IU-24 report for IU-17/IU-19/IU-21.
 *
 *   {@link GcpCreate} is likewise declared here because IU-23 owns `types/**` and
 *   §8.2's `gcp.ts` row has no `GcpCreate` — for the same reason: the contract had no
 *   create. **It belongs in `types/gcp.ts`.** Flagged.
 * ─────────────────────────────────────────────────────────────────────────────
 */

import type { Page, Uuid } from '../types/common';
import type { GeoJsonFeatureCollection, PixelXY, ProviderId } from '../types/geo';
import type {
  GcpFilters,
  GcpOverview,
  GcpOverviewFilters,
  GcpRead,
  GcpRecomputeDryRun,
  GcpRecomputeRequest,
  GcpResetRequest,
  GcpUpdate,
  SurveyorConfidence,
} from '../types/gcp';
import type { JobRead } from '../types/job';
import { fetchJson, forgetEtag, toQuery } from './client';

// ─────────────────────────────────────────────────────────────────────────────
// The manual correspondence — SCOPE.md §5
// ─────────────────────────────────────────────────────────────────────────────

/**
 * ★★ `POST /images/{image_id}/gcps` — commit a manual correspondence.
 *
 * The surveyor marked a landmark in the photo and clicked the same physical spot on
 * the satellite map. **The coordinate is a DIRECT OBSERVATION, not an inference**
 * (SCOPE.md §2) — there is no homography, so there is no residual, no degeneracy
 * gate, and no computed confidence.
 *
 * Mirrors `correspondenceStore`'s committable state (IU-25) field for field, so the
 * commit is a projection and not a translation.
 */
export interface GcpCreate {
  /**
   * ★ **ORIGINAL image pixel space** — independent of viewer zoom, pan, brightness
   *   and contrast. Produced by `lib/viewport/transform.ts`'s `stageToImage` at
   *   `ImageViewer`'s single conversion site (§8.6: *"normative and
   *   correctness-critical"*). **Never rounded** — sub-pixel is stored, rounding is
   *   for display only.
   */
  /**
   * ★ Send **exactly one** of `image_px` or `landmark_id` — never both. The server
   *   rejects both with 422 ("Send exactly one … sending both makes two claims about one
   *   fact"): `landmark_id` derives the photo pixel from a saved annotation, `image_px`
   *   states it directly. When the correspondence is anchored to a saved landmark, send
   *   `landmark_id` and omit `image_px`; otherwise send `image_px`.
   */
  image_px?: PixelXY;

  /** ★ The map click, **EPSG:4326**. Stored as `geography(Point, 4326)` (SCOPE.md §5). */
  lat: number;
  lon: number;

  /**
   * ★ **SURVEYOR-DECLARED, NEVER COMPUTED** (SCOPE.md §5), and therefore **REQUIRED**.
   *
   *   Optional-with-a-default would manufacture a judgement the human never made,
   *   which is the same failure §8.7's decimal truncation exists to prevent, one
   *   field over. `correspondenceStore` refuses to reach `ready` without it for the
   *   same reason.
   */
  declared_confidence: SurveyorConfidence;

  /**
   * The annotation this correspondence is anchored to — `GcpRead.landmark_id`.
   * `null` when the surveyor clicked a bare pixel rather than an existing landmark.
   *
   * ★ `correspondenceStore` holds a `landmark_client_id` (annotationStore's local
   *   identity). The caller resolves it to the persisted annotation's `Uuid` before
   *   committing; an unsaved landmark has no server id to link.
   */
  landmark_id?: Uuid | null;

  /** `'GCP01'`. `^[A-Za-z0-9_\-]{1,32}$`, unique per image. Server-assigned when omitted. */
  code?: string | null;
  /** ★ The surveyor's free-text point name — the "Name" column (no character constraints). */
  name?: string | null;

  /**
   * ★ ACCURACY INPUTS, and they are not optional in spirit.
   *
   *   SCOPE.md §5: *"Reported positional accuracy comes from imagery
   *   ground-sample-distance and click precision at the map's zoom level — a real,
   *   defensible number — not from a match score."* The server cannot compute either
   *   term without knowing **which basemap** the click landed on and **at what
   *   zoom**: GSD is `f(provider, zoom, latitude)` and click precision is
   *   `f(zoom)`. Omit them and `gis/accuracy.py` has nothing to work from, leaving
   *   `total_ce90_m` — which §11.7 calls mandatory on every GCP — uncomputable.
   *
   *   Typed optional only because the server may fall back to the project's default
   *   provider; `map_zoom` has no such fallback and callers must send it.
   */
  provider?: ProviderId | null;
  map_zoom?: number | null;

  /**
   * The surveyor's free-text note. ★ The create wire field is `note` (the backend
   * `GcpManualCreate` schema; `extra="forbid"` 422s anything else — `adjustment_note`
   * included). It round-trips as `GcpRead.adjustment_note` on reads.
   */
  note?: string | null;
}

// ─────────────────────────────────────────────────────────────────────────────

const forImage = (imageId: Uuid): string => `/images/${imageId}/gcps`;
const flat = (id: Uuid): string => `/gcps/${id}`;

/** Endpoint 42's two outcomes: `dry_run: true` → `200`, otherwise `202 JobRead`. */
export type GcpRecomputeResponse = JobRead | GcpRecomputeDryRun;

/** Discriminates {@link GcpRecomputeResponse} structurally — a `JobRead` has a `status`. */
export function isRecomputeDryRun(r: GcpRecomputeResponse): r is GcpRecomputeDryRun {
  return typeof r === 'object' && r !== null && 'deltas' in r && 'fit' in r;
}

export const gcpsApi = {
  /**
   * ★★ ADDED — `POST /images/{image_id}/gcps` → `201 GcpRead`. Not in §7. See the
   *    module header. **This is how every GCP in this build comes into existence.**
   *
   * ★ The server sets `source: 'manual'` — it is not a client input. A client that
   *   could assert its own provenance could assert `'automatic'`, and SCOPE.md §5's
   *   whole point is that *"an automatic GCP can never be confused with an observed
   *   one downstream or in an export"*. Provenance is the server's to record.
   */
  create: (imageId: Uuid, body: GcpCreate, signal?: AbortSignal): Promise<GcpRead> =>
    fetchJson<GcpRead>(forImage(imageId), { method: 'POST', body, signal }),

  /**
   * `POST /images/{id}/gcps/copy-from/{sourceImageId}` → `201`. A camera that adopts
   * a NEW frame with the SAME aim carries the previous frame's control points over
   * (2026-09-09) — each recreated through the manual path, same pixel, same spot.
   */
  copyFrom: (
    imageId: Uuid,
    sourceImageId: Uuid,
    signal?: AbortSignal,
  ): Promise<{ copied: number; items: GcpRead[] }> =>
    fetchJson<{ copied: number; items: GcpRead[] }>(
      `${forImage(imageId)}/copy-from/${sourceImageId}`,
      { method: 'POST', signal },
    ),

  /** Endpoint 38 — `GET /images/{id}/gcps` → `200 Page[GcpRead]`. */
  listForImage: (imageId: Uuid, f: GcpFilters = {}, signal?: AbortSignal): Promise<Page<GcpRead>> =>
    fetchJson<Page<GcpRead>>(forImage(imageId), {
      query: { format: 'json', ...toQuery(f) },
      signal,
    }),

  /**
   * Endpoint 38 with `format=geojson` → a `GeoJsonFeatureCollection`.
   *
   * ★ `[lon, lat]` inside the geometry — RFC 7946 mandates x,y — while `lat`/`lon`
   *   objects everywhere else are lat-first (§6.1). The inversion is the single most
   *   common GeoJSON defect; it is stated here because this is the one function in
   *   the unit that returns it.
   */
  listForImageGeoJson: (
    imageId: Uuid,
    f: GcpFilters = {},
    signal?: AbortSignal,
  ): Promise<GeoJsonFeatureCollection<GcpRead>> =>
    fetchJson<GeoJsonFeatureCollection<GcpRead>>(forImage(imageId), {
      query: { format: 'geojson', ...toQuery(f) },
      signal,
    }),

  /** Endpoint 64 — `GET /match-results/{id}/gcps` → `200 Page[GcpRead]`. Empty in this build. */
  listForMatch: (
    matchResultId: Uuid,
    f: GcpFilters = {},
    signal?: AbortSignal,
  ): Promise<Page<GcpRead>> =>
    fetchJson<Page<GcpRead>>(`/match-results/${matchResultId}/gcps`, { query: toQuery(f), signal }),

  /**
   * Endpoint 39 — `GET /gcps/{id}` → `200 GcpRead` + `ETag`.
   *
   * ★ Reading a GCP is what puts its `ETag` in the registry, which is what makes the
   *   `If-Match` on {@link gcpsApi.update} possible. A list response carries one ETag
   *   for the whole page, so it cannot supply a per-row one — `useAdjustGcp`
   *   documents the consequence.
   */
  get: (id: Uuid, signal?: AbortSignal): Promise<GcpRead> =>
    fetchJson<GcpRead>(flat(id), { signal }),

  /**
   * ★ `GET /gcps` → `200 Page[GcpOverview]` — EVERY GCP THE SURVEYOR HAS PLACED,
   *   across every project, for the dashboard's geographic overview.
   *
   * ★ Unnested deliberately. Every other read here is nested under an image or a
   *   match result, because every other screen is *about* one photograph. The
   *   dashboard is about the whole body of work, and fanning out one request per
   *   project to assemble it would make the first screen of the app the slowest.
   *
   * ★ It returns {@link GcpOverview}, not `GcpRead` — see the type for why.
   */
  overview: (f: GcpOverviewFilters = {}, signal?: AbortSignal): Promise<Page<GcpOverview>> =>
    fetchJson<Page<GcpOverview>>('/gcps', { query: toQuery(f), signal }),

  /**
   * ★ Endpoint 40 — `PATCH /gcps/{id}`, **`If-Match` REQUIRED** → `200` · `412` · `422`.
   *
   *   THE ADJUSTMENT ENDPOINT (SCOPE.md §5: *"either endpoint can be dragged and
   *   re-committed"*). §8.5 is explicit that `POST /gcps/{id}/adjust` — 50-frontend's
   *   design, with `{imagePixel, latLon, pinned}` — is **VOID**: it does not exist,
   *   and `pinned` is on no schema and no table.
   *
   * ★ `image_px` IS NOT ADJUSTABLE HERE. Moving the point on the photograph is
   *   `PATCH /annotations/{id}`. Two endpoints, two meanings: *"the coordinate is in
   *   the wrong place"* vs *"I marked the wrong pixel"*. `GcpUpdate` has no `image_px`
   *   field, so the type system enforces it.
   */
  update: (id: Uuid, body: GcpUpdate, etag?: string, signal?: AbortSignal): Promise<GcpRead> =>
    fetchJson<GcpRead>(flat(id), { method: 'PATCH', body, ifMatch: etag, signal }),

  /**
   * Endpoint 41 — `POST /gcps/{id}/reset` → `200 GcpRead`. **Idempotent.**
   *
   * ★ Restores `original` — the algorithm's answer, written once and kept forever.
   *   `422 GCP_ORIGINAL_UNAVAILABLE` when the GCP was never adjusted.
   */
  reset: (
    id: Uuid,
    body: GcpResetRequest = { confirm: true },
    signal?: AbortSignal,
  ): Promise<GcpRead> => fetchJson<GcpRead>(`${flat(id)}/reset`, { method: 'POST', body, signal }),

  /**
   * ★★ ADDED — `DELETE /gcps/{id}` → `204`. Permanently removes a manual GCP.
   *
   * ★ A hard delete on the server (manual GCPs carry no `deleted_at`). The backing
   *   landmark annotation is left intact — removing a control point is not removing the
   *   feature it marked.
   */
  remove: async (id: Uuid, signal?: AbortSignal): Promise<void> => {
    await fetchJson<void>(flat(id), { method: 'DELETE', parse: 'none', signal });
    forgetEtag(flat(id));
  },

  /**
   * ★ DEFERRED — endpoint 42 `POST /images/{id}/gcps/recompute` → **`501`** in this
   *   build. Both modes are deferred: `rederive` runs the matching pipeline and
   *   `refit` re-fits a homography (SCOPE.md §4). Live: `202 JobRead`, or `200
   *   GcpRecomputeDryRun` when `dry_run: true`.
   */
  recompute: (
    imageId: Uuid,
    body: GcpRecomputeRequest = {},
    signal?: AbortSignal,
  ): Promise<GcpRecomputeResponse> =>
    fetchJson<GcpRecomputeResponse>(`${forImage(imageId)}/recompute`, {
      method: 'POST',
      body,
      signal,
    }),

  /** Drops a GCP's cached `ETag`. Called after any write that supersedes it. */
  forgetEtag: (id: Uuid): void => forgetEtag(flat(id)),
};
