/**
 * Field video — a FRAME SOURCE, not a timeline. Mirrors the backend's
 * `VideoRead`/`VideoSummary` (built concurrently), field for field.
 *
 * ★ THE CASING LAW (§8.1 / L9): every wire field here is snake_case and is never
 *   renamed. Videos exist only to let a surveyor scrub to a second and CAPTURE that
 *   frame; the frame becomes a real `images` row (`ImageRead`, carrying
 *   `source_video_id` / `source_video_time_s`) which the existing GCP tools annotate.
 */

import type { IsoDateTime, Uuid } from './common';

/**
 * ★ Optional (`urls?`) because the backend contract marks it optional. When absent,
 *   the client synthesises URLs with `videosApi.fileUrl` / `videosApi.frameUrl` — the
 *   endpoints are stable regardless of whether the response echoes them.
 */
export interface VideoUrls {
  /** Range-served video bytes — used directly as the `<video src>`. */
  file: string;
  /** `GET /videos/{id}/frame?t=` — a JPEG preview, the fallback scrubber's source. */
  frame?: string;
}

/** `VideoRead` — `GET /videos/{id}` and the `201` from `POST /videos`. */
export interface Video {
  id: Uuid;
  /** `null` for a clip that lives in the library only — no survey project. */
  project_id: Uuid | null;
  filename: string;
  mime_type: string;
  size_bytes: number;
  /** Duration in seconds. The scrubber's max and the "go to second" clamp. */
  duration_s: number;
  /** Frames per second — the frame-step buttons nudge by `1 / fps`. */
  fps: number;
  width: number;
  height: number;
  frame_count: number | null;
  codec: string | null;
  /** A browser-playable H.264 preview exists; false for HEVC = transcode running. */
  preview_available: boolean;
  created_at: IsoDateTime;
  urls?: VideoUrls;
}

/**
 * List projection — `GET /videos?project_id=`. The contract lists the same fields as
 * `VideoRead`, so it is structurally identical; kept as its own name so a future
 * divergence is a type change, not a silent widening.
 */
export interface VideoSummary {
  id: Uuid;
  project_id: Uuid | null;
  filename: string;
  mime_type: string;
  size_bytes: number;
  duration_s: number;
  fps: number;
  width: number;
  height: number;
  frame_count: number | null;
  codec: string | null;
  created_at: IsoDateTime;
  urls?: VideoUrls;
}

/**
 * `POST /videos` (multipart). Exactly one of `file` / `source_path`, plus `project_id`.
 *
 * ★ `source_path` is the desktop route: a field video is routinely multiple GB, and
 *   the bytes-over-IPC picker hard-fails above its ceiling — the local API opens the
 *   path directly instead, exactly as the DEM upload does.
 */
export interface VideoCreate {
  /** The upload's bytes (browser route, and drag-and-drop everywhere). */
  file?: File;
  /** Absolute path on the API's own machine (desktop picker route). */
  source_path?: string;
  /** Omit (or null) to keep the clip in the library only — no project. */
  project_id?: Uuid | null;
  filename?: string;
}

/**
 * `POST /videos/{id}/frames` → `201 ImageRead`. Captures the frame at `t_seconds` as a
 * real image in the project. `code` optionally pre-labels the GCP the surveyor will
 * derive from it.
 */
export interface FrameCaptureRequest {
  t_seconds: number;
  code?: string | null;
  /** The surveyor's name for the photo. null/omitted → the server's default name. */
  filename?: string | null;
  /** The project the photograph goes to — required when the clip has none of its own. */
  project_id?: Uuid | null;
}
