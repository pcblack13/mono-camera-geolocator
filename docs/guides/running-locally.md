# Running LandExplorer locally — WITHOUT Docker

**This machine has no Docker.** This guide is the real path, and it is honest about what works today,
what needs a network, and what needs a service you must install yourself.

**Verified on the dev machine on 2026-07-17.** Every capability claim below was checked, not assumed.

---

## 0. What is actually on this machine

```
Python 3.12.3   node v20.20.2   npm 10.8.2   git   make   corepack
```

| Installed | Version | |
|---|---|---|
| `cv2` | **4.13.0** | ★ no `opencv-contrib` — **`cv2.xfeatures2d` is ABSENT**; SURF/BEBLID/VGG/LATCH are unavailable and must not be referenced |
| `numpy` | **2.4.3** | NumPy-2 ABI |
| `scipy` | **1.17.1** | |
| `torch` / `torchvision` | **2.11.0+cu130** | ★ **`torch.cuda.is_available()` is `False`** — there is **no usable GPU** despite the cu130 wheel. **Never infer CUDA from a build name.** |
| `osgeo` (GDAL) | **3.8.4** | ★ Raster IO works today **without** rasterio |
| `PIL` | 12.1.1 | |

| **NOT installed** | Consequence |
|---|---|
| `fastapi` · `pydantic` · `sqlalchemy` · `alembic` · `celery` · `redis` · `httpx` | ★ **The backend cannot run until you `pip install` them — which needs a network.** |
| `rasterio` · `pyproj` · `geopandas` · `fiona` · `shapely` · `reportlab` · `ezdxf` | Optional. **Each degrades gracefully** (§11.3). GDAL substitutes for rasterio here. |
| `pytest` · `pytest-asyncio` · `hypothesis` | ★ The test **runner** is not a runtime dep. One `[dev]` install away. |
| **`postgres` · `postgis` · `redis-server`** | ★ **You must install these yourself.** See §3. |
| **`docker`** | ★ **Absent.** Compose files are authored blind. **No task may be marked "verified" on the basis of a compose file** (§13.4 rule 9). |
| `pnpm` | `corepack enable && corepack prepare pnpm@9 --activate` |

> ### ★ The single most important fact about this environment
>
> **`cv2`, `numpy`, `scipy`, `torch` and `osgeo` are SYSTEM site-packages.**
>
> **A plain `python -m venv` HIDES all five** — and **`osgeo` cannot be pip-installed back at all**
> (it needs `libgdal-dev` plus a version-matched `pip install GDAL==$(gdal-config --version)`; note
> `gdal-config` is **not** on this machine either).
>
> **Therefore every venv in this repo MUST be created with `--system-site-packages`.** Get this wrong
> and you delete the entire CV stack from your own environment, with no way back that does not involve
> apt.

---

## 1. The three tiers — know which one you need

| Tier | What runs | Network? | Services? |
|---|---|---|---|
| **0** | ★ `ai_engine` + `gis`: import, introspect, **and the full test suites** | **No** | **No** |
| **1** | The API process: `/health`, `/docs`, `openapi.json` | **Yes**, once, to `pip install` the web stack | **No** |
| **2** | The whole product: upload → mark → GCP → export | **Yes**, once | **Postgres+PostGIS, Redis** |

**Tier 0 works right now, on this machine, with no network and nothing installed.** That is not an
accident — it is [ADR-001](../architecture/adr/ADR-001-separate-installable-packages.md), and it is why
`ai_engine` and `gis` are separate distributions.

---

## 2. Tier 0 — `ai_engine` and `gis` (works now, offline)

```bash
cd /home/yahi/Desktop/landexplorer

# Prints the §0.1 capability table for THIS machine. Run it first, always.
python3 scripts/check_env.py
```

### Bootstrap

```bash
bash scripts/bootstrap_dev.sh
```

That script is **exact and not left to the implementer** (§14 F-63). It does:

```bash
python scripts/check_env.py                       # print the capability table FIRST

python -m venv --system-site-packages .venv       # ★ WITHOUT --system-site-packages the venv hides
                                                  #   cv2/numpy/scipy/torch/osgeo — the entire CV
                                                  #   stack — and osgeo cannot be pip-installed back.
source .venv/bin/activate

pip install -e ./ai_engine[dev] --no-deps         # ★ --no-deps or pip downloads opencv/numpy/scipy
pip install -e ./gis[dev]       --no-deps         #   from PyPI on a machine with no network guarantee

corepack enable && corepack prepare pnpm@9 --activate
```

★ **It installs NOTHING from PyPI on this machine, and succeeds with no network.** Asserted in §9.13.

### Verify

```bash
python -c "import ai_engine, gis; print(ai_engine.version(), 'ok')"

cd ai_engine && pytest      # green: no env, no network, no GPU, no weights
cd ../gis    && pytest      # green: fixture provider + committed 64×64 GeoTIFF, no network
```

> `gis`'s suite is green **with `httpx`, `redis`, `geopandas`, `fiona`, `reportlab` and `ezdxf` all
> absent** — because of the **call-time binding rule** (§11.3): *any module whose dependency is not in
> its package's base install binds that dependency INSIDE the function that uses it, never at module
> scope.* That is what makes collection succeed.

★ **In this build, the `ai_engine` suites prove the *seam*, not the pipeline.** Every extractor,
matcher and estimator raises `NotImplementedDeferred`
([ADR-015](../architecture/adr/ADR-015-defer-the-automatic-matching-engine.md)). **A green
`ai_engine` suite does not mean matching works. It means matching is correctly, honestly absent.**

---

## 3. Tier 2 — Postgres + PostGIS and Redis

**Neither is installed here. You must install them.** Debian/Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y postgresql postgresql-16-postgis-3 redis-server
sudo systemctl enable --now postgresql redis-server
```

**Adjust `postgresql-16-postgis-3` to your server's major version** (`psql --version`). ★ **PostGIS is
a real dependency, not an accelerant** ([ADR-008](../architecture/adr/ADR-008-postgis-geography-4326.md)):
without it, migration `0001` fails and readiness reports `postgres: down`.

### Create the role and database

```bash
sudo -u postgres psql <<'SQL'
CREATE ROLE landexplorer WITH LOGIN PASSWORD 'landexplorer';
CREATE DATABASE landexplorer OWNER landexplorer;
SQL

sudo -u postgres psql -d landexplorer <<'SQL'
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
SQL
```

*(Migration `0001` also enables these. Doing it as superuser first is simpler than granting the app
role superuser.)*

### Verify

```bash
psql "postgresql://landexplorer:landexplorer@localhost:5432/landexplorer" -c "SELECT postgis_version();"
redis-cli ping    # PONG
```

---

## 4. Tier 1/2 — the backend

★ **This step needs a network**, once. There is no way around it: `fastapi`, `sqlalchemy`, `pydantic`,
`celery` and `redis` are not on this machine and are not vendored.

```bash
source .venv/bin/activate          # ★ the --system-site-packages venv from §2

pip install -e ./ai_engine --no-deps
pip install -e ./gis       --no-deps
pip install -r backend/requirements.txt
pip install -r backend/requirements-dev.txt
```

> **Why `--no-deps` for the two local packages and not for `backend/requirements.txt`:** the local
> packages' deps (`opencv`, `numpy`, `scipy`) are **already here as system packages** and pip would
> re-download them. The backend's deps genuinely are not here.

### Configure

**`db` and `redis` in the defaults are COMPOSE hostnames.** On a bare host they do not resolve — this
is the one place the zero-config default is deliberately wrong for you:

```bash
export LE_DATABASE_URL='postgresql+psycopg://landexplorer:landexplorer@localhost:5432/landexplorer'
export LE_REDIS_URL='redis://localhost:6379/0'
export LE_CELERY_RESULT_BACKEND='redis://localhost:6379/1'
export LE_LOG_FORMAT=console     # readable; `json` is for an aggregator
```

> **The trade, stated:** the default optimises for the documented happy path (compose) and makes the
> bare-host failure **legible** via `/health/ready`'s per-dependency diagnosis rather than a boot
> traceback (§9.3). **You will see it as a `503` naming `postgres`, not as a crash** — which is the
> design working.

### Migrate

```bash
cd backend
alembic upgrade head
alembic heads | wc -l      # ★ must be exactly 1
```

★ **Never set `LE_DB_AUTO_MIGRATE=true` outside dev.** N replicas racing `upgrade head` yields lock
contention and partially applied schemas (ADR-011).

### Run

```bash
# API — from backend/
uvicorn app.main:app --reload --port 8000

# Worker — a second terminal, same venv, same env vars
celery -A app.tasks.celery_app worker -Q cv,io,export --concurrency=2 --loglevel=info

# Beat (optional: tile-cache GC, export TTL sweep, stale-job reaper)
celery -A app.tasks.celery_app beat --loglevel=info
```

### Verify

```bash
curl -s localhost:8000/api/v1/health | jq
curl -s 'localhost:8000/api/v1/health/ready?verbose=true' | jq
curl -s localhost:8000/api/v1/capabilities | jq
```

**Reading `/health/ready` correctly:**

| Component | `down` ⇒ |
|---|---|
| `postgres` · `redis` · `storage` | ★ **`503`** — nothing can be served correctly |
| `celery` · `imagery` · `raster` | **`200 degraded`** |
| `models` | ★ **never affects readiness** — informational only |

> ★ **`models: degraded` is EXPECTED and correct here.** There are no weights, and in this build every
> matching component is **deferred** anyway. **If missing weights made the app unready, it would never
> start on this machine.**
>
> ★ **`raster: degraded` with `backend: "gdal"` is also correct here** — rasterio is absent, GDAL 3.8.4
> substitutes. **`backend: "none"` would be a real problem**: it means `local_orthophoto` is dead,
> GeoTIFF ingest cannot populate `crs_epsg`/`bounds`/`geotransform`, and `total_ce90_m` is
> uncomputable — *all of it silently.* That is exactly why the `raster` check exists.

---

## 5. The frontend

```bash
cd frontend
corepack enable && corepack prepare pnpm@9 --activate
pnpm install                       # ★ needs a network
pnpm dev                           # http://localhost:5173 — proxies /api → localhost:8000
```

```bash
pnpm test          # vitest + RTL + MSW — ★ NO backend needed, no network
pnpm build
```

★ **The frontend test suite mocks every endpoint with MSW and needs no backend running.** That is a
direct consequence of [ADR-013](../architecture/adr/ADR-013-react-query-server-zustand-ui.md):
components never call `api/` directly, only `api/hooks/`.

---

## 6. Seed the offline demo

```bash
python scripts/make_fixtures.py      # synthetic ortho + tiles + scene. No network.
python scripts/seed_demo_data.py     # demo project with default_provider='fixture'
```

★ **Upload → mark → place GCPs → export, with the NIC unplugged.** See
[offline-mode.md](offline-mode.md).

---

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| ★ `ModuleNotFoundError: cv2` **inside the venv** | **The venv was created without `--system-site-packages`.** | `rm -rf .venv` and re-run `scripts/bootstrap_dev.sh`. Do not `pip install opencv-python` — you will get a second, conflicting copy. |
| ★ `ModuleNotFoundError: osgeo` | Same. **And it cannot be pip-installed back.** | Same fix. `osgeo` comes from the system package only. |
| `/health/ready` → 503, `postgres: down` | `LE_DATABASE_URL` still points at the compose hostname `db` | Export the `localhost` URL (§4). **This is the design working, not a bug.** |
| `pip install` hangs or fails | ★ **No network.** Tier 1/2 genuinely require one. | Tier 0 works offline. There is no offline path to `fastapi`. |
| `POST /images/{id}/match` → **501** | ★ **Expected.** Matching is DEFERRED. | Place GCPs manually: `POST /images/{id}/gcps`. See [ADR-015](../architecture/adr/ADR-015-defer-the-automatic-matching-engine.md). |
| `capabilities` shows every matcher unavailable | ★ **Expected.** Deferred + no weights. | Nothing to fix. |
| `raster: none` in `/health/ready` | Neither rasterio nor GDAL bound | On this box GDAL is present — you are probably in a venv without `--system-site-packages`. |
| `pytest: command not found` | Not a runtime dep (§0.1) | `pip install -e ./ai_engine[dev] --no-deps` |
| Celery tasks never run | No worker, or a different `LE_REDIS_URL` than the API | Start the worker with **the same env**. `/health/ready` reports `celery: degraded`. |
| `alembic heads` prints 2+ | Branched revision chain | Fix before merging. CI asserts exactly 1. |

---

## 8. What you CANNOT verify on this machine — stated honestly

| | Why |
|---|---|
| **Docker / compose** | ★ **Docker is not installed. Compose files are authored blind and are NOT verified** (§13.4 rule 9). The first CI run with Docker is the gate. **No task may claim otherwise.** |
| **GPU / CUDA paths** | `torch.cuda.is_available()` is `False`. `auto` → `cpu`, always, here. |
| **Deep model backends** | No weights, and they are **never auto-downloaded**. Also deferred. |
| **Keyed imagery providers** | No keys, no network. `is_configured()` → `False` — **registered, reported, not offered.** |
| **The automatic matching engine** | ★ **DEFERRED. It does not exist in this build** (`SCOPE.md` §1). |

**Everything else — the whole manual GCP product — runs here.**
