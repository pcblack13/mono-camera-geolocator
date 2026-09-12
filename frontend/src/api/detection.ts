/**
 * `/detection/*` — live object detection, geolocated through the LUT library.
 *
 * ★ WHAT A MARK CLAIMS, so no component implies more: a mark's lat/lon comes from a
 *   LUT — a camera pose frozen against a DEM. It is valid ONLY while the camera has
 *   not moved since that LUT was built, and it is only as good as that pose.
 *
 * ★ The runtime is OPTIONAL server-side (ultralytics + torch are heavy). The
 *   availability endpoint says what this machine can do and — where it cannot — the
 *   exact words that fix it. The UI gates on that, never on guesswork.
 */

import { fetchJson } from './client';

export interface DetectionCapability {
  available: boolean;
  reason: string | null;
  /** For the tracker: the kinds this build can run ("vit" only with its weights). */
  kinds?: string[];
}

export interface DetectionAvailability {
  detector: DetectionCapability;
  tracker: DetectionCapability;
  models: string[];
  /** Where inference will run (`cpu` / `cuda:0` / `mps`); null when absent. */
  device?: string | null;
  classes: DetectionClass[];
}

/** One subject the pipeline can detect — the COCO id, and its name. */
export interface DetectionClass {
  id: number;
  name: string;
}

export interface DetectionStartRequest {
  source: string;
  lut_site?: string | null;
  conf?: number;
  classes?: number[] | null;
  imgsz?: number;
  tile?: boolean;
  model?: string | null;
  max_frames?: number;
  /** File sources: detect every Nth frame (skips are counted). Live ignores it. */
  every_nth?: number;
  /**
   * ★ Opt-in ground-contact correction (1.3): each placed mark is pushed away from
   *   the camera by half its class's typical length and the metres applied are
   *   recorded on the mark (`centre_offset_m`). Off by default — it assumes a length.
   */
  centre_marks?: boolean;
  /** ★ How often ONE object may become a mark, per second (2026-09-11). A run
   *  used to place one per detection per frame — a single tracked car at 25 fps
   *  put 605 points on the map in 24 seconds, and the app stuttered under them.
   *  0 = a mark every frame. */
  mark_rate_hz?: number;
  /**
   * ★ Steady boxes (2026-09-03): debounce + smoothing + coasting over the raw
   *   per-frame YOLO output, so the overlay stops flickering. On by default.
   */
  steady_boxes?: boolean;
  /**
   * The registered camera this run belongs to (1.3). With it, the run is the
   * camera's DESIRED state: the server restarts it after a restart, and Stop
   * clears it. Without it, the run is a one-off.
   */
  camera_id?: string | null;
  /**
   * The handoff ARMS at this frame count and FIRES on the first armed frame
   * where YOLO found something. 0 = YOLO on every frame.
   */
  tracker_start_frame?: number;
  /** Which visual tracker follows locks: vit (learned, default) | csrt | kcf | mil. */
  tracker_type?: string;
  /** ★ False = a TRACKING-ONLY run (2026-09-11): no detector, no weights — the
   *  operator's drawn boxes are followed and placed, and nothing else is a box. */
  detect?: boolean;
  /**
   * ★ Past the handoff, YOLO runs again every this-many frames and re-seeds each
   *   lock on its fresh box, so the tracker's drift is corrected instead of
   *   compounding. Server default 10; 0 = only ever on a lost lock.
   */
  tracker_refresh_every?: number;
}

export interface DetectionBox {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  score: number;
  cls_name: string;
  track_id: number | null;
  /** The tracker's estimate rather than a detector sighting — drawn orange. */
  predicted: boolean;
  /** A mark was placed for it (its ground pixel had terrain under it). */
  placed: boolean;
}

export interface DetectionLatest {
  seq: number;
  frame_index: number;
  time_s: number;
  width: number;
  height: number;
  boxes: DetectionBox[];
}

export interface DetectionMark {
  /**
   * ★ NULL IS A REAL ANSWER (2026-09-07). A detection can exist without a place:
   *   an embedded board that detects on its own sends every sighting, and its
   *   lookup table places only some of them — while its drift guard is unhappy,
   *   none at all. Such a row belongs in the attribute table with an empty
   *   position, never on the map and never with a fabricated zero.
   */
  lat: number | null;
  lon: number | null;
  score: number;
  cls_name: string;
  frame_index: number;
  time_s: number;
  /** The ground-contact pixel; null for a mark from a data feed (no picture). */
  u: number | null;
  v: number | null;
  track_id: number | null;
  predicted: boolean;
  /** When the detection happened — UTC, and the server's local wall clock with
   *  offset, both stamped at detection time. Older sessions may lack them. */
  detected_at?: string | null;
  detected_at_local?: string | null;
  /**
   * ★ THE CAMERA'S DRIFT VERDICT WHEN THIS MARK WAS PLACED (1.3). A coordinate is
   *   valid only while the camera has not moved since its LUT was built; this is
   *   the drift monitor's confirmed answer at that instant — `moved` / `changed`
   *   mean "where" is in doubt, `unwatched` means nobody was checking.
   */
  drift_status?: DriftStamp;
  drift_ref_id?: string | null;
  /** ★ Metres this mark may be off on the ground from the measured drift, at its own range (2026-09-09). */
  drift_shift_m?: number | null;
  /** Metres the mark was pushed away from the camera (`centre_marks`); null = none. */
  centre_offset_m?: number | null;
}

export type DriftStamp = 'unwatched' | 'pending' | 'ok' | 'moved' | 'changed' | 'degraded';

/** The two stamps that mean the coordinate is in doubt. */
export const DRIFT_ALERT_STAMPS: readonly DriftStamp[] = ['moved', 'changed'];

export interface DetectionSession {
  session_id: string;
  source: string;
  status: 'starting' | 'running' | 'stopped' | 'failed';
  started_at: string;
  error: string | null;
  device: string;
  device_name: string;
  media_width: number;
  media_height: number;
  frames_done: number;
  /** Frames the camera produced that the detector never saw — the price of staying live. */
  frames_dropped: number;
  fps: number;
  phase: string;
  counts: Record<string, number>;
  /** Ground pixels on sky / outside the DEM — counted, never guessed. */
  skipped_no_terrain: number;
  marks_total: number;
  marks_dropped: number;
  /** Detection rows durably written to the database (batched). */
  db_rows_written: number;
  /** Rows the database refused — the last failure is in `db_error`. */
  db_rows_failed: number;
  db_error: string | null;
  latest: DetectionLatest | null;
  lut_site: string | null;
  lut_summary: Record<string, unknown> | null;
  settings: Record<string, unknown>;
  /** File sessions: true while the run holds between frames. */
  paused: boolean;
  /** What was recording — the video's filename, or the live source string. */
  camera_name: string;
  /** The recording camera's [lat, lon] from the LUT manifest; null without one. */
  camera_location: [number, number] | null;
  /** The registered camera this run belongs to, when the page said so (1.3). */
  camera_id?: string | null;
  /** The drift verdict the LAST detected frame was stamped with, and its watch. */
  drift_status?: DriftStamp;
  drift_ref_id?: string | null;
  /** ★ Metres this mark may be off on the ground from the measured drift, at its own range (2026-09-09). */
  drift_shift_m?: number | null;
  /** Marks placed while the watch read MOVED or CHANGED — placed, never hidden. */
  marks_under_alert?: number;
  /** Detections geolocated but not marked, because the same object was marked a
   *  moment ago — the difference between what was seen and what is on the map. */
  marks_thinned?: number;
  /** ★ Manual tracking (2026-09-03): whether the operator has the tracker on, the
   *  ids currently followed, and the one LOCKED primary (the highlighted object). */
  tracking_on?: boolean;
  tracked_ids?: number[];
  primary_track_id?: number | null;
  /** ★ The operator's names for tracks (2026-09-11), keyed by the id as a string. */
  track_names?: Record<string, string>;
  /** False = tracking-only: no detector ran; every box is an operator's lock. */
  detect?: boolean;
}

export interface DetectionMarksRead {
  next_index: number;
  marks: DetectionMark[];
}

export const detectionApi = {
  availability: (signal?: AbortSignal): Promise<DetectionAvailability> =>
    fetchJson<DetectionAvailability>('/detection/availability', { signal }),

  start: (body: DetectionStartRequest, signal?: AbortSignal): Promise<DetectionSession> =>
    fetchJson<DetectionSession>('/detection/sessions', { method: 'POST', body, signal }),

  /** Every in-memory session, newest first — the camera wall polls this. */
  list: (signal?: AbortSignal): Promise<{ items: DetectionSession[] }> =>
    fetchJson<{ items: DetectionSession[] }>('/detection/sessions', { signal }),

  get: (sessionId: string, signal?: AbortSignal): Promise<DetectionSession> =>
    fetchJson<DetectionSession>(`/detection/sessions/${sessionId}`, { signal }),

  /** Marks from `since` onward — the map polls incrementally, never re-downloading. */
  marks: (sessionId: string, since: number, signal?: AbortSignal): Promise<DetectionMarksRead> =>
    fetchJson<DetectionMarksRead>(`/detection/sessions/${sessionId}/marks?since=${since}`, {
      signal,
    }),

  /** Pause/resume a video-file run between frames. */
  pause: (sessionId: string, paused: boolean, signal?: AbortSignal): Promise<DetectionSession> =>
    fetchJson<DetectionSession>(`/detection/sessions/${sessionId}/pause`, {
      method: 'POST',
      body: { paused },
      signal,
    }),

  /**
   * Steer what the burned-in preview draws, mid-run — the Boxes / Labels /
   * Tracks chips call this so they keep working while a detection is on.
   */
  setOverlay: (
    sessionId: string,
    overlay: { boxes?: boolean; labels?: boolean; tracks?: boolean; hud?: boolean },
    signal?: AbortSignal,
  ): Promise<DetectionSession> =>
    fetchJson<DetectionSession>(`/detection/sessions/${sessionId}/overlay`, {
      method: 'POST',
      body: overlay,
      signal,
    }),

  /** Turn manual tracking on/off mid-run — the "Start tracking" button. Off
   *  releases every lock; on lets the operator click objects to follow them. */
  setTracking: (sessionId: string, on: boolean, signal?: AbortSignal): Promise<DetectionSession> =>
    fetchJson<DetectionSession>(`/detection/sessions/${sessionId}/tracking`, {
      method: 'POST',
      body: { on },
      signal,
    }),

  /** One click, in MEDIA pixels: track/untrack the object there (`lock` promotes
   *  it to the highlighted primary instead). The worker resolves it on its next
   *  frame; the new state arrives on the following poll. */
  track: (
    sessionId: string,
    point: { u: number; v: number; lock?: boolean },
    signal?: AbortSignal,
  ): Promise<DetectionSession> =>
    fetchJson<DetectionSession>(`/detection/sessions/${sessionId}/track`, {
      method: 'POST',
      body: point,
      signal,
    }),

  /** ★ Track what the operator DREW (2026-09-11): a box in MEDIA pixels, detection
   *  or not. The worker seeds the visual tracker on it; `name` labels the track. */
  trackBox: (
    sessionId: string,
    box: { x1: number; y1: number; x2: number; y2: number; name?: string | null },
    signal?: AbortSignal,
  ): Promise<DetectionSession> =>
    fetchJson<DetectionSession>(`/detection/sessions/${sessionId}/track-box`, {
      method: 'POST',
      body: box,
      signal,
    }),

  /** ★ Name a track — "#3" becomes "white pickup" in the table, the picture and
   *  the export. Empty clears. Allowed on a finished run. */
  nameTrack: (
    sessionId: string,
    trackId: number,
    name: string,
    signal?: AbortSignal,
  ): Promise<DetectionSession> =>
    fetchJson<DetectionSession>(`/detection/sessions/${sessionId}/tracks/${trackId}/name`, {
      method: 'PUT',
      body: { name: name.trim() === '' ? null : name.trim() },
      signal,
    }),

  /** Set/clear the LOCKED primary by track id (null clears; an id already primary
   *  toggles off) — the inspector's lock control. */
  lock: (
    sessionId: string,
    trackId: number | null,
    signal?: AbortSignal,
  ): Promise<DetectionSession> =>
    fetchJson<DetectionSession>(`/detection/sessions/${sessionId}/lock`, {
      method: 'POST',
      body: { track_id: trackId },
      signal,
    }),

  stop: (sessionId: string, signal?: AbortSignal): Promise<void> =>
    fetchJson<void>(`/detection/sessions/${sessionId}`, { method: 'DELETE', signal }),
};
