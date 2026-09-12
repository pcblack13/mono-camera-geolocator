/**
 * Images — endpoints 10, 11, 14, 15.
 *
 * ★ Upload (endpoint 9) is `useImageUpload.ts` — it has a different transport and a
 *   different lifecycle.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import type { Page, Uuid } from '../../types/common';
import type { ImageFilters, ImageMetadataRead, ImageRead, ImageSummary } from '../../types/image';
import { imagesApi, type ImageRescaleBody } from '../images';
import { qk } from '../queryKeys';

export function useImages(
  projectId: Uuid | null,
  f: ImageFilters = {},
): UseQueryResult<Page<ImageSummary>> {
  return useQuery({
    queryKey: qk.images.listFiltered(projectId!, f),
    queryFn: ({ signal }) => imagesApi.list(projectId!, f, signal),
    enabled: projectId !== null,
  });
}

/**
 * Endpoint 11 — `GET /images/{id}`.
 *
 * ★★ THE SOURCE OF `D`. `ImageRead.variants[].display_scale` is the `D` of §8.6's
 *    coordinate model (`= width / original_width`, server-computed), and
 *    `original_width`/`original_height` are ALWAYS present and non-null (§12 C-36).
 *    **Without them the client cannot convert a stage click to an original-image
 *    pixel and the entire coordinate model collapses** — which is to say every GCP
 *    this build produces depends on this response. Never derive `D` from a rendered
 *    element's size.
 */
export function useImage(imageId: Uuid | null): UseQueryResult<ImageRead> {
  return useQuery({
    queryKey: qk.images.detail(imageId!),
    queryFn: ({ signal }) => imagesApi.get(imageId!, signal),
    enabled: imageId !== null,
  });
}

/**
 * Endpoint 14 — the verbatim EXIF block and the GeoTIFF metadata.
 *
 * ★ Separate from `useImage` because it is large (hundreds of tags, sometimes an
 *   embedded thumbnail) and the workspace does not need it to render.
 */
export function useImageMetadata(imageId: Uuid | null): UseQueryResult<ImageMetadataRead> {
  return useQuery({
    queryKey: qk.images.metadata(imageId!),
    queryFn: ({ signal }) => imagesApi.metadata(imageId!, signal),
    enabled: imageId !== null,
  });
}

export interface DeleteImageVariables {
  imageId: Uuid;
  projectId: Uuid;
  hard?: boolean;
}

export function useDeleteImage(): UseMutationResult<void, unknown, DeleteImageVariables> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ imageId, hard }: DeleteImageVariables) =>
      imagesApi.remove(imageId, hard ?? false),
    onSuccess: (_void, { imageId, projectId }) => {
      queryClient.removeQueries({ queryKey: qk.images.detail(imageId) });
      void queryClient.invalidateQueries({ queryKey: qk.images.lists() });
      void queryClient.invalidateQueries({ queryKey: qk.projects.detail(projectId) });
      // A deleted photo takes its control points off the dashboard map with it.
      void queryClient.invalidateQueries({ queryKey: qk.gcps.overviews() });
    },
  });
}

/**
 * ★ Rescale a stored photo to a new pixel size (§ resolution feature).
 *
 * The server resizes the raster AND scales existing landmark/GCP pixel positions to
 * match; the recorded lat/lon are UNCHANGED. On success we seed the returned
 * `ImageRead` and invalidate everything whose pixels just moved:
 *
 *   - the image detail (new `width`/`height`/`variants` — the viewer reloads at size),
 *   - its GCPs (their `image_px` were scaled server-side),
 *   - its annotations (landmark pixels were scaled too),
 *   - its metadata (the raster block changed),
 *   - the images list (thumbnail dimensions changed).
 */
export function useRescaleImage(
  imageId: Uuid,
): UseMutationResult<ImageRead, unknown, ImageRescaleBody> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ImageRescaleBody) => imagesApi.rescale(imageId, body),
    onSuccess: (image) => {
      queryClient.setQueryData(qk.images.detail(imageId), image);
      void queryClient.invalidateQueries({ queryKey: qk.images.detail(imageId) });
      void queryClient.invalidateQueries({ queryKey: qk.images.metadata(imageId) });
      void queryClient.invalidateQueries({ queryKey: qk.images.lists() });
      void queryClient.invalidateQueries({ queryKey: qk.gcps.forImage(imageId) });
      void queryClient.invalidateQueries({ queryKey: qk.annotations.forImage(imageId) });
    },
  });
}

/** The inverse: back to the pristine camera bytes. Same caches move, same reason. */
export function useRestoreImageResolution(
  imageId: Uuid,
): UseMutationResult<ImageRead, unknown, void> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => imagesApi.restoreResolution(imageId),
    onSuccess: (image) => {
      queryClient.setQueryData(qk.images.detail(imageId), image);
      void queryClient.invalidateQueries({ queryKey: qk.images.detail(imageId) });
      void queryClient.invalidateQueries({ queryKey: qk.images.metadata(imageId) });
      void queryClient.invalidateQueries({ queryKey: qk.images.lists() });
      void queryClient.invalidateQueries({ queryKey: qk.gcps.forImage(imageId) });
      void queryClient.invalidateQueries({ queryKey: qk.annotations.forImage(imageId) });
    },
  });
}
