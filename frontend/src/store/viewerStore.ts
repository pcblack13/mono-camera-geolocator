/**
 * `viewerStore` — CONTRACT.md §8.5 / 50-frontend.md §3.4, §5.
 *
 * Owns: `transform {scale,x,y}` · `displayScale` (D) · `viewport` · `naturalSize` ·
 * `adjustments` · `isFullscreen` · `cursorImagePos` · `minScale`/`maxScale`.
 * Persisted: `adjustments` only.
 *
 * ★ **ALL the arithmetic lives in `lib/viewport/transform.ts`.** This store is
 *   wiring: it holds the state, builds the `ViewportContext`, and calls the pure
 *   functions. No component may inline any of it and neither may this file (§5).
 *
 * ★ **`displayScale` lives in the store, not in a prop** — deliberately (§3.4). It
 *   is an input to EVERY coordinate conversion, and a single store-owned value that
 *   changes atomically with `setImageSource` is far safer than a prop that can be
 *   stale by one render during a variant swap. A stale `D` for one frame is a wrong
 *   coordinate.
 *
 * ★ L7 — browser-only. `naturalSize`/`displayScale` are COPIED from `ImageVariant`
 *   at load; the store never fetches and never caches server data.
 */

import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';

import type { Point2D, Rect, Size } from '../types/common';
import {
  clampPan,
  compensateVariantSwap,
  fitScale,
  fitToView as computeFitToView,
  scaleLimits,
  stageToImage,
  zoomAt as computeZoomAt,
  zoomToActualSize as computeZoomToActualSize,
  zoomToImageRect as computeZoomToImageRect,
  type ViewerTransform,
  type ViewportContext,
} from '../lib/viewport/transform';

export type { ViewerTransform, ViewportContext };

export interface ImageAdjustments {
  /** UI range −100..100, 0 = neutral. */
  brightness: number;
  /** UI range −100..100, 0 = neutral. */
  contrast: number;
}

export interface ViewerState {
  transform: ViewerTransform;
  /** `D = variant.width / variant.original_width`. ★ NOT user-controlled. */
  displayScale: number;
  viewport: Size;
  /** ★ ORIGINAL dims. `null` until an image loads. */
  naturalSize: Size | null;
  adjustments: ImageAdjustments;
  isFullscreen: boolean;
  /** ★ ORIGINAL image px, for the status bar. */
  cursorImagePos: Point2D | null;
  minScale: number;
  maxScale: number;
  /**
   * ★ §5.6 — is the current transform still the one `fitToView` produced?
   *
   *   Tracked so a resize or a variant swap re-fits ONLY when the user had not
   *   zoomed themselves. **A user's manual zoom is never overridden**; silently
   *   re-fitting the pane while someone is lining up a corner GCP is the kind of
   *   thing that makes a tool feel hostile.
   */
  isFitted: boolean;

  setTransform: (t: ViewerTransform) => void;
  zoomAt: (stagePoint: Point2D, factor: number) => void;
  panBy: (dx: number, dy: number) => void;
  fitToView: () => void;
  zoomToActualSize: () => void;
  zoomToImageRect: (rect: Rect) => void;
  setViewport: (width: number, height: number) => void;
  setImageSource: (natural: Size, displayScale: number) => void;
  setAdjustment: (k: keyof ImageAdjustments, v: number) => void;
  resetAdjustments: () => void;
  setFullscreen: (v: boolean) => void;
  setCursorImagePos: (p: Point2D | null) => void;
  reset: () => void;
  /** The context for `lib/viewport/transform.ts`. `null` until an image loads. */
  context: () => ViewportContext | null;
}

const NEUTRAL: ImageAdjustments = { brightness: 0, contrast: 0 };

const INITIAL = {
  transform: { scale: 1, x: 0, y: 0 } satisfies ViewerTransform,
  displayScale: 1,
  viewport: { width: 0, height: 0 } satisfies Size,
  naturalSize: null,
  isFullscreen: false,
  cursorImagePos: null,
  minScale: 0.05,
  maxScale: 40,
  isFitted: true,
};

/**
 * ★ §6.4 — the CSS filter string. **Not a Konva filter, by architectural choice.**
 *
 *   `Konva.Node.cache()` rasterises into a buffer with its own origin and pixelRatio
 *   — it couples an APPEARANCE control to the GEOMETRY pipeline. A brightness slider
 *   must be incapable of moving a GCP by a fraction of a pixel, and the strongest
 *   guarantee is architectural rather than vigilance-based: CSS `filter` is a
 *   paint-stage op that **structurally cannot** touch the scene graph, the hit graph,
 *   or `getPointerPosition()`.
 *
 * ★ Order is `brightness` then `contrast` — CSS filters compose left-to-right, and
 *   contrast-then-brightness clips shadows differently and looks wrong on the
 *   underexposed field photos that are the common case.
 *
 * ★ Neutral returns `'none'`, omitting the property entirely so there is no
 *   compositing layer at rest.
 *
 * ★ Adjustments are NEVER sent to the backend and never affect matching. The slider
 *   is a human aid, not a preprocessing step.
 */
export function adjustmentsToFilterCss(a: ImageAdjustments): string {
  if (a.brightness === 0 && a.contrast === 0) return 'none';
  const b = 1 + (a.brightness / 100) * 0.8;
  const c = 1 + (a.contrast / 100) * 0.8;
  return `brightness(${b.toFixed(3)}) contrast(${c.toFixed(3)})`;
}

export const useViewerStore = create<ViewerState>()(
  devtools(
    persist(
      (set, get) => {
        const context = (): ViewportContext | null => {
          const s = get();
          if (!s.naturalSize) return null;
          return {
            transform: s.transform,
            displayScale: s.displayScale,
            naturalSize: s.naturalSize,
            viewport: s.viewport,
          };
        };

        /**
         * ★ THE single write path for the transform. `clampPan` is applied HERE, not
         *   at the call sites, so it cannot be forgotten (§5.5). Konva's
         *   `dragBoundFunc` is deliberately unused — it would double-clamp against
         *   this. One clamp, one owner.
         */
        const commit = (t: ViewerTransform, fitted: boolean, action: string): void => {
          const ctx = context();
          if (!ctx) return;
          set({ transform: clampPan(t, ctx), isFitted: fitted }, false, action);
        };

        return {
          ...INITIAL,
          adjustments: NEUTRAL,
          context,

          setTransform: (t) => commit(t, false, 'viewer/setTransform'),

          zoomAt: (stagePoint, factor) => {
            const ctx = context();
            if (!ctx) return;
            const s = get();
            commit(
              computeZoomAt(stagePoint, factor, ctx, {
                minScale: s.minScale,
                maxScale: s.maxScale,
              }),
              false,
              'viewer/zoomAt',
            );
          },

          panBy: (dx, dy) => {
            const s = get();
            commit(
              { scale: s.transform.scale, x: s.transform.x + dx, y: s.transform.y + dy },
              false,
              'viewer/panBy',
            );
          },

          fitToView: () => {
            const ctx = context();
            if (!ctx) return;
            // ★ `isFitted: true` — this transform IS a fit, so a later resize may re-fit it.
            commit(computeFitToView(ctx), true, 'viewer/fitToView');
          },

          zoomToActualSize: () => {
            const ctx = context();
            if (!ctx) return;
            const s = get();
            commit(
              computeZoomToActualSize(ctx, { minScale: s.minScale, maxScale: s.maxScale }),
              false,
              'viewer/zoomToActualSize',
            );
          },

          zoomToImageRect: (rect) => {
            const ctx = context();
            if (!ctx) return;
            const s = get();
            commit(
              computeZoomToImageRect(rect, ctx, { minScale: s.minScale, maxScale: s.maxScale }),
              false,
              'viewer/zoomToImageRect',
            );
          },

          setViewport: (width, height) => {
            const prev = get();
            const next: Size = { width, height };
            const natural = prev.naturalSize;
            if (!natural) {
              set({ viewport: next }, false, 'viewer/setViewport');
              return;
            }

            const ctx: ViewportContext = {
              transform: prev.transform,
              displayScale: prev.displayScale,
              naturalSize: natural,
              viewport: next,
            };
            const limits = scaleLimits(ctx);

            // ★ Re-fit on resize ONLY if the view was already a fit (§5.6). Otherwise
            //   just re-clamp the existing transform against the new viewport, which
            //   keeps the user's zoom and stops the image from stranding off-screen.
            const transform = prev.isFitted ? computeFitToView(ctx) : clampPan(prev.transform, ctx);

            set({ viewport: next, transform, ...limits }, false, 'viewer/setViewport');
          },

          /**
           * ★ §5.3 — the variant swap, applied ATOMICALLY with the bitmap swap in ONE
           *   store update, so no frame renders with mismatched `s`/`D`.
           *
           * ★ **No annotation coordinate is touched.** They are in ORIGINAL space,
           *   which is invariant across the swap. That is the payoff of the
           *   three-space design: variants become a pure presentation concern.
           */
          setImageSource: (natural, displayScale) => {
            const prev = get();
            const isNewImage =
              !prev.naturalSize ||
              prev.naturalSize.width !== natural.width ||
              prev.naturalSize.height !== natural.height;

            const nextCtx: ViewportContext = {
              transform: prev.transform,
              displayScale,
              naturalSize: natural,
              viewport: prev.viewport,
            };
            const limits = scaleLimits(nextCtx);

            if (isNewImage) {
              // A different image: reset to fit. Carrying a transform across images
              // would land the user at an arbitrary corner of the new one.
              set(
                {
                  naturalSize: natural,
                  displayScale,
                  ...limits,
                  transform: computeFitToView(nextCtx),
                  isFitted: true,
                  cursorImagePos: null,
                },
                false,
                'viewer/setImageSource:new',
              );
              return;
            }

            // Same image, new variant: keep the view pinned at the viewport centre.
            const prevCtx: ViewportContext = {
              transform: prev.transform,
              displayScale: prev.displayScale,
              naturalSize: natural,
              viewport: prev.viewport,
            };
            const transform = prev.isFitted
              ? computeFitToView(nextCtx)
              : compensateVariantSwap(prevCtx, displayScale);

            set(
              { naturalSize: natural, displayScale, ...limits, transform, isFitted: prev.isFitted },
              false,
              'viewer/setImageSource:variant',
            );
          },

          setAdjustment: (k, v) =>
            set(
              (s) => ({ adjustments: { ...s.adjustments, [k]: Math.max(-100, Math.min(100, v)) } }),
              false,
              `viewer/setAdjustment:${k}`,
            ),

          resetAdjustments: () => set({ adjustments: NEUTRAL }, false, 'viewer/resetAdjustments'),

          setFullscreen: (v) => set({ isFullscreen: v }, false, 'viewer/setFullscreen'),

          setCursorImagePos: (p) => set({ cursorImagePos: p }, false, 'viewer/setCursorImagePos'),

          reset: () =>
            // ★ `adjustments` deliberately survive: they are persisted per-user, not
            //   per-image (§6.4) — field conditions tend to be consistent across a shoot.
            set({ ...INITIAL }, false, 'viewer/reset'),
        };
      },
      {
        name: 'landexplorer.viewer',
        version: 1,
        // ★ Only `adjustments`. The transform is per-image-session and resets to fit
        //   on image change; persisting it would restore a zoom into a different image.
        partialize: (s) => ({ adjustments: s.adjustments }),
        merge: (persisted, current) => {
          const p = persisted as { adjustments?: Partial<ImageAdjustments> } | undefined;
          return { ...current, adjustments: { ...NEUTRAL, ...(p?.adjustments ?? {}) } };
        },
      },
    ),
    { name: 'viewerStore' },
  ),
);

/**
 * ★ **THE conversion helper for the ONE conversion site** (`ImageViewer`'s pointer
 *   handlers, §8.6).
 *
 *   Returns ORIGINAL image px, or `null` when no image is loaded. Exposed here so a
 *   component never rebuilds a `ViewportContext` by hand — the store owns `D`, and
 *   `D` assembled at a call site is `D` that can be stale.
 */
export function stagePointToImage(stagePoint: Point2D): Point2D | null {
  const ctx = useViewerStore.getState().context();
  if (!ctx) return null;
  return stageToImage(stagePoint, ctx);
}

/** The scale at which the whole image fits — for the zoom control's "Fit" readout. */
export function currentFitScale(): number | null {
  const ctx = useViewerStore.getState().context();
  return ctx ? fitScale(ctx) : null;
}
