# Configuration — every environment variable, and what it does

**Derived from `CONTRACT.md` §9.** ★ **`.env.example` is GENERATED from §9** by
`scripts/check_env.py --emit-example`, and **CI asserts it matches** (§13.4 rules 7, 11).
*Anything that mirrors a Python source of truth is generated or it drifts.*

---

## 0. The two rules that make this document short

> ### **L10 — Every setting has a working default. `Settings()` with an empty environment NEVER raises.**
> **There are ZERO required environment variables.**

> ### **L2 — The default imagery provider is keyless.**
> `docker compose up` with an empty `.env` yields a working satellite view via `esri_world_imagery`.
> **Keyed providers are strictly opt-in.**

**Copying `.env.example` is OPTIONAL.** You are configuring an application that already works.

### Prefixes

| Prefix | Meaning |
|---|---|
| **`LE_`** | Everything the backend reads. `core/config.py` declares `env_prefix="LE_"` **once**. |
| **`VITE_`** | Frontend, **build-time**, ★ **NEVER secret** — anything in `VITE_*` is compiled into the bundle and is **public**. |
| *(unprefixed)* | Only compose infra vars that upstream images define (`POSTGRES_*`, `REDIS_PORT`). |
| **§** | **A secret.** Never logged, never returned by any API, redacted in `/health/ready`. |

> **`20-api.md`'s unprefixed names (`MAX_UPLOAD_BYTES`, `AUTH_MODE`) and `40-imagery.md`'s
> (`IMAGERY_PROVIDER`, `ORTHO_DIR`) are VOID.** Every backend var is `LE_`-prefixed — an unprefixed
> `AUTH_MODE` in a shared shell is a collision waiting to happen.

### ★ What "boots with zero env vars" means precisely (§9.13)

| Claim | Guarantee |
|---|---|
| `Settings()` with `env={}` | Constructs. Zero required fields. CI: `test_settings_zero_env`. |
| `AiEngineConfig` from `Settings()` with `env={}` → `preflight()` | Returns a `PreflightReport`. **Raises NOTHING.** |
| `uvicorn app.main:app` with no env | Process starts. `GET /api/v1/health` → `200`. OpenAPI serves. |
| `GET /api/v1/health/ready` with **no infra** | ★ **`503` + a per-dependency diagnosis, not a stack trace.** |
| `docker compose up` with **no `.env`** | Full working stack. `LE_IMAGERY_PROVIDER=auto` → Esri (keyless). **This is L2.** |
| `make seed && make up` **with the NIC unplugged** | ★ Upload → mark → export, **offline**. See [offline-mode.md](offline-mode.md). |
| `import ai_engine`, `import gis` — zero installs | **Clean on this machine right now.** |

---

## 1. Core (§9.1)

| Var | Default | What it does |
|---|---|---|
| `LE_ENV` | `development` | `development\|staging\|production` |
| `LE_DEBUG` | `false` | ★ **Forced `false` when `LE_ENV=production`.** Only `true` lets a traceback repr reach `error.details`. |
| `LE_APP_NAME` | `LandExplorer` | OpenAPI title |
| `LE_API_PREFIX` | `/api/v1` | The prefix. Applied **once**, in `api/v1/router.py`. Mirror in nginx. |
| `LE_API_HOST` | `0.0.0.0` | Bind address |
| `LE_API_PORT` | `8000` | |
| `LE_API_WORKERS` | `2` | uvicorn workers |
| `LE_CORS_ORIGINS` | `http://localhost:5173,http://localhost:8080` | CSV. Vite dev + nginx. |
| `LE_LOG_LEVEL` | `INFO` | |
| `LE_LOG_FORMAT` | `json` | `json\|console`. **Use `console` in dev**; JSON is for a log aggregator. |
| `LE_REQUEST_ID_HEADER` | `X-Request-ID` | The ULID a user pastes into a bug report. |
| `LE_SECRET_KEY` **§** | *(ephemeral random per boot)* | ★ **Safe as a default only because auth is OFF by default.** Set it the moment you set `LE_AUTH_MODE`. |
| `LE_TESTING` | `false` | Set by conftest. Fixture provider + eager Celery. |
| `LE_ENABLE_DOCS` | `true` | `/docs`, `/redoc`. *An internal survey tool benefits more from discoverable docs than it loses to disclosure.* |
| `LE_READ_ONLY` | `false` | `403 READ_ONLY_MODE` on every mutating route. |

## 2. Auth — off by default (§9.2)

| Var | Default | What it does |
|---|---|---|
| `LE_AUTH_MODE` | **`none`** | `none\|api_key\|bearer\|cookie` |
| `LE_ACCESS_TOKEN_TTL_SECONDS` | `3600` | |
| `LE_API_KEYS` **§** | *(empty)* | CSV of **hashed** keys |
| `LE_JWKS_URL` | *(empty)* | |
| `LE_RATE_LIMIT_ENABLED` | `false` | |
| `LE_RATE_LIMIT_PER_MINUTE` | `600` | |

> ### ★ The honest consequence, stated rather than hidden
>
> With `LE_AUTH_MODE=none`, **`gcps.adjusted_by = 'anonymous'`** — a value that attributes nothing.
> The database can prove *that* a coordinate was adjusted and *when*, **but not by whom.**
>
> **That is acceptable for a single-surveyor deployment and NOT acceptable for a multi-user one
> producing legal survey deliverables.**
>
> `PATCH /gcps/{id}` returns `401 MISSING_CREDENTIALS` whenever `LE_AUTH_MODE != none` and no
> principal resolves — **the audit trail is enforced the moment there is more than one person who
> could be lying.** `/health/ready` reports `auth_mode` so a reviewer sees it at a glance.

## 3. Database (§9.3)

| Var | Default | What it does |
|---|---|---|
| `LE_DATABASE_URL` **§** | `postgresql+psycopg://landexplorer:landexplorer@db:5432/landexplorer` | ★ **`db` resolves inside compose. On a bare host you MUST set this.** |
| `LE_MIGRATION_DATABASE_URL` **§** | *(= `LE_DATABASE_URL`)* | A distinct superuser role in prod. |
| `LE_DB_POOL_SIZE` | `5` | |
| `LE_DB_MAX_OVERFLOW` | `10` | |
| `LE_DB_POOL_TIMEOUT_SECONDS` | `30` | |
| `LE_DB_ECHO` | `false` | SQL logging. Noisy; dev only. |
| `LE_DB_STATEMENT_TIMEOUT_MS` | `30000` | |
| `LE_DB_AUTO_MIGRATE` | **`false`** | ★ `compose.dev` sets `true`; **prod leaves `false`.** N replicas racing `upgrade head` yields lock contention and partially applied schemas (ADR-011). |

> **The `db` default is a deliberate trade:** optimise for the documented happy path (compose), and
> make the bare-host failure **legible** via `/health/ready`'s per-dependency diagnosis rather than a
> boot traceback. See [running-locally.md](running-locally.md).

## 4. Redis / Celery (§9.4)

| Var | Default | What it does |
|---|---|---|
| `LE_REDIS_URL` **§** | `redis://redis:6379/0` | Broker, health, idempotency, pubsub, rate limit |
| `LE_CELERY_BROKER_URL` **§** | *(= `LE_REDIS_URL`)* | |
| `LE_CELERY_RESULT_BACKEND` **§** | `redis://redis:6379/1` | |
| `LE_CELERY_TASK_ALWAYS_EAGER` | `false` | Tests set `true` — the whole job path, in-process, no broker. |
| `LE_CELERY_WORKER_CONCURRENCY` | `2` | ★ **Keep low: SIFT is CPU-hungry.** |
| `LE_CELERY_TASK_SOFT_TIME_LIMIT` | `600` | ★ Soft ⇒ catchable ⇒ job marked `failed` **cleanly**. |
| `LE_CELERY_TASK_TIME_LIMIT` | `900` | Hard kill. |
| `LE_CELERY_PREFETCH_MULTIPLIER` | `1` | Long tasks ⇒ no hoarding. |
| `LE_CELERY_ACKS_LATE` | `true` | Redelivery on worker crash. |
| `LE_JOB_MAX_ATTEMPTS` | `3` | |
| `LE_JOB_RETRY_BACKOFF_SECONDS` | `5` | |
| `LE_JOB_RETRY_BACKOFF_MAX_SECONDS` | `120` | |
| `LE_JOB_RESULT_TTL_SECONDS` | `86400` | |
| `LE_JOB_STALE_AFTER_SECONDS` | `1800` | Reaper marks orphaned `running` → `failed`. |
| `LE_JOB_PROGRESS_TTL_SECONDS` | `3600` | |
| `LE_JOB_RETENTION_DAYS` | `30` | |

## 5. Storage & uploads (§9.5)

| Var | Default | What it does |
|---|---|---|
| `LE_STORAGE_BACKEND` | `local` | `local\|s3` |
| `LE_STORAGE_LOCAL_ROOT` | `./data/storage` | ★ **Must be a shared volume across api + workers.** |
| `LE_STORAGE_S3_BUCKET` | *(empty)* | |
| `LE_STORAGE_S3_ENDPOINT_URL` | *(empty)* | Set for MinIO. |
| `LE_STORAGE_S3_REGION` | `us-east-1` | |
| `LE_STORAGE_S3_ACCESS_KEY_ID` **§** | *(empty)* | |
| `LE_STORAGE_S3_SECRET_ACCESS_KEY` **§** | *(empty)* | |
| `LE_STORAGE_SIGNED_URL_TTL_SECONDS` | `900` | |
| `LE_STORAGE_MIN_FREE_BYTES` | `2147483648` | `507 INSUFFICIENT_STORAGE`, checked **before** streaming. |
| `LE_UPLOAD_MAX_BYTES` | **`524288000`** (500 MB) | ★ **Mirror in nginx `client_max_body_size`** and `VITE_MAX_UPLOAD_MB`. |
| `LE_UPLOAD_ALLOWED_MIME` | `image/jpeg,image/png,image/tiff,image/webp` | ★ **Sniffed, not trusted from the header.** |
| `LE_MAX_IMAGE_PIXELS` | `400000000` | Decompression-bomb guard. |
| `LE_MAX_IMAGE_DIM` | `65535` | |
| `LE_ASYNC_INGEST_THRESHOLD_BYTES` | `52428800` (50 MB) | Above this, ingest goes async ⇒ `202`. |
| `LE_USE_SENDFILE` | `false` | `X-Accel-Redirect` in prod. |

> **`boto3` absent with `LE_STORAGE_BACKEND=s3` is a `ConfigurationError` at boot** — not a
> degradation. **That is a configuration error, not a missing optional dependency** (§11.3).

## 6. Imagery (§9.6) — ★ read [`docs/legal/imagery-terms.md`](../legal/imagery-terms.md) before enabling a keyed provider

| Var | Default | What it does |
|---|---|---|
| `LE_IMAGERY_PROVIDER` | **`auto`** | ★ **`auto` = PREFERENCE:** walk `LE_IMAGERY_FALLBACK_CHAIN`, take the first `is_configured()`. An explicit name = **that provider**, chain as error-recovery only. |
| `LE_IMAGERY_FALLBACK_CHAIN` | `local_orthophoto,esri_world_imagery` | ★ **`local_orthophoto` FIRST** — mounted orthophotos are definitionally better than any web tile source. Self-skips when the dir is empty. |
| `LE_IMAGERY_DIRECT_TILE_URLS` | **`false`** | ★ `false` ⇒ `tile_url_template` is the **proxy path for every provider**. `true` ⇒ keyless providers return upstream URLs — **opting the browser out of the ToS chokepoint, the shared quota bucket and cache identity.** See [legal §3.3](../legal/imagery-terms.md). |
| `LE_IMAGERY_STRICT` | `false` | ★ **`true` in prod: no silent fallback.** *Dev is forgiving; prod is loud.* |
| `LE_ALLOWED_PROVIDERS` | *(empty = all registered)* | ★ **The operator's hard allow-list.** Outside it ⇒ `403 PROVIDER_TOS_FORBIDDEN`. |
| `LE_IMAGERY_OFFLINE` | `false` | `true` ⇒ only `local_orthophoto` + `fixture`. **A first-class mode, not a test flag.** |
| `LE_IMAGERY_TILE_CACHE_BACKEND` | `disk` | `memory\|disk\|redis`. ★ **`redis` in prod** — a disk cache in a container is per-replica, and four workers on one AOI would fetch every tile four times. |
| `LE_IMAGERY_TILE_CACHE_DIR` | `./data/tile_cache` | |
| `LE_IMAGERY_TILE_CACHE_TTL_SECONDS` | `2592000` (30 d) | ★ **Several ToS cap caching. VERIFY.** Per-provider caps (e.g. `LE_MAPBOX_CACHE_TTL_SECONDS`) additionally apply — **the stricter clock wins.** |
| `LE_IMAGERY_TILE_CACHE_MAX_BYTES` | `21474836480` (20 GB) | LRU cap, enforced by the sweep. |
| `LE_IMAGERY_NEGATIVE_TILE_CACHE_TTL_SECONDS` | `86400` (1 d) | "No imagery here" markers (ocean, gaps). Short on purpose — gaps get filled. |
| `LE_IMAGERY_TILE_CACHE_SWEEP_ON_STARTUP` | `true` | ★ **Desktop GC.** The API process sweeps the disk cache at startup — no Celery beat needed. |
| `LE_IMAGERY_TILE_CACHE_SWEEP_INTERVAL_SECONDS` | `3600` | Periodic in-process sweep; `0` disables (server deployments where beat owns GC). |
| `LE_IMAGERY_AUTO_CACHE_ENABLED` | `true` | Automatic viewport caching (the map's cloud chip toggles it at runtime). Feeds the SAME tile cache as manual downloads. |
| `LE_IMAGERY_AUTO_CACHE_PREFETCH_VIEWPORTS` | `1` | Prefetch buffer around the visible viewport, in viewport-widths (0–3). |
| `LE_IMAGERY_AUTO_CACHE_ZOOM_RANGE` | `full_detail` | `current_only` \| `current_plus_one` \| `current_plus_minus_one` \| `full_detail`. ★ `full_detail`: once zoomed to the gate or deeper, the visible area ALSO fills at every deeper zoom up to `AUTO_CACHE_MAX_ZOOM` — progressively, in per-viewport chunks, session-capped. |
| `LE_IMAGERY_AUTO_CACHE_FULL_DETAIL_MIN_ZOOM` | `15` | Full-detail activates only at this zoom or deeper — a wide viewport × every zoom is millions of tiles, so wide views stay current-only. |
| `LE_IMAGERY_AUTO_CACHE_MAX_ZOOM` | `19` | The full-detail ceiling (clamped to the provider's max). Mapbox native detail ends ~z19; z20–22 are upsampled. |
| `LE_IMAGERY_AUTO_CACHE_CONCURRENCY` | `4` | Background download workers (the provider's rate limiter still governs). |
| `LE_IMAGERY_AUTO_CACHE_MAX_TILES_PER_VIEWPORT` | `500` | The CHUNK size per settled viewport, visible tiles first — full-detail areas fill chunk by chunk. `0` = uncapped. |
| `LE_IMAGERY_AUTO_CACHE_MAX_TILES_PER_SESSION` | `20000` | Session cap (reset on restart / toggle / project switch). `0` = uncapped. |
| `LE_IMAGERY_AUTO_CACHE_MAX_SESSION_BYTES` | `2147483648` (2 GB) | Session download-byte cap. `0` = uncapped (the global cache size still applies). |
| `LE_IMAGERY_MAX_CONCURRENT_FETCHES` | `4` | |
| `LE_IMAGERY_RATE_LIMIT_RPS` | `5` | Token bucket per provider. ★ **A provider's rate limit is a contractual term.** |
| `LE_IMAGERY_REQUEST_TIMEOUT_SECONDS` | `15` | |
| `LE_IMAGERY_MAX_RETRIES` | `3` | Jittered backoff. |
| `LE_IMAGERY_USER_AGENT` | `LandExplorer/1.0 (+https://example.invalid)` | ★ **Set a real contact.** It is how a provider reaches you before they block you. |

### Esri — keyless, the L2 default

| Var | Default |
|---|---|
| `LE_ESRI_IMAGERY_TILE_URL_TEMPLATE` | `…/World_Imagery/MapServer/tile/{z}/{y}/{x}` — ★ **note the `{z}/{y}/{x}` order** |
| `LE_ESRI_REFERENCE_TILE_URL_TEMPLATE` | `…/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}` — the overlay composited **over** imagery for `kind=hybrid` |
| `LE_ESRI_TERRAIN_TILE_URL_TEMPLATE` | `…/World_Terrain_Base/MapServer/tile/{z}/{y}/{x}` — `kind=terrain` |
| `LE_ESRI_MAX_ZOOM` | `19` |
| `LE_ESRI_RATE_LIMIT_RPS` | `8.0` |

### Local orthophoto — offline, highest accuracy

| Var | Default | What it does |
|---|---|---|
| `LE_LOCAL_ORTHO_DIR` | `./data/orthophotos` | Empty dir ⇒ provider reports unavailable, **no crash**. |
| `LE_LOCAL_ORTHO_ATTRIBUTION` | `Local orthophoto` | **You set it — only you know the source.** |
| `LE_LOCAL_ORTHO_REINDEX_SECONDS` | `300` | |
| `LE_LOCAL_ORTHO_ASSUME_BLACK_NODATA` | `false` | ★ **`false` on purpose — black is a legitimate pixel value.** |

### Keyed providers — all opt-in, all `is_configured() = false` until set

| Var | Default | What it does |
|---|---|---|
| `LE_MAPBOX_ACCESS_TOKEN` **§** | *(empty)* | Empty ⇒ **not offered**, not a crash. |
| `LE_MAPBOX_STYLE_ID` | `mapbox.satellite` | |
| `LE_MAPBOX_CACHE_TTL_SECONDS` | `2592000` | ★ **VERIFY against current ToS** — flagged because we did not verify it and will not guess. **Live:** consulted on every cache write/read; the stricter of this and the global TTL wins. |
| `LE_MAPBOX_NEGATIVE_CACHE_TTL_SECONDS` | `86400` | How long Mapbox "no imagery here" is remembered. |
| `LE_MAPBOX_RATE_LIMIT_RPS` | `10` | Self-imposed upstream rate (token bucket; Redis-shared when available). |
| `LE_MAPBOX_MAX_TILE_REQUESTS_PER_OPERATION` | `20000` | ★ Pre-cache budget: upstream requests per Offline Area download. `0` = unlimited. Refused **before** the first request. |
| `LE_MAPBOX_MAX_PREFETCH_TILES` | `50000` | Pre-cache budget: total tiles per download run. `0` = unlimited. |
| `LE_MAPBOX_MAX_TILE_REQUESTS_PER_DAY` | `0` (unlimited) | Daily upstream budget, persisted across restarts; a running download **pauses** (resumable) when reached. |
| `LE_BING_MAPS_KEY` **§** | *(empty)* | |
| `LE_BING_IMAGERY_SET` | `Aerial` | |
| `LE_COPERNICUS_CLIENT_ID` **§** | *(empty)* | |
| `LE_COPERNICUS_CLIENT_SECRET` **§** | *(empty)* | |
| `LE_COPERNICUS_MAX_CLOUD_PCT` | `20` | |
| `LE_SENTINEL_MAX_ZOOM` | **`15`** | ★ **REFUSES `zoom > 15`** rather than serving upsampled mush a matcher would confidently act on. |
| `LE_GOOGLE_MAPS_STATIC_KEY` **§** | *(empty)* | |
| `LE_GOOGLE_TOS_ACKNOWLEDGED` | **`false`** | ★ **DOUBLE OPT-IN. The key alone is insufficient** — the operator must assert their own ToS coverage. **Google Earth is never a provider.** |

## 6a. Elevation (§9.6a)

| Var | Default | What it does |
|---|---|---|
| `LE_ELEVATION_PROVIDER` | **`none`** | `none\|local_dem\|copernicus_dem`. ★ **`none` is KEYLESS, OFFLINE and TERMINAL:** `elevation_m` and `elevation_source` are **both `NULL`** and the job says `ELEVATION_UNAVAILABLE`. **Honest beats absent.** |
| `LE_LOCAL_DEM_DIR` | `./data/dem` | Drop DTM GeoTIFFs here. Empty ⇒ unavailable, **no crash**. |
| `LE_COPERNICUS_DEM_URL` | *(empty)* | |
| `LE_ELEVATION_CACHE_TTL_SECONDS` | `2592000` | |

> ★ **`elevation_source` may never name a source that did not run.** `ck_gcps_elevation_source_consistent`
> binds the pair: `(elevation_m IS NULL) = (elevation_source IS NULL)`.

## 7. Search (§9.7) — ★ consumed by the DEFERRED matching engine

**These are configured, validated and stored. Nothing reads them in this build** — the pipeline is
deferred ([ADR-015](../architecture/adr/ADR-015-defer-the-automatic-matching-engine.md)). They are not
removed: `SCOPE.md` §7 requires re-enabling to touch nothing outside `ai_engine/`.

| Var | Default | What it does |
|---|---|---|
| `LE_SEARCH_DEFAULT_ZOOM` | `18` | |
| `LE_SEARCH_DEFAULT_RADIUS_M` | `1000` | |
| `LE_SEARCH_MAX_RADIUS_M` | `50000` | |
| `LE_SEARCH_MAX_CANDIDATES` | `25` | |
| `LE_SEARCH_WINDOW_SIZE_PX` | `1024` | |
| `LE_SEARCH_OVERLAP_RATIO` | `0.5` | ★ Buys the **512 px footprint guarantee**. At 0.25 it is only 256 px. |
| `LE_SEARCH_TARGET_GSD_M` | `0.5` | |
| `LE_MAX_TILES_PER_JOB` | `512` | |
| `LE_MAX_STATIC_TILES` | **`16`** | ★ **LIVE — endpoint 53.** Cut from 256: *a 64-MP stitch inside a GET is the workload L5 forbids.* |
| `LE_MAX_STATIC_PIXELS` | **`4194304`** (4 MP) | ★ **LIVE — endpoint 53.** |
| `LE_SEARCH_MAX_BBOX_AREA_KM2` | `2500` | |
| `LE_EXIF_RADIUS_INFLATION` | `3.0` | Multiply EXIF HPE. |
| `LE_EXIF_MIN_RADIUS_M` | `250` | |

> **`LE_SEARCH_REQUIRE_PRIOR` is DELETED.** The requirement is **unconditional**: a hint is a hard
> input requirement, not a toggle. **A config flag implying global search is possible would be a lie.**

## 8. AI engine (§9.8) — ★ consumed by the DEFERRED engine

**Every component below resolves to *deferred* in this build**, not to a classical fallback — because
the classical path is deferred too (`SCOPE.md` §6). The **registry, preflight and reporting are real**;
the bodies raise `NotImplementedDeferred`.

| Var | Default | What it does |
|---|---|---|
| `LE_AI_EXTRACTOR` | `sift` | L1 default |
| `LE_AI_MATCHER` | `flann` | |
| `LE_AI_DETECTOR_FREE` | *(empty)* | Empty ⇒ no LoFTR |
| `LE_AI_SEGMENTER` | `classical` | |
| `LE_AI_SUGGESTER` | `classical_suggester` | |
| `LE_AI_RANSAC_METHOD` | `usac_magsac` | ★ A robust-fit **METHOD** (`RansacConfig.method`) |
| `LE_AI_ESTIMATOR_BACKEND` | `opencv` | ★ A component **REGISTRY KEY**. `opencv` is the only registered one. |
| `LE_AI_ALLOW_DEEP_MODELS` | `true` | `false` = never even probe |
| `LE_AI_STRICT_BACKEND` | **`false`** | ★ `true` ⇒ missing weights **raise**. **CI accuracy suites only — `true` in prod violates L1.** |
| `LE_AI_MODEL_WEIGHTS_DIR` | `./data/model_weights` | ★ **Empty by default and that is the supported state.** |
| `LE_AI_DEVICE` | `auto` | ★ **`auto` → `cpu` here** (`cuda.is_available()` is `False` **despite the cu130 wheel**). `cuda` when unavailable ⇒ **WARN + `cpu`**, never a crash. **Never infer CUDA from a build name.** |
| `LE_AI_TORCH_THREADS` | `0` | `0` = torch's default |
| `LE_AI_DETERMINISTIC_SEED` | `42` | RANSAC reproducibility |
| `LE_AI_MAX_FEATURES` | `8000` | |
| `LE_AI_CLAHE_ENABLED` | `true` | Big win on hazy field photos |
| `LE_AI_RATIO_TEST` | `0.75` | Lowe |
| `LE_AI_CROSS_CHECK` | `true` | Mutual NN |
| `LE_AI_MIN_MATCHES` | `10` | Below ⇒ candidate skipped |
| `LE_AI_RANSAC_THRESHOLD_PX` | `3.0` | |
| `LE_AI_RANSAC_MAX_ITERS` | `10000` | |
| `LE_AI_RANSAC_CONFIDENCE` | `0.999` | |
| `LE_AI_MIN_INLIERS` | `12` | H1 |
| `LE_AI_MIN_CONFIDENCE` | `40.0` | ★ **0–100.** Below ⇒ dropped. **Refusing to answer beats a confident wrong coordinate (L12).** |
| `LE_AI_RANK_MARGIN` | `10.0` | Winner must beat runner-up by this, else `status="ambiguous"` |
| `LE_AI_MAX_RESULTS` | `5` | |
| `LE_AI_SCORE_WEIGHT_FEATURE` | `0.25` | ★ The four weights **must sum to 1.0 ± 1e-6** |
| `LE_AI_SCORE_WEIGHT_GEOMETRIC` | `0.35` | |
| `LE_AI_SCORE_WEIGHT_LANDMARK` | `0.30` | |
| `LE_AI_SCORE_WEIGHT_SEMANTIC` | `0.10` | |
| `LE_AI_CALIBRATION_ID` | `identity` | ★ **Ships uncalibrated and says so** (`calibrated=false`) |
| `LE_AI_SEMANTICS_ENABLED` | `false` | Off: SAM is heavy and weight-dependent |
| `LE_AI_DEEP_MAX_CANDIDATES` | `8` | ★ **CODE-ENFORCED cap.** LoFTR/SAM are 2–8 s per 1024² on CPU. |
| `LE_AI_SAM_CHECKPOINT` · `LE_AI_SUPERPOINT_WEIGHTS` · `LE_AI_SUPERGLUE_WEIGHTS` · `LE_AI_LIGHTGLUE_WEIGHTS` · `LE_AI_LOFTR_WEIGHTS` · `LE_AI_DINOV2_WEIGHTS` | *(all empty)* | ★ **Weights are NEVER auto-downloaded.** `scripts/download_models.py` is opt-in, prints licences, and **requires a worker restart** (preflight is cached). |

> **`LE_AI_ESTIMATOR` is DELETED — it was a zero-env boot crash.** It defaulted to `usac_magsac`,
> which is a `HomographyMethod` **value**, not a registry **key** — so resolving it found no spec,
> exhausted the chain, and raised `ComponentUnavailable` **at boot on an empty environment**, violating
> L10 and L11. **Two env vars, two concepts, no overlap:** `LE_AI_RANSAC_METHOD` (a method) and
> `LE_AI_ESTIMATOR_BACKEND` (a registry key).

## 9. Limits, exports, misc (§9.9)

| Var | Default | What it does |
|---|---|---|
| `LE_MAX_ANNOTATIONS_PER_IMAGE` | `2000` | |
| `LE_MAX_BATCH_FILES` | `100` | |
| `LE_MAX_BATCH_BYTES` | `2147483648` | |
| `LE_MAX_REPLAY_EVENTS` | `5000` | |
| `LE_CHECKPOINT_EVERY_N_EVENTS` | `50` | |
| `LE_GCP_CONSISTENCY_TOLERANCE_M` | `0.5` | ★ `PATCH /gcps/{id}` with **both** `lat/lon` and `satellite_px`: beyond this ⇒ `422 GCP_ADJUSTMENT_AMBIGUOUS`. |
| `LE_GCP_BOUNDS_SLACK_M` | `100` | |
| `LE_GEOTIFF_DISAGREEMENT_M` | `50` | `geotiff_georeference_disagreement` flag |
| `LE_PROJECT_NAMES_UNIQUE` | `false` | |
| `LE_EXPORT_DIR` | `./data/storage/exports` | |
| `LE_EXPORT_FORMATS` | `csv,geojson,kml,kmz,shapefile,gpkg,dxf,pdf` | ★ **Unavailable optional deps are DROPPED from `GET /capabilities`, not crashed on.** |
| `LE_EXPORT_DEFAULT_SRID` | `4326` | |
| `LE_EXPORT_TTL_SECONDS` | `604800` (7 d) | Then `410 EXPORT_EXPIRED`. |
| `LE_EXPORT_MAX_ROWS` | `100000` | |
| `LE_EXPORT_INCLUDE_ATTRIBUTION` | `true` | ★ **Should not be turned off** — several providers' ToS **require attribution on derived output**. |

## 10. Observability (§9.10)

| Var | Default | What it does |
|---|---|---|
| `LE_METRICS_ENABLED` | `true` | |
| `LE_METRICS_PATH` | `/metrics` | ★ **Not under `/api/v1`**; not part of the public contract. |
| `LE_SENTRY_DSN` **§** | *(empty)* | Empty ⇒ not initialised |
| `LE_OTEL_EXPORTER_OTLP_ENDPOINT` | *(empty)* | Empty ⇒ **no-op tracer** |
| `LE_OTEL_SERVICE_NAME` | `landexplorer-api` | |

**Required metrics:** `http_requests_total{route,method,status}` · `http_request_duration_seconds{route}`
· `job_duration_seconds{type,status}` · `job_queue_depth{queue}` ·
`imagery_tile_requests_total{provider,cache}` · `imagery_upstream_errors_total{provider}` ·
**`model_fallbacks_total{requested,effective,reason}`** · `gcp_adjustments_total` ·
`ratelimit_rejections_total{scope}` · `ratelimit_failopen_total` · `unhandled_exceptions_total{route}`.

> ★ **`model_fallbacks_total` is deliberately a metric and not just a log line.** A fleet-wide spike
> means **someone's weight volume did not mount** — *that should page, not hide in `INFO`.*

★ **Keys, tokens, and `Authorization` values are scrubbed by a logging filter before emission.**

## 11. Frontend — `VITE_` (§9.11) — ★ build-time, NEVER secret

| Var | Default | What it does |
|---|---|---|
| `VITE_API_BASE_URL` | `/api/v1` | |
| `VITE_APP_NAME` | `LandExplorer` | |
| `VITE_MAP_DEFAULT_CENTER` | `0,0` | |
| `VITE_MAP_DEFAULT_ZOOM` | `3` | |
| `VITE_JOB_POLL_INTERVAL_MS` | `1500` | Floor for the adaptive schedule |
| `VITE_MAX_UPLOAD_MB` | `500` | ★ **Mirrors `LE_UPLOAD_MAX_BYTES`** |
| `VITE_ENABLE_DEVTOOLS` | `false` | |
| `VITE_MIN_LANDMARKS` | `4` | A homography needs ≥4. ★ **Inherited from the deferred engine — in manual mode a single correspondence is already a valid GCP.** |

> **`VITE_MAP_TILE_URL` and `VITE_MAP_ATTRIBUTION` are DELETED.** The backend is the single source of
> truth; the SPA calls `GET /imagery/providers`. **An escape hatch that lets the bundle disagree with
> the server about which provider's ToS applies is exactly the divergence this system cannot afford.**
> **`VITE_JOB_SSE_ENABLED` is DELETED** — SSE is out of scope for v1.

## 12. Compose infrastructure (§9.12) — unprefixed; upstream images own these

| Var | Default |
|---|---|
| `POSTGRES_USER` | `landexplorer` |
| `POSTGRES_PASSWORD` **§** | `landexplorer` — ★ **change in prod** |
| `POSTGRES_DB` | `landexplorer` |
| `POSTGRES_PORT` | `5432` |
| `REDIS_PORT` | `6379` |
| `LE_WEB_PORT` | `8080` |
| `LE_WORKER_CV_REPLICAS` · `LE_WORKER_IO_REPLICAS` · `LE_WORKER_EXPORT_REPLICAS` | `1` |

---

## 13. Recipes

### Local dev, no Docker
```bash
LE_DATABASE_URL=postgresql+psycopg://landexplorer:landexplorer@localhost:5432/landexplorer
LE_REDIS_URL=redis://localhost:6379/0
LE_CELERY_RESULT_BACKEND=redis://localhost:6379/1
LE_LOG_FORMAT=console
LE_DB_AUTO_MIGRATE=true
```
See [running-locally.md](running-locally.md).

### Air-gapped / demo — no network at all
```bash
LE_IMAGERY_OFFLINE=true          # only local_orthophoto + fixture resolve
LE_IMAGERY_PROVIDER=fixture      # or drop GeoTIFFs in ./data/orthophotos and leave it `auto`
LE_ELEVATION_PROVIDER=none
```
See [offline-mode.md](offline-mode.md).

### Production hardening
```bash
LE_ENV=production                # forces LE_DEBUG=false
LE_SECRET_KEY=<a real secret>
LE_AUTH_MODE=bearer              # ★ the audit trail becomes enforceable
LE_DB_AUTO_MIGRATE=false         # migrate as a deliberate step; N replicas racing is the bug
LE_IMAGERY_STRICT=true           # no silent provider fallback — provenance is not negotiable
LE_ALLOWED_PROVIDERS=local_orthophoto   # only what you are licensed for
LE_IMAGERY_TILE_CACHE_BACKEND=redis     # a disk cache in a container is per-replica
LE_IMAGERY_USER_AGENT="YourOrg LandExplorer/1.0 (+https://yourorg.example/contact)"
LE_LOG_FORMAT=json
LE_AI_STRICT_BACKEND=false       # ★ true in prod violates L1
```

> ★ **Before any commercial deployment, work through the operator checklist in
> [`docs/legal/imagery-terms.md`](../legal/imagery-terms.md) §4.** It is a compliance obligation, not a
> formality.
