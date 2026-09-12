/**
 * Images — endpoints 9–15 (§7).
 *
 * ★ `ImageUploadForm` (§6.2) is multipart and is the ONE place the app uses
 *   `XMLHttpRequest` — see `client.ts`'s {@link upload} for why (`fetch` cannot
 *   report upload progress, and a 400 MB orthophoto over a field uplink is exactly
 *   when a surveyor needs a progress bar that is not lying).
 */

import type { Page, Uuid } from '../types/common';
import type {
  ImageFilters,
  ImageMetadataRead,
  ImageRead,
  ImageSummary,
  ImageUpdate,
  ImageUploadAccepted,
} from '../types/image';
import { buildUrl, fetchJson, forgetEtag, toQuery, upload, type UploadOptions } from './client';

const path = (id: Uuid): string => `/images/${id}`;

/**
 * `ImageUploadForm` (§6.2), as the browser sends it. Every field except `file` and
 * `project_id` is optional.
 *
 * ★ `metadata` is JSON-encoded into a form field — multipart carries strings, and
 *   the server parses it back (§12 C-22 adds `notes` and `metadata` to this form).
 */
export interface ImageUploadForm {
  file: File;
  project_id: Uuid;
  filename?: string;
  notes?: string;
  captured_at?: string;
  metadata?: Record<string, unknown>;
  /**
   * ★ Optional target RESOLUTION (§ resolution feature). When present, the server
   *   stores the photo at exactly this pixel size instead of the file's native one.
   *   Send BOTH or NEITHER — a lone dimension is ambiguous, so the transport only
   *   appends them together (see {@link toFormData}).
   */
  target_width?: number;
  target_height?: number;
}

/** `POST /images/{id}/rescale` body — the new pixel size. */
export interface ImageRescaleBody {
  width: number;
  height: number;
}

/** `ThumbnailParams` (§6.2) — endpoint 13. */
export interface ThumbnailParams {
  width?: number;
  height?: number;
  format?: 'png' | 'jpeg' | 'webp';
}

/**
 * Endpoint 9 returns `201 ImageRead` for a small file and `202 ImageUploadAccepted`
 * for one over `LE_ASYNC_INGEST_THRESHOLD_BYTES` (50 MB, §12 C-06).
 */
export type ImageUploadResponse = ImageRead | ImageUploadAccepted;

/**
 * ★ Discriminates STRUCTURALLY rather than on the status code. The two bodies are
 *   unambiguously different (`ImageUploadAccepted` wraps `{ image, job }`), and a
 *   structural check keeps working if a proxy rewrites 202 → 200 — which some do.
 */
export function isUploadAccepted(r: ImageUploadResponse): r is ImageUploadAccepted {
  return typeof r === 'object' && r !== null && 'image' in r && 'job' in r;
}

function toFormData(form: ImageUploadForm): FormData {
  const fd = new FormData();
  fd.append('file', form.file, form.filename ?? form.file.name);
  fd.append('project_id', form.project_id);
  if (form.filename !== undefined) fd.append('filename', form.filename);
  if (form.notes !== undefined) fd.append('notes', form.notes);
  if (form.captured_at !== undefined) fd.append('captured_at', form.captured_at);
  if (form.metadata !== undefined) fd.append('metadata', JSON.stringify(form.metadata));
  // ★ Multipart carries strings; the server parses these back to ints. Appended only
  //   as a pair — a target with one dimension missing is never sent.
  if (form.target_width !== undefined && form.target_height !== undefined) {
    fd.append('target_width', String(form.target_width));
    fd.append('target_height', String(form.target_height));
  }
  return fd;
}

export const imagesApi = {
  /** Endpoint 9 — `POST /images` (multipart) → `201 ImageRead` · `202 ImageUploadAccepted`. */
  upload: (form: ImageUploadForm, opts: UploadOptions = {}): Promise<ImageUploadResponse> =>
    upload<ImageUploadResponse>('/images', toFormData(form), opts),

  /**
   * Endpoint 10 — `GET /images` → `200 Page[ImageSummary]`.
   *
   * ★ `project_id` is a QUERY param, not a path segment — §7 lists `/images`, not
   *   `/projects/{id}/images`. `qk.images.list(projectId)` scopes the cache to match.
   */
  list: (
    projectId: Uuid,
    f: ImageFilters = {},
    signal?: AbortSignal,
  ): Promise<Page<ImageSummary>> =>
    fetchJson<Page<ImageSummary>>('/images', {
      query: { project_id: projectId, ...toQuery(f) },
      signal,
    }),

  /** Endpoint 11 — `GET /images/{id}` → `200 ImageRead` + `ETag`. */
  get: (id: Uuid, signal?: AbortSignal): Promise<ImageRead> =>
    fetchJson<ImageRead>(path(id), { signal }),

  /**
   * Endpoint 12 — the raster itself. **A URL, not a fetch**: this is an `<img src>`
   * / `<a href>`, and pulling a 400 MB GeoTIFF through React Query would cache it in
   * JS heap.
   */
  fileUrl: (id: Uuid, download = false): string => buildUrl(`${path(id)}/file`, { download }),

  /** Endpoint 13 — a URL, for the same reason as {@link imagesApi.fileUrl}. */
  thumbnailUrl: (id: Uuid, params: ThumbnailParams = {}): string =>
    buildUrl(`${path(id)}/thumbnail`, toQuery(params)),

  /** Endpoint 14 — `GET /images/{id}/metadata` → `200 ImageMetadataRead` (the verbatim EXIF block). */
  metadata: (id: Uuid, signal?: AbortSignal): Promise<ImageMetadataRead> =>
    fetchJson<ImageMetadataRead>(`${path(id)}/metadata`, { signal }),

  /**
   * ★ NOT IN §7 — `PATCH /images/{image_id}` has no row in the endpoint table, yet
   *   §6.2 declares `ImageUpdate` and IU-23 mirrors it in `types/image.ts`. A request
   *   schema with no endpoint is either a missing row or a dead type. **Not called by
   *   any hook in this unit**; exposed so the gap is visible rather than silently
   *   worked around. Flagged for IU-21/IU-17.
   */
  update: (id: Uuid, body: ImageUpdate, etag?: string, signal?: AbortSignal): Promise<ImageRead> =>
    fetchJson<ImageRead>(path(id), { method: 'PATCH', body, ifMatch: etag, signal }),

  /**
   * ★ NOT IN §7 — `POST /images/{id}/rescale` (§ resolution feature). Resizes the
   *   stored photo to `{width, height}` and scales existing landmark/GCP pixel
   *   positions proportionally; the recorded lat/lon are UNCHANGED. Returns the
   *   refreshed `ImageRead` (new `width`/`height`/`variants`). Built in parallel by the
   *   backend agent — may 404 until it lands; callers degrade gracefully.
   */
  rescale: (id: Uuid, body: ImageRescaleBody, signal?: AbortSignal): Promise<ImageRead> =>
    fetchJson<ImageRead>(`${path(id)}/rescale`, { method: 'POST', body, signal }),

  /** Undo every rescale — pristine camera bytes return; 422 if never rescaled. */
  restoreResolution: (id: Uuid, signal?: AbortSignal): Promise<ImageRead> =>
    fetchJson<ImageRead>(`${path(id)}/rescale/restore`, { method: 'POST', signal }),

  /** Endpoint 15 — `DELETE /images/{id}` → `204`. `hard: true` requires `X-Confirm-Delete`. */
  remove: async (id: Uuid, hard = false, signal?: AbortSignal): Promise<void> => {
    await fetchJson<void>(path(id), {
      method: 'DELETE',
      query: { hard },
      confirmDelete: hard,
      parse: 'none',
      signal,
    });
    forgetEtag(path(id));
  },
};
