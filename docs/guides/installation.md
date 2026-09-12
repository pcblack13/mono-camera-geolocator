# Installation

**Two supported paths.** Pick the one that matches your machine.

| Path | Use when | Guide |
|---|---|---|
| **Docker Compose** | You have Docker. **The documented happy path.** | §1 below |
| **Bare host** | ★ **You are on the dev machine — Docker is NOT installed here** | ★ **[running-locally.md](running-locally.md)** |

---

## 0. Prerequisites

| Path | Needs |
|---|---|
| **Compose** | Docker + Docker Compose v2. That is all. |
| **Bare host** | Python **3.12** · node **20** + npm · PostgreSQL **14+** with **PostGIS 3** · Redis **6+** · **system GDAL** (`libgdal-dev` + python bindings) |

★ **Docker is not installed on this machine.** Compose files are **authored blind** and are **NOT
verified** (`CONTRACT.md` §13.4 rule 9): *"No task may be marked verified on the basis of a compose
file."* **The first CI run with Docker is the gate.** §1 is written to spec; if it does not work, that
is exactly what rule 9 predicted.

---

## 1. Docker Compose

```bash
git clone <repo> landexplorer && cd landexplorer
docker compose -f infra/compose/docker-compose.yml up
```

> ### ★ That is the whole thing. **No `.env` needed. Zero required variables.**
>
> **L10** — every setting has a working default; `Settings()` with an empty environment never raises.
> **L2** — the default imagery provider is **keyless** (`esri_world_imagery`), so you get a working
> satellite view with no API keys at all.

| | |
|---|---|
| Web UI | http://localhost:8080 (`LE_WEB_PORT`) |
| API | http://localhost:8000/api/v1 |
| Docs | http://localhost:8000/docs |

```bash
curl -s localhost:8000/api/v1/health | jq
curl -s 'localhost:8000/api/v1/health/ready?verbose=true' | jq
```

### Compose files

| File | Purpose |
|---|---|
| `docker-compose.yml` | ★ **BASE — must work with an EMPTY `.env`** (L2) |
| `docker-compose.dev.yml` | Hot reload, bind mounts, exposed ports, **`LE_DB_AUTO_MIGRATE=true`** |
| `docker-compose.prod.yml` | Replicas, healthchecks, restart policies |
| `docker-compose.test.yml` | Ephemeral pg+redis for CI |

```bash
docker compose -f infra/compose/docker-compose.yml -f infra/compose/docker-compose.dev.yml up
```

### Migrations

`compose.dev` sets `LE_DB_AUTO_MIGRATE=true`. ★ **Production leaves it `false`** and migrates as a
deliberate, reviewable step — **N replicas racing `alembic upgrade head` yields lock contention and
partially applied schemas** (ADR-011):

```bash
make migrate     # or: docker compose run --rm api alembic upgrade head
```

### ★ The backend image needs GDAL, and this is not optional

`infra/docker/backend.Dockerfile` **MUST**:

1. `apt-get install -y libgdal-dev gdal-bin`
2. install a **version-matched** binding: `pip install GDAL==$(gdal-config --version)`
3. ★ **run `scripts/check_env.py` at build time with its output asserted**

> **Why this is a build-time assertion rather than a runtime hope.** GDAL's Python bindings are **not
> pip-installable from a plain wheel**. An image built without them ships with **no raster backend**,
> and every consequence is **silent**: `local_orthophoto` is dead · GeoTIFF ingest cannot populate
> `crs_epsg`/`bounds`/`geotransform`, so `ck_images_geotiff_complete` **rejects the row** ·
> `gis/accuracy.py` cannot reach UTM, so **`total_ce90_m` — mandatory on every GCP — is
> uncomputable.** **An image that lost its raster backend must fail the *build*, not a surveyor's
> export.** `/health/ready`'s `raster` check and `GET /capabilities` surface the same probe at runtime.

**On the dev box `pyproj`/`rasterio` are genuinely optional** (system GDAL substitutes). **In the image
nothing substitutes**, which is why §9.14 pins them there and marks them optional here.

---

## 2. Bare host

★ **[running-locally.md](running-locally.md)** — the honest path, verified on this machine, including
what needs a network and what you must install yourself.

**In one paragraph:** `ai_engine` and `gis` install and test **right now, offline**, via
`scripts/bootstrap_dev.sh` (`python -m venv --system-site-packages` + `pip install -e … --no-deps`,
which installs **nothing from PyPI**). The **backend** needs a network once, to `pip install` the web
stack. **Postgres+PostGIS and Redis you install yourself.**

---

## 3. Verify the install

```bash
python3 scripts/check_env.py      # ★ prints the §0.1 capability table for YOUR machine
```

```bash
curl -s localhost:8000/api/v1/capabilities | jq
```

**Expected on a fresh machine, and all of it correct:**

| Report | Why it is right |
|---|---|
| `models: degraded` | ★ No weights — **and matching is DEFERRED anyway.** **Never affects readiness.** *If missing weights made the app unready, it would never start here.* |
| `raster: gdal` | rasterio absent, **GDAL 3.8.4 substitutes**. ★ `none` would be a real problem. |
| `imagery: esri_world_imagery` | ★ **Keyless. This is L2.** |
| Keyed providers `configured: false` | ★ **Registered, reported, not offered.** Not a crash. |
| `shapefile`/`pdf` possibly absent | Optional deps **dropped from `/capabilities`, not crashed on**. CSV/GeoJSON/KML/KMZ **can never degrade**. |

---

## 4. Seed the offline demo

```bash
python scripts/make_fixtures.py     # synthetic ortho + tiles + scene. No network.
python scripts/seed_demo_data.py    # demo project with default_provider='fixture'
make seed && make up                # ★ upload → mark → GCP → export, with the NIC UNPLUGGED
```

See [offline-mode.md](offline-mode.md).

---

## 5. ★ Before you deploy this for real

- [ ] Read [`docs/legal/imagery-terms.md`](../legal/imagery-terms.md) **§4, the operator checklist**.
      **The keyless Esri default is a bootstrapping decision, not a licensing one. Reachable ≠
      licensed.**
- [ ] Set `LE_SECRET_KEY`, `POSTGRES_PASSWORD`, and `LE_AUTH_MODE` — ★ with auth off,
      `gcps.adjusted_by = 'anonymous'` and **the audit trail attributes nothing.**
- [ ] `LE_DB_AUTO_MIGRATE=false`, `LE_IMAGERY_STRICT=true`,
      `LE_IMAGERY_TILE_CACHE_BACKEND=redis`, `LE_IMAGERY_USER_AGENT=<a real contact>`.
- [ ] Understand what you are shipping: ★ **[`TRACEABILITY.md`](../architecture/TRACEABILITY.md)** —
      **the automatic matching engine is DEFERRED.**

See [configuration.md §13](configuration.md#13-recipes) for the full production recipe.
