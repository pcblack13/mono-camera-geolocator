/**
 * Imagery providers and the tile proxy — endpoints 50–53 (§7).
 *
 * ★★ L2 — THE DEFAULT PROVIDER IS KEYLESS. `docker compose up` with an empty `.env`
 *    yields a working satellite search via `esri_world_imagery`. Nothing in this
 *    module hard-codes it: the default arrives on `ProviderInfo.is_default` and on
 *    `CapabilitiesResponse.defaults.provider`, because **the backend is the single
 *    source of truth for provider config**. `VITE_MAP_TILE_URL` and
 *    `VITE_MAP_ATTRIBUTION` were DELETED (§9.11) precisely so the bundle cannot
 *    disagree with the server about whose ToS applies.
 *
 * ★★ THE TILE URL IS THE SERVER'S TO CHOOSE. Use `ProviderInfo.tile_url_template` —
 *    do not build one. By default it is the proxy path for EVERY provider, keyed or
 *    keyless (§7.2); `LE_IMAGERY_DIRECT_TILE_URLS=true` makes keyless providers
 *    return their upstream URL instead. {@link providersApi.tileUrlTemplate} exists
 *    for the `local_orthophoto`/`fixture` case where the server's template is the
 *    only possible answer, and it returns the proxy path — never an upstream one.
 */

import type { Page } from '../types/common';
import type { BasemapKind, GeocodeResult, ProviderId, ProviderInfo } from '../types/geo';
import { buildUrl, fetchJson, toQuery } from './client';

/**
 * `ProviderListParams` (§6.2, endpoint 50).
 *
 * ★ DECLARED HERE — IU-23 owns `types/**` and declared no provider list filter.
 *   Belongs in `types/geo.ts`; flagged for IU-23.
 */
export interface ProviderFilters {
  configured?: boolean;
  kind?: BasemapKind;
  supports_offline?: boolean;
  limit?: number;
  offset?: number;
}

/** `TileParams` (§6.2, endpoint 52). */
export interface TileParams {
  kind?: BasemapKind;
  /** Retina/@2x where the provider supports it. */
  scale?: number;
}

/** `StaticImageParams` (§6.2, endpoint 53). */
export interface StaticImageParams {
  provider?: ProviderId;
  kind?: BasemapKind;
  /** `min_lon,min_lat,max_lon,max_lat` — EPSG:4326. */
  bbox: string;
  zoom?: number;
  width?: number;
  height?: number;
  format?: 'png' | 'jpeg' | 'geotiff';
}

export const providersApi = {
  /** Endpoint 50 — `GET /imagery/providers` → `200 Page[ProviderInfo]`. */
  list: (f: ProviderFilters = {}, signal?: AbortSignal): Promise<Page<ProviderInfo>> =>
    fetchJson<Page<ProviderInfo>>('/imagery/providers', { query: toQuery(f), signal }),

  /**
   * `GET /imagery/geocode` — resolve a typed place name to coordinates.
   *
   * ★ A server-side proxy (keeps the geocoder's User-Agent/rate-limit obligations on the
   *   backend). Returns `502 PROVIDER_UPSTREAM_ERROR` when offline or unreachable — the
   *   caller should fall back to typed lat/lon.
   */
  geocode: (q: string, limit?: number, signal?: AbortSignal): Promise<GeocodeResult[]> =>
    fetchJson<GeocodeResult[]>('/imagery/geocode', {
      query: toQuery({ q, ...(limit !== undefined ? { limit } : {}) }),
      signal,
    }),

  /**
   * Endpoint 51 — `GET /imagery/providers/{provider}` → `200 ProviderInfo`.
   *
   * ★ `health` is served from the **30 s cache**, never a live probe (§7.2.1(4)): an
   *   endpoint that does a network round trip per call is a DoS amplifier pointed at
   *   a provider whose rate limit we are contractually obliged to respect.
   */
  get: (provider: ProviderId, signal?: AbortSignal): Promise<ProviderInfo> =>
    fetchJson<ProviderInfo>(`/imagery/providers/${provider}`, { signal }),

  /**
   * Endpoint 52 — the proxy path, as a Leaflet URL template.
   *
   * ★ PREFER `ProviderInfo.tile_url_template`. This is the fallback for when there is
   *   no `ProviderInfo` in hand yet, and it always yields the PROXY path — which is
   *   the correct default for every provider (§7.2). Leaflet substitutes `{z}/{x}/{y}`.
   */
  tileUrlTemplate: (provider: ProviderId, params: TileParams = {}): string =>
    buildUrl(`/imagery/tiles/${provider}/{z}/{x}/{y}`, toQuery(params))
      // `buildUrl` percent-encodes nothing in the path, but URLSearchParams is only
      // applied to the query — the braces survive. Guard anyway: a Leaflet template
      // with encoded braces silently fetches a literal `%7Bz%7D` tile forever.
      .replace(/%7B/g, '{')
      .replace(/%7D/g, '}'),

  /**
   * Endpoint 53 — `GET /imagery/static` → binary. A URL, not a fetch.
   *
   * ★ Budget: `LE_MAX_STATIC_TILES=16`, `LE_MAX_STATIC_PIXELS=4194304` (4 MP)
   *   (§7.2.1(3)). Over budget is `422 STATIC_IMAGE_TOO_LARGE`, not a slow success —
   *   a 64 MP stitch is a job, not a GET.
   */
  staticImageUrl: (params: StaticImageParams): string =>
    buildUrl('/imagery/static', toQuery(params)),
};
