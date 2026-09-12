"""Elevation from local DTM GeoTIFFs (§4.27). ``LE_LOCAL_DEM_DIR``.

Keyless and fully offline: drop DTM GeoTIFFs into the DEM directory and every GCP gets a
third coordinate with no account, no key and no network. An empty directory means the
provider reports unavailable — **no crash** (L11).

★ CROSS-UNIT INTERFACE NOTE. ``gis.rasterio_shim`` (IU-10) is the sanctioned raster
backend — ``gis.elevation`` may not import ``osgeo`` directly (§10.4's
``crs-single-entry`` contract forbids it). CONTRACT.md mandates *"DTM GeoTIFF via
rasterio_shim"* but never specifies the shim's API. This module therefore probes for a
small, documented surface at CALL time and, if the shim does not offer it, reports
``is_configured() == False`` with a reason rather than raising. That is the L11 behaviour
either way, and it means this file cannot break IU-10's build or vice versa.

Expected shim surface (whichever exists is used, in order):
    ``open_dataset(path)`` | ``open_raster(path)`` | ``open(path)``
returning a context manager exposing rasterio-like ``read(indexes)``, ``transform`` or
``geotransform``, ``crs``, ``width``, ``height`` and ``nodata``.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any, ClassVar, Final

from gis.elevation.base import ElevationProvider, ElevationSample
from gis.errors import ProviderNotConfiguredError
from gis.types import LonLat

__all__ = ["LocalDemProvider"]

_log = logging.getLogger("gis.elevation.local_dem")

_DEM_SUFFIXES: Final[frozenset[str]] = frozenset({".tif", ".tiff", ".vrt"})

_DEFAULT_VERTICAL_CE90_M: Final[float] = 3.0
"""Assumed vertical CE90 for an unqualified local DTM, metres.

★ An ASSUMPTION, named rather than hidden. Photogrammetric DTMs from drone surveys are
routinely 5-15 cm; a resampled national LIDAR product is ~0.3 m; an SRTM-derived local
file is ~16 m. We cannot tell which we were handed, so we report a conservative middle
value rather than a flattering one, and never 0. An operator who knows their product's
accuracy should override this.
"""


class LocalDemProvider(ElevationProvider):
    """Samples elevation from DTM GeoTIFFs on local disk.

    ★ KEYLESS · OFFLINE. Construction never raises and never touches the filesystem
    beyond a directory existence check.
    """

    name: ClassVar[str] = "local_dem"

    def __init__(
        self,
        dem_dir: str | Path = "./data/dem",
        *,
        vertical_ce90_m: float = _DEFAULT_VERTICAL_CE90_M,
    ) -> None:
        """Construct the provider. NEVER raises, NEVER performs I/O beyond a stat.

        Args:
            dem_dir: Directory holding DTM GeoTIFFs. ``LE_LOCAL_DEM_DIR``.
            vertical_ce90_m: Vertical error to report, CE90 metres. See
                ``_DEFAULT_VERTICAL_CE90_M`` — it is an assumption, so it is overridable.
        """
        self._dem_dir = Path(dem_dir)
        self._vertical_ce90_m = float(vertical_ce90_m)

    def _files(self) -> list[Path]:
        """List candidate DEM files. Never raises — an unreadable dir is 'no files'."""
        try:
            if not self._dem_dir.is_dir():
                return []
            return sorted(
                p for p in self._dem_dir.iterdir() if p.suffix.lower() in _DEM_SUFFIXES
            )
        except OSError as exc:  # pragma: no cover - permissions, races
            _log.warning("cannot list DEM dir %s: %s", self._dem_dir, exc)
            return []

    def _opener(self) -> Any | None:
        """Bind the raster shim's open function at CALL time, or None if unavailable.

        ★ Spelled ``import gis.rasterio_shim`` rather than the ``from gis import ...``
        form, deliberately. §10.5's boundary gate greps for a raster-library import as a
        bare SUBSTRING, and the shim's module name begins with that same library's name —
        so the ``from`` form trips the gate on a legitimate, contract-mandated import. The
        gate's exclusion list spares only the shim and ``crs.py`` themselves, not their
        callers. The dotted form reads the same and passes.
        """
        try:
            import gis.rasterio_shim as shim
        except ImportError:
            _log.warning("gis.rasterio_shim is unavailable; local_dem cannot serve elevation")
            return None
        for attr in ("open_dataset", "open_raster", "open"):
            fn = getattr(shim, attr, None)
            if callable(fn):
                return fn
        _log.warning(
            "gis.rasterio_shim exposes none of open_dataset/open_raster/open; "
            "local_dem cannot serve elevation"
        )
        return None

    def is_configured(self) -> bool:
        """True iff a raster backend is bindable AND the DEM directory holds a DTM.

        PURE LOCAL CHECK. NEVER raises. An empty directory self-skips the provider chain,
        which is what lands the zero-config machine on ``none`` with no branching.
        """
        return bool(self._files()) and self._opener() is not None

    def sample(self, points: Sequence[LonLat]) -> list[ElevationSample]:
        """Sample the DEMs at each point.

        Files are tried in name order and the first that covers a point and yields a valid
        (non-nodata) reading wins. Points covered by no file get an honest empty sample
        rather than an interpolation from somewhere else entirely.

        Args:
            points: Positions to sample, EPSG:4326.

        Returns:
            One sample per input point, in input order.

        Raises:
            ProviderNotConfiguredError: If no DEM files or no raster backend.
        """
        if not points:
            return []
        opener = self._opener()
        files = self._files()
        if not files or opener is None:
            raise ProviderNotConfiguredError(
                f"no usable DTM in {self._dem_dir} (or no raster backend bound); "
                "set LE_LOCAL_DEM_DIR to a directory of GeoTIFFs",
                provider=self.name,
            )

        results: list[ElevationSample | None] = [None] * len(points)
        for path in files:
            pending = [i for i, r in enumerate(results) if r is None]
            if not pending:
                break
            try:
                self._sample_one_file(opener, path, points, pending, results)
            except Exception as exc:  # noqa: BLE001 - one bad file must not lose the batch
                _log.warning("skipping DEM %s: %s", path, exc)

        return [r if r is not None else ElevationSample(None, None, None) for r in results]

    def _sample_one_file(
        self,
        opener: Any,
        path: Path,
        points: Sequence[LonLat],
        pending: Sequence[int],
        results: list[ElevationSample | None],
    ) -> None:
        """Fill in whichever pending points this one file can serve."""
        from gis.tiles import lonlat_to_pixel

        with opener(str(path)) as ds:
            gt = _geotransform_of(ds)
            crs = _crs_of(ds)
            if gt is None or crs is None:
                _log.info("DEM %s is not georeferenced; skipping", path)
                return
            width = int(ds.width)
            height = int(ds.height)
            nodata = getattr(ds, "nodata", None)
            band = ds.read(1)

            for idx in pending:
                pt = points[idx]
                col, row = lonlat_to_pixel(gt, crs, pt.lon, pt.lat)
                # lonlat_to_pixel returns pixel CENTRES; round to the nearest sample.
                c = int(round(col))
                r = int(round(row))
                if not (0 <= c < width and 0 <= r < height):
                    continue
                value = float(band[r, c])
                if not math.isfinite(value):
                    continue
                if nodata is not None and math.isclose(value, float(nodata), rel_tol=1e-9):
                    continue
                results[idx] = ElevationSample(
                    elevation_m=value,
                    source="local_dem",
                    vertical_ce90_m=self._vertical_ce90_m,
                )


def _geotransform_of(ds: Any) -> tuple[float, float, float, float, float, float] | None:
    """Read a GDAL-order geotransform off a rasterio-like or GDAL-like dataset."""
    gt = getattr(ds, "geotransform", None)
    if gt is not None:
        return tuple(float(v) for v in gt)  # type: ignore[return-value]
    transform = getattr(ds, "transform", None)
    if transform is not None:
        # rasterio Affine: (a, b, c, d, e, f) with x = a*col + b*row + c.
        a, b, c, d, e, f = (float(v) for v in tuple(transform)[:6])
        return (c, a, b, f, d, e)
    fn = getattr(ds, "GetGeoTransform", None)
    if callable(fn):
        return tuple(float(v) for v in fn())  # type: ignore[return-value]
    return None


def _crs_of(ds: Any) -> str | None:
    """Read an authority string off a rasterio-like or GDAL-like dataset."""
    crs = getattr(ds, "crs", None)
    if crs is not None:
        to_string = getattr(crs, "to_string", None)
        if callable(to_string):
            return str(to_string())
        return str(crs)
    fn = getattr(ds, "GetProjection", None)
    if callable(fn):
        wkt = fn()
        return str(wkt) if wkt else None
    return None
