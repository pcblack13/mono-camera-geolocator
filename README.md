# Mono Camera Geolocator (LandExplorer)

A **ground control point (GCP) surveying desktop app**: a surveyor uploads a field
photograph (or a video frame), marks a landmark in it, clicks the same physical spot on a
satellite map, and the pair is recorded as a GCP with a real coordinate and an honest
accuracy figure. Fixed cameras get a per-pixel lookup table (LUT) so live detections land
on the map — and a drift monitor that says when the camera has moved. Runs locally and
fully offline.

One product, three names you will meet: the **folder** is `mono-camera-geolocator`, the
**code and packages** call themselves `landexplorer` / `LandExplorer`, and the **UI and
installer** say "Mono Camera Geolocator". They are the same thing.

> Installing the packaged desktop app? See [`INSTALL.md`](INSTALL.md). This file is for
> developers.

---

## Map of the repository

```
mono-camera-geolocator/
├── backend/        FastAPI API + Celery workers + SQLAlchemy/PostGIS.  Python import root: `app`
│   ├── app/          api/v1 routers → services → db/repositories → models/schemas; services/detection/
│   │                 (the owned YOLO + tracker + LUT core); vendor/ (LUT generator, geo_accuracy,
│   │                 drift monitor — vendored verbatim); tests/ (unit tests live beside the code)
│   ├── alembic/      database migrations
│   └── data/         DEV RUNTIME data (models, uploads, LUTs) — gitignored, can be large
├── gis/            Pure geospatial package `landexplorer-gis` (import root `gis`): tiles, imagery
│                   providers + offline cache, CRS, accuracy (CE90), EXIF, exports, elevation
├── ai_engine/      Pure-CV package `landexplorer-ai-engine` (import root `ai_engine`). The automatic
│                   matcher is DEFERRED: typed stubs that raise, endpoints answer 501 — see SCOPE.md
├── frontend/       React + Vite + TypeScript SPA (React Query for server state, Zustand for UI state)
├── desktop/        Electron shell + installers; bundles backend/, frontend/dist, gis/src, ai_engine/src
├── docs/           architecture/ (CONTRACT.md is law, SCOPE.md overrides it), guides/, dev-guide/, api/
├── scripts/        bootstrap_dev.sh, verify_boundaries.sh (the CI gate), check_env.py, make_fixtures.py
├── tests/          CROSS-package tests only: contract/, integration/, e2e/ (unit tests live in each package)
├── data/           Runtime data root when run from here — see data/README.md
├── run.py          Start API + worker + frontend from one terminal (stdlib only; finds the venv itself)
├── pyproject.toml  ONE ruff/black/mypy/pytest config for the whole repo — deliberately not a package
├── .importlinter   The import-boundary contracts (app → gis → ai_engine)
├── requirements.txt  Every Python dependency of the full product, in one file
├── INSTALL.md      End-user install notes for the packaged desktop app (+ "What's new")
└── RELEASE_CHECKLIST.md
```

The three Python trees are **separate installable packages** with enforced boundaries:
`app` may import `gis` and `ai_engine`; `gis` may import only `ai_engine.types` /
`ai_engine.errors`; `ai_engine` imports no web, database or geo stack at all. A violation is
a **CI failure**, not a review opinion — run `scripts/verify_boundaries.sh` before calling a
boundary change done.

## Where to start reading

1. [`docs/architecture/SCOPE.md`](docs/architecture/SCOPE.md) — what this build *is* (138 lines; overrides everything).
2. [`docs/guides/README.md`](docs/guides/README.md) — the developer guides index (quickstart, running locally, configuration, offline mode, adding a provider…).
3. [`docs/dev-guide/README.md`](docs/dev-guide/README.md) — the commands that actually get used, with the gotchas marked ★.
4. [`docs/architecture/CONTRACT.md`](docs/architecture/CONTRACT.md) — names, interfaces and layout rules. Doc precedence: `CONTRACT.md` > the numbered architecture docs > `00-overview.md`; corrections land in CONTRACT §14, never in the numbered docs.

## Running it (development)

Three processes — API, Celery worker (exports only), frontend. Either:

```bash
python3 run.py            # all three from one terminal; --only api,web / --reload / --check
```

or by hand, from `backend/` so `.env` loads (see `docs/guides/running-locally.md`):

```bash
cd backend && uvicorn app.main:app --host 127.0.0.1 --port 8000          # API  → /docs
cd backend && celery -A app.tasks.celery_app worker -Q cv,io,export,celery  # worker
cd frontend && npm run dev                                                 # http://localhost:5173
```

Needs PostgreSQL + PostGIS and Redis; `scripts/bootstrap_dev.sh` sets up the venv,
`scripts/check_env.py` tells you what is missing and how to fix it.

## Testing

| What | Command |
|---|---|
| Boundaries + grep gates (the definition of done) | `scripts/verify_boundaries.sh` |
| Backend unit tests | `cd backend && python -m pytest app/tests -q` |
| gis / ai_engine unit tests | `python -m pytest gis/src ai_engine/src -q` |
| Cross-package contract / e2e | `python -m pytest tests -q` |
| Frontend | `cd frontend && npm run typecheck && npm run test -- --run && npm run lint && npm run build` |
| Desktop installer | see `desktop/README.md` and `docs/dev-guide/desktop-and-install.md` |

## Conventions in one breath

Python 3.12, `ruff` + `black` (line length 100), `mypy`; every setting is `LE_`-prefixed
(`backend/app/core/config.py`) with a working default; wire types are `snake_case` on both
sides; **honesty is the core value** — never fabricate a coordinate, a confidence or an
accuracy; deferred features raise/501 rather than pretend. Details: `docs/guides/contributing.md`.
