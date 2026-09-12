/**
 * `api/captureLibrary.ts` — the surveyor's local capture folder over the wire.
 *
 * Every video-frame capture also lands as a plain JPEG in
 * `~/Pictures/LandExplorer` (server-side, which IS the user's laptop in the
 * desktop app). These calls let the picker browse that folder and import a photo
 * into any project — the import runs through the server's normal upload path, so
 * dedupe/ingest behave exactly as if the file had been dragged in.
 */

import { buildUrl, fetchJson } from './client';
import type { ImageRead } from '../types/image';
import type { Uuid } from '../types/common';

export interface CaptureLibraryEntry {
  filename: string;
  size_bytes: number;
  modified_at: string;
}

export interface CaptureLibraryList {
  /** The folder on disk, shown so "where do these come from?" answers itself. */
  folder: string | null;
  items: CaptureLibraryEntry[];
}

export const captureLibraryApi = {
  list: (signal?: AbortSignal): Promise<CaptureLibraryList> =>
    fetchJson('/capture-library', { signal }),

  /** The photo's bytes — the picker's `<img>` source (browser downscales). */
  fileUrl: (filename: string): string =>
    buildUrl(`/capture-library/${encodeURIComponent(filename)}`),

  importIntoProject: (filename: string, projectId: Uuid): Promise<ImageRead> =>
    fetchJson(`/capture-library/${encodeURIComponent(filename)}/import`, {
      method: 'POST',
      body: { project_id: projectId },
    }),
};

export default captureLibraryApi;
