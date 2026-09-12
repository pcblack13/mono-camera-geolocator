# Release checklist — Mono Camera Geolocator

Run top to bottom for every release. Written after the 1.2.x field bugs
(process leaks, >2 GiB uploads, malformed Mapbox token, Windows event-loop
crash) — each line below exists because skipping it once cost real time.

## 0. Before building (any OS)

- [ ] `git status` clean; version bumped in `desktop/package.json`
- [ ] Backend tests: `cd backend && pytest app/tests -q`
- [ ] GIS tests: `cd gis && pytest src/gis/tests -q` (especially
      `test_providers_contract.py` whenever a provider changed)
- [ ] Frontend: `cd frontend && npx vitest run && npm run build`
- [ ] Desktop smoke (Linux): `cd desktop && npm run smoke && npm run smoke:managed`

## 1. Linux build + verify

- [ ] `cd desktop && npm run dist` → `dist-installers/*.deb` + `.AppImage`
- [ ] Install the `.deb` on a clean machine/VM (or upgrade an existing install)
- [ ] First boot completes; `~/.local/share/MonoCameraGeolocator/boot.log` written
- [ ] Map draws (Mapbox). Break test A: `LE_MAPBOX_ACCESS_TOKEN=pk.pk.garbage` in
      `work/.env` → map STILL works (built-in token) + warning in the log.
      Break test B: a well-formed but fake token → red on-map banner naming the 401
- [ ] DEM: Browse-pick a **multi-GB** `.tif` → appears instantly (path route,
      no upload bar) and processes
- [ ] Video: upload a **>2 GB** video via Browse
- [ ] Live tab: Scan local devices → device chip appears → LIVE, FPS healthy →
      Capture frame lands in the capture library. Encoding should read **MJPEG**;
      a raw format (YUYV/GREY) still streams but must show the note explaining the
      frame rate — 1.2.6 warns, it does not refuse
- [ ] Live tab: unplug the device mid-stream → within ~6 s the picture is covered
      by **Device disconnected** and Capture is disabled (never a frozen frame)
- [ ] GCP tables tab: Point ID column filled for uncoded points
- [ ] Close the window, wait 5 s:
      `ps aux | grep -E 'uvicorn|celery|postgres|redis-server' | grep -v grep` → empty
- [ ] Ctrl+C test (source runs): `./run-desktop.sh`, Ctrl+C in the terminal →
      same `ps` check → empty

## 2. Windows build + verify

- [ ] Tag `win-build-v<version>` (GitHub Actions) or build per `WINDOWS.md`
- [ ] Install the Setup exe **as a normal user** — never run the app elevated
      (postgres refuses to start as Administrator)
- [ ] First boot: runtime unpack (~1 min) → the splash must pass
      "Preparing your workspace" (migrations — the 1.2.3 blocker). On failure the
      error text is selectable and the full log is at
      `%LOCALAPPDATA%\MonoCameraGeolocator\boot.log`
- [ ] No stray cmd windows while the app runs
- [ ] Map draws; DEM Browse-pick with a Windows path; video upload
- [ ] Close the app → Task Manager: no leftover `python.exe` / `postgres.exe` /
      `redis-server.exe`
- [ ] Defender note: a first boot on a slow disk can take minutes (real-time
      scanning of the unpacked runtime). Timeouts allow 90 s (postgres) / 120 s
      (API); if it still trips, launch once more before debugging.

## 3. Rollout

- [ ] Upgrade **every** 1.2.x machine — older builds leak postgres/redis each session
- [ ] Remove stray `LE_MAPBOX_ACCESS_TOKEN` lines from `<app-data>/work/.env`
      unless deliberately overriding (malformed ones are ignored automatically now)
- [ ] **Diff `<app-data>/work/.env` against `backend/.env`.** Nothing keeps them in
      sync, so the running copy silently keeps whatever it was first given — a stale
      `LE_ALLOWED_PROVIDERS` there hid Esri and Sentinel from the map settings for a
      whole release. An absent or empty line allows every provider
