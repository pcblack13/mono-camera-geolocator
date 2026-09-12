/**
 * `lib/geo/gazetteer.ts` — the places this app can find WITHOUT the internet.
 *
 * ★ OFFLINE FIRST (owner ask 2026-09-10: "type the city or country he wants to
 *   search or go to, or put the coordinates"). The globe ships Natural Earth's
 *   public-domain countries, provinces, major cities and continent/region label
 *   points under `/geo/*.geojson` — the same files the globe draws — so a search
 *   for "Beirut", "Lebanon", "Western Asia" or "Asia" answers from disk. Anything
 *   finer (a village, a street) goes to the server's geocoder when it is online.
 *   Coordinates typed in any common form ("34.10, 36.01", "34°06'N 36°01'E") are
 *   parsed here, never geocoded.
 */

import { parseLocation } from './parseLocation';
import type { LatLon } from '../../types/geo';

export type PlaceKind = 'continent' | 'region' | 'country' | 'province' | 'city' | 'coordinates' | 'online';

export interface Place {
  kind: PlaceKind;
  name: string;
  /** The country (a city or province), or the continent (a country). */
  context: string | null;
  lat: number;
  lon: number;
  /** The zoom that frames a place of this kind. */
  zoom: number;
  /** Population, for ranking cities. */
  pop: number;
}

interface Fc {
  features: { properties: Record<string, unknown>; geometry: { type: string; coordinates: unknown } }[];
}

const num = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) ? v : 0);
const str = (v: unknown): string => (typeof v === 'string' ? v : '');

/** Zoom by kind — a continent fills the globe, a city fills the screen. */
export const ZOOM_FOR: Record<Exclude<PlaceKind, 'coordinates' | 'online'>, number> = {
  continent: 2.4,
  region: 3.4,
  country: 5,
  province: 6.5,
  city: 11,
};

/** A country's zoom from its population — India is not framed like Malta. */
function countryZoom(pop: number): number {
  if (pop > 100_000_000) return 3.6;
  if (pop > 20_000_000) return 4.4;
  if (pop > 2_000_000) return 5.4;
  return 6.5;
}

/** The four files → one flat list. Pure: takes the parsed JSON. */
export function buildGazetteer(files: {
  countries: Fc;
  regions: Fc;
  places: Fc;
  provinceLabels: Fc;
}): Place[] {
  const out: Place[] = [];
  for (const f of files.regions.features) {
    const [lon, lat] = f.geometry.coordinates as [number, number];
    const kind = str(f.properties.kind) === 'continent' ? 'continent' : 'region';
    out.push({ kind, name: str(f.properties.name), context: null, lat, lon, zoom: ZOOM_FOR[kind], pop: 0 });
  }
  for (const f of files.countries.features) {
    const p = f.properties;
    out.push({
      kind: 'country',
      name: str(p.name),
      context: str(p.continent) || null,
      lat: num(p.ly),
      lon: num(p.lx),
      zoom: countryZoom(num(p.pop)),
      pop: num(p.pop),
    });
  }
  for (const f of files.provinceLabels.features) {
    const [lon, lat] = f.geometry.coordinates as [number, number];
    out.push({ kind: 'province', name: str(f.properties.name), context: str(f.properties.country) || null, lat, lon, zoom: ZOOM_FOR.province, pop: 0 });
  }
  for (const f of files.places.features) {
    const [lon, lat] = f.geometry.coordinates as [number, number];
    const p = f.properties;
    out.push({
      kind: 'city',
      name: str(p.name),
      context: str(p.country) || null,
      lat,
      lon,
      zoom: num(p.pop) > 5_000_000 ? 10 : ZOOM_FOR.city,
      pop: num(p.pop),
    });
  }
  return out.filter((p) => p.name !== '');
}

/** Case- and accent-insensitive: "Sao Paulo" finds "São Paulo". */
export function fold(s: string): string {
  return s
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .trim();
}

const KIND_RANK: Record<PlaceKind, number> = {
  country: 0,
  continent: 1,
  region: 2,
  city: 3,
  province: 4,
  coordinates: 5,
  online: 6,
};

/**
 * The best matches for what was typed. Prefix matches first (what you are
 * still typing), then substrings; within a tier countries before cities, and
 * bigger cities before smaller ones.
 */
export function searchPlaces(gazetteer: readonly Place[], query: string, limit = 8): Place[] {
  const q = fold(query);
  if (q.length < 2) return [];
  const scored: { place: Place; score: number }[] = [];
  for (const place of gazetteer) {
    const name = fold(place.name);
    let score: number;
    if (name === q) score = 0;
    else if (name.startsWith(q)) score = 1;
    else if (name.includes(q)) score = 2;
    else continue;
    scored.push({ place, score });
  }
  scored.sort(
    (a, b) =>
      a.score - b.score ||
      KIND_RANK[a.place.kind] - KIND_RANK[b.place.kind] ||
      b.place.pop - a.place.pop ||
      a.place.name.localeCompare(b.place.name),
  );
  return scored.slice(0, limit).map((s) => s.place);
}

/** Typed coordinates → a place to go to, or null when the text is not a pair. */
export function coordinatesPlace(query: string): Place | null {
  const at: LatLon | null = parseLocation(query);
  if (at === null) return null;
  return {
    kind: 'coordinates',
    name: `${at.lat.toFixed(5)}, ${at.lon.toFixed(5)}`,
    context: null,
    lat: at.lat,
    lon: at.lon,
    zoom: 14,
    pop: 0,
  };
}

let loading: Promise<Place[]> | null = null;

/** The gazetteer, fetched once from the app's own static files. */
export function loadGazetteer(base = ''): Promise<Place[]> {
  if (loading === null) {
    const get = async (name: string): Promise<Fc> => {
      const res = await fetch(`${base}/geo/${name}.geojson`);
      if (!res.ok) throw new Error(`${name}: HTTP ${res.status}`);
      return (await res.json()) as Fc;
    };
    loading = Promise.all([
      get('countries'),
      get('regions'),
      get('places'),
      get('province-labels'),
    ])
      .then(([countries, regions, places, provinceLabels]) =>
        buildGazetteer({ countries, regions, places, provinceLabels }),
      )
      .catch((err: unknown) => {
        loading = null; // a failed load may be retried on the next search
        throw err;
      });
  }
  return loading;
}
