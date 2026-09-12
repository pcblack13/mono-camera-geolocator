# `landexplorer-gis`

The geospatial layer of LandExplorer. **`ai_engine` ends at pixels; this package is the
only place a coordinate is born.**

Everything that turns a window pixel into a survey claim — the geotransform, the CRS, the
metres, the North, the elevation — lives here and nowhere else. It has no FastAPI, no
SQLAlchemy, and no CV algorithms.

```
window pixel --(+0.5)--> geotransform --> srid --> EPSG:4326 --> gcps.geom
cov_px --x gsd_m^2--> TRUE metres --> CE90 + error ellipse
yaw_window --+ grid convergence--> yaw_true_north
```

## Install

```bash
pip install -e ./gis --no-deps      # numpy, PIL, httpx are system-site on the dev box
pip install -e ./gis[dev] --no-deps # + pytest, hypothesis, mypy, ruff
```

Extras: `[pyproj]` `[rasterio]` `[redis]` `[exports]` `[dev]`.

> **On the dev box `pyproj` is absent and GDAL is present.** That is a supported
> configuration, not a broken one — see *Optional dependencies* below.

## The five rules

**1. Never measure in EPSG:4326.** Degrees are not a length unit. One degree of longitude
is 111 km at the equator, 64 km at 55N and 0 at the pole.

**2. Never measure in EPSG:3857.** Web Mercator metres are **not metres**. They are
inflated by `1/cos(phi)`:

| Latitude | 100 m of ground measures |
|---|---|
| 0 | 100.0 m |
| 45 | 141.4 m |
| **55** (Yorkshire, Denmark, S. Sweden, the Canadian prairies) | **174.3 m** |
| 60 | 200.0 m |

3857 is a **pixel-addressing scheme**, not a measurement system. Every reported distance,
area and RMSE is computed in UTM. `distance_m` and `polygon_area_m2` **refuse** a
non-ground-metric CRS rather than return a number that looks like metres and isn't.

**3. Pixel coordinates are pixel CENTRES.**

```python
X = gt[0] + (col + 0.5) * gt[1] + (row + 0.5) * gt[2]
```

The `+0.5` is not pedantry. Omitting it biases *every* GCP by half a pixel, consistently in
one direction (~0.21 m at z18/45N). That is a **systematic bias, not noise** — it does not
average out, and at the 0.5 m GCP-consistency tolerance it spuriously rejects correct
edits. `lonlat_to_pixel` is the exact inverse, including the `-0.5`.
`invert_geotransform` is the plain affine (EDGE) inverse and is **never** for GCP work.

**4. Tile `y` increases SOUTHWARD.** Slippy/XYZ, `y = 0` at the north edge. TMS flips it;
we never do.

**5. `always_xy=True`, always.** EPSG:4326's authority-defined axis order is
(latitude, longitude), and pyproj honours it by default. A transformer built without
`always_xy` reads your longitude as a latitude and returns *plausible numbers for the wrong
place on Earth* — in a GCP product, the most expensive bug available, because the surveyor
drives to the wrong field. `gis/crs.py` is the only module that may construct a
transformer, and it only ever builds always-xy ones. The mistake is unreachable rather than
documented.

## Layout

| Module | Responsibility |
|---|---|
| `tiles.py` | **The foundation.** Slippy math, quadkeys, closed-form 4326<->3857, stitching, geotransforms, pixel<->lonlat, metres-per-pixel, zoom selection. **numpy + stdlib only. No I/O, no optional deps.** |
| `crs.py` | **The only `pyproj`/`osgeo.osr` import site.** UTM zone selection, cached always-xy transformers. |
| `geometry.py` | Box algebra, true-metre distance/area/buffer, antimeridian splitting. |
| `accuracy.py` | **The single producer of `AccuracyEstimate`.** px -> metres, CE90, the error ellipse. |
| `pose.py` | Window-frame pose -> geography: geotransform rotation + **grid convergence**. |
| `heatmap.py` | Per-window pixel heatmaps -> one true-metre geographic grid. |
| `exif.py` | EXIF GPS extraction, DOP parsing, radius inflation. |
| `elevation/` | lon/lat -> elevation + vertical CE90. **`none` is the keyless default.** |
| `imagery/` | Providers, tile cache, attribution — **the legal boundary**. |
| `candidates/` | Search hints, plans, and the `WindowSource` seam into `ai_engine`. |
| `exports/` | GCP records -> CSV/GeoJSON/KML/Shapefile/PDF. |
| `raster.py`, `rasterio_shim.py` | Windowed reads via rasterio-or-GDAL. |

`gis/__init__.py` re-exports only the pure value types, errors and config. It deliberately
does **not** import `imagery` (httpx), `exif` (PIL) or `crs` (pyproj/osgeo) — `import
gis.tiles` runs it first, and `tiles` must stay dependency-free. Import the submodule you
need.

## Accuracy, and what this build actually reports

**CE90 and only CE90**, on every field of `AccuracyEstimate`. `confidence_level` ships on
the type so a number can never be read at the wrong level.

For the record, because this is where the mistake gets made: **2-sigma on the semi-major of
a 2-D error ellipse is ~86.5%, not 95%.** The 2-D 95% radius is 2.448 sigma; the 90% radius
is 2.146 sigma.

In this build a GCP is a **manual, direct observation** (see `docs/architecture/SCOPE.md`),
so its accuracy comes from imagery GSD and click precision — not from a homography
covariance and not from a match score:

```python
from gis.accuracy import manual_gcp_accuracy
from gis.tiles import resolution_at

est = manual_gcp_accuracy(
    gsd_m=resolution_at(18, 55.0),   # 0.343 m/px — cos-corrected TRUE ground metres
    georef_ce90_m=3.0,               # the provider's own georeferencing error
    click_sigma_px=3.0,              # surveyor click precision, 1-sigma
)
est.total_ce90_m      # 3.72 m
est.dominant_term     # 'georeference'  <- the imagery, not the surveyor, is the limit
```

`dominant_term` is the actionable part: it tells a user whether a steadier hand or better
imagery is the way forward. **`confidence` is surveyor-declared and is never computed** —
`AccuracyEstimate` has no such field, so the mistake is unrepresentable.

## Optional dependencies (`CONTRACT.md` §11.3)

**A missing optional dependency is a WARNING and a fallback — never a traceback and never
silent.** Any module whose dependency is not in the base install binds it **inside the
function that uses it**, never at module scope, so `is_configured()` / `capabilities()` /
`probe()` are callable with the dependency absent.

`crs.py` binds **pyproj -> osgeo.osr -> closed-form NumPy** (4326<->3857 only) -> typed
`CrsBackendUnavailable` at *call* time.

```python
from gis.crs import probe
probe()   # 'crs backend: osgeo.osr (full)'  on the dev box
```

> ⚠️ **A container with neither pyproj nor GDAL can only do 4326<->3857.** UTM metrics are
> then uncomputable — which means `total_ce90_m`, mandatory on every GCP, is uncomputable,
> and `local_orthophoto` is dead. That must be **loud**, not silently accurate-to-nothing:
> `probe()` says so and `/health/ready` and `GET /capabilities` surface it. The backend
> image pins `pyproj` and installs `libgdal-dev` for exactly this reason.

## Tests

```bash
pip install -e ./gis[dev] --no-deps
cd gis && pytest
```

**No network, ever** — the fixture provider and a committed 64x64 GeoTIFF cover every path.

The golden-value tests in `test_tiles_math.py` are the product's safety net for every
coordinate it will ever emit. They are checked against **published references and
first-principles arithmetic, never against our own implementation** — a test written to
agree with the code it tests proves only that the code is self-consistent.

Known-value anchors:

- `lonlat_to_tile(-0.1278, 51.5074, 12) == TileRef(12, 2046, 1362)` (London)
- `resolution_at(18, 55.0) == 0.34251936163340246`
- `zoom_for_resolution(0.5, 45.0, 512) == 17` vs `(0.5, 45.0, 256) == 18`
- `utm_epsg_for(180.0, 45.0) == "EPSG:32660"`, `(-180.0, 45.0) == "EPSG:32601"`
- `cov_px = I2` at z18/55N ⇒ `sqrt(lambda_max) == 0.34251936163340246`
