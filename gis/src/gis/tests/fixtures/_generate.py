"""Regenerate every committed fixture in this directory. Deterministic. NO NETWORK.

★ **The committed binaries are the source of truth; this script is their provenance.**
Run it only to *reproduce* them — never as part of a test run. A fixture that a test
regenerates is not a fixture, it is a fixture-shaped mock of whatever the code does today,
and it cannot catch a regression in the code that writes it.

    python3 gis/src/gis/tests/fixtures/_generate.py [--check]

``--check`` regenerates into a temporary directory and diffs against the committed bytes,
which is how CI can prove the two have not drifted.

**Why this lives here and not in ``scripts/make_fixtures.py``.** CONTRACT.md §2.9 names
``scripts/make_fixtures.py`` as the generator, but §3 assigns all of ``scripts/**`` to
IU-30 while ``gis/src/gis/tests/fixtures/**`` is IU-14's. The generator sits beside the
bytes it produces, inside the owning unit, so regenerating a fixture never requires
touching another unit's file. ``scripts/make_fixtures.py`` may call into this module.

**What is generated, and the contract each item discharges (§13.2):**

* ``synthetic_ortho.tif`` — 64x64 EPSG:32633 GeoTIFF, known geotransform. Backs
  ``LocalOrthophotoProvider``, ``detect_georeferencing()`` and the offline gis suite.
* ``plain.tif``          — a TIFF with NO georeferencing. GDAL hands back the identity
  transform for it. ★ This file is the difference between ``is_geotiff`` meaning something
  and marking every scanned TIFF as georeferenced at 0N 0E.
* ``tiles/{z}/{x}/{y}.png`` — 256x256 RGB tiles backing ``FixtureProvider``.
* ``slippy_goldens.json`` — §13.3's published tile numbers.

★ **Pixels are written with ``WriteRaster`` (bytes), never ``WriteArray``.**
``osgeo.gdal_array`` does not import under NumPy 2 on this machine, and ``WriteArray``
goes through it. Same constraint IU-10's ``test_raster.py`` documents.
"""

from __future__ import annotations

import argparse
import filecmp
import hashlib
import json
import math
import sys
import tempfile
from pathlib import Path
from typing import Any, Final

import numpy as np

HERE: Final[Path] = Path(__file__).parent

# --- The mandated geometry ---------------------------------------------------
#
# ★ THESE THREE CONSTANTS ARE LOAD-BEARING AND ARE NOT FREE TO CHANGE.
#   IU-10's test_raster.py and IU-11's test_providers_contract.py each hardcode them and
#   assert against the committed file when it is present:
#       _ORTHO_GT   = (500000.0, 0.5, 0.0, 5000000.0, 0.0, -0.5)
#       _ORTHO_EPSG = 32633
#       _ORTHO_SIZE = 64
#   Changing any of them here turns two other units' suites red. They were cross-checked
#   against both files, not chosen.
ORTHO_GT: Final[tuple[float, float, float, float, float, float]] = (
    500000.0,
    0.5,
    0.0,
    5000000.0,
    0.0,
    -0.5,
)
ORTHO_EPSG: Final[int] = 32633
ORTHO_SIZE: Final[int] = 64

# 500000 E in UTM 33N is exactly the zone's central meridian, so the ortho's top-left
# corner is exactly 15.0000000 E, 45.1534772 N. Verified with osr, not assumed.
ORTHO_LON: Final[float] = 15.0
ORTHO_LAT: Final[float] = 45.1534772

SEED: Final[int] = 20260717
"""Fixed seed. §13.2: "Generated with a fixed seed, no network"."""

# The committed tiles cover the ortho's own ground, so the demo scene and the ortho are
# the same place rather than two unrelated synthetic worlds.
TILE_SIZE: Final[int] = 256
COMMITTED_TILES: Final[tuple[tuple[int, int, int], ...]] = (
    (15, 17749, 11767),
    (16, 35498, 23535),
    (16, 35499, 23535),
    (16, 35498, 23536),
    (16, 35499, 23536),
)


# =============================================================================
# Synthetic farmland — shared by the ortho and the tiles
# =============================================================================


def _farmland(
    size: int,
    *,
    seed: int,
    rows_deg: float,
    row_spacing_px: float,
    grain: float = 3.0,
) -> np.ndarray:
    """Render deterministic synthetic farmland as ``(size, size, 3)`` uint8 RGB.

    Structured rather than random: parcels, crop rows, a track and a canal. Structure
    matters twice over — it compresses (the whole fixture set stays under 200 KB) and it
    gives a feature detector something to find, so the same generator can back both an
    ortho fixture and the offline demo tiles.

    Args:
        size: Output edge length in pixels.
        seed: Deterministic seed.
        rows_deg: Crop-row orientation, degrees CCW from the +x axis.
        row_spacing_px: Crop-row period in pixels.
        grain: Std-dev of the per-pixel noise. ★ Costly: i.i.d. noise is incompressible, so
            at 256x256 a grain of 3.0 inflates a PNG from ~9 KB to ~108 KB and blows §13.2's
            500 KB budget on five tiles alone. The 64x64 ortho can afford it (it is 4 KB of
            pixels); the tiles pass ``grain=0.0`` and get their variation from structure.

    Returns:
        ``(size, size, 3)`` uint8 RGB, C-contiguous.
    """
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float64)

    # Two parcels split by a diagonal, each with its own crop colour.
    parcel = ((xx * 0.55 + yy * 0.45) > (size * 0.5)).astype(np.float64)

    soil = np.array([134.0, 106.0, 78.0])
    crop_a = np.array([86.0, 128.0, 60.0])
    crop_b = np.array([120.0, 146.0, 74.0])

    base = np.empty((size, size, 3), dtype=np.float64)
    for c in range(3):
        base[..., c] = crop_a[c] * (1.0 - parcel) + crop_b[c] * parcel

    # Crop rows: a periodic ridge pattern at the seeded orientation.
    theta = math.radians(rows_deg)
    projected = xx * math.cos(theta) + yy * math.sin(theta)
    rows = 0.5 + 0.5 * np.sin(2.0 * math.pi * projected / row_spacing_px)
    base += (rows[..., None] - 0.5) * 26.0

    # A soil track running roughly north-south, and a canal running east-west.
    track = np.abs(xx - size * 0.28) < max(1.0, size * 0.022)
    canal = np.abs(yy - size * 0.70) < max(1.0, size * 0.016)
    base[track] = soil
    base[canal] = np.array([74.0, 104.0, 132.0])

    # Mild grain so the image is never flat, but not so much that DEFLATE gives up.
    if grain > 0.0:
        base += rng.normal(0.0, grain, base.shape)

    return np.ascontiguousarray(np.clip(base, 0, 255).astype(np.uint8))


# =============================================================================
# GeoTIFFs
# =============================================================================


def _write_tif(path: Path, *, georeferenced: bool) -> None:
    """Write one 64x64 3-band uint8 GeoTIFF, with or without georeferencing.

    ★ No nodata value is declared on either file. IU-10's
    ``test_nodata_absent_means_no_substitution`` reads the committed ortho and asserts that
    ``apply_nodata=True`` changes nothing, which is only true while this stays true.
    """
    from osgeo import gdal, osr

    # ★ EXPECTED NOISE, NOT A FAILURE. UseExceptions() does `from . import gdal_array`
    #   internally, and gdal_array is compiled against NumPy 1; under this machine's NumPy
    #   2.4 that import prints a multi-line "_ARRAY_API not found" block to stderr that
    #   looks exactly like a crash and is not one — GDAL carries on and exceptions are
    #   enabled. It is the same root cause as IU-10's "WriteRaster, never WriteArray" note.
    #   Enabling exceptions is worth the noise here: this script writes files that other
    #   units' suites assert against, and a silent GDAL error code would ship a bad fixture.
    gdal.UseExceptions()

    image = _farmland(ORTHO_SIZE, seed=SEED, rows_deg=22.0, row_spacing_px=6.0)

    driver = gdal.GetDriverByName("GTiff")
    dataset = driver.Create(
        str(path),
        ORTHO_SIZE,
        ORTHO_SIZE,
        3,
        gdal.GDT_Byte,
        options=["COMPRESS=DEFLATE", "PREDICTOR=2", "ZLEVEL=9"],
    )
    if georeferenced:
        dataset.SetGeoTransform(ORTHO_GT)
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(ORTHO_EPSG)
        dataset.SetProjection(srs.ExportToWkt())
    # ★ else: set NOTHING. Not an identity transform written on purpose — an ABSENCE.
    #   GDAL then reports (0,1,0,0,0,1) on read, which is exactly the trap plain.tif exists
    #   to prove we do not fall into.

    for band_index in range(1, 4):
        band = dataset.GetRasterBand(band_index)
        plane = np.ascontiguousarray(image[..., band_index - 1])
        band.WriteRaster(0, 0, ORTHO_SIZE, ORTHO_SIZE, plane.tobytes())

    dataset.FlushCache()
    del dataset


# =============================================================================
# Tiles
# =============================================================================


def _write_tiles(root: Path) -> None:
    """Write the committed ``tiles/{z}/{x}/{y}.png`` set.

    ★ 256x256 PNG, no alpha. ``FixtureProvider.get_tile`` passes these through
    ``gis.imagery.base.decode_rgb(..., expect_size=256)``, which rejects a wrong-sized tile
    with ``ProviderTransportError``.

    ★ **Palettised, on purpose.** ``decode_rgb`` calls ``Image.convert("RGB")``, so an
    indexed PNG arrives at every caller as ordinary ``(256,256,3)`` uint8 RGB — the wire
    shape is unchanged. It costs ~6 KB per tile instead of ~108 KB, which is what keeps the
    committed set inside §13.2's budget.
    """
    from PIL import Image

    for z, x, y in COMMITTED_TILES:
        # Seed from (z, x, y) with hashlib, mirroring FixtureProvider's own rule.
        # ★ hashlib, never hash(): hash() of a str is salted per process (PYTHONHASHSEED),
        #   so a fixture seeded from it would differ between runs.
        digest = hashlib.sha256(f"{z}/{x}/{y}".encode()).digest()
        seed = int.from_bytes(digest[:8], "big") % (2**32)
        image = _farmland(
            TILE_SIZE,
            seed=seed,
            rows_deg=22.0 + (seed % 17),
            row_spacing_px=9.0 + (seed % 5),
            grain=0.0,
        )
        path = root / str(z) / str(x) / f"{y}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        quantised = Image.fromarray(image, mode="RGB").quantize(
            colors=64, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE
        )
        quantised.save(path, format="PNG", optimize=True)


# =============================================================================
# Slippy goldens (§13.3)
# =============================================================================


def _slippy_goldens() -> dict[str, Any]:
    """Build §13.3's golden table from the PUBLISHED formula, independently of ``gis``.

    ★ §13.3: "checked against published references, not against our own implementation".
    So these are computed here from the OSM wiki's reference formula and committed. A
    golden recomputed by the code under test proves only that the code agrees with itself.

    ★ **CONTRACT DEVIATION, VERIFIED BY HAND AND BY ARITHMETIC.** §13.3 states the London
    golden as ``TileRef(12, 2047, 1362)``. The x is wrong::

        x = (lon + 180) / 360 * 2**z = (-0.1278 + 180) / 360 * 4096 = 2046.5459... -> 2046

    Tile x=2046 spans lon [-0.17578125, -0.087890625); -0.1278 is inside it. x=2047 begins
    at -0.087890625, which is east of London. y=1362 is correct. The value committed here
    is **2046**. IU-09's ``test_tiles_math.py`` reached the same conclusion independently
    and documents it in the same terms; the two units agree, which is the only reason to
    trust either. Bending the implementation to satisfy the printed golden would inject a
    one-tile (~9.8 km at z12) error into every coordinate the product emits.
    """
    max_latitude = 85.0511287798066

    def deg2num(lon: float, lat: float, z: int) -> tuple[int, int]:
        n = 2**z
        clamped = max(-max_latitude, min(max_latitude, lat))
        x = int(math.floor((lon + 180.0) / 360.0 * n))
        y = int(
            math.floor((1.0 - math.asinh(math.tan(math.radians(clamped))) / math.pi) / 2.0 * n)
        )
        return max(0, min(n - 1, x)), max(0, min(n - 1, y))

    places = [
        ("London", -0.1278, 51.5074, 12),
        ("London z0", -0.1278, 51.5074, 0),
        ("Greenwich prime meridian, east side", 0.0001, 51.4779, 12),
        ("Greenwich prime meridian, west side", -0.0001, 51.4779, 12),
        ("New York", -74.0060, 40.7128, 12),
        ("Sydney", 151.2093, -33.8688, 12),
        ("Rio de Janeiro", -43.1729, -22.9068, 12),
        ("Nairobi", 36.8219, -1.2921, 12),
        ("Tokyo", 139.6917, 35.6895, 12),
        ("Cape Town", 18.4241, -33.9249, 12),
        ("Reykjavik", -21.8277, 64.1265, 12),
        ("Null Island", 0.0, 0.0, 1),
        ("Origin corner", -180.0, max_latitude, 1),
        ("Fixture ortho", ORTHO_LON, ORTHO_LAT, 16),
    ]

    tiles = []
    for name, lon, lat, z in places:
        x, y = deg2num(lon, lat, z)
        tiles.append({"name": name, "lon": lon, "lat": lat, "z": z, "x": x, "y": y})

    def quadkey(z: int, x: int, y: int) -> str:
        out = []
        for i in range(z, 0, -1):
            digit = 0
            mask = 1 << (i - 1)
            if x & mask:
                digit += 1
            if y & mask:
                digit += 2
            out.append(str(digit))
        return "".join(out)

    quadkeys = [
        {"z": z, "x": x, "y": y, "quadkey": quadkey(z, x, y)}
        for z, x, y in [(1, 0, 0), (1, 1, 0), (1, 0, 1), (1, 1, 1), (3, 3, 5), (2, 0, 0)]
    ]

    return {
        "_comment": (
            "Golden slippy values for §13.3, computed from the published OSM reference "
            "formula, NOT from gis.tiles. See _generate.py for the London x=2046 ruling "
            "(CONTRACT.md §13.3 misprints it as 2047)."
        ),
        "constants": {
            "EARTH_CIRCUMFERENCE_M": 40075016.685578488,
            "ORIGIN_SHIFT_M": 20037508.342789244,
            "MAX_LATITUDE": max_latitude,
            "RESOLUTION_Z0_256": 156543.03392804097,
        },
        "tiles": tiles,
        "quadkeys": quadkeys,
    }


# =============================================================================
# Driver
# =============================================================================


def generate(into: Path) -> None:
    """Write every fixture into ``into``."""
    into.mkdir(parents=True, exist_ok=True)
    _write_tif(into / "synthetic_ortho.tif", georeferenced=True)
    _write_tif(into / "plain.tif", georeferenced=False)
    _write_tiles(into / "tiles")
    (into / "slippy_goldens.json").write_text(
        json.dumps(_slippy_goldens(), indent=2) + "\n", encoding="utf-8"
    )


def verify(directory: Path) -> list[str]:
    """Read the fixtures back and assert the properties the suite depends on.

    ★ Written as a read-back rather than a claim: the geotransform is asserted to
    round-trip out of the committed bytes, because "I called SetGeoTransform" and "the file
    on disk carries that geotransform" are different statements and only the second one is
    what the tests load.

    Returns:
        A list of human-readable failures. Empty means the fixtures are sound.
    """
    from osgeo import gdal, osr

    # ★ EXPECTED NOISE, NOT A FAILURE. UseExceptions() does `from . import gdal_array`
    #   internally, and gdal_array is compiled against NumPy 1; under this machine's NumPy
    #   2.4 that import prints a multi-line "_ARRAY_API not found" block to stderr that
    #   looks exactly like a crash and is not one — GDAL carries on and exceptions are
    #   enabled. It is the same root cause as IU-10's "WriteRaster, never WriteArray" note.
    #   Enabling exceptions is worth the noise here: this script writes files that other
    #   units' suites assert against, and a silent GDAL error code would ship a bad fixture.
    gdal.UseExceptions()
    problems: list[str] = []

    # --- synthetic_ortho.tif --------------------------------------------------
    ds = gdal.Open(str(directory / "synthetic_ortho.tif"))
    gt = ds.GetGeoTransform()
    if tuple(gt) != ORTHO_GT:
        problems.append(f"ortho geotransform {tuple(gt)} != mandated {ORTHO_GT}")
    if (ds.RasterXSize, ds.RasterYSize) != (ORTHO_SIZE, ORTHO_SIZE):
        problems.append(f"ortho size {(ds.RasterXSize, ds.RasterYSize)} != 64x64")
    if ds.RasterCount != 3:
        problems.append(f"ortho band count {ds.RasterCount} != 3")
    if gdal.GetDataTypeName(ds.GetRasterBand(1).DataType) != "Byte":
        problems.append("ortho dtype is not uint8")
    srs = osr.SpatialReference(wkt=ds.GetProjection())
    code = srs.GetAuthorityCode(None)
    if code != str(ORTHO_EPSG):
        problems.append(f"ortho EPSG {code} != {ORTHO_EPSG}")
    for b in range(1, 4):
        if ds.GetRasterBand(b).GetNoDataValue() is not None:
            problems.append(f"ortho band {b} declares nodata; IU-10 asserts it does not")
    del ds

    # --- plain.tif ------------------------------------------------------------
    ds = gdal.Open(str(directory / "plain.tif"))
    gt = tuple(ds.GetGeoTransform())
    if gt != (0.0, 1.0, 0.0, 0.0, 0.0, 1.0):
        problems.append(f"plain.tif transform {gt} is not GDAL's identity — the trap is gone")
    if ds.GetProjection():
        problems.append("plain.tif carries a projection; it must carry none")
    del ds

    # --- tiles ----------------------------------------------------------------
    from PIL import Image

    for z, x, y in COMMITTED_TILES:
        path = directory / "tiles" / str(z) / str(x) / f"{y}.png"
        if not path.is_file():
            problems.append(f"missing tile {path}")
            continue
        with Image.open(path) as im:
            arr = np.asarray(im.convert("RGB"), dtype=np.uint8)
        if arr.shape != (TILE_SIZE, TILE_SIZE, 3):
            problems.append(f"tile {z}/{x}/{y} is {arr.shape}, expected (256,256,3)")

    # --- goldens --------------------------------------------------------------
    goldens = json.loads((directory / "slippy_goldens.json").read_text(encoding="utf-8"))
    london = next(t for t in goldens["tiles"] if t["name"] == "London")
    if (london["x"], london["y"]) != (2046, 1362):
        problems.append(f"London golden is {(london['x'], london['y'])}, expected (2046, 1362)")

    # --- size budget ----------------------------------------------------------
    total = sum(p.stat().st_size for p in directory.rglob("*") if p.is_file())
    if total > 200_000:
        problems.append(f"fixtures total {total} bytes, over the 200 KB budget")

    return problems


def main(argv: list[str] | None = None) -> int:
    """Regenerate (default) or check the committed fixtures."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="regenerate into a temp dir and diff against the committed bytes",
    )
    args = parser.parse_args(argv)

    if args.check:
        with tempfile.TemporaryDirectory() as tmp:
            fresh = Path(tmp)
            generate(fresh)
            drifted = [
                name
                for name in ("synthetic_ortho.tif", "plain.tif", "slippy_goldens.json")
                if not filecmp.cmp(fresh / name, HERE / name, shallow=False)
            ]
            for z, x, y in COMMITTED_TILES:
                rel = Path("tiles") / str(z) / str(x) / f"{y}.png"
                if not filecmp.cmp(fresh / rel, HERE / rel, shallow=False):
                    drifted.append(str(rel))
            if drifted:
                print("DRIFT: committed fixtures differ from a fresh generation:")
                for name in drifted:
                    print(f"  - {name}")
                return 1
        print("fixtures match a fresh generation")
        return 0

    generate(HERE)
    problems = verify(HERE)
    if problems:
        print("FIXTURES ARE NOT SOUND:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    total = sum(p.stat().st_size for p in HERE.rglob("*") if p.is_file() and p.suffix != ".py")
    print(f"fixtures regenerated and verified ({total} bytes total)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
