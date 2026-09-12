"""DEM access with vectorised bilinear sampling.

The sampling maths is deliberately identical to core/geo_io.py of the GUI:
interpolation happens between the four surrounding CELL CENTRES, using
continuous pixel coordinates. Sampling anywhere else (e.g. cell corners) makes
the surface discontinuous at cell boundaries and breaks the ray/DEM crossing
search.
"""
from __future__ import annotations

import hashlib
import os
import warnings

import numpy as np
import rasterio
from pyproj import Transformer


class DEM:
    """Read-only DEM with scalar and vectorised height lookup."""

    def __init__(self, path: str) -> None:
        self.path = os.path.abspath(path)
        self.ds = rasterio.open(self.path)

        if self.ds.crs is None:
            raise ValueError("DEM has no CRS: %s" % self.path)
        self.epsg = self.ds.crs.to_epsg()
        if self.epsg is None:
            raise ValueError("DEM CRS has no EPSG code: %s" % self.ds.crs)
        if self.ds.crs.is_geographic:
            raise ValueError(
                "DEM CRS %s is geographic (degrees). Reproject to a metric CRS "
                "first, e.g. gdalwarp -t_srs EPSG:32637 in.tif out.tif" % self.ds.crs)

        tr = self.ds.transform
        if abs(tr.b) > 1e-12 or abs(tr.d) > 1e-12:
            raise ValueError("DEM grid is rotated; only axis-aligned rasters are supported")

        self.res = float(abs(tr.a))
        if not 0.05 <= self.res <= 1000.0:
            raise ValueError("implausible pixel size %.6g for a metric CRS" % self.res)

        with warnings.catch_warnings():   # rasterio 1.5 + numpy 2.5 shape notice
            warnings.simplefilter("ignore", DeprecationWarning)
            self.array = np.asarray(self.ds.read(1), dtype=np.float64)
        if self.ds.nodata is not None:
            self.array[self.array == self.ds.nodata] = np.nan
        self.height, self.width = self.array.shape

        # affine inverse, kept as scalars for speed
        self._inv_a = 1.0 / tr.a
        self._inv_e = 1.0 / tr.e
        self._c = tr.c
        self._f = tr.f

        self._to_lonlat = Transformer.from_crs(self.epsg, 4326, always_xy=True)
        self._to_xy = Transformer.from_crs(4326, self.epsg, always_xy=True)

    # ------------------------------------------------------------------ info
    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return "<DEM %s EPSG:%d %dx%d @ %.3f m>" % (
            os.path.basename(self.path), self.epsg, self.width, self.height, self.res)

    def md5(self, chunk: int = 1 << 20) -> str:
        """Hash of the DEM file - written into the bundle manifest so a LUT can
        never be silently paired with a different terrain model."""
        h = hashlib.md5()
        with open(self.path, "rb") as fh:
            for block in iter(lambda: fh.read(chunk), b""):
                h.update(block)
        return h.hexdigest()

    # -------------------------------------------------------------- sampling
    def z(self, x: float, y: float) -> float:
        """Scalar bilinear height; NaN outside coverage."""
        out = self.z_many(np.array([x], dtype=np.float64),
                          np.array([y], dtype=np.float64))
        return float(out[0])

    def z_many(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        """Vectorised bilinear height for arrays of projected coordinates.

        Returns NaN where the sample falls outside the raster or on nodata.
        """
        col = (x - self._c) * self._inv_a - 0.5
        row = (y - self._f) * self._inv_e - 0.5

        c0 = np.floor(col)
        r0 = np.floor(row)
        fc = col - c0
        fr = row - r0
        c0 = c0.astype(np.int64)
        r0 = r0.astype(np.int64)

        ok = (r0 >= 0) & (r0 <= self.height - 2) & (c0 >= 0) & (c0 <= self.width - 2)
        out = np.full(x.shape, np.nan, dtype=np.float64)
        if not np.any(ok):
            return out

        r0o, c0o = r0[ok], c0[ok]
        fro, fco = fr[ok], fc[ok]
        a = self.array
        z00 = a[r0o, c0o]
        z01 = a[r0o, c0o + 1]
        z10 = a[r0o + 1, c0o]
        z11 = a[r0o + 1, c0o + 1]
        out[ok] = (z00 * (1 - fco) * (1 - fro) + z01 * fco * (1 - fro)
                   + z10 * (1 - fco) * fro + z11 * fco * fro)
        return out

    # ------------------------------------------------------------ conversion
    def xy_to_lonlat(self, x: np.ndarray, y: np.ndarray):
        return self._to_lonlat.transform(x, y)

    def lonlat_to_xy(self, lon: float, lat: float):
        return self._to_xy.transform(lon, lat)

    def close(self) -> None:
        self.ds.close()
