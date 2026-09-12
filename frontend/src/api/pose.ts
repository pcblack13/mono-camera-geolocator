/**
 * Camera pose — endpoint 48 (§7).
 *
 * ★★ DEFERRED — SCOPE.md §4. Camera pose (yaw/pitch/roll) estimation is an ABC only.
 *    The `camera_poses` table IS created and holds no rows (rule 5).
 *
 * ★ THE 404-vs-501 DISTINCTION, and it is not pedantry. §7 types endpoint 48 `200
 *   CameraPoseRead · 404` — the 404 (`CAMERA_POSE_NOT_AVAILABLE`) means *"this image
 *   has no pose row"*, which is a true statement about data. SCOPE.md §4 rule 3 says
 *   a deferred feature answers **`501`, not 404**, because *"the feature is planned,
 *   not absent"*. In this build both are true at once: the row is absent AND the
 *   producer is deferred.
 *
 *   **`501` is the honest answer** — a 404 would tell the UI "try another image",
 *   which is a lie: no image in this build has a pose, and none can. The distinction
 *   survives into the future, where a 404 will mean exactly what §7 says. Flagged for
 *   IU-21: endpoint 48 returns `501` while the estimator is deferred.
 */

import type { Uuid } from '../types/common';
import type { CameraPoseRead, CameraPoseUpdate } from '../types/pose';
import { fetchJson } from './client';

export const poseApi = {
  /** ★ DEFERRED — endpoint 48 `GET /images/{id}/camera-pose` → **`501`** in this build. */
  get: (imageId: Uuid, signal?: AbortSignal): Promise<CameraPoseRead> =>
    fetchJson<CameraPoseRead>(`/images/${imageId}/camera-pose`, { signal }),

  /**
   * ★ NOT IN §7 — IU-23 declares `CameraPoseUpdate` (§8.2's `pose.ts` row lists it)
   *   and the endpoint table has no PATCH for it. A surveyor-supplied pose would be a
   *   manual-mode feature in the spirit of SCOPE.md §5, but SCOPE.md does not call for
   *   one and inventing a second write surface for a deferred subsystem is exactly the
   *   churn SCOPE.md §7 forbids. **No hook calls this.** Flagged for IU-17/IU-21 as a
   *   type with no endpoint.
   */
  update: (
    imageId: Uuid,
    body: CameraPoseUpdate,
    etag?: string,
    signal?: AbortSignal,
  ): Promise<CameraPoseRead> =>
    fetchJson<CameraPoseRead>(`/images/${imageId}/camera-pose`, {
      method: 'PATCH',
      body,
      ifMatch: etag,
      signal,
    }),
};
