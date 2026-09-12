/**
 * The aria-live announcer must be INVISIBLE TO LAYOUT, not just to eyes.
 *
 * ★ THE BUG THIS PINS (2026-09-01): `visuallyHiddenSx` said `width: 1, height: 1`
 *   — and in MUI's `sx`, a numeric size in (0, 1] means **100%**. The two
 *   announcers became full-viewport absolute boxes below the shell; clipped and
 *   unseen, they still stretched the document's scroll extent, so every page
 *   could scroll a whole viewport of nothing and the top bars slid away.
 */

import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';

import { LiveRegion, visuallyHiddenSx } from '../components/common/LiveRegion';

describe('the live-region announcer', () => {
  it('★ hides with PIXEL units — a bare 1 is 100% in sx, a whole viewport of nothing', () => {
    expect(visuallyHiddenSx.width).toBe('1px');
    expect(visuallyHiddenSx.height).toBe('1px');
    expect(visuallyHiddenSx.margin).toBe('-1px');
  });

  it('renders one square pixel, absolutely positioned and clipped', () => {
    const { container } = render(<LiveRegion message="Added point P4" />);
    const el = container.firstElementChild as HTMLElement;
    const style = getComputedStyle(el);
    expect(style.position).toBe('absolute');
    expect(style.height).toBe('1px');
    expect(style.width).toBe('1px');
    // Still in the accessibility tree — hidden, never display:none.
    expect(el).toHaveAttribute('role', 'status');
    expect(style.display).not.toBe('none');
  });
});
