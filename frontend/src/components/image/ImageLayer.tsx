/**
 * `image/ImageLayer.tsx` (pure) — 50-frontend.md §2.10 / §6.3.
 *
 * A dedicated Konva `Layer` holding exactly ONE `Konva.Image`, drawn at the display
 * variant's dimensions. The Stage applies `s`/`(tx,ty)`.
 *
 * ★★ THE LAYER SPLIT EXISTS FOR THE CSS FILTER (§6.3). Konva renders each Layer to
 *    its own `<canvas>`, so applying `filter` to THIS layer's canvas colours the
 *    imagery and nothing else — the annotation and overlay layers render at true
 *    colour, keeping the confidence palette (§8.6) exact under `brightness(1.6)`.
 *
 * ★ **CSS filter, never `Konva.Filters`** (§6.2). `Konva.Node.cache()` rasterises
 *   into a buffer with its own origin/pixelRatio and is a documented source of
 *   sub-pixel offset bugs — it would couple an APPEARANCE control to the GEOMETRY
 *   pipeline, and a brightness slider must be structurally incapable of moving a GCP.
 *   A CSS `filter` is a paint-stage op that cannot touch the scene graph, the hit
 *   graph, or `getPointerPosition()`. The guarantee is architectural.
 *
 * ★ `listening={false}` — the image never needs hit detection, which halves the
 *   hit-graph cost on a large raster. All hit-testing is the annotation layer's.
 */

import { useLayoutEffect, useRef } from 'react';
import { Image as KonvaImage, Layer } from 'react-konva';
import type Konva from 'konva';

export interface ImageLayerProps {
  image: HTMLImageElement | ImageBitmap;
  displayWidth: number;
  displayHeight: number;
  /** e.g. `'brightness(1.15) contrast(0.9)'`, or `'none'` at rest (§6.4). */
  filterCss: string;
}

export function ImageLayer({
  image,
  displayWidth,
  displayHeight,
  filterCss,
}: ImageLayerProps): JSX.Element {
  const layerRef = useRef<Konva.Layer>(null);

  // ★ §6.3 — apply the filter to the layer's native canvas element. This is a
  //   paint-time compositor property; it never enters Konva's transform.
  useLayoutEffect(() => {
    const layer = layerRef.current;
    if (!layer) return;
    const canvas = layer.getCanvas()._canvas as HTMLCanvasElement | undefined;
    if (canvas) canvas.style.filter = filterCss;
  }, [filterCss]);

  return (
    <Layer ref={layerRef} listening={false}>
      <KonvaImage
        image={image as unknown as CanvasImageSource}
        x={0}
        y={0}
        width={displayWidth}
        height={displayHeight}
        // Smooth on downscale (thumb/preview) — a nearest-neighbour raster reads as
        // "broken", and the surveyor judges the imagery, not the resampler.
        imageSmoothingEnabled
        perfectDrawEnabled={false}
      />
    </Layer>
  );
}
