/**
 * ★ The 3D pane's zoom control must live where the chrome layer leaves room.
 *
 * `MapPanel` renders a full-bleed overlay at `zIndex: 1000` whose top row is deliberately
 * RIGHT-aligned, with the comment "so Leaflet's own zoom control keeps the top-left
 * corner". That cluster sets `pointerEvents: 'auto'`, so anything the map itself puts in
 * the top-right corner is both painted under it and unclickable.
 *
 * The 2D pane obeys this (Leaflet's default zoom control is top-left). The 3D pane put its
 * `NavigationControl` top-right, so the zoom buttons were invisible AND dead — which
 * presents to the user as "3D will not zoom", with nothing in the console to explain it.
 *
 * This is exactly the class of bug a render test catches and a unit test cannot: the
 * defect is a COLLISION between two components that are each individually correct.
 */

import { render, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { asUuid } from '../types/common';

/** Records every `addControl` call so the assertion can inspect the position argument. */
const addControl = vi.fn();
const on = vi.fn();
const addSource = vi.fn();
const setTerrain = vi.fn();

class FakeNavigationControl {
  constructor(public options: unknown) {}
}

vi.mock('maplibre-gl', () => {
  class FakeMap {
    addControl = addControl;
    on = on;
    addSource = addSource;
    setTerrain = setTerrain;
    getSource = (): undefined => undefined;
    getLayer = (): undefined => undefined;
    getCanvas = (): HTMLCanvasElement => document.createElement('canvas');
    isStyleLoaded = (): boolean => false;
    once = (): void => {};
    isMoving = (): boolean => false;
    getCenter = (): { lat: number; lng: number } => ({ lat: 34.11, lng: 36.03 });
    getZoom = (): number => 14;
    getPitch = (): number => 60;
    getBearing = (): number => 0;
    queryRenderedFeatures = (): unknown[] => [];
    resize = (): void => {};
    remove = (): void => {};
    addLayer = (): void => {};
  }
  const mod = {
    Map: FakeMap,
    NavigationControl: FakeNavigationControl,
    GeoJSONSource: class {},
  };
  return { __esModule: true, default: mod, ...mod };
});

vi.mock('maplibre-gl/dist/maplibre-gl.css', () => ({}));

const VIEW = { center: { lat: 34.11, lon: 36.03 }, zoom: 14, bounds: null };

describe('Terrain3DMap control placement', () => {
  beforeEach(() => {
    addControl.mockClear();
  });

  it("★ puts the zoom control top-LEFT, clear of MapPanel's right-aligned chrome", async () => {
    const { Terrain3DMap } = await import('../components/map/Terrain3DMap');

    render(
      <Terrain3DMap
        projectId={asUuid('11111111-1111-1111-1111-111111111111')}
        hasProjectDem={false}
        providerId="esri_world_imagery"
        basemap="satellite"
        initialView={VIEW}
        exaggeration={1}
        maxZoom={19}
        gcps={[]}
        draft={null}
      />,
    );

    await waitFor(() => expect(addControl).toHaveBeenCalled());

    const navCall = addControl.mock.calls.find(
      ([control]) => control instanceof FakeNavigationControl,
    );
    expect(navCall, 'a NavigationControl must be added at all').toBeTruthy();
    expect(
      navCall?.[1],
      "top-right sits under MapPanel's chrome cluster (zIndex 1000, pointerEvents auto), " +
        'so the zoom buttons render hidden and swallow no clicks — the user sees a 3D map ' +
        'that will not zoom',
    ).toBe('top-left');
  });
});
