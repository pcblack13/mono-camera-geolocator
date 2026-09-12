/**
 * A Leaflet map that cannot be measured must not poison the shared view store.
 *
 * ★ THE REPORTED FAULT: create a project, place four GCPs, press Accuracy — and the
 *   editor was replaced by "This editor hit a problem — Invalid LatLng object:
 *   (NaN, NaN)".
 *
 * ★ THE CHAIN. Opening the accuracy tab hid the editor. Hiding it with `display: none`
 *   collapsed it to zero size; Leaflet re-measured to 0 × 0 and fired `moveend`, whose
 *   `getCenter()` is degenerate at that size. `MapViewSync` reported that centre into
 *   `mapStore` — shared by every map — and the next component to apply the stored view
 *   called `setView(NaN, NaN)`, which Leaflet throws on, inside a render effect.
 *
 * ★ Two fixes, both needed, tested at different levels:
 *   1. `WorkspacePage` no longer collapses the editor (stacked + `visibility`), so the
 *      degenerate measurement does not happen in the first place.
 *   2. THIS test pins the second one: `MapViewSync` refuses to move a non-finite view
 *      in EITHER direction. A transient unmeasurable map is normal; propagating it is
 *      what turned it into a crash, and the guard is what stops any future cause of a
 *      0 × 0 container from taking the editor down again.
 *
 * Leaflet cannot mount in jsdom, so `useMap` is mocked with a map whose measurements
 * are degenerate — which is precisely the condition under test.
 */

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/react';

const listeners: Record<string, () => void> = {};
const fakeMap = {
  getCenter: vi.fn(() => ({ lat: Number.NaN, lng: Number.NaN })),
  getZoom: vi.fn(() => Number.NaN),
  setView: vi.fn(),
  flyTo: vi.fn(),
  fitBounds: vi.fn(),
  on: vi.fn((event: string, handler: () => void) => {
    listeners[event] = handler;
  }),
  off: vi.fn(),
};

vi.mock('react-leaflet', () => ({ useMap: () => fakeMap }));

import { MapViewSync } from '../components/map/MapViewSync';
import type { MapViewState } from '../types/geo';

const GOOD_VIEW: MapViewState = {
  center: { lat: 33.8938, lon: 35.5018 },
  zoom: 16,
  bounds: null,
};

describe('MapViewSync with an unmeasurable map', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fakeMap.getCenter.mockReturnValue({ lat: Number.NaN, lng: Number.NaN });
    fakeMap.getZoom.mockReturnValue(Number.NaN);
  });

  it('does not report a degenerate centre up into the shared store', () => {
    const onViewChange = vi.fn();
    render(
      <MapViewSync
        view={GOOD_VIEW}
        seq={1}
        lastOrigin="map"
        onViewChange={onViewChange}
        reducedMotion
      />,
    );

    // The resize that hiding an ancestor causes fires exactly this.
    listeners.moveend?.();
    listeners.zoomend?.();

    expect(onViewChange).not.toHaveBeenCalled();
  });

  it('still reports a real move once the map can be measured again', () => {
    const onViewChange = vi.fn();
    render(
      <MapViewSync
        view={GOOD_VIEW}
        seq={1}
        lastOrigin="map"
        onViewChange={onViewChange}
        reducedMotion
      />,
    );

    fakeMap.getCenter.mockReturnValue({ lat: 33.9, lng: 35.5 });
    fakeMap.getZoom.mockReturnValue(17);
    listeners.moveend?.();

    expect(onViewChange).toHaveBeenCalledWith(
      { center: { lat: 33.9, lon: 35.5 }, zoom: 17, bounds: null },
      'map',
    );
  });

  it('never hands Leaflet a non-finite view to apply', () => {
    render(
      <MapViewSync
        view={{ center: { lat: Number.NaN, lon: Number.NaN }, zoom: Number.NaN, bounds: null }}
        seq={7}
        lastOrigin="user"
        onViewChange={vi.fn()}
        reducedMotion
      />,
    );

    // This is the call that used to throw `Invalid LatLng object: (NaN, NaN)`.
    expect(fakeMap.setView).not.toHaveBeenCalled();
    expect(fakeMap.flyTo).not.toHaveBeenCalled();
  });

  it('never frames a non-finite box either — fitBounds throws the same way', () => {
    render(
      <MapViewSync
        view={{
          center: { lat: 33.8938, lon: 35.5018 },
          zoom: 16,
          bounds: {
            min_lat: Number.NaN,
            min_lon: Number.NaN,
            max_lat: Number.NaN,
            max_lon: Number.NaN,
          },
        }}
        seq={11}
        lastOrigin="user"
        onViewChange={vi.fn()}
        reducedMotion
      />,
    );
    expect(fakeMap.fitBounds).not.toHaveBeenCalled();
    // …and it falls back to the centre, which IS finite here, rather than doing nothing.
    expect(fakeMap.setView).toHaveBeenCalledWith([33.8938, 35.5018], 16, { animate: false });
  });

  it('applies a good view normally — the guard must not freeze the map', () => {
    render(
      <MapViewSync
        view={GOOD_VIEW}
        seq={9}
        lastOrigin="user"
        onViewChange={vi.fn()}
        reducedMotion
      />,
    );
    expect(fakeMap.setView).toHaveBeenCalledWith([33.8938, 35.5018], 16, { animate: false });
  });
});
