# Desktop app, packaging & install

```bash
cd ~/Desktop/GEO-1/tools/mono-camera-geolocator/desktop
```

---

## Run from source

```bash
./run-desktop.sh
```

Boots the full managed stack (bundled PostgreSQL, Redis, API, worker) against
your **source tree** — symlinking `frontend/dist`, `gis/src` and `ai_engine/src`
into `local-resources/` so a `git pull` needs no runtime rebuild.

Two things it does that surprise people:

1. It uses the **same data directory** as the installed app
   (`~/.local/share/MonoCameraGeolocator/`). Source runs and installed runs share
   one database.
2. It **writes an applications-menu entry** on every run:
   `~/.local/share/applications/mono-camera-geolocator-repo.desktop`, pointing at
   this checkout. That is why the launcher can show two identical
   "Mono Camera Geolocator" icons — one is the installed package, one is your
   checkout. See "Launcher entries" below.

---

## Build installers

```bash
npm run dist        # Linux: .AppImage AND .deb
npm run dist:win    # Windows: NSIS Setup .exe (normally done by CI instead)
```

Output goes to `desktop/dist-installers/`. Artifact names come from
`package.json` → `build.deb.artifactName` etc.:

| Target | File |
|---|---|
| deb | `mono-camera-geolocator_<version>_amd64.deb` |
| AppImage | `MonoCameraGeolocator-<version>.AppImage` |
| Windows | `MonoCameraGeolocator-Setup-<version>.exe` |

**Build the frontend first** — the packager copies `../frontend/dist` verbatim
and will happily ship a stale UI:

```bash
cd ../frontend && npm run build && cd ../desktop && npm run dist
```

`npm run dist` also needs `runtime-build/runtime.tar.gz` to exist (~520 MB). If
it is missing, build it with `runtime-build/build-runtime.sh`.

---

## Boot smokes

★ On a machine without `backend/venv` (this one, since 2026-09-01), point the
smoke at the packaged runtime — and `smoke:managed` needs the tarball to exist:

```bash
# pack the existing env once (~1 min; verifies completeness itself)
cd runtime-build && ./build-runtime.sh && cd ..

LE_DESKTOP_PYTHON=$PWD/runtime-build/env/bin/python npm run smoke   # needs a dev PG on 5432
npm run smoke:managed                                               # self-contained — the real gate
```

Plain `smoke` boots against a dev PostgreSQL on 5432; a machine without one
fails there by design — `smoke:managed` is the gate that matches what ships.


```bash
npm run smoke            # API against the dev database
npm run smoke:managed    # the full bundled stack, end to end
```

See `tests-and-builds.md` for what good output looks like.

---

## Install / upgrade the .deb

```bash
sudo apt install ~/Desktop/GEO-1/tools/mono-camera-geolocator/desktop/dist-installers/mono-camera-geolocator_1.2.6_amd64.deb
```

Use `apt install ./file.deb` (with a path), not `dpkg -i` — apt resolves
dependencies, dpkg does not.

Confirm the installed version:

```bash
dpkg -l | grep mono-camera-geolocator
```

You want `ii  mono-camera-geolocator  1.2.6  amd64`.

**apt only ever keeps ONE version installed.** Installing 1.2.6 replaces 1.2.5
in place — there is no "old version" left behind to uninstall. If you are
hunting for old versions, you are looking for stale *installer files*, not
installed packages.

### Harmless warning you can ignore

```
N: Download is performed unsandboxed as root as file '...' couldn't be
   accessed by user '_apt'. - pkgAcquire::Run (13: Permission denied)
```

apt's unprivileged `_apt` user cannot read files under your home directory, so
it falls back to fetching as root. The install still succeeds. Verify with
`dpkg -l` rather than worrying about this line.

---

## ★ The process-leak check — run it after every install

Older 1.2.x builds leaked background processes every session. Close the app,
wait ~5 seconds, then:

```bash
ps aux | grep -E 'uvicorn|celery|MonoCameraGeolocator' | grep -v grep
ss -ltnp 2>/dev/null | grep -E '15432|16379|8123'
```

**Empty output from both is a pass.**

> ### ★ Do not grep for bare `postgres` and `redis-server`
>
> If you have a system PostgreSQL or Redis installed — most dev machines do —
> a broad grep matches those and looks alarming while being completely fine:
>
> ```
> redis     1583  /usr/bin/redis-server 127.0.0.1:6379
> postgres  1721  /usr/lib/postgresql/16/bin/postgres -D /var/lib/postgresql/16/main
> postgres  1728  postgres: 16/main: checkpointer
> ```
>
> Four tells that these are **system services, not app leaks**:
>
> | Tell | System service | Leaked app process |
> |---|---|---|
> | Start time | days ago | today, when you ran the app |
> | Owner | `postgres` / `redis` | your user |
> | Path | `/usr/lib/postgresql/...`, `/usr/bin/redis-server` | the app's bundled runtime |
> | Port | 5432 / 6379 | **15432 / 16379** |
>
> The decisive signal is `uvicorn` and `celery`: those are the app's own
> processes and nothing else on a normal machine runs them. If neither appears,
> the app shut down cleanly.

Also do the Ctrl+C variant for source runs:

```bash
./run-desktop.sh
# Ctrl+C in the terminal, then the same ps check
```

---

## Launcher entries (.desktop files)

Two entries can legitimately exist, and by default they have **identical
names**, which makes them impossible to tell apart in the menu:

| File | Launches | Created by |
|---|---|---|
| `/usr/share/applications/mono-camera-geolocator.desktop` | `/opt/MonoCameraGeolocator/mono-camera-geolocator` | the `.deb` (dpkg-owned) |
| `~/.local/share/applications/mono-camera-geolocator-repo.desktop` | `<checkout>/desktop/run-desktop.sh` | `run-desktop.sh`, every run |

Find every entry that mentions the app:

```bash
find / -xdev -name "*.desktop" 2>/dev/null \
  | xargs grep -liE "mono.?camera|landexplorer" 2>/dev/null
```

> Watch your regex. `mono-?camera` matches `monocamera` and `mono-camera` but
> **not** `Mono Camera` with a space — which is exactly what `Name=` contains.
> Use `mono.?camera` as above.

Who owns a given entry:

```bash
dpkg -S /usr/share/applications/mono-camera-geolocator.desktop
```

- names a package → remove the package, not the file
- *"no path found matching"* → orphan, safe to `sudo rm`
- under `~/.local/share/applications/` → yours, `rm` freely

Remove the source-checkout entry:

```bash
rm -v ~/.local/share/applications/mono-camera-geolocator-repo.desktop
update-desktop-database ~/.local/share/applications 2>/dev/null
```

It comes back the next time you run `./run-desktop.sh` — that block is near the
end of the script if you want it gone permanently.

Refresh the menu after any change:

```bash
sudo update-desktop-database /usr/share/applications
update-desktop-database ~/.local/share/applications 2>/dev/null
```

---

## Reclaiming disk space

Old installers are large — roughly 1.2 GB per release (566 MB deb + 600 MB
AppImage).

```bash
cd ~/Desktop/GEO-1/tools/mono-camera-geolocator/desktop/dist-installers
ls -lh                                    # look first

rm -v mono-camera-geolocator_1.2.5_amd64.deb MonoCameraGeolocator-1.2.5.AppImage
```

Name the files explicitly. A glob like `rm *1.2.5*` works today but will delete
the wrong thing the moment you reuse it after a version bump.

Find strays elsewhere (Desktop, Downloads):

```bash
find ~ -maxdepth 3 \( -iname "MonoCameraGeolocator*.AppImage" -o -iname "mono-camera-geolocator_*.deb" \) 2>/dev/null | xargs ls -lh
```

Read that list and delete by name. Do **not** pipe it into `rm` — it will match
the current release you just built.

### ⚠ Never delete this

```
~/.local/share/MonoCameraGeolocator/
```

That is not a version — it is your data. It holds `pgdata` (the bundled
PostgreSQL cluster with every project, image and GCP), `work/.env`, and the DEM
library. Upgrades deliberately preserve it. Deleting it destroys your work and
frees you of nothing.

---

## Logs

```bash
# Linux
cat ~/.local/share/MonoCameraGeolocator/boot.log

# Windows
# %LOCALAPPDATA%\MonoCameraGeolocator\boot.log
```

First place to look when the app **will not start**. When it IS running, start
with the in-app log monitor instead — `/status` in the app, or
`curl -s http://127.0.0.1:8123/api/v1/health/logs?level=error` — see
`troubleshooting.md`.

---

## A second, private API against the same data (2026-09-01)

Sometimes you need to exercise a backend change while the user's app keeps
running on 8123. The packaged runtime can serve a second instance on another
port, against the **same** bundled database, with your source edits live
(the `local-resources/*` symlinks point into the checkout):

```bash
# copy the env the running stack actually uses (from the worker process)
pid=$(pgrep -f "[c]elery" | head -1)
tr '\0' '\n' < /proc/$pid/environ | grep -E "^LE_|^PYTHONPATH"

# then, with those LE_* vars exported and LE_SERVE_FRONTEND_DIR unset:
cd ~/.local/share/MonoCameraGeolocator/work
~/Desktop/GEO-1/tools/mono-camera-geolocator/desktop/runtime-build/env/bin/python \
  -m app.serve --host 127.0.0.1 --port 8124
```

Point a Vite dev server at it (`VITE_PROXY_TARGET=http://localhost:8124`) and
you have the full stack twice, colliding nowhere.

★ Stop it by its **listening socket**, never `pkill -f` (a pattern that also
appears in your own shell command kills the shell — exit 144, twice now):

```bash
pid=$(ss -ltnp "sport = :8124" | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2)
kill $pid
```
