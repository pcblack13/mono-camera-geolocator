/**
 * Phase 2's gate: ZERO hard-coded colours in `src/components`.
 *
 * ★ WHY A TEST AND NOT A REVIEW RULE. A hex literal in a component is a fork of
 *   the design system — a colour the theme switch cannot reach and the token file
 *   does not know about. Twenty-eight of them existed when Phase 2 started, each
 *   individually reasonable, collectively drift. Review missed all of them;
 *   a grep never will.
 *
 * ★ WHERE COLOURS MAY LIVE: `src/theme/**` (tokens, palette, paint, dataColors,
 *   confidence) and nowhere else. A component that needs a colour imports a name
 *   that says what the colour is FOR — `ON_MEDIA`, not `'#fff'`.
 */

import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';

const ROOT = resolve(__dirname, '../components');

/** Hex colours: #rgb, #rrggbb, #rrggbbaa — as string literals or CSS values. */
const HEX = /#[0-9a-fA-F]{3,8}\b/g;

/** Lines where a hex is not a colour, or not ours to police. */
const EXEMPT_LINE = /(^\s*\/\/|^\s*\*|\bid=|\bhref=|encodeURI)/;

function* walk(dir: string): Generator<string> {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) yield* walk(p);
    else if (/\.(tsx|ts|css)$/.test(name)) yield p;
  }
}

describe('the design-system gate', () => {
  it('finds zero hard-coded colours in src/components', () => {
    const offenders: string[] = [];
    for (const file of walk(ROOT)) {
      const lines = readFileSync(file, 'utf8').split('\n');
      lines.forEach((line, i) => {
        if (EXEMPT_LINE.test(line)) return;
        const hits = line.match(HEX);
        if (hits)
          offenders.push(`${file.slice(ROOT.length + 1)}:${i + 1}  ${line.trim().slice(0, 80)}`);
      });
    }
    // ★ The failure message lists every offender — the fix is to move each to a
    //   named export in src/theme/paint.ts or dataColors.ts, never to widen this.
    expect(offenders, offenders.join('\n')).toEqual([]);
  });
});
