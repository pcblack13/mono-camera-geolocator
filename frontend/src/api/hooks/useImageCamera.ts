/**
 * The photograph's entered camera — query + save, same idiom as `useProjectDem`.
 *
 * ★ The save invalidates ONLY `qk.imageCamera(id)`: the camera is embedded in no
 *   list row and no other response, so a broader sweep would refetch data that cannot
 *   have changed.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import type { Uuid } from '../../types/common';
import type {
  AutoGcpEstimateRead,
  AutoGcpEstimateRequest,
  AutoGcpProjectRead,
  AutoGcpProjectRequest,
  ImageCameraPut,
  ImageCameraRead,
} from '../../types/imageCamera';
import { imageCameraApi } from '../imageCamera';
import { qk } from '../queryKeys';

/**
 * ★ POSE DIAGNOSTICS ARE NOT TOASTED (1.2.6).
 *
 *   The solve returns quality notes — a GCP that fell outside the DEM and was left
 *   out, a point that reprojects far worse than the rest. They are true, and they
 *   are still in every response for anyone reading the API or the console. They are
 *   simply not INTERRUPTIONS: the estimate runs on every auto-GCP click and on every
 *   drag of a mark, so a note that is worth reading once became a toast that fired
 *   through the whole run and trained the surveyor to dismiss warnings unread.
 *
 *   This is the same treatment `auto_gcp_service` already gives the camera-shift and
 *   solved-vs-entered-tilt numbers: silenced as toasts, preserved as data. A warning
 *   nobody reads is worse than no warning, because it costs attention and buys
 *   nothing.
 */
function logPoseDiagnostics(imageId: string, warnings: readonly string[]): void {
  if (warnings.length === 0) return;
  // eslint-disable-next-line no-console -- a developer channel, deliberately not the UI
  console.debug('[auto-gcp] pose diagnostics for image %s:', imageId, warnings);
}

export function useImageCamera(imageId: Uuid | null): UseQueryResult<ImageCameraRead> {
  return useQuery({
    queryKey: qk.imageCamera(imageId!),
    queryFn: ({ signal }) => imageCameraApi.get(imageId!, signal),
    enabled: imageId !== null,
  });
}

export interface SaveImageCameraVariables {
  imageId: Uuid;
  body: ImageCameraPut;
}

export function useSaveImageCamera(): UseMutationResult<
  ImageCameraRead,
  unknown,
  SaveImageCameraVariables
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ imageId, body }: SaveImageCameraVariables) => imageCameraApi.put(imageId, body),
    onSuccess: (camera, { imageId }) => {
      queryClient.setQueryData(qk.imageCamera(imageId), camera);
    },
  });
}

export interface EstimateFromPixelVariables {
  imageId: Uuid;
  body: AutoGcpEstimateRequest;
}

/**
 * Estimate a photo pixel's world position from the photo's 4+ located GCPs.
 * ★ Read-only — nothing to invalidate; the caller decides whether the estimate
 * becomes a GCP (and the GCP-create hook does its own invalidation).
 */
export function useEstimateFromPixel(): UseMutationResult<
  AutoGcpEstimateRead,
  unknown,
  EstimateFromPixelVariables
> {
  return useMutation({
    mutationFn: ({ imageId, body }: EstimateFromPixelVariables) =>
      imageCameraApi.estimate(imageId, body),
    onSuccess: (data, { imageId }) => {
      logPoseDiagnostics(imageId, data.warnings ?? []);
    },
  });
}

export interface ProjectFromLatLonVariables {
  imageId: Uuid;
  body: AutoGcpProjectRequest;
}

/**
 * The estimate run BACKWARDS: a world coordinate → the pixel where it appears
 * through the solved pose. ★ Read-only, like `useEstimateFromPixel`, and its
 * diagnostics go to the same console-only channel.
 */
export function useProjectFromLatLon(): UseMutationResult<
  AutoGcpProjectRead,
  unknown,
  ProjectFromLatLonVariables
> {
  return useMutation({
    mutationFn: ({ imageId, body }: ProjectFromLatLonVariables) =>
      imageCameraApi.project(imageId, body),
    onSuccess: (data, { imageId }) => {
      logPoseDiagnostics(imageId, data.warnings ?? []);
    },
  });
}
