/**
 * `/drift/*` — camera drift references: freeze the trusted state, check it later.
 *
 * ★ WHAT A VERDICT CLAIMS, so no component implies more: the monitor measures
 *   CHANGE from the frozen reference, never correctness — a reference frozen on
 *   a wrong mapping reports OK forever. And the four states stay four: MOVED and
 *   CHANGED both mean "stop trusting the coordinates" (different remedies);
 *   DEGRADED means "cannot judge" and is NOT an alert.
 *
 * ★ `state` vs `status`: `state` is one frame's raw reading, `status` is the
 *   temporally confirmed verdict (three identical non-OK readings in a row).
 *   ALERT ON `status`, show `state` as telemetry — the vendor's own rule.
 */

import { API_BASE_URL, fetchJson } from './client';

export type DriftState = 'OK' | 'MOVED' | 'CHANGED' | 'DEGRADED';

export interface DriftFreezeRequest {
  name?: string;
  /** A live device/URL, or `video:<id>` — the same source grammar detection uses. */
  source: string;
  lut_site: string;
  alert_ground_m?: number;
  ref_range_m?: number | null;
  confirm_n?: number;
  n_landmarks?: number;
  /** `video:` sources — freeze from this clip second. Live sources ignore it. */
  at_s?: number | null;
  // ── GEO-DRIFT D1 / C1: where the reference is frozen from, and with what K ──
  /** Freeze on THIS photograph (the one the GCPs are on) rather than a fresh grab. */
  freeze_from_image_id?: string | null;
  /** Default true: freeze on the photograph the lookup table was built from, when known. */
  use_lut_image?: boolean;
  /** Derive K from a field of view — for a bundle with no intrinsics (`pose_needs_fov`). */
  no_calibration?: boolean;
  fov_h_deg?: number | null;
  fov_v_deg?: number | null;
  square_pixels?: boolean;
}

/** ★ GEO-DRIFT A2: which way the camera moved — pan (left/right), tilt (up/down), roll. */
export interface DriftAxisAngles {
  pan_deg: number;
  tilt_deg: number;
  roll_deg: number;
  axis_total_deg: number;
}

export interface DriftReference {
  ref_id: string;
  name: string;
  source: string;
  source_label: string;
  lut_site: string;
  created_utc: string;
  frame_width: number;
  frame_height: number;
  n_landmarks: number;
  alert_ground_m: number;
  ref_range_m: number;
  confirm_n: number;
  /** Freeze-time consistency smoke test (~0 on a real LUT by construction). */
  ref_reproj_mean_px: number;
  range_min_m: number;
  range_median_m: number;
  range_max_m: number;
  /** Clips: the second the reference was frozen from; null for live sources. */
  frozen_at_s?: number | null;
  // ── GEO-DRIFT D1 / C1: provenance ────────────────────────────────────────
  /** `image` (the GCP photograph), `clip` or `live` — how far the reference can be trusted. */
  frozen_from?: 'image' | 'clip' | 'live';
  frozen_from_label?: string | null;
  /** How THIS freeze obtained K. */
  intrinsics_mode?: 'calibration' | 'fov';
  fov?: { fov_h_deg: number; fov_v_deg: number; square_pixels: boolean } | null;
  /** How the LOOKUP TABLE obtained its K — a different question. */
  lut_intrinsics_mode?: 'calibration' | 'fov';
  /** Set when derived intrinsics measurably disagree with the table. */
  intrinsics_warning?: string | null;
}

export interface DriftVerdict {
  ref_id: string;
  checked_utc: string;
  /** Where the frame came from: a running detection session's tap, or a capture. */
  via: 'detector' | 'capture' | 'provider' | null;
  /** Clips: the second that was judged; null for live frames. */
  at_s?: number | null;
  /** The judged frame's size — the overlay's coordinate space. */
  frame_w?: number | null;
  frame_h?: number | null;
  /**
   * The FROZEN frame's outline inside the current frame, normalised 0–1, four
   * corners clockwise from top-left: the frame edge at zero drift, sliding off
   * as the camera turns. Null when no rotation was solved (DEGRADED).
   */
  outline?: [number, number][] | null;
  /** Each landmark: frozen at (u, v), found at (x, y) — null coords when lost. */
  landmarks?: { u: number; v: number; x: number | null; y: number | null }[] | null;
  state: DriftState;
  /** The confirmed verdict — the banner and any alerting render from THIS. */
  status: DriftState | null;
  confirmed: boolean;
  /** The server's honest sentence, shown verbatim. */
  why: string;
  n_landmarks: number;
  n_matched: number;
  n_lost: number;
  n_inliers: number | null;
  rot_deg: number | null;
  ground_err_at_ref: number | null;
  /** ★ A DEGRADED look re-read as a LARGE MOVE (2026-09-09): the picture's coherent shift, px. */
  large_move_px?: number | null;
  resid_mean_px: number | null;
  mean_conf: number | null;
  snr: number | null;
  /** ★ GEO-DRIFT A2: pan/tilt/roll of the move; null on DEGRADED. */
  angles?: DriftAxisAngles | null;
}

export interface DriftMonitor {
  ref_id: string;
  status: 'running' | 'stopped' | 'failed';
  source: string;
  interval_s: number;
  started_utc: string;
  checks_done: number;
  /** "Couldn't even look" (device busy) — distinct from any verdict. */
  capture_failures: number;
  last_error: string | null;
  last: DriftVerdict | null;
  history: DriftVerdict[];
}

export const driftApi = {
  references: (signal?: AbortSignal): Promise<{ items: DriftReference[] }> =>
    fetchJson<{ items: DriftReference[] }>('/drift/references', { signal }),

  freeze: (body: DriftFreezeRequest, signal?: AbortSignal): Promise<DriftReference> =>
    fetchJson<DriftReference>('/drift/references', { method: 'POST', body, signal }),

  /** `atS` (video sources): judge the clip's frame at that second — without it a
   *  clip check re-reads frame 0, which may be the frozen frame itself. */
  check: (refId: string, atS?: number, signal?: AbortSignal): Promise<DriftVerdict> =>
    fetchJson<DriftVerdict>(`/drift/references/${refId}/check`, {
      method: 'POST',
      body: atS === undefined ? {} : { at_s: atS },
      signal,
    }),

  /** Every monitor's state — the one poll the pill and the map banner share. */
  status: (signal?: AbortSignal): Promise<{ items: DriftMonitor[] }> =>
    fetchJson<{ items: DriftMonitor[] }>('/drift/status', { signal }),

  /** With a `cameraId` the watch is the camera's DESIRED state: the server restarts
   *  it after a restart, and a stop that names the camera clears it (1.3). */
  startMonitor: (
    refId: string,
    intervalS: number,
    cameraId?: string | null,
    signal?: AbortSignal,
  ): Promise<DriftMonitor> =>
    fetchJson<DriftMonitor>(`/drift/references/${refId}/monitor/start`, {
      method: 'POST',
      body: { interval_s: intervalS, ...(cameraId ? { camera_id: cameraId } : {}) },
      signal,
    }),

  stopMonitor: (
    refId: string,
    cameraId?: string | null,
    signal?: AbortSignal,
  ): Promise<DriftMonitor> =>
    fetchJson<DriftMonitor>(`/drift/references/${refId}/monitor/stop`, {
      method: 'POST',
      query: cameraId ? { camera_id: cameraId } : undefined,
      signal,
    }),

  /** ★ GEO-DRIFT B2: the field-unit export — a zip with everything an embedded box needs. */
  fieldUnitUrl: (refId: string): string =>
    `${API_BASE_URL}/drift/references/${encodeURIComponent(refId)}/field-unit`,
  remove: (refId: string, signal?: AbortSignal): Promise<void> =>
    fetchJson<void>(`/drift/references/${refId}`, { method: 'DELETE', signal }),
};
