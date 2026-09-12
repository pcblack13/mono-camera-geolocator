/**
 * Confidence heatmap — mirrors `backend/app/schemas/pose.py`'s heatmap half (§6.2).
 *
 * ★★ DEFERRED (SCOPE.md §4): "Confidence heatmap over candidate camera locations" is
 *    an ABC only. `GET /images/{id}/heatmap` is registered and documented and
 *    returns `501` with a `feature: "deferred"` marker. The
 *    `confidence_heatmaps` / `confidence_heatmap_cells` tables ARE created exactly
 *    as specified — they simply hold no rows.
 *
 * ★ Vector, not raster. `postgis_raster` is deliberately NOT installed: the
 *   interaction model is per-cell-with-attributes (hover → score breakdown), which
 *   a raster band cannot hold; sparsity is free in vector; and a raster would force
 *   storage in 3857, reintroducing the Mercator distortion the design exists to
 *   avoid.
 */

import type { IsoDateTime, Uuid } from './common';
import type { BBox, LatLon } from './geo';

export type HeatmapFormat = 'json' | 'geojson' | 'png';

/**
 * ★ Continuous, perceptually uniform, **viridis-derived and REVERSED** so low
 *   confidence is the attention-getting end (yellow) rather than the pleasant end:
 *   `0.0 → #FDE725` (yellow, alarming in context), `0.5 → #21918C` (teal),
 *   `1.0 → #440154` (deep purple, "nothing to see here").
 *
 *   This inversion is deliberate — a heatmap where the GOOD regions glow brightly
 *   trains the eye to look at exactly the wrong places. A legend with numeric stops
 *   is mandatory and always rendered with the layer; an unlabelled heatmap is
 *   decoration.
 */
export type Colormap = 'viridis' | 'viridis_r' | 'magma' | 'inferno' | 'turbo' | 'gray';

/**
 * ★ Only the CENTROID is stored. The cell polygon is `centroid ± cell_size_m/2`,
 *   fully determined by the parent. Storing 10 000 five-vertex polygons is ~5× the
 *   bytes and ~5× the GIST index FOR ZERO INFORMATION.
 */
export interface HeatmapCell {
  col: number;
  row: number;
  /** ★ The cell CENTROID, EPSG:4326. */
  center: LatLon;
  /** 0–1. */
  score: number;
  /**
   * ★ A cell AGGREGATES every candidate whose centre fell in it. A cell with
   *   `sample_count = 1` is far less trustworthy than one with 12, and the UI dims
   *   it accordingly.
   */
  sample_count: number;
  /** Per-term score breakdown for the hover tooltip. */
  components: Record<string, number>;
}

export interface HeatmapGrid {
  cols: number;
  rows: number;
  /** ★ TRUE ground metres, never projected metres. */
  cell_size_m: number;
  bbox: BBox;
}

export interface HeatmapCandidate {
  match_result_id: Uuid | null;
  center: LatLon;
  score: number;
  rank: number;
}

export interface HeatmapScoreRange {
  min: number;
  max: number;
  mean: number;
}

/**
 * ★ Heatmap cells are SPARSE and the payload SAYS SO. **Absent ≠ score 0** — a cell
 *   with no candidate was never evaluated, which is a different claim from "we
 *   evaluated it and it scored zero". Rendering the first as the second would paint
 *   confident emptiness over unexplored ground.
 */
export interface HeatmapSparsity {
  cell_count: number;
  /** `grid.cols * grid.rows`. */
  total_cells: number;
  note: string;
}

export interface HeatmapRead {
  id: Uuid;
  match_job_id: Uuid;
  image_id: Uuid;
  grid: HeatmapGrid;
  cells: HeatmapCell[];
  sparsity: HeatmapSparsity;
  score_range: HeatmapScoreRange;
  argmax: HeatmapCandidate | null;
  candidates: HeatmapCandidate[];
  colormap: Colormap;
  render_url: string | null;
  created_at: IsoDateTime;
}

export interface HeatmapParams {
  format?: HeatmapFormat;
  colormap?: Colormap;
  /** Drop cells below this score to cut payload. Absent cells stay absent, not zero. */
  min_score?: number;
  include_components?: boolean;
}
