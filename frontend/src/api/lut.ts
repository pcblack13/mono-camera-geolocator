/**
 * `/lut/*` — pixel→lat/lon lookup-table builds.
 *
 * ★ A build ray-casts every pixel of one photograph against the project DEM and
 *   packages the result as a deployable bundle (`lat.npy` + `lon.npy` + manifest +
 *   standalone reader). Builds run server-side on a thread and are POLLED — the
 *   status carries pixel-level progress and, at the end, the validation report.
 */

import type { Uuid } from '../types/common';
import { fetchJson, upload, type UploadOptions } from './client';

/** `GET /lut/library/{site}/lookup` — where one pixel of the picture lands. */
export interface LutLookup {
  site_name: string;
  u: number;
  v: number;
  lut_u: number;
  lut_v: number;
  placed: boolean;
  lat: number | null;
  lon: number | null;
  elevation_m: number | null;
  elevation_source: string | null;
  reason: 'off_table' | 'no_terrain' | null;
}

export interface LutBuildRequest {
  image_id: Uuid;
  /** Output folder becomes `<site_name>_lut`. Defaults to the photograph's filename stem. */
  site_name?: string;
  target_height_m?: number;
  coord_dtype?: 'float64' | 'float32';
  validation_samples?: number;
}

export interface LutValidationReport {
  samples?: number;
  mean_error_m?: number;
  max_error_m?: number;
  tolerance_m?: number;
  passed?: boolean;
  [key: string]: unknown;
}

export interface LutBuildStatus {
  build_id: string;
  image_id: Uuid;
  project_id: Uuid;
  site_name: string;
  status: 'queued' | 'running' | 'succeeded' | 'failed';
  progress_done: number;
  progress_total: number;
  started_at: string;
  error: string | null;
  report: LutValidationReport | null;
  bundle_dir: string | null;
  archive_available: boolean;
  /**
   * ★ Set when the build stood on an ADOPTED correction from the accuracy check rather
   *   than on the pose this photograph's GCPs alone imply. Null is the normal case. A
   *   LUT whose geometry came from somewhere other than its own control points must say
   *   so — here, and in `adopted_correction.json` inside the bundle.
   */
  adopted: {
    stage?: string;
    adopted_at?: string;
    all_m?: number | null;
    gate_accepted?: boolean;
    reproj_mean_px?: number;
    reproj_max_px?: number;
    ground_correction_applied?: boolean;
    ground_correction_note?: string;
  } | null;
}

export interface LutLibraryEntry {
  site_name: string;
  built_utc: string | null;
  image: { width?: number; height?: number };
  payload_mb: number | null;
  validation_passed: boolean | null;
  max_error_m: number | null;
  /** `[lat, lon]` the bundle looks from — lets the map open before a run. */
  center: [number, number] | null;
  bundle_dir: string;
  archive_available: boolean;
  /**
   * ★ True when the manifest carries `pose.R/C/K` + the image size + `dem.epsg` —
   *   everything the DRIFT monitor re-solves geometry from. Detection needs only the
   *   arrays, so a bundle imported payload-only is `false` here and still perfectly
   *   usable for placement. The drift page uses this to say so BEFORE Freeze.
   */
  has_pose: boolean;
  /** ★ GEO-DRIFT C1: the bundle has everything but intrinsics — freezable once a
   *  field of view is given. Distinct from `has_pose`, which stays false for it. */
  pose_needs_fov?: boolean;
  /**
   * ★ Present when the focal was SOLVED from the control points (a no-calibration
   *   build, 2026-09-09): the seed the search started from — typed, or the default
   *   when the field of view was left blank — and the angle it solved to.
   */
  /** The photograph the pose was solved on, when the bundle records it (2026-09-09). */
  source_image_id?: string | null;
  intrinsics?: {
    mode: 'fov';
    fov_h_seed_deg: number | null;
    seed_defaulted: boolean;
    focal_solved: boolean;
    fov_h_solved_deg: number | null;
    fx_solved: number | null;
  } | null;
  /**
   * ★ Set when the bundle was IMPORTED rather than built here — when, from what, and
   *   whether its manifest travelled with it or had to be synthesised. A LUT the app
   *   cannot vouch for must say where it came from.
   */
  imported: {
    at_utc?: string;
    source?: string;
    manifest?: 'synthesised' | 'from the bundle';
    has_pose?: boolean;
    note?: string;
  } | null;
}

/**
 * `POST /lut/library/import` — file a bundle this app did not build.
 *
 * ★ Exactly one of `file` / `source_path`. `source_path` is the DESKTOP route: the
 *   API runs on this same machine, so a 150 MB bundle — or a bundle FOLDER, which
 *   cannot be uploaded at all — is opened in place instead of travelling over HTTP.
 */
export interface LutImportForm {
  file?: File;
  source_path?: string;
  /** Defaults to the bundle's own name, then the file name. Sanitised server-side. */
  site_name?: string;
  /** Replace a bundle already filed under that name (the 409's answer). */
  overwrite?: boolean;
}

function importFormData(form: LutImportForm): FormData {
  const fd = new FormData();
  if (form.file) fd.append('file', form.file, form.file.name);
  if (form.source_path !== undefined) fd.append('source_path', form.source_path);
  if (form.site_name !== undefined && form.site_name !== '') fd.append('site_name', form.site_name);
  if (form.overwrite) fd.append('overwrite', 'true');
  return fd;
}

export const lutApi = {
  create: (body: LutBuildRequest, signal?: AbortSignal): Promise<LutBuildStatus> =>
    fetchJson<LutBuildStatus>('/lut/builds', { method: 'POST', body, signal }),

  list: (signal?: AbortSignal): Promise<LutBuildStatus[]> =>
    fetchJson<LutBuildStatus[]>('/lut/builds', { signal }),

  get: (buildId: string, signal?: AbortSignal): Promise<LutBuildStatus> =>
    fetchJson<LutBuildStatus>(`/lut/builds/${buildId}`, { signal }),

  /** ★ The bundles ON DISK — the durable record; survives API restarts. */
  library: (signal?: AbortSignal): Promise<LutLibraryEntry[]> =>
    fetchJson<LutLibraryEntry[]>('/lut/library', { signal }),

  /** ★ One pixel of a LIVE picture → the ground, through a library bundle — the
   *  monitoring page's live predict (2026-09-10). `w`/`h` are the media's size so a
   *  1280×720 stream reads the right cell of a 4032×2268 table; `projectId` adds
   *  the elevation from the camera project's DEM. Sky answers `placed: false`. */
  lookup: (
    siteName: string,
    q: { u: number; v: number; w?: number; h?: number; projectId?: string | null },
    signal?: AbortSignal,
  ): Promise<LutLookup> => {
    const params = new URLSearchParams({ u: String(q.u), v: String(q.v) });
    if (q.w && q.h) {
      params.set('w', String(Math.round(q.w)));
      params.set('h', String(Math.round(q.h)));
    }
    if (q.projectId) params.set('project_id', q.projectId);
    return fetchJson<LutLookup>(
      `/lut/library/${encodeURIComponent(siteName)}/lookup?${params.toString()}`,
      { signal },
    );
  },

  /**
   * Import an existing bundle into that same library — the answer for a LUT that
   * arrived on a USB stick or was built on another machine. Answers with the row
   * the library will show, so a caller can select it immediately.
   *
   * `onProgress` reports UPLOAD bytes; the validation that follows is server-side
   * and takes about a second.
   */
  import: (form: LutImportForm, opts: UploadOptions = {}): Promise<LutLibraryEntry> =>
    upload<LutLibraryEntry>('/lut/library/import', importFormData(form), opts),
};
