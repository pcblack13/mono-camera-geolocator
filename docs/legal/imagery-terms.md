# Imagery providers — legal posture, ToS obligations, and what the operator must verify

**Status:** compliance record. **Not marketing, and not legal advice.**
**Audience:** the operator who deploys LandExplorer, and whoever signs off on what it outputs.
**Normative mechanisms:** `CONTRACT.md` §11.5 · [ADR-002](../architecture/adr/ADR-002-abstract-the-imagery-provider.md) · [ADR-010](../architecture/adr/ADR-010-tile-proxy.md)
**Last reviewed:** 2026-07-17 · **Review cadence: every 6 months and before any commercial deployment.**

---

## 0. Read this first

> ### This document is not legal advice, and it is not a licence.
>
> It records **what we know, what we assume, and what we have not verified**, so that an operator can
> see the shape of their obligation. **Provider terms change without notice and vary by jurisdiction,
> by contract, and by plan.** Every statement below about a third party's terms is a summary made on
> the review date above, from publicly published terms, and **may be out of date by the time you read
> it**.
>
> **You — the operator — are the licensee.** Not us. If LandExplorer fetches a tile using your key,
> that request is made under *your* agreement with *that* provider, for *your* purpose. **You must
> read the current terms yourself before enabling any provider**, and again before using its output in
> a deliverable you sell, file, or rely on.

### 0.1 Why this document exists at all

The product's output is a **survey coordinate someone may dig, build, or file against**, derived by a
human clicking on **somebody else's satellite imagery**. That makes two questions unavoidable:

1. **Were we allowed to use those pixels that way?**
2. **Does the answer change when the output is sold?**

Almost every web basemap's terms were written for *"show a map in an app"*. **"Derive a survey control
point from the imagery and sell it as a deliverable" is a materially different use, and it is the use
most likely to exceed the terms of any web basemap.** This is the single most important sentence in
this document.

---

## 1. Google Earth — why it is not, and cannot be, a provider

**The client states plainly that Google Earth imagery cannot legally or technically be searched or
processed via its app or API.** That is the constraint the entire imagery layer is designed around.

### 1.1 What we did about it

**Google Earth is not disabled. It is absent.** (`CONTRACT.md` §11.5, ADR-002.)

| | |
|---|---|
| Provider module | **None.** No `google_earth.py`, no scaffolding, no commented-out class. |
| Registry entry | **None.** |
| Database enum | **The `imagery_provider` PG enum has no `google_earth` member** — it is unrepresentable in the type system. **The database itself cannot store a row claiming Google Earth as a source.** |
| Config flag | **None.** There is no `LE_GOOGLE_EARTH_*` variable to set. |
| CI | **Greps for Earth endpoint patterns.** |

**Why absence rather than a disabled flag.** A flag can be flipped. An enum member can be selected. A
raising stub invites a `# TODO: implement`. And a `google_earth` enum member would be a value the
database could **store** — so a row could *claim* Google Earth provenance, which is precisely the
misattribution the constraint exists to prevent. **"Never" has exactly one implementation, and it is
absence.**

### 1.2 The distinction that matters, because it is easy to get wrong

| Product | Status here |
|---|---|
| **Google Earth** (the desktop/web application and its imagery) | ★ **EXCLUDED. Never a provider.** |
| **Google Earth Engine** | ★ **EXCLUDED.** Not implemented, not scaffolded, not planned. |
| **Google Maps Static API** | **Available, opt-in, double-gated.** A *different* product with a *different* commercial licence — see §2.5. |

**These are not the same product and they do not share terms.** The exclusion of Google Earth is not a
statement that Google imagery is unusable; it is a statement that **that product, via that app or
API, is unavailable to us for this purpose.** Google Maps Static is a separately licensed commercial
API, and it remains the operator's obligation to confirm their own licence covers this use (§2.5).

### 1.3 What "technically" means, and why it does not soften anything

Scraping tiles out of the Google Earth client, or reverse-engineering an undocumented endpoint, is
**technically possible and categorically forbidden here** — by the client's constraint, by Google's
terms, and by the fact that a survey deliverable built on a scraped tile is a deliverable with no
defensible provenance. **There is no engineering cleverness that makes this available.** If someone
proposes it, the answer is no, and the reason is this section.

---

## 2. Per-provider posture

**Legend.**
· **Key** — what the operator must supply.
· **Attribution** — enforced structurally: `SatelliteChip.attribution` and `match_results.attribution`
are **required fields**. **Pixels cannot travel without their credit.**
· **`allows_caching`** — when `False`, `DiskTileCache`/`RedisTileCache` **refuse the write** and fall
back to in-process LRU with a `WARNING`. **A provider with restrictive terms cannot accidentally
accumulate a permanent on-disk copy via a background job.**
· **`allows_derivative_export`** — when `False`, `ExportContext.chip = None`, so **the PDF omits the
map figure** and records it in `ExportBundle.warnings`.

> **★ The capability flags are the enforcement. This document is the reasoning.** A ToS obligation
> that lives only in Markdown is an obligation nobody enforces at 2 a.m. **`capabilities()` is the
> place a provider's terms become executable** — and it is the operator's job to make sure the flags
> a provider ships with match the terms the operator is actually under.

### 2.1 `esri_world_imagery` — ★★ THE DEFAULT · KEYLESS

| | |
|---|---|
| **Key** | **None.** This is L2: `docker compose up` with an empty `.env` yields a working satellite view. |
| **Env** | `LE_ESRI_IMAGERY_TILE_URL_TEMPLATE` (note the **`{z}/{y}/{x}`** order), `LE_ESRI_MAX_ZOOM=19`, `LE_ESRI_RATE_LIMIT_RPS=8.0` |
| **Attribution** | **Required.** Esri, and the imagery's source consortium (Maxar, Earthstar Geographics, and the GIS User Community, varying by location and zoom). |

> ### ★ The caveat that must not be softened, restated from `CONTRACT.md` §11.5
>
> **"Keyless Esri" is a BOOTSTRAPPING decision, not a licensing one. Reachable ≠ licensed.**
>
> The endpoint answers without a key. **That is not permission.** ArcGIS Online content is governed by
> Esri's terms and by the terms of the underlying imagery suppliers, and those terms distinguish
> sharply between evaluation, non-commercial use, and commercial use — and between *displaying* a map
> and *deriving a product* from it.
>
> **The default satisfies the zero-config mandate and nothing more. This is not a recommendation.**

**What the operator MUST verify before any commercial or deliverable-producing use:**

1. **That you have an ArcGIS licence covering your use**, and that "derive survey control points and
   supply them to a client" is within it. Assume it is not until you have confirmed it is.
2. **Whether a keyless/unauthenticated request is permitted at all** for your use, or whether Esri
   requires an authenticated ArcGIS Online / Developer subscription.
3. **The caching terms** against `LE_IMAGERY_TILE_CACHE_TTL_SECONDS` (**default 30 days**). See §3.
4. **The attribution requirements** for the specific imagery served at your AOI and zoom — attribution
   for World Imagery is **source- and location-dependent**, not one fixed string.
5. **Your rate limit**, against `LE_ESRI_RATE_LIMIT_RPS=8.0` and `LE_IMAGERY_RATE_LIMIT_RPS=5`.

**Open, unresolved, and escalated to the client** (`CONTRACT.md` §12.5, `TRACEABILITY.md` §5):

> Whether keyless Esri is a defensible *product* default for paid deliverables **is a question for the
> client and their counsel, not a decision an architect gets to make alone.** If the answer is no, the
> honest move is a first-run interstitial forcing an explicit provider choice — **which trades away the
> zero-config promise.** The default stands **pending that ruling**; the mitigation is that the caveat
> propagates to the README, the first-run log line, the UI provider picker, and **every PDF**.

### 2.2 `local_orthophoto` — ★★ THE CLEANEST POSTURE

| | |
|---|---|
| **Key** | None. Reads GeoTIFFs from `LE_LOCAL_ORTHO_DIR` (`./data/orthophotos`). |
| **Attribution** | `LE_LOCAL_ORTHO_ATTRIBUTION` — **the operator sets it, because only the operator knows the source.** |
| **Terms** | ★ **Whatever the operator's own imagery licence says. There is no third party in the request path.** |

**This is the recommended provider for commercial survey work**, and the recommendation is not only
legal:

- **No third-party ToS in the loop.** You own or licence the imagery directly; the question of whether
  a basemap's terms cover derived deliverables **does not arise**.
- **It is the highest-accuracy path**, and **the only path where total error is knowable**
  (`CONTRACT.md` §12.5) — your ortho has a known georegistration error; Esri/Mapbox/Bing do not
  publish theirs. This is why it **heads the default fallback chain**: with `LE_IMAGERY_PROVIDER=auto`
  (the default), a populated ortho directory **wins automatically**, and an empty one self-skips to
  Esri with no branching.
- **It is fully offline.**

**What the operator MUST verify:** that their own licence for the orthophotos covers the deliverable
they are producing. **Aerial survey imagery is frequently licensed per-project or per-client**, and
"we bought this ortho for project A" does not always extend to project B.

### 2.3 `fixture` — TEST + OFFLINE DEMO

| | |
|---|---|
| **Key** | None. **No network. Deterministic. Procedurally generated.** |
| **Terms** | **None. We generate the pixels.** No third-party rights are involved. |

**Not test-only** — it is the front door of `LE_IMAGERY_OFFLINE=true` and of `make seed && make up`.
See [`docs/guides/offline-mode.md`](../guides/offline-mode.md).

**The one obligation:** its output is **synthetic and geographically meaningless**. A GCP derived
against fixture imagery is a **test artefact, not a coordinate**, and must never reach a deliverable.
The demo project seeded by `scripts/seed_demo_data.py` exists to demonstrate the *workflow*, not to
produce survey data.

### 2.4 `mapbox` · `bing` · `sentinel` — keyed, opt-in

These are **registered but report `configured: false`** until their key is set. `GET
/imagery/providers` lists them with a reason. **An explicitly requested unconfigured provider is a
`503 PROVIDER_NOT_CONFIGURED`** — never a silent substitution, because **imagery changes the answer's
provenance** (`CONTRACT.md` §11.0).

#### `mapbox` — `LE_MAPBOX_ACCESS_TOKEN` §

| | |
|---|---|
| **Env** | `LE_MAPBOX_ACCESS_TOKEN` §, `LE_MAPBOX_STYLE_ID=mapbox.satellite`, `LE_MAPBOX_CACHE_TTL_SECONDS=2592000` |
| **Attribution** | **Required**, and Mapbox is specific about form and placement. |

**MUST verify before enabling:**
1. **Your plan covers this use.** Mapbox terms distinguish sharply between plan tiers, and between
   interactive display and other uses.
2. ★ **The caching terms.** `LE_MAPBOX_CACHE_TTL_SECONDS` is marked **"VERIFY against current ToS"** in
   `CONTRACT.md` §9.6 **and it is marked that way because we did not verify it and will not guess.**
   Mapbox has historically restricted caching of its tiles. **The 30-day default may exceed what your
   agreement permits. Check, then set the value to what your agreement actually allows.**
3. **Whether deriving and selling coordinates from Mapbox Satellite is permitted** under your plan.
4. **Attribution placement** — required on the map **and** on derived output.

#### `bing` — `LE_BING_MAPS_KEY` §

| | |
|---|---|
| **Env** | `LE_BING_MAPS_KEY` §, `LE_BING_IMAGERY_SET=Aerial` · requires a **metadata handshake** before tiles |
| **Attribution** | **Required**, including the imagery vendor list **returned by the metadata call** — it is dynamic, not a constant. |

**MUST verify before enabling:**
1. **Which Bing Maps licence you hold.** Bing Maps has distinct free/basic/enterprise terms, and
   licensing has changed materially over the product's life.
2. **Whether your licence permits a non-Microsoft-map end use** — i.e. extracting coordinates rather
   than displaying a Bing map.
3. **Caching.** Bing's terms have historically been restrictive here. **Verify against
   `LE_IMAGERY_TILE_CACHE_TTL_SECONDS` and set `allows_caching=False` on the provider if your terms
   require it** — the cache will then refuse to write and fall back to request-lifetime LRU
   automatically.
4. **That the dynamic vendor attribution from the metadata response is surfaced**, not a hardcoded
   "© Microsoft".

#### `sentinel` (Copernicus) — OAuth2 client credentials

| | |
|---|---|
| **Env** | `LE_COPERNICUS_CLIENT_ID` §, `LE_COPERNICUS_CLIENT_SECRET` §, `LE_COPERNICUS_MAX_CLOUD_PCT=20`, `LE_SENTINEL_MAX_ZOOM=15` |
| **Attribution** | **Required**: Copernicus Sentinel data, with the year. |

**The most permissive licence of the keyed set** — Copernicus Sentinel data is **full, free and open**
under the Copernicus licence, including commercial use, subject to attribution. **This is the keyed
provider whose terms are least likely to obstruct a commercial deliverable.**

**MUST verify before enabling:**
1. **The attribution form** required by the Copernicus licence for your specific output.
2. **The access service's own terms** — the *data* licence and the *API access* terms are separate
   things, and rate limits and quotas belong to the access service.

★ **Accuracy note, which is not a legal point but belongs next to one:** `LE_SENTINEL_MAX_ZOOM=15` and
the provider **refuses `zoom > 15`** rather than serving upsampled mush. Sentinel-2 is ~10 m/px.
**Sentinel-2 L1C georegistration is ~8–12 m CE95** (`CONTRACT.md` §12.5) — so a GCP derived against
Sentinel has a floor on its accuracy of roughly a *building*. It is the right provider for a 50 m
question and the wrong one for a 0.5 m question, and `accuracy.dominant_term` will say
`georeference` to make that visible.

### 2.5 `google_static` — ★ DOUBLE OPT-IN

| | |
|---|---|
| **Env** | `LE_GOOGLE_MAPS_STATIC_KEY` § **AND** `LE_GOOGLE_TOS_ACKNOWLEDGED=true` |
| **Attribution** | **Required**, per Google's terms. |

> **★ The key alone is insufficient — and that is deliberate.** `CONTRACT.md` §11.5: *"Google Maps
> Static needs an affirmative act."* Setting `LE_GOOGLE_TOS_ACKNOWLEDGED=true` is the operator
> **asserting that they have read Google's terms and that their own licence covers this use**. It is a
> second, separate, deliberate action that cannot be performed by accident or by copying a key into an
> `.env`.

**MUST verify before enabling — and this is the provider with the most restrictive terms of the set:**

1. **That your Google Maps Platform agreement permits this use at all.** Google's terms have
   historically been **explicit** about restrictions on: creating derivative products from the
   imagery, extracting or storing content, using the imagery for surveying, and using it outside a
   Google Map.
2. ★ **Caching and storage.** Google's terms have historically **prohibited or tightly limited**
   caching of Static Maps content. **If your terms prohibit caching, the provider must ship
   `allows_caching=False`** — the tile cache will then refuse to write and fall back to in-process,
   request-lifetime LRU with a `WARNING`, automatically.
3. ★ **Derivative export.** If your terms prohibit including the imagery in a derived deliverable, the
   provider must ship **`allows_derivative_export=False`** — the PDF report will then **omit the map
   figure** and say so in `ExportBundle.warnings`, rather than embedding imagery you may not
   redistribute.
4. **That the exclusion of Google Earth (§1) is not weakened by this provider's presence.** They are
   different products with different licences. Enabling Static does **not** enable Earth, and no code
   path in this system can reach Earth.

**Our position:** this provider exists because the API is a legitimate, separately licensed commercial
product that some operators do hold an appropriate licence for. **It is off by default, gated twice,
and we make no claim that any given operator may use it.**

---

## 3. Cross-cutting obligations

### 3.1 Caching — `LE_IMAGERY_TILE_CACHE_TTL_SECONDS` defaults to **30 days**

**Several providers' terms cap or prohibit caching.** The default is chosen for **cost and rate-limit
politeness**, not because 30 days is known to be permitted for your provider.

**The mechanism:** `capabilities().allows_caching = False` makes `DiskTileCache` and `RedisTileCache`
**refuse the write** and fall back to `LRUTileCache` (in-process, request-lifetime) with a `WARNING`.
**So a provider with restrictive terms cannot accidentally accumulate a permanent on-disk copy via a
background job** — which is exactly what a 20 GB LRU tile cache filled by a Celery worker would
otherwise be.

**The operator's obligation:** set `LE_IMAGERY_TILE_CACHE_TTL_SECONDS` to what **your** terms permit,
and ensure the provider's `allows_caching` flag matches **your** agreement. **The flag ships with our
best reading; it is not a legal determination and it is not a substitute for reading your contract.**

### 3.2 Attribution — a licence condition, not a courtesy

**`LE_EXPORT_INCLUDE_ATTRIBUTION` defaults to `true` and ★ should not be turned off.** Several
providers' terms **require attribution on derived output**, so disabling it may place you in breach.

Attribution is structural, not decorative:

- `SatelliteChip.attribution`, `CandidateWindow.attribution` and `match_results.attribution` are
  **required fields** — **pixels cannot travel without their credit, including across the `ai_engine`
  seam**.
- It is surfaced in the map UI, in `X-Imagery-Attribution` on endpoint 36, in the CSV, and in **every
  PDF**.
- ★ **It is always served from the `match_results` row, never by re-resolving the provider** — which
  may have been reconfigured since the pixels were fetched. **The credit belongs to whoever actually
  supplied the pixels, not to whoever is configured today.**

### 3.3 `LE_IMAGERY_DIRECT_TILE_URLS` — the consequence, stated (§14 F-105)

**Default `false`: every provider's `tile_url_template` is our proxy path.** Browser tile traffic
therefore passes through the same chokepoint as worker traffic, and the following apply **to browser
traffic too**:

- **ToS enforcement** — one place where provider rules are applied;
- **the shared quota bucket** — `LE_IMAGERY_RATE_LIMIT_RPS`, counted across all users, per provider;
- **`LE_ALLOWED_PROVIDERS`** — the operator's hard allow-list;
- **`LE_IMAGERY_USER_AGENT`** — ★ **operators should set this to a real contact address.** It is how a
  provider reaches you before they block you.

> **★ Setting `LE_IMAGERY_DIRECT_TILE_URLS=true` opts the browser out of all four**, for keyless
> providers, in exchange for bandwidth. **The keyless provider is `esri_world_imagery` — the default —
> so this is not a marginal setting.** It means every browser tile goes straight to Esri with the
> browser's own User-Agent, outside your rate limit, outside your allow-list, and outside the
> chokepoint. **Take this trade only if you have read §2.1 and accepted the consequence.**

### 3.4 Rate limits

`LE_IMAGERY_RATE_LIMIT_RPS=5` (per provider, token bucket, Redis-backed in prod) and
`LE_IMAGERY_MAX_CONCURRENT_FETCHES=4`. **A provider's rate limit is a contractual term, not a
suggestion** — exceeding it is both a technical failure and a terms breach. Set these to **your**
agreement's limits.

### 3.5 The accuracy disclosure that belongs in every deliverable

**Reported accuracy excludes provider georegistration error, and is therefore optimistic for every
web provider** (`CONTRACT.md` §12.5, unresolved and disclosed).

We report **our fit to the provider's pixels**. **Esri, Mapbox and Bing do not publish their own
georegistration error.** Sentinel-2 L1C is ~8–12 m CE95. The mitigation is structural rather than
rhetorical: `georef_ce90_m` is **mandatory** on `ProviderCapabilities`, flows into `total_ce90_m`, and
`accuracy.dominant_term` lets the UI say the useful thing:

> *"Your accuracy is limited by the basemap, not by the match."*

**`local_orthophoto` is the only path where total error is knowable.** If you are selling a deliverable
with an accuracy figure attached, **that is the provider to use**, and §2.2 is the reason.

---

## 4. The operator's pre-flight checklist

**Before enabling any keyed provider, and before any commercial deployment.** Do not delegate this to
whoever is holding the `.env` file.

- [ ] **I have read the current terms of every provider I am enabling** — not this summary. This
      document is dated and providers change terms without notice.
- [ ] **I hold a licence covering my actual use**, including *"deriving survey control points from the
      imagery and supplying them to a client"* — not merely *"displaying a map"*.
- [ ] **I have verified the caching terms** and set `LE_IMAGERY_TILE_CACHE_TTL_SECONDS` accordingly,
      and confirmed each provider's `allows_caching` flag matches my agreement.
- [ ] **I have verified the attribution requirements** and left `LE_EXPORT_INCLUDE_ATTRIBUTION=true`.
- [ ] **I have verified the derivative-export terms** and confirmed each provider's
      `allows_derivative_export` flag matches my agreement.
- [ ] **I have set `LE_IMAGERY_USER_AGENT` to a real contact address.**
- [ ] **I have set the rate limits to my agreement's limits.**
- [ ] **I have set `LE_ALLOWED_PROVIDERS`** to exactly the providers I am licensed for — so an
      unlicensed one cannot be selected by a request, a config slip, or a fallback.
- [ ] **I have considered `LE_IMAGERY_STRICT=true` for production**, so an unavailable provider is a
      loud `503` rather than a silent substitution. *Dev is forgiving; prod is loud.*
- [ ] **If I am producing a paid deliverable, I have not left the keyless Esri default in place**
      without the ruling in §2.1 — or I have obtained that ruling.
- [ ] **I understand that Google Earth is excluded and that no configuration re-enables it** (§1).
- [ ] **I have read §3.5** and understand that my reported accuracy excludes the basemap's own
      georegistration error, unless I am using `local_orthophoto`.

---

## 5. Summary table

| Provider | Key | Default? | Offline | Terms posture | Recommended for a paid deliverable? |
|---|---|---|---|---|---|
| `esri_world_imagery` | none | ★ **yes** | no | **Reachable ≠ licensed.** Bootstrapping only. **Open question escalated to the client.** | ⚠ **Not without your own ruling** (§2.1) |
| `local_orthophoto` | none | via `auto` | ★ **yes** | ★ **Your own imagery. No third party in the path.** | ★ **YES — and it is the only path where total error is knowable** |
| `fixture` | none | no | ★ **yes** | Ours. Synthetic. | ✗ **Never — its output is not a coordinate** |
| `mapbox` | ✔ § | no | no | Plan-dependent. ★ **Caching terms UNVERIFIED — see §2.4** | Only if your plan says so |
| `bing` | ✔ § | no | no | Licence-tier-dependent; historically restrictive on caching | Only if your licence says so |
| `sentinel` | ✔ § | no | no | ★ **Copernicus: full, free and open, incl. commercial, with attribution** | Yes for ~10 m work — **never for sub-metre** |
| `google_static` | ✔ § **+ ack** | no | no | ★ **Most restrictive. Double opt-in.** Historically restricts derivation, storage, surveying use | Only with an explicit Google agreement covering it |
| **Google Earth** | — | — | — | ★ **EXCLUDED. Unrepresentable. No configuration enables it.** | ✗ **Never** |

---

## 6. If you believe this document is wrong

**Please assume it might be.** It was written from published terms on the review date by engineers,
not lawyers, and its most valuable property is that it is **honest about its own limits**.

- If a provider's terms have changed → open a PR against this file **and** against the provider's
  `capabilities()` flags. **The flags are the enforcement; this file is only the reasoning.**
- If your counsel reaches a different conclusion → **their conclusion wins.** Set
  `LE_ALLOWED_PROVIDERS` to match it, and record the ruling here.
- If you find a code path that reaches an excluded provider → **that is a defect of the highest
  severity.** It should be impossible (§1.1); if it is not, the type system has failed and the fix is
  structural, not a patch.
