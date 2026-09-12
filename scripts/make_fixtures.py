#!/usr/bin/env python3
"""Generate the committed binary test fixtures. CONTRACT.md §13.2.

**Fixed seed. No network. Total output < 500 KB.** These fixtures are what make
the coordinate math verifiable without network, weights, or a GPU — so they are
generated deterministically and committed to git.

What this writes:

===========================================  ===========================================
``gis/tests/fixtures/synthetic_ortho.tif``   64x64, **EPSG:32633** (UTM 33N), known
                                             geotransform. §13.3 requires a < 1e-6 px
                                             round-trip on it — which the closed-form
                                             NumPy CRS fallback cannot do, and which is
                                             therefore the fixture that justifies
                                             ``gis.crs``'s osr path (§10.5).
``gis/tests/fixtures/plain.tif``             NO georeferencing. GDAL hands back the
                                             identity transform; ``detect_georeferencing``
                                             must say "not georeferenced" rather than
                                             believing the identity.
``gis/tests/fixtures/tiles/{z}/{x}/{y}.png`` Deterministic 256x256 slippy tiles. The
                                             offline front door: FixtureProvider serves
                                             these, so ``make seed && make up`` works
                                             with the NIC unplugged.
``data/fixtures/demo_scene.jpg``             A ground-level oblique "field photo" for
                                             the demo project (``seed_demo_data.py``).
===========================================  ===========================================

★ **Ownership note (CONTRACT.md §3).** ``gis/src/gis/tests/fixtures/**`` belongs to
IU-14 and ``ai_engine/tests/fixtures/`` to IU-08 — this script is only the
*generator*, mandated by §2.9. It therefore **refuses to overwrite an existing
file** unless ``--force``, so running it can never silently clobber a fixture a
unit hand-tuned. Point it elsewhere with ``--out-dir`` to inspect the output
without touching the tree.

Deps: numpy + PIL (base), osgeo/GDAL for the GeoTIFFs. All present on this
machine (§0.1), so unlike the compose files this script is actually testable here.

Usage::

    python3 scripts/make_fixtures.py                 # write the canonical paths
    python3 scripts/make_fixtures.py --out-dir /tmp/f --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent

# ★ THE SEED. Fixed, stated once, and the reason these files are reproducible.
SEED = 20260717

# --- synthetic_ortho.tif -----------------------------------------------------
# EPSG:32633 = WGS 84 / UTM zone 33N. Chosen because it is NOT 4326 and NOT 3857:
# it is the fixture that proves gis.crs can reach a projected CRS at all, which
# the closed-form NumPy fallback cannot (§10.5's crs.py exemption exists for it).
ORTHO_EPSG = 32633
ORTHO_SIZE = 64
# GDAL geotransform order: (origin_x, pixel_w, row_rot, origin_y, col_rot, pixel_h).
# North-up: row_rot = col_rot = 0 and pixel_h is NEGATIVE (y decreases downward).
# 0.5 m/px matches LE_SEARCH_TARGET_GSD_M so the fixture is realistic for the
# accuracy math that consumes it.
ORTHO_GEOTRANSFORM = (500000.0, 0.5, 0.0, 5000000.0, 0.0, -0.5)

TILE_SIZE = 256
# One small deterministic pyramid. z18 is LE_SEARCH_DEFAULT_ZOOM.
FIXTURE_TILES: tuple[tuple[int, int, int], ...] = (
    (16, 34952, 22550),
    (17, 69905, 45100),
    (18, 139810, 90200),
    (18, 139811, 90200),
    (18, 139810, 90201),
    (18, 139811, 90201),
)


def _farmland(
    height: int, width: int, rng: np.random.Generator, *, scale: float = 1.0
) -> np.ndarray:
    """Render procedural farmland: fields, crop rows, a road and a canal.

    Textured on purpose — a real extractor must find plenty of keypoints here, so
    that a blank-scene failure is distinguishable from a matcher failure. (In THIS
    build the extractors are deferred; the fixture is still generated because it
    costs nothing now and is the future engine's acceptance harness — SCOPE.md §4.)

    Args:
        height: Output rows.
        width: Output columns.
        rng: Seeded generator. The whole point of this module.
        scale: Multiplies feature sizes, so a 64 px ortho and a 256 px tile share
            a visual language without sharing pixel counts.

    Returns:
        ``(height, width, 3)`` uint8 RGB.
    """
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float64)
    img = np.zeros((height, width, 3), dtype=np.float64)

    # Field parcels: a low-frequency mosaic of differently-farmed rectangles.
    n_fields_y = max(2, int(4 * scale))
    n_fields_x = max(2, int(4 * scale))
    field_y = (yy / (height / n_fields_y)).astype(int)
    field_x = (xx / (width / n_fields_x)).astype(int)
    field_id = field_y * n_fields_x + field_x
    palette = rng.uniform(0.25, 0.75, size=(n_fields_y * n_fields_x, 3))
    palette[:, 1] *= 1.25  # vegetation: green channel dominates
    for fid in range(n_fields_y * n_fields_x):
        mask = field_id == fid
        img[mask] = palette[fid]

    # Crop rows: per-field direction and period. This is the high-frequency
    # texture that makes the fixture "textured enough" to be useful.
    for fid in range(n_fields_y * n_fields_x):
        mask = field_id == fid
        if not mask.any():
            continue
        theta = rng.uniform(0.0, np.pi)
        period = rng.uniform(3.0, 7.0) * scale
        proj = xx * np.cos(theta) + yy * np.sin(theta)
        rows = 0.10 * np.sin(2.0 * np.pi * proj / period)
        img[mask] += rows[mask, None]

    # A road (bright, straight) and a canal (dark, straight) — the ridge-like
    # linear features. They cross, giving a well-localised corner.
    road_y = height * rng.uniform(0.35, 0.65)
    road_w = max(1.0, 2.0 * scale)
    road = np.exp(-(((yy - road_y) / road_w) ** 2))
    img += road[..., None] * np.array([0.35, 0.32, 0.28])

    canal_x = width * rng.uniform(0.35, 0.65)
    canal_w = max(1.0, 1.5 * scale)
    canal = np.exp(-(((xx - canal_x) / canal_w) ** 2))
    img -= canal[..., None] * np.array([0.25, 0.20, 0.05])

    # Sensor noise. Small, but it keeps the fixture from being pathologically clean.
    img += rng.normal(0.0, 0.015, size=img.shape)

    return (np.clip(img, 0.0, 1.0) * 255.0).astype(np.uint8)


def _write_geotiff(
    path: Path, array: np.ndarray, *, epsg: int | None, geotransform: tuple[float, ...] | None
) -> None:
    """Write an RGB uint8 GeoTIFF via GDAL.

    Args:
        path: Destination.
        array: ``(H,W,3)`` uint8.
        epsg: Native CRS code, or ``None`` to write NO georeferencing at all
            (the ``plain.tif`` case — GDAL will report the identity transform,
            and detecting that honestly is the point of the fixture).
        geotransform: 6-element GDAL-order transform, or ``None``.
    """
    from osgeo import gdal, osr  # noqa: PLC0415 — call-time bound (§11.3)

    # ★★ DO NOT "SIMPLIFY" THIS TO WriteArray(). VERIFIED ON THIS MACHINE:
    #
    #    osgeo.gdal_array — GDAL's NumPy bridge — is compiled against NumPy 1.x and
    #    is BROKEN under the NumPy 2.4.3 installed here:
    #        ImportError: numpy.core.multiarray failed to import
    #    so band.WriteArray(...) and band.ReadAsArray(...) BOTH FAIL. So does
    #    gdal.UseExceptions(), which imports gdal_array internally — the very call
    #    the GDAL docs tell you to make first.
    #
    #    GDAL's CORE is fine: Create/Open, SetGeoTransform, SetProjection and the
    #    RAW BYTE interface (WriteRaster/ReadRaster) all work perfectly and
    #    round-trip exactly. So we go through bytes and let NumPy do the framing
    #    itself. §0.1's "Raster IO works today without rasterio" is true ONLY via
    #    this path.
    #
    #    This is why UseExceptions() is not called here and errors are checked by
    #    return value instead.
    height, width, bands = array.shape
    driver = gdal.GetDriverByName("GTiff")
    # DEFLATE: keeps the committed bytes small (§13.2's < 500 KB budget).
    dataset = driver.Create(
        str(path), width, height, bands, gdal.GDT_Byte, options=["COMPRESS=DEFLATE", "TILED=NO"]
    )
    if dataset is None:
        msg = f"GDAL could not create {path}"
        raise OSError(msg)
    try:
        if geotransform is not None:
            dataset.SetGeoTransform(list(geotransform))
        if epsg is not None:
            srs = osr.SpatialReference()
            srs.ImportFromEPSG(epsg)
            dataset.SetProjection(srs.ExportToWkt())
        for band_index in range(bands):
            band = dataset.GetRasterBand(band_index + 1)
            # np.ascontiguousarray: tobytes() on a sliced view would otherwise
            # silently serialise the wrong stride order.
            plane = np.ascontiguousarray(array[:, :, band_index], dtype=np.uint8)
            band.WriteRaster(0, 0, width, height, plane.tobytes())
        dataset.FlushCache()
    finally:
        dataset = None  # noqa: F841 — GDAL closes on dereference; this IS the close


def _write_png(path: Path, array: np.ndarray, *, colours: int = 64) -> None:
    """Write an RGB uint8 PNG via PIL, palette-quantised to fit §13.2's size budget.

    ★ The quantisation is not cosmetic — it is what keeps these files committable.
    §13.2 budgets **< 500 KB for every committed fixture combined**. Truecolour PNGs
    of this scene run ~130 KB *each* (the per-pixel sensor noise is essentially
    incompressible), which blows the budget six times over on the tiles alone.
    A 64-colour palette costs nothing that matters here — the fields, crop rows,
    road and canal all survive, so the fixture is still richly textured — and it
    cuts each tile by roughly 5x.

    MEDIANCUT with a fixed palette size is deterministic, so the committed bytes
    stay reproducible (which is the entire contract of this module).

    Args:
        path: Destination.
        array: ``(H,W,3)`` uint8 RGB.
        colours: Palette size.
    """
    from PIL import Image  # noqa: PLC0415

    rgb = Image.fromarray(array, mode="RGB")
    quantised = rgb.quantize(colors=colours, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    quantised.save(path, format="PNG", optimize=True)


def _write_jpeg(path: Path, array: np.ndarray, *, quality: int = 82) -> None:
    """Write an RGB uint8 JPEG via PIL."""
    from PIL import Image  # noqa: PLC0415

    Image.fromarray(array, mode="RGB").save(path, format="JPEG", quality=quality, optimize=True)


class FixtureWriter:
    """Writes fixtures, refusing to clobber. Tracks what it did for the summary."""

    def __init__(self, out_dir: Path, *, force: bool) -> None:
        self.out_dir = out_dir
        self.force = force
        self.written: list[Path] = []
        self.skipped: list[Path] = []

    def target(self, rel: str) -> Path | None:
        """Resolve ``rel`` under the output dir, or ``None`` if it must not be written."""
        path = self.out_dir / rel
        if path.exists() and not self.force:
            self.skipped.append(path)
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def record(self, path: Path) -> None:
        """Note that ``path`` was written."""
        self.written.append(path)


def make_orthos(writer: FixtureWriter) -> None:
    """Write ``synthetic_ortho.tif`` (EPSG:32633) and ``plain.tif`` (no CRS)."""
    rng = np.random.default_rng(SEED)
    pixels = _farmland(ORTHO_SIZE, ORTHO_SIZE, rng, scale=0.25)

    ortho = writer.target("gis/src/gis/tests/fixtures/synthetic_ortho.tif")
    if ortho is not None:
        _write_geotiff(ortho, pixels, epsg=ORTHO_EPSG, geotransform=ORTHO_GEOTRANSFORM)
        writer.record(ortho)

    # ★ plain.tif is the SAME pixels with the georeferencing removed. Same bytes,
    #   different metadata: any test that passes on one and fails on the other has
    #   isolated georeferencing as the cause, not content.
    plain = writer.target("gis/src/gis/tests/fixtures/plain.tif")
    if plain is not None:
        _write_geotiff(plain, pixels, epsg=None, geotransform=None)
        writer.record(plain)


def make_tiles(writer: FixtureWriter) -> None:
    """Write the deterministic fixture tile pyramid.

    Each tile's content is seeded from its own ``(z, x, y)``, so a tile is
    reproducible in isolation and two different addresses can never collide into
    identical bytes — which would make a tile-addressing bug invisible.
    """
    for z, x, y in FIXTURE_TILES:
        rel = f"gis/src/gis/tests/fixtures/tiles/{z}/{x}/{y}.png"
        path = writer.target(rel)
        if path is None:
            continue
        rng = np.random.default_rng(SEED + z * 1_000_003 + x * 1_009 + y)
        # Coarser features at low zoom, finer at high zoom — visually plausible.
        pixels = _farmland(TILE_SIZE, TILE_SIZE, rng, scale=1.0 + (z - 16) * 0.35)
        _write_png(path, pixels)
        writer.record(path)


def make_demo_scene(writer: FixtureWriter) -> None:
    """Write the demo "field photo" used by ``seed_demo_data.py``.

    A ground-level **oblique** view: the top of the frame is compressed toward a
    horizon. That obliqueness is not decoration — it is the exact property that
    makes automatic homography matching unreliable and that SCOPE.md §2 cites as
    the reason the automatic engine is deferred in favour of manual GCP placement.
    """
    path = writer.target("data/fixtures/demo_scene.jpg")
    if path is None:
        return
    rng = np.random.default_rng(SEED + 7)
    height, width = 720, 1280
    plan = _farmland(height, width, rng, scale=2.0)

    # Warp to an oblique view: compress rows toward the horizon at y = h/3.
    horizon = height / 3.0
    out = np.zeros_like(plan)
    rows = np.arange(height, dtype=np.float64)
    # Rows above the horizon are sky; below, perspective foreshortening.
    depth = np.clip((rows - horizon) / (height - horizon), 1e-3, None)
    src_rows = np.clip(horizon + (height - horizon) * depth**2.2, 0, height - 1).astype(int)
    for dst_y in range(height):
        if rows[dst_y] < horizon:
            continue
        # Horizontal convergence toward the vanishing point at x = w/2.
        squeeze = depth[dst_y]
        cols = np.arange(width, dtype=np.float64)
        src_cols = np.clip(
            width / 2.0 + (cols - width / 2.0) / max(squeeze, 0.05), 0, width - 1
        ).astype(int)
        out[dst_y] = plan[src_rows[dst_y]][src_cols]

    # Sky above the horizon: a simple gradient. Featureless on purpose.
    sky_rows = int(horizon)
    grad = np.linspace(0.0, 1.0, sky_rows)[:, None]
    sky = (1.0 - grad) * np.array([120.0, 160.0, 210.0]) + grad * np.array([200.0, 215.0, 235.0])
    out[:sky_rows] = np.clip(sky[:, None, :], 0, 255).astype(np.uint8)

    _write_jpeg(path, out)
    writer.record(path)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="make_fixtures.py",
        description="Generate the committed test fixtures (CONTRACT.md §13.2). "
        "Fixed seed, no network.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=REPO_ROOT,
        help="root to write under (default: the repo root, i.e. the canonical paths)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing fixtures. Off by default: gis/tests/fixtures belongs to "
        "IU-14 and ai_engine/tests/fixtures to IU-08 (§3), and this script is only their "
        "generator — it must never silently clobber a hand-tuned fixture.",
    )
    args = parser.parse_args(argv)

    try:
        import numpy  # noqa: F401, PLC0415
        from osgeo import gdal  # noqa: F401, PLC0415
        from PIL import Image  # noqa: F401, PLC0415
    except ImportError as exc:
        print(f"make_fixtures: missing a generator dependency: {exc}", file=sys.stderr)
        print("  Needs numpy + PIL + osgeo. All three are system packages here (§0.1);", file=sys.stderr)
        print("  if they are invisible, your venv lacks --system-site-packages.", file=sys.stderr)
        return 2

    writer = FixtureWriter(args.out_dir, force=args.force)
    make_orthos(writer)
    make_tiles(writer)
    make_demo_scene(writer)

    committed = 0
    total = 0
    for path in writer.written:
        size = path.stat().st_size
        total += size
        rel = path.relative_to(args.out_dir)
        # data/ is gitignored (§2.10), so it does not count against §13.2's budget
        # for COMMITTED fixtures. Only the tree that git actually carries does.
        is_committed = not str(rel).startswith("data/")
        if is_committed:
            committed += size
        print(f"  wrote {rel}  ({size:,} B){'' if is_committed else '  [gitignored]'}")
    for path in writer.skipped:
        print(f"  kept  {path.relative_to(args.out_dir)}  (exists — pass --force to regenerate)")

    if writer.written:
        print(f"\n  {len(writer.written)} file(s), {total:,} B written.")
        print(f"  {committed:,} B of that is COMMITTED to git (§13.2 budget: < 500,000 B).")
        # ★ Enforced, not merely mentioned. A budget nobody checks is a wish.
        if committed > 500_000:
            print(
                f"\n  \033[31m✘ OVER BUDGET: {committed:,} B > 500,000 B (§13.2).\033[0m",
                file=sys.stderr,
            )
            print(
                "    Shrink the palette in _write_png() or drop a tile — do not raise the\n"
                "    budget. These files live in git forever.",
                file=sys.stderr,
            )
            return 1
    if writer.skipped and not writer.written:
        print("\n  Nothing written — everything already exists. Use --force to regenerate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
