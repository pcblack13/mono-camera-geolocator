/**
 * ★★ THE VIEWER COORDINATE MATH — CONTRACT.md §8.6 / 50-frontend.md §5.
 *
 * **This is the product's highest-risk client code.** A GCP is a survey coordinate
 * someone may dig, build, or file against (L12). A coordinate corrupted by a zoom
 * transform is a wrong answer delivered confidently — the worst failure this system
 * has. Everything in this file exists for that sentence.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * ★ THE NORMATIVE RULE: annotation and GCP coordinates are ALWAYS in ORIGINAL
 *   IMAGE PIXEL SPACE, regardless of zoom, pan, variant, brightness or contrast.
 * ─────────────────────────────────────────────────────────────────────────────
 *
 * There are **THREE** coordinate spaces, not two:
 *
 * ```
 *   ORIGINAL image px  ──× D──▶  DISPLAY raster px  ──× s, +(tx,ty)──▶  STAGE px
 *      (5472×3648)                  (2048×1365)                         (viewport)
 *      ▲ the ONLY space              ▲ what Konva.Image                  ▲ what pointer
 *        ever stored                   actually holds                      events give us
 * ```
 *
 * | Symbol | Meaning | Source |
 * |---|---|---|
 * | `D` | `variant.display_scale = variant.width / variant.original_width` | server metadata |
 * | `s` | Konva stage scale — user zoom | `viewerStore.transform.scale` |
 * | `(tx, ty)` | Konva stage position — user pan, screen px | `viewerStore.transform` |
 *
 * ★ **THE NAIVE BUG this module exists to prevent** (§8.6, stated so a reviewer
 *   recognises it instantly): read `stage.getPointerPosition()`, divide by `s`,
 *   subtract the pan, store it. That yields **DISPLAY** pixels, not ORIGINAL ones.
 *   It silently disagrees with the backend (which computed features on the
 *   original) and every annotation jumps by `D₁/D₂` when a variant swaps. Because
 *   `D ≈ 1` on small test images, **it survives development and detonates on the
 *   first real 5000px upload.** The rule: `D` is in the pipeline ALWAYS, even when
 *   it equals 1.
 *
 * ★ **PURE.** No React, no Konva, no store imports — by construction, so this is
 *   unit- and property-testable in isolation (IU-29 owns the tests). No component
 *   may inline any of this arithmetic.
 *
 * ★ **Device pixel ratio never appears in these formulas.** Konva handles DPR
 *   internally and `getPointerPosition()` returns CSS-pixel stage coordinates.
 *   Introducing DPR here would be a bug.
 *
 * ★ **Sub-pixel policy: image coordinates are NEVER rounded.** Stored as `number`,
 *   sent as JSON floats, displayed to 1 decimal. A rounded correspondence carries
 *   needless error. Round for display, never for storage.
 */

import { err, ok, type Point2D, type Rect, type Result, type Size } from '../../types/common';

// ─────────────────────────────────────────────────────────────────────────────
// Types (§8.6, verbatim)
// ─────────────────────────────────────────────────────────────────────────────

/** The Konva stage transform: scale `s` and translation `(tx, ty)` in screen px. */
export interface ViewerTransform {
  /** `s` — stage scale: DISPLAY px → screen px. User zoom. */
  scale: number;
  /** `tx` — stage translation, screen px. */
  x: number;
  /** `ty` — stage translation, screen px. */
  y: number;
}

/**
 * Everything needed for a conversion. **Passed explicitly — never read from a store
 * here.** That is what keeps this module pure and what makes the round-trip
 * property test possible.
 */
export interface ViewportContext {
  /** `s`, `tx`, `ty`. */
  transform: ViewerTransform;
  /** `D = variant.width / variant.original_width`. */
  displayScale: number;
  /** ORIGINAL image dimensions. NOT the variant's. */
  naturalSize: Size;
  /** Container size in CSS px. */
  viewport: Size;
}

/** Zoom limits. Derived by {@link scaleLimits}; held in `viewerStore` (§8.5). */
export interface ScaleLimits {
  minScale: number;
  maxScale: number;
}

/**
 * Why a context is unusable. Carried by {@link Result} rather than thrown: these
 * guards run inside pointer handlers and a throw there unmounts the canvas mid-drag
 * (§8.2's rationale for `Result` naming the viewport guards explicitly).
 */
export interface TransformError {
  code:
    | 'INVALID_DISPLAY_SCALE'
    | 'INVALID_STAGE_SCALE'
    | 'INVALID_NATURAL_SIZE'
    | 'NON_FINITE_INPUT';
  message: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Constants (§5.4 / §5.5 / §5.6)
// ─────────────────────────────────────────────────────────────────────────────

/** §5.6 — leaves a 5% gutter so edge annotations are not flush against the pane border. */
export const FIT_PADDING = 0.95;

/**
 * §5.5 — the image may be pushed until half the viewport is empty.
 *
 * ★ Not cosmetic. It puts any edge/corner at the viewport CENTRE, where the
 *   crosshair is most precise. Without it, corner GCPs cannot be placed accurately
 *   — a real failure, not a theoretical one.
 */
export const OVERSCROLL = 0.5;

/** §5.6 — `zoomToImageRect` leaves context around the revealed point, not a claustrophobic crop. */
export const REVEAL_PADDING = 0.8;

/** §5.4 — the absolute zoom-out floor, in stage-scale terms, for ordinary images. */
export const MIN_SCALE_FLOOR = 0.05;

/** §5.4 — the user can always reach 40× ORIGINAL pixels, whichever variant is loaded. */
export const MAX_ORIGINAL_ZOOM = 40;

// ─────────────────────────────────────────────────────────────────────────────
// Guards
// ─────────────────────────────────────────────────────────────────────────────

const isFinitePoint = (p: Point2D): boolean => Number.isFinite(p.x) && Number.isFinite(p.y);

/**
 * ★ L12 — refuse rather than answer wrongly.
 *
 * `D = 0` or `s = 0` makes `stageToImage` divide by zero and return `Infinity`/`NaN`
 * — a coordinate that is *wrong*, not *absent*, and which would flow straight into a
 * command, the store, and the network. Callers that cannot tolerate a throw use
 * {@link safeStageToImage}; callers with a validated context use the bare functions.
 */
export function validateViewportContext(
  ctx: ViewportContext,
): Result<ViewportContext, TransformError> {
  if (!Number.isFinite(ctx.displayScale) || ctx.displayScale <= 0) {
    return err({
      code: 'INVALID_DISPLAY_SCALE',
      message: `displayScale must be a positive finite number, got ${String(ctx.displayScale)}`,
    });
  }
  if (!Number.isFinite(ctx.transform.scale) || ctx.transform.scale <= 0) {
    return err({
      code: 'INVALID_STAGE_SCALE',
      message: `transform.scale must be a positive finite number, got ${String(ctx.transform.scale)}`,
    });
  }
  if (
    !Number.isFinite(ctx.naturalSize.width) ||
    !Number.isFinite(ctx.naturalSize.height) ||
    ctx.naturalSize.width <= 0 ||
    ctx.naturalSize.height <= 0
  ) {
    return err({
      code: 'INVALID_NATURAL_SIZE',
      message: 'naturalSize must have positive finite dimensions',
    });
  }
  if (!Number.isFinite(ctx.transform.x) || !Number.isFinite(ctx.transform.y)) {
    return err({ code: 'NON_FINITE_INPUT', message: 'transform translation must be finite' });
  }
  return ok(ctx);
}

/** `stageToImage` with the guard applied. Use this at the pointer boundary. */
export function safeStageToImage(
  p: Point2D,
  ctx: ViewportContext,
): Result<Point2D, TransformError> {
  const valid = validateViewportContext(ctx);
  if (!valid.ok) return valid;
  if (!isFinitePoint(p)) {
    return err({ code: 'NON_FINITE_INPUT', message: 'pointer position must be finite' });
  }
  return ok(stageToImage(p, ctx));
}

// ─────────────────────────────────────────────────────────────────────────────
// The conversions (§8.6 — signatures are the contract's, verbatim)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * ★ **STAGE/screen → ORIGINAL image px. THE conversion site's function.**
 *
 * ```
 *   display.x = (p.x - tx) / s
 *   image.x   = display.x / D
 *   ∴ image.x = (p.x - tx) / (s * D)
 *     image.y = (p.y - ty) / (s * D)
 * ```
 *
 * `ImageViewer.onPointerDown/Move/Up` calls this once and **discards the raw stage
 * point**. The result is what goes into commands, stores, and the network.
 */
export function stageToImage(p: Point2D, ctx: ViewportContext): Point2D {
  const k = ctx.transform.scale * ctx.displayScale;
  return {
    x: (p.x - ctx.transform.x) / k,
    y: (p.y - ctx.transform.y) / k,
  };
}

/**
 * ★ **ORIGINAL image px → STAGE/screen px.**
 *
 * ```
 *   stage.x = p.x * D * s + tx
 *   stage.y = p.y * D * s + ty
 * ```
 *
 * ★ **ONLY for DOM overlays that live OUTSIDE the Konva Stage** — tooltips, the
 *   loupe, HTML labels — which do not inherit the Konva transform.
 *   `AnnotationLayer` must use {@link imageToDisplay} for node positions instead;
 *   using this one there **double-applies the stage transform** and produces
 *   annotations that drift at 2× the pan rate.
 */
export function imageToStage(p: Point2D, ctx: ViewportContext): Point2D {
  const k = ctx.transform.scale * ctx.displayScale;
  return {
    x: p.x * k + ctx.transform.x,
    y: p.y * k + ctx.transform.y,
  };
}

/**
 * ★ **ORIGINAL image px → DISPLAY raster px — what Konva NODES are positioned in.**
 *
 * Konva applies `s`/`(tx,ty)` for us because the nodes are Stage children. This is
 * the function `AnnotationLayer` wants. See {@link imageToStage}'s warning.
 */
export function imageToDisplay(p: Point2D, displayScale: number): Point2D {
  return { x: p.x * displayScale, y: p.y * displayScale };
}

/** DISPLAY raster px → ORIGINAL image px. */
export function displayToImage(p: Point2D, displayScale: number): Point2D {
  return { x: p.x / displayScale, y: p.y / displayScale };
}

/**
 * `s * D` — ORIGINAL px → screen px.
 *
 * The number to **inverse-scale chrome by**: a marker that should stay 12 screen px
 * across every zoom level is drawn at `12 / effectiveScale` in image terms.
 */
export function effectiveScale(ctx: ViewportContext): number {
  return ctx.transform.scale * ctx.displayScale;
}

/** ORIGINAL image rect → STAGE rect. For DOM overlays only — see {@link imageToStage}. */
export function imageRectToStage(r: Rect, ctx: ViewportContext): Rect {
  const k = effectiveScale(ctx);
  const origin = imageToStage({ x: r.x, y: r.y }, ctx);
  return { x: origin.x, y: origin.y, width: r.width * k, height: r.height * k };
}

/** STAGE rect → ORIGINAL image rect. */
export function stageRectToImage(r: Rect, ctx: ViewportContext): Rect {
  const k = effectiveScale(ctx);
  const origin = stageToImage({ x: r.x, y: r.y }, ctx);
  return { x: origin.x, y: origin.y, width: r.width / k, height: r.height / k };
}

/**
 * The region of the ORIGINAL image currently visible, in ORIGINAL px.
 *
 * Used for annotation culling and for compare-mode view sync. **Not clamped to the
 * image** — it deliberately reports the letterboxed area too, because a culler needs
 * the true visible window and a sync needs the true viewport footprint.
 */
export function visibleImageRect(ctx: ViewportContext): Rect {
  return stageRectToImage(
    { x: 0, y: 0, width: ctx.viewport.width, height: ctx.viewport.height },
    ctx,
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Guards on the image domain
// ─────────────────────────────────────────────────────────────────────────────

const clamp = (v: number, lo: number, hi: number): number => (v < lo ? lo : v > hi ? hi : v);

/**
 * Clamp an ORIGINAL-px point into `[0, width] × [0, height]`.
 *
 * ★ The bounds are INCLUSIVE of `width`/`height`, matching the API's
 *   `ANNOTATION_OUT_OF_BOUNDS` check (`all coords within [0, width] × [0, height]`).
 *   Clamping — not rejecting — is right at the drag boundary: a pointer that leaves
 *   the image during a drag should pin the vertex to the edge, not cancel the drag.
 */
export function clampToImageBounds(p: Point2D, natural: Size): Point2D {
  return {
    x: clamp(p.x, 0, natural.width),
    y: clamp(p.y, 0, natural.height),
  };
}

/** Is an ORIGINAL-px point inside `[0, width] × [0, height]`? Same inclusive bounds as the API. */
export function isWithinImage(p: Point2D, natural: Size): boolean {
  return (
    Number.isFinite(p.x) &&
    Number.isFinite(p.y) &&
    p.x >= 0 &&
    p.y >= 0 &&
    p.x <= natural.width &&
    p.y <= natural.height
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Fit, limits, pan clamping (§5.5 / §5.6)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * The stage scale at which the whole ORIGINAL image fits the viewport, with
 * {@link FIT_PADDING}.
 *
 * ```
 *   sw  = viewport.width  / (natural.width  * D)     // note the * D — we fit the ORIGINAL
 *   sh  = viewport.height / (natural.height * D)
 *   fit = min(sw, sh) * FIT_PADDING
 * ```
 */
export function fitScale(ctx: ViewportContext): number {
  const sw = ctx.viewport.width / (ctx.naturalSize.width * ctx.displayScale);
  const sh = ctx.viewport.height / (ctx.naturalSize.height * ctx.displayScale);
  return Math.min(sw, sh) * FIT_PADDING;
}

/**
 * §5.4 — `minScale = min(fitScale * 0.5, 0.05)` · `maxScale = 40 / D`.
 *
 * ★ **`min`, not `max` — and the asymmetry is load-bearing.** For an ordinary image
 *   `fitScale * 0.5 > 0.05`, so the floor is 5% and the prose "never below 5%"
 *   holds. For a very large image `fitScale` is itself tiny (a 20000px raster fits
 *   at ~0.02); `max` would put the floor ABOVE fit and **the user could not even
 *   reach fit-to-view**. `min` always admits fit and half-fit. Do not "fix" this.
 *
 * ★ `maxScale = 40 / D` expresses the cap in ORIGINAL-pixel terms, so "max zoom"
 *   means the same thing regardless of which variant is loaded.
 */
export function scaleLimits(ctx: ViewportContext): ScaleLimits {
  return {
    minScale: Math.min(fitScale(ctx) * 0.5, MIN_SCALE_FLOOR),
    maxScale: MAX_ORIGINAL_ZOOM / ctx.displayScale,
  };
}

/**
 * §5.5 — the user can never lose the image off-screen, but can bring any edge to the
 * centre.
 *
 * - **Fits → centred, hard.** A free-floating small image looks broken.
 * - **Overflows → clamped with {@link OVERSCROLL} of the viewport as margin.**
 *
 * ★ Applied on EVERY transform write and enforced inside `viewerStore.setTransform`
 *   rather than at the call sites, so it cannot be forgotten. Konva's
 *   `dragBoundFunc` is deliberately NOT used — it would double-clamp against this.
 *   One clamp, one owner.
 */
export function clampPan(t: ViewerTransform, ctx: ViewportContext): ViewerTransform {
  const sw = ctx.naturalSize.width * ctx.displayScale * t.scale;
  const sh = ctx.naturalSize.height * ctx.displayScale * t.scale;
  const mx = ctx.viewport.width * OVERSCROLL;
  const my = ctx.viewport.height * OVERSCROLL;

  const x =
    sw <= ctx.viewport.width
      ? (ctx.viewport.width - sw) / 2
      : clamp(t.x, ctx.viewport.width - sw - mx, mx);
  const y =
    sh <= ctx.viewport.height
      ? (ctx.viewport.height - sh) / 2
      : clamp(t.y, ctx.viewport.height - sh - my, my);

  return { scale: t.scale, x, y };
}

/**
 * §5.6 — fit the whole ORIGINAL image in the viewport. `clampPan` does the centring.
 */
export function fitToView(ctx: ViewportContext): ViewerTransform {
  const scale = fitScale(ctx);
  return clampPan({ scale, x: 0, y: 0 }, ctx);
}

/**
 * §5.6 — `scale = 1 / D`: one ORIGINAL pixel = one CSS pixel.
 *
 * ★ That is the correct definition of "100%" for this product, and it is only
 *   expressible because `D` is explicit.
 */
export function zoomToActualSize(ctx: ViewportContext, limits: ScaleLimits): ViewerTransform {
  const scale = clamp(1 / ctx.displayScale, limits.minScale, limits.maxScale);
  return zoomAt(centerOf(ctx.viewport), scale / ctx.transform.scale, ctx, limits);
}

const centerOf = (v: Size): Point2D => ({ x: v.width / 2, y: v.height / 2 });

// ─────────────────────────────────────────────────────────────────────────────
// Zoom-to-cursor (§5.4)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * ★ **THE INVARIANT: the image point under the cursor does not move.**
 *
 * ```
 *   1. before = stageToImage(pointer, ctx)              // ORIGINAL px under cursor
 *   2. sNext  = clamp(s * factor, minScale, maxScale)
 *   3. if sNext === s: return t unchanged               // at a limit; do NOT translate
 *   4. tx' = pointer.x - before.x * D * sNext
 *      ty' = pointer.y - before.y * D * sNext
 *   5. clampPan
 * ```
 *
 * Step 4 is the algebra of solving `imageToStage(before) = pointer` for `t` at
 * `sNext`. **Step 3 matters**: at max zoom, continued wheeling must not translate —
 * omitting it makes the image creep at the zoom limit.
 *
 * @param pointer stage-container coords (what `stage.getPointerPosition()` returns)
 * @param factor  multiplicative zoom step; see `ImageViewer` for the wheel/pinch mapping
 */
export function zoomAt(
  pointer: Point2D,
  factor: number,
  ctx: ViewportContext,
  limits: ScaleLimits,
): ViewerTransform {
  const s = ctx.transform.scale;
  const sNext = clamp(s * factor, limits.minScale, limits.maxScale);

  // ★ At a limit: return the transform untouched. Not a no-op for politeness — a
  //   translate here is the "creeping at max zoom" bug.
  if (sNext === s) return ctx.transform;

  const before = stageToImage(pointer, ctx);
  const k = ctx.displayScale * sNext;

  return clampPan({ scale: sNext, x: pointer.x - before.x * k, y: pointer.y - before.y * k }, ctx);
}

/**
 * §5.6 / §3.5 — the "locate GCP" reveal. Frames an ORIGINAL-px rect in the viewport
 * with {@link REVEAL_PADDING} of context around it.
 *
 * A zero-area rect (revealing a single point) is handled: the scale term degenerates
 * to `Infinity`, so we clamp to `maxScale` and simply centre the point.
 */
export function zoomToImageRect(
  r: Rect,
  ctx: ViewportContext,
  limits: ScaleLimits,
): ViewerTransform {
  const sw = ctx.viewport.width / (r.width * ctx.displayScale);
  const sh = ctx.viewport.height / (r.height * ctx.displayScale);
  const raw = Math.min(sw, sh) * REVEAL_PADDING;
  const scale = clamp(
    Number.isFinite(raw) ? raw : limits.maxScale,
    limits.minScale,
    limits.maxScale,
  );

  const k = ctx.displayScale * scale;
  const cx = r.x + r.width / 2;
  const cy = r.y + r.height / 2;
  const c = centerOf(ctx.viewport);

  return clampPan({ scale, x: c.x - cx * k, y: c.y - cy * k }, ctx);
}

// ─────────────────────────────────────────────────────────────────────────────
// Variant swapping (§5.3)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * ★ **Swap `preview` → `full` without moving anything.**
 *
 * `D` changes (0.374 → 0.749). Leaving `s` alone would visibly double the image. A
 * pure `s` compensation (`s' = s · D_old / D_new`) pins the STAGE ORIGIN — the
 * image's top-left — not the viewport centre. The correct operation anchors at the
 * viewport centre:
 *
 * ```
 *   c_img = stageToImage(viewportCentre, ctx_old)   // captured BEFORE the swap, in ORIGINAL px
 *   s'    = s * D_old / D_new
 *   tx'   = c.x - c_img.x * D_new * s'
 *   ty'   = c.y - c_img.y * D_new * s'
 * ```
 *
 * ★ Because `c_img` is in **ORIGINAL** space it is invariant across the swap — which
 *   is precisely why the three-space model makes the whole system tractable.
 *   **No annotation coordinate is touched.** Variants are a pure presentation
 *   concern. The store applies this atomically with the bitmap swap in one update,
 *   so no frame renders with mismatched `s`/`D`.
 *
 * @param ctx  the context BEFORE the swap (carrying `D_old`)
 * @param nextDisplayScale `D_new`
 */
export function compensateVariantSwap(
  ctx: ViewportContext,
  nextDisplayScale: number,
): ViewerTransform {
  const c = centerOf(ctx.viewport);
  const cImg = stageToImage(c, ctx);
  const scale = (ctx.transform.scale * ctx.displayScale) / nextDisplayScale;
  const k = nextDisplayScale * scale;

  const nextCtx: ViewportContext = {
    ...ctx,
    displayScale: nextDisplayScale,
    transform: { scale, x: 0, y: 0 },
  };
  return clampPan({ scale, x: c.x - cImg.x * k, y: c.y - cImg.y * k }, nextCtx);
}
