/**
 * `/live/*` — live video sources: network cameras AND local capture devices.
 *
 * ★ Capture: the SERVER connects to the source, grabs one frame, and writes it
 *   into the capture library — from there it imports into any project like any
 *   other photograph.
 *
 * ★ Display: the browser can render only http MJPEG itself. Everything else —
 *   RTSP, HDMI capture cards, USB/USB-C cameras (`/dev/videoN` on Linux,
 *   DirectShow on Windows) — is re-served as http MJPEG by `GET /live/stream`,
 *   which is what `proxyStreamUrl` points the panel's player at.
 */

import { API_BASE_URL, buildUrl, fetchJson } from './client';
import type { DetectionMark } from './detection';

export interface LiveFrameCaptured {
  filename: string;
  width: number;
  height: number;
  size_bytes: number;
  file_url: string;
  /** Where the extra copy landed when a save folder was chosen, else null. */
  saved_to?: string | null;
}

/** Options for a capture: a chosen name and/or a folder to also save a copy into. */
export interface LiveCaptureOptions {
  name?: string;
  /** Absolute folder on the API's machine (desktop "Save to folder…"). */
  saveDir?: string;
}

/** One local capture device — an HDMI capture card or a USB/USB-C camera. */
export interface LiveDeviceInfo {
  /** `/dev/video0` (Linux) or `"0"` (a Windows DirectShow index). */
  id: string;
  label: string;
}

export const liveApi = {
  captureFrame: (
    url: string,
    opts: LiveCaptureOptions = {},
    signal?: AbortSignal,
  ): Promise<LiveFrameCaptured> =>
    fetchJson<LiveFrameCaptured>('/live/frame', {
      method: 'POST',
      body: { url, name: opts.name || undefined, save_dir: opts.saveDir || undefined },
      signal,
    }),

  /** Same grab, from a LOCAL device (id from `listDevices`). */
  captureDeviceFrame: (
    device: string,
    opts: LiveCaptureOptions = {},
    signal?: AbortSignal,
  ): Promise<LiveFrameCaptured> =>
    fetchJson<LiveFrameCaptured>('/live/frame', {
      method: 'POST',
      body: { device, name: opts.name || undefined, save_dir: opts.saveDir || undefined },
      signal,
    }),

  /** `GET /live/devices` — probes hardware, so call on explicit user action only. */
  listDevices: (signal?: AbortSignal): Promise<{ items: LiveDeviceInfo[] }> =>
    fetchJson<{ items: LiveDeviceInfo[] }>('/live/devices', { signal }),

  /** The server's MJPEG re-stream of ANY source — what the player uses for
   *  rtsp and local devices (http MJPEG is read directly instead). */
  proxyStreamUrl: (src: string): string => buildUrl('/live/stream', { src }),

  /** `GET /live/boxes` — the boxes a SENDER is showing right now, for the overlay.
   *
   *  ★ Not the same thing as its data feed. The feed carries the sender's
   *  DETECTIONS and they become marks and durable rows; this carries what is on
   *  screen this instant and is kept nowhere. Poll it only while someone is
   *  looking, and never while one of our own runs is drawing its own boxes. */
  sourceBoxes: (src: string, signal?: AbortSignal): Promise<SourceBoxes> =>
    fetchJson<SourceBoxes>(`/live/boxes?src=${encodeURIComponent(src)}`, { signal }),

  // ── senders: cameras that announce themselves on a cable ──────────────────

  /** `GET /live/senders` — every camera heard announcing itself right now.
   *
   *  ★ LISTENING, NOT SCANNING. Nothing is probed and no address is guessed: a
   *  camera either broadcasts or it is not there. Silence for a few seconds
   *  removes it, so unplugging a cable is visible while you are still looking. */
  senders: (signal?: AbortSignal): Promise<SenderList> =>
    fetchJson<SenderList>('/live/senders', { signal }),

  /** `POST /live/senders/{id}/connect` — start the app's own reader. Idempotent. */
  connectSender: (senderId: string, signal?: AbortSignal): Promise<SourceBoxes> =>
    fetchJson<SourceBoxes>(`/live/senders/${senderId}/connect`, {
      method: 'POST',
      signal,
    }),

  /** `DELETE /live/senders/{id}/connect` — stop reading it. */
  disconnectSender: (senderId: string, signal?: AbortSignal): Promise<void> =>
    fetchJson<void>(`/live/senders/${senderId}/connect`, { method: 'DELETE', signal }),

  /** The boxes a connected sender is showing right now — polled by the overlay. */
  senderBoxes: (senderId: string, signal?: AbortSignal): Promise<SourceBoxes> =>
    fetchJson<SourceBoxes>(`/live/senders/${senderId}/boxes`, { signal }),

  /** One operator click, carried to the sender that owns its tracker. */
  senderCommand: (
    senderId: string,
    body: SenderCommandBody,
    signal?: AbortSignal,
  ): Promise<SourceCommandRead> =>
    fetchJson<SourceCommandRead>(`/live/senders/${senderId}/command`, {
      method: 'POST',
      body,
      signal,
    }),

  /** The player's URL for a connected sender.
   *
   *  ★ ABSOLUTE, AND NOT ONLY FOR THE DOM. `API_BASE_URL` is relative (`/api/v1`)
   *  so the app works behind any origin — but a camera's stored `source` must
   *  look like a camera to the registry's validator, which accepts http(s),
   *  rtsp, /dev/… or a device index and nothing else. A root-relative path is
   *  none of those and is refused with "Request validation failed".
   *
   *  ★ THE STORED URL IS NOT THE ONE WE PLAY. The desktop API takes the first
   *  free port at or after 8123, so an absolute URL baked into a row can name
   *  the wrong port after a restart. The monitor page therefore rebuilds this
   *  from the sender id every time rather than trusting what was stored — the
   *  row keeps a valid, honest address, and playback never depends on it. */
  senderStreamUrl: (senderId: string): string =>
    `${window.location.origin}${API_BASE_URL}/live/senders/${senderId}/stream`,

  /** The RECORD channel for a connected sender: its detections as NDJSON lines,
   *  each stamped with the sender's own drift verdict. Registered as the camera's
   *  data source, so the ordinary feed reader ingests it — marks, map, rows —
   *  with no new source scheme. Same rebuild-from-id rule as the stream URL. */
  senderDetectionsUrl: (senderId: string): string =>
    `${window.location.origin}${API_BASE_URL}/live/senders/${senderId}/detections.ndjson`,

  /** `POST /live/source-command` — carry one operator click to a sender that
   *  detects on its own hardware. The sender's answer is passed through, so a
   *  refusal arrives in its own words rather than as a generic failure. */
  sourceCommand: (body: SourceCommandBody, signal?: AbortSignal): Promise<SourceCommandRead> =>
    fetchJson<SourceCommandRead>('/live/source-command', { method: 'POST', body, signal }),

  // ── data feeds: integrations that SEND detections (serial/UART, a Pi) ──────

  /** Open (or find running) the feed for `source` — idempotent per source. */
  /** `POST /live/data-feeds` — idempotent per source. With a `cameraId` the feed is
   *  the camera's DESIRED state and is re-opened after an API restart (1.3). */
  startDataFeed: (
    source: string,
    cameraId?: string | null,
    signal?: AbortSignal,
  ): Promise<DataFeedRead> =>
    fetchJson<DataFeedRead>('/live/data-feeds', {
      method: 'POST',
      body: { source, ...(cameraId ? { camera_id: cameraId } : {}) },
      signal,
    }),

  dataFeed: (feedId: string, signal?: AbortSignal): Promise<DataFeedRead> =>
    fetchJson<DataFeedRead>(`/live/data-feeds/${feedId}`, { signal }),

  /** The feed's marks cursor — the same shape a detection session serves. */
  dataFeedMarks: (
    feedId: string,
    since: number,
    signal?: AbortSignal,
  ): Promise<DataFeedMarksRead> =>
    fetchJson<DataFeedMarksRead>(`/live/data-feeds/${feedId}/marks?since=${since}`, { signal }),

  stopDataFeed: (feedId: string, signal?: AbortSignal): Promise<void> =>
    fetchJson<void>(`/live/data-feeds/${feedId}`, { method: 'DELETE', signal }),

  // ── recordings: the stream + its attribute table, one folder each ──────────

  /** Start recording a source — idempotent: an active recording is returned. */
  startRecording: (
    source: string,
    cameraName: string,
    signal?: AbortSignal,
  ): Promise<RecordingRead> =>
    fetchJson<RecordingRead>('/live/recordings', {
      method: 'POST',
      body: { source, camera_name: cameraName },
      signal,
    }),

  /** The active recording of a source — how a re-entered page finds its state.
   *  Resolves `null` when nothing is being recorded (a 200, so the console stays
   *  quiet on the ordinary case). */
  activeRecording: (source: string, signal?: AbortSignal): Promise<RecordingRead | null> =>
    fetchJson<{ recording: RecordingRead | null }>(
      `/live/recordings/active?src=${encodeURIComponent(source)}`,
      { signal },
    ).then((answer) => answer.recording),

  /** Stop and finalize — resolves once video, CSV and meta are on disk. */
  stopRecording: (recordingId: string, signal?: AbortSignal): Promise<RecordingRead> =>
    fetchJson<RecordingRead>(`/live/recordings/${recordingId}`, { method: 'DELETE', signal }),

  listRecordings: (signal?: AbortSignal): Promise<RecordingLibraryList> =>
    fetchJson<RecordingLibraryList>('/live/recordings', { signal }),

  deleteRecording: (folder: string, signal?: AbortSignal): Promise<void> =>
    fetchJson<void>(`/live/recordings/library/${encodeURIComponent(folder)}`, {
      method: 'DELETE',
      signal,
    }),

  /** Direct download URL of one file in a recording folder. */
  recordingFileUrl: (
    folder: string,
    file: 'video.mp4' | 'detections.csv' | 'satellite.png' | 'marks.geojson',
  ): string => `${API_BASE_URL}/live/recordings/files/${encodeURIComponent(folder)}/${file}`,

  /**
   * ★ THE WHOLE SESSION, ONE FILE (2026-09-12, owner ask). A zip holding one
   * folder per session and, inside it, the video, the satellite map and the
   * attribute table each in their own — the folder an operator would otherwise
   * have assembled from three separate downloads.
   */
  recordingPackageUrl: (folder: string): string =>
    `${API_BASE_URL}/live/recordings/package/${encodeURIComponent(folder)}`,

  // ── watching a recording in the app (2026-09-07) ───────────────────────────

  /**
   * The playable (H.264) rendition — the recorder's own file is MPEG-4 Part 2,
   * which no browser decodes. Derived on the first ask, Range-served so the
   * player can seek.
   */
  recordingPlayUrl: (folder: string): string =>
    `${API_BASE_URL}/live/recordings/files/${encodeURIComponent(folder)}/preview.mp4`,

  /** The recording's first frame as a JPEG — the library card's picture, derived on the first ask. */
  recordingPosterUrl: (folder: string): string =>
    `${API_BASE_URL}/live/recordings/files/${encodeURIComponent(folder)}/poster.jpg`,

  /** The attribute table as rows on the recording's clock — what the player follows. */
  recordingTable: (folder: string, signal?: AbortSignal): Promise<RecordingTable> =>
    fetchJson<RecordingTable>(`/live/recordings/table/${encodeURIComponent(folder)}`, {
      signal,
    }),

  /** Cut `[startS, endS]` into a NEW recording; resolves with its library entry. */
  trimRecording: (
    folder: string,
    startS: number,
    endS: number,
    signal?: AbortSignal,
  ): Promise<RecordingLibraryEntry> =>
    fetchJson<RecordingLibraryEntry>(`/live/recordings/trim/${encodeURIComponent(folder)}`, {
      method: 'POST',
      body: { start_s: startS, end_s: endS },
      signal,
    }),
};

export interface RecordingRead {
  recording_id: string;
  source: string;
  camera_name: string;
  folder: string;
  path: string;
  status: 'recording' | 'done' | 'failed';
  error: string | null;
  started_at: string;
  ended_at: string | null;
  frames: number;
  marks: number;
  video_bytes: number;
}

export interface RecordingLibraryEntry {
  folder: string;
  path: string;
  camera_name: string;
  source: string;
  started_at: string;
  ended_at: string | null;
  duration_s: number;
  frames: number;
  marks: number;
  video_bytes: number;
  has_video: boolean;
  has_csv: boolean;
  /**
   * `satellite.png` exists — the folder carries the scene's map (2026-09-12).
   * False for a run that placed nothing (no lookup table, so no ground to draw)
   * and for a recording made before the map existed, until its first package
   * download builds one.
   */
  has_map?: boolean;
  /** `preview.mp4` exists — it has been watched in the app once. */
  playable?: boolean;
  /** The folder this one was cut from, when it is a trim. */
  trimmed_from?: string | null;
}

/** One row of a recording's attribute table, placed on the recording's clock. */
export interface RecordingTableRow {
  index: number;
  /** Seconds since the recording started — what the player seeks to; null when unreadable. */
  t: number | null;
  time_utc: string;
  class_name: string;
  score: number | null;
  lat: number | null;
  lon: number | null;
  frame: number | null;
  track_id: number | null;
  predicted: boolean | null;
  drift: string | null;
  centre_m: number | null;
  mark_id: number | null;
}

/** `GET /live/recordings/table/{folder}`. */
export interface RecordingTable {
  folder: string;
  camera_name: string;
  source: string;
  started_at: string;
  ended_at: string | null;
  duration_s: number;
  /** `marks` = LUT-placed, full columns; `detections` = a no-LUT run's table. */
  table: 'marks' | 'detections';
  columns: string[];
  rows: RecordingTableRow[];
  has_video: boolean;
  trimmed_from: string | null;
}

export interface RecordingLibraryList {
  items: RecordingLibraryEntry[];
  root: string;
}

export interface DataFeedRead {
  feed_id: string;
  source: string;
  status: 'starting' | 'running' | 'stopped' | 'failed';
  error: string | null;
  started_at: string;
  last_mark_at: number;
  lines_ok: number;
  lines_bad: number;
  marks_total: number;
}

/** A camera that announced itself on the wire, as IT described itself.
 *  Every field is the sender's claim: the app has heard a broadcast, not opened
 *  a socket, which is why `reachable` is stated separately. */
export interface SenderRead {
  id: string;
  host: string;
  port: number;
  control_port: number;
  name: string;
  last_seen: number;
  /** Where the sender says it stands — so Connect needs no coordinates typed. */
  lat: number | null;
  lon: number | null;
  width: number | null;
  height: number | null;
  classes: string[] | null;
  /** True when it waits for an operator click before following anything. */
  manual: boolean | null;
  lut: string | null;
  /** Its lookup table is a placeholder: coordinates believable and wrong. */
  lut_placeholder: boolean;
  /** ★ HEARD IS NOT REACHED. False means this machine has no address on the
   *  sender's network — we can hear its broadcast but cannot open a socket. */
  reachable: boolean;
  needs_subnet: string | null;
}

export interface SenderList {
  items: SenderRead[];
}

/** One instruction for a connected sender. No url: the path names it. */
export interface SenderCommandBody {
  op: string;
  u?: number;
  v?: number;
  id?: number;
  on?: boolean;
}

/** One box a sender already found — the same field-for-field shape as our own
 *  `DetectionBox`, so the overlay canvas draws it without a translation step. */
export interface SourceBox {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  score: number;
  cls_name: string;
  track_id: number | null;
  predicted: boolean;
  placed: boolean;
}

/** One instruction for a sender that owns its own tracker. */
export interface SourceCommandBody {
  /** The sender's command endpoint (its bridge). */
  url: string;
  /** 'track' | 'untrack' | 'clear' | 'auto' — the sender's vocabulary. */
  op: string;
  /** Source-media pixels, for 'track'. */
  u?: number;
  v?: number;
  /** The object to release, for 'untrack'. */
  id?: number;
  /** For 'auto': true restores the sender's self-promoting tracking. */
  on?: boolean;
}

/** What the sender said. `ok: false` with a reason is a normal answer, not an
 *  error — "no viewer is connected" and "the click hit nothing" are different
 *  facts and the operator is entitled to both. */
export interface SourceCommandRead {
  ok: boolean;
  accepted: string | null;
  error: string | null;
}

/** `GET /live/boxes`. A quiet or unreachable sender answers with zero size and
 *  an empty list — which the overlay reads as "draw nothing", not as an error. */
export interface SourceBoxes {
  seq: number;
  frame_index: number;
  time_s: number;
  width: number;
  height: number;
  geo_valid: boolean;
  source: string | null;
  boxes: SourceBox[];
}

export interface DataFeedMarksRead {
  next_index: number;
  marks: DetectionMark[];
}
