/**
 * Camera pose — mirrors `backend/app/schemas/pose.py` (§6.2), field for field.
 *
 * ★★ DEFERRED (SCOPE.md §4): camera pose (yaw/pitch/roll) estimation is an ABC only.
 *    `GET/PATCH /images/{id}/camera-pose` are **registered and documented** and
 *    return `501` with a `feature: "deferred"` marker. The `camera_poses` table IS
 *    created exactly as specified (SCOPE.md §4 rule 5) — it simply holds no rows.
 *
 * ★ ONE OF THE FIVE MODULES §8.2 ADDED: `api/pose.ts` and `usePose` shipped with no
 *   home for `CameraPoseRead`, so IU-24 would have inlined `any` — exactly the drift
 *   §8.1 exists to prevent.
 */

import type { IsoDateTime, Uuid } from './common';
import type { GeoJsonPolygon, LatLon } from './geo';

/** Identical to the `pose_method` PG enum (§5.3). Parity leg 3 with `ai_engine`. */
export type PoseMethod =
  /** ★ The PRIMARY path: the plane's metric frame is known, so the 4-way
   *  `decomposeHomographyMat` ambiguity never arises. */
  | 'zhang_plane'
  | 'homography_decomposition'
  | 'pnp'
  | 'exif_gps_only'
  | 'manual'
  | 'heatmap_argmax';

export interface CameraIntrinsics {
  /** 9 floats, ROW-MAJOR. */
  k: number[];
  fx: number;
  fy: number;
  cx: number;
  cy: number;
  source: 'exif' | 'fov' | 'vanishing_points' | 'assumed' | 'manual';
}

export interface CameraIntrinsicsInput {
  fx?: number;
  fy?: number;
  cx?: number;
  cy?: number;
  hfov_deg?: number;
}

/**
 * ★ THE ANGLE CONVENTIONS, and they are the classic silent-disagreement bug between
 *   a CV module and a map renderer (§5.6):
 *   - `yaw_deg`   — **0 = TRUE North**, clockwise, `[0, 360)`.
 *   - `pitch_deg` — 0 = horizon, + = up, `[-90, 90]`.
 *   - `roll_deg`  — + = clockwise, `[-180, 180]`.
 *
 * ★ `ai_engine`'s `PoseResult.yaw_deg` is 0 = **up the window raster** — a different
 *   quantity. For a north-up EPSG:3857 window they coincide; for a rotated or UTM
 *   window they do NOT, and `gis.pose.window_yaw_to_north_deg()` (which applies the
 *   geotransform rotation AND the grid convergence) is the ONLY thing permitted to
 *   convert. What arrives here is already converted.
 */
export interface Orientation {
  yaw_deg: number | null;
  pitch_deg: number | null;
  roll_deg: number | null;
}

export interface OrientationInput {
  yaw_deg?: number | null;
  pitch_deg?: number | null;
  roll_deg?: number | null;
}

/** ★ Honest error bars. `null` is honest; `0` would not be. */
export interface PoseUncertainty {
  sigma_yaw_deg: number | null;
  sigma_pitch_deg: number | null;
  sigma_roll_deg: number | null;
  sigma_position_m: number | null;
  sigma_altitude_m: number | null;
}

/**
 * ★ `decomposeHomographyMat` returns up to four solutions. When the plane's metric
 *   frame is unknown they cannot be disambiguated, and reporting one as *the* answer
 *   would be a fabrication (L12).
 */
export interface PoseAmbiguity {
  is_ambiguous: boolean;
  solution_count: number;
  /** The rejected alternatives, so a reviewer can see what was discarded and why. */
  alternatives: { yaw_deg: number; pitch_deg: number; roll_deg: number; score: number }[];
  disambiguated_by: string | null;
}

export interface CameraPoseRead {
  id: Uuid;
  image_id: Uuid;
  /** `null` for `exif_gps_only` / `manual`. */
  match_result_id: Uuid | null;
  position: LatLon;
  altitude_m: number | null;
  orientation: Orientation;
  /** `> 0 AND < 180`. */
  hfov_deg: number | null;
  vfov_deg: number | null;
  /** Drives the Leaflet view cone. */
  footprint: GeoJsonPolygon | null;
  method: PoseMethod;
  /** ★ 0–100. */
  confidence: number;
  /** 9 floats, ROW-MAJOR, world→camera. */
  rotation_matrix: number[] | null;
  intrinsics: CameraIntrinsics | null;
  reproj_error_px: number | null;
  inlier_count: number | null;
  uncertainty: PoseUncertainty;
  ambiguity: PoseAmbiguity | null;
  is_selected: boolean;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

/** PATCH — the surveyor overrides an estimate. `method` becomes `manual`. */
export interface CameraPoseUpdate {
  position?: LatLon | undefined;
  altitude_m?: number | null | undefined;
  orientation?: OrientationInput | undefined;
  intrinsics?: CameraIntrinsicsInput | undefined;
  hfov_deg?: number | null | undefined;
  is_selected?: boolean | undefined;
}
