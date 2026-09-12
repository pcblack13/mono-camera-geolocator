# `gis` test fixtures — committed, offline, deterministic

Required by `CONTRACT.md` §13.2. **Committed to git on purpose**: they are what makes the
`gis` suite runnable with no network, no GPU, no weights and no database — on a plane, in
CI, and on a fresh clone.

Regenerate with:

```bash
python3 gis/src/gis/tests/fixtures/_generate.py          # rewrite + verify
python3 gis/src/gis/tests/fixtures/_generate.py --check  # diff vs committed (CI)
```

★ **Never regenerate at test time.** A fixture the suite rewrites before reading is not a
fixture — it is a mirror of whatever the code does today, and it cannot catch a regression
in the code that writes it. `_generate.py` is a developer tool; `conftest.py` only reads.

Total: **~42 KB** (budget: 500 KB in §13.2, 200 KB for this directory).

| File | Bytes | What it is | Why it exists |
|---|---:|---|---|
| `synthetic_ortho.tif` | 9 046 | 64×64, 3-band uint8, **EPSG:32633**, geotransform `(500000.0, 0.5, 0.0, 5000000.0, 0.0, -0.5)`, DEFLATE, **no nodata** | Backs `LocalOrthophotoProvider`, `detect_georeferencing() is True`, `gsd_of() == 0.5`, and the offline `gis` suite |
| `plain.tif` | 8 832 | 64×64, 3-band uint8, **no CRS, no geotransform** | ★ GDAL reports the identity transform `(0,1,0,0,0,1)` for it. **The difference between `is_geotiff` meaning something and marking every scanned TIFF as georeferenced at 0N 0E** |
| `tiles/{z}/{x}/{y}.png` | 5 × ~4 KB | 256×256 palettised PNG | Committed tiles for `FixtureProvider`; the reproducible offline demo scene |
| `slippy_goldens.json` | 2 800 | §13.3 golden tile numbers + quadkeys | Published reference values, **not** recomputed from `gis.tiles` |

## The geometry is load-bearing

`(500000.0, 0.5, 0.0, 5000000.0, 0.0, -0.5)` · EPSG:32633 · 64×64 are **not free to
change.** IU-10's `test_raster.py` and IU-11's `test_providers_contract.py` each hardcode
them *and read this file when it is present*. Changing any of them turns two other units'
suites red. `conftest.py` re-exports them as `ORTHO_GT` / `ORTHO_EPSG` / `ORTHO_SIZE` so new
tests import one definition rather than hand-copying a fifth.

500000 E is exactly UTM 33N's central meridian, so the ortho's top-left corner is exactly
**15.0000000 E, 45.1534772 N**. The committed tiles cover that same ground, so the demo
scene and the ortho are one place rather than two unrelated synthetic worlds.

## Two traps this directory is built around

1. **`osgeo.gdal_array` does not import under NumPy 2** on this machine, and `WriteArray`
   goes through it. Pixels are written with `WriteRaster(...tobytes())`. Calling
   `gdal.UseExceptions()` also triggers that import and prints an `_ARRAY_API not found`
   block to stderr that **looks exactly like a crash and is not one** — GDAL carries on.
2. **i.i.d. noise is incompressible.** At 256×256 a per-pixel grain of σ=3 inflates a PNG
   from ~4 KB to ~108 KB; five tiles alone then blow the whole §13.2 budget. The tiles use
   `grain=0.0` and take their variation from structure (parcels, crop rows, a track, a
   canal), then quantise to 64 colours. `decode_rgb` calls `.convert("RGB")`, so callers
   still receive ordinary `(256,256,3)` uint8 RGB.

## `slippy_goldens.json` — the London ruling

§13.3 prints the London golden as `TileRef(12, 2047, 1362)`. **The x is wrong**, by the
contract's own formula:

```
x = (lon + 180) / 360 * 2**z = (-0.1278 + 180) / 360 * 4096 = 2046.5459… → 2046
```

Tile x=2046 spans lon `[-0.17578125, -0.087890625)`, which contains -0.1278; x=2047 begins
at -0.087890625, east of London. `y=1362` is correct. **2046** is committed here. IU-09's
`test_tiles_math.py` reached the same conclusion independently and documents it in the same
terms — two units agreeing from first principles is the only reason to trust either.
Bending the implementation to satisfy a printed golden would inject a one-tile (~9.8 km at
z12) error into every coordinate the product emits.
