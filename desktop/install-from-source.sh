#!/bin/bash
# ★ ONE-COMMAND INSTALL FROM A REPO CHECKOUT.
#
#   ./desktop/install-from-source.sh            build everything, then sudo-install the .deb
#   ./desktop/install-from-source.sh --build-only   build everything, print the install command
#
# Why this exists: the finished installers are 400+ MB and can never live in git
# (GitHub hard-rejects files over 100 MB), so a teammate with only the repo builds
# them locally. Everything needed is in the tree; this script is just the order:
#
#   1. frontend  → npm install && npm run build                 (~1 min)
#   2. runtime   → runtime-build/build-runtime.sh, FIRST RUN ONLY — downloads the
#                  self-contained python/postgres/redis stack   (~1 GB, 10-20 min)
#   3. installer → npm run dist (electron-builder)              (~5-10 min)
#   4. install   → sudo apt install ./dist-installers/<version>.deb
#
# Re-runs are fast: step 2 is skipped while runtime.tar.gz exists (delete it only
# when PYTHON dependencies change), and steps 1/3 rebuild only what npm must.
#
# Requirements on the machine: Node.js 20+, npm, curl, tar, and a Debian-based
# system for step 4 (any other distro: use --build-only and run the AppImage from
# dist-installers/ instead).

set -euo pipefail
cd "$(dirname "$0")"

BUILD_ONLY=0
[ "${1:-}" = "--build-only" ] && BUILD_ONLY=1

need() { command -v "$1" >/dev/null 2>&1 || { echo "ERROR: '$1' is required. $2" >&2; exit 1; }; }
need node "Install Node.js 20+ (e.g. sudo apt install nodejs npm)"
need npm  "Install Node.js 20+ (e.g. sudo apt install nodejs npm)"
need curl "sudo apt install curl"
need tar  "sudo apt install tar"

echo "== 1/4 frontend =="
(cd ../frontend && npm install --no-audit --no-fund && npm run build)

echo "== 2/4 bundled runtime =="
if [ -f runtime-build/runtime.tar.gz ]; then
  echo "runtime.tar.gz already built — skipping (delete it to force a rebuild)"
else
  echo "first build: downloading the self-contained runtime (~1 GB, 10-20 min)…"
  bash runtime-build/build-runtime.sh
fi

echo "== 3/4 installers =="
npm install --no-audit --no-fund
npm run dist
VERSION=$(node -p "require('./package.json').version")
DEB="dist-installers/mono-camera-geolocator_${VERSION}_amd64.deb"
[ -f "$DEB" ] || { echo "ERROR: expected $DEB was not produced" >&2; exit 1; }
ls -lh "$DEB"

if [ "$BUILD_ONLY" = 1 ]; then
  echo
  echo "Build complete. Install with:"
  echo "  sudo apt install \"./desktop/$DEB\""
  exit 0
fi

echo "== 4/4 install (asks for your sudo password) =="
sudo apt install -y "./$DEB"

cat <<'EOF'

Installed. Launch "Mono Camera Geolocator" from the applications menu, or run:
  mono-camera-geolocator

Imagery API keys (Mapbox / Google) go in:
  ~/.local/share/MonoCameraGeolocator/work/.env
See desktop/installation.md §8 for the exact lines.
EOF
