# Offline mode — the whole product with the NIC unplugged

**★ A first-class supported mode, not a test flag** (`CONTRACT.md` §9.13).

---

## Why this exists

**The brief's hard requirement is that the system work end to end on this machine, and it gives no
network guarantee.**

v1.0 satisfied "works out of the box" **only via Esri, which needs network** — and when Esri is
unreachable, `get_tile` raises `ProviderTransportError`, which §11.6 correctly classifies as a job
**`failed`**. So the disconnected out-of-the-box experience was: *upload, mark landmarks, match, **job
fails***.

**Both offline providers were unreachable by default:** `fixture` was labelled **"TEST-ONLY"** and
wired to `LE_TESTING` (*"set by conftest"*), and `local_orthophoto` self-skips because
`./data/orthophotos` ships empty.

> ★ **The capability existed — the e2e suite has always used the fixture provider with no network — it
> just had no door a human could open.** `fixture`'s label changed from **"TEST-ONLY"** to **"TEST +
> OFFLINE DEMO"**, because the old comment told implementers to make it unreachable in production,
> **which would have broken the very mode §9.6 promises.**

---

## 1. The two offline providers

| Provider | Use | Output |
|---|---|---|
| **`local_orthophoto`** | ★ **Real work.** Your own GeoTIFFs in `LE_LOCAL_ORTHO_DIR`. | ★ **Real coordinates.** Highest accuracy, **the only path where total error is knowable**, and **no third party in the request path**. |
| **`fixture`** | ★ **Demo and tests.** Procedural, deterministic, committed tiles. | ★ **Synthetic and geographically meaningless. A test artefact, NOT a coordinate.** |

> ### ★ Never confuse these
>
> `local_orthophoto` is the **best** provider in the system for a survey deliverable.
> `fixture` output **must never reach one.** It exists to prove the *workflow*, not to produce data.

---

## 2. Real offline work — `local_orthophoto`

**Drop GeoTIFFs in and you are done:**

```bash
cp /path/to/your-ortho.tif ./data/orthophotos/
```

★ **That is the entire configuration.** `LE_IMAGERY_PROVIDER` defaults to **`auto`**, which walks
`LE_IMAGERY_FALLBACK_CHAIN` (`local_orthophoto,esri_world_imagery`) and takes the first
`is_configured()` provider. **A populated ortho dir wins automatically.**

```bash
export LE_LOCAL_ORTHO_ATTRIBUTION="Aerial survey 2026-03, © YourOrg"   # ★ only you know the source
export LE_IMAGERY_OFFLINE=true          # optional: hard-restrict to local_orthophoto + fixture
export LE_ELEVATION_PROVIDER=local_dem  # optional: drop DTM GeoTIFFs in ./data/dem
```

> **Why `auto` matters, and why it was a real bug.** v1.0 defaulted `LE_IMAGERY_PROVIDER` to
> `esri_world_imagery` and walked the chain **only when the named provider was unconfigured**. Esri is
> keyless, so `is_configured()` is **always True**, so **the chain was never consulted** — and an
> operator who dropped GeoTIFFs into `./data/orthophotos` **still got Esri tiles and never learned
> why.** The ordering's own rationale described a **preference**; the code implemented **error
> recovery**. Only one could be true. **`auto` makes both true.**

**Verify:**

```bash
curl -s $API/imagery/providers | jq '.items[] | select(.configured) | {name, attribution}'
curl -s $API/health/ready | jq '.checks.imagery'      # -> provider: "local_orthophoto"
```

★ **`LE_LOCAL_ORTHO_ASSUME_BLACK_NODATA=false` on purpose — black is a legitimate pixel value.**

---

## 3. The offline demo — `fixture`

```bash
python scripts/make_fixtures.py      # synthetic ortho + tiles + scene. Fixed seed. No network.
python scripts/seed_demo_data.py     # a demo project with default_provider='fixture'
make seed && make up
```

★ **Upload → mark → place GCPs → export, offline, no weights, no GPU.**

```bash
export LE_IMAGERY_OFFLINE=true
export LE_IMAGERY_PROVIDER=fixture
```

With `LE_IMAGERY_OFFLINE=true`, **only `local_orthophoto` and `fixture` resolve for NETWORK
fetches.** Any upstream request to another provider is refused rather than attempted — **air-gapped
mode, enforced rather than hoped for.** Cached tiles are another matter — see the next section.

---

## 3.4 Automatic viewport caching — the continuous half

> **"Automatic caching is designed to continuously cache the areas the user is actively
> working on. Manual Offline Area Download is designed to deliberately prepare a complete
> geographic area for field use."**

**Both feed the SAME persistent tile cache** (`data/tile_cache/`) — a tile cached by one
is indistinguishable to the other and to the live map.

While the map is open and **Automatic caching** is ON (the cloud chip on the map), every
*settled* viewport (debounced `moveend`/`zoomend`, never per-mouse-move) is reported to
`POST /api/v1/imagery/cache/viewport`. The backend enumerates the visible tiles at the
current zoom, adds a configurable prefetch ring
(`LE_IMAGERY_AUTO_CACHE_PREFETCH_VIEWPORTS`, default 1 viewport), skips everything the
cache already holds, and queues just the missing tiles for background download — visible
tiles first (HIGH), the prefetch ring after (MEDIUM/LOW), deeper zooms last. A new
viewport **replaces** the queue, so tiles for an area you left are cancelled, and an
in-flight registry guarantees one upstream request per tile no matter how many paths ask.

**Full detail (the default `ZOOM_RANGE=full_detail`):** once you are zoomed to z15 or
deeper, the visible area also fills at **every deeper zoom** up to
`LE_IMAGERY_AUTO_CACHE_MAX_ZOOM` (default z19) — progressively, in per-viewport chunks
(500 tiles at a time, shallow→deep), continuing automatically while you work until the
area is complete or a session cap stops it. Below z15 it stays current-zoom-only,
because a wide viewport times every zoom is millions of tiles.

Strict caps keep it from ever exploding (each refusal names its setting):

```bash
LE_IMAGERY_AUTO_CACHE_ENABLED=true
LE_IMAGERY_AUTO_CACHE_PREFETCH_VIEWPORTS=1     # 0–3 viewports of buffer
LE_IMAGERY_AUTO_CACHE_ZOOM_RANGE=full_detail   # | current_only | current_plus_one | current_plus_minus_one
LE_IMAGERY_AUTO_CACHE_FULL_DETAIL_MIN_ZOOM=15
LE_IMAGERY_AUTO_CACHE_MAX_ZOOM=19
LE_IMAGERY_AUTO_CACHE_CONCURRENCY=4
LE_IMAGERY_AUTO_CACHE_MAX_TILES_PER_VIEWPORT=500     # the chunk size
LE_IMAGERY_AUTO_CACHE_MAX_TILES_PER_SESSION=20000
LE_IMAGERY_AUTO_CACHE_MAX_SESSION_BYTES=2147483648   # 2 GB per session; 0 = uncapped
```

It always yields: a running **manual** Offline Area download pauses automatic caching
(deliberate AOI preparation owns the rate budget); offline mode or a dead network pauses
it with a visible note (and it resumes for the *current* viewport only — never a replay
of everywhere you went); the provider's ToS TTL, the global size cap and eviction apply
unchanged, because it is just another writer to the one cache. The chip shows live
coverage of the visible area ("94% cached"), the download count, and the session tallies;
`GET /api/v1/imagery/usage` breaks upstream requests down by source
(`map` / `precache` / `viewport`).

## 3.5 Cached web imagery — the Offline Area Manager

**The field workflow: prepare online, survey offline.** The map's tile proxy is a READ-THROUGH
disk cache (`data/tile_cache/`), and the **Offline Area Manager** (the download icon on the
workspace map) turns that into a deliberate preparation step:

1. Draw the AOI polygon on the map and pick a zoom band (default **z13→z17**; up to z19).
2. The panel shows the **server's estimate** before anything downloads: total tiles, already
   cached, **new tiles = upstream requests**, and estimated storage (measured from your own
   cache when possible, a stated default otherwise).
3. **Download.** The run executes **server-side** (`POST /api/v1/imagery/offline/operations`)
   through the same cache, licence gate and rate limiter as the live map — with progress,
   **pause / resume / cancel / retry-failed**, and it survives a page navigation.
4. On completion an **offline manifest** (`data/tile_cache/manifests/<id>.json`) records the
   provider, its **config fingerprint** (style/@2x/format — the cache variant), AOI, zoom band,
   counts and the imagery's **expiry** (the provider's ToS-capped TTL).

**In the field**, with `LE_IMAGERY_OFFLINE=true` and the provider explicitly selected (e.g.
`mapbox_satellite`): cached tiles are **served from disk**; uncached tiles return a controlled
`204` (blank ground marks the edge of the prepared area) — **never a network attempt**. The
allow-list still applies: offline mode never widens `LE_ALLOWED_PROVIDERS`.

Coverage of any area can be checked at any time: `POST /api/v1/imagery/offline/coverage`.

**Budgets** (all refusals happen *before* the first request, naming the setting to change):

```bash
LE_MAPBOX_MAX_TILE_REQUESTS_PER_OPERATION=20000   # upstream requests per download run
LE_MAPBOX_MAX_PREFETCH_TILES=50000                # total tiles per run (cached included)
LE_MAPBOX_MAX_TILE_REQUESTS_PER_DAY=0             # 0 = unlimited; persisted across restarts
```

**Cache policy** — every knob is live:

```bash
LE_IMAGERY_TILE_CACHE_TTL_SECONDS=2592000    # global 30 d
LE_MAPBOX_CACHE_TTL_SECONDS=2592000          # ★ Mapbox's ToS-capped TTL — the STRICTER clock wins
LE_MAPBOX_NEGATIVE_CACHE_TTL_SECONDS=86400   # "no imagery here" markers (ocean, gaps)
LE_IMAGERY_TILE_CACHE_MAX_BYTES=21474836480  # 20 GB, LRU-evicted
LE_IMAGERY_TILE_CACHE_SWEEP_ON_STARTUP=true  # desktop GC — no Celery beat needed
LE_IMAGERY_TILE_CACHE_SWEEP_INTERVAL_SECONDS=3600
LE_MAPBOX_RATE_LIMIT_RPS=10                  # self-imposed upstream rate
```

`GET /api/v1/imagery/usage` reports the app's own ledger — upstream requests (today and since
start), cache hit ratio, 429s, offline misses. **This is the application's count, not the
provider's billing dashboard**, which remains the billing truth.

---

## 4. What works offline — and what does not

| ✅ Works with no network | |
|---|---|
| Upload, metadata, EXIF, thumbnails | |
| The viewer, annotation, undo/redo | |
| The satellite map | via `fixture` or `local_orthophoto` |
| ★ **Manual GCP mode** | **the whole product** |
| Accuracy in metres | `gis/accuracy.py` — GSD + click precision |
| Exports | CSV/GeoJSON/KML/KMZ are **stdlib-only and can never degrade** |
| Version history, batch | |
| ★ `cd ai_engine && pytest`, `cd gis && pytest` | **no network, no GPU, no weights** |
| ★ `cd frontend && pnpm test` | MSW mocks every endpoint — **no backend** |

| ❌ Does not, and says so | |
|---|---|
| Esri / Mapbox / Bing / Sentinel / Google Static — **upstream fetches** | Network. Refused under `LE_IMAGERY_OFFLINE`, or a `ProviderTransportError` → job `failed`. ★ Tiles **pre-cached with the Offline Area Manager still serve** (§3.5). |
| `copernicus_dem` elevation | Network. **`LE_ELEVATION_PROVIDER=none` is keyless, offline and TERMINAL:** `elevation_m` and `elevation_source` are **both NULL** and the job says `ELEVATION_UNAVAILABLE`. ★ **Honest beats absent.** |
| Deep model backends | ★ **Weights are NEVER auto-downloaded** — *a silent multi-hundred-MB fetch on a machine that may be air-gapped, triggered by a user clicking "Match", is unacceptable.* Also deferred. |
| ★ **Automatic matching** | ★ **DEFERRED — not a network issue.** `501`. [ADR-015](../architecture/adr/ADR-015-defer-the-automatic-matching-engine.md) |
| `pip install` of the backend stack | ★ **Genuinely needs a network, once.** See [running-locally.md](running-locally.md) §1. |

---

## 5. Air-gapped production checklist

- [ ] `LE_IMAGERY_OFFLINE=true` — only `local_orthophoto` + `fixture` resolve
- [ ] `LE_ALLOWED_PROVIDERS=local_orthophoto` — ★ **fixture cannot be selected by accident**
- [ ] GeoTIFFs in `LE_LOCAL_ORTHO_DIR`; `LE_LOCAL_ORTHO_ATTRIBUTION` set to the real source
- [ ] `LE_ELEVATION_PROVIDER=local_dem` + DTMs in `LE_LOCAL_DEM_DIR`, **or `none` and accept honest NULLs**
- [ ] `LE_IMAGERY_STRICT=true` — ★ **no silent fallback.** *Dev is forgiving; prod is loud.*
- [ ] `LE_IMAGERY_TILE_CACHE_BACKEND=redis` if you run multiple workers
- [ ] Verify `/health/ready` reports `imagery: local_orthophoto` and `raster: gdal` (**not `none`**)
- [ ] ★ **Confirm no `fixture`-sourced GCP is in your export.** Filter on `source` and on the
      project's provider. **A fixture coordinate is not a coordinate.**



## 6. Change the path of where to see my cached map photos

1 - Create a folder with your new path
2 - nano ~/.local/share/MonoCameraGeolocator/work/.env
3 - Edit or Add this line with your created folder path,  LE_IMAGERY_TILE_CACHE_DIR=/home/pcblack/Documents/LandExplorer/map_tiles
4 - Save it
5 - To keep your old cached files move them to this new directory path with this command:
 ```bash 

 mv ~/.local/share/MonoCameraGeolocator/work/data/tile_cache/* /home/pcblack/Documents/LandExplorer/map_tiles/

 ```