/**
 * The camera monitor's layout — the map beside the picture, the deck that follows.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';

import { BottomDeck } from '../components/monitor/camera/BottomDeck';
import { DriftSection } from '../components/drift/DriftSection';
import { setLanguage } from '../i18n';
import { useMonitorLayoutStore } from '../store/monitorLayoutStore';

vi.mock('../api/lut', () => ({
  lutApi: { library: async () => [{ site_name: 'MONODEMO', has_pose: true }] },
}));
vi.mock('../api/hooks/useDrift', () => {
  const idle = { mutate: vi.fn(), isPending: false, error: null };
  return {
    useDriftReferences: () => ({ data: [] }),
    useDriftMonitors: () => ({ data: [] }),
    useFreezeReference: () => idle,
    useDriftCheck: () => idle,
    useStartDriftMonitor: () => idle,
    useStopDriftMonitor: () => idle,
  };
});

describe('the monitor layout store', () => {
  beforeEach(() => useMonitorLayoutStore.getState().resetLayout());

  it('★ the map stands BESIDE the video by default — the video’s equal, half the row', () => {
    const s = useMonitorLayoutStore.getState();
    expect(s.mapBeside).toBe(true);
    expect(s.mapFraction).toBe(0.5);
    s.setMapFraction(0.05);
    expect(useMonitorLayoutStore.getState().mapFraction).toBe(0.25);
    s.setMapFraction(0.99);
    expect(useMonitorLayoutStore.getState().mapFraction).toBe(0.75);
    s.setMapFraction(Number.NaN);
    expect(useMonitorLayoutStore.getState().mapFraction).toBe(0.5);
    s.setMapBeside(false);
    expect(useMonitorLayoutStore.getState().mapBeside).toBe(false);
  });

  it('rehydrates a persisted layout that predates the side map with the defaults', () => {
    localStorage.setItem(
      'le.monitorLayout.v1',
      JSON.stringify({ state: { inspectorPx: 400, deckTab: 'events' }, version: 1 }),
    );
    void useMonitorLayoutStore.persist.rehydrate();
    const s = useMonitorLayoutStore.getState();
    expect(s.mapBeside).toBe(true);
    expect(s.mapFraction).toBe(0.5);
    expect(s.inspectorPx).toBe(400);
    expect(s.deckTab).toBe('events');
    localStorage.removeItem('le.monitorLayout.v1');
  });
});

describe('the bottom deck', () => {
  beforeEach(() => {
    setLanguage('en');
    useMonitorLayoutStore.getState().resetLayout();
  });

  it('★ loses its Map tab while the map sits beside the video — and never shows a blank pane', () => {
    // The remembered tab is the map; the deck no longer offers it.
    useMonitorLayoutStore.getState().setDeckTab('map');
    render(
      <BottomDeck resizable counts={{ detections: 3, events: 1 }} tabs={['detections', 'events']}>
        {(tab) => <div data-testid="pane">{tab}</div>}
      </BottomDeck>,
    );
    expect(screen.queryByRole('tab', { name: 'Map' })).toBeNull();
    expect(screen.getByRole('tab', { name: 'Detections · 3' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(screen.getByTestId('pane')).toHaveTextContent('detections');
  });

  it('offers all three tabs, and the actions slot, when the map is docked below', () => {
    render(
      <BottomDeck
        resizable
        counts={{ detections: 0, events: 0 }}
        actions={<button type="button">beside</button>}
      >
        {(tab) => <div>{tab}</div>}
      </BottomDeck>,
    );
    expect(screen.getByRole('tab', { name: 'Map' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: 'Detections' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'beside' })).toBeTruthy();
  });
});

describe('the drift section (the Drift tool page; the monitor inspector only reads the camera’s watch)', () => {
  it('★ stacks into a column and still offers the freeze on the CHOSEN table', async () => {
    setLanguage('en');
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <DriftSection source="http://cam/stream" lutSite="MONODEMO" live layout="stack" />
      </QueryClientProvider>,
    );
    const freeze = await screen.findByRole('button', { name: /Freeze reference/ });
    expect(freeze).toBeEnabled();
    expect(screen.getByRole('spinbutton', { name: 'alert above (m)' })).toBeTruthy();
    // no "apply a lookup table" plea — the table was chosen in ③
    expect(screen.queryByText(/Apply a lookup table above/)).toBeNull();
  });
});
