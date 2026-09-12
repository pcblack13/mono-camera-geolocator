/**
 * The globe's search box (2026-09-10): coordinates first, the offline gazetteer
 * next, the online geocoder last.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { PlaceSearch } from '../components/monitor/globe/PlaceSearch';
import { providersApi } from '../api/providers';
import { setLanguage } from '../i18n';

vi.mock('../api/providers', () => ({ providersApi: { geocode: vi.fn() } }));

const FILES: Record<string, unknown> = {
  countries: { features: [{ properties: { name: 'Lebanon', continent: 'Asia', pop: 6_800_000, lx: 35.9, ly: 33.9 }, geometry: { type: 'Point', coordinates: [0, 0] } }] },
  regions: { features: [] },
  places: { features: [{ properties: { name: 'Beirut', country: 'Lebanon', pop: 2_000_000 }, geometry: { type: 'Point', coordinates: [35.5, 33.89] } }] },
  'province-labels': { features: [] },
};

describe('PlaceSearch', () => {
  beforeEach(() => {
    setLanguage('en');
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        const name = /\/geo\/(.+)\.geojson$/.exec(String(url))?.[1] ?? '';
        return new Response(JSON.stringify(FILES[name] ?? { features: [] }), { status: 200 });
      }),
    );
    vi.mocked(providersApi.geocode).mockReset();
  });
  afterEach(() => vi.unstubAllGlobals());

  it('★ finds a city offline and goes there at a city zoom', async () => {
    const onGo = vi.fn();
    render(<PlaceSearch onGo={onGo} />);
    const box = screen.getByRole('combobox');
    fireEvent.change(box, { target: { value: 'bei' } });
    const option = await screen.findByText('Beirut');
    fireEvent.click(option);
    expect(onGo).toHaveBeenCalledWith(expect.objectContaining({ kind: 'city', name: 'Beirut', lat: 33.89, lon: 35.5, zoom: 11 }));
    expect(providersApi.geocode).not.toHaveBeenCalled();
  });

  it('★ typed coordinates are offered first, with no lookup at all', async () => {
    const onGo = vi.fn();
    render(<PlaceSearch onGo={onGo} />);
    const box = screen.getByRole('combobox');
    fireEvent.change(box, { target: { value: '34.104413, 36.015914' } });
    fireEvent.click(await screen.findByText('34.10441, 36.01591'));
    expect(onGo).toHaveBeenCalledWith(expect.objectContaining({ kind: 'coordinates', lat: 34.104413, lon: 36.015914 }));
    expect(providersApi.geocode).not.toHaveBeenCalled();
  });

  it('asks the server only when nothing local answers, and marks the answer as online', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(providersApi.geocode).mockResolvedValue([
      { display_name: 'Yammouneh, Baalbek', lat: 34.1, lon: 36.0, category: 'village', bbox: null },
    ]);
    const onGo = vi.fn();
    render(<PlaceSearch onGo={onGo} />);
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'yammouneh' } });
    await vi.advanceTimersByTimeAsync(600);
    await waitFor(() => expect(providersApi.geocode).toHaveBeenCalledWith('yammouneh', 6));
    fireEvent.click(await screen.findByText('Yammouneh, Baalbek'));
    expect(onGo).toHaveBeenCalledWith(expect.objectContaining({ kind: 'online', lat: 34.1, lon: 36.0 }));
    vi.useRealTimers();
  });
});
