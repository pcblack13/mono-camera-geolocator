# Mono Camera Geolocator — Installation & User Guide

Welcome to **Mono Camera Geolocator**, the desktop application for turning field photographs
into surveyed ground control points — with real coordinates, real elevations, and an
honest accuracy figure on every point.

This guide walks you through installing the app, explains how its database works,
and covers everything you need to know to run it with confidence.

---

## 1. What you received

Your delivery contains one (or both) of these installers for Linux (64-bit):

| File | What it is |
| --- | --- |
| `mono-camera-geolocator_<version>_amd64.deb` | The recommended installer for Ubuntu / Debian systems |
| `MonoCameraGeolocator-<version>.AppImage` | A portable single-file version — no installation, runs from anywhere |

**Everything is inside.** The app bundles its own Python runtime, its own
**PostgreSQL + PostGIS database engine**, its own Redis, and all processing
libraries. You do **not** need to install a database, Python, or anything else.
A freshly installed computer is enough.

---

## 2. System requirements

- **OS:** Ubuntu 22.04 / 24.04 or a comparable 64-bit Linux (Debian, Mint, …)
- **Disk:** ~1.5 GB free for the app and its runtime, plus space for your imagery
  and elevation files
- **Memory:** 8 GB RAM recommended
- **Network:** *optional.* The app runs fully offline; internet is only needed for
  online satellite basemaps (offline imagery is supported — see §8)

---

## 3. Installing

### Option A — the `.deb` package (recommended)

1. Open a terminal in the folder containing the file (or use its full path).
2. Run:
   ```bash
   sudo apt install ./mono-camera-geolocator_<version>_amd64.deb
   ```
   > The `./` (or a full path) matters — apt needs to see it as a file, not a
   > package name. If you see *"Unsupported file … given on commandline"*, the path
   > is wrong.
3. That's it. **Mono Camera Geolocator** now appears in your applications menu, and the
   command `mono-camera-geolocator` works from any terminal.

*(A note line about "Download is performed unsandboxed as root" may appear — it is
a harmless apt message about reading a file from your home folder.)*

### Option B — the AppImage (no installation)

1. Make it executable, then run it:
   ```bash
   chmod +x MonoCameraGeolocator-<version>.AppImage
   ./MonoCameraGeolocator-<version>.AppImage
   ```
2. On Ubuntu 24.04 and newer, if the app exits without showing a window, launch it
   as:
   ```bash
   ./MonoCameraGeolocator-<version>.AppImage --no-sandbox
   ```
   (Ubuntu restricts a sandbox feature AppImages rely on. The `.deb` install does
   not have this limitation.)

---

## 4. First launch — what happens and why

Start **Mono Camera Geolocator** from your applications menu. The **first** launch performs a
one-time setup, narrated in a small status window:

1. **Unpacking the runtime** (~1 minute) — the bundled Python/PostGIS runtime is
   extracted to your user data folder.
2. **Creating your database** — a private PostgreSQL cluster is initialised and the
   database schema is created automatically.
3. **Starting services** — the database, the background worker, and the app server
   start; when everything reports healthy, the main window opens.

Every launch after the first takes only a few seconds.

---

## 5. How the database works (important to understand)

Mono Camera Geolocator stores your projects, photographs, ground control points and their
accuracy figures in a **real PostgreSQL + PostGIS database** — the same technology
professional GIS servers use. The difference: **the app owns it entirely.**

- **Private:** the database is created by the app, for the app. It listens only on
  your own computer (`127.0.0.1`, a port chosen automatically) and is never
  reachable from the network.
- **Automatic:** it starts when the app starts and shuts down cleanly when you
  close the window. There is nothing to configure, no password to manage, no
  service to install.
- **Self-repairing:** if the app is force-killed or the computer loses power, the
  next launch detects the leftover database process and recovers it safely.
- **Where it lives:** everything — database, uploaded photographs, elevation
  models, exports — is stored under one folder in your home directory:

  ```
  ~/.local/share/MonoCameraGeolocator/
  ├── runtime/     the bundled engine (recreated automatically if deleted)
  ├── pgdata/      ★ your database — all projects and GCPs
  └── work/data/   ★ your files — photographs, DEMs, exports
  ```

  The two ★ folders are **your data**. The app never stores anything outside this
  folder (plus a small settings folder at `~/.config/MonoCameraGeolocator`).

---

## 6. Daily use

- **Launch:** applications menu → Mono Camera Geolocator (or `mono-camera-geolocator`).
- **Close:** just close the window — the database and worker shut down cleanly
  with it.
- **One instance:** launching the app twice simply focuses the window that is
  already open.
- **In-app guidance:** the Home page gives a tour of the workflow (create a
  project → set up each photograph's camera → attach a DEM → locate points →
  export), and a welcome dialog greets each session.

---

## 7. Backing up, moving, and resetting your data

- **Backup:** close the app, then copy the whole folder
  `~/.local/share/MonoCameraGeolocator/` somewhere safe. That single folder *is* your
  complete state.
- **Restore / move to a new computer:** install Mono Camera Geolocator there, run it once,
  close it, replace `~/.local/share/MonoCameraGeolocator/` with your backup, launch.
- **Factory reset:** close the app and delete `~/.local/share/MonoCameraGeolocator/`.
  The next launch starts from scratch (first-run setup runs again).
- Always **close the app before** copying or deleting the folder — a live database
  should not be copied mid-write.

---

## 8. Satellite imagery & offline use

- **Esri World Imagery** works out of the box, no key needed.
- **Google Map Tiles** and **Sentinel/Copernicus** require your own API
  credentials. To add them to the installed app, create the file
  `~/.local/share/MonoCameraGeolocator/work/.env` containing, for example:
  ```
  LE_GOOGLE_MAPS_STATIC_KEY=your-key-here
  LE_GOOGLE_TOS_ACKNOWLEDGED=true
  ```
  then restart the app. The provider appears in the map's basemap selector once
  the key is picked up. (Sentinel uses `LE_COPERNICUS_CLIENT_ID`,
  `LE_COPERNICUS_CLIENT_SECRET`, `LE_COPERNICUS_INSTANCE_ID`.)
  > Requires version **1.1.1 or later** — 1.1.0 ignored this file; update the
  > app (§9) if the provider does not appear after a restart.
- **About the Google key:** it is a Google Maps Platform key with the **Map Tiles
  API** enabled on it (and listed in the key's API restrictions) in the Google
  Cloud console. `LE_GOOGLE_TOS_ACKNOWLEDGED=true` is your confirmation that
  *your* agreement with Google permits this use — the app will not enable the
  provider without it.
- **Fully offline:** you can cache map tiles while online (draw an area on the 2D
  map), or work with your own georeferenced orthophotos and DEMs. Elevation always
  comes from the DEM *you* attach to a project — never from an online guess.

---

## 9. Updating the app

Install the new version over the old one:

```bash
sudo apt install ./mono-camera-geolocator_<new-version>_amd64.deb
```

**Your data is untouched by updates** — it lives in your home folder, not in the
application directory. Any database schema changes are applied automatically the
next time the app starts.

---

## 10. Uninstalling

```bash
sudo apt remove mono-camera-geolocator
```

This removes the application only. Your data remains in
`~/.local/share/MonoCameraGeolocator/` — delete that folder too if you want everything
gone (see §7 about backing it up first).

---

## 11. Troubleshooting

| Symptom | Cause & fix |
| --- | --- |
| *"Unsupported file … given on commandline"* during install | The path to the `.deb` is wrong. Use `./file.deb` from its folder, or the full path. |
| AppImage exits instantly with no window (Ubuntu ≥ 24.04) | Launch with `--no-sandbox`, or use the `.deb` instead. |
| *"The SUID sandbox helper binary was found, but is not configured correctly"* | Run `sudo chmod 4755 /opt/MonoCameraGeolocator/chrome-sandbox` once, then launch again. (Fixed automatically by installers dated after 2026-07-30.) |
| App exits instantly with no window (any install) | A previous instance may have crashed and left its lock behind. Run: `rm ~/.config/MonoCameraGeolocator/Singleton*` and launch again. |
| The app looks like an older version after an upgrade | Versions before 1.1.3 could keep showing a cached copy of the previous version. Close the app, run `rm -rf ~/.config/MonoCameraGeolocator`, launch again (your projects are untouched — they live in `~/.local/share`). From 1.1.3 on this cannot happen. |
| First launch seems stuck | The status window narrates each step; the runtime unpack can take a minute or two on slow disks. If an error is shown, it states the reason — leave the window open and read it. |
| "Exports are unavailable" | The background worker stopped; everything else keeps working. Restart the app to bring it back. |
| Where do I report a problem? | Note the message in the status window (or any red error text in the app — it includes a request ID) and contact your vendor: **mohammad@smartech-lb.net**. |

---

## 12. Privacy

All of your data — photographs, coordinates, elevation models, exports — is stored
and processed **locally on your computer**. The application makes no network
connections except to the satellite imagery providers you choose to use.
