/**
 * The token set — the two failures that would fork the design system silently.
 *
 * ★ 1. CSS AND MUI MUST AGREE. `tokens.css` styles plain CSS and the Konva/Leaflet
 *      overlays; `palette.ts` styles every MUI component. They declare the same
 *      surfaces, so a value changed in one and not the other produces a panel that
 *      is *almost* the right colour — the kind of drift nobody reports and everyone
 *      sees. This pins them together.
 * ★ 2. COLOUR MEANS ONE THING. The accuracy bands own green/amber/orange/red. If a
 *      lifecycle state ever claims one of those hues, a committed-but-unreliable
 *      point becomes green and red at once, and the app's central claim — that
 *      colour tells you how far to trust a coordinate — stops being true.
 */

import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { darkPalette, lightPalette } from '../theme/palette';
import { CONFIDENCE_COLORS } from '../theme/confidence';

const css = readFileSync(resolve(__dirname, '../theme/tokens.css'), 'utf8');

/** Read one custom property out of a given selector block. */
function token(selector: string, name: string): string {
  const block = new RegExp(`${selector}\\s*\\{([\\s\\S]*?)\\n\\}`).exec(css);
  if (!block) throw new Error(`no block for ${selector}`);
  const m = new RegExp(`--${name}:\\s*([^;]+);`).exec(block[1]);
  if (!m) throw new Error(`no --${name} in ${selector}`);
  return m[1].trim().toLowerCase();
}

describe('tokens.css and the MUI palette agree', () => {
  it('shares the dark surfaces', () => {
    expect(token(":root\\[data-theme='dark'\\]", 'bg-base')).toBe(
      String(darkPalette.background?.default).toLowerCase(),
    );
    expect(token(":root\\[data-theme='dark'\\]", 'bg-elevated')).toBe(
      String(darkPalette.background?.paper).toLowerCase(),
    );
    expect(token(":root\\[data-theme='dark'\\]", 'hairline')).toBe(
      String(darkPalette.divider).toLowerCase(),
    );
  });

  it('shares the light surfaces', () => {
    expect(token(":root\\[data-theme='light'\\]", 'bg-base')).toBe(
      String(lightPalette.background?.default).toLowerCase(),
    );
    expect(token(":root\\[data-theme='light'\\]", 'hairline')).toBe(
      String(lightPalette.divider).toLowerCase(),
    );
  });

  it('shares the one interactive accent', () => {
    // ★ ONE accent, not a palette of them: "interactive" must be unmistakable
    //   against imagery, and a second accent would make it a guess.
    const accent = token(":root\\[data-theme='dark'\\]", 'accent');
    expect(accent).toBe(String((darkPalette.primary as { main: string }).main).toLowerCase());
  });
});

describe('colour keeps one meaning', () => {
  it('reserves the accuracy hues for accuracy', () => {
    for (const band of ['high', 'moderate', 'low', 'unreliable'] as const) {
      expect(token(":root\\[data-theme='dark'\\]", `acc-${band}`)).toBe(
        CONFIDENCE_COLORS[band].dark.toLowerCase(),
      );
    }
  });

  it('gives the draft state a hue no accuracy band uses', () => {
    // ★ Violet is free precisely because no accuracy band claims it — which is why
    //   lifecycle got violet and NOT the brief's green/amber/red.
    const draft = token(":root\\[data-theme='dark'\\]", 'status-draft');
    const bands = Object.values(CONFIDENCE_COLORS).map((b) => b.dark.toLowerCase());
    expect(bands).not.toContain(draft);
  });

  it('never lets the accent collide with an accuracy band', () => {
    const accent = token(":root\\[data-theme='dark'\\]", 'accent');
    const bands = Object.values(CONFIDENCE_COLORS).map((b) => b.dark.toLowerCase());
    expect(bands).not.toContain(accent);
  });
});

describe('motion respects the machine', () => {
  it('collapses every duration under prefers-reduced-motion', () => {
    // Field laptops are not all fast, and vestibular disorders are not rare.
    const reduced = /@media \(prefers-reduced-motion: reduce\)\s*\{([\s\S]*?)\n\}/.exec(css);
    expect(reduced).not.toBeNull();
    for (const d of ['fast', 'normal', 'slow', 'fly']) {
      expect(reduced![1]).toContain(`--dur-${d}: 0ms;`);
    }
  });
});
