#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
#  LandExplorer — make this repo runnable on THIS machine. CONTRACT.md §2.9.
#
#  ★ THIS SCRIPT INSTALLS NOTHING FROM PyPI, AND THAT IS THE POINT.
#    The brief gives no network guarantee. Everything the CV stack needs is
#    ALREADY HERE as a system package:
#
#        cv2 · numpy · scipy · torch · osgeo   ← system-site packages
#
#    Two flags carry that fact, and BOTH are load-bearing:
#
#      --system-site-packages   A plain `python -m venv` HIDES ALL FIVE. And
#                               `osgeo` CANNOT BE PIP-INSTALLED BACK — GDAL's
#                               bindings need libgdal-dev plus a version-matched
#                               build. Forget this flag and you have destroyed
#                               the raster backend on the only machine we can
#                               test on. The one script whose job is making the
#                               repo runnable here is the one most able to break
#                               it (§0.1).
#
#      --no-deps                Without it, pip resolves opencv/numpy/scipy from
#                               PyPI — over a network that may not exist — and
#                               shadows the system builds with a second copy.
#
#  After this runs:
#      import ai_engine, import gis      clean, zero runtime installs
#      cd ai_engine && pytest            green
#      cd gis && pytest                  green
# ═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VENV_DIR="${VENV_DIR:-${REPO_ROOT}/.venv}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [[ -t 1 && "${NO_COLOR:-}" == "" ]]; then
    BOLD=$'\033[1m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; DIM=$'\033[2m'; RESET=$'\033[0m'
else
    BOLD=""; GREEN=""; YELLOW=""; DIM=""; RESET=""
fi

step() { printf '\n%s▶ %s%s\n' "$BOLD" "$1" "$RESET"; }

# ── 1. Print the capability table FIRST ──────────────────────────────────────
#    Before we change anything, show what this machine actually has. If GDAL is
#    missing, you want to know now — not when an export silently produces
#    nothing six weeks from now.
step "Machine capabilities (CONTRACT.md §0.1)"
"$PYTHON_BIN" "${REPO_ROOT}/scripts/check_env.py" || true

# ── 2. The venv — WITH system site packages ──────────────────────────────────
step "Virtual environment: ${VENV_DIR}"
if [[ -d "$VENV_DIR" ]]; then
    if [[ ! -f "${VENV_DIR}/pyvenv.cfg" ]]; then
        printf '%s✘ %s exists but is not a venv. Remove it and re-run.%s\n' "$YELLOW" "$VENV_DIR" "$RESET" >&2
        exit 1
    fi
    if ! grep -q 'include-system-site-packages = true' "${VENV_DIR}/pyvenv.cfg"; then
        printf '%s✘ THE EXISTING VENV HIDES THE SYSTEM CV STACK.%s\n' "$YELLOW" "$RESET" >&2
        printf '  %s was created without --system-site-packages, so cv2/numpy/scipy/\n' "$VENV_DIR" >&2
        printf '  torch/osgeo are invisible inside it — and osgeo cannot be pip-installed back.\n' >&2
        printf '  Fix:  rm -rf %s && scripts/bootstrap_dev.sh\n' "$VENV_DIR" >&2
        exit 1
    fi
    printf '  %sexists, and exposes system site-packages — reusing%s\n' "$DIM" "$RESET"
else
    "$PYTHON_BIN" -m venv --system-site-packages "$VENV_DIR"
    printf '  %screated with --system-site-packages%s\n' "$DIM" "$RESET"
fi

VPY="${VENV_DIR}/bin/python"

# Prove the flag did its job before we build anything on top of it.
step "Verifying the venv did NOT hide the system CV stack"
"$VPY" - <<'PYEOF'
import importlib.util
import sys

REQUIRED = ["numpy", "cv2", "scipy", "osgeo"]
missing = [m for m in REQUIRED if importlib.util.find_spec(m) is None]
if missing:
    print(f"  \033[31m✘ INVISIBLE INSIDE THE VENV: {', '.join(missing)}\033[0m", file=sys.stderr)
    print("    The venv was created without --system-site-packages, or the system", file=sys.stderr)
    print("    packages are genuinely absent. osgeo CANNOT be pip-installed back.", file=sys.stderr)
    raise SystemExit(1)
print(f"  \033[32m✔\033[0m visible inside the venv: {', '.join(REQUIRED)}")
PYEOF

# ── 3. The two editable installs — --no-deps, always ─────────────────────────
step "Editable installs (--no-deps: nothing is fetched from PyPI)"
for pkg in ai_engine gis; do
    if [[ -f "${REPO_ROOT}/${pkg}/pyproject.toml" ]]; then
        "$VPY" -m pip install -e "./${pkg}[dev]" --no-deps --quiet \
            && printf '  %s✔%s ./%s[dev]\n' "$GREEN" "$RESET" "$pkg"
    else
        printf '  %s•%s ./%s/pyproject.toml not written yet — skipping%s\n' \
            "$YELLOW" "$RESET" "$pkg" "$DIM${RESET}"
    fi
done

printf '\n  %sNote: `[dev]` brings pytest/hypothesis/mypy/ruff — the test RUNNER is not a%s\n' "$DIM" "$RESET"
printf '  %sruntime dep. "Zero installs" covers RUNTIME deps only (§0.1). If you have no%s\n' "$DIM" "$RESET"
printf '  %snetwork, the [dev] extras above are the one thing that needs an index.%s\n' "$DIM" "$RESET"

# ── 4. pnpm via corepack ─────────────────────────────────────────────────────
step "Frontend toolchain (§2.5 mandates pnpm-lock.yaml)"
if command -v corepack >/dev/null 2>&1; then
    corepack enable >/dev/null 2>&1 || printf '  %s• corepack enable needs sudo on some installs%s\n' "$DIM" "$RESET"
    corepack prepare pnpm@9 --activate >/dev/null 2>&1 \
        && printf '  %s✔%s pnpm 9 activated\n' "$GREEN" "$RESET" \
        || printf '  %s•%s corepack could not activate pnpm (offline?) — run it manually later\n' "$YELLOW" "$RESET"
else
    printf '  %s•%s corepack not found; node %s\n' "$YELLOW" "$RESET" "$(node --version 2>/dev/null || echo 'absent')"
fi

# ── 5. Where to go next ──────────────────────────────────────────────────────
printf '\n%s✔ bootstrap complete%s\n\n' "$GREEN" "$RESET"
printf 'Activate it:      source %s/bin/activate\n' "${VENV_DIR#"$REPO_ROOT"/}"
printf 'Run the suites:   cd ai_engine && pytest      ·      cd gis && pytest\n'
printf 'Check boundaries: make verify-boundaries\n'
printf 'Run the stack:    make up        %s(needs Docker — NOT installed on this machine)%s\n' "$DIM" "$RESET"
printf '\n%sThis build is a MANUAL GCP tool. Automatic matching is DEFERRED —%s\n' "$BOLD" "$RESET"
printf '%sread docs/architecture/SCOPE.md before you go looking for the matcher.%s\n' "$DIM" "$RESET"
