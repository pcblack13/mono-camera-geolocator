/**
 * `theme/styleCache.ts` — the two emotion caches the app can style through.
 *
 * ★ WHY TWO. Arabic mirrors the chrome (2026-08-31, owner decision), and MUI's
 *   way of mirroring is not per-component — it is a stylis plugin that flips every
 *   physical property (`margin-left` ⇄ `margin-right`, `left` ⇄ `right`) at the
 *   moment the CSS is serialized. That flip lives in the CACHE, so the direction
 *   choice is which cache the tree renders under: `rtlCache` for Arabic,
 *   `ltrCache` for English — and `ltrCache` again INSIDE an `LtrIsland`, which is
 *   how a geometry surface (Konva stage, Leaflet/MapLibre map) un-flips its own
 *   styles while sitting in a mirrored page.
 *
 * ★ Module-level constants, never rebuilt: a fresh cache per render would re-insert
 *   every rule and thrash the CSSOM. The keys differ so the two caches' <style>
 *   tags can coexist without clobbering each other.
 */

import createCache from '@emotion/cache';
import { prefixer } from 'stylis';
import rtlPlugin from 'stylis-plugin-rtl';

export const ltrCache = createCache({ key: 'mui' });

/** ★ `prefixer` must be restated: passing `stylisPlugins` REPLACES emotion's
 *  defaults, and dropping the prefixer would silently unprefix every rule. */
export const rtlCache = createCache({
  key: 'mui-rtl',
  stylisPlugins: [prefixer, rtlPlugin],
});
