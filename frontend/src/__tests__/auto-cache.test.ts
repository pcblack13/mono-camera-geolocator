/**
 * Automatic viewport caching — store semantics and chip label derivation.
 *
 * ★ The backend owns queueing/limits (tested there); the frontend's job is the toggle,
 *   the online flag, and honest label text. The map-zoom→provider-zoom conversion the
 *   reporter performs is the same `zoomShift` pinned by `offline-area.test.ts`.
 */

import { beforeEach, describe, expect, it } from 'vitest';

import type { AutoCacheStatus } from '../api/offline';
import { autoCacheLabel } from '../components/map/AutoCacheStatusChip';
import { useAutoCacheStore } from '../store/autoCacheStore';

function status(overrides: Partial<AutoCacheStatus> = {}): AutoCacheStatus {
  return {
    enabled: true,
    online: true,
    active: false,
    provider: 'mapbox_satellite',
    kind: 'satellite',
    zoom: 18,
    viewport_tiles: 120,
    cached_tiles: 112,
    missing_tiles: 8,
    coverage_percent: 93.3,
    queued_tiles: 0,
    truncated: false,
    note: null,
    session: {
      started_at: '2026-08-07T00:00:00Z',
      project_id: null,
      tiles_requested: 100,
      tiles_downloaded: 90,
      tiles_skipped_cached: 5,
      tiles_no_imagery: 3,
      tiles_failed: 2,
      bytes_downloaded: 1024,
      limit_reached: null,
    },
    ...overrides,
  };
}

describe('autoCacheLabel', () => {
  it('offline beats everything — cached imagery still serves', () => {
    expect(autoCacheLabel(true, false, status({ queued_tiles: 40 }))).toBe(
      'Offline — cached imagery',
    );
  });

  it('toggle-off is stated even with a stale status present', () => {
    expect(autoCacheLabel(false, true, status())).toBe('Auto-cache off');
  });

  it('a live download shows the remaining count', () => {
    expect(autoCacheLabel(true, true, status({ queued_tiles: 38 }))).toBe('Caching… 38 left');
  });

  it('settled viewports show coverage, full coverage reads as done', () => {
    expect(autoCacheLabel(true, true, status({ coverage_percent: 93.3 }))).toBe('93% cached');
    expect(autoCacheLabel(true, true, status({ coverage_percent: 100 }))).toBe('Area cached');
  });

  it('no report yet is honest about not knowing coverage', () => {
    expect(autoCacheLabel(true, true, null)).toBe('Auto-cache on');
    expect(autoCacheLabel(true, true, status({ coverage_percent: null }))).toBe('Auto-cache on');
  });
});

describe('useAutoCacheStore', () => {
  beforeEach(() => {
    useAutoCacheStore.setState({ enabled: true, status: null, online: true });
  });

  it('defaults: enabled, online, no status', () => {
    const s = useAutoCacheStore.getState();
    expect(s.enabled).toBe(true);
    expect(s.online).toBe(true);
    expect(s.status).toBeNull();
  });

  it('toggle and status round-trip', () => {
    useAutoCacheStore.getState().setEnabled(false);
    expect(useAutoCacheStore.getState().enabled).toBe(false);
    const st = status();
    useAutoCacheStore.getState().setStatus(st);
    expect(useAutoCacheStore.getState().status).toEqual(st);
  });

  it('offline/online transitions flip only the online flag', () => {
    useAutoCacheStore.getState().setStatus(status());
    useAutoCacheStore.getState().setOnline(false);
    const s = useAutoCacheStore.getState();
    expect(s.online).toBe(false);
    expect(s.enabled).toBe(true); // the user's preference survives an outage
    expect(s.status).not.toBeNull(); // last known coverage still shown
  });

  it('persists only the preference, not live status', () => {
    // partialize keeps `enabled` out of `status`/`online` — assert the shape directly.
    const persisted = JSON.parse(window.localStorage.getItem('le-auto-cache') ?? '{}');
    expect(Object.keys(persisted.state ?? {})).toEqual(['enabled']);
  });
});
