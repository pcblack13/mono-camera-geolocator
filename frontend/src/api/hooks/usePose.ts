/**
 * Camera pose — endpoint 48.
 *
 * ★★ DEFERRED — SCOPE.md §4. Returns `501` in this build. Gate on {@link usePoseDeferral}.
 */

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import type { Uuid } from '../../types/common';
import type { CameraPoseRead } from '../../types/pose';
import { poseApi } from '../pose';
import { qk } from '../queryKeys';
import { DEFERRED_TOOLTIP, useIsFeatureDeferred } from './useCapabilities';

/** The honest gate for a pose panel. */
export function usePoseDeferral(): { disabled: boolean; tooltip: string | undefined } {
  const deferred = useIsFeatureDeferred('camera_pose');
  return { disabled: deferred, tooltip: deferred ? DEFERRED_TOOLTIP.camera_pose : undefined };
}

/**
 * ★ DEFERRED — endpoint 48 → **`501`** in this build.
 *
 * ★ `enabled` is gated on the capability, not just on `imageId`. Rule 4 again: the
 *   request is never fired when the server has told us it cannot be answered, so the
 *   panel renders its explainer instead of a spinner.
 *
 * ★ WHEN LIVE, a `404 CAMERA_POSE_NOT_AVAILABLE` is a NORMAL, EXPECTED answer — most
 *   images have no pose row. It is a 4xx, so §8.4's predicate already never retries
 *   it; the panel renders "no pose for this image", not an error.
 */
export function usePose(imageId: Uuid | null): UseQueryResult<CameraPoseRead> {
  const deferred = useIsFeatureDeferred('camera_pose');
  return useQuery({
    queryKey: qk.pose.forImage(imageId!),
    queryFn: ({ signal }) => poseApi.get(imageId!, signal),
    enabled: imageId !== null && !deferred,
  });
}
