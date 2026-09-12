/**
 * Exports — endpoints 58–63.
 *
 * ★ FULLY BUILT (SCOPE.md §3): CSV · GeoJSON · Shapefile · KML · PDF report. **Real
 *   jobs**, polled by `useJob` for real.
 *
 * ★★ SCOPE.md §5: *"Uncommitted correspondences must never appear in the GCP table or
 *    an export."* Structurally guaranteed and worth stating: an export reads `gcps`
 *    server-side, and an uncommitted correspondence lives only in
 *    `correspondenceStore`. There is no client-supplied GCP payload on this path.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import type { Page, Uuid } from '../../types/common';
import type { ExportFilters, ExportRead, ExportRequest, ExportSummary } from '../../types/export';
import type { JobRead } from '../../types/job';
import { exportsApi } from '../exports';
import { qk } from '../queryKeys';

export function useExports(f: ExportFilters = {}): UseQueryResult<Page<ExportSummary>> {
  return useQuery({
    queryKey: qk.exports.list(f),
    queryFn: ({ signal }) => exportsApi.list(f, signal),
  });
}

export function useExport(exportId: Uuid | null): UseQueryResult<ExportRead> {
  return useQuery({
    queryKey: qk.exports.detail(exportId!),
    queryFn: ({ signal }) => exportsApi.get(exportId!, signal),
    enabled: exportId !== null,
  });
}

export interface StartExportVariables {
  /** Exactly one of these. An image export is `?image_id`-scoped; a project export is not. */
  imageId?: Uuid;
  projectId?: Uuid;
  body: ExportRequest;
}

/**
 * Endpoints 58/59 — `202 JobRead`. Poll the returned job with `useJob`, then read
 * `ExportRead.download_url` (or `exportsApi.downloadUrl`).
 *
 * ★ `acknowledge_low_confidence` exists on `ExportRequest` and is the surveyor's
 *   explicit act. Do not default it to `true` — an export that silently ships
 *   `unreliable` GCPs into a deliverable is precisely the failure L12 names, and the
 *   acknowledgement is the record that a human accepted them.
 */
export function useStartExport(): UseMutationResult<JobRead, unknown, StartExportVariables> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ imageId, projectId, body }: StartExportVariables) => {
      if (imageId !== undefined) return exportsApi.startForImage(imageId, body);
      if (projectId !== undefined) return exportsApi.startForProject(projectId, body);
      // A programmer error, not a user error — and it must not become a request with
      // `undefined` in the path, which would 404 and read as a server fault.
      return Promise.reject(
        new Error('useStartExport: exactly one of imageId or projectId is required.'),
      );
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.exports.lists() });
      void queryClient.invalidateQueries({ queryKey: qk.jobs.lists() });
    },
  });
}

export function useDeleteExport(): UseMutationResult<void, unknown, Uuid> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (exportId: Uuid) => exportsApi.remove(exportId),
    onSuccess: (_void, exportId) => {
      queryClient.removeQueries({ queryKey: qk.exports.detail(exportId) });
      void queryClient.invalidateQueries({ queryKey: qk.exports.lists() });
    },
  });
}

/**
 * ★ Is this export downloadable right now?
 *
 *   `409 EXPORT_NOT_READY` and `410 EXPORT_EXPIRED` are real answers on endpoint 62,
 *   and a download is a browser navigation — it cannot be caught and rendered like a
 *   fetch. Gate the link on this instead of letting the browser show its own error
 *   page for a case the API predicted.
 */
export function isExportDownloadable(exp: ExportRead | undefined): boolean {
  if (!exp || exp.status !== 'succeeded' || exp.download_url === null) return false;
  if (exp.expires_at !== null && Date.parse(exp.expires_at) <= Date.now()) return false;
  return true;
}
