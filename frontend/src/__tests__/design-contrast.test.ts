/**
 * Phase 5's gate: WCAG AA contrast in BOTH themes — computed from the real
 * tokens, not asserted from memory.
 *
 * ★ The ratios are calculated out of `tokens.css` itself, so retuning a surface
 *   or an ink re-runs the arithmetic. A palette that passes AA on the day it was
 *   designed and drifts below it two edits later is the failure this prevents.
 *
 * ★ WHAT IS CHECKED IS TEXT. The accuracy hues are marker fills with their own
 *   redundant encodings (glyph, dash); they are checked at the 3:1 graphics
 *   threshold, not the 4.5:1 text one — holding paint to a text standard would
 *   just force the bands toward each other.
 */

import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { luminance } from '../lib/contrast';

const css = readFileSync(resolve(__dirname, '../theme/tokens.css'), 'utf8');

function token(selector: string, name: string): string {
  const block = new RegExp(`${selector}\\s*\\{([\\s\\S]*?)\\n\\}`).exec(css);
  if (!block) throw new Error(`no block for ${selector}`);
  const m = new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{3,8})\\s*;`).exec(block[1]);
  if (!m) throw new Error(`--${name} in ${selector} is not a plain hex`);
  return m[1];
}

function ratio(a: string, b: string): number {
  const [l1, l2] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (l1 + 0.05) / (l2 + 0.05);
}

const DARK = ":root\\[data-theme='dark'\\]";
const LIGHT = ":root\\[data-theme='light'\\]";

describe.each([
  ['dark', DARK],
  ['light', LIGHT],
])('%s theme', (_name, sel) => {
  it('holds 4.5:1 for primary text on every surface', () => {
    const ink = token(sel, 'text-primary');
    for (const surface of ['bg-base', 'bg-elevated', 'bg-overlay', 'bg-inset']) {
      expect(ratio(ink, token(sel, surface)), `text-primary on ${surface}`).toBeGreaterThanOrEqual(
        4.5,
      );
    }
  });

  it('holds 4.5:1 for secondary text on the surfaces it labels', () => {
    const ink = token(sel, 'text-secondary');
    for (const surface of ['bg-base', 'bg-elevated']) {
      expect(
        ratio(ink, token(sel, surface)),
        `text-secondary on ${surface}`,
      ).toBeGreaterThanOrEqual(4.5);
    }
  });

  it('keeps the accent legible as text and as a filled control', () => {
    // as link/label text on the base surface
    expect(ratio(token(sel, 'accent'), token(sel, 'bg-base'))).toBeGreaterThanOrEqual(4.5);
    // as a contained button: its own contrast ink on the accent fill
    expect(ratio(token(sel, 'accent-contrast'), token(sel, 'accent'))).toBeGreaterThanOrEqual(4.5);
  });

  it('keeps every accuracy band distinguishable from its ground (3:1 graphics)', () => {
    for (const band of ['acc-high', 'acc-moderate', 'acc-low', 'acc-unreliable']) {
      expect(
        ratio(token(sel, band), token(sel, 'bg-canvas')),
        `${band} on canvas`,
      ).toBeGreaterThanOrEqual(3);
    }
  });
});
