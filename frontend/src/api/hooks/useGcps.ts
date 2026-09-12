/**
 * ★★ GCP reads, and **the manual-mode create** — SCOPE.md §5.
 *
 * `useCreateGcp` is the hook that makes this build a product: it is the only way a
 * GCP comes into existence when the matching engine is deferred. See `api/gcps.ts`
 * for why the endpoint it calls is an addition to §7.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import type { Page, Uuid } from '../../types/common';
import type { GcpFilters, GcpRead } from '../../types/gcp';
import type { GeoJsonFeatureCollection } from '../../types/geo';
import { gcpsApi, type GcpCreate } from '../gcps';
import { qk } from '../queryKeys';

/**
 * ★ ONE PAGE OF 200, NOT 50 (1.3). The server's default page is 50 rows, and every
 *   consumer of this hook — the marker layers on both panes, the table, and the
 *   auto-naming that continues from the highest existing `GCP-NN` — read only
 *   that first page. Past 50 points on one photograph, markers went missing and
 *   a new point could be named after one that already existed (the 1.2.x known
 *   issue). The fix asks for the server's maximum page HERE, in the one hook,
 *   so every caller shares one cache entry and the key does not fork.
 *   A photograph with more than 200 points is out of this product's range.
 */
export const GCP_PAGE_LIMIT = 200;

/** Endpoint 38 — the GCP table's query. */
export function useGcps(imageId: Uuid | null, f: GcpFilters = {}): UseQueryResult<Page<GcpRead>> {
  const filters: GcpFilters = { limit: GCP_PAGE_LIMIT, ...f };
  return useQuery({
    queryKey: qk.gcps.forImageFiltered(imageId!, { ...filters, format: 'json' }),
    queryFn: ({ signal }) => gcpsApi.listForImage(imageId!, filters, signal),
    enabled: imageId !== null,
  });
}

/**
 * Endpoint 38 with `format=geojson`.
 *
 * ★ A SEPARATE CACHE ENTRY from {@link useGcps}, deliberately — see
 *   `qk.gcps.forImageFiltered`. Same URL, incompatible shapes.
 */
export function useGcpsGeoJson(
  imageId: Uuid | null,
  f: GcpFilters = {},
): UseQueryResult<GeoJsonFeatureCollection<GcpRead>> {
  return useQuery({
    queryKey: qk.gcps.forImageFiltered(imageId!, { ...f, format: 'geojson' }),
    queryFn: ({ signal }) => gcpsApi.listForImageGeoJson(imageId!, f, signal),
    enabled: imageId !== null,
  });
}

/** Endpoint 64 — `GET /match-results/{id}/gcps`. Empty in this build (SCOPE.md §4 rule 5). */
export function useGcpsForMatch(
  matchResultId: Uuid | null,
  f: GcpFilters = {},
): UseQueryResult<Page<GcpRead>> {
  return useQuery({
    queryKey: qk.gcps.forMatchFiltered(matchResultId!, f),
    queryFn: ({ signal }) => gcpsApi.listForMatch(matchResultId!, f, signal),
    enabled: matchResultId !== null,
  });
}

/**
 * Endpoint 39 — one GCP.
 *
 * ★★ READING A GCP IS WHAT MAKES IT EDITABLE. The response's `ETag` lands in
 *    `client.ts`'s registry, and endpoint 40 REQUIRES `If-Match`. A page ETag covers
 *    the whole page, so `useGcps` cannot supply a per-row one — **the inspector must
 *    have mounted `useGcp(id)` before `useAdjustGcp` can commit without a 428.**
 *    `useAdjustGcp` documents the consequence and the escape hatch.
 */
export function useGcp(gcpId: Uuid | null): UseQueryResult<GcpRead> {
  return useQuery({
    queryKey: qk.gcps.detail(gcpId!),
    queryFn: ({ signal }) => gcpsApi.get(gcpId!, signal),
    enabled: gcpId !== null,
    // ★ Always hit the network on mount, even when the detail cache is pre-seeded (e.g. by
    //   `useCreateGcp`). This read's PURPOSE is to register the row's ETag for the required
    //   `If-Match` on `PATCH /gcps/{id}` (client.ts); a cache-only read never carries one, so
    //   the adjust/rename would 428.
    refetchOnMount: 'always',
    staleTime: 0,
  });
}

/**
 * ★★ COMMIT A MANUAL CORRESPONDENCE — SCOPE.md §5. **The core interaction.**
 *
 * The surveyor marked a landmark in the photo and clicked the same physical spot on
 * the satellite map; this writes the pair. **The coordinate is a direct observation,
 * not an inference** — there is no homography, no degenerate solve, and no computed
 * confidence.
 *
 * ★ Wire it to `correspondenceStore` (IU-25) as that store's header prescribes:
 *   `beginCommit()` → `mutate` → `commitSucceeded(gcp.id)` / `commitFailed(error)`.
 *   The store deliberately holds no `GcpRead` — *"uncommitted correspondences must
 *   never appear in the GCP table or an export"* is enforced by the store being
 *   unable to represent one, and by the table reading only from React Query (L7).
 *
 * ★ NO OPTIMISTIC UPDATE, deliberately. Every other mutation here updates the cache
 *   before the server answers; this one does not. A GCP is a survey coordinate
 *   someone may dig, build or file against (L12), and the server assigns its `code`,
 *   its `accuracy` (from imagery GSD and click precision — SCOPE.md §5) and its
 *   `source`. **An optimistic row would have to invent all three**, and the invented
 *   accuracy would be rendered, at a decimal count derived from itself (§8.7), for
 *   however long the request takes. A fabricated accuracy figure is exactly what
 *   SCOPE.md's ruling exists to avoid. The commit is one round trip; it can wait.
 */
export function useCreateGcp(imageId: Uuid): UseMutationResult<GcpRead, unknown, GcpCreate> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (body: GcpCreate) => gcpsApi.create(imageId, body),
    onSuccess: (gcp) => {
      // Seed the detail cache so the inspector renders instantly — and so the
      // response's ETag is already registered for an immediate adjustment.
      queryClient.setQueryData(qk.gcps.detail(gcp.id), gcp);
      // Every filtered variant of this image's GCP list is now wrong. The prefix
      // catches them all, including the geojson one.
      void queryClient.invalidateQueries({ queryKey: qk.gcps.forImage(imageId) });
      // ★ The dashboard's cross-project map is a view of the same points.
      void queryClient.invalidateQueries({ queryKey: qk.gcps.overviews() });
      // `ImageRead.counts.gcps` and the annotation's `gcp_id`/`gcp_ids` moved too.
      void queryClient.invalidateQueries({ queryKey: qk.images.detail(imageId) });
      void queryClient.invalidateQueries({ queryKey: qk.annotations.forImage(imageId) });
    },
  });
}

/**
 * `DELETE /gcps/{id}` — permanently remove a manual GCP.
 *
 * ★ Mirrors {@link useCreateGcp}'s cache surface in reverse: the deleted detail is
 *   dropped and every list / count / annotation-link that referenced it is invalidated.
 *   The backing landmark annotation still exists on the server, so `annotations.forImage`
 *   is refreshed to pick up its now-cleared `gcp_id`.
 */
export function useDeleteGcp(imageId: Uuid): UseMutationResult<void, unknown, Uuid> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (gcpId: Uuid) => gcpsApi.remove(gcpId),
    onSuccess: (_result, gcpId) => {
      queryClient.removeQueries({ queryKey: qk.gcps.detail(gcpId) });
      void queryClient.invalidateQueries({ queryKey: qk.gcps.forImage(imageId) });
      void queryClient.invalidateQueries({ queryKey: qk.gcps.overviews() });
      void queryClient.invalidateQueries({ queryKey: qk.images.detail(imageId) });
      void queryClient.invalidateQueries({ queryKey: qk.annotations.forImage(imageId) });
    },
  });
}
