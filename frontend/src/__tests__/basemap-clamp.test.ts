/**
 * `clampBasemapToKinds` — the guard against an impossible (provider, kind) pair.
 *
 * ★ THE REPORTED FAULT THIS PINS: the basemap kind is persisted and survives provider
 *   changes, so a workspace last used on Esri Hybrid opened on satellite-only Mapbox
 *   with `?kind=hybrid` on every tile request — each one refused server-side
 *   (`TileOutOfRangeError`), the map a blank grid with markers floating on nothing,
 *   while the dashboard (which defaults to satellite) worked. The dashboard/workspace
 *   asymmetry is what made it look like a workspace bug; the pair was the bug.
 */

import { describe, expect, it } from 'vitest';

import { clampBasemapToKinds } from '../components/map/tileMath';
import type { BasemapKind } from '../types/geo';

describe('clampBasemapToKinds', () => {
  it('★ heals a persisted Esri-era hybrid onto satellite-only Mapbox', () => {
    expect(clampBasemapToKinds('hybrid', ['satellite'])).toBe('satellite');
    expect(clampBasemapToKinds('terrain', ['satellite'])).toBe('satellite');
  });

  it('keeps a kind the provider serves', () => {
    expect(clampBasemapToKinds('hybrid', ['satellite', 'hybrid'])).toBe('hybrid');
    expect(clampBasemapToKinds('satellite', ['satellite'])).toBe('satellite');
  });

  it('clamps to the provider FIRST (canonical) kind, not an arbitrary one', () => {
    expect(clampBasemapToKinds('terrain', ['satellite', 'hybrid'])).toBe('satellite');
  });

  it('claims nothing while capabilities are unknown or empty', () => {
    // Still loading (`undefined`) or a degenerate listing: clamping would be a guess.
    expect(clampBasemapToKinds('hybrid', undefined)).toBe('hybrid');
    expect(clampBasemapToKinds('hybrid', [] as BasemapKind[])).toBe('hybrid');
  });
});
