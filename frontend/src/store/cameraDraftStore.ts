/**
 * `store/cameraDraftStore.ts` — the ONE camera being set up that is not on the server yet.
 *
 * ★ EVERY STEP IS OPEN BEFORE THE CAMERA EXISTS (2026-09-04, owner ask). The settings
 *   pipeline used to create the camera at step 3 and lock the DEM, frame and
 *   lookup-table steps until then — the owner refused that: one page, every
 *   option available, ONE "Add camera" at the end. So a new camera is a DRAFT held
 *   here until that press: its name, connection, position and calibration as
 *   typed, plus the server-side ids the later steps produce — the backing project
 *   (created the first time the DEM or the frame needs a home), the frame image,
 *   and the lookup table's site name once it is built. "Add camera to the server"
 *   posts the whole draft as one row and clears it.
 *
 * ★ PERSISTED, so the round trip through the GCP editor ("Place control points" →
 *   "Back to camera settings") lands back on the same draft — and so does a
 *   reload. A draft is discarded explicitly, or by being added.
 */

import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';

import type { CameraConnection } from './cameraRegistryStore';

export interface CameraDraftFields {
  name: string;
  connection: CameraConnection;
  source: string;
  dataUrl: string;
  serialPort: string;
  serialBaud: string;
  lat: string;
  lon: string;
  heading_deg: string;
  fov_deg: string;
  /** Calibration as typed, keyed by `CALIBRATION_KEYS`. */
  calibration: Record<string, string>;
  /** ★ GEO-DRIFT C2/C3: no calibration — the focal is SOLVED from the control
   *  points, seeded by the field of view at step 3. */
  no_calibration: boolean;
  /** The backing project, once the DEM or the frame needed one. */
  project_id: string | null;
  /** The frame chosen from the camera, once there is one. */
  frame_image_id: string | null;
  /** The lookup table built for the frame, once there is one. */
  lut_site: string | null;
}

export const EMPTY_DRAFT: CameraDraftFields = {
  name: '',
  connection: 'lan',
  source: '',
  dataUrl: '',
  serialPort: '',
  serialBaud: '115200',
  lat: '',
  lon: '',
  heading_deg: '',
  fov_deg: '',
  calibration: {},
  no_calibration: false,
  project_id: null,
  frame_image_id: null,
  lut_site: null,
};

export interface CameraDraftState {
  draft: CameraDraftFields;
  /** ISO of the last edit; null when the draft is pristine. */
  touchedAt: string | null;
  patch: (changes: Partial<CameraDraftFields>) => void;
  clear: () => void;
}

/** True when anything has been typed or produced — the "Discard draft" gate. */
export function draftHasContent(d: CameraDraftFields): boolean {
  return (
    d.name.trim() !== '' ||
    d.source.trim() !== '' ||
    d.dataUrl.trim() !== '' ||
    d.serialPort.trim() !== '' ||
    d.lat.trim() !== '' ||
    d.lon.trim() !== '' ||
    d.project_id !== null ||
    d.frame_image_id !== null ||
    d.lut_site !== null ||
    Object.values(d.calibration).some((v) => v.trim() !== '')
  );
}

export const useCameraDraftStore = create<CameraDraftState>()(
  devtools(
    persist(
      (set) => ({
        draft: EMPTY_DRAFT,
        touchedAt: null,
        patch: (changes) =>
          set(
            (s) => ({ draft: { ...s.draft, ...changes }, touchedAt: new Date().toISOString() }),
            false,
            'cameraDraft/patch',
          ),
        clear: () => set({ draft: EMPTY_DRAFT, touchedAt: null }, false, 'cameraDraft/clear'),
      }),
      {
        name: 'le.cameraDraft.v1',
        // ★ Re-judge what comes back: an off-shape draft is dropped, never repaired.
        merge: (persisted, current) => {
          const p = persisted as Partial<CameraDraftState> | undefined;
          const d = p?.draft;
          if (!d || typeof d !== 'object' || typeof d.name !== 'string') return current;
          return {
            ...current,
            draft: { ...EMPTY_DRAFT, ...d, calibration: { ...(d.calibration ?? {}) } },
            touchedAt: typeof p?.touchedAt === 'string' ? p.touchedAt : null,
          };
        },
      },
    ),
    { name: 'cameraDraftStore' },
  ),
);
