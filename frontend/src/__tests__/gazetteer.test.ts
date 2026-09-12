/** The offline place search behind the globe's search box (2026-09-10). */

import { describe, expect, it } from 'vitest';

import { buildGazetteer, coordinatesPlace, fold, searchPlaces } from '../lib/geo/gazetteer';

const pt = (lon: number, lat: number) => ({ type: 'Point', coordinates: [lon, lat] });
const G = buildGazetteer({
  regions: {
    features: [
      { properties: { name: 'Asia', kind: 'continent' }, geometry: pt(90, 35) },
      { properties: { name: 'Western Asia', kind: 'subregion' }, geometry: pt(40, 30) },
    ],
  },
  countries: {
    features: [
      { properties: { name: 'Lebanon', continent: 'Asia', pop: 6_800_000, lx: 35.9, ly: 33.9 }, geometry: pt(0, 0) },
      { properties: { name: 'India', continent: 'Asia', pop: 1_300_000_000, lx: 79, ly: 22 }, geometry: pt(0, 0) },
    ],
  },
  provinceLabels: {
    features: [{ properties: { name: 'Beqaa', country: 'Lebanon' }, geometry: pt(36.0, 33.9) }],
  },
  places: {
    features: [
      { properties: { name: 'Beirut', country: 'Lebanon', pop: 2_000_000 }, geometry: pt(35.5, 33.89) },
      { properties: { name: 'São Paulo', country: 'Brazil', pop: 20_000_000 }, geometry: pt(-46.6, -23.5) },
      { properties: { name: 'Bern', country: 'Switzerland', pop: 130_000 }, geometry: pt(7.4, 46.9) },
    ],
  },
});

describe('gazetteer', () => {
  it('folds accents and case', () => {
    expect(fold('São Paulo')).toBe('sao paulo');
  });

  it('★ prefix matches first, countries before cities, big cities before small', () => {
    const names = searchPlaces(G, 'be').map((p) => `${p.kind}:${p.name}`);
    expect(names.slice(0, 2)).toEqual(['city:Beirut', 'city:Bern']);
    expect(names).toContain('province:Beqaa');
    expect(searchPlaces(G, 'leb')[0]).toMatchObject({ kind: 'country', name: 'Lebanon', lat: 33.9, lon: 35.9 });
    expect(searchPlaces(G, 'sao pa')[0].name).toBe('São Paulo');
    expect(searchPlaces(G, 'asia')[0]).toMatchObject({ kind: 'continent', zoom: 2.4 });
    expect(searchPlaces(G, 'x')).toEqual([]);
  });

  it('a country is framed by its size; a megacity a little wider than a town', () => {
    expect(searchPlaces(G, 'india')[0].zoom).toBeLessThan(searchPlaces(G, 'lebanon')[0].zoom);
    expect(searchPlaces(G, 'são')[0].zoom).toBe(10);
    expect(searchPlaces(G, 'bern')[0].zoom).toBe(11);
  });

  it('★ typed coordinates are a destination, never a geocode', () => {
    expect(coordinatesPlace('34.104413, 36.015914')).toMatchObject({ kind: 'coordinates', lat: 34.104413, lon: 36.015914, zoom: 14 });
    expect(coordinatesPlace('Beirut')).toBeNull();
  });
});
