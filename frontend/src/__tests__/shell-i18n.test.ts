/**
 * Every literal the shell hands to `t()` has an Arabic sentence.
 *
 * ★ The translation degrades to English silently — which is the right behaviour
 *   for a surveyor, and the wrong one for a reviewer: nobody notices the gap. This
 *   scan makes the gap loud, for the chrome every page shares.
 */

import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';

import { AR } from '../i18n/ar';

const ROOT = resolve(__dirname, '../components/shell');
const LITERAL = /\bt\(\s*'((?:[^'\\]|\\.)*)'\s*[,)]/g;

function* walk(dir: string): Generator<string> {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) yield* walk(p);
    else if (/\.tsx?$/.test(name)) yield p;
  }
}

describe('the shell speaks Arabic', () => {
  it('has an Arabic entry for every t() literal under components/shell', () => {
    const missing: string[] = [];
    for (const file of walk(ROOT)) {
      const src = readFileSync(file, 'utf8');
      for (const m of src.matchAll(LITERAL)) {
        const key = m[1].replace(/\\'/g, "'");
        if (!(key in AR)) missing.push(`${file.slice(ROOT.length + 1)}: ${key}`);
      }
    }
    expect(missing, missing.join('\n')).toEqual([]);
  });
});
