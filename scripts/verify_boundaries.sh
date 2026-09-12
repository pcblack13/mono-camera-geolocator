#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
#  LandExplorer — the boundary gate. CONTRACT.md §10.4 (import-linter) + §10.5
#  (the greps). This is a BUILD FAILURE, not a code-review opinion (§10).
#
#  It enforces, mechanically:
#      L3  ai_engine does not know what a CRS is.
#      L4  gis does not know what a descriptor is.
#      L5  the API never performs CV  (where allow_indirect_imports made the
#          import-linter rule toothless, THIS is where it bites — §10.4).
#      L8  torch is imported in exactly one module.
#      + Google Earth is structurally excluded, Settings is read exactly once,
#        and there are no ad-hoc raster/CRS backend fallbacks.
#
#  Usage:
#      scripts/verify_boundaries.sh            # everything
#      scripts/verify_boundaries.sh --greps    # §10.5 only (no import-linter needed)
#
#  Exit 0 = clean. Exit 1 = a boundary was crossed. Exit 2 = the gate itself broke.
# ═══════════════════════════════════════════════════════════════════════════════
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 2

FAILURES=0
CHECKS=0
SKIPPED=0
GREPS_ONLY=0
[[ "${1:-}" == "--greps" ]] && GREPS_ONLY=1

if [[ -t 1 && "${NO_COLOR:-}" == "" && "${TERM:-}" != "dumb" ]]; then
    RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'
    BOLD=$'\033[1m'; DIM=$'\033[2m'; RESET=$'\033[0m'
else
    RED=""; GREEN=""; YELLOW=""; BOLD=""; DIM=""; RESET=""
fi

# ─────────────────────────────────────────────────────────────────────────────
# ★ THE COMMENT STRIPPER — and the one place this script knowingly departs from
#   the LETTER of §10.5 in order to implement its MEANING. Read this before
#   "fixing" it.
#
#   §10.5 writes its gates as:   py_src <pattern> <dir> | strip_comments | ...
#   i.e. grep FIRST, strip SECOND. That pipeline cannot do what §10.5 says it
#   does. grep emits `path:lineno:CONTENT`; stripping the comment out of CONTENT
#   afterwards does not un-emit the line — it just prints a mangled copy of it.
#   A hit that existed ONLY inside a comment still reaches the output and still
#   fails the gate.
#
#   That is not academic. §10.5's own rule 1 ("Code, not prose") exists because
#   §4.10's VERBATIM, MANDATED windows.py contains
#        crs: str  # OPAQUE. e.g. "EPSG:3857"
#   and IU-01 — the FIRST unit in the build order — would go red on its first
#   commit. Implemented literally, the fix does not fix the bug it was written
#   for. So: WE STRIP BEFORE WE MATCH. The patterns, the directories, the
#   --exclude-dir=tests scoping and the `noqa: L3` escape are all §10.5's,
#   verbatim and unchanged. Only the order is corrected.
#
#   The awk below replicates sed's two rules in sed's order, so the semantics of
#   `strip_comments` are preserved exactly:
#       s/[[:space:]]#.*$//     drop a trailing comment (needs whitespace before #)
#       /^[[:space:]]*#/d       drop a full-line comment
#   Known and accepted limitation, identical to §10.5's own: a '#' inside a
#   string literal truncates the line. §10.5's stripper has the same property.
# ─────────────────────────────────────────────────────────────────────────────

# py_src_stream <dir>... -> emits `path:lineno:code` for every line of CODE
#   (comments removed) in every *.py outside a tests/ directory. §10.5's
#   `py_src()` is `grep -rn --include='*.py' --exclude-dir=tests`; the
#   --exclude-dir=tests scoping is rule 2 ("Source, not tests") and is REQUIRED:
#   §2.2 puts tests/ INSIDE ai_engine/src/ai_engine/, and IU-03's mandated test
#   "nothing imports cv2.xfeatures2d" MUST contain the literal string to assert
#   on it — so a repo-wide gate would fail on the very test proving the property.
py_src_stream() {
    local dirs=()
    local d
    for d in "$@"; do
        [[ -d "$d" ]] && dirs+=("$d")
    done
    [[ ${#dirs[@]} -eq 0 ]] && return 0
    find "${dirs[@]}" -type f -name '*.py' -not -path '*/tests/*' -print0 2>/dev/null \
      | xargs -0 -r awk '
            {
                code = $0
                sub(/[[:space:]]#.*$/, "", code)       # rule 1: trailing comment
                if (code ~ /^[[:space:]]*#/) next      # rule 2: full-line comment
                if (code ~ /^[[:space:]]*$/) next      # nothing left to match
                printf "%s:%d:%s\n", FILENAME, FNR, code
            }'
}

# gate <law> <description> <output>
#   Every §10.5 gate MUST return EMPTY. Non-empty output = the boundary was crossed.
gate() {
    local law="$1" desc="$2" out="$3"
    CHECKS=$((CHECKS + 1))
    if [[ -z "$out" ]]; then
        printf '  %s✔%s %-5s %s\n' "$GREEN" "$RESET" "$law" "$desc"
    else
        printf '  %s✘%s %-5s %s\n' "$RED" "$RESET" "$law" "${BOLD}${desc}${RESET}"
        printf '%s\n' "$out" | sed 's/^/        /'
        printf '\n'
        FAILURES=$((FAILURES + 1))
    fi
}

# Trees are written by other units and may legitimately not exist yet during a
# parallel build. A gate over an absent tree is SKIPPED and SAID SO — never
# silently passed. Once the tree lands, the gate is strict.
tree_present() {
    local d="$1"
    if [[ -d "$d" ]]; then
        return 0
    fi
    SKIPPED=$((SKIPPED + 1))
    printf '  %s•%s %-5s %s%s%s\n' "$YELLOW" "$RESET" "SKIP" "$DIM" "not present yet: $d" "$RESET"
    return 1
}

printf '%sLandExplorer — boundary gate%s  %s(CONTRACT.md §10.4 + §10.5)%s\n\n' \
    "$BOLD" "$RESET" "$DIM" "$RESET"

# ═════════════════════════════════════════════════════════════════════════════
# §10.5 — THE GREP GATES. Patterns are §10.5's, verbatim.
# ═════════════════════════════════════════════════════════════════════════════
printf '%s§10.5 grep gates%s\n' "$BOLD" "$RESET"

AI_SRC="ai_engine/src/ai_engine"
GIS_SRC="gis/src/gis"
BE_SRC="backend/app"

# ── L3 — ai_engine does not know what a CRS is ──────────────────────────────
if tree_present "$AI_SRC"; then
    gate "L3" "ai_engine knows no CRS (no epsg/pyproj/lat/lon/mercator/slippy/quadkey/geodesic)" \
        "$(py_src_stream "$AI_SRC" \
            | grep -iE 'epsg|pyproj|latitude|longitude|lonlat|lon_lat|mercator|slippy|quadkey|geodesic' \
            | grep -v 'noqa: L3')"

    # ── L3b — ai_engine never INDEXES the opaque geotransform (§4.24(4)) ─────
    #   The 1/cos(phi) pose bug is a READ of a field it is allowed to CARRY, so
    #   the type system cannot catch it and ONLY a grep can.
    gate "L3b" "ai_engine never indexes the opaque geotransform" \
        "$(py_src_stream "$AI_SRC" | grep -E 'geotransform[[:space:]]*\[')"
fi

# ── L4 — gis does not know what a descriptor is ─────────────────────────────
if tree_present "$GIS_SRC"; then
    gate "L4" "gis knows no descriptor (no sift/orb/akaze/brisk/ransac/magsac/homography)" \
        "$(py_src_stream "$GIS_SRC" \
            | grep -iE 'sift|orb_create|akaze|brisk|ransac|magsac|descriptor|findhomography|xfeatures2d')"

    # ── Google Earth is structurally excluded ───────────────────────────────
    #   Not a disabled flag: an ABSENCE. There is no enum label for it either —
    #   unrepresentable in the type system is the cheapest possible enforcement.
    gate "LEGAL" "Google Earth is structurally excluded from gis" \
        "$(py_src_stream "$GIS_SRC" | grep -iE 'kh\.google|khms|google.*earth|earth.*google')"

    # ── no ad-hoc raster/CRS backend fallbacks ──────────────────────────────
    #   ★ crs.py is EXEMPT: §10.2 grants it osgeo and §11.3 REQUIRES the osr
    #     fallback. Verified on this machine: pyproj is MISSING and osgeo.osr is
    #     present, so osr is the ONLY working path for anything that is not
    #     4326<->3857 — and §13.2 commits synthetic_ortho.tif at EPSG:32633 with
    #     §13.3 requiring a <1e-6 px round-trip, which the closed-form NumPy
    #     fallback CANNOT do. rasterio_shim.py is the other sanctioned site.
    #   ★ SECOND DEPARTURE FROM §10.5's LETTER, SAME REASON AS THE STRIPPER:
    #     §10.5 writes the pattern as `import rasterio\|from osgeo`. Taken
    #     literally, `import rasterio` matches AS A SUBSTRING of
    #         from gis import rasterio_shim
    #     which is the import §10.2 EXPLICITLY PERMITS for gis.elevation,
    #     gis.raster and anything else needing raster IO — going through the shim
    #     is the whole point of having one. The literal gate therefore fails on
    #     gis/elevation/local_dem.py, i.e. on mandated source, exactly as v1.0's
    #     L3 gate failed on §4.10's mandated windows.py.
    #
    #     Fixed with a word boundary: `import rasterio\b` does NOT match
    #     `import rasterio_shim` (the following `_` is a word character) and DOES
    #     match `import rasterio` / `import rasterio as rio`.
    #
    #     `from rasterio` is ALSO matched now, closing a false NEGATIVE the
    #     literal pattern left open: `from rasterio.windows import Window` binds
    #     rasterio just as hard as `import rasterio` and slipped straight through.
    #     The file-path exemptions are §10.5's own, unchanged.
    #   gis/dem/ is EXEMPT: the DEM pipeline (ported from DTM_Proccesing) is
    #   rasterio-NATIVE — windowed reads, warp/reproject, nodata masking — and
    #   the shim's read-meta surface cannot express it. rasterio is a hard,
    #   pinned dep of every runtime that runs the pipeline (§9.14), so the
    #   shim's GDAL fallback has nothing to add there.
    gate "RASTER" "rasterio/osgeo bound only in rasterio_shim.py, crs.py and dem/" \
        "$(py_src_stream "$GIS_SRC" \
            | grep -E 'import rasterio\b|from rasterio\b|import osgeo\b|from osgeo\b' \
            | grep -vE 'rasterio_shim\.py|crs\.py|/dem/')"
fi

# ── §0.1 — cv2.xfeatures2d stays banned ─────────────────────────────────────
#   The environment now ships opencv-contrib-python-headless (ONE wheel, no GUI)
#   for the CSRT tracker in detection — a deliberate 2026-08 decision. The
#   xfeatures2d ban survives that swap: feature matching stays on main-module
#   APIs so it cannot silently depend on contrib being present.
#   Scoped to source. IU-03's runtime assertion is the STRONGER check anyway: it
#   catches getattr(cv2, 'xfeatur' + 'es2d'), which no grep can see.
if [[ -d "$AI_SRC" || -d "$GIS_SRC" || -d "$BE_SRC" ]]; then
    gate "§0.1" "nothing references cv2.xfeatures2d (matching stays on main cv2)" \
        "$(py_src_stream "$AI_SRC" "$GIS_SRC" "$BE_SRC" | grep -E 'xfeatures2d')"
fi

if tree_present "$BE_SRC"; then
    # ── Settings is read exactly once ───────────────────────────────────────
    gate "L10" "os.getenv/os.environ appears only in core/config.py" \
        "$(py_src_stream "$BE_SRC" \
            | grep -E 'os\.getenv|os\.environ' \
            | grep -v 'core/config\.py')"

    # ── L5 — the API never performs CV ──────────────────────────────────────
    #   This is where L5 actually bites: §10.4's api-not-db lists cv2 but
    #   allow_indirect_imports makes that entry toothless, and §10.4 says so.
    if [[ -d "$BE_SRC/api" ]]; then
        gate "L5" "no cv2/torch import reachable from backend/app/api/" \
            "$(py_src_stream "$BE_SRC/api" | grep -E 'import cv2|import torch')"
    fi
fi

# ═════════════════════════════════════════════════════════════════════════════
# §10.3 — THE SEAM MUST STILL EXIST.
#   Every gate above is a prohibition, and a prohibition is trivially satisfied
#   by deleting the thing. §10.4 requires CI to ASSERT the one PERMITTED
#   cross-package import still exists, so that nobody "fixes" a boundary
#   violation by cutting the seam gis.candidates -> ai_engine.types.
# ═════════════════════════════════════════════════════════════════════════════
printf '\n%s§10.3 the permitted seam%s\n' "$BOLD" "$RESET"
SEAM_DIR="$GIS_SRC/candidates"
if [[ -d "$SEAM_DIR" ]]; then
    CHECKS=$((CHECKS + 1))
    # ★ NOT `| grep -q`: under pipefail, -q exits on the first match, awk dies
    #   with SIGPIPE (141), and the pipeline "fails" — reporting the seam GONE
    #   while staring straight at it. Capture instead; grep then reads to EOF.
    if [[ -n "$(py_src_stream "$SEAM_DIR" | grep -E 'from ai_engine\.types|import ai_engine\.types')" ]]; then
        printf '  %s✔%s %-5s %s\n' "$GREEN" "$RESET" "§10.3" \
            "gis.candidates -> ai_engine.types still exists (the seam is intact)"
    else
        printf '  %s✘%s %-5s %s\n' "$RED" "$RESET" "§10.3" \
            "${BOLD}THE SEAM IS GONE: gis.candidates no longer imports ai_engine.types${RESET}"
        printf '        §10.3 permits exactly this import and the design depends on it.\n'
        printf '        If a boundary gate was "fixed" by deleting it, that fix is wrong.\n\n'
        FAILURES=$((FAILURES + 1))
    fi
else
    SKIPPED=$((SKIPPED + 1))
    printf '  %s•%s %-5s %s%s%s\n' "$YELLOW" "$RESET" "SKIP" "$DIM" \
        "not present yet: $SEAM_DIR" "$RESET"
fi

# ═════════════════════════════════════════════════════════════════════════════
# §10.4 — import-linter.
# ═════════════════════════════════════════════════════════════════════════════
if [[ $GREPS_ONLY -eq 0 ]]; then
    printf '\n%s§10.4 import-linter%s\n' "$BOLD" "$RESET"
    if command -v lint-imports >/dev/null 2>&1; then
        # `app` is backend/app — it only resolves with backend/ on sys.path.
        export PYTHONPATH="${REPO_ROOT}/backend:${REPO_ROOT}/ai_engine/src:${REPO_ROOT}/gis/src:${PYTHONPATH:-}"
        if lint-imports --config "${REPO_ROOT}/.importlinter" 2>&1 | sed 's/^/  /'; then
            CHECKS=$((CHECKS + 1))
        else
            CHECKS=$((CHECKS + 1))
            FAILURES=$((FAILURES + 1))
        fi
    else
        SKIPPED=$((SKIPPED + 1))
        printf '  %s•%s %-5s %s%s%s\n' "$YELLOW" "$RESET" "SKIP" "$DIM" \
            "lint-imports not installed — pip install import-linter (it is a [dev] extra)" "$RESET"
    fi
fi

# ═════════════════════════════════════════════════════════════════════════════
printf '\n'
if [[ $FAILURES -eq 0 ]]; then
    printf '%s✔ boundaries intact%s — %d gate(s) passed' "$GREEN" "$RESET" "$CHECKS"
    [[ $SKIPPED -gt 0 ]] && printf ', %s%d skipped%s' "$YELLOW" "$SKIPPED" "$RESET"
    printf '\n'
    if [[ $SKIPPED -gt 0 ]]; then
        printf '%s  A SKIP is not a PASS. Skipped gates cover trees that do not exist yet;%s\n' \
            "$DIM" "$RESET"
        printf '%s  they become strict the moment the tree lands.%s\n' "$DIM" "$RESET"
    fi
    exit 0
fi
printf '%s✘ %d BOUNDARY VIOLATION(S)%s across %d gate(s).\n' "$RED" "$FAILURES" "$RESET" "$CHECKS"
printf '  These are laws (CONTRACT.md §1), not preferences. A PR violating one is\n'
printf '  rejected without discussion. If a line above is a false positive on a\n'
printf '  COMMENT, the stripper missed it — fix the stripper, not the gate.\n'
exit 1
