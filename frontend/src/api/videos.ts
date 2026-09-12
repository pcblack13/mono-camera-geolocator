/**
 * Videos — a FRAME SOURCE for the GCP workflow. Mirrors `src/api/images.ts`.
 *
 * ★ The contract (built concurrently by the backend):
 *   - `POST   /videos`              (multipart) → 201 `Video`
 *   - `GET    /videos?project_id=`  → `Page<VideoSummary>`
 *   - `GET    /videos/{id}`         → `Video`
 *   - `GET    /videos/{id}/file`    → the bytes, **Range-served** (an `<video src>`)
 *   - `GET    /videos/{id}/frame?t=`→ a JPEG preview of that second (fallback scrubber)
 *   - `POST   /videos/{id}/frames`  → 201 `ImageRead` (the captured frame, now an image)
 *   - `DELETE /videos/{id}`         → 204
 *
 * ★ `fileUrl` / `frameUrl` are URLs, not fetches — for the same reason as
 *   `imagesApi.fileUrl`: a video is tens of megabytes and belongs on an element's
 *   `src`, never pulled through React Query into the JS heap.
 */

import type { Page, Uuid } from '../types/common';
import type { ImageRead } from '../types/image';
import type { FrameCaptureRequest, Video, VideoCreate, VideoSummary } from '../types/video';
import { buildUrl, fetchJson, forgetEtag, upload, type UploadOptions } from './client';

const path = (id: Uuid): string => `/videos/${id}`;

/** Exported for the tests: the one place the upload body is assembled. */
export function toFormData(form: VideoCreate): FormData {
  const fd = new FormData();
  // ★ Exactly one of the two. `source_path` is the desktop route — the API runs on
  //   this same machine and streams the file from disk (no multi-GB HTTP body).
  if (form.file) fd.append('file', form.file, form.filename ?? form.file.name);
  if (form.source_path !== undefined) fd.append('source_path', form.source_path);
  // ★ Omitted for a library-only clip (no project) — the server accepts either.
  if (form.project_id != null) fd.append('project_id', form.project_id);
  if (form.filename !== undefined) fd.append('filename', form.filename);
  return fd;
}

export const videosApi = {
  /** `POST /videos` (multipart) → `201 Video`. Uses the one XHR (progress on a field uplink). */
  upload: (form: VideoCreate, opts: UploadOptions = {}): Promise<Video> =>
    upload<Video>('/videos', toFormData(form), opts),

  /** `GET /videos?project_id=` → `Page[VideoSummary]`. `project_id` is a QUERY param. */
  list: (projectId: Uuid, signal?: AbortSignal): Promise<Page<VideoSummary>> =>
    fetchJson<Page<VideoSummary>>('/videos', { query: { project_id: projectId }, signal }),

  /**
   * `GET /videos` with NO project filter → every video across every project — the
   * Video editor tab's library view. `project_id` is optional on the endpoint.
   */
  // ★ EVERY clip, not the first 200: the pickers on the detection and drift pages
  //   list this, and a library that grew past one page was silently truncated.
  //   200 is the API's page ceiling, so this walks the pages.
  listAll: async (signal?: AbortSignal): Promise<Page<VideoSummary>> => {
    const limit = 200;
    const first = await fetchJson<Page<VideoSummary>>('/videos', {
      query: { limit, offset: 0 },
      signal,
    });
    const items = [...first.items];
    let offset = items.length;
    while (offset < first.total && items.length < 5000) {
      const page = await fetchJson<Page<VideoSummary>>('/videos', {
        query: { limit, offset },
        signal,
      });
      if (page.items.length === 0) break;
      items.push(...page.items);
      offset += page.items.length;
    }
    return { ...first, items, limit: items.length, offset: 0 };
  },

  /** `GET /videos/{id}` → `Video`. */
  get: (id: Uuid, signal?: AbortSignal): Promise<Video> => fetchJson<Video>(path(id), { signal }),

  /** The Range-served bytes — the `<video src>`. Native seeking works because of Range. */
  fileUrl: (id: Uuid): string => buildUrl(`${path(id)}/file`),

  /** The H.264 preview stream — 404 until `preview_available` (HEVC transcode). */
  previewUrl: (id: Uuid): string => buildUrl(`${path(id)}/preview`),

  /** A server-rendered JPEG of the frame at `t` seconds — the non-playable-format scrubber. */
  frameUrl: (id: Uuid, t: number): string => buildUrl(`${path(id)}/frame`, { t }),

  /**
   * `POST /videos/{id}/frames` → `201 ImageRead`. Captures the frame at `t_seconds` as a
   * real image in the project — which the surveyor then annotates with the existing tools.
   */
  captureFrame: (id: Uuid, body: FrameCaptureRequest, signal?: AbortSignal): Promise<ImageRead> =>
    fetchJson<ImageRead>(`${path(id)}/frames`, { method: 'POST', body, signal }),

  /** `DELETE /videos/{id}` → `204`. */
  remove: async (id: Uuid, signal?: AbortSignal): Promise<void> => {
    await fetchJson<void>(path(id), { method: 'DELETE', parse: 'none', signal });
    forgetEtag(path(id));
  },
};
