"""The raster backend shim: ``rasterio`` | ``osgeo.gdal`` | a typed error (§11.3).

★ **BOUND AT CALL TIME, NEVER AT IMPORT.** ``import gis.rasterio_shim`` succeeds on a
machine with neither backend installed; only an actual ``open_dataset()`` raises, and it
raises ``RasterBackendUnavailable`` — a typed ``gis`` error naming the dependency that
would fix it — never a bare ``ImportError``. ``probe()`` and ``is_available()`` are total
and callable with both backends absent.

Without this module, ``local_orthophoto`` — the single highest-accuracy, fully-offline
provider — would be dead on the only machine we can test on, where **rasterio is absent
and GDAL 3.8.4 is present**.

Both backends are normalised to ONE dataset surface (``RasterDataset``), which is
deliberately rasterio-shaped: ``read(indexes)`` returning ``(H, W)`` for a scalar band
index and ``(bands, H, W)`` for a sequence, plus ``width`` / ``height`` / ``crs`` /
``nodata``. Callers never branch on which backend bound.

★★ VERIFIED ENVIRONMENT FINDING — ``osgeo.gdal_array`` IS BROKEN ON THIS MACHINE.
The Debian-packaged GDAL 3.8.4 extension ``osgeo._gdal_array`` is compiled against the
NumPy **1.x** ABI and fails to import under the installed NumPy 2.4.3 with
``AttributeError: _ARRAY_API not found``. Every documented GDAL/NumPy bridge call —
``Dataset.ReadAsArray``, ``Band.ReadAsArray``, ``Band.WriteArray`` — routes through it and
therefore **raises on this machine**. CONTRACT.md §0.1's *"Raster IO works today without
rasterio"* is true only via the path this module actually takes:

    ``Band.ReadRaster()`` -> ``bytes`` -> ``np.frombuffer()`` -> ``reshape()``

which is pure C-API and does not touch ``gdal_array`` at all. **Do not "simplify" this
module to ``ReadAsArray``**; it would work on a correctly-built GDAL and fail here, which
is the worst of both worlds. The buffer path is also exactly as fast — GDAL fills the same
buffer either way — so nothing is being traded for the portability.
"""

from __future__ import annotations

import abc
import contextlib
import logging
import threading
import warnings
from collections.abc import Sequence
from types import ModuleType, TracebackType
from typing import Any, Final, Self

import numpy as np

from gis.errors import RasterBackendUnavailable
from gis.types import GeoTransform, RasterMeta

__all__ = [
    "IDENTITY_GEOTRANSFORM",
    "RasterDataset",
    "backend_reason",
    "is_available",
    "open_dataset",
    "probe",
]

_log = logging.getLogger("gis.rasterio_shim")

IDENTITY_GEOTRANSFORM: Final[GeoTransform] = (0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
"""★ GDAL's geotransform for a raster that has NONE.

This is the value that makes ``detect_georeferencing()`` necessary. A plain scanned TIFF
reports this transform, and reading it literally places the image's top-left corner at
0N 0E with one-degree pixels — *the Gulf of Guinea, at continental scale*. GDAL does not
lie here; it returns a documented default. Believing the default is the bug.
"""

_BIND_LOCK: Final[threading.Lock] = threading.Lock()
_backend_name: str | None = None
_backend_module: ModuleType | None = None
_backend_reason: str | None = None


# --- Backend binding ---------------------------------------------------------


def _bind() -> tuple[str, ModuleType | None, str | None]:
    """Bind a raster backend, memoising the result. NEVER raises.

    Preference order is ``rasterio`` then ``osgeo.gdal``. rasterio is preferred where it
    exists because its windowed-read API is narrower and better specified; GDAL is the leg
    that actually carries this machine.

    Returns:
        ``(name, module, reason)`` where ``name`` is ``"rasterio"``, ``"gdal"`` or
        ``"none"``, ``module`` is the bound module (None when nothing bound), and
        ``reason`` is a human sentence naming the missing dependency (None on success).
    """
    global _backend_name, _backend_module, _backend_reason

    if _backend_name is not None:
        return (_backend_name, _backend_module, _backend_reason)

    with _BIND_LOCK:
        if _backend_name is not None:  # another thread won the race
            return (_backend_name, _backend_module, _backend_reason)

        try:
            import rasterio  # noqa: PLC0415 - CALL-TIME BINDING, §11.3. Never move this up.

            _backend_name, _backend_module, _backend_reason = "rasterio", rasterio, None
            _log.debug("raster backend: rasterio %s", getattr(rasterio, "__version__", "?"))
            return (_backend_name, _backend_module, _backend_reason)
        except ImportError:
            pass

        try:
            # ★ CALL-TIME BINDING, §11.3. §10.4's crs-single-entry contract permits
            #   osgeo in this module and in gis/crs.py only.
            from osgeo import gdal  # noqa: PLC0415

            _configure_gdal(gdal)
            _backend_name, _backend_module, _backend_reason = "gdal", gdal, None
            _log.debug("raster backend: osgeo.gdal %s", gdal.__version__)
            return (_backend_name, _backend_module, _backend_reason)
        except ImportError:
            pass

        _backend_name = "none"
        _backend_module = None
        _backend_reason = (
            "no raster backend: neither 'rasterio' nor 'osgeo' (GDAL) is importable. "
            "Install the gis[rasterio] extra, or install GDAL's Python bindings."
        )
        return (_backend_name, _backend_module, _backend_reason)


def _configure_gdal(gdal: Any) -> None:
    """Turn GDAL's C error codes into Python exceptions. NEVER raises.

    ``gdal.UseExceptions()`` internally attempts ``from . import gdal_array`` and swallows
    the ImportError itself — but NumPy 2 prints a C-level banner to stderr on the way
    through (see this module's header). The warnings context suppresses what is
    suppressible; the rest is a one-time cosmetic artefact of a GDAL built against NumPy 1
    and is harmless, because nothing here uses ``gdal_array``.
    """
    with contextlib.suppress(Exception), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        gdal.UseExceptions()


def probe() -> str:
    """Return which raster backend binds RIGHT NOW: ``rasterio`` | ``gdal`` | ``none``.

    ★ Total, cheap after the first call, and callable with both backends absent — that is
    what lets ``/health/ready`` and ``GET /capabilities`` report the raster backend rather
    than 500 while trying to discover it (§14 F-56).

    Returns:
        The bound backend's name, or ``"none"``.
    """
    return _bind()[0]


def is_available() -> bool:
    """True iff some raster backend can be bound. NEVER raises."""
    return _bind()[0] != "none"


def backend_reason() -> str | None:
    """Return why no backend is available, or None when one is.

    Returns:
        A human sentence naming the dependency that would fix it, or None.
    """
    return _bind()[2]


def _require_backend() -> tuple[str, ModuleType]:
    """Bind a backend or raise the typed error.

    Raises:
        RasterBackendUnavailable: When neither rasterio nor GDAL is importable. ★ A typed
            ``gis`` error, NOT an ``ImportError`` — callers of this package handle
            ``GisError`` and must not have to learn our stack.
    """
    name, module, reason = _bind()
    if module is None:
        raise RasterBackendUnavailable(reason or "no raster backend available")
    return (name, module)


# --- The uniform dataset surface ---------------------------------------------


class RasterDataset(abc.ABC):
    """One open raster, normalised across backends.

    A context manager: ``with open_dataset(path) as ds: ...``. Closing is idempotent.

    The surface is deliberately rasterio-shaped, because that is the API the rest of the
    codebase reads most naturally and because GDAL's is the one that needs normalising
    anyway (0-based vs 1-based bands, buffers vs arrays, identity-transform defaults).
    """

    @property
    @abc.abstractmethod
    def width(self) -> int:
        """Raster width in pixels."""

    @property
    @abc.abstractmethod
    def height(self) -> int:
        """Raster height in pixels."""

    @property
    @abc.abstractmethod
    def count(self) -> int:
        """Number of bands."""

    @property
    @abc.abstractmethod
    def dtype(self) -> str:
        """NumPy dtype name of band 1, e.g. ``"uint8"``."""

    @property
    @abc.abstractmethod
    def driver(self) -> str | None:
        """Short driver name, e.g. ``"GTiff"``."""

    @property
    @abc.abstractmethod
    def crs(self) -> str | None:
        """Authority string of ``geotransform`` (e.g. ``"EPSG:32633"``), or a WKT when no
        authority resolves, or **None when the file is not georeferenced**.

        ★ None is the honest answer for a plain TIFF and is what makes callers skip it
        rather than place it at the equator.
        """

    @property
    @abc.abstractmethod
    def geotransform(self) -> GeoTransform:
        """The GDAL 6-tuple. ``IDENTITY_GEOTRANSFORM`` when the file has none — read
        ``is_georeferenced`` before believing it.
        """

    @property
    @abc.abstractmethod
    def is_georeferenced(self) -> bool:
        """True iff this raster carries a usable CRS **and** a real geotransform (or GCPs).

        ★ The single most load-bearing property in this module. See
        ``gis.raster.detect_georeferencing``.
        """

    @property
    @abc.abstractmethod
    def nodata(self) -> float | None:
        """Band 1's nodata value, or None."""

    @property
    @abc.abstractmethod
    def overview_count(self) -> int:
        """Number of overview levels on band 1. 0 when the file has no pyramid."""

    @abc.abstractmethod
    def overview_shape(self, level: int) -> tuple[int, int]:
        """Return ``(height, width)`` of overview ``level`` (0-based) on band 1.

        Raises:
            IndexError: If ``level`` is out of range.
        """

    @abc.abstractmethod
    def read(
        self,
        indexes: int | Sequence[int] | None = None,
        *,
        window: tuple[int, int, int, int] | None = None,
        out_shape: tuple[int, int] | None = None,
        resampling: str = "nearest",
    ) -> np.ndarray:
        """Read pixels.

        Args:
            indexes: A 1-based band index, a sequence of them, or None for every band.
            window: ``(col_off, row_off, width, height)`` in pixels. None reads it all.
                ★ The window is CLIPPED to the raster; an entirely-outside window yields a
                zero-size array rather than an error, so a caller mosaicking edge tiles
                does not have to pre-clip.
            out_shape: ``(height, width)`` to decimate/resample the read into. None means
                native size. This is what makes an overview read cheap: the backend picks
                the right pyramid level itself.
            resampling: ``nearest`` | ``bilinear`` | ``cubic`` | ``average``. Only
                consulted when ``out_shape`` differs from the window size.

        Returns:
            ``(H, W)`` when ``indexes`` is a scalar int; ``(bands, H, W)`` otherwise.
            Never a masked array — apply ``nodata`` yourself, or use
            ``gis.raster.windowed_read``, which does.

        Raises:
            ValueError: On an unknown ``resampling``, a non-positive window size, or an
                out-of-range band index.
        """

    @abc.abstractmethod
    def close(self) -> None:
        """Release the dataset. Idempotent."""

    def meta(self) -> RasterMeta:
        """Return this raster's georeferencing metadata, with no pixels attached.

        Returns:
            A fully populated ``RasterMeta``.
        """
        return RasterMeta(
            width=self.width,
            height=self.height,
            band_count=self.count,
            geotransform=self.geotransform,
            crs=self.crs,
            is_georeferenced=self.is_georeferenced,
            nodata=self.nodata,
            dtype=self.dtype,
            overview_count=self.overview_count,
            driver=self.driver,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


_RESAMPLING_NAMES: Final[frozenset[str]] = frozenset(
    {"nearest", "bilinear", "cubic", "average"}
)


def _check_resampling(resampling: str) -> str:
    """Validate a resampling name.

    Raises:
        ValueError: If the name is not one of the four supported algorithms.
    """
    if resampling not in _RESAMPLING_NAMES:
        raise ValueError(
            f"unknown resampling {resampling!r}; expected one of "
            f"{sorted(_RESAMPLING_NAMES)}"
        )
    return resampling


def _clip_window(
    window: tuple[int, int, int, int] | None, width: int, height: int
) -> tuple[int, int, int, int]:
    """Clip a ``(col_off, row_off, w, h)`` window to the raster, or return the full extent.

    Raises:
        ValueError: If the requested width or height is negative.
    """
    if window is None:
        return (0, 0, width, height)
    col_off, row_off, win_w, win_h = (int(v) for v in window)
    if win_w < 0 or win_h < 0:
        raise ValueError(f"window size must be >= 0, got ({win_w}, {win_h})")
    col0 = max(0, col_off)
    row0 = max(0, row_off)
    col1 = min(width, col_off + win_w)
    row1 = min(height, row_off + win_h)
    return (col0, row0, max(0, col1 - col0), max(0, row1 - row0))


def _normalise_indexes(
    indexes: int | Sequence[int] | None, count: int
) -> tuple[list[int], bool]:
    """Normalise a band selector.

    Returns:
        ``(band_list, scalar)`` — ``band_list`` is 1-based; ``scalar`` records whether the
        caller passed a bare int and therefore expects a 2-D result.

    Raises:
        ValueError: If a band index is outside ``[1, count]``.
    """
    if indexes is None:
        return (list(range(1, count + 1)), False)
    if isinstance(indexes, int):
        bands, scalar = [int(indexes)], True
    else:
        bands, scalar = [int(i) for i in indexes], False
    for band in bands:
        if not (1 <= band <= count):
            raise ValueError(f"band {band} outside [1, {count}]")
    return (bands, scalar)


# --- The rasterio leg --------------------------------------------------------


class _RasterioDataset(RasterDataset):
    """``RasterDataset`` backed by rasterio. ★ NOT exercised on this dev machine."""

    def __init__(self, rasterio_module: Any, path: str) -> None:
        self._rio = rasterio_module
        self._ds: Any | None = rasterio_module.open(path)
        self._path = path

    @property
    def _handle(self) -> Any:
        if self._ds is None:
            raise ValueError(f"dataset {self._path!r} is closed")
        return self._ds

    @property
    def width(self) -> int:
        return int(self._handle.width)

    @property
    def height(self) -> int:
        return int(self._handle.height)

    @property
    def count(self) -> int:
        return int(self._handle.count)

    @property
    def dtype(self) -> str:
        return str(self._handle.dtypes[0])

    @property
    def driver(self) -> str | None:
        return str(self._handle.driver) if self._handle.driver else None

    @property
    def crs(self) -> str | None:
        if not self.is_georeferenced:
            return None
        crs = self._handle.crs
        if crs is None:
            return None
        try:
            return str(crs.to_string())
        except Exception:  # noqa: BLE001 - a CRS we cannot render is still a CRS
            return str(crs)

    @property
    def geotransform(self) -> GeoTransform:
        transform = self._handle.transform
        # rasterio Affine is (a, b, c, d, e, f) with x = a*col + b*row + c and
        # y = d*col + e*row + f. GDAL orders the same six numbers differently.
        a, b, c, d, e, f = (float(v) for v in tuple(transform)[:6])
        return (c, a, b, f, d, e)

    @property
    def is_georeferenced(self) -> bool:
        ds = self._handle
        if getattr(ds, "gcps", None):
            gcps, gcp_crs = ds.gcps
            if gcps and gcp_crs is not None:
                return True
        if ds.crs is None:
            return False
        try:
            if ds.transform.is_identity:
                return False
        except AttributeError:  # pragma: no cover - very old rasterio
            if self.geotransform == IDENTITY_GEOTRANSFORM:
                return False
        return True

    @property
    def nodata(self) -> float | None:
        value = self._handle.nodata
        return None if value is None else float(value)

    @property
    def overview_count(self) -> int:
        return len(self._handle.overviews(1))

    def overview_shape(self, level: int) -> tuple[int, int]:
        factors = self._handle.overviews(1)
        if not (0 <= level < len(factors)):
            raise IndexError(f"overview level {level} outside [0, {len(factors)})")
        factor = int(factors[level])
        return (self.height // factor, self.width // factor)

    def read(
        self,
        indexes: int | Sequence[int] | None = None,
        *,
        window: tuple[int, int, int, int] | None = None,
        out_shape: tuple[int, int] | None = None,
        resampling: str = "nearest",
    ) -> np.ndarray:
        _check_resampling(resampling)
        bands, scalar = _normalise_indexes(indexes, self.count)
        col0, row0, win_w, win_h = _clip_window(window, self.width, self.height)

        if win_w == 0 or win_h == 0:
            shape = out_shape or (win_h, win_w)
            empty = np.zeros((len(bands), *shape), dtype=np.dtype(self.dtype))
            return empty[0] if scalar else empty

        rio_window = self._rio.windows.Window(col0, row0, win_w, win_h)
        kwargs: dict[str, Any] = {"window": rio_window}
        if out_shape is not None:
            kwargs["out_shape"] = (len(bands), int(out_shape[0]), int(out_shape[1]))
            kwargs["resampling"] = getattr(
                self._rio.enums.Resampling, resampling, self._rio.enums.Resampling.nearest
            )
        data = self._handle.read(bands, **kwargs)
        arr = np.asarray(data)
        return arr[0] if scalar else arr

    def close(self) -> None:
        if self._ds is not None:
            self._ds.close()
            self._ds = None


# --- The GDAL leg — ★ the one that carries this machine ----------------------


_GDAL_TO_NUMPY: Final[dict[str, str]] = {
    "Byte": "uint8",
    "Int8": "int8",
    "UInt16": "uint16",
    "Int16": "int16",
    "UInt32": "uint32",
    "Int32": "int32",
    "UInt64": "uint64",
    "Int64": "int64",
    "Float32": "float32",
    "Float64": "float64",
    "CInt16": "complex64",
    "CInt32": "complex64",
    "CFloat32": "complex64",
    "CFloat64": "complex128",
}
"""GDAL type name -> NumPy dtype name.

★ Hand-written on purpose. The canonical mapping lives in ``osgeo.gdal_array``, which does
not import here (see the module header), so this module carries its own. Complex types are
mapped for completeness; this product reads uint8 imagery and float32/int16 DEMs.
"""


class _GdalDataset(RasterDataset):
    """``RasterDataset`` backed by ``osgeo.gdal``.

    ★ Reads go through ``Band.ReadRaster()`` + ``np.frombuffer``, NEVER ``ReadAsArray``,
    because ``osgeo.gdal_array`` does not import under NumPy 2 on this machine. See the
    module header.
    """

    def __init__(self, gdal_module: Any, path: str) -> None:
        self._gdal = gdal_module
        self._path = path
        with contextlib.suppress(Exception):
            gdal_module.PushErrorHandler("CPLQuietErrorHandler")
        try:
            ds = gdal_module.Open(path, gdal_module.GA_ReadOnly)
        finally:
            with contextlib.suppress(Exception):
                gdal_module.PopErrorHandler()
        if ds is None:
            # Reached only when UseExceptions() could not be enabled.
            raise ValueError(f"GDAL could not open {path!r}: {gdal_module.GetLastErrorMsg()}")
        self._ds: Any | None = ds

    @property
    def _handle(self) -> Any:
        if self._ds is None:
            raise ValueError(f"dataset {self._path!r} is closed")
        return self._ds

    @property
    def width(self) -> int:
        return int(self._handle.RasterXSize)

    @property
    def height(self) -> int:
        return int(self._handle.RasterYSize)

    @property
    def count(self) -> int:
        return int(self._handle.RasterCount)

    @property
    def dtype(self) -> str:
        band = self._handle.GetRasterBand(1)
        name = self._gdal.GetDataTypeName(band.DataType)
        return _GDAL_TO_NUMPY.get(name, "uint8")

    @property
    def driver(self) -> str | None:
        driver = self._handle.GetDriver()
        return str(driver.ShortName) if driver is not None else None

    @property
    def crs(self) -> str | None:
        if not self.is_georeferenced:
            return None
        return self._authority_string()

    def _authority_string(self) -> str | None:
        """Render this raster's CRS as ``AUTHORITY:CODE``, falling back to WKT.

        ★ ``osgeo.osr`` is NOT imported here: ``SpatialReference`` instances arrive from
        the dataset itself. §10.4's ``crs-single-entry`` contract permits ``osgeo`` in this
        module, but keeping the import surface to ``osgeo.gdal`` alone keeps the grep gate
        and the contract's intent aligned with no exemption to argue about.
        """
        spatial_ref = self._handle.GetSpatialRef()
        if spatial_ref is None and self._handle.GetGCPCount() > 0:
            spatial_ref = self._handle.GetGCPSpatialRef()
        if spatial_ref is None:
            wkt = self._handle.GetProjectionRef()
            return str(wkt) if wkt else None
        authority = spatial_ref.GetAuthorityName(None)
        code = spatial_ref.GetAuthorityCode(None)
        if authority and code:
            return f"{authority}:{code}"
        try:
            return str(spatial_ref.ExportToWkt())
        except Exception:  # noqa: BLE001 - an unrenderable CRS is still not None
            return None

    @property
    def geotransform(self) -> GeoTransform:
        gt = self._handle.GetGeoTransform(can_return_null=True)
        if gt is None:
            return IDENTITY_GEOTRANSFORM
        return tuple(float(v) for v in gt)  # type: ignore[return-value]

    @property
    def is_georeferenced(self) -> bool:
        """True iff GDAL has real georeferencing for this file.

        ★ THE DISTINCTION THAT DECIDES ``images.is_geotiff``. Three signals, and the first
        is the strong one:

        1. ``GetGeoTransform(can_return_null=True)`` returns **None** — not the identity —
           when the file carries no transform. Verified against GDAL 3.8.4 on this machine.
           The zero-argument form returns ``IDENTITY_GEOTRANSFORM`` instead, which is why
           every read of a geotransform in this package goes through the null-able form.
        2. GCPs with their own CRS georeference a file that has no affine transform at all.
        3. Belt and braces: a CRS must be present, and an identity transform is rejected
           even if GDAL handed it back as real — an identity transform is not survey
           georeferencing under any projection, and treating it as such would place the
           raster at 0N 0E with one-unit pixels.
        """
        ds = self._handle
        if ds.GetGCPCount() > 0 and ds.GetGCPSpatialRef() is not None:
            return True
        if ds.GetGeoTransform(can_return_null=True) is None:
            return False
        if ds.GetSpatialRef() is None and not ds.GetProjectionRef():
            return False
        return self.geotransform != IDENTITY_GEOTRANSFORM

    @property
    def nodata(self) -> float | None:
        value = self._handle.GetRasterBand(1).GetNoDataValue()
        return None if value is None else float(value)

    @property
    def overview_count(self) -> int:
        return int(self._handle.GetRasterBand(1).GetOverviewCount())

    def overview_shape(self, level: int) -> tuple[int, int]:
        band = self._handle.GetRasterBand(1)
        total = band.GetOverviewCount()
        if not (0 <= level < total):
            raise IndexError(f"overview level {level} outside [0, {total})")
        overview = band.GetOverview(level)
        return (int(overview.YSize), int(overview.XSize))

    def _resample_alg(self, resampling: str) -> int:
        """Map a resampling name to a GDAL ``GRIORA_*`` constant."""
        gdal = self._gdal
        return {
            "nearest": gdal.GRIORA_NearestNeighbour,
            "bilinear": gdal.GRIORA_Bilinear,
            "cubic": gdal.GRIORA_Cubic,
            "average": gdal.GRIORA_Average,
        }[resampling]

    def read(
        self,
        indexes: int | Sequence[int] | None = None,
        *,
        window: tuple[int, int, int, int] | None = None,
        out_shape: tuple[int, int] | None = None,
        resampling: str = "nearest",
    ) -> np.ndarray:
        _check_resampling(resampling)
        bands, scalar = _normalise_indexes(indexes, self.count)
        col0, row0, win_w, win_h = _clip_window(window, self.width, self.height)
        dtype = np.dtype(self.dtype)

        if out_shape is None:
            out_h, out_w = win_h, win_w
        else:
            out_h, out_w = int(out_shape[0]), int(out_shape[1])

        if win_w == 0 or win_h == 0 or out_h == 0 or out_w == 0:
            empty = np.zeros((len(bands), out_h, out_w), dtype=dtype)
            return empty[0] if scalar else empty

        alg = self._resample_alg(resampling)
        planes: list[np.ndarray] = []
        for band_index in bands:
            band = self._handle.GetRasterBand(band_index)
            # ★ ReadRaster, NOT ReadAsArray — gdal_array does not import under NumPy 2.
            raw = band.ReadRaster(
                col0,
                row0,
                win_w,
                win_h,
                buf_xsize=out_w,
                buf_ysize=out_h,
                buf_type=band.DataType,
                resample_alg=alg,
            )
            if raw is None:  # pragma: no cover - only without UseExceptions()
                raise ValueError(
                    f"GDAL read failed on {self._path!r} band {band_index}: "
                    f"{self._gdal.GetLastErrorMsg()}"
                )
            # frombuffer gives a read-only view over GDAL's bytes; copy so callers may write.
            planes.append(
                np.frombuffer(raw, dtype=dtype).reshape(out_h, out_w).copy()
            )

        stacked = np.stack(planes, axis=0)
        return stacked[0] if scalar else stacked

    def close(self) -> None:
        # GDAL closes and flushes when the last Python reference drops.
        self._ds = None


# --- The entry point ---------------------------------------------------------


def open_dataset(path: str) -> RasterDataset:
    """Open a raster through whichever backend binds. ★ THE entry point.

    ★ Named ``open_dataset`` because ``gis.elevation.local_dem`` (IU-09) probes for
    ``open_dataset`` | ``open_raster`` | ``open`` in that order and degrades gracefully if
    none exists. This is the name it finds first, and the surface it expects
    (``read(1)`` -> 2-D, ``width``, ``height``, ``crs``, ``geotransform``, ``nodata``) is
    the surface returned here.

    Args:
        path: A filesystem path, or any GDAL/rasterio-openable URI.

    Returns:
        An open ``RasterDataset``. Use it as a context manager.

    Raises:
        RasterBackendUnavailable: Neither rasterio nor GDAL is importable. ★ A typed
            error, NOT an ``ImportError``.
        ValueError: The file could not be opened, is not a raster, or is corrupt. ★ The
            backend's own exception type is deliberately not propagated.
    """
    name, module = _require_backend()
    try:
        if name == "rasterio":
            return _RasterioDataset(module, path)
        return _GdalDataset(module, path)
    except RasterBackendUnavailable:
        raise
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001 - the caller must not learn our raster stack
        raise ValueError(f"cannot open raster {path!r}: {exc}") from exc
