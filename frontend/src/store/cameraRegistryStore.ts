/**
 * `store/cameraRegistryStore.ts` — the cameras the operator has placed on the globe.
 *
 * ★ A CACHE OF THE SERVER, SINCE 1.3 (2026-09-02). The registry used to be CLIENT
 *   STATE ONLY, persisted under `le.cameras.v1` — which meant a second machine
 *   saw no cameras, a cleared browser lost them, and a `detection_events` row named
 *   its camera by a string only this browser knew. The rows now live in the
 *   `cameras` table (`api/cameras.ts`); this store holds what the server last
 *   said, so the globe draws instantly and works offline, and every add / patch /
 *   remove goes to the API FIRST and takes the server's answer. Ids are the
 *   server's UUIDs; a ULID here is a pre-1.3 row that was never migrated —
 *   `CameraRegistrySync` offers to import those once, then forgets them.
 *
 * ★ VALIDATION RETURNS A RESULT, NEVER THROWS, AND NEVER GUESSES (L12). A NaN, an
 *   out-of-range number or an empty source is refused with the field named. A
 *   latitude beyond ±90 that would be a fine longitude — the classic transposed
 *   pair — is refused WITH A HINT and the dialog offers a one-click swap; the
 *   store itself never swaps, because a silently corrected coordinate is a camera
 *   on the wrong continent that nobody was told about. The server restates the
 *   same rules (`schemas/camera.py`); this copy answers before the round trip.
 *
 * ★ STATUS IS TRANSIENT. `live / connecting / lost / refused / unknown` is what the
 *   last detail page or hover probe SAW — the globe shows it without opening a
 *   socket per marker. It is deliberately not persisted: a status from yesterday
 *   presented as current would be a lie, so a reload starts every camera at
 *   "never opened".
 */

/* eslint-disable camelcase -- the registry's field names are the brief's own
   (`heading_deg`, `fov_deg`, `created_at`), snake_case like the wire it mirrors. */
import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';

import type {
  CameraCalibration,
  CameraCreate,
  CameraDesired,
  CameraImportItem,
  CameraRead,
  CameraUpdate,
} from '../api/cameras';
import { camerasApi } from '../api/cameras';
import { asUuid } from '../types/common';
import { useMonitorSettingsStore } from './monitorSettingsStore';

/**
 * How an integration physically reaches the app.
 *
 * ★ THREE KINDS, BECAUSE THERE ARE THREE ANSWERS (2026-09-11, owner decision).
 *   The eight before it — lan, stream, hdmi, usb, bnc, serial, uart, embedded —
 *   asked the operator for exactly three things: an address on the network, a
 *   capture device on this machine, or a serial port. A Pi and an IP camera are
 *   both an address; HDMI, BNC and USB are all a capture card; serial and UART
 *   are one line. The extra labels bought nothing and had to be chosen between.
 *   Migration 0023 folds every stored row the same way.
 */
export type CameraConnection = 'lan' | 'usb' | 'serial';

export const CAMERA_CONNECTIONS: readonly CameraConnection[] = ['lan', 'usb', 'serial'];

/** The kind that carries DATA and no picture. */
export const DATA_ONLY_CONNECTIONS: readonly CameraConnection[] = ['serial'];
/** The kind whose source is a capture DEVICE on this machine, not an address. */
export const DEVICE_CONNECTIONS: readonly CameraConnection[] = ['usb'];

export const isCameraConnection = (v: unknown): v is CameraConnection =>
  typeof v === 'string' && (CAMERA_CONNECTIONS as readonly string[]).includes(v);

export type { CameraCalibration } from '../api/cameras';

/**
 * What the integration DELIVERS. A LAN or HDMI camera gives pictures the app can
 * run detection on; a serial/UART device gives DATA — detections with
 * coordinates, plotted straight onto the map; an embedded system (a Pi) may give
 * either or both.
 */
export type CameraProvides = 'camera' | 'data' | 'both';

export interface RegisteredCamera {
  /** The server's UUID (a ULID marks a pre-1.3 row awaiting migration). */
  id: string;
  name: string;
  /** -90..90, WGS84. Named — never a tuple. */
  lat: number;
  /** -180..180, WGS84. */
  lon: number;
  /** The VIDEO source: http(s) MJPEG/snapshot, rtsp://, or a local device path.
   *  Empty for a data-only integration — there is no picture to open. */
  source: string;
  /** Default 'lan'. Older rows lack it; every reader must default. */
  connection?: CameraConnection;
  /** Default 'camera'. */
  provides?: CameraProvides;
  /** The DATA feed, when `provides` includes data: `serial:///dev/ttyUSB0?baud=115200`
   *  (or a bare `/dev/tty…` path) or an http(s) URL streaming JSON/CSV lines. */
  data_source?: string;
  /** 0..360; draws the FOV wedge on the globe. */
  heading_deg?: number;
  /** Default 60. */
  fov_deg?: number;
  /** 1..30. */
  fps?: number;
  tags?: string[];
  /** The LUT bundle last applied to this camera on the server (a library site name). */
  lut_site?: string;
  /** The camera's backing project (2026-09-04) — its DEM, frame and control points. */
  project_id?: string;
  /** The frame chosen from this camera — the photograph the control points sit on. */
  frame_image_id?: string;
  /** Optional intrinsics / mast / tilt entered on the camera itself. */
  calibration?: CameraCalibration;
  /** What the server will restart for this camera after a restart — intent, not status. */
  desired?: CameraDesired;
  /** ISO. */
  created_at: string;
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** A server id, as opposed to a pre-1.3 browser ULID. */
export const isServerCameraId = (id: string): boolean => UUID_RE.test(id);

/** One server row → the registry's shape (nulls become absent, as the dialog writes them). */
export function fromServer(row: CameraRead): RegisteredCamera {
  return {
    id: row.id,
    name: row.name,
    lat: row.lat,
    lon: row.lon,
    source: row.source ?? '',
    ...(row.connection !== 'lan' ? { connection: row.connection } : {}),
    ...(row.provides !== 'camera' ? { provides: row.provides } : {}),
    ...(row.data_source ? { data_source: row.data_source } : {}),
    ...(row.heading_deg !== null ? { heading_deg: row.heading_deg } : {}),
    ...(row.fov_deg !== null ? { fov_deg: row.fov_deg } : {}),
    ...(row.fps !== null ? { fps: row.fps } : {}),
    ...(row.tags.length > 0 ? { tags: row.tags } : {}),
    ...(row.lut_site ? { lut_site: row.lut_site } : {}),
    ...(row.project_id ? { project_id: row.project_id } : {}),
    ...(row.frame_image_id ? { frame_image_id: row.frame_image_id } : {}),
    ...(row.calibration ? { calibration: row.calibration } : {}),
    desired: row.desired,
    created_at: row.created_at,
  };
}

/** The registry's shape → what `POST /cameras` takes. */
export function toCreate(value: Omit<RegisteredCamera, 'id' | 'created_at'>): CameraCreate {
  return {
    name: value.name,
    lat: value.lat,
    lon: value.lon,
    source: value.source === '' ? null : value.source,
    connection: value.connection ?? 'lan',
    provides: value.provides ?? 'camera',
    data_source: value.data_source ?? null,
    heading_deg: value.heading_deg ?? null,
    fov_deg: value.fov_deg ?? null,
    fps: value.fps ?? null,
    tags: value.tags ?? [],
    lut_site: value.lut_site ?? null,
    project_id: value.project_id ? asUuid(value.project_id) : null,
    frame_image_id: value.frame_image_id ? asUuid(value.frame_image_id) : null,
    calibration: value.calibration ?? null,
  };
}

export type CameraStatusState = 'unknown' | 'connecting' | 'live' | 'lost' | 'refused';

export interface CameraStatus {
  state: CameraStatusState;
  /** Epoch ms of the observation. */
  at: number;
  /** The server's verbatim refusal, when `state` is `refused`. */
  message?: string;
}

/** What the add dialog collects — every field as typed, before validation. */
export interface CameraInput {
  name?: unknown;
  lat?: unknown;
  lon?: unknown;
  source?: unknown;
  connection?: unknown;
  provides?: unknown;
  data_source?: unknown;
  heading_deg?: unknown;
  fov_deg?: unknown;
  fps?: unknown;
  tags?: unknown;
  // ── the setup pipeline (2026-09-04): carried through, calibration judged ─────
  lut_site?: unknown;
  project_id?: unknown;
  frame_image_id?: unknown;
  calibration?: unknown;
}

export interface CameraValidationError {
  field: keyof RegisteredCamera | 'row';
  message: string;
  /** The dialog offers a one-click swap when lat/lon look transposed. */
  hint?: 'swap';
}

export type Result<T, E> = { ok: true; value: T } | { ok: false; errors: E[] };

const num = (v: unknown): number | null => {
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  if (typeof v === 'string' && v.trim() !== '') {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  return null;
};

export const CALIBRATION_KEYS = [
  'fx',
  'fy',
  'cx',
  'cy',
  'k1',
  'k2',
  'p1',
  'p2',
  'k3',
  'mast_offset_m',
  'tilt_deg',
] as const;
export type CalibrationKey = (typeof CALIBRATION_KEYS)[number];

/**
 * Judge the optional calibration as typed (strings or numbers, blanks allowed).
 * Nothing entered → `undefined` (stored as NULL, never a blob of nulls); a
 * non-number, a focal length ≤ 0 or a tilt beyond ±90° is refused by name.
 */
export function validateCalibration(
  raw: unknown,
): Result<CameraCalibration | undefined, CameraValidationError> {
  if (raw === undefined || raw === null) return { ok: true, value: undefined };
  if (typeof raw !== 'object') {
    return {
      ok: false,
      errors: [{ field: 'calibration', message: 'Calibration must be an object.' }],
    };
  }
  const r = raw as Record<string, unknown>;
  const errors: CameraValidationError[] = [];
  const out: Record<CalibrationKey, number | null> = {
    fx: null,
    fy: null,
    cx: null,
    cy: null,
    k1: null,
    k2: null,
    p1: null,
    p2: null,
    k3: null,
    mast_offset_m: null,
    tilt_deg: null,
  };
  for (const key of CALIBRATION_KEYS) {
    const v = r[key];
    if (v === undefined || v === null || v === '') continue;
    const n = num(v);
    if (n === null) {
      errors.push({ field: 'calibration', message: `${key} must be a number.` });
      continue;
    }
    if ((key === 'fx' || key === 'fy') && n <= 0) {
      errors.push({ field: 'calibration', message: `${key} must be a positive number of pixels.` });
      continue;
    }
    if (key === 'tilt_deg' && (n < -90 || n > 90)) {
      errors.push({ field: 'calibration', message: 'Tilt must be between -90° and 90°.' });
      continue;
    }
    out[key] = n;
  }
  if (errors.length > 0) return { ok: false, errors };
  if (CALIBRATION_KEYS.every((k) => out[k] === null)) return { ok: true, value: undefined };
  return { ok: true, value: out };
}

/** http(s), rtsp, or a local device. */
export function looksLikeSource(source: string): boolean {
  const s = source.trim();
  if (s === '') return false;
  if (/^(https?|rtsp):\/\/\S+/i.test(s)) return true;
  // Local devices: `/dev/video0`, a DirectShow index, `device:N`.
  return /^(\/dev\/\S+|\d+|device:\S+)$/i.test(s);
}

/**
 * A DATA feed: a serial port (`serial://…` / `/dev/tty…`) or an http(s) line
 * stream sending detections.
 */
export function looksLikeDataSource(source: string): boolean {
  const s = source.trim();
  if (s === '') return false;
  // ★ ws(s):// and tcp:// joined on 2026-09-11 — `live_data_service` opens them.
  return /^(serial:\/\/\S+|\/dev\/tty\S+|(https?|wss?|tcp):\/\/\S+)$/i.test(s);
}

/**
 * Validate one camera's fields. Returns EVERY problem, so a dialog can show them
 * all at once instead of one per submit.
 */
export function validateCamera(
  input: CameraInput,
): Result<Omit<RegisteredCamera, 'id' | 'created_at'>, CameraValidationError> {
  const errors: CameraValidationError[] = [];
  const name = typeof input.name === 'string' ? input.name.trim() : '';
  if (name === '') errors.push({ field: 'name', message: 'Give the camera a name.' });

  const lat = num(input.lat);
  const lon = num(input.lon);
  if (lat === null) errors.push({ field: 'lat', message: 'Latitude must be a number.' });
  if (lon === null) errors.push({ field: 'lon', message: 'Longitude must be a number.' });
  const latBad = lat !== null && (lat < -90 || lat > 90);
  const lonBad = lon !== null && (lon < -180 || lon > 180);
  // ★ The transposed pair: refused, with the fix named — never applied silently.
  if (
    lat !== null &&
    lon !== null &&
    latBad &&
    !lonBad &&
    Math.abs(lon) <= 90 &&
    Math.abs(lat) <= 180
  ) {
    errors.push({
      field: 'lat',
      message: `Latitude ${lat} is outside ±90 — but it would be a valid longitude. Were the two swapped?`,
      hint: 'swap',
    });
  } else {
    if (latBad) errors.push({ field: 'lat', message: 'Latitude must be between -90 and 90.' });
    if (lonBad) errors.push({ field: 'lon', message: 'Longitude must be between -180 and 180.' });
  }

  // ── the integration: how it connects, and what it delivers (2026-09-02) ─────
  const connection: CameraConnection = isCameraConnection(input.connection)
    ? input.connection
    : 'lan';
  const dataOnly = DATA_ONLY_CONNECTIONS.includes(connection);
  const provides: CameraProvides =
    input.provides === 'data' || input.provides === 'both'
      ? input.provides
      : // ★ Serial/UART carries no picture; saying otherwise would promise a video
        //   nothing can deliver. It is DATA, whatever the caller typed.
        dataOnly
        ? 'data'
        : 'camera';
  if (dataOnly && input.provides === 'camera') {
    errors.push({
      field: 'source',
      message: 'A serial / UART connection carries detection data, not video.',
    });
  }

  const source = typeof input.source === 'string' ? input.source.trim() : '';
  const data_source = typeof input.data_source === 'string' ? input.data_source.trim() : '';
  // A video source is required exactly when the integration PROVIDES video.
  if (provides !== 'data') {
    if (source === '') errors.push({ field: 'source', message: 'A source is required.' });
    else if (!looksLikeSource(source)) {
      errors.push({
        field: 'source',
        message:
          'The source must be an http(s) or rtsp:// URL, or a local device (e.g. /dev/video0).',
      });
    }
  }
  // A data feed is required exactly when the integration PROVIDES data.
  if (provides !== 'camera') {
    if (data_source === '') {
      errors.push({
        field: 'data_source',
        message: 'A data feed is required — a serial port or an http(s) URL sending detections.',
      });
    } else if (!looksLikeDataSource(data_source)) {
      errors.push({
        field: 'data_source',
        message:
          'The data feed must be a serial port (serial:///dev/ttyUSB0?baud=115200 or /dev/tty…), an http(s) URL, a ws(s):// websocket, or tcp://host:port.',
      });
    }
  }

  let heading_deg: number | undefined;
  if (input.heading_deg !== undefined && input.heading_deg !== '' && input.heading_deg !== null) {
    const h = num(input.heading_deg);
    if (h === null || h < 0 || h > 360) {
      errors.push({ field: 'heading_deg', message: 'Heading must be 0–360°.' });
    } else heading_deg = h;
  }
  let fov_deg: number | undefined;
  if (input.fov_deg !== undefined && input.fov_deg !== '' && input.fov_deg !== null) {
    const f = num(input.fov_deg);
    if (f === null || f <= 0 || f > 180) {
      errors.push({ field: 'fov_deg', message: 'Field of view must be 1–180°.' });
    } else fov_deg = f;
  }
  let fps: number | undefined;
  if (input.fps !== undefined && input.fps !== '' && input.fps !== null) {
    const f = num(input.fps);
    if (f === null || f < 1 || f > 30) errors.push({ field: 'fps', message: 'FPS must be 1–30.' });
    else fps = Math.round(f);
  }
  let tags: string[] | undefined;
  if (Array.isArray(input.tags)) {
    tags = input.tags.filter((x): x is string => typeof x === 'string' && x.trim() !== '');
    if (tags.length === 0) tags = undefined;
  }
  // ── the setup pipeline's fields ride along (2026-09-04) ─────────────────────
  const idOf = (v: unknown): string | undefined =>
    typeof v === 'string' && v.trim() !== '' ? v.trim() : undefined;
  const lut_site = idOf(input.lut_site);
  const project_id = idOf(input.project_id);
  const frame_image_id = idOf(input.frame_image_id);
  const calibrationResult = validateCalibration(input.calibration);
  if (!calibrationResult.ok) errors.push(...calibrationResult.errors);
  const calibration = calibrationResult.ok ? calibrationResult.value : undefined;

  if (errors.length > 0) return { ok: false, errors };
  return {
    ok: true,
    value: {
      name,
      lat: lat as number,
      lon: lon as number,
      source,
      // The defaults stay OFF the stored row — an old export imports unchanged.
      ...(connection !== 'lan' ? { connection } : {}),
      ...(provides !== 'camera' ? { provides } : {}),
      ...(data_source !== '' ? { data_source } : {}),
      ...(heading_deg !== undefined ? { heading_deg } : {}),
      ...(fov_deg !== undefined ? { fov_deg } : {}),
      ...(fps !== undefined ? { fps } : {}),
      ...(tags !== undefined ? { tags } : {}),
      ...(lut_site !== undefined ? { lut_site } : {}),
      ...(project_id !== undefined ? { project_id } : {}),
      ...(frame_image_id !== undefined ? { frame_image_id } : {}),
      ...(calibration !== undefined ? { calibration } : {}),
    },
  };
}

/** One pasted CSV line, judged: `name,lat,lon,source[,heading,fov]`. */
export interface CsvRow {
  line: number;
  raw: string;
  result: ReturnType<typeof validateCamera>;
}

/** Split CSV text into judged rows. Blank lines and a header row are skipped. */
export function parseCameraCsv(text: string): CsvRow[] {
  const rows: CsvRow[] = [];
  const lines = text.split(/\r?\n/);
  lines.forEach((raw, i) => {
    const line = raw.trim();
    if (line === '') return;
    const cells = line.split(',').map((c) => c.trim());
    // A header: first cell says "name" and the lat cell is not a number.
    if (i === 0 && /^name$/i.test(cells[0] ?? '') && num(cells[1]) === null) return;
    if (cells.length < 4) {
      rows.push({
        line: i + 1,
        raw,
        result: {
          ok: false,
          errors: [{ field: 'row', message: 'Expected name,lat,lon,source[,heading,fov].' }],
        },
      });
      return;
    }
    const [name, lat, lon, source, heading_deg, fov_deg] = cells;
    rows.push({
      line: i + 1,
      raw,
      result: validateCamera({ name, lat, lon, source, heading_deg, fov_deg }),
    });
  });
  return rows;
}

/** Re-validate one persisted row — anything off-shape is dropped, never repaired. */
function reviveCamera(raw: unknown): RegisteredCamera | null {
  if (!raw || typeof raw !== 'object') return null;
  const r = raw as Record<string, unknown>;
  const checked = validateCamera(r);
  if (!checked.ok) return null;
  if (typeof r.id !== 'string' || r.id.trim() === '') return null;
  const created_at =
    typeof r.created_at === 'string' && !Number.isNaN(Date.parse(r.created_at))
      ? r.created_at
      : new Date(0).toISOString();
  return { id: r.id, created_at, ...checked.value };
}

export interface CameraRegistryState {
  cameras: RegisteredCamera[];
  /** Transient — see the header. Keyed by camera id. */
  statuses: Record<string, CameraStatus>;
  /** Rows the last rehydrate refused. Shown once as a warning; not persisted. */
  droppedOnLoad: number;
  /** True once the server's list has replaced the cached one this session. */
  hydrated: boolean;
  /** Pre-1.3 browser rows found at hydrate time — offered for import once, then gone. */
  legacy: RegisteredCamera[];

  /** `POST /cameras`, then the server's row joins the list. Rejects on a refusal. */
  add: (value: Omit<RegisteredCamera, 'id' | 'created_at'>) => Promise<RegisteredCamera>;
  /** `PATCH /cameras/{id}` with the changed fields, then the server's row replaces ours. */
  update: (
    id: string,
    patch: Partial<Omit<RegisteredCamera, 'id' | 'created_at'>>,
  ) => Promise<void>;
  /** `DELETE /cameras/{id}` — the server stops its watch / run / feed first. */
  remove: (id: string) => Promise<void>;
  setStatus: (id: string, state: CameraStatusState, message?: string) => void;
  /** Import an exported JSON document: known ids are patched, the rest created. */
  importJson: (
    text: string,
  ) => Promise<Result<{ added: number; updated: number }, CameraValidationError>>;
  exportJson: () => string;
  acknowledgeDropped: () => void;
  /** The server's list replaces the cache; pre-1.3 rows are set aside as `legacy`. */
  hydrate: (rows: CameraRead[]) => void;
  /** Send the legacy rows to `POST /cameras/import`, re-key their saved setups, forget them. */
  migrateLegacy: () => Promise<number>;
  discardLegacy: () => void;
}

const EMPTY_STATUS: CameraStatus = { state: 'unknown', at: 0 };

export const useCameraRegistryStore = create<CameraRegistryState>()(
  devtools(
    persist(
      (set, get) => ({
        cameras: [],
        statuses: {},
        droppedOnLoad: 0,
        hydrated: false,
        legacy: [],

        add: async (value) => {
          const camera = fromServer(await camerasApi.create(toCreate(value)));
          set((s) => ({ cameras: [...s.cameras, camera] }), false, 'cameras/add');
          return camera;
        },

        update: async (id, patch) => {
          const current = get().cameras.find((c) => c.id === id);
          if (current === undefined) return;
          const checked = validateCamera({ ...current, ...patch });
          if (!checked.ok) return;
          // Only the keys the caller sent travel — a PATCH is not a PUT.
          const body: CameraUpdate = {};
          const full = toCreate(checked.value);
          for (const key of Object.keys(patch) as (keyof CameraUpdate)[]) {
            if (key in full) (body as Record<string, unknown>)[key] = full[key];
          }
          const row = fromServer(await camerasApi.update(asUuid(id), body));
          set(
            (s) => ({ cameras: s.cameras.map((c) => (c.id === id ? row : c)) }),
            false,
            'cameras/update',
          );
        },

        remove: async (id) => {
          if (isServerCameraId(id)) await camerasApi.remove(asUuid(id));
          // ★ The camera's saved monitor setup leaves with it — an orphaned setup
          //   for an id nobody can mint again is dead weight in localStorage.
          useMonitorSettingsStore.getState().forget(id);
          set(
            (s) => {
              const statuses = { ...s.statuses };
              delete statuses[id];
              return { cameras: s.cameras.filter((c) => c.id !== id), statuses };
            },
            false,
            'cameras/remove',
          );
        },

        setStatus: (id, state, message) =>
          set(
            (s) => ({
              statuses: {
                ...s.statuses,
                [id]: { state, at: Date.now(), ...(message !== undefined ? { message } : {}) },
              },
            }),
            false,
            'cameras/setStatus',
          ),

        importJson: async (text) => {
          let parsed: unknown;
          try {
            parsed = JSON.parse(text);
          } catch {
            return {
              ok: false,
              errors: [{ field: 'row', message: 'That file is not valid JSON.' }],
            };
          }
          const list = Array.isArray(parsed)
            ? parsed
            : parsed &&
                typeof parsed === 'object' &&
                Array.isArray((parsed as { cameras?: unknown }).cameras)
              ? (parsed as { cameras: unknown[] }).cameras
              : null;
          if (list === null) {
            return {
              ok: false,
              errors: [
                { field: 'row', message: 'Expected an array of cameras, or {"cameras": [...]}.' },
              ],
            };
          }
          // ★ Every row is judged BEFORE anything is sent — a document with one bad
          //   row changes nothing, here or on the server (the import is all-or-nothing).
          const errors: CameraValidationError[] = [];
          const known = new Set(get().cameras.map((c) => c.id));
          const toPatch: { id: string; value: Omit<RegisteredCamera, 'id' | 'created_at'> }[] = [];
          const toCreateRows: CameraImportItem[] = [];
          list.forEach((raw, i) => {
            const checked = validateCamera((raw ?? {}) as CameraInput);
            if (!checked.ok) {
              errors.push(
                ...checked.errors.map((e) => ({ ...e, message: `Row ${i + 1}: ${e.message}` })),
              );
              return;
            }
            const id =
              raw && typeof raw === 'object' && typeof (raw as { id?: unknown }).id === 'string'
                ? (raw as { id: string }).id
                : '';
            if (id !== '' && known.has(id) && isServerCameraId(id))
              toPatch.push({ id, value: checked.value });
            else
              toCreateRows.push({ ...toCreate(checked.value), ...(id ? { client_id: id } : {}) });
          });
          if (errors.length > 0) return { ok: false, errors };

          const updatedRows: RegisteredCamera[] = [];
          for (const { id, value } of toPatch) {
            updatedRows.push(fromServer(await camerasApi.update(asUuid(id), toCreate(value))));
          }
          let addedRows: RegisteredCamera[] = [];
          if (toCreateRows.length > 0) {
            const result = await camerasApi.import(toCreateRows);
            // the server answers with ids; re-read the rows for their full shape
            const fresh = await camerasApi.all();
            const ids = new Set(result.items.map((it) => it.id));
            addedRows = fresh.filter((r) => ids.has(r.id)).map(fromServer);
          }
          set(
            (s) => {
              const byId = new Map(s.cameras.map((c) => [c.id, c]));
              for (const c of [...updatedRows, ...addedRows]) byId.set(c.id, c);
              return { cameras: [...byId.values()] };
            },
            false,
            'cameras/importJson',
          );
          return { ok: true, value: { added: addedRows.length, updated: updatedRows.length } };
        },

        exportJson: () => JSON.stringify({ version: 1, cameras: get().cameras }, null, 2),

        hydrate: (rows) =>
          set(
            (s) => {
              const legacy = s.hydrated
                ? s.legacy
                : s.cameras.filter((c) => !isServerCameraId(c.id));
              return { cameras: rows.map(fromServer), hydrated: true, legacy };
            },
            false,
            'cameras/hydrate',
          ),

        migrateLegacy: async () => {
          const legacy = get().legacy;
          if (legacy.length === 0) return 0;
          const result = await camerasApi.import(
            legacy.map((c) => ({ ...toCreate(c), client_id: c.id })),
          );
          // ★ The per-camera monitor setup follows the camera to its new id: an
          //   operator who migrates ten cameras must not re-enter ten setups.
          const settings = useMonitorSettingsStore.getState();
          for (const item of result.items) {
            if (item.client_id) settings.rekey(item.client_id, item.id);
          }
          const fresh = await camerasApi.all();
          set(
            { cameras: fresh.map(fromServer), legacy: [], hydrated: true },
            false,
            'cameras/migrateLegacy',
          );
          return result.created;
        },

        discardLegacy: () => {
          const settings = useMonitorSettingsStore.getState();
          for (const c of get().legacy) settings.forget(c.id);
          set({ legacy: [] }, false, 'cameras/discardLegacy');
        },

        acknowledgeDropped: () => set({ droppedOnLoad: 0 }, false, 'cameras/acknowledgeDropped'),
      }),
      {
        name: 'le.cameras.v1',
        version: 1,
        partialize: (s) => ({ cameras: s.cameras }),
        // ★ The validating merge. Every persisted row is re-judged by the same
        //   validator the dialog uses; the ones that fail are counted, not trusted.
        merge: (persisted, current) => {
          const raw = (persisted as { cameras?: unknown } | undefined)?.cameras;
          if (!Array.isArray(raw)) return current;
          const cameras: RegisteredCamera[] = [];
          const seen = new Set<string>();
          let dropped = 0;
          for (const row of raw) {
            const c = reviveCamera(row);
            if (c === null || seen.has(c.id)) {
              dropped += 1;
              continue;
            }
            seen.add(c.id);
            cameras.push(c);
          }
          if (dropped > 0) {
            // eslint-disable-next-line no-console
            console.warn(`camera registry: dropped ${dropped} corrupt row(s) on load`);
          }
          return {
            ...current,
            cameras,
            statuses: {},
            droppedOnLoad: dropped,
            hydrated: false,
            legacy: [],
          };
        },
      },
    ),
    { name: 'cameraRegistryStore' },
  ),
);

// ── selectors — subscribe with these, never with the whole store ─────────────

export const selectCameras = (s: CameraRegistryState): RegisteredCamera[] => s.cameras;
export const selectCameraById =
  (id: string | undefined) =>
  (s: CameraRegistryState): RegisteredCamera | undefined =>
    id === undefined ? undefined : s.cameras.find((c) => c.id === id);
export const selectCameraStatus =
  (id: string) =>
  (s: CameraRegistryState): CameraStatus =>
    s.statuses[id] ?? EMPTY_STATUS;
/** Boolean per-camera selectors — a marker re-renders only when ITS answer flips. */
export const selectIsLive =
  (id: string) =>
  (s: CameraRegistryState): boolean =>
    s.statuses[id]?.state === 'live';
export const selectIsLost =
  (id: string) =>
  (s: CameraRegistryState): boolean =>
    s.statuses[id]?.state === 'lost' || s.statuses[id]?.state === 'refused';
export const selectLiveCount = (s: CameraRegistryState): number =>
  s.cameras.filter((c) => s.statuses[c.id]?.state === 'live').length;
export const selectLostCount = (s: CameraRegistryState): number =>
  s.cameras.filter((c) => {
    const st = s.statuses[c.id]?.state;
    return st === 'lost' || st === 'refused';
  }).length;
