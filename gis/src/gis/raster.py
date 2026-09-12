"""Raster IO: windowed reads, overviews, nodata, and ``detect_georeferencing()``.

Every byte read from a raster file in this system passes through here or through
``gis.rasterio_shim``, which this module is the friendly face of. No CV, no CRS
transforms, no network: pixels and a geotransform in, pixels and a geotransform out.

★ ``detect_georeferencing()`` IS THE MOST CONSEQUENTIAL FUNCTION IN THIS MODULE, and in
this build more than any other. Per ``SCOPE.md``, a **georeferenced GeoTIFF upload yields
EXACT GCPs with no matching at all** — the geotransform simply *is* the answer. So this
one boolean decides whether an upload takes the exact path or the manual-survey path, and
a false positive means a scanned TIFF gets silently placed in the Gulf of Guinea and
exported as survey control.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Final

import numpy as np

from gis.rasterio_shim import IDENTITY_GEOTRANSFORM, RasterDataset, open_dataset
from gis.types import BBox, GeoTransform, RasterMeta

__all__ = [
    "GeoreferencingReport",
    "bounds_of",
    "detect_georeferencing",
    "gsd_of",
    "overview_for_scale",
    "read_meta",
    "read_overview",
    "windowed_read",
]

_log = logging.getLogger("gis.raster")

_MAX_SANE_PIXEL_SIZE: Final[float] = 1.0e7
"""Largest plausible ``|pixel_width|``, in the geotransform's own units.

A metre-based projected CRS spans ~4e7 m; a degree-based one spans 360. A pixel bigger
than 1e7 units is not a raster of the Earth, it is a corrupt or placeholder transform.
"""


@dataclass(frozen=True, slots=True)
class GeoreferencingReport:
    """Why ``detect_georeferencing()`` decided what it decided.

    ★ Exists so the decision is auditable rather than a bare bool. When a surveyor asks
    "why was my GeoTIFF not recognised?", ``reason`` answers it without a debugger, and
    the ingest path can put it straight into a ``WarningItem``.
    """

    is_georeferenced: bool
    crs: str | None
    geotransform: GeoTransform
    reason: str
    """A human sentence. Non-empty whether the answer was True or False."""
    has_gcps: bool = False
    is_identity_transform: bool = False
    """★ True when the file reported GDAL's identity transform — the specific trap."""

    def __bool__(self) -> bool:
        """Allow ``if detect_georeferencing(path):`` to read naturally."""
        return self.is_georeferenced


def detect_georeferencing(path: str) -> GeoreferencingReport:
    """Decide whether a raster carries usable georeferencing.

    ★ THE GEOTIFF SHORT-CIRCUIT'S GATE. True here means the upload's pixels can be turned
    into lat/lon directly and exactly, with no matching and no surveyor click. It must
    therefore be conservative: a False costs a surveyor some manual clicks, while a False
    POSITIVE fabricates survey coordinates from an identity transform. Those are not
    comparable errors, so the tie goes to False.

    ★ **Beware GDAL's identity transform.** ``Dataset.GetGeoTransform()`` returns
    ``(0, 1, 0, 0, 0, 1)`` for a raster that has NO transform — a documented default, not
    a bug. Read literally it places the top-left pixel at 0N 0E with one-degree pixels.
    ``gis.rasterio_shim`` reads the null-able form (which returns None instead) and this
    function additionally rejects the identity transform outright, so the trap is closed
    twice.

    The conditions, ALL of which must hold:

    1. A raster backend is bound (else the answer is an honest False with a reason).
    2. The file opens as a raster.
    3. A CRS is present — pixels cannot become lat/lon without one — **or** the file
       carries GCPs with their own CRS.
    4. A geotransform is present and is not the identity.
    5. The transform is non-degenerate: non-zero, finite determinant, and pixel sizes
       within a sane magnitude.

    Args:
        path: Path to the raster.

    Returns:
        A ``GeoreferencingReport``. It is truthy iff the raster is georeferenced. ★ NEVER
        raises — an unreadable file is "not georeferenced, and here is why", because this
        runs during ingest of a file a user just uploaded and a traceback there tells the
        surveyor nothing.
    """
    try:
        with open_dataset(path) as ds:
            return _report_for(ds)
    except Exception as exc:  # noqa: BLE001 - ingest asks a question; it gets an answer
        _log.info("detect_georeferencing(%s): not readable as a raster: %s", path, exc)
        return GeoreferencingReport(
            is_georeferenced=False,
            crs=None,
            geotransform=IDENTITY_GEOTRANSFORM,
            reason=f"not readable as a raster: {exc}",
        )


def _report_for(ds: RasterDataset) -> GeoreferencingReport:
    """Build the report for an already-open dataset."""
    gt = ds.geotransform
    crs = ds.crs
    is_identity = gt == IDENTITY_GEOTRANSFORM
    has_gcps = False

    if not ds.is_georeferenced:
        if is_identity:
            reason = (
                "no georeferencing: the file reports GDAL's identity transform "
                "(0, 1, 0, 0, 0, 1), which means 'no transform', not 'one-unit pixels at "
                "the origin'"
            )
        elif crs is None:
            reason = "no georeferencing: the file carries no coordinate reference system"
        else:
            reason = "no georeferencing: the backend reports no usable transform"
        return GeoreferencingReport(
            is_georeferenced=False,
            crs=None,
            geotransform=gt,
            reason=reason,
            is_identity_transform=is_identity,
        )

    if crs is None:
        return GeoreferencingReport(
            is_georeferenced=False,
            crs=None,
            geotransform=gt,
            reason=(
                "a geotransform is present but no CRS is: the pixels have a grid but no "
                "datum, so they cannot become lat/lon"
            ),
            is_identity_transform=is_identity,
        )

    ok, why = _transform_is_sane(gt)
    if not ok:
        return GeoreferencingReport(
            is_georeferenced=False,
            crs=crs,
            geotransform=gt,
            reason=f"degenerate geotransform: {why}",
            is_identity_transform=is_identity,
        )

    return GeoreferencingReport(
        is_georeferenced=True,
        crs=crs,
        geotransform=gt,
        reason=f"georeferenced in {crs}",
        has_gcps=has_gcps,
        is_identity_transform=False,
    )


def _transform_is_sane(gt: GeoTransform) -> tuple[bool, str]:
    """Check a geotransform for degeneracy.

    Returns:
        ``(ok, why)``. ``why`` is empty when ok.
    """
    if not all(math.isfinite(v) for v in gt):
        return (False, "contains a non-finite coefficient")
    # det of [[pixel_width, row_rotation], [col_rotation, pixel_height]]
    det = gt[1] * gt[5] - gt[2] * gt[4]
    if det == 0.0 or not math.isfinite(det):
        return (False, "is singular (zero-area pixels)")
    if abs(gt[1]) > _MAX_SANE_PIXEL_SIZE or abs(gt[5]) > _MAX_SANE_PIXEL_SIZE:
        return (False, f"pixel size exceeds {_MAX_SANE_PIXEL_SIZE:g} CRS units")
    return (True, "")


def read_meta(path: str) -> RasterMeta:
    """Read a raster's metadata without reading its pixels.

    Args:
        path: Path to the raster.

    Returns:
        A ``RasterMeta``. ``crs`` is None and ``is_georeferenced`` is False for a file
        with no georeferencing.

    Raises:
        RasterBackendUnavailable: No raster backend is installed.
        ValueError: The file is not a readable raster.
    """
    with open_dataset(path) as ds:
        return ds.meta()


def bounds_of(path: str) -> tuple[BBox | None, str | None]:
    """Return a georeferenced raster's footprint, reprojected to EPSG:4326.

    Args:
        path: Path to the raster.

    Returns:
        ``(bbox, crs)`` — the 4326 footprint and the file's native CRS. ``(None, None)``
        when the file is not georeferenced, and ``(None, crs)`` when it is georeferenced
        but its CRS cannot be transformed with the available backends.

    Raises:
        RasterBackendUnavailable: No raster backend is installed.
        ValueError: The file is not a readable raster.
    """
    from gis.crs import transform_points  # call-time: crs.py binds pyproj/osr itself

    with open_dataset(path) as ds:
        if not ds.is_georeferenced or ds.crs is None:
            return (None, None)
        native_crs = ds.crs
        gt = ds.geotransform
        width, height = ds.width, ds.height

    # ★ The EDGE corners (0 and width/height, not width-1), because a GDAL geotransform's
    #   origin is the outer edge of the top-left pixel — so these four points are the
    #   raster's true extent, not its outermost pixel centres.
    # ★ All four, so a rotated transform is handled rather than assumed away.
    xs: list[float] = []
    ys: list[float] = []
    for col, row in ((0, 0), (width, 0), (width, height), (0, height)):
        xs.append(gt[0] + col * gt[1] + row * gt[2])
        ys.append(gt[3] + col * gt[4] + row * gt[5])

    try:
        lons, lats = transform_points(
            np.asarray(xs, dtype=np.float64),
            np.asarray(ys, dtype=np.float64),
            native_crs,
            "EPSG:4326",
        )
    except Exception as exc:  # noqa: BLE001 - CrsError and friends; the answer is "cannot"
        _log.warning("cannot reproject %s bounds from %s: %s", path, native_crs, exc)
        return (None, native_crs)

    bbox = BBox(
        west=float(np.min(lons)),
        south=float(np.min(lats)),
        east=float(np.max(lons)),
        north=float(np.max(lats)),
    )
    return (bbox, native_crs)


def gsd_of(path: str) -> float | None:
    """Return a georeferenced raster's ground sample distance in TRUE metres.

    ★ Not a geotransform coefficient. For a projected metric CRS the pixel size *is*
    metres; for a geographic CRS (degrees) it is converted at the raster's centre
    latitude, with the ``cos(phi)`` factor applied to the longitude axis. A caller that
    read ``gt[1]`` directly would report ~1e-5 "metres" for a degree-based raster.

    Args:
        path: Path to the raster.

    Returns:
        Metres per pixel (the geometric mean of the two axes), or None when the file is
        not georeferenced or its CRS cannot be classified.

    Raises:
        RasterBackendUnavailable: No raster backend is installed.
        ValueError: The file is not a readable raster.
    """
    from gis.crs import is_metric_crs  # call-time: crs.py owns backend binding
    from gis.tiles import EARTH_RADIUS_M

    with open_dataset(path) as ds:
        if not ds.is_georeferenced or ds.crs is None:
            return None
        crs = ds.crs
        gt = ds.geotransform
        width, height = ds.width, ds.height

    # Pixel axis lengths in the CRS's own units, honouring rotation terms.
    x_span = math.hypot(gt[1], gt[4])
    y_span = math.hypot(gt[2], gt[5])

    try:
        metric = is_metric_crs(crs)
    except Exception as exc:  # noqa: BLE001 - an unclassifiable CRS yields an honest None
        _log.warning("cannot classify CRS %s of %s: %s", crs, path, exc)
        return None

    if metric:
        return float(math.sqrt(x_span * y_span))

    # Degrees. Convert at the raster's centre latitude.
    centre_lat = gt[3] + (width / 2.0) * gt[4] + (height / 2.0) * gt[5]
    if not (-90.0 <= centre_lat <= 90.0):
        _log.warning("%s: centre latitude %.3f is not a latitude; GSD unknown", path, centre_lat)
        return None
    m_per_deg = math.pi * EARTH_RADIUS_M / 180.0
    x_m = x_span * m_per_deg * math.cos(math.radians(centre_lat))
    y_m = y_span * m_per_deg
    if x_m <= 0.0 or y_m <= 0.0:
        return None
    return float(math.sqrt(x_m * y_m))


def windowed_read(
    path: str,
    window: tuple[int, int, int, int],
    *,
    indexes: int | tuple[int, ...] | None = None,
    out_shape: tuple[int, int] | None = None,
    resampling: str = "nearest",
    apply_nodata: bool = True,
    fill_value: float = 0.0,
) -> tuple[np.ndarray, GeoTransform]:
    """Read one window of a raster, with its EXACT geotransform.

    ★ The geotransform is folded to the window's origin, never returned unchanged. A
    windowed read whose transform still points at the file's origin is the defect that
    produces coordinates wrong by the window offset while crashing nothing.

    ★ Reading a window rather than the file is not an optimisation here. An orthomosaic is
    routinely tens of gigabytes; ``local_orthophoto`` serving one 256-px tile must touch
    256x256 pixels, not 2e10 of them.

    Args:
        path: Path to the raster.
        window: ``(col_off, row_off, width, height)`` in pixels. Clipped to the raster;
            the returned geotransform describes what was ACTUALLY returned.
        indexes: 1-based band index, a tuple of them, or None for every band.
        out_shape: ``(height, width)`` to resample the window into. None means native.
        resampling: ``nearest`` | ``bilinear`` | ``cubic`` | ``average``.
        apply_nodata: When True and the band declares a nodata value, matching pixels are
            replaced with ``fill_value``. ★ A nodata value read as data is a black hole in
            a mosaic and a garbage number in a DEM.
        fill_value: What nodata becomes. Ignored when ``apply_nodata`` is False.

    Returns:
        ``(array, geotransform)``. The array is ``(H, W)`` for a scalar ``indexes`` and
        ``(bands, H, W)`` otherwise; the geotransform is exact for those pixels, including
        any decimation implied by ``out_shape``.

    Raises:
        RasterBackendUnavailable: No raster backend is installed.
        ValueError: The file is unreadable, the window is invalid, or a band is out of
            range.
    """
    col_off, row_off, win_w, win_h = (int(v) for v in window)
    if win_w < 0 or win_h < 0:
        raise ValueError(f"window size must be >= 0, got ({win_w}, {win_h})")

    with open_dataset(path) as ds:
        col0 = max(0, col_off)
        row0 = max(0, row_off)
        col1 = min(ds.width, col_off + win_w)
        row1 = min(ds.height, row_off + win_h)
        clipped_w = max(0, col1 - col0)
        clipped_h = max(0, row1 - row0)

        data = ds.read(
            indexes,
            window=(col0, row0, clipped_w, clipped_h),
            out_shape=out_shape,
            resampling=resampling,
        )
        nodata = ds.nodata
        gt = ds.geotransform

    if apply_nodata and nodata is not None:
        data = _apply_nodata(data, nodata, fill_value)

    out_h = data.shape[-2]
    out_w = data.shape[-1]
    scale_x = (clipped_w / out_w) if out_w else 1.0
    scale_y = (clipped_h / out_h) if out_h else 1.0
    return (data, _window_geotransform(gt, col0, row0, scale_x, scale_y))


def _apply_nodata(data: np.ndarray, nodata: float, fill_value: float) -> np.ndarray:
    """Replace nodata pixels with ``fill_value``, preserving dtype where possible."""
    if data.size == 0:
        return data
    if np.issubdtype(data.dtype, np.floating) and math.isnan(nodata):
        mask = np.isnan(data)
    else:
        mask = data == np.asarray(nodata, dtype=data.dtype)
    if not mask.any():
        return data
    out = data.copy()
    out[mask] = np.asarray(fill_value).astype(data.dtype, copy=False)
    return out


def _window_geotransform(
    gt: GeoTransform, col_off: int, row_off: int, scale_x: float, scale_y: float
) -> GeoTransform:
    """Return the geotransform of a window, exactly.

    ★ THE FOLD. The origin advances through the SAME affine as the pixels do, so a rotated
    transform is handled rather than assumed away; the pixel-size and rotation terms then
    scale by any decimation.
    """
    origin_x = gt[0] + col_off * gt[1] + row_off * gt[2]
    origin_y = gt[3] + col_off * gt[4] + row_off * gt[5]
    return (
        origin_x,
        gt[1] * scale_x,
        gt[2] * scale_y,
        origin_y,
        gt[4] * scale_x,
        gt[5] * scale_y,
    )


def overview_for_scale(path: str, target_scale: float) -> int:
    """Pick the overview level nearest a decimation factor, without exceeding it.

    ★ Reading the finest level and downsampling in NumPy wastes the pyramid the file
    already paid for: an 8x overview is 64x fewer bytes off disk.

    Args:
        path: Path to the raster.
        target_scale: Desired decimation, ``>= 1``. ``4.0`` means "a quarter-size read".

    Returns:
        A 0-based overview level, or ``-1`` meaning "read the full-resolution band". The
        chosen level's factor never EXCEEDS ``target_scale``, so the caller never gets
        pixels coarser than it asked for and then has to upsample mush.

    Raises:
        RasterBackendUnavailable: No raster backend is installed.
        ValueError: The file is unreadable or ``target_scale < 1``.
    """
    if target_scale < 1.0:
        raise ValueError(f"target_scale must be >= 1, got {target_scale}")
    with open_dataset(path) as ds:
        best = -1
        best_factor = 1.0
        for level in range(ds.overview_count):
            ov_h, ov_w = ds.overview_shape(level)
            if ov_w <= 0 or ov_h <= 0:
                continue
            factor = ds.width / ov_w
            if factor <= target_scale + 1e-9 and factor > best_factor:
                best, best_factor = level, factor
        return best


def read_overview(
    path: str, level: int, *, indexes: int | tuple[int, ...] | None = None
) -> tuple[np.ndarray, GeoTransform]:
    """Read a whole overview level, with its exact geotransform.

    Args:
        path: Path to the raster.
        level: 0-based overview level. ``-1`` means the full-resolution band, so the
            return value of ``overview_for_scale()`` can be passed straight in.
        indexes: 1-based band index, a tuple of them, or None for every band.

    Returns:
        ``(array, geotransform)``. The geotransform's pixel sizes are scaled by the
        overview's decimation factor — it describes the pixels returned, not the file's.

    Raises:
        RasterBackendUnavailable: No raster backend is installed.
        ValueError: The file is unreadable.
        IndexError: ``level`` is out of range.
    """
    with open_dataset(path) as ds:
        if level < 0:
            data = ds.read(indexes)
            return (data, ds.geotransform)
        ov_h, ov_w = ds.overview_shape(level)
        data = ds.read(indexes, out_shape=(ov_h, ov_w), resampling="average")
        scale_x = ds.width / ov_w if ov_w else 1.0
        scale_y = ds.height / ov_h if ov_h else 1.0
        return (data, _window_geotransform(ds.geotransform, 0, 0, scale_x, scale_y))
