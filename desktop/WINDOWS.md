# Building the Windows installer

The Windows installer must be built **on a Windows machine** (conda environments
and executables are per-OS). One-time + per-release steps, in PowerShell:

## Prerequisites (once)

- Windows 10 1803+ (64-bit)
- Node.js 20+ — https://nodejs.org

## Build

```powershell
cd GEO-1\tools\mono-camera-geolocator

# 1. frontend
cd frontend
npm install
npm run build

# 2. Windows runtime (first time ~15 min: python + postgres/postgis + redis port)
cd ..\desktop
powershell -ExecutionPolicy Bypass -File runtime-build\build-runtime.ps1

# 3. installer
npm install
npm run dist:win
```

Output: `dist-installers\MonoCameraGeolocator-Setup-<version>.exe` (NSIS,
per-user, no admin needed). App data lands in
`%LOCALAPPDATA%\MonoCameraGeolocator`; imagery keys (optional — Mapbox is built
in) go in `%LOCALAPPDATA%\MonoCameraGeolocator\work\.env`.

## Platform notes (why things are the way they are)

- **Redis**: conda-forge has no win-64 redis. The runtime script downloads a
  **pinned** community port (tporadowski/redis 5.0.14.1) into
  `runtime-build\redis-win`, shipped as `resources\redis-win` — `runtime.js`
  starts it from there on Windows. Celery runs with the `threads` pool
  (prefork does not exist on Windows).
- **PostgreSQL + PostGIS**: conda-forge has no win-64 **postgis** either, so the
  runtime script downloads **pinned** official builds — EDB's PostgreSQL 16
  binaries zip plus the PostGIS project's matching pg16 bundle — and merges
  them into the env's `Library\` tree (where `runtime.js` already looks).
  TCP-only on loopback (Windows has no Unix sockets) — same trust-auth, same
  random free port.
- **Nobody builds this by hand anymore**: the `windows-installer` GitHub
  Actions workflow runs all of the above on a clean Windows runner and attaches
  the Setup exe to the release. Trigger: push a `win-build-v<version>` tag, or
  run it from the Actions tab. The steps below remain for local debugging only.
- **Do not reuse a Linux `runtime.tar.gz`** on Windows or vice versa: the
  tarball built on each OS is for that OS. `npm run dist` (Linux) and
  `npm run dist:win` (Windows) each expect their own runtime build to have run
  on that machine.
