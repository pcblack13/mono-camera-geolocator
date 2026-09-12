/**
 * `image/CrosshairCursor.tsx` (pure) — the precision crosshair for point placement
 * and correspondence marking. 50-frontend.md §2.9/§2.10.
 *
 * ★ **A DOM overlay, not a Konva node** (§5.2). It lives OUTSIDE the Stage, so it does
 *   not inherit the stage transform and is drawn directly in screen/stage-container
 *   coordinates — which is exactly why it stays a constant size and pixel-sharp at
 *   every zoom. `imageToStage` is the sanctioned conversion for such overlays; here
 *   the viewer already has the stage-space pointer, so no conversion is needed.
 *
 * ★ `pointer-events: none` — the crosshair must never eat the click it is helping the
 *   surveyor aim.
 */

export interface CrosshairCursorProps {
  visible: boolean;
  /** Stage-container (screen) coordinates of the cursor. */
  x: number;
  y: number;
  width: number;
  height: number;
  color: string;
}

export function CrosshairCursor({
  visible,
  x,
  y,
  width,
  height,
  color,
}: CrosshairCursorProps): JSX.Element | null {
  if (!visible) return null;
  return (
    <svg
      width={width}
      height={height}
      aria-hidden
      style={{
        position: 'absolute',
        inset: 0,
        pointerEvents: 'none',
        zIndex: 2,
      }}
    >
      <line x1={x} y1={0} x2={x} y2={height} stroke={color} strokeWidth={1} opacity={0.5} />
      <line x1={0} y1={y} x2={width} y2={y} stroke={color} strokeWidth={1} opacity={0.5} />
      <circle cx={x} cy={y} r={5} fill="none" stroke={color} strokeWidth={1.5} />
      <circle cx={x} cy={y} r={1} fill={color} />
    </svg>
  );
}
