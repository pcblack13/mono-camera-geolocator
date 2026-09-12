/**
 * DEM processing endpoints — `gis.dem` behind `/dem/*`.
 *
 * ★ These are NOT deferred. Everything here runs for real; there is no 501 to guard
 *   against and no capability gate to check. The one honest failure mode is a
 *   deployment without rasterio, which arrives as a normal `ApiError`.
 */

import { fetchJson, request, upload, type UploadOptions } from './client';
import type {
  DemActiveResponse,
  DemProcessForm,
  DemProcessResponse,
  DemSampleForm,
  DemSampleResponse,
} from '../types/dem';

/**
 * ★ Multipart carries strings, so the AOI corner array is sent as JSON TEXT in one
 *   field rather than as `aoi_corners[0][lat]`-style repeats. The backend parses it in
 *   one place (`_parse_corners`) and rejects malformed input as a 422 about the
 *   request — not a 500 from inside the pipeline.
 */
function toFormData(form: DemProcessForm): FormData {
  const fd = new FormData();
  // ★ Exactly one of the two. `source_path` is the desktop route: the API runs on
  //   this same machine and opens the file directly — no multi-GB HTTP body.
  if (form.file) fd.append('file', form.file, form.file.name);
  if (form.source_path !== undefined) fd.append('source_path', form.source_path);

  if (form.aoi_corners && form.aoi_corners.length > 0) {
    fd.append('aoi_corners', JSON.stringify(form.aoi_corners));
  }
  // ★ The camera triple travels together or not at all — the backend refuses a partial
  //   one rather than silently processing the whole DEM.
  if (
    form.camera_lat !== undefined &&
    form.camera_lon !== undefined &&
    form.radius_m !== undefined
  ) {
    fd.append('camera_lat', String(form.camera_lat));
    fd.append('camera_lon', String(form.camera_lon));
    fd.append('radius_m', String(form.radius_m));
  }
  if (form.tolerance !== undefined) fd.append('tolerance', String(form.tolerance));
  if (form.reproject !== undefined) fd.append('reproject', String(form.reproject));
  // ★ `null` means "auto-pick the UTM zone" and is expressed by OMITTING the field.
  //   Sending the string "null" would reach the backend as an invalid EPSG code.
  if (form.target_srid !== undefined && form.target_srid !== null) {
    fd.append('target_srid', String(form.target_srid));
  }
  if (form.resampling !== undefined) fd.append('resampling', form.resampling);
  if (form.target_resolution_m !== undefined && form.target_resolution_m !== null) {
    fd.append('target_resolution_m', String(form.target_resolution_m));
  }
  if (form.set_as_elevation_source !== undefined) {
    fd.append('set_as_elevation_source', String(form.set_as_elevation_source));
  }
  if (form.project_id !== undefined) fd.append('project_id', form.project_id);
  // ★ An image DEM needs its project too — the backend rejects image_id alone. The
  //   DEM page only ever sends this together with project_id.
  if (form.image_id !== undefined) fd.append('image_id', form.image_id);
  return fd;
}

export const demApi = {
  /**
   * `POST /dem/process` (multipart) → `200 DemProcessResponse`.
   *
   * Crops to the AOI and reprojects into a projected metre CRS. `onProgress` reports
   * UPLOAD bytes only — a DEM tile is tens of megabytes and that is the part worth a
   * progress bar; the processing itself is server-side and not streamed.
   */
  process: (form: DemProcessForm, opts: UploadOptions = {}): Promise<DemProcessResponse> =>
    upload<DemProcessResponse>('/dem/process', toFormData(form), opts),

  /**
   * `GET /dem/{run_id}/download` → the processed GeoTIFF as a `Blob`.
   *
   * Goes through the API client rather than pointing an `<a href>` at the URL, so the
   * request carries its `X-Request-ID` and a failure arrives as an `ApiError` instead
   * of a browser tab showing raw JSON.
   */
  download: async (runId: string, signal?: AbortSignal): Promise<Blob> =>
    (await request<Blob>(`/dem/${runId}/download`, { parse: 'blob', signal })).data,

  /**
   * `GET /dem/active` → which DEM new GCPs sample their elevation from.
   *
   * ★ Not under `/dem/{run_id}` — it describes the ADOPTED DEM, which may be from any
   * earlier run. The backend registers it before the `{run_id}` routes so `active` is
   * never captured as a run id.
   */
  active: (signal?: AbortSignal): Promise<DemActiveResponse> =>
    fetchJson<DemActiveResponse>('/dem/active', { signal }),

  /**
   * `POST /projects/{id}/dem` — adopt a preprocessed DEM as THIS project's Z source.
   *
   * ★ Sends no crop and no reprojection: the file is already prepared. The server skips
   *   the warp when the raster is already in ground metres, so re-projecting would only
   *   resample a correct surface and blur it.
   */
  uploadProjectDem: (
    projectId: string,
    source: File | { path: string; name: string },
    opts: UploadOptions = {},
  ): Promise<DemProcessResponse> => {
    const fd = new FormData();
    // ★ A `File` uploads its bytes; a `{path}` (desktop picker) sends only the
    //   path and the local API streams the file straight from disk.
    if (source instanceof File) fd.append('file', source, source.name);
    else fd.append('source_path', source.path);
    fd.append('reproject', 'false');
    return upload<DemProcessResponse>(`/projects/${projectId}/dem`, fd, opts);
  },

  /** `GET /projects/{id}/dem` → the project's DEM, or the global fallback. */
  projectDem: (projectId: string, signal?: AbortSignal): Promise<DemActiveResponse> =>
    fetchJson<DemActiveResponse>(`/projects/${projectId}/dem`, { signal }),

  /** `DELETE /projects/{id}/dem`. ★ Recorded GCP elevations are untouched. */
  deleteProjectDem: (projectId: string, signal?: AbortSignal): Promise<void> =>
    fetchJson<void>(`/projects/${projectId}/dem`, { method: 'DELETE', parse: 'none', signal }),

  /**
   * `POST /projects/{id}/images/{imageId}/dem` — adopt a preprocessed DEM for ONE
   * image, overriding the project DEM for that photograph only.
   *
   * ★ Same preprocessed contract as {@link demApi.uploadProjectDem}: no crop, no
   *   reproject (the server still skips the warp when the raster is already metric).
   */
  uploadImageDem: (
    projectId: string,
    imageId: string,
    source: File | { path: string; name: string },
    opts: UploadOptions = {},
  ): Promise<DemProcessResponse> => {
    const fd = new FormData();
    if (source instanceof File) fd.append('file', source, source.name);
    else fd.append('source_path', source.path);
    fd.append('reproject', 'false');
    return upload<DemProcessResponse>(`/projects/${projectId}/images/${imageId}/dem`, fd, opts);
  },

  /**
   * `GET /projects/{id}/images/{imageId}/dem` → this image's OWN DEM.
   *
   * ★ `active: false` means the image has no override and falls back to the project
   *   DEM — the caller shows "Using the project DEM".
   */
  imageDem: (
    projectId: string,
    imageId: string,
    signal?: AbortSignal,
  ): Promise<DemActiveResponse> =>
    fetchJson<DemActiveResponse>(`/projects/${projectId}/images/${imageId}/dem`, { signal }),

  /** `DELETE /projects/{id}/images/{imageId}/dem` — the image reverts to the project
   *  DEM. ★ Elevations already recorded on its GCPs are untouched. */
  deleteImageDem: (projectId: string, imageId: string, signal?: AbortSignal): Promise<void> =>
    fetchJson<void>(`/projects/${projectId}/images/${imageId}/dem`, {
      method: 'DELETE',
      parse: 'none',
      signal,
    }),

  /** `POST /dem/{run_id}/sample` → `200 DemSampleResponse`. Stage 3. */
  sample: (runId: string, body: DemSampleForm, signal?: AbortSignal): Promise<DemSampleResponse> =>
    fetchJson<DemSampleResponse>(`/dem/${runId}/sample`, {
      method: 'POST',
      body,
      signal,
    }),
};
