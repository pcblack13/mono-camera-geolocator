/**
 * An in-memory stand-in for `camerasApi` (1.3) — the registry tests drive the
 * store through the same calls the app makes, against a server that lives in a
 * Map. UUIDs are minted deterministically so assertions can read them back.
 */

/* eslint-disable camelcase -- wire fields */
import type {
  CameraCreate,
  CameraDesired,
  CameraDriftRead,
  CameraImportItem,
  CameraImportResult,
  CameraRead,
  CameraUpdate,
} from '../api/cameras';

const EMPTY_DESIRED: CameraDesired = { watch: null, detect: null, feed: false };

let counter = 0;
export function fakeUuid(): string {
  counter += 1;
  return `00000000-0000-4000-8000-${String(counter).padStart(12, '0')}`;
}

export function makeFakeCamerasApi(): {
  rows: Map<string, CameraRead>;
  api: {
    all: () => Promise<CameraRead[]>;
    get: (id: string) => Promise<CameraRead>;
    create: (body: CameraCreate) => Promise<CameraRead>;
    update: (id: string, body: CameraUpdate) => Promise<CameraRead>;
    remove: (id: string) => Promise<void>;
    import: (cameras: CameraImportItem[]) => Promise<CameraImportResult>;
    setDesired: (id: string, desired: CameraDesired) => Promise<CameraRead>;
    freezeDrift: (id: string) => Promise<CameraDriftRead>;
    /** The whole-camera export — a plain URL the browser downloads (2026-09-12). */
    exportUrl: (id: string) => string;
    list: () => Promise<never>;
  };
} {
  const rows = new Map<string, CameraRead>();
  const now = (): string => new Date().toISOString();
  const rowOf = (body: CameraCreate, id: string): CameraRead => ({
    id: id as CameraRead['id'],
    name: body.name,
    lat: body.lat,
    lon: body.lon,
    source: body.source ?? null,
    connection: body.connection ?? 'lan',
    provides: body.provides ?? 'camera',
    data_source: body.data_source ?? null,
    heading_deg: body.heading_deg ?? null,
    fov_deg: body.fov_deg ?? null,
    fps: body.fps ?? null,
    tags: body.tags ?? [],
    lut_site: body.lut_site ?? null,
    project_id: body.project_id ?? null,
    frame_image_id: body.frame_image_id ?? null,
    calibration: body.calibration ?? null,
    desired: EMPTY_DESIRED,
    created_at: now(),
    updated_at: now(),
  });
  const api = {
    all: async (): Promise<CameraRead[]> => [...rows.values()],
    get: async (id: string): Promise<CameraRead> => {
      const row = rows.get(id);
      if (!row) throw new Error('No camera');
      return row;
    },
    create: async (body: CameraCreate): Promise<CameraRead> => {
      if (!body.name) throw new Error('a camera needs a name');
      const row = rowOf(body, fakeUuid());
      rows.set(row.id, row);
      return row;
    },
    update: async (id: string, body: CameraUpdate): Promise<CameraRead> => {
      const row = rows.get(id);
      if (!row) throw new Error('No camera');
      const next = { ...row, ...body, updated_at: now() } as CameraRead;
      rows.set(id, next);
      return next;
    },
    remove: async (id: string): Promise<void> => {
      rows.delete(id);
    },
    import: async (cameras: CameraImportItem[]): Promise<CameraImportResult> => {
      const items = cameras.map((c) => {
        const row = rowOf(c, fakeUuid());
        rows.set(row.id, row);
        return { client_id: c.client_id ?? null, id: row.id, name: row.name };
      });
      return { created: items.length, items };
    },
    setDesired: async (id: string, desired: CameraDesired): Promise<CameraRead> => {
      const row = rows.get(id);
      if (!row) throw new Error('No camera');
      const next = { ...row, desired };
      rows.set(id, next);
      return next;
    },
    // ★ The camera's own drift watch (2026-09-08): refuses like the server —
    //   naming the table or the frame — and records the watch on the row.
    freezeDrift: async (id: string): Promise<CameraDriftRead> => {
      const row = rows.get(id);
      if (!row) throw new Error('No camera');
      if (!row.lut_site) throw new Error('the drift watch starts once the lookup table is built from the frame.');
      if (!row.frame_image_id)
        throw new Error("the drift watch freezes on the camera's frame — capture one and place its control points first.");
      const ref_id = fakeUuid().replace(/-/g, '').slice(0, 32).padEnd(32, '0');
      rows.set(id, {
        ...row,
        desired: { ...row.desired, watch: { ref_id, interval_s: 10 } },
        updated_at: now(),
      });
      return {
        ref_id,
        interval_s: 10,
        n_landmarks: 12,
        frozen_from_label: 'frame.jpg',
        created_utc: now(),
        intrinsics_mode: 'calibration',
        intrinsics_warning: null,
        watching: true,
      };
    },
    exportUrl: (id: string): string => `/api/v1/cameras/${id}/export`,
    list: async (): Promise<never> => {
      throw new Error('not used by the store');
    },
  };
  return { rows, api };
}

/** The one instance the test files share with their `vi.mock` factories. */
export const fakeCameras = makeFakeCamerasApi();
