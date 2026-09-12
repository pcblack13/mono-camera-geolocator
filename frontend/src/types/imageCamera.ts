/**
 * `types/imageCamera.ts` — the photograph's entered camera, mirroring
 * `backend/app/schemas/image_camera.py` field-for-field (L9: snake_case both sides).
 *
 * ★ ONE ENTERED CAMERA PER PHOTOGRAPH, typed in on its setup page. This is *entered
 *   reference data* for the fixed-camera workflow — not `CameraPoseRead`, which is a
 *   per-image, match-derived estimate (deferred, 501) and lives in `types/pose.ts`.
 *
 * ★ Conventions, stated once so the form labels and the maths agree:
 *   - `fx fy cx cy` are PIXELS (OpenCV pinhole K), not millimetres.
 *   - Distortion is Brown–Conrady, consumed in OpenCV vector order `[k1, k2, p1, p2, k3]`.
 *   - `lat`/`lon` are WGS84 decimal degrees; projected X/Y/Z are DERIVED from the
 *     project DEM at solve time, never stored.
 *   - `mast_offset_m` — metres the optical centre sits above the bare-earth DEM.
 *   - `tilt_deg` — degrees BELOW horizontal, + = aimed down (the field-tool
 *     convention; equals `-pitch_deg` in pose vocabulary).
 */

import type { Uuid } from './common';

/** `GET`/`PUT /images/{id}/camera` response. `configured=false` ⇒ all fields null. */
export interface ImageCameraRead {
  image_id: Uuid;
  /** True iff a camera has been saved for this photograph. */
  configured: boolean;

  fx: number | null;
  fy: number | null;
  cx: number | null;
  cy: number | null;
  k1: number | null;
  k2: number | null;
  p1: number | null;
  p2: number | null;
  k3: number | null;
  img_w: number | null;
  img_h: number | null;

  lat: number | null;
  lon: number | null;
  mast_offset_m: number | null;

  tilt_deg: number | null;

  /** The surveyor turned auto GCP picking on for this photograph (intent only —
   *  the tool also needs FOUR located GCPs before it activates). */
  auto_gcp_enabled: boolean;
  /** ★ GEO-DRIFT C2: solve the focal from the GCPs instead of trusting `fx..cy`. */
  no_calibration: boolean;
  /** A ROUGH seed for that solve, degrees — not a measurement. */
  fov_h_deg: number | null;
  /** null means square pixels. */
  fov_v_deg: number | null;

  created_at: string | null;
  updated_at: string | null;
}

/**
 * `PUT /images/{id}/camera` — full replace, idempotent. An omitted/null field IS a
 * cleared field; `lat` and `lon` must travel together (the server 422s a lone one).
 */
export interface ImageCameraPut {
  fx?: number | null;
  fy?: number | null;
  cx?: number | null;
  cy?: number | null;
  k1?: number | null;
  k2?: number | null;
  p1?: number | null;
  p2?: number | null;
  k3?: number | null;
  img_w?: number | null;
  img_h?: number | null;

  lat?: number | null;
  lon?: number | null;
  mast_offset_m?: number | null;

  tilt_deg?: number | null;

  /** Omitted ⇒ false (PUT is full-replace). */
  auto_gcp_enabled?: boolean;
  /** ★ GEO-DRIFT C2 — see `ImageCameraRead`. */
  no_calibration?: boolean;
  fov_h_deg?: number | null;
  fov_v_deg?: number | null;
}

/** `POST /images/{id}/camera/estimate` — geolocate one photo pixel. */
export interface AutoGcpEstimateRequest {
  /** Full-resolution image pixels, y-down — the same space `gcps.pixel_x/y` uses. */
  u: number;
  v: number;
  /** Metres above the terrain the TARGET sits (rooftop, vehicle). Default 0 = ground. */
  height_offset_m?: number;
}

/**
 * The estimate — an INFERENCE, carrying the diagnostics that qualify it. The tilt
 * and position numbers compare the solve against what was ENTERED at setup; big
 * gaps mean a mistyped station or a misplaced GCP, and the UI must show them.
 */
export interface AutoGcpEstimateRead {
  lat: number;
  lon: number;
  elevation_m: number;
  distance_m: number;

  gcps_used: number;
  reproj_mean_px: number;
  reproj_max_px: number;
  azimuth_deg: number;
  tilt_solved_deg: number;
  tilt_entered_deg: number | null;
  position_shift_m: number;
  warnings: string[];
}

/**
 * `POST /images/{id}/camera/project` — the estimate run BACKWARDS: a world
 * coordinate → the full-resolution pixel where it appears through the solved pose.
 * Used to keep the photo mark in lock-step when the MAP endpoint is dragged in Auto
 * mode. Off-DEM and behind-camera are 422s, not shapes here.
 */
export interface AutoGcpProjectRequest {
  lat: number;
  lon: number;
  /** Metres above the terrain the TARGET sits. Default 0 = ground. */
  height_offset_m?: number;
}

export interface AutoGcpProjectRead {
  /** Full-resolution image pixels, y-down — the same space `gcps.pixel_x/y` uses. */
  u: number;
  v: number;
  /** Judged against the entered `img_w`/`img_h`; `null` = no frame size on record
   *  (the client judges against the rendered image's natural size instead). */
  inside_image: boolean | null;
  gcps_used: number;
  warnings: string[];
}
