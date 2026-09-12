/**
 * `offerableProviders` — which imagery providers the map selector lists.
 *
 * ★ The menu is about IMAGERY, not about deployment. Entries that cannot draw a
 *   tile on this machine are hidden rather than greyed out, and two entries are
 *   never offered at all: test fixtures and the superseded Google Static endpoint.
 *   The active choice otherwise survives the filter — a select whose value is
 *   missing from its own options renders blank.
 *
 * ★★ ESRI IS NO LONGER UI-BANNED (1.2.6). It was on the never-offered list while
 *    it was retired in favour of Mapbox, as a belt-and-braces guard on top of the
 *    server's `LE_ALLOWED_PROVIDERS`. When Esri came back as a first-class option
 *    the ban stayed, and the switcher broke in two visible ways: choosing Esri left
 *    the dropdown BLANK (the active value had no matching item), and Esri never
 *    appeared in the menu to switch back to.
 *
 *    The duplicate rule is gone rather than made conditional. `LE_ALLOWED_PROVIDERS`
 *    is now the single source of truth for who may be offered, and the tests below
 *    pin that: Esri appears when the server allows it, and disappears — like any
 *    other provider — when the operator bans it.
 */

import { describe, expect, it } from 'vitest';

import { offerableProviders } from '../components/map/BasemapSwitcher';
import type { ProviderId, ProviderInfo } from '../types/geo';

const provider = (name: string, configured: boolean, allowed?: boolean): ProviderInfo =>
  ({
    name,
    title: name,
    configured,
    allowed,
    is_default: name === 'mapbox_satellite',
  }) as ProviderInfo;

const ALL: ProviderInfo[] = [
  provider('esri_world_imagery', true),
  provider('local_orthophoto', false),
  provider('fixture', true),
  provider('mapbox_satellite', true),
  provider('bing_aerial', false),
  provider('sentinel_copernicus', false),
  provider('google_maps_static', true),
  provider('google_map_tiles', true),
];

const names = (list: ProviderInfo[]): string[] => list.map((p) => p.name);

describe('offerableProviders', () => {
  it('★ offers only what can actually draw here — no "needs a key" clutter', () => {
    expect(names(offerableProviders(ALL, 'mapbox_satellite' as ProviderId))).toEqual([
      'esri_world_imagery',
      'mapbox_satellite',
      'google_map_tiles',
    ]);
  });

  it('★ OFFERS Esri when the server allows it — the UI ban is gone (1.2.6)', () => {
    // Keyless, so it always reports configured. It must appear in the menu whether
    // or not it is the active choice — otherwise it cannot be switched TO, and
    // selecting it elsewhere leaves the dropdown with a value it cannot render.
    expect(names(offerableProviders(ALL, 'mapbox_satellite' as ProviderId))).toContain(
      'esri_world_imagery',
    );
    expect(names(offerableProviders(ALL, 'esri_world_imagery' as ProviderId))).toContain(
      'esri_world_imagery',
    );
  });

  it('★ hides Esri when the OPERATOR bans it — the server is the only authority', () => {
    // The replacement for the old unconditional ban: one rule, applied to Esri
    // exactly as to every other provider.
    const esriBanned = ALL.map((p) =>
      p.name === 'esri_world_imagery' ? provider(p.name, true, false) : p,
    );
    expect(names(offerableProviders(esriBanned, 'mapbox_satellite' as ProviderId))).not.toContain(
      'esri_world_imagery',
    );
  });

  it('never offers test fixtures or the superseded Google Static endpoint', () => {
    const offered = names(offerableProviders(ALL, 'mapbox_satellite' as ProviderId));
    expect(offered).not.toContain('fixture');
    expect(offered).not.toContain('google_maps_static');
  });

  it('keeps the ACTIVE provider even when it is unconfigured', () => {
    // Otherwise the select would render blank on a machine whose configured
    // provider was later disabled — hiding the very fact worth showing.
    const offered = names(offerableProviders(ALL, 'sentinel_copernicus' as ProviderId));
    expect(offered).toContain('sentinel_copernicus');
  });

  it('reveals a provider as soon as it is configured', () => {
    const withSentinel = ALL.map((p) =>
      p.name === 'sentinel_copernicus' ? provider(p.name, true) : p,
    );
    expect(names(offerableProviders(withSentinel, 'mapbox_satellite' as ProviderId))).toContain(
      'sentinel_copernicus',
    );
  });

  it('★ hides a provider the operator banned via LE_ALLOWED_PROVIDERS', () => {
    const googleBanned = ALL.map((p) =>
      p.name === 'google_map_tiles' ? provider(p.name, true, false) : p,
    );
    expect(names(offerableProviders(googleBanned, 'mapbox_satellite' as ProviderId))).toEqual([
      'esri_world_imagery',
      'mapbox_satellite',
    ]);
  });

  it('treats a missing `allowed` field as allowed — older servers omit it', () => {
    // `provider()` leaves `allowed` undefined for every entry; google_map_tiles
    // (configured, undefined allowed) must pass the filter.
    const offered = names(offerableProviders(ALL, 'mapbox_satellite' as ProviderId));
    expect(offered).toContain('google_map_tiles');
  });

  it('keeps the ACTIVE provider even when it was banned after being chosen', () => {
    const googleBanned = ALL.map((p) =>
      p.name === 'google_map_tiles' ? provider(p.name, true, false) : p,
    );
    expect(names(offerableProviders(googleBanned, 'google_map_tiles' as ProviderId))).toContain(
      'google_map_tiles',
    );
  });
});
