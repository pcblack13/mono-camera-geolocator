/**
 * Imagery providers — endpoints 50–51.
 *
 * ★★ L2 — THE DEFAULT PROVIDER IS KEYLESS, and nothing here hard-codes which one it
 *    is. {@link useDefaultProvider} reads `is_default` off the server's answer, so a
 *    zero-config machine gets `esri_world_imagery` because the SERVER said so — the
 *    same reason `VITE_MAP_TILE_URL` was deleted (§9.11): the bundle must never
 *    disagree with the server about whose ToS applies.
 */

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import type { Page } from '../../types/common';
import type { ProviderId, ProviderInfo } from '../../types/geo';
import { providersApi, type ProviderFilters } from '../providers';
import { qk } from '../queryKeys';

/**
 * Endpoint 50 — `GET /imagery/providers`.
 *
 * ★ `staleTime: 5 min`. Provider config is static, but `health` is served from the
 *   server's 30 s cache and a provider that went down should surface within a few
 *   minutes without the operator reloading. Not `Infinity` for that reason, and not
 *   short — endpoint 51 explicitly refuses to be a per-call network probe (§7.2.1(4)),
 *   and hammering the list would defeat the same rate-limit courtesy from the client
 *   side.
 */
export function useProviders(f: ProviderFilters = {}): UseQueryResult<Page<ProviderInfo>> {
  return useQuery({
    queryKey: qk.providersFiltered(f),
    queryFn: ({ signal }) => providersApi.list(f, signal),
    staleTime: 5 * 60_000,
  });
}

/** Endpoint 51 — one provider, health from the 30 s cache. */
export function useProvider(provider: ProviderId | null): UseQueryResult<ProviderInfo> {
  return useQuery({
    queryKey: qk.providerDetail(provider!),
    queryFn: ({ signal }) => providersApi.get(provider!, signal),
    enabled: provider !== null,
    staleTime: 5 * 60_000,
  });
}

/**
 * ★ The server's default provider (L2). `undefined` until the list loads.
 *
 * ★ Prefer `CapabilitiesResponse.defaults.provider` when capabilities is already
 *   mounted — it is the same answer from a cheaper, `Infinity`-cached query. This hook
 *   exists for the map, which needs the full `ProviderInfo` (attribution, zoom range,
 *   `tile_url_template`) anyway.
 */
export function useDefaultProvider(): ProviderInfo | undefined {
  const { data } = useProviders();
  return data?.items.find((p) => p.is_default);
}

/**
 * Providers a `BasemapSwitcher` may actually offer.
 *
 * ★ `configured: false` for a PROVIDER genuinely means "you may not request it": an
 *   explicitly requested unconfigured provider is `503 PROVIDER_NOT_CONFIGURED` (L11
 *   exception (a)). **This is the deliberate asymmetry with matchers** — imagery
 *   changes the answer's PROVENANCE, a matcher changes only its ACCURACY — so
 *   filtering here is correct, where filtering a matcher dropdown would not be.
 *
 * ★ `allowed: false` is the operator's `LE_ALLOWED_PROVIDERS` ban (403 server-side)
 *   and filters identically. `!== false` because servers that predate the field
 *   omit it, meaning "allowed".
 */
export function useAvailableProviders(): ProviderInfo[] {
  const { data } = useProviders();
  return (data?.items ?? []).filter((p) => p.configured && p.allowed !== false);
}
