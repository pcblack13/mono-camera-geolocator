"""IU-10 · ``gis.rasterio_shim`` + ``gis.raster``.

★ The obligations this suite discharges (§13.1 IU-10):

* ``rasterio_shim`` binds at **call** time, not import: with rasterio absent,
  ``import gis.raster`` **succeeds** and the GDAL path is used.
* With **both** absent, the call raises ``RasterBackendUnavailable`` — a **typed error**,
  not an ``ImportError``.
* ★ ``detect_georeferencing()`` returns **False** for a plain TIFF carrying GDAL's identity
  transform **and True for the committed synthetic GeoTIFF** — *the exact distinction that
  decides ``images.is_geotiff``*, and in this build the distinction that decides whether an
  upload short-circuits to exact GCPs.
* Windowed reads honour nodata.

The fixtures ``synthetic_ortho.tif`` (64x64, EPSG:32633) and ``plain.tif`` (no
georeferencing) are IU-14's, under ``gis/tests/fixtures/``. ★ This module **generates
equivalents locally when they are absent**, so IU-10 is verifiable before IU-14 lands and
so a fixture regeneration cannot silently gut this suite. When the committed fixtures
exist, they are used and take precedence.

NO NETWORK. Every test here is filesystem-local.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from gis import rasterio_shim
from gis.errors import RasterBackendUnavailable
from gis.raster import (
    bounds_of,
    detect_georeferencing,
    gsd_of,
    overview_for_scale,
    read_meta,
    read_overview,
    windowed_read,
)
from gis.rasterio_shim import IDENTITY_GEOTRANSFORM

_FIXTURES = Path(__file__).parent / "fixtures"

_ORTHO_GT = (500000.0, 0.5, 0.0, 5000000.0, 0.0, -0.5)
_ORTHO_EPSG = 32633
_ORTHO_SIZE = 64


requires_backend = pytest.mark.skipif(
    not rasterio_shim.is_available(),
    reason="no raster backend (neither rasterio nor GDAL); the shim reports it honestly",
)


# --- Fixtures ----------------------------------------------------------------


def _write_geotiff(
    path: Path, *, georeferenced: bool, size: int = _ORTHO_SIZE, nodata: float | None = None
) -> Path:
    """Write a small GeoTIFF with GDAL, with or without georeferencing.

    ★ Pixels are written with ``WriteRaster`` (bytes), never ``WriteArray``:
    ``osgeo.gdal_array`` does not import under NumPy 2 on this machine. See
    ``gis/rasterio_shim.py``'s header. This helper would otherwise fail at collection on
    the only box we can test on.
    """
    gdal = pytest.importorskip("osgeo.gdal", reason="fixture generation needs GDAL")
    osr = pytest.importorskip("osgeo.osr", reason="fixture generation needs GDAL")

    driver = gdal.GetDriverByName("GTiff")
    dataset = driver.Create(str(path), size, size, 3, gdal.GDT_Byte)
    if georeferenced:
        dataset.SetGeoTransform(_ORTHO_GT)
        spatial_ref = osr.SpatialReference()
        spatial_ref.ImportFromEPSG(_ORTHO_EPSG)
        dataset.SetProjection(spatial_ref.ExportToWkt())
    rng = np.random.default_rng(1234)
    for band_index in range(1, 4):
        band = dataset.GetRasterBand(band_index)
        data = rng.integers(1, 255, (size, size), dtype=np.uint8)
        if nodata is not None:
            # ★ Actually PLANT nodata pixels. Without this the raster would contain no
            #   nodata at all and test_windowed_read_honours_nodata would pass vacuously —
            #   the most dangerous kind of green test.
            data[: size // 4, :] = np.uint8(nodata)
            band.SetNoDataValue(nodata)
        band.WriteRaster(0, 0, size, size, data.tobytes())
    dataset.FlushCache()
    del dataset
    return path


@pytest.fixture(scope="module")
def ortho_tif(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A 64x64 EPSG:32633 GeoTIFF with a known geotransform.

    Prefers IU-14's committed fixture; generates an equivalent when it is absent.
    """
    committed = _FIXTURES / "synthetic_ortho.tif"
    if committed.is_file():
        return committed
    return _write_geotiff(
        tmp_path_factory.mktemp("raster") / "synthetic_ortho.tif", georeferenced=True
    )


@pytest.fixture(scope="module")
def plain_tif(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """★ A TIFF with NO georeferencing — the identity-transform trap."""
    committed = _FIXTURES / "plain.tif"
    if committed.is_file():
        return committed
    return _write_geotiff(tmp_path_factory.mktemp("raster") / "plain.tif", georeferenced=False)


# --- The shim ----------------------------------------------------------------


def test_shim_imports_without_any_backend() -> None:
    """★ Importing the shim binds NOTHING. The whole point of §11.3.

    If this module reached ``import rasterio`` or ``from osgeo import gdal`` at module
    scope, ``gis.raster``, ``gis.elevation.local_dem`` and ``local_orthophoto`` would all
    die at import on a machine missing that library — and the gis suite would die at
    COLLECTION, before a single test ran.
    """
    import importlib

    module = importlib.import_module("gis.rasterio_shim")
    assert module is not None


def test_probe_is_total_and_stable() -> None:
    """``probe()`` never raises and reports one of exactly three answers."""
    backend = rasterio_shim.probe()
    assert backend in ("rasterio", "gdal", "none")
    assert rasterio_shim.probe() == backend, "probe() must be stable within a process"
    assert rasterio_shim.is_available() == (backend != "none")


def test_probe_reports_a_reason_only_when_unavailable() -> None:
    """★ ``/health/ready`` and ``GET /capabilities`` surface this. It must be coherent."""
    if rasterio_shim.is_available():
        assert rasterio_shim.backend_reason() is None
    else:
        reason = rasterio_shim.backend_reason()
        assert reason and ("rasterio" in reason or "GDAL" in reason)


def test_no_backend_raises_a_typed_error_not_an_import_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """★ With BOTH backends absent, the CALL raises ``RasterBackendUnavailable``.

    A typed ``gis`` error naming the dependency that would fix it — never a bare
    ``ImportError``. A caller handling ``GisError`` must not also have to handle our import
    failures.
    """
    monkeypatch.setattr(rasterio_shim, "_backend_name", None, raising=False)
    monkeypatch.setattr(rasterio_shim, "_backend_module", None, raising=False)
    monkeypatch.setattr(rasterio_shim, "_backend_reason", None, raising=False)
    monkeypatch.setitem(__import__("sys").modules, "rasterio", None)
    monkeypatch.setitem(__import__("sys").modules, "osgeo", None)
    monkeypatch.setitem(__import__("sys").modules, "osgeo.gdal", None)

    assert rasterio_shim.probe() == "none"
    assert rasterio_shim.is_available() is False
    reason = rasterio_shim.backend_reason()
    assert reason and "rasterio" in reason

    with pytest.raises(RasterBackendUnavailable):
        rasterio_shim.open_dataset(str(tmp_path / "anything.tif"))

    # Reset so the module-scoped memo does not leak into the rest of the suite.
    monkeypatch.undo()
    rasterio_shim._backend_name = None  # noqa: SLF001
    rasterio_shim._backend_module = None  # noqa: SLF001
    rasterio_shim._backend_reason = None  # noqa: SLF001


# --- detect_georeferencing: THE distinction ----------------------------------


@requires_backend
def test_detect_georeferencing_true_for_the_synthetic_geotiff(ortho_tif: Path) -> None:
    """★ A real GeoTIFF is recognised. In this build that means EXACT GCPs, no matching."""
    report = detect_georeferencing(str(ortho_tif))

    assert report.is_georeferenced is True
    assert bool(report) is True
    assert report.crs is not None
    assert "32633" in report.crs
    assert report.is_identity_transform is False
    assert report.reason


@requires_backend
def test_detect_georeferencing_false_for_a_plain_tiff(plain_tif: Path) -> None:
    """★★ THE TEST THIS MODULE EXISTS FOR.

    GDAL hands back the **identity transform** ``(0, 1, 0, 0, 0, 1)`` for a raster with no
    georeferencing. Believing it places the image at **0N 0E with one-degree pixels** — the
    Gulf of Guinea, at continental scale — and marks every scanned TIFF as georeferenced.

    This assertion is the difference between ``is_geotiff`` meaning something and meaning
    nothing.
    """
    report = detect_georeferencing(str(plain_tif))

    assert report.is_georeferenced is False
    assert bool(report) is False
    assert report.crs is None
    assert report.reason


@requires_backend
def test_the_identity_transform_is_actually_what_gdal_returns(plain_tif: Path) -> None:
    """Pin the trap itself, so a backend change that alters it is caught HERE.

    ★ If GDAL ever stopped returning the identity transform for an ungeoreferenced file,
    ``detect_georeferencing`` would still be correct — but this test documents *why* the
    function is shaped the way it is, and fails loudly if the premise moves.
    """
    report = detect_georeferencing(str(plain_tif))
    assert report.geotransform == IDENTITY_GEOTRANSFORM
    assert report.is_identity_transform is True


def test_detect_georeferencing_never_raises(tmp_path: Path) -> None:
    """★ It runs during ingest of a file a user just uploaded.

    A traceback there tells the surveyor nothing. Every unreadable input is an honest
    "not georeferenced, and here is why".
    """
    not_a_raster = tmp_path / "notes.txt"
    not_a_raster.write_text("this is not a raster")

    for candidate in (not_a_raster, tmp_path / "does_not_exist.tif", tmp_path):
        report = detect_georeferencing(str(candidate))
        assert report.is_georeferenced is False
        assert report.reason


@requires_backend
def test_detect_georeferencing_rejects_a_degenerate_transform(tmp_path: Path) -> None:
    """A CRS plus a zero-area-pixel transform is not georeferencing."""
    gdal = pytest.importorskip("osgeo.gdal")
    osr = pytest.importorskip("osgeo.osr")

    path = tmp_path / "degenerate.tif"
    dataset = gdal.GetDriverByName("GTiff").Create(str(path), 8, 8, 1, gdal.GDT_Byte)
    dataset.SetGeoTransform((500000.0, 0.0, 0.0, 5000000.0, 0.0, 0.0))  # singular
    spatial_ref = osr.SpatialReference()
    spatial_ref.ImportFromEPSG(_ORTHO_EPSG)
    dataset.SetProjection(spatial_ref.ExportToWkt())
    dataset.FlushCache()
    del dataset

    report = detect_georeferencing(str(path))
    assert report.is_georeferenced is False
    assert "degenerate" in report.reason or "singular" in report.reason


# --- Metadata ----------------------------------------------------------------


@requires_backend
def test_read_meta_of_the_geotiff(ortho_tif: Path) -> None:
    """``RasterMeta`` reports the file, exactly."""
    meta = read_meta(str(ortho_tif))

    assert meta.width == _ORTHO_SIZE
    assert meta.height == _ORTHO_SIZE
    assert meta.band_count == 3
    assert meta.is_georeferenced is True
    assert meta.crs is not None
    assert meta.dtype == "uint8"
    assert meta.geotransform[1] > 0
    assert meta.geotransform[5] < 0, "north-up rasters have a negative pixel height"


@requires_backend
def test_read_meta_of_a_plain_tiff_reports_no_crs(plain_tif: Path) -> None:
    """★ ``crs`` is None, not "EPSG:4326". None is the honest answer."""
    meta = read_meta(str(plain_tif))
    assert meta.is_georeferenced is False
    assert meta.crs is None


@requires_backend
def test_bounds_of_a_plain_tiff_is_none(plain_tif: Path) -> None:
    """★ No footprint from a file with no georeferencing — not a footprint at 0N 0E."""
    bbox, crs = bounds_of(str(plain_tif))
    assert bbox is None
    assert crs is None


@requires_backend
def test_bounds_of_the_geotiff_are_in_4326(ortho_tif: Path) -> None:
    """The footprint comes back in EPSG:4326, reprojected from the file's UTM zone."""
    bbox, crs = bounds_of(str(ortho_tif))
    if bbox is None:
        pytest.skip("no CRS backend can transform EPSG:32633 -> EPSG:4326 here")

    assert crs is not None and "32633" in crs
    assert -180.0 <= bbox.west <= 180.0
    assert -90.0 <= bbox.south <= 90.0
    assert bbox.west < bbox.east
    assert bbox.south < bbox.north
    # UTM 33N at 5 000 000 N / 500 000 E is central Europe, near 15E / 45N.
    assert 10.0 < bbox.west < 20.0
    assert 40.0 < bbox.south < 50.0


@requires_backend
def test_gsd_of_a_utm_geotiff_is_the_pixel_size(ortho_tif: Path) -> None:
    """★ For a metric CRS the pixel size IS ground metres — no cos(phi) correction."""
    gsd = gsd_of(str(ortho_tif))
    if gsd is None:
        pytest.skip("no CRS backend can classify EPSG:32633 here")
    assert gsd == pytest.approx(abs(_ORTHO_GT[1]), rel=1e-6)


@requires_backend
def test_gsd_of_a_plain_tiff_is_none(plain_tif: Path) -> None:
    """No georeferencing means no ground sample distance. None, never a fabricated number."""
    assert gsd_of(str(plain_tif)) is None


# --- Windowed reads ----------------------------------------------------------


@requires_backend
def test_windowed_read_returns_the_window(ortho_tif: Path) -> None:
    """A window read returns exactly the requested pixels."""
    data, _gt = windowed_read(str(ortho_tif), (10, 20, 8, 6), indexes=1)

    assert data.shape == (6, 8), "shape is (height, width)"
    assert data.dtype == np.uint8
    assert data.flags["C_CONTIGUOUS"]


@requires_backend
def test_windowed_read_folds_the_offset_into_the_origin(ortho_tif: Path) -> None:
    """★★ THE FOLD. A window's geotransform points at the WINDOW, not at the file.

    A windowed read whose transform still points at the file's origin produces coordinates
    wrong by the window offset while crashing nothing and looking entirely plausible.
    """
    col_off, row_off = 10, 20
    _data, gt = windowed_read(str(ortho_tif), (col_off, row_off, 8, 6), indexes=1)

    assert gt[0] == pytest.approx(_ORTHO_GT[0] + col_off * _ORTHO_GT[1])
    assert gt[3] == pytest.approx(_ORTHO_GT[3] + row_off * _ORTHO_GT[5])
    assert gt[1] == pytest.approx(_ORTHO_GT[1]), "pixel size is unchanged by an offset"
    assert gt[5] == pytest.approx(_ORTHO_GT[5])


@requires_backend
def test_windowed_read_scales_the_transform_when_decimating(ortho_tif: Path) -> None:
    """★ ``out_shape`` halves the read, so the geotransform's pixel size doubles.

    The transform must describe the pixels RETURNED, not the pixels on disk.
    """
    _data, gt = windowed_read(
        str(ortho_tif), (0, 0, _ORTHO_SIZE, _ORTHO_SIZE), indexes=1, out_shape=(32, 32)
    )

    assert gt[0] == pytest.approx(_ORTHO_GT[0]), "the origin does not move"
    assert gt[3] == pytest.approx(_ORTHO_GT[3])
    assert gt[1] == pytest.approx(_ORTHO_GT[1] * 2.0)
    assert gt[5] == pytest.approx(_ORTHO_GT[5] * 2.0)


@requires_backend
def test_windowed_read_clips_and_reports_what_it_returned(ortho_tif: Path) -> None:
    """A window overhanging the edge is clipped; the transform describes the clipped result."""
    data, gt = windowed_read(str(ortho_tif), (60, 60, 100, 100), indexes=1)

    assert data.shape == (4, 4), "clipped to the raster's extent"
    assert gt[0] == pytest.approx(_ORTHO_GT[0] + 60 * _ORTHO_GT[1])
    assert gt[3] == pytest.approx(_ORTHO_GT[3] + 60 * _ORTHO_GT[5])


@requires_backend
def test_windowed_read_entirely_outside_yields_an_empty_array(ortho_tif: Path) -> None:
    """★ Not an error. A caller mosaicking edge tiles must not have to pre-clip."""
    data, _gt = windowed_read(str(ortho_tif), (500, 500, 10, 10), indexes=1)
    assert data.size == 0


@requires_backend
def test_windowed_read_multiband_is_band_major(ortho_tif: Path) -> None:
    """All bands come back ``(bands, H, W)`` — the rasterio convention the shim normalises to."""
    data, _gt = windowed_read(str(ortho_tif), (0, 0, 16, 16))
    assert data.shape == (3, 16, 16)

    one, _gt = windowed_read(str(ortho_tif), (0, 0, 16, 16), indexes=1)
    assert one.shape == (16, 16), "a scalar index yields a 2-D array"

    two, _gt = windowed_read(str(ortho_tif), (0, 0, 16, 16), indexes=(1, 2))
    assert two.shape == (2, 16, 16)


@requires_backend
def test_windowed_read_rejects_an_out_of_range_band(ortho_tif: Path) -> None:
    """Band 9 of a 3-band file is a caller bug and says so."""
    with pytest.raises(ValueError, match="band"):
        windowed_read(str(ortho_tif), (0, 0, 4, 4), indexes=9)


@requires_backend
def test_windowed_read_rejects_unknown_resampling(ortho_tif: Path) -> None:
    """An unknown resampling name fails loudly rather than silently becoming nearest."""
    with pytest.raises(ValueError, match="resampling"):
        windowed_read(str(ortho_tif), (0, 0, 4, 4), indexes=1, resampling="lanczos99")


# --- nodata ------------------------------------------------------------------


@requires_backend
def test_windowed_read_honours_nodata(tmp_path: Path) -> None:
    """★ A nodata value read as data is a black hole in a mosaic and garbage in a DEM."""
    path = _write_geotiff(tmp_path / "nodata.tif", georeferenced=True, size=16, nodata=255.0)

    raw, _gt = windowed_read(str(path), (0, 0, 16, 16), indexes=1, apply_nodata=False)
    filled, _gt = windowed_read(
        str(path), (0, 0, 16, 16), indexes=1, apply_nodata=True, fill_value=0
    )

    assert read_meta(str(path)).nodata == 255.0
    assert (raw == 255).any(), "the fixture must actually contain nodata pixels"
    assert not (filled == 255).any(), "every nodata pixel was replaced"
    # The substantive assertion: wherever the raw band held nodata, the filled band holds
    # the fill value instead — and nowhere else changed.
    assert (filled[raw == 255] == 0).all()
    assert np.array_equal(filled[raw != 255], raw[raw != 255])


@requires_backend
def test_nodata_absent_means_no_substitution(ortho_tif: Path) -> None:
    """With no declared nodata, ``apply_nodata=True`` changes nothing."""
    a, _ = windowed_read(str(ortho_tif), (0, 0, 16, 16), indexes=1, apply_nodata=False)
    b, _ = windowed_read(str(ortho_tif), (0, 0, 16, 16), indexes=1, apply_nodata=True)
    assert np.array_equal(a, b)


# --- Overviews ---------------------------------------------------------------


@requires_backend
def test_overview_selection_and_read(tmp_path: Path) -> None:
    """★ Reading an 8x overview is 64x fewer bytes off disk than decimating in NumPy."""
    gdal = pytest.importorskip("osgeo.gdal")

    path = _write_geotiff(tmp_path / "pyramid.tif", georeferenced=True, size=64)
    dataset = gdal.Open(str(path), gdal.GA_Update)
    dataset.BuildOverviews("AVERAGE", [2, 4])
    dataset.FlushCache()
    del dataset

    assert read_meta(str(path)).overview_count == 2

    # A level's factor must never EXCEED the requested decimation: the caller must not be
    # handed pixels coarser than it asked for and then have to upsample mush.
    assert overview_for_scale(str(path), 1.5) == -1, "no overview is coarse enough"
    assert overview_for_scale(str(path), 2.0) == 0
    assert overview_for_scale(str(path), 4.0) == 1
    assert overview_for_scale(str(path), 100.0) == 1, "clamped to the coarsest available"

    data, gt = read_overview(str(path), 0, indexes=1)
    assert data.shape == (32, 32)
    assert gt[1] == pytest.approx(_ORTHO_GT[1] * 2.0), "the transform describes the overview"

    full, gt_full = read_overview(str(path), -1, indexes=1)
    assert full.shape == (64, 64)
    assert gt_full[1] == pytest.approx(_ORTHO_GT[1])


@requires_backend
def test_overview_for_scale_rejects_upsampling(ortho_tif: Path) -> None:
    """A decimation factor below 1 is a caller bug."""
    with pytest.raises(ValueError, match="target_scale"):
        overview_for_scale(str(ortho_tif), 0.5)


@requires_backend
def test_dataset_is_a_context_manager_and_closes_idempotently(ortho_tif: Path) -> None:
    """The shim's dataset closes cleanly, twice."""
    from gis.rasterio_shim import open_dataset

    with open_dataset(str(ortho_tif)) as dataset:
        assert dataset.width == _ORTHO_SIZE
        meta = dataset.meta()
    assert meta.width == _ORTHO_SIZE
    dataset.close()  # idempotent


@requires_backend
def test_opening_a_non_raster_raises_a_typed_error(tmp_path: Path) -> None:
    """★ ``ValueError``, not a raw GDAL ``RuntimeError``. Callers must not learn our stack."""
    from gis.rasterio_shim import open_dataset

    junk = tmp_path / "junk.tif"
    junk.write_bytes(b"definitely not a raster")

    with pytest.raises(ValueError, match="raster|open"):
        open_dataset(str(junk))
