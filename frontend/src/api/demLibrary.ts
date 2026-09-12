/**
 * `api/demLibrary.ts` — the processed-DEM library over the wire.
 *
 * Every successful DEM pipeline run drops its output GeoTIFF (plus a metadata
 * sidecar) into `~/Documents/LandExplorer/DEMs`. These calls list that folder and
 * adopt one entry as a project's elevation source — server-side, through the real
 * pipeline, so adoption behaves exactly like uploading the file on the setup page.
 */

import { fetchJson } from './client';
import type { DemProcessResponse } from '../types/dem';
import type { Uuid } from '../types/common';

export interface DemLibraryEntry {
  filename: string;
  size_bytes: number;
  modified_at: string;
  source_name: string | null;
  output_crs: string | null;
  pixel_size_m: number | null;
}

export interface DemLibraryList {
  folder: string | null;
  items: DemLibraryEntry[];
}

export const demLibraryApi = {
  list: (signal?: AbortSignal): Promise<DemLibraryList> => fetchJson('/dem-library', { signal }),

  adoptIntoProject: (filename: string, projectId: Uuid): Promise<DemProcessResponse> =>
    fetchJson(`/dem-library/${encodeURIComponent(filename)}/adopt`, {
      method: 'POST',
      body: { project_id: projectId },
    }),

  /** Adopt a library DEM for ONE image — overrides the project DEM for that photo only. */
  adoptIntoImage: (filename: string, projectId: Uuid, imageId: Uuid): Promise<DemProcessResponse> =>
    fetchJson(`/dem-library/${encodeURIComponent(filename)}/adopt`, {
      method: 'POST',
      body: { project_id: projectId, image_id: imageId },
    }),

  /**
   * `DELETE /dem-library/{filename}` — remove one processed DEM (and its metadata
   * sidecar) from the library folder. ★ Strands nothing: adoption always copied the
   * bytes into the project's own storage, so projects keep working.
   */
  remove: (filename: string, signal?: AbortSignal): Promise<void> =>
    fetchJson<void>(`/dem-library/${encodeURIComponent(filename)}`, {
      method: 'DELETE',
      parse: 'none',
      signal,
    }),
};

export default demLibraryApi;
