/**
 * `workspace/Splitter.tsx` — the resize handle (50-frontend §1.4 / §2.7). **(pure)**
 *
 * ★ It emits DELTAS, not absolute sizes: "the parent owns the sizing policy and
 *   clamping, so the splitter stays dumb and reusable for both axes." The same
 *   component serves the vertical column seams and the horizontal dock seam.
 *
 * ★ Pointer flow per §1.4: `pointerdown` → `setPointerCapture` → `pointermove`
 *   (rAF-throttled) → `pointerup`. Coalescing to one rAF is what keeps a drag over a
 *   5472×3648 canvas from thrashing layout.
 *
 * ★ Keyboard-operable, `role="separator"` with `aria-orientation`/`aria-valuenow`,
 *   `tabindex=0`. Arrows nudge, `Enter` resets. A field surveyor on a keyboard-only
 *   setup must be able to size the panes.
 *
 * ★ Hit area is 6px visual / 12px pointer via the `::before` inset expansion — a real
 *   pointer target without a fat visual seam.
 */

import {
  useCallback,
  useEffect,
  useRef,
  type JSX,
  type KeyboardEvent,
  type PointerEvent,
} from 'react';
import Box from '@mui/material/Box';

import { useDirection } from '../../i18n';

export interface SplitterProps {
  orientation: 'vertical' | 'horizontal';
  ariaLabel: string;
  /** 0..100, percentage of the flexible axis — reported as `aria-valuenow`. */
  valueNow: number;
  min?: number;
  max?: number;
  onDragDelta: (deltaPx: number) => void;
  onDragEnd?: () => void;
  onReset?: () => void;
  disabled?: boolean;
}

/** px nudged per arrow keypress — a keyboard analogue of §1.4's "nudge 2%". */
const KEY_STEP_PX = 24;

export function Splitter({
  orientation,
  ariaLabel,
  valueNow,
  min = 0,
  max = 100,
  onDragDelta,
  onDragEnd,
  onReset,
  disabled = false,
}: SplitterProps): JSX.Element {
  const isVertical = orientation === 'vertical'; // vertical seam ↔ horizontal drag (x)
  // ★ The delta CONTRACT is visual-LTR: "+" grows the pane that sits left of the
  //   seam in a left-to-right page. In the mirrored Arabic UI the flex row runs
  //   the other way, so a rightward pointer move must report as "−" for the
  //   parent's sizing maths to keep matching what the hand did. Only the
  //   horizontal axis mirrors; vertical drags are direction-blind.
  const direction = useDirection();
  const xSign = isVertical && direction === 'rtl' ? -1 : 1;
  const draggingRef = useRef(false);
  const lastPosRef = useRef(0);
  const pendingRef = useRef(0);
  const rafRef = useRef<number | null>(null);

  const flush = useCallback(() => {
    rafRef.current = null;
    const delta = pendingRef.current;
    pendingRef.current = 0;
    if (delta !== 0) onDragDelta(delta);
  }, [onDragDelta]);

  const schedule = useCallback(
    (delta: number) => {
      pendingRef.current += delta;
      if (rafRef.current === null) {
        rafRef.current = window.requestAnimationFrame(flush);
      }
    },
    [flush],
  );

  useEffect(
    () => () => {
      if (rafRef.current !== null) window.cancelAnimationFrame(rafRef.current);
    },
    [],
  );

  const onPointerDown = useCallback(
    (e: PointerEvent<HTMLDivElement>) => {
      if (disabled) return;
      draggingRef.current = true;
      lastPosRef.current = isVertical ? e.clientX : e.clientY;
      e.currentTarget.setPointerCapture(e.pointerId);
    },
    [disabled, isVertical],
  );

  const onPointerMove = useCallback(
    (e: PointerEvent<HTMLDivElement>) => {
      if (!draggingRef.current) return;
      const pos = isVertical ? e.clientX : e.clientY;
      const delta = (pos - lastPosRef.current) * xSign;
      lastPosRef.current = pos;
      if (delta !== 0) schedule(delta);
    },
    [isVertical, schedule, xSign],
  );

  const endDrag = useCallback(
    (e: PointerEvent<HTMLDivElement>) => {
      if (!draggingRef.current) return;
      draggingRef.current = false;
      if (e.currentTarget.hasPointerCapture(e.pointerId)) {
        e.currentTarget.releasePointerCapture(e.pointerId);
      }
      if (rafRef.current !== null) {
        window.cancelAnimationFrame(rafRef.current);
        flush();
      }
      onDragEnd?.();
    },
    [flush, onDragEnd],
  );

  const onKeyDown = useCallback(
    (e: KeyboardEvent<HTMLDivElement>) => {
      if (disabled) return;
      const dec = isVertical ? 'ArrowLeft' : 'ArrowUp';
      const inc = isVertical ? 'ArrowRight' : 'ArrowDown';
      if (e.key === dec) {
        e.preventDefault();
        onDragDelta(-KEY_STEP_PX * xSign);
      } else if (e.key === inc) {
        e.preventDefault();
        onDragDelta(KEY_STEP_PX * xSign);
      } else if (e.key === 'Enter' || e.key === 'Home') {
        e.preventDefault();
        onReset?.();
      }
    },
    [disabled, isVertical, onDragDelta, onReset, xSign],
  );

  return (
    <Box
      role="separator"
      aria-orientation={isVertical ? 'vertical' : 'horizontal'}
      aria-label={ariaLabel}
      aria-valuenow={Math.round(valueNow)}
      aria-valuemin={min}
      aria-valuemax={max}
      aria-disabled={disabled || undefined}
      tabIndex={disabled ? -1 : 0}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onDoubleClick={() => onReset?.()}
      onKeyDown={onKeyDown}
      sx={{
        'position': 'relative',
        'flex': '0 0 auto',
        'width': isVertical ? 6 : '100%',
        'height': isVertical ? '100%' : 6,
        'cursor': disabled ? 'default' : isVertical ? 'col-resize' : 'row-resize',
        'bgcolor': 'divider',
        'touchAction': 'none',
        'transition': 'background-color 120ms',
        '&:hover': disabled ? undefined : { bgcolor: 'primary.main' },
        '&:focus-visible': {
          outline: '2px solid',
          outlineColor: 'primary.main',
          outlineOffset: -1,
        },
        // ★ 12px pointer target without a 12px visual seam.
        '&::before': {
          content: '""',
          position: 'absolute',
          top: isVertical ? 0 : -3,
          bottom: isVertical ? 0 : -3,
          left: isVertical ? -3 : 0,
          right: isVertical ? -3 : 0,
        },
      }}
    />
  );
}

export default Splitter;
