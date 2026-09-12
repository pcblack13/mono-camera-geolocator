#!/bin/bash
# ★ RUN THE DESKTOP APP STRAIGHT FROM THE REPO — no installer, no apt, no sudo.
#
#   ./run-desktop.sh
#
# Everything — Python, PostgreSQL+PostGIS, Redis, every package — installs into
# ONE folder: `desktop/runtime-build/env`. The first run builds it (~1 GB
# download, 10-20 min); every run after that goes straight to the app window.
# Survey data lives in `~/.local/share/MonoCameraGeolocator/`, exactly as with
# the packaged installer, so the two are interchangeable on one machine.
#
# How: the app's MANAGED mode boots from a "resources" directory (normally the
# installed package). This script stages one out of symlinks into the checkout
# and points the app at it via LE_DESKTOP_RESOURCES — the same path
# `smoke-managed.js` proves headlessly.

set -euo pipefail
cd "$(dirname "$0")"

# ★ NEVER WITH SUDO. Root cannot attach to your desktop's display ("Authorization
#   required, but no authorization protocol specified", dead X/EGL init), and the
#   first-run database would be created in /root — invisible to your real account.
#   Nothing here needs elevation; refuse loudly instead of failing confusingly.
if [ "$(id -u)" = "0" ]; then
  echo "ERROR: do not run this with sudo. Run it as yourself:  ./run-desktop.sh" >&2
  exit 1
fi
# ★ And only from inside a desktop session — over plain SSH there is no display to
#   open a window on, and Electron dies in exactly the confusing way above.
if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
  echo "ERROR: no graphical display (DISPLAY/WAYLAND_DISPLAY unset)." >&2
  echo "Run this from a terminal INSIDE the desktop session, not over SSH." >&2
  exit 1
fi

need() { command -v "$1" >/dev/null 2>&1 || { echo "ERROR: '$1' is required — sudo apt install $2" >&2; exit 1; }; }
need curl "curl"
need tar  "tar"

# ★ Node is bootstrapped, not demanded: if the machine has no node/npm (or an old
#   one), a private copy is downloaded into runtime-build/node — same one-folder
#   principle as the runtime env. Nothing needs to be preinstalled beyond curl/tar.
NODE_MAJOR_MIN=20
node_ok() {
  command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1 &&
    [ "$(node -p 'process.versions.node.split(".")[0]')" -ge "$NODE_MAJOR_MIN" ] 2>/dev/null
}
if ! node_ok; then
  NODE_VERSION="v22.12.0"
  if [ ! -x runtime-build/node/bin/npm ]; then
    echo "== node not found — downloading a private copy into runtime-build/node =="
    mkdir -p runtime-build/node
    curl -fsSL "https://nodejs.org/dist/${NODE_VERSION}/node-${NODE_VERSION}-linux-x64.tar.gz" \
      | tar -xz -C runtime-build/node --strip-components=1
  fi
  export PATH="$PWD/runtime-build/node/bin:$PATH"
  node_ok || { echo "ERROR: the private node copy failed to run" >&2; exit 1; }
fi

if [ ! -x runtime-build/env/bin/python ]; then
  echo "== first run: building the environment into runtime-build/env (~1 GB, 10-20 min) =="
  bash runtime-build/build-runtime.sh --env-only
fi

if [ ! -f ../frontend/dist/index.html ] ||
   [ -n "$(find ../frontend/src -newer ../frontend/dist/index.html -print -quit 2>/dev/null)" ]; then
  echo "== building the frontend =="
  (cd ../frontend && npm install --no-audit --no-fund && npm run build)
fi

[ -d node_modules ] || npm install --no-audit --no-fund

# Stage the managed-mode resources dir from the checkout. `-n`: replace the
# symlink itself, never write through it into the target.
mkdir -p local-resources
ln -sfn "$PWD/runtime-build/env"          local-resources/runtime
ln -sfn "$(cd ../backend && pwd)"         local-resources/backend
ln -sfn "$(cd ../frontend && pwd)/dist"   local-resources/frontend-dist
# gis/ai_engine as SOURCE — boot.js puts these on PYTHONPATH ahead of the env's
# baked copies, so a `git pull` that changes gis needs no env rebuild.
ln -sfn "$(cd ../gis && pwd)/src"         local-resources/gis-src
ln -sfn "$(cd ../ai_engine && pwd)/src"   local-resources/ai_engine-src

# ★ Applications-menu entry, refreshed on every run so it always points at THIS
#   checkout (a moved repo self-heals on the next terminal run). After the first
#   run the app launches from the menu like any installed program.
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$APPS_DIR"
cat > "$APPS_DIR/mono-camera-geolocator-repo.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Mono Camera Geolocator
Comment=Ground control point surveying
Exec="$PWD/run-desktop.sh"
Icon=$PWD/icon.svg
Terminal=false
Categories=Science;Geography;
StartupWMClass=Electron
EOF
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS_DIR" || true

export LE_DESKTOP_RESOURCES="$PWD/local-resources"
# ★ The managed stack must never inherit a dev database/redis by accident.
unset LE_DATABASE_URL LE_REDIS_URL 2>/dev/null || true

# ★ Ubuntu ≥ 24.04 blocks Chromium's user-namespace sandbox for unpackaged apps
#   (AppArmor), and Electron then exits without a window. The installed .deb fixes
#   this with a SUID helper; running from the repo cannot, so pass --no-sandbox —
#   but ONLY when the kernel actually enforces the restriction. Read /proc
#   directly: menu launches may not have /usr/sbin (sysctl) on PATH.
SANDBOX_ARGS=()
if [ "$(cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns 2>/dev/null || echo 0)" = "1" ]; then
  echo "(this Ubuntu restricts the Chromium sandbox for unpackaged apps — using --no-sandbox)"
  SANDBOX_ARGS=(--no-sandbox)
fi

exec npm start -- "${SANDBOX_ARGS[@]}"
