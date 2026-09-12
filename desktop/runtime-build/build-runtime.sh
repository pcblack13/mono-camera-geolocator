#!/bin/bash
# Build the self-contained runtime: python + postgresql/postgis + redis + backend deps.
set -euo pipefail
cd "$(dirname "$0")"
SOFT="$(cd ../.. && pwd)"

# ★★ STRICT ISOLATION FROM THE BUILD MACHINE'S USER SITE-PACKAGES. Without this,
#    pip sees packages in ~/.local/lib/pythonX/site-packages as "already satisfied"
#    and SKIPS them — the July build shipped a runtime with no numpy and no dateutil,
#    and nobody noticed for a week because the dev machine's user site quietly filled
#    the hole at runtime. A clean machine then crashed on first boot. The sanity step
#    below imports through the same isolation, so a hollow env can never pack again.
export PYTHONNOUSERSITE=1

echo "== micromamba =="
# ★ The STATIC binary from the official releases repo, not the .tar.bz2 from
#   micro.mamba.pm: `tar -xj` execs the external `bzip2` program, which a fresh
#   Ubuntu does not ship — the one-folder install must assume nothing beyond
#   curl+tar. The `--version` probe also heals a partial file left by a killed
#   earlier download, which `-x` alone would trust.
if ! bin/micromamba --version >/dev/null 2>&1; then
  mkdir -p bin
  curl -fsSL https://github.com/mamba-org/micromamba-releases/releases/latest/download/micromamba-linux-64 \
    -o bin/micromamba
  chmod +x bin/micromamba
fi

# ★ FULLY SELF-CONTAINED: root prefix AND package cache live inside runtime-build/,
#   never in ~/.mamba. The shared per-user cache is lock-protected, and a stale lock
#   from an interrupted earlier run leaves the next run "Waiting for other mamba
#   process to finish" forever. In-repo caches cannot collide with anything.
export MAMBA_ROOT_PREFIX="$PWD/mamba-root"
export CONDA_PKGS_DIRS="$PWD/mamba-root/pkgs"

echo "== conda env (python + postgres + postgis + redis) =="
if [ ! -x env/bin/python ]; then
  ./bin/micromamba create -y -r mamba-root -p "$PWD/env" -c conda-forge \
    python=3.12 postgresql=16 postgis redis-server pip
fi

echo "== backend python deps =="
env/bin/pip install --no-input -r "$SOFT/backend/requirements.txt"
env/bin/pip install --no-input --no-deps "$SOFT/ai_engine" "$SOFT/gis"

# ── live detection: torch + ultralytics, on the GPU when the machine has one ──
# ★ THE CUDA BUILD WHEN AN NVIDIA DRIVER IS PRESENT (2026-09-10, owner ask). The
#   env used to carry the CPU wheel, so an RTX 3060 sat idle while detection ran
#   on 20 cores. `resolve_device("auto")` already takes the GPU whenever torch can
#   see one; what was missing was a torch that could. Driver ≥ 580 serves CUDA 13,
#   which is what the cu130 wheels need; older drivers fall back to the CPU wheel.
#   Skip the whole block with --no-detection (a ~3 GB download on GPU machines).
if [[ " $* " != *" --no-detection "* ]]; then
  TORCH_INDEX="https://download.pytorch.org/whl/cpu"
  if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
    DRIVER_MAJOR="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1 | cut -d. -f1)"
    if [ "${DRIVER_MAJOR:-0}" -ge 580 ] 2>/dev/null; then
      TORCH_INDEX="https://download.pytorch.org/whl/cu130"
      echo "== torch: NVIDIA GPU with driver $DRIVER_MAJOR — CUDA 13 build =="
    else
      echo "== torch: NVIDIA driver $DRIVER_MAJOR is older than 580 — CPU build (update the driver for GPU detection) =="
    fi
  else
    echo "== torch: no NVIDIA GPU — CPU build =="
  fi
  env/bin/pip install --no-input --index-url "$TORCH_INDEX" "torch==2.13.0" "torchvision==0.28.0"
  # WITHOUT its deps: it would pull opencv-python over the contrib-headless install.
  env/bin/pip install --no-input --no-deps "ultralytics==8.4.130"
  env/bin/pip install --no-input pyyaml tqdm psutil nvidia-ml-py requests matplotlib pandas
fi
env/bin/pip install --no-input conda-pack

echo "== sanity =="
# `-s` doubles the isolation: even if PYTHONNOUSERSITE is lost, this import list can
# only be satisfied from INSIDE the env — numpy/dateutil are named because they are
# exactly the two the user-site leak once swallowed.
env/bin/python -s -c "import cv2, rasterio, pyproj, fastapi, celery, numpy, dateutil, uvicorn, ezdxf, reportlab, shapely, geopandas; print('py deps OK (isolated)')"
env/bin/postgres --version
env/bin/redis-server --version | head -1

# --env-only: stop after the env is built and verified. The env is fully usable
# in place (run-desktop.sh points the app straight at it); the tarball below is
# only needed to BUILD INSTALLERS, and packing it costs minutes and a gigabyte.
if [ "${1:-}" = "--env-only" ]; then
  echo "RUNTIME ENV: OK (skipped conda-pack — --env-only)"
  exit 0
fi

echo "== conda-pack =="
rm -f runtime.tar.gz
env/bin/conda-pack -p "$PWD/env" -o runtime.tar.gz --compress-level 1
ls -lh runtime.tar.gz

echo "== verify the tarball is complete =="
# The final gate: the ARTIFACT itself must contain the critical packages. A hollow
# tarball must never leave this script again.
# ★ Listed ONCE into a file, then grepped — `tar | grep -q` under `pipefail` kills
#   tar with SIGPIPE on the first match and reads success as failure.
listing="$(mktemp)"
tar -tzf runtime.tar.gz > "$listing"
for pkg in numpy dateutil cv2 rasterio fastapi celery ezdxf reportlab shapely geopandas; do
  grep -q "site-packages/${pkg}/" "$listing" || {
    echo "FATAL: runtime.tar.gz is missing '${pkg}' — the env was not built in isolation." >&2
    rm -f "$listing"
    exit 1
  }
done
rm -f "$listing"
echo "RUNTIME BUILD: OK"
