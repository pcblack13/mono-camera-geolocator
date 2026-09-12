/**
 * ★ `useImageUpload` — endpoint 9, and the bridge to `uploadStore` (IU-25).
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * ★★ THE SEAM. `uploadStore` owns the QUEUE — file handles, ordering, the
 *    concurrency budget (3), per-item progress and cancellation. It owns **no
 *    transport**: it calls an {@link Uploader} that IU-24 registers via
 *    `setUploader`, because *"an `XMLHttpRequest` opened from a store would be a
 *    second, unauthenticated API client with no `ErrorEnvelope` parsing and no
 *    request id"*.
 *
 *    {@link useUploaderRegistration} is that registration. Mount it ONCE, high in the
 *    tree (the upload screen or the shell) — mounting it twice is harmless (the
 *    second overwrites with an identical function) but pointless.
 * ─────────────────────────────────────────────────────────────────────────────
 */

import { useEffect } from 'react';
import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';

import type { Uuid } from '../../types/common';
import { useUploadStore, type Uploader, type UploadItem } from '../../store/uploadStore';
import {
  imagesApi,
  isUploadAccepted,
  type ImageUploadForm,
  type ImageUploadResponse,
} from '../images';
import { qk } from '../queryKeys';

/**
 * Register IU-24's transport with `uploadStore`.
 *
 * ★ The store's `Uploader` resolves with the new image's id and nothing else — *"the
 *   store never inspects the response beyond that"* (L7: an `ImageRead` is server
 *   state and belongs in React Query, not in a Zustand store).
 *
 * ★ `202 ImageUploadAccepted` — a file over 50 MB (§12 C-06) — resolves the same way.
 *   The store then sits in `processing`, which is exactly right: **the bytes are up
 *   but the server's ingest job is still running**, and saying `done` would promise an
 *   image the surveyor cannot yet open. IU-28 polls `job` with `useJob` and calls
 *   `markProcessed(clientId)` when it goes terminal.
 */
export function useUploaderRegistration(projectId: Uuid | null): void {
  const setUploader = useUploadStore((s) => s.setUploader);
  const queryClient = useQueryClient();

  useEffect(() => {
    if (projectId === null) {
      setUploader(null);
      return;
    }

    const uploader: Uploader = async (item: UploadItem, onProgress, signal): Promise<Uuid> => {
      const response = await imagesApi.upload(
        { file: item.file, project_id: projectId },
        { onProgress, signal },
      );

      const image = isUploadAccepted(response) ? response.image : response;

      // Seed the cache — the thumbnail grid renders without a refetch.
      queryClient.setQueryData(qk.images.detail(image.id), image);
      void queryClient.invalidateQueries({ queryKey: qk.images.lists() });
      void queryClient.invalidateQueries({ queryKey: qk.projects.detail(projectId) });

      return image.id;
    };

    setUploader(uploader);
    // ★ Deregister on unmount: a stale closure over an old `projectId` would upload
    //   the next screen's files into the previous project.
    return () => setUploader(null);
  }, [projectId, setUploader, queryClient]);
}

export interface UploadImageVariables {
  form: ImageUploadForm;
  onProgress?: (bytesSent: number, bytesTotal: number) => void;
  signal?: AbortSignal;
  /** ★ The double-click guard (§12 C-27). Optional — the server replays the response. */
  idempotencyKey?: string;
}

/**
 * A single upload, outside the queue — for a one-off "replace this image" affordance.
 *
 * ★ For the multi-file dropzone use `uploadStore` + {@link useUploaderRegistration};
 *   it owns the concurrency budget, and 40 concurrent `useMutation`s would saturate a
 *   field tablet's uplink and starve the interactive requests the surveyor is waiting
 *   on.
 */
export function useImageUpload(): UseMutationResult<
  ImageUploadResponse,
  unknown,
  UploadImageVariables
> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ form, onProgress, signal, idempotencyKey }: UploadImageVariables) =>
      imagesApi.upload(form, { onProgress, signal, idempotencyKey }),
    onSuccess: (response, { form }) => {
      const image = isUploadAccepted(response) ? response.image : response;
      queryClient.setQueryData(qk.images.detail(image.id), image);
      void queryClient.invalidateQueries({ queryKey: qk.images.lists() });
      void queryClient.invalidateQueries({ queryKey: qk.projects.detail(form.project_id) });
    },
  });
}
