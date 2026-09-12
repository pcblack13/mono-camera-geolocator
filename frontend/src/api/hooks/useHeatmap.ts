/**
 * Confidence heatmap — endpoint 49.
 *
 * ★★ DEFERRED — SCOPE.md §4. Returns `501` in this build. Gate on {@link useHeatmapDeferral}.
 *
 * ★ `mapStore.heatmapEnabled` (IU-25) is browser state — a toggle. It must be forced
 *   off and disabled while the feature is deferred, or the map mounts an overlay whose
 *   `<img>` 501s and renders broken. **A broken image is not an honest tooltip.**
 */

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import type { Uuid } from '../../types/common';
import type { HeatmapParams, HeatmapRead } from '../../types/heatmap';
import { heatmapApi } from '../heatmap';
import { qk } from '../queryKeys';
import { DEFERRED_TOOLTIP, useIsFeatureDeferred } from './useCapabilities';

/** The honest gate for the heatmap toggle. */
export function useHeatmapDeferral(): { disabled: boolean; tooltip: string | undefined } {
  const deferred = useIsFeatureDeferred('heatmap');
  return { disabled: deferred, tooltip: deferred ? DEFERRED_TOOLTIP.heatmap : undefined };
}

/**
 * ★ DEFERRED — endpoint 49 (`format=json`) → **`501`** in this build.
 *
 * ★ Gated on the capability AND on `enabled`, so the request is never fired for a
 *   feature the server has said it cannot answer.
 *
 * ★ The JSON form is the one to fetch even when rendering the PNG overlay:
 *   `grid.bbox` georeferences the image and `score_range` scales the legend, and both
 *   arrive on response HEADERS (`X-Heatmap-BBox`, `X-Heatmap-Score-Range`) that a
 *   browser will not expose to an `<img>`.
 */
export function useHeatmap(
  imageId: Uuid | null,
  params: HeatmapParams = {},
  enabled = true,
): UseQueryResult<HeatmapRead> {
  const deferred = useIsFeatureDeferred('heatmap');
  return useQuery({
    queryKey: qk.heatmap.forImageFiltered(imageId!, params),
    queryFn: ({ signal }) => heatmapApi.get(imageId!, params, signal),
    enabled: imageId !== null && enabled && !deferred,
  });
}
