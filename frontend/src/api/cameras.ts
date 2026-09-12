/**
 * Cameras — the server-side registry (`/cameras/*`, 2026-09-02).
 *
 * ★ THE REGISTRY MOVED. Until 1.3 the cameras lived in ONE browser's
 *   `localStorage` (`le.cameras.v1`); a second machine saw nothing, and the
 *   `detection_events` a camera wrote named it by a string only that browser knew.
 *   `cameraRegistryStore` is now a CACHE of this API: every add/patch/remove goes
 *   through here first, and the store takes the server's answer.
 *
 * ★ `desired` IS INTENT, NOT STATUS. `CameraDesired` is what the operator asked the
 *   camera to be doing (a watch, a run, a feed); the API restarts it after a
 *   restart. Whether it is doing it NOW is the detection / drift / feed status.
 *
 * ★ No `fetch` here: every call goes through `client.ts` (§2.5).
 */

/* eslint-disable camelcase -- wire fields are snake_case (L9) */
import type { Page, Uuid } from '../types/common';
import { API_BASE_URL, fetchJson, toQuery } from './client';

/** ★ The three things that differ (narrowed 2026-09-11, see `cameraRegistryStore`):
 *  an address on the network, a capture device on this machine, a serial line. */
export type CameraConnection = 'lan' | 'usb' | 'serial';

/** The optional calibration entered on the camera itself — `ImageCameraPut`'s
 *  vocabulary minus the position (the registry's lat/lon IS the position). */
export interface CameraCalibration {
  fx: number | null;
  fy: number | null;
  cx: number | null;
  cy: number | null;
  k1: number | null;
  k2: number | null;
  p1: number | null;
  p2: number | null;
  k3: number | null;
  mast_offset_m: number | null;
  tilt_deg: number | null;
}
export type CameraProvides = 'camera' | 'data' | 'both';

export interface CameraDesiredWatch {
  ref_id: string;
  interval_s: number;
}

export interface CameraDesiredDetect {
  lut_site: string | null;
  conf: number;
  classes: number[] | null;
  imgsz: number;
  tile: boolean;
  model: string | null;
  tracker_start_frame: number;
  tracker_type: string;
  tracker_refresh_every: number;
  centre_marks: boolean;
  /** Steady boxes — absent on intents recorded before 2026-09-03 (defaults on). */
  steady_boxes?: boolean;
}

export interface CameraDesired {
  watch: CameraDesiredWatch | null;
  detect: CameraDesiredDetect | null;
  feed: boolean;
}

/** The registry attributes — what the add dialog collects, what the row stores. */
export interface CameraFields {
  name: string;
  lat: number;
  lon: number;
  source: string | null;
  connection: CameraConnection;
  provides: CameraProvides;
  data_source: string | null;
  heading_deg: number | null;
  fov_deg: number | null;
  fps: number | null;
  tags: string[];
  lut_site: string | null;
  /** The camera's backing project — its DEM, frame and control points live there. */
  project_id: Uuid | null;
  /** The frame chosen from this camera — the photograph the control points sit on. */
  frame_image_id: Uuid | null;
  calibration: CameraCalibration | null;
}

export interface CameraRead extends CameraFields {
  id: Uuid;
  desired: CameraDesired;
  created_at: string;
  updated_at: string;
}

/** `POST /cameras` body — every field optional except name/lat/lon. */
export type CameraCreate = Partial<CameraFields> & Pick<CameraFields, 'name' | 'lat' | 'lon'>;
/** `PATCH /cameras/{id}` — only the sent keys change. */
export type CameraUpdate = Partial<CameraFields>;

export interface CameraImportItem extends CameraCreate {
  /** The browser's old id (a ULID) — the result maps it to the server UUID. */
  client_id?: string;
}

export interface CameraImportResult {
  created: number;
  items: { client_id: string | null; id: Uuid; name: string }[];
}

/**
 * `POST /cameras/{id}/drift/freeze` — the drift reference now frozen on the
 * camera's FRAME (the photograph its control points sit on), and the background
 * watch on it (2026-09-08, owner decision). The monitoring page only reads.
 */
export interface CameraDriftRead {
  ref_id: string;
  interval_s: number;
  n_landmarks: number;
  frozen_from_label: string | null;
  created_utc: string;
  intrinsics_mode: 'calibration' | 'fov';
  intrinsics_warning: string | null;
  watching: boolean;
}

const path = (id: Uuid): string => `/cameras/${id}`;

export const camerasApi = {
  /** `GET /cameras` → `Page[CameraRead]`. */
  list: (q?: string, signal?: AbortSignal): Promise<Page<CameraRead>> =>
    fetchJson<Page<CameraRead>>('/cameras', { query: toQuery({ q, limit: 200 }), signal }),

  /** `GET /cameras/all` → every camera, by name — the globe draws all of them. */
  all: (signal?: AbortSignal): Promise<CameraRead[]> =>
    fetchJson<CameraRead[]>('/cameras/all', { signal }),

  /** `GET /cameras/{id}`. */
  get: (id: Uuid, signal?: AbortSignal): Promise<CameraRead> =>
    fetchJson<CameraRead>(path(id), { signal }),

  /**
   * ★ THE WHOLE CAMERA, ONE FILE (2026-09-12, owner ask). A zip holding the
   * registry row — name, connection, position, tags, calibration — beside every
   * artefact its setup produced: the frame captured and used, the control points,
   * the DEM, the processed DEM calibration, the lookup table and the frozen drift
   * reference. A half-configured camera exports too; the bundle's `camera.json`
   * names each step that had not happened rather than refusing.
   *
   * A direct URL, not a `fetchJson`: the browser downloads it.
   */
  exportUrl: (id: Uuid): string => `${API_BASE_URL}${path(id)}/export`,

  /** `POST /cameras` → `201 CameraRead`. A 422 names the rule that refused it. */
  create: (body: CameraCreate, signal?: AbortSignal): Promise<CameraRead> =>
    fetchJson<CameraRead>('/cameras', { method: 'POST', body, signal }),

  /** `PATCH /cameras/{id}` — send ONLY the changed fields. */
  update: (id: Uuid, body: CameraUpdate, signal?: AbortSignal): Promise<CameraRead> =>
    fetchJson<CameraRead>(path(id), { method: 'PATCH', body, signal }),

  /** `DELETE /cameras/{id}` → 204. Its watch / run / feed are stopped first. */
  remove: async (id: Uuid, signal?: AbortSignal): Promise<void> => {
    await fetchJson<void>(path(id), { method: 'DELETE', parse: 'none', signal });
  },

  /** `POST /cameras/import` → `201`. All or nothing; maps client ids to UUIDs. */
  import: (cameras: CameraImportItem[], signal?: AbortSignal): Promise<CameraImportResult> =>
    fetchJson<CameraImportResult>('/cameras/import', { method: 'POST', body: { cameras }, signal }),

  /** `PUT /cameras/{id}/desired` — intent only; starts nothing NOW. */
  setDesired: (id: Uuid, desired: CameraDesired, signal?: AbortSignal): Promise<CameraRead> =>
    fetchJson<CameraRead>(`${path(id)}/desired`, { method: 'PUT', body: desired, signal }),

  /**
   * `POST /cameras/{id}/drift/freeze` → 201. Freezes the drift reference on the
   * camera's frame with its lookup table and starts the background watch; a 422
   * names the missing piece (the table, the frame, or the pose).
   */
  freezeDrift: (id: Uuid, signal?: AbortSignal): Promise<CameraDriftRead> =>
    fetchJson<CameraDriftRead>(`${path(id)}/drift/freeze`, { method: 'POST', signal }),
};
