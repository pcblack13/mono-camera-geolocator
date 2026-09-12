/**
 * `map/ConfidenceHeatmapLayer.tsx` — 50-frontend §2.18.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * ★★ DEFERRED SURFACE — SCOPE.md §1, §4.
 *
 *   The heatmap visualises *where a homography is trustworthy across the footprint* —
 *   which requires a matching engine to have produced a `match_result` and its
 *   confidence grid. **That engine is deferred**, so in this build no grid ever
 *   arrives (`useHeatmap` returns `501 FEATURE_DEFERRED`), and this layer renders
 *   NOTHING.
 *
 *   The layer is kept, and the toggle that drives it is DISABLED with an honest
 *   tooltip upstream in `MapPanel` (SCOPE.md §4 rule 4). The colour RAMP itself lives
 *   in `theme/confidence.ts` (it is theme, not engine) and is ready the day the grid
 *   is — re-enabling costs this component nothing but the removal of the early return
 *   (SCOPE.md §7).
 *
 *   The rasterise-to-canvas + `ImageOverlay` implementation §2.18 describes is
 *   deliberately NOT written speculatively: there is no data shape to write it against
 *   yet (the deferred `HeatmapRead` is a stub), and a canvas that never paints is dead
 *   code that would rot. When the engine lands it slots in here behind the same props.
 * ─────────────────────────────────────────────────────────────────────────────
 */

export interface ConfidenceHeatmapLayerProps {
  /** Honoured only when a match result and its grid exist — never, this build. */
  enabled: boolean;
  matchResultId: string | null;
  opacity: number;
}

export function ConfidenceHeatmapLayer(_props: ConfidenceHeatmapLayerProps): null {
  // DEFERRED: no confidence grid is produced while automatic matching is off. See header.
  return null;
}
