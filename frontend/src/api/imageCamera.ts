/**
 * The photograph's entered camera — `/images/{id}/camera`.
 *
 * ★ NOT deferred (unlike `poseApi`): these endpoints are real CRUD over a real table.
 *   GET always answers 200 on a live image — `configured: false` with every field
 *   null is the honest "nothing saved yet", so there is no 404-as-state to special-case.
 */

import { fetchJson } from './client';
import type { Uuid } from '../types/common';
import type {
  AutoGcpEstimateRead,
  AutoGcpEstimateRequest,
  AutoGcpProjectRead,
  AutoGcpProjectRequest,
  ImageCameraPut,
  ImageCameraRead,
} from '../types/imageCamera';

/**
 * A saved camera → the PUT body that would reproduce it. ★ PUT is FULL-REPLACE, so a
 * caller flipping one field (the editor's "enable auto GCP picking" button) must send
 * everything it read back — this is the one honest way to do that.
 */
export function toPutBody(read: ImageCameraRead): ImageCameraPut {
  return {
    fx: read.fx,
    fy: read.fy,
    cx: read.cx,
    cy: read.cy,
    k1: read.k1,
    k2: read.k2,
    p1: read.p1,
    p2: read.p2,
    k3: read.k3,
    img_w: read.img_w,
    img_h: read.img_h,
    lat: read.lat,
    lon: read.lon,
    mast_offset_m: read.mast_offset_m,
    tilt_deg: read.tilt_deg,
    auto_gcp_enabled: read.auto_gcp_enabled,
    // ★ THE MODE TRAVELS TOO (2026-09-09). The PUT is full-replace, so leaving these
    //   out RESET a no-calibration station to "calibrated with no focal" every time
    //   the editor's Auto toggle wrote the station back — the seed typed at step 3
    //   vanished with it, and every solve was refused for "no intrinsics".
    no_calibration: read.no_calibration ?? false,
    fov_h_deg: read.fov_h_deg ?? null,
    fov_v_deg: read.fov_v_deg ?? null,
  };
}

export const imageCameraApi = {
  /** `GET /images/{id}/camera` → the station, or the `configured: false` shape. */
  get: (imageId: Uuid, signal?: AbortSignal): Promise<ImageCameraRead> =>
    fetchJson<ImageCameraRead>(`/images/${imageId}/camera`, { signal }),

  /**
   * `PUT /images/{id}/camera` — create or fully replace. ★ Full-replace semantics:
   * the setup page saves the whole form, and an omitted field IS a cleared field.
   */
  put: (imageId: Uuid, body: ImageCameraPut, signal?: AbortSignal): Promise<ImageCameraRead> =>
    fetchJson<ImageCameraRead>(`/images/${imageId}/camera`, {
      method: 'PUT',
      body,
      signal,
    }),

  /**
   * `POST /images/{id}/camera/estimate` — solve the pose from the photo's 4+ located
   * GCPs and intersect the pixel's ray with the project DEM. Read-only: creates no
   * row; prerequisite failures are 422s that NAME the missing piece.
   */
  estimate: (
    imageId: Uuid,
    body: AutoGcpEstimateRequest,
    signal?: AbortSignal,
  ): Promise<AutoGcpEstimateRead> =>
    fetchJson<AutoGcpEstimateRead>(`/images/${imageId}/camera/estimate`, {
      method: 'POST',
      body,
      signal,
    }),

  /**
   * `POST /images/{id}/camera/project` — the estimate run BACKWARDS: world
   * coordinate → the pixel where it appears through the solved pose. Read-only;
   * off-DEM and behind-camera are 422s that say so.
   */
  project: (
    imageId: Uuid,
    body: AutoGcpProjectRequest,
    signal?: AbortSignal,
  ): Promise<AutoGcpProjectRead> =>
    fetchJson<AutoGcpProjectRead>(`/images/${imageId}/camera/project`, {
      method: 'POST',
      body,
      signal,
    }),

  /** `DELETE /images/{id}/camera` — idempotent; 204 either way. */
  remove: (imageId: Uuid, signal?: AbortSignal): Promise<void> =>
    fetchJson<void>(`/images/${imageId}/camera`, {
      method: 'DELETE',
      parse: 'none',
      signal,
    }),
};
