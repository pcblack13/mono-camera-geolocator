/**
 * GCP import — reading a KML/KMZ the surveyor refined in an external viewer.
 *
 * ★ **Two calls, never one.** `preview` parses and matches and **writes nothing**;
 *   `apply` commits. An import edits the coordinates in a survey deliverable, so the
 *   preview is where the surveyor sees what moves and the apply is where they consent.
 *   Collapsing them would let a mis-picked file rewrite a project's GCPs silently.
 *
 * ★ **The file is uploaded twice, and that is deliberate.** Caching the parse
 *   server-side between the two calls would need a handle, a TTL and a store, and would
 *   open a window in which the thing applied is not the thing that was shown.
 *   `expected_match_count` closes the loop instead: a file that changed under the
 *   surveyor comes back `409 IMPORT_FILE_CHANGED` rather than being applied.
 *
 * ★ These go through {@link upload} rather than `fetchJson` because they are multipart —
 *   see the `Content-Type` note in `client.ts`. A GCP KML is kilobytes, so `onProgress`
 *   is exposed but rarely worth wiring.
 */

import type { Uuid } from '../types/common';
import type { KmlImportApplyForm, KmlImportApplyResponse, KmlImportPreview } from '../types/import';
import { upload, type UploadOptions } from './client';

export const importsApi = {
  /**
   * `POST /projects/{id}/gcps/import/kml/preview` → `200 KmlImportPreview`.
   *
   * Reports what an apply would change. **Writes nothing**, so it is safe to call on
   * every file selection.
   */
  previewKml: (
    projectId: Uuid,
    file: File,
    opts: UploadOptions = {},
  ): Promise<KmlImportPreview> => {
    const fd = new FormData();
    fd.append('file', file, file.name);
    return upload<KmlImportPreview>(`/projects/${projectId}/gcps/import/kml/preview`, fd, opts);
  },

  /**
   * `POST /projects/{id}/gcps/import/kml/apply` → `200 KmlImportApplyResponse`.
   *
   * Each moved GCP goes through the ordinary adjustment path, so `original_geom` is
   * preserved, `manually_adjusted` is set, and `adjustment_offset_m` is measured by
   * PostGIS in true ground metres. Re-applying an unchanged file is a no-op.
   */
  applyKml: (
    projectId: Uuid,
    form: KmlImportApplyForm,
    opts: UploadOptions = {},
  ): Promise<KmlImportApplyResponse> => {
    const fd = new FormData();
    fd.append('file', form.file, form.file.name);

    // ★ Multipart carries strings. `undefined` fields are OMITTED, never sent as the
    //   string "undefined" — the backend's Form defaults are the single source of the
    //   default, and a literal "undefined" would reach it as an invalid value.
    if (form.expected_match_count !== undefined) {
      fd.append('expected_match_count', String(form.expected_match_count));
    }
    if (form.apply_elevation !== undefined) {
      fd.append('apply_elevation', String(form.apply_elevation));
    }
    if (form.note !== undefined && form.note.length > 0) fd.append('note', form.note);

    return upload<KmlImportApplyResponse>(`/projects/${projectId}/gcps/import/kml/apply`, fd, opts);
  },
};
