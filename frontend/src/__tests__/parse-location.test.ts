/**
 * `parseLocation` — the "go to location" box's coordinate reader.
 *
 * ★ The dangerous failure here is not rejecting a valid coordinate; it is ACCEPTING
 *   a wrong one and flying the surveyor somewhere plausible-looking. So the tests
 *   pin both directions: every shape people actually paste, and the shapes that
 *   must return null rather than a guess.
 */

import { describe, expect, it } from 'vitest';

import { parseCoordinateValue, parseLocation } from '../lib/geo/parseLocation';

describe('parseLocation — accepted shapes', () => {
  it('reads decimal degrees, comma or space separated', () => {
    expect(parseLocation('34.1067, 36.0172')).toEqual({ lat: 34.1067, lon: 36.0172 });
    expect(parseLocation('34.1067 36.0172')).toEqual({ lat: 34.1067, lon: 36.0172 });
    expect(parseLocation('  34.1067,36.0172 ')).toEqual({ lat: 34.1067, lon: 36.0172 });
  });

  it('reads negative (southern / western) coordinates', () => {
    expect(parseLocation('-33.8688, 151.2093')).toEqual({ lat: -33.8688, lon: 151.2093 });
  });

  it('applies hemisphere letters', () => {
    const p = parseLocation('34.1067N 36.0172E');
    expect(p?.lat).toBeCloseTo(34.1067, 6);
    expect(p?.lon).toBeCloseTo(36.0172, 6);
    const s = parseLocation('33.8688S 151.2093W');
    expect(s?.lat).toBeCloseTo(-33.8688, 6);
    expect(s?.lon).toBeCloseTo(-151.2093, 6);
  });

  it('★ respects hemisphere ORDER — a longitude-first paste is not read as a latitude', () => {
    const p = parseLocation('36.0172E, 34.1067N');
    expect(p?.lat).toBeCloseTo(34.1067, 6);
    expect(p?.lon).toBeCloseTo(36.0172, 6);
  });

  it('reads degrees/minutes/seconds', () => {
    const p = parseLocation('34°06\'24.1"N 36°01\'02"E');
    expect(p?.lat).toBeCloseTo(34.10669, 4);
    expect(p?.lon).toBeCloseTo(36.01722, 4);
  });
});

describe('parseLocation — refused, never guessed', () => {
  it('returns null for a place NAME', () => {
    expect(parseLocation('Canal survey')).toBeNull();
    expect(parseLocation('Beirut')).toBeNull();
  });

  it('returns null for out-of-range values rather than clamping', () => {
    expect(parseLocation('95, 36')).toBeNull();
    expect(parseLocation('34, 200')).toBeNull();
  });

  it('returns null for anything that is not a pair', () => {
    expect(parseLocation('34.1067')).toBeNull();
    expect(parseLocation('34.1067, 36.0172, 12')).toBeNull();
    expect(parseLocation('')).toBeNull();
    expect(parseLocation('   ')).toBeNull();
  });
});

describe('parseCoordinateValue — one axis, one box', () => {
  it('reads decimal and DMS for each axis', () => {
    expect(parseCoordinateValue('34.1067', 'lat')).toBeCloseTo(34.1067, 6);
    expect(parseCoordinateValue('36.0172', 'lon')).toBeCloseTo(36.0172, 6);
    expect(parseCoordinateValue('34°06\'24.1"N', 'lat')).toBeCloseTo(34.10669, 4);
  });

  it('applies the hemisphere letter of its own axis', () => {
    expect(parseCoordinateValue('33.8688S', 'lat')).toBeCloseTo(-33.8688, 6);
    expect(parseCoordinateValue('151.2093W', 'lon')).toBeCloseTo(-151.2093, 6);
  });

  it('★ refuses a hemisphere from the WRONG axis — the boxes were swapped', () => {
    expect(parseCoordinateValue('36.0172E', 'lat')).toBeNull();
    expect(parseCoordinateValue('34.1067N', 'lon')).toBeNull();
  });

  it('enforces each axis range instead of clamping', () => {
    expect(parseCoordinateValue('95', 'lat')).toBeNull();
    expect(parseCoordinateValue('95', 'lon')).toBeCloseTo(95, 6);
    expect(parseCoordinateValue('200', 'lon')).toBeNull();
  });

  it('returns null for names and blanks', () => {
    expect(parseCoordinateValue('Canal survey', 'lat')).toBeNull();
    expect(parseCoordinateValue('', 'lon')).toBeNull();
  });
});
