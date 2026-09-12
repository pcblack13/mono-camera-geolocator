/**
 * `map/ErrorHeatOverlay.tsx` — the measured geolocation error, on the satellite pane.
 *
 * ★ WHY IT BELONGS HERE. The heat map answers "which part of this scene is wrong", and
 *   the surveyor decides where to place the next point ON THIS PANE. Making them open
 *   another tab to see it meant carrying the answer across a screen from memory.
 *
 * ★ IT IS PLACED BY WARPED CORNERS, not by the ortho grid's. The layer this draws
 *   (`heat_web_*`) is reprojected to Web Mercator server-side and comes with its own
 *   lat/lon bounds, because Leaflet stretches an overlay linearly between the corners
 *   it is given. Handing it the projected grid's corners would rotate the image by the
 *   meridian convergence — an ERROR map placed tens of metres from the error it
 *   describes, which is worse than showing nothing.
 *
 * ★ Semi-transparent and non-interactive: it sits under the GCP markers so it can never
 *   hide a point or swallow the click that places one.
 */

import type { JSX } from 'react';
import { ImageOverlay } from 'react-leaflet';

import { layerUrl, type AccuracyGrid, type SolutionKey } from '../../api/accuracy';
import type { Uuid } from '../../types/common';

export interface ErrorHeatOverlayProps {
  imageId: Uuid;
  /** The measurement's grid — carries `web_bounds`. */
  grid: AccuracyGrid;
  /** Which stage's error to draw. */
  stage: SolutionKey;
  /** Layer names the server actually has, so a missing stage draws nothing. */
  availableLayers: readonly string[];
  opacity?: number;
}

export function ErrorHeatOverlay({
  imageId,
  grid,
  stage,
  availableLayers,
  opacity = 0.75,
}: ErrorHeatOverlayProps): JSX.Element | null {
  const bounds = grid.web_bounds;
  if (bounds == null) return null;

  const layer = `heat_web_${stage}`;
  // Fall back to the raw error: it always exists once a measurement does, and drawing
  // nothing because a per-stage layer is missing would read as "no error here".
  const name = availableLayers.includes(layer) ? layer : 'heat_web_raw';
  if (!availableLayers.includes(name)) return null;

  return (
    <ImageOverlay
      // ★ Keyed by layer AND by when it was measured: React would otherwise reuse the
      //   same <img> across a re-measurement and keep showing the previous run's heat.
      key={`${name}:${grid.vmax_m}:${bounds.south}:${bounds.west}`}
      url={layerUrl(imageId, name)}
      bounds={[
        [bounds.south, bounds.west],
        [bounds.north, bounds.east],
      ]}
      opacity={opacity}
      interactive={false}
      zIndex={350}
    />
  );
}
