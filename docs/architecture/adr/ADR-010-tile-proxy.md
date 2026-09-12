# ADR-010 — The imagery tile proxy lives on the backend; provider keys never reach the browser

**Status:** Accepted · **AMENDED by `CONTRACT.md` §7.2 — the amendment reverses this ADR's original default**
**Normative record:** `CONTRACT.md` §7.2, §7.2.1, §11.5

---

## ★ Read this first: what changed, and why

`00-overview.md` §7's ADR-010 stated the rule as: **direct upstream URL for keyless providers, proxy
path for keyed ones** — *"Proxy only when there is a secret to protect."*

**That rule is void.** `CONTRACT.md` §7.2 reverses the default, and the reasoning is worth stating
because the original looks obviously right until you check which provider it applies to:

> **`esri_world_imagery` is keyless, and it is the L2 default.** So on **every zero-config machine**,
> every browser tile would have bypassed the proxy — and with it reason 3 (*single chokepoint for ToS
> enforcement*), reason 4 (*quota and cost control — one Redis-backed bucket per provider, counted
> across all users*), reason 5 (*worker-and-browser cache identity*), plus `LE_ALLOWED_PROVIDERS`,
> `LE_IMAGERY_RATE_LIMIT_RPS` and `LE_IMAGERY_USER_AGENT` (which operators are told to set to a real
> contact).

The original rule optimised bandwidth on the **one path that most needed the controls**, and
`20-api.md` stated the opposite rule outright (*"always our proxy path, never the upstream URL — that
is the whole design"*), so two live documents disagreed **in practice, on the default path.**

## Decision (as amended)

**By default, `ProviderInfo.tile_url_template` is the proxy path
`/api/v1/imagery/tiles/{provider}/{z}/{x}/{y}` for EVERY provider — keyed or keyless.**

`LE_IMAGERY_DIRECT_TILE_URLS` defaults to **`false`**. Setting it `true` makes **keyless** providers
return their upstream URL instead, **saving bandwidth at a stated cost** — a cost documented in
[`docs/legal/imagery-terms.md`](../../legal/imagery-terms.md) and intended for an operator who has
read it and accepted the consequence.

**The SPA never learns a provider's upstream URL or key.** It calls `GET /imagery/providers` and
renders whatever `tile_url_template` it is given. **`VITE_MAP_TILE_URL` and `VITE_MAP_ATTRIBUTION` are
deleted** — an escape hatch that lets the bundle disagree with the server about *which provider's ToS
applies* is exactly the divergence this system cannot afford.

**The proxy routes run in the threadpool** (§7.2.1): endpoints 51/52/53 are declared **`def`, not
`async def`**. A synchronous `httpx` call inside an `async def` blocks the event loop for the entire
worker process — taking `/health` down alongside it.

**`204` on a valid tile address with no imagery** (ocean, gap) is deliberate. It is not an error, and
Leaflet renders nothing.

## The six reasons the proxy exists — load-bearing one first

1. **There is no way to call a keyed tile API from a browser without exposing the key.** Anything in
   `VITE_*` is compiled into the bundle and is **public**.
2. **Provider interchangeability.** `local_orthophoto` is *impossible* without the proxy — there is no
   upstream URL to give a browser.
3. **Single chokepoint for ToS enforcement.**
4. **Quota and cost control** — one Redis-backed bucket per provider, counted across all users.
5. **Worker-and-browser cache identity** — the surveyor's browsing **warms the cache for their own
   match job**, and it makes `satellite_checksum` meaningful.
6. **An offline `fixture` provider** that lets the whole app be tested with no network, no keys and no
   weights.

## Consequences

**Positive.**
- Keys stay server-side. Structurally, not by convention.
- Every stated reason above is **true by default**, on the default provider, on a zero-config machine.
- The tile cache is shared between the map UI and the pipeline.
- `LE_IMAGERY_USER_AGENT` and the rate limiter apply to browser traffic too — so the contact address
  an operator is asked to set is actually the one a provider sees.

**Negative, stated honestly.**
- **Proxied tiles cost API bandwidth and a hop**, including for the keyless default. That is the
  price of reasons 3/4/5, and it is a real cost, not a rounding error, on a heavily-panned map.
  `LE_IMAGERY_DIRECT_TILE_URLS=true` buys it back for keyless providers only, and the operator taking
  that trade should know they are opting out of the chokepoint, the shared bucket and cache identity.
- The API is now on the latency path for map rendering. Cache backend choice matters: `disk` in dev,
  **`redis` in prod** — a disk cache in a container is per-replica, and four workers searching the same
  AOI would fetch every tile four times.
- The threadpool requirement is easy to regress: someone converts a route to `async def` for
  consistency and takes down the event loop. §7.2.1 is normative for exactly this reason.

## Alternatives considered

**Rejected — a Mapbox token in `VITE_MAPBOX_TOKEN`.** Public the moment the bundle ships. URL
restrictions mitigate but do not solve, and it forecloses server-side caching entirely.

**Rejected — proxy only keyed providers** (this ADR's own original decision). See the amendment above:
it routes the **default** provider around every control the proxy exists to apply.

**Rejected — never proxy; require every operator to supply keys.** Breaks L2 (zero-config keyless
default) and makes `local_orthophoto` and `fixture` impossible.

**Rejected — a CDN in front of upstream providers instead of our proxy.** Moves the cache but not the
key problem, and adds a third party to the ToS question rather than removing one.

## Related

- [ADR-002](ADR-002-abstract-the-imagery-provider.md) — the provider abstraction and the legal boundary.
- [`docs/legal/imagery-terms.md`](../../legal/imagery-terms.md) — the `LE_IMAGERY_DIRECT_TILE_URLS` consequence.
- `CONTRACT.md` §7.2, §7.2.1, §9.6, §11.5.
