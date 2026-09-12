"""★ L3 and L4 — the package boundaries, asserted by parsing rather than by importing.

`CONTRACT.md` §1::

    L3 — `ai_engine` does not know what a CRS is. No pyproj, no EPSG, no lat, no lon, no
         z/x/y. It begins at pixels and ends at pixels.
    L4 — `gis` does not know what a descriptor is. No SIFT, no ratio test, no RANSAC, no
         homography estimation. It ends at pixels + a geotransform.

Both laws say **"CI gate: §10.5, normatively and only"** — §10.5 is the single definition of
the patterns and this file does not invent its own. v1.0 defined each gate twice with
different tokens, and, as §10.5 puts it, *"two definitions of one gate is two gates, and the
looser one is the one that passes."* The vocabularies below are transcribed from §10.5.

**Why this exists when `scripts/verify_boundaries.sh` already runs the greps.** Three
reasons, and the third is the real one:

1. It runs in the suite, so a developer sees it before CI does.
2. It parses, so it sees *code* and not prose — which is the behaviour §10.5 asks for and
   does not quite get (see `_astsupport.code_lines`).
3. **These two laws are why the repo is testable at all.** §10.6: `ai_engine` depends only
   on numpy/opencv/scipy, so `cd ai_engine && pytest` runs on this machine, where fastapi,
   sqlalchemy and pydantic are not installed. L3/L4 are not architectural taste — they are
   the property that keeps the CV core runnable, and a property that load-bearing deserves
   an assertion inside the suite it protects.

★ No imports of the packages under test. `ai_engine` needs cv2 and `gis` needs numpy+PIL;
neither is needed to read their source.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

from _astsupport import REPO_ROOT, code_lines, scan, source_files

AI_ENGINE_SRC: Final[Path] = REPO_ROOT / "ai_engine" / "src" / "ai_engine"
GIS_SRC: Final[Path] = REPO_ROOT / "gis" / "src" / "gis"
BACKEND_APP: Final[Path] = REPO_ROOT / "backend" / "app"

# --- §10.5, transcribed verbatim ---------------------------------------------

L3_PATTERN: Final[str] = r"epsg|pyproj|latitude|longitude|lonlat|lon_lat|mercator|slippy|quadkey|geodesic"
"""§10.5 L3 — `ai_engine` does not know what a CRS is. Case-insensitive."""

L3B_PATTERN: Final[str] = r"geotransform\s*\["
"""§10.5 L3b — `ai_engine` never INDEXES the opaque geotransform (§4.24(4)).

★ Not case-insensitive; §10.5 uses `-E`, not `-iE`, for this one.

The 1/cos(phi) pose bug is a **read** of a field `ai_engine` is allowed to *carry*, so the
type system cannot catch it and only a scan can. Carrying an opaque token is the seam
working; indexing it is `ai_engine` deciding it knows what a geotransform means.
"""

L4_PATTERN: Final[str] = r"sift|orb_create|akaze|brisk|ransac|magsac|descriptor|findhomography|xfeatures2d"
"""§10.5 L4 — `gis` does not know what a descriptor is. Case-insensitive."""

GOOGLE_EARTH_PATTERN: Final[str] = r"kh\.google|khms|google.*earth|earth.*google"
"""§10.5 — Google Earth is structurally excluded by client legal constraint."""


def _fmt(hits: list[str], law: str) -> str:
    listing = "\n".join(f"    {hit}" for hit in hits)
    return f"{law} violated by {len(hits)} code line(s):\n{listing}"


# =============================================================================
# L3 — ai_engine knows no CRS
# =============================================================================


def test_l3_ai_engine_does_not_know_what_a_crs_is() -> None:
    """★ No EPSG, no pyproj, no lat/lon, no slippy vocabulary anywhere in `ai_engine`.

    `ai_engine` begins at pixels and ends at pixels. `gis.crs` is the only birthplace of a
    coordinate — which is why swapping Esri for Mapbox cannot change the matching algorithm.

    ★ `# noqa: L3` on a code line is the sanctioned escape hatch (§10.5 filters it), for the
    rare identifier that trips the vocabulary without crossing the boundary.
    """
    hits = [hit for hit in scan(AI_ENGINE_SRC, L3_PATTERN) if "noqa: L3" not in hit]
    assert not hits, _fmt(hits, "L3 (ai_engine must not know what a CRS is)")


def test_l3b_ai_engine_never_indexes_the_opaque_geotransform() -> None:
    """★ §4.24(4): `ai_engine` may CARRY `geotransform`; it may never READ an element.

    `CandidateWindow.geotransform` is deliberately opaque — `ai_engine` hands it back to
    `gis` untouched. The moment `ai_engine` writes `geotransform[1]` it has decided it knows
    which element is the pixel size, and the 1/cos(phi) latitude correction that belongs to
    `gis.accuracy` starts leaking into a package that has no latitude to correct with.
    """
    hits = scan(AI_ENGINE_SRC, L3B_PATTERN, flags=0)
    assert not hits, _fmt(hits, "L3b (ai_engine must not index the opaque geotransform)")


# =============================================================================
# L4 — gis knows no descriptor
# =============================================================================


def test_l4_gis_does_not_know_what_a_descriptor_is() -> None:
    """★ No SIFT, no RANSAC, no homography estimation, no descriptors anywhere in `gis`.

    `gis` ends at pixels plus a geotransform. It fetches imagery and turns pixel covariance
    into metres; it never decides *which* pixels correspond.
    """
    hits = scan(GIS_SRC, L4_PATTERN)
    assert not hits, _fmt(hits, "L4 (gis must not know what a descriptor is)")


# =============================================================================
# The remaining §10.5 gates that are pure source properties
# =============================================================================


def test_opencv_contrib_is_never_referenced() -> None:
    """§0.1: `cv2.xfeatures2d` is **ABSENT** on this machine (no opencv-contrib).

    SURF/BEBLID/VGG/LATCH are unavailable and must not be referenced. Scanned across all
    three trees. IU-03's runtime assertion is the stronger check — it catches
    `getattr(cv2, "xfeatur" + "es2d")`, which no scan can see — but this one is free.
    """
    hits: list[str] = []
    for tree in (AI_ENGINE_SRC, GIS_SRC, BACKEND_APP):
        if tree.exists():
            hits.extend(scan(tree, r"xfeatures2d"))
    assert not hits, _fmt(hits, "§0.1 (opencv-contrib is absent; xfeatures2d must not appear)")


def test_google_earth_is_structurally_excluded() -> None:
    """★ §5.3: there is deliberately NO `google_earth` provider label.

    Google Earth imagery is out of scope by client legal constraint, and making it
    **unrepresentable in the type system** is the cheapest possible enforcement. Not a
    disabled flag: an absence. This gate keeps it an absence.
    """
    hits = scan(GIS_SRC, GOOGLE_EARTH_PATTERN)
    assert not hits, _fmt(hits, "§10.5 (Google Earth is structurally excluded from gis)")


def test_l5_the_api_never_imports_cv2_or_torch() -> None:
    """★ L5: the API never performs CV. A `cv2` import reachable from a route is a defect.

    §10.5 greps `backend/app/api/` specifically, because import-linter's
    `allow_indirect_imports` made the equivalent rule toothless there.
    """
    api_dir = BACKEND_APP / "api"
    if not api_dir.exists():
        pytest.skip("backend/app/api is not present yet (IU-21)")
    hits = scan(api_dir, r"import\s+cv2|import\s+torch", flags=0)
    assert not hits, _fmt(hits, "L5 (the API never performs CV)")


def test_settings_are_read_in_exactly_one_place() -> None:
    """§10.5: no `os.getenv` / `os.environ` outside `backend/app/core/config.py`.

    L10 says every setting has a working default and `Settings()` never raises. That
    guarantee is only worth anything if there is exactly one place where the environment is
    read — a stray `os.getenv` elsewhere is a setting with no default and no documentation.
    """
    if not BACKEND_APP.exists():
        pytest.skip("backend/app is not present yet")
    hits = [
        hit
        for hit in scan(BACKEND_APP, r"os\.getenv|os\.environ", flags=0)
        if "core/config.py" not in hit
    ]
    assert not hits, _fmt(hits, "§10.5 (Settings is read exactly once, in core/config.py)")


def test_gis_binds_no_raster_or_crs_backend_outside_the_two_sanctioned_modules() -> None:
    """§10.5: `import rasterio` / `from osgeo` only in `rasterio_shim.py` and `crs.py`.

    ★ `crs.py` is EXEMPT and the exemption is load-bearing, not a concession: pyproj is
    missing on this machine and `osgeo.osr` is present, so osr is the ONLY working path for
    anything that is not 4326<->3857 — and §13.2 commits `synthetic_ortho.tif` at EPSG:32633
    with §13.3 requiring a <1e-6 px round-trip on it, which the closed-form NumPy fallback
    cannot do. Without the exemption, either this gate fails or the entire gis CRS suite,
    GeoTIFF ingest and `gis/accuracy.py`'s UTM math fail on the only machine we can test on.
    """
    hits = [
        hit
        for hit in scan(GIS_SRC, r"import\s+rasterio|from\s+osgeo", flags=0)
        # ★ gis/dem is a THIRD sanctioned rasterio site, deliberately: its warp stage
        #   needs calculate_default_transform/reproject/windows — surface the shim never
        #   wrapped (the shim exists to make rasterio OPTIONAL for reads; dem REQUIRES
        #   it and says so at call time with RasterBackendUnavailable naming the fix).
        #   osgeo remains confined to the original two.
        if not re.search(r"rasterio_shim\.py|crs\.py|dem/", hit)
    ]
    assert not hits, _fmt(hits, "§10.5 (no ad-hoc raster/CRS backend fallbacks in gis)")


# =============================================================================
# The scan itself must be honest
# =============================================================================


def test_the_scanner_excludes_tests_but_sees_real_source() -> None:
    """★ A gate that scans nothing passes everything.

    §10.5 rule 2 excludes `tests/` — §2.2 puts them *inside* the package, and IU-03's
    mandated test "nothing imports `cv2.xfeatures2d`" must contain that literal string in
    order to assert on it. That exclusion is correct and is also exactly how a boundary gate
    silently becomes a no-op: point it one directory too high and it is green forever.
    """
    ai_files = source_files(AI_ENGINE_SRC)
    gis_files = source_files(GIS_SRC)

    assert len(ai_files) > 40, f"L3 scanned only {len(ai_files)} ai_engine files"
    assert len(gis_files) > 25, f"L4 scanned only {len(gis_files)} gis files"
    assert not [p for p in ai_files if "tests" in p.parts], "tests leaked into the L3 scan"
    assert not [p for p in gis_files if "tests" in p.parts], "tests leaked into the L4 scan"


def test_the_scanner_reads_code_and_ignores_comments_and_docstrings(tmp_path: Path) -> None:
    """★ The property §10.5 rule 1 asks for, asserted directly on a known file.

    §4.10's mandated `windows.py` carries an opaque `crs: str` field whose comment says
    `e.g. "EPSG:3857"`. That comment is the boundary being *explained*, not crossed. A gate
    that cannot tell the difference goes red on IU-01's first commit — which is precisely
    what §10.5 rule 1 was written to prevent. The probe lives under `tmp_path`, never in the
    source tree the real gates scan.
    """
    probe = tmp_path / "_comment_probe.py"
    probe.write_text(
        '"""A docstring mentioning EPSG and latitude."""\n'
        "# A comment mentioning pyproj and mercator.\n"
        "crs = 1  # trailing comment mentioning quadkey\n"
        'real_code = "epsg:3857"\n'
        "gt = window.geotransform[1]\n",
        encoding="utf-8",
    )
    lines = code_lines(probe)
    joined = " ".join(lines.values())

    for prose_token in ("latitude", "pyproj", "mercator", "quadkey"):
        assert prose_token not in joined.lower(), f"{prose_token!r} survived from prose"
    assert "epsg:3857" in joined.lower(), "a real string literal must NOT be stripped"
    assert re.search(L3_PATTERN, joined, re.IGNORECASE), "the scanner must still see code"
    assert re.search(L3B_PATTERN, joined), "the scanner must see a cross-token pattern like L3b"
