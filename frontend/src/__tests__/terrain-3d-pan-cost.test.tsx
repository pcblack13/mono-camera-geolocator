/**
 * ★★ The 3D pane must not raycast the terrain on every mousemove — that is what stopped
 *    it panning.
 *
 * `groundMetresPerPixel` calls `map.unproject()` twice. On a flat map that is an inverse
 * matrix multiply. With terrain enabled it is a GPU framebuffer readback (`gl.readPixels`)
 * to raycast the terrain mesh, which stalls the render pipeline. `mousemove` fires at
 * pointer-polling rate, so doing this per event starves the drag of frames and the map sits
 * frozen under a "grab" cursor.
 *
 * These tests assert the two guards that fix it, at the level where the bug actually lived:
 * how many times `unproject` is reached, not whether a helper returns the right number.
 */

import { render, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { asUuid } from '../types/common';

type Listener = (event: unknown) => void;

const unproject = vi.fn(() => ({ lat: 34.11, lng: 36.03, distanceTo: () => 7.9 }));
/** Every `map.on(...)` registration, so a test can fire MapLibre events by name. */
let listeners: Record<string, Listener[]> = {};

function fire(event: string, payload?: unknown): void {
  for (const fn of listeners[event] ?? []) fn(payload);
}

vi.mock('maplibre-gl', () => {
  class FakePoint {
    constructor(
      public x: number,
      public y: number,
    ) {}
  }
  class FakeMap {
    on = (event: string, fn: Listener): void => {
      (listeners[event] ??= []).push(fn);
    };
    unproject = unproject;
    addControl = (): void => {};
    addSource = (): void => {};
    addLayer = (): void => {};
    setTerrain = (): void => {};
    getSource = (): undefined => undefined;
    getCanvas = (): HTMLCanvasElement => document.createElement('canvas');
    getCenter = (): { lat: number; lng: number } => ({ lat: 34.11, lng: 36.03 });
    getZoom = (): number => 14;
    getPitch = (): number => 60;
    getBearing = (): number => 0;
    isStyleLoaded = (): boolean => false;
    once = (): void => {};
    isMoving = (): boolean => false;
    getLayer = (): undefined => undefined;
    queryRenderedFeatures = (): unknown[] => [];
    resize = (): void => {};
    remove = (): void => {};
  }
  const mod = {
    Map: FakeMap,
    NavigationControl: class {},
    Point: FakePoint,
    GeoJSONSource: class {},
  };
  return { __esModule: true, default: mod, ...mod };
});

vi.mock('maplibre-gl/dist/maplibre-gl.css', () => ({}));

const VIEW = { center: { lat: 34.11, lon: 36.03 }, zoom: 14, bounds: null };
const MOVE = { lngLat: { lat: 34.11, lng: 36.03 }, point: { x: 10, y: 10 } };

async function mount(): Promise<void> {
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
      onCursorMove={() => {}}
      onGroundScale={() => {}}
    />,
  );
  await waitFor(() => expect(listeners['mousemove']?.length).toBeGreaterThan(0));
}

/** Run the queued animation frame, which is where the coalesced readout work happens. */
async function nextFrame(): Promise<void> {
  await new Promise((resolve) => requestAnimationFrame(() => resolve(null)));
  await new Promise((resolve) => setTimeout(resolve, 0));
}

describe('Terrain3DMap pointer cost', () => {
  beforeEach(() => {
    listeners = {};
    unproject.mockClear();
  });

  it('★ does NO terrain raycast while the camera is moving — this is what unfroze the pan', async () => {
    await mount();

    fire('movestart');
    for (let i = 0; i < 60; i += 1) fire('mousemove', MOVE);
    await nextFrame();

    expect(
      unproject,
      'a drag must cost zero GPU readbacks; each one stalls the pipeline and the map ' +
        'stops responding to the drag that caused it',
    ).not.toHaveBeenCalled();
  });

  it('★ coalesces a burst of hover events into a single frame of work', async () => {
    await mount();

    for (let i = 0; i < 60; i += 1) fire('mousemove', MOVE);
    await nextFrame();

    // groundMetresPerPixel unprojects twice (here, and one pixel right) — so ONE
    // coalesced update is exactly 2 calls, not 120.
    expect(unproject.mock.calls.length).toBeLessThanOrEqual(2);
  });

  it('resumes reporting once the camera settles', async () => {
    await mount();

    fire('movestart');
    for (let i = 0; i < 10; i += 1) fire('mousemove', MOVE);
    await nextFrame();
    expect(unproject).not.toHaveBeenCalled();

    fire('moveend');
    fire('mousemove', MOVE);
    await nextFrame();
    expect(unproject).toHaveBeenCalled();
  });
});
