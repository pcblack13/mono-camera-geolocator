# Mono Camera Geolocator — Desktop

The whole app as a desktop application: an Electron window over the **local** API,
which itself serves the built frontend — one origin, no browser, no CORS.

> Naming: the product's display name is **Mono Camera Geolocator**; internal
> identifiers (env vars `LE_*`, the `landexplorer` database role, code paths) keep
> the original codename on purpose — renaming them buys nothing and breaks data.

## Dev mode — `npm start`

Runs against the repo's own venv and your system PostgreSQL/Redis:

1. **Migrations** — `alembic upgrade head` against the configured database.
2. **The API** starts on the first free port at/after `8123` (never fighting a dev
   server), with `LE_SERVE_FRONTEND_DIR` pointed at `frontend/dist` so it serves the
   SPA: `/` and every deep link fall back to `index.html`; `/api/*` stays JSON.
3. **The Celery worker** starts (exports + video previews + thumbnails). It dying —
   or Redis being absent — degrades those features only. `LE_DESKTOP_WORKER=0`
   skips it.
4. A branded splash narrates boot in user language (the verbatim technical stages
   go to stdout); once `/api/v1/health/ready` answers 200 the app window opens.
5. **Closing the window stops everything** — API and worker are killed (TERM, then
   KILL after 5 s) on every exit path. Single-instance: launching twice focuses the
   existing window.

Prerequisites: `backend/venv` installed, `frontend/dist` built, PostgreSQL+PostGIS
and Redis running (see RUNNING.md).

| Env | Meaning |
| --- | --- |
| `LE_DESKTOP_PORT` | Preferred port (default 8123; scans upward if taken). |
| `LE_DESKTOP_PYTHON` | Interpreter instead of `backend/venv/bin/python`. |
| `LE_DESKTOP_WORKER=0` | Don't start the Celery worker. |
| `LE_DESKTOP_APPDATA` | Override the managed-mode app-data directory. |

## Install on a teammate's machine

Nothing needs to be preinstalled — the script downloads everything it needs
(including its own Node.js) into the repo folder.

```bash
# 1. clone the repo
git clone git@github.com:Doctor13-st/GEO-1.git
cd GEO-1/tools/mono-camera-geolocator/desktop

# 2. run — the first time builds everything (python, database, all packages)
#    into ONE folder (runtime-build/env, ~20 min). After that it opens in seconds.
./run-desktop.sh

# 3. imagery keys — same lines as on the main machine
mkdir -p ~/.local/share/MonoCameraGeolocator/work
nano ~/.local/share/MonoCameraGeolocator/work/.env
```

`.env` contents:

```
LE_MAPBOX_ACCESS_TOKEN=pk.your-token
LE_ALLOWED_PROVIDERS=local_orthophoto,mapbox_satellite,google_map_tiles,esri_world_imagery
LE_IMAGERY_FALLBACK_CHAIN=local_orthophoto,mapbox_satellite,esri_world_imagery
LE_GOOGLE_MAPS_STATIC_KEY=your-google-key
LE_GOOGLE_TOS_ACKNOWLEDGED=true
```

After the first run the app is in the **applications menu** (search "Mono Camera
Geolocator"). To update: `git pull`, then `./run-desktop.sh` once.
Don't release any new release until you have the accept from me
(`./install-from-source.sh` still exists for building the standalone `.deb`/`.AppImage` installers for customers.)

## Packaged installers (blank-machine mode) — `npm run dist`

Builds `dist-installers/MonoCameraGeolocator-<v>.AppImage` and
`mono-camera-geolocator_<v>_amd64.deb`. Both are **fully self-contained**: a
conda-based runtime (Python 3.12, PostgreSQL 16 + PostGIS, Redis, every backend
wheel incl. OpenCV/rasterio/pyproj **and a static ffmpeg** for HEVC video
previews) plus the backend source and built frontend ride inside. The target
machine needs nothing installed.

On first launch the app unpacks the runtime into
`~/.local/share/MonoCameraGeolocator/` (a minute or so, once), `initdb`s a
**private PostgreSQL cluster** (loopback-only, random free port, sockets in a
short `/tmp` path), starts its own Redis, runs migrations, and opens. All survey
data lives under that app-data directory; deleting it resets the app completely.

Hard-won platform facts, encoded in the build — do not "simplify" them away:

- **The install dir is spaceless** (`/opt/MonoCameraGeolocator`): Chromium's
  zygote launcher execvp's its own path split on spaces — `/opt/Mono Camera
  Geolocator` died at launch with `failed to execvp: /opt/Mono`. The human name
  lives only in the `.desktop` entry (`build.linux.desktop.Name`).
- **`build.productName` overrides top-level `productName`** — both are set.
- **The runtime self-repairs after a move.** conda-unpack bakes absolute paths at
  relocation time, so `.unpacked-ok` stores *where* the unpack happened; a
  mismatch (the LandExplorer→MonoCameraGeolocator data migration, a copied home,
  a changed `XDG_DATA_HOME`) wipes and re-unpacks (~1 min). `pgdata` and uploads
  live outside the runtime and are never touched. Legacy
  `~/.local/share/LandExplorer` data is migrated by an atomic rename on first
  launch.
- **The deb postinst sets the SUID sandbox unconditionally**: electron-builder's
  default tests user-namespaces *as root*, which Ubuntu ≥ 24.04 exempts from its
  restriction — so it skipped the SUID bit and the app crashed for normal users.
  If the **AppImage** exits without a window on Ubuntu ≥ 24.04, launch it with
  `--no-sandbox` (the deb does not have this problem).
- Stranded single-instance lock (crash mid-boot): delete
  `~/.config/MonoCameraGeolocator/Singleton*`. ★ The Electron profile dir is
  `productName` VERBATIM — capital letters, no dashes. The lowercase package name
  appeared in these docs once and sent a support session deleting the wrong,
  nonexistent folder while the real poisoned cache survived.
- **Imagery API keys (Google Map Tiles, Sentinel, …) come from `<app-data>/work/.env`**,
  because the packaged `backend/` is a read-only installer image and the API runs
  with cwd = `work/`. The backend mirrors the **cwd** `.env` into `os.environ`
  (`app/core/config.py::_mirror_env_file_into_environ`) — that is what lets the
  gis providers, which read `os.environ` directly, see keys on a packaged
  machine. Installers ≤ 1.1.0 mirrored only the source-anchored `backend/.env`
  and silently ignored `work/.env`; do not reintroduce that.

Rebuilding after changes: `frontend && npm run build`, re-run
`runtime-build/build-runtime.sh` only if *Python dependencies* changed, then
`npm run dist`.

Install/upgrade on a machine:

```bash
sudo apt install ./mono-camera-geolocator_<v>_amd64.deb
# upgrading FROM the old package name (landexplorer-desktop ≤ 1.0.0):
sudo apt remove landexplorer-desktop   # first; data in ~/.local/share survives
```

## Verifying headlessly

- `npm run smoke` — dev-mode boot: health 200, SPA served, deep links fall back,
  unknown `/api/*` still fails as JSON.
- `npm run smoke:managed` — stages the installer's exact payload, unpacks the
  runtime into a scratch app-data, boots the private postgres/redis/API, and
  creates a real project through the bundled PostGIS.
