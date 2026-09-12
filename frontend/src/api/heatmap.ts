/**
 * Confidence heatmap — endpoint 49 (§7).
 *
 * ★★ DEFERRED — SCOPE.md §4. The confidence heatmap over candidate camera locations is
 *    an ABC only, and the `confidence_heatmap` table holds no rows (rule 5). Endpoint
 *    49 returns **`501`** with a `feature: "deferred"` marker.
 *
 * ★ Same 404-vs-501 reasoning as `pose.ts`: §7 types a `404 HEATMAP_NOT_AVAILABLE`
 *   for "no heatmap for this image", but in this build no image can have one, so
 *   `501` is the honest answer. Flagged for IU-21.
 */

import type { Uuid } from '../types/common';
import type { GeoJsonFeatureCollection } from '../types/geo';
import type { HeatmapCell, HeatmapParams, HeatmapRead } from '../types/heatmap';
import { buildUrl, fetchJson, toQuery } from './client';

export const heatmapApi = {
  /** ★ DEFERRED — endpoint 49, `format=json` (the default) → **`501`** in this build. */
  get: (imageId: Uuid, params: HeatmapParams = {}, signal?: AbortSignal): Promise<HeatmapRead> =>
    fetchJson<HeatmapRead>(`/images/${imageId}/heatmap`, {
      query: { ...toQuery(params), format: 'json' },
      signal,
    }),

  /** ★ DEFERRED — endpoint 49, `format=geojson`. */
  getGeoJson: (
    imageId: Uuid,
    params: HeatmapParams = {},
    signal?: AbortSignal,
  ): Promise<GeoJsonFeatureCollection<HeatmapCell>> =>
    fetchJson<GeoJsonFeatureCollection<HeatmapCell>>(`/images/${imageId}/heatmap`, {
      query: { ...toQuery(params), format: 'geojson' },
      signal,
    }),

  /**
   * ★ DEFERRED — endpoint 49, `format=png`. A URL, not a fetch: it is a Leaflet
   *   `ImageOverlay` source. The `X-Heatmap-BBox` and `X-Heatmap-Score-Range`
   *   response headers that georeference it are unreadable from an `<img>` — take the
   *   bbox from `HeatmapRead.grid.bbox` and the range from `HeatmapRead.score_range`
   *   instead, i.e. the JSON call must precede the overlay.
   *
   * ★ In this build the `<img>` will 501 and render broken. **The UI must gate on
   *   `useCapabilities().deferred_features` and never mount the overlay** — SCOPE.md
   *   §4 rule 4: disabled with an honest tooltip, not a broken image.
   */
  renderUrl: (imageId: Uuid, params: HeatmapParams = {}): string =>
    buildUrl(`/images/${imageId}/heatmap`, { ...toQuery(params), format: 'png' }),
};
