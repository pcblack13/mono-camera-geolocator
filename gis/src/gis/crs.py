"""Coordinate reference systems (CONTRACT.md §4.16, §11.3; 40-imagery §6).

★ THE ONLY MODULE IN THE REPO THAT MAY IMPORT ``pyproj`` OR ``osgeo.osr``.

Backend chain, bound at CALL time (§11.3) and never at import::

    pyproj  ->  osgeo.osr  ->  closed-form NumPy (EPSG:4326 <-> EPSG:3857 only)  ->  CrsBackendUnavailable

Importing this module NEVER imports a CRS library. ``probe()`` and ``is_metric_crs()``
are callable with every backend absent.

★ always_xy=True, ALWAYS
------------------------
EPSG:4326's authority-defined axis order is (LATITUDE, LONGITUDE), and pyproj >= 2.2
honours the authority order by default. So::

    Transformer.from_crs("EPSG:4326", "EPSG:32630").transform(lon, lat)   # SILENTLY WRONG

It does not raise. It returns plausible numbers for the wrong place on Earth — in an
agricultural GCP product, the single most expensive bug available, because the surveyor
drives to the wrong field. ``always_xy=True`` forces (x=lon, y=lat) on input AND output.
``osgeo.osr``'s exact equivalent is ``SetAxisMappingStrategy(OAMS_TRADITIONAL_GIS_ORDER)``
and is mandatory for the identical reason.

The pitfall is eliminated by making the mistake unreachable: transformer construction
happens ONLY in ``get_transformer``, which ONLY ever passes the traditional order, and CI
greps for ``from_crs`` outside this module.
"""

from __future__ import annotations

import logging
import math
import warnings
from functools import lru_cache
from importlib.util import find_spec
from typing import Any, Literal

import numpy as np

from gis.errors import CrsBackendUnavailable, CrsError, OutsideUtmError
from gis.tiles import lonlat_to_meters_array, meters_to_lonlat_array
from gis.types import GeoTransform

__all__ = [
    "CrsTransformer",
    "backend_name",
    "get_transformer",
    "is_ground_metric_crs",
    "is_metric_crs",
    "lonlat_to_pixel",
    "normalize_crs",
    "pixel_to_lonlat",
    "probe",
    "transform_point",
    "transform_points",
    "utm_epsg_for",
]

_log = logging.getLogger("gis.crs")

CrsBackend = Literal["pyproj", "osr", "closed_form", "none"]

_WEB_MERCATOR_ALIASES: frozenset[str] = frozenset(
    {"EPSG:3857", "EPSG:900913", "EPSG:102100", "EPSG:102113"}
)
_GEOGRAPHIC_ALIASES: frozenset[str] = frozenset({"EPSG:4326", "EPSG:4979", "CRS84"})


def normalize_crs(crs: str) -> str:
    """Normalise an authority string to a canonical ``AUTHORITY:CODE`` form.

    Accepts ``"epsg:4326"``, ``"EPSG::4326"``, ``"4326"``, ``"CRS84"`` and the OGC URN
    form. Anything unrecognised is upper-cased and returned unchanged so a backend can
    still try it (WKT and PROJ strings pass through).

    Args:
        crs: An authority string.

    Returns:
        The canonical form.

    Raises:
        CrsError: If ``crs`` is empty.
    """
    if not crs or not crs.strip():
        raise CrsError("empty CRS string")
    key = crs.strip()
    if key.upper().startswith(("+", "PROJCS", "GEOGCS", "PROJCRS", "GEOGCRS")):
        return key  # WKT / PROJ string: leave it alone, only a real backend can read it
    key = key.upper().replace("URN:OGC:DEF:CRS:OGC:1.3:", "").replace("URN:OGC:DEF:CRS:", "")
    key = key.replace("EPSG::", "EPSG:")
    if key.isdigit():
        key = f"EPSG:{key}"
    if key == "CRS84" or key == "OGC:CRS84":
        return "EPSG:4326"
    return key


def utm_epsg_for(lon: float, lat: float) -> str:
    """Return the best UTM zone EPSG code for a point.

    ``zone = min(floor((wrap(lon) + 180) / 6) + 1, 60)``; north ``32600 + zone``,
    south ``32700 + zone``.

    ★ THE CLAMP TO 60 IS THE FIX, AND THE WRAP MUST NOT TOUCH +/-180. The naive
    ``floor((lon + 180) / 6) + 1`` returns **61** at ``lon = 180.0``, giving EPSG:32661 —
    UPS North, a polar stereographic CRS, not a UTM zone at all. Because every metric
    computation in the product routes through this function, the failure is not an
    exception: it is plausible distances in the wrong system.

    ★ CONTRACT DEVIATION (deliberate, and the contract is self-inconsistent here).
    CONTRACT.md §14 C-56 prescribes ``zone = min(int(floor(((lon + 180) % 360) / 6)) + 1, 60)``
    and in the same row demands the goldens ``utm_epsg_for(180.0, 45.0) == "EPSG:32660"``
    and ``utm_epsg_for(-180.0, 45.0) == "EPSG:32601"``. **Its formula fails its own first
    golden**: ``(180 + 180) % 360 == 0``, so ``lon = +180`` lands in zone **1**, not 60.
    The ``% 360`` collapses the east edge of the world onto the west edge. The goldens
    express the correct intent — +180 is the eastern limit (zone 60), -180 the western
    (zone 1) — so the goldens are honoured and the formula is corrected: wrap ONLY when
    ``lon`` is outside ``[-180, 180]``, then clamp. Both goldens pass, and ``lon = 185``
    still correctly resolves to zone 1 via ``-175``.

    Norway zone-32 and Svalbard exceptions are deliberately NOT special-cased. Our AOIs
    are <= 10 km, where using the adjacent zone costs sub-millimetre; a rarely-exercised
    branch would cost more than it buys. It is logged when it applies.

    Args:
        lon: Longitude in degrees.
        lat: Latitude in degrees; sign selects the north/south EPSG family.

    Returns:
        An ``"EPSG:326NN"`` / ``"EPSG:327NN"`` string.

    Raises:
        OutsideUtmError: If ``|lat| > 84`` — outside the UTM domain (use UPS).
        CrsError: If either coordinate is not finite.
    """
    if not (math.isfinite(lon) and math.isfinite(lat)):
        raise CrsError(f"non-finite coordinate: lon={lon}, lat={lat}")
    if abs(lat) > 84.0:
        raise OutsideUtmError(
            f"lat={lat} is outside the UTM domain (|lat| <= 84); a UPS CRS is required"
        )
    # Wrap only genuinely out-of-range longitudes; +/-180 are IN range and are distinct
    # zone-wise, so `% 360` must not be allowed to fold +180 onto -180.
    lon_w = lon if -180.0 <= lon <= 180.0 else ((lon + 180.0) % 360.0) - 180.0
    zone = max(1, min(int(math.floor((lon_w + 180.0) / 6.0)) + 1, 60))
    if 56.0 <= lat < 64.0 and 3.0 <= lon_w < 12.0:
        _log.debug(
            "point (%.4f, %.4f) is in the Norway zone-32 exception region; using standard "
            "zone %d (sub-mm cost at our AOI extents)",
            lon,
            lat,
            zone,
        )
    base = 32600 if lat >= 0.0 else 32700
    return f"EPSG:{base + zone}"


def _have(module: str) -> bool:
    """True iff ``module`` is importable, checked WITHOUT importing it.

    ``find_spec`` has no side effects — no CUDA init, no multi-second import to discover
    we will not use it.
    """
    try:
        return find_spec(module) is not None
    except (ImportError, ValueError):  # pragma: no cover - malformed install
        return False


def backend_name() -> CrsBackend:
    """Return the CRS backend that a general transform would bind right now.

    Never imports anything. ``"closed_form"`` means only EPSG:4326 <-> EPSG:3857 is
    available; ``"none"`` is unreachable in practice (the closed form has no deps) and
    exists so the return type states the whole domain.

    Returns:
        ``"pyproj"``, ``"osr"``, or ``"closed_form"``.
    """
    if _have("pyproj"):
        return "pyproj"
    if _have("osgeo.osr"):
        return "osr"
    return "closed_form"


def probe() -> str:
    """Return a human-readable one-line report of the bound CRS backend.

    Surfaced by ``/health/ready`` and ``GET /capabilities``. A container with neither
    pyproj nor GDAL can only do 4326<->3857, which means UTM metrics — and therefore
    ``total_ce90_m``, mandatory on every GCP — are uncomputable. That must be LOUD, not
    silently accurate-to-nothing.
    """
    backend = backend_name()
    if backend == "pyproj":
        return "crs backend: pyproj (full)"
    if backend == "osr":
        return "crs backend: osgeo.osr (full)"
    return (
        "crs backend: closed-form NumPy (EPSG:4326<->EPSG:3857 ONLY). "
        "UTM metrics, GeoTIFF native CRS and export reprojection are UNAVAILABLE: "
        "install pyproj or GDAL python bindings."
    )


def is_metric_crs(crs: str) -> bool:
    """True iff the CRS's linear unit is the metre.

    ★ Note carefully: EPSG:3857 satisfies this and is STILL not a measurement system.
    Its "metres" are inflated by ``1/cos(phi)`` — 74% at 55N. Use
    ``is_ground_metric_crs`` to gate anything that reports a distance, area or RMSE.

    Args:
        crs: An authority string.

    Returns:
        True if linear units are metres, False for a geographic CRS. Falls back to a
        static EPSG-range check when no backend is installed.
    """
    key = normalize_crs(crs)
    if key in _GEOGRAPHIC_ALIASES:
        return False
    backend = backend_name()
    if backend == "pyproj":
        try:
            from pyproj import CRS as _PyprojCRS

            crs_obj = _PyprojCRS.from_user_input(key)
            if crs_obj.is_geographic:
                return False
            units = {ax.unit_name.lower() for ax in crs_obj.axis_info}
            return bool(units & {"metre", "meter", "m"})
        except Exception:  # noqa: BLE001 - any pyproj failure falls through to the static check
            _log.warning("pyproj could not describe %s; using the static unit check", key)
    elif backend == "osr":
        try:
            from osgeo import osr

            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore", message=r".*Neither osr\.UseExceptions.*", category=FutureWarning
                )
                sr = osr.SpatialReference()
                if sr.SetFromUserInput(key) == 0:
                    if sr.IsGeographic():
                        return False
                    return abs(sr.GetLinearUnits() - 1.0) < 1e-9
        except Exception:  # noqa: BLE001 - any GDAL failure falls through
            _log.warning("osr could not describe %s; using the static unit check", key)

    # Static fallback: the CRSs this product actually uses.
    if key in _WEB_MERCATOR_ALIASES:
        return True
    if key.startswith("EPSG:"):
        try:
            code = int(key.split(":", 1)[1])
        except ValueError:
            return False
        # UTM north/south and UPS: all metre-based.
        if 32601 <= code <= 32660 or 32701 <= code <= 32760 or code in (32661, 32761):
            return True
    return False


def is_ground_metric_crs(crs: str) -> bool:
    """True iff distances measured in this CRS are TRUE ground metres.

    This is ``is_metric_crs`` minus Web Mercator. It exists because EPSG:3857's linear
    unit genuinely IS the metre, so a units-only gate lets a caller measure in 3857 and
    get a number that looks like metres and is not — 74% too large at 55N, which is
    Yorkshire, Denmark, southern Sweden and the Canadian prairie belt. That is the exact
    failure the ``_m`` gate exists to prevent, so the gate needs this predicate and not
    the other one.

    Args:
        crs: An authority string.

    Returns:
        True for UTM/UPS and other projected metre CRSs; False for EPSG:4326 and
        EPSG:3857 alike.
    """
    key = normalize_crs(crs)
    if key in _WEB_MERCATOR_ALIASES:
        return False
    return is_metric_crs(key)


class CrsTransformer:
    """A bound, cached, always-xy coordinate transform.

    Construct only via ``get_transformer``. Instances are immutable and thread-safe.

    Attributes:
        src: Canonical source authority string.
        dst: Canonical destination authority string.
        backend: Which library actually bound — ``"pyproj"``, ``"osr"`` or
            ``"closed_form"``.
    """

    __slots__ = ("_impl", "backend", "dst", "src")

    def __init__(self, src: str, dst: str, backend: CrsBackend, impl: Any) -> None:
        self.src = src
        self.dst = dst
        self.backend: CrsBackend = backend
        self._impl = impl

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"CrsTransformer({self.src!r} -> {self.dst!r}, backend={self.backend!r})"

    def transform(
        self, x: np.ndarray | float, y: np.ndarray | float
    ) -> tuple[np.ndarray, np.ndarray]:
        """Transform coordinates from ``src`` to ``dst``.

        Args:
            x: Easting/longitude — ★ ALWAYS the FIRST argument, in every CRS.
            y: Northing/latitude.

        Returns:
            ``(x_out, y_out)`` float64 arrays shaped like the (broadcast) inputs.

        Raises:
            CrsError: If the backend rejects the coordinates.
        """
        xa = np.atleast_1d(np.asarray(x, dtype=np.float64))
        ya = np.atleast_1d(np.asarray(y, dtype=np.float64))
        if xa.shape != ya.shape:
            xa, ya = np.broadcast_arrays(xa, ya)

        if self.backend == "closed_form":
            out_x, out_y = self._impl(xa, ya)
        elif self.backend == "pyproj":
            out_x, out_y = self._impl.transform(xa, ya)
            out_x = np.asarray(out_x, dtype=np.float64)
            out_y = np.asarray(out_y, dtype=np.float64)
        else:  # osr
            out_x, out_y = _osr_transform(self._impl, xa, ya)

        if not np.all(np.isfinite(out_x) & np.isfinite(out_y)):
            raise CrsError(
                f"transform {self.src} -> {self.dst} produced a non-finite coordinate; "
                "the input is probably outside the destination CRS's domain of validity"
            )
        return (out_x, out_y)


def _osr_transform(
    ct: Any, xa: np.ndarray, ya: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Run an ``osgeo.osr.CoordinateTransformation`` over flat arrays."""
    pts = list(zip(xa.ravel().tolist(), ya.ravel().tolist(), strict=True))
    if not pts:
        return (xa.copy(), ya.copy())
    try:
        res = ct.TransformPoints(pts)
    except Exception as exc:  # noqa: BLE001 - GDAL raises bare RuntimeErrors
        raise CrsError(f"osr transform failed: {exc}") from exc
    arr = np.asarray(res, dtype=np.float64)
    return (arr[:, 0].reshape(xa.shape), arr[:, 1].reshape(xa.shape))


def _closed_form(src: str, dst: str) -> Any | None:
    """Return a closed-form transform callable for ``src`` -> ``dst``, or None.

    Covers exactly the identity and EPSG:4326 <-> EPSG:3857 — the only transform on the
    hot path, four lines of arithmetic, no library required.
    """
    src_geo = src in _GEOGRAPHIC_ALIASES
    dst_geo = dst in _GEOGRAPHIC_ALIASES
    src_wm = src in _WEB_MERCATOR_ALIASES
    dst_wm = dst in _WEB_MERCATOR_ALIASES

    if (src_geo and dst_geo) or (src_wm and dst_wm) or src == dst:
        return lambda x, y: (np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64))
    if src_geo and dst_wm:
        return lonlat_to_meters_array
    if src_wm and dst_geo:
        return meters_to_lonlat_array
    return None


@lru_cache(maxsize=64)
def get_transformer(src: str, dst: str) -> CrsTransformer:
    """Return a cached transform from ``src`` to ``dst``.

    ★ THE ONLY transformer factory in the repo, and it ONLY ever builds always-xy
    transforms. Backends are tried in order: pyproj, osgeo.osr, closed-form NumPy.

    Cached because construction costs milliseconds and these are called per-GCP in tight
    loops.

    Args:
        src: Source CRS authority string.
        dst: Destination CRS authority string.

    Returns:
        A ``CrsTransformer``.

    Raises:
        CrsBackendUnavailable: If no installed backend can serve this pair. Raised at
            CALL time and it names the dependency that would fix it.
        CrsError: If a backend rejects one of the CRS strings.
    """
    src_n = normalize_crs(src)
    dst_n = normalize_crs(dst)

    if _have("pyproj"):
        try:
            from pyproj import Transformer as _PyprojTransformer

            impl = _PyprojTransformer.from_crs(src_n, dst_n, always_xy=True)
            return CrsTransformer(src_n, dst_n, "pyproj", impl)
        except Exception as exc:  # noqa: BLE001 - fall through to the next backend
            _log.warning("pyproj could not build %s -> %s (%s); trying osr", src_n, dst_n, exc)

    if _have("osgeo.osr"):
        try:
            from osgeo import osr

            # ★ Deliberately calling NEITHER osr.UseExceptions() NOR DontUseExceptions():
            #   BOTH eagerly import osgeo.gdal_array, whose compiled extension is built
            #   against NumPy 1.x and fails to initialise under the NumPy 2.4 installed
            #   here — printing an alarming multi-line binary-incompatibility banner and a
            #   fake traceback to stderr on every call. Verified on this machine.
            #   We check SetFromUserInput's return codes explicitly and wrap failures
            #   ourselves, so the exception mode buys nothing and costs real noise.
            #   Declining to call them makes GDAL emit a FutureWarning instead, which is
            #   suppressed here and ONLY here: an unactionable per-boot warning is how
            #   operators learn to ignore warnings that matter.
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message=r".*Neither osr\.UseExceptions.*",
                    category=FutureWarning,
                )
                s_ref = osr.SpatialReference()
                if s_ref.SetFromUserInput(src_n) != 0:
                    raise CrsError(f"osr could not parse source CRS {src_n!r}")
                t_ref = osr.SpatialReference()
                if t_ref.SetFromUserInput(dst_n) != 0:
                    raise CrsError(f"osr could not parse destination CRS {dst_n!r}")
                # ★ The exact always_xy equivalent, mandatory for the identical reason.
                s_ref.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
                t_ref.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
                impl = osr.CoordinateTransformation(s_ref, t_ref)
            return CrsTransformer(src_n, dst_n, "osr", impl)
        except CrsError:
            raise
        except Exception as exc:  # noqa: BLE001 - fall through to the closed form
            _log.warning("osr could not build %s -> %s (%s); trying closed form", src_n, dst_n, exc)

    impl = _closed_form(src_n, dst_n)
    if impl is not None:
        return CrsTransformer(src_n, dst_n, "closed_form", impl)

    raise CrsBackendUnavailable(
        f"no CRS backend can transform {src_n} -> {dst_n}. The closed-form fallback covers "
        "EPSG:4326 <-> EPSG:3857 only. Install pyproj (pip install 'landexplorer-gis[pyproj]') "
        "or the GDAL python bindings."
    )


def transform_points(
    lons: np.ndarray, lats: np.ndarray, src: str, dst: str
) -> tuple[np.ndarray, np.ndarray]:
    """Batch-transform coordinates between two CRSs.

    Vectorised: per-point Python looping is ~100x slower for no reason.

    Args:
        lons: First-axis coordinates (longitude/easting) in ``src``.
        lats: Second-axis coordinates (latitude/northing) in ``src``.
        src: Source CRS authority string.
        dst: Destination CRS authority string.

    Returns:
        ``(x, y)`` float64 arrays in ``dst``, shaped like the inputs.

    Raises:
        CrsBackendUnavailable: If no backend can serve the pair.
        CrsError: If the transform fails or produces non-finite output.
    """
    return get_transformer(src, dst).transform(lons, lats)


def pixel_to_lonlat(gt: GeoTransform, crs: str, col: float, row: float) -> tuple[float, float]:
    """Convert a raster pixel to ``(lon, lat)``, for ANY projected CRS. ★ PIXEL-CENTRE.

    This is the general-CRS sibling of ``gis.tiles.pixel_to_lonlat``. Use this one for a
    local orthophoto in its native UTM zone (or any national grid); use the ``tiles`` one
    on the slippy hot path, where the closed form needs no backend.

    ★ Both share ``gis.tiles.apply_geotransform``, so the ``+0.5`` is applied at exactly
    ONE site and the two functions cannot drift apart. The split exists because §10.4's
    ``gis-tiles-pure`` contract forbids ``gis.tiles`` from importing ``gis.crs`` — tiles
    must stay dependency-free, and only this module may bind a CRS backend.

    Args:
        gt: The raster's geotransform.
        crs: Authority string of ``gt``. Any CRS a backend can resolve.
        col: Fractional pixel column.
        row: Fractional pixel row.

    Returns:
        ``(lon, lat)`` in EPSG:4326 degrees.

    Raises:
        CrsBackendUnavailable: If no backend can serve ``crs`` -> EPSG:4326.
        CrsError: If the transform fails.
    """
    from gis.tiles import apply_geotransform

    x, y = apply_geotransform(gt, col, row)
    return transform_point(x, y, crs, "EPSG:4326")


def lonlat_to_pixel(gt: GeoTransform, crs: str, lon: float, lat: float) -> tuple[float, float]:
    """Convert ``(lon, lat)`` to a raster pixel, for ANY projected CRS.

    ★ THE EXACT INVERSE of this module's ``pixel_to_lonlat``, including the ``-0.5``.
    Round-trips to floating-point resolution, which is what makes the two GCP-adjust
    chains agree on a local orthophoto just as they do on a slippy window.

    Args:
        gt: The raster's geotransform.
        crs: Authority string of ``gt``.
        lon: Longitude in degrees.
        lat: Latitude in degrees.

    Returns:
        ``(col, row)`` as fractional pixel-centre coordinates.

    Raises:
        CrsBackendUnavailable: If no backend can serve EPSG:4326 -> ``crs``.
        ValueError: If ``gt`` is singular.
        CrsError: If the transform fails.
    """
    from gis.tiles import unapply_geotransform

    x, y = transform_point(lon, lat, "EPSG:4326", crs)
    return unapply_geotransform(gt, x, y)


def transform_point(x: float, y: float, src: str, dst: str) -> tuple[float, float]:
    """Transform a single coordinate pair.

    Args:
        x: Longitude/easting in ``src``. ★ Always first, in every CRS.
        y: Latitude/northing in ``src``.
        src: Source CRS authority string.
        dst: Destination CRS authority string.

    Returns:
        ``(x, y)`` in ``dst``.

    Raises:
        CrsBackendUnavailable: If no backend can serve the pair.
        CrsError: If the transform fails.
    """
    out_x, out_y = get_transformer(src, dst).transform(
        np.asarray([x], dtype=np.float64), np.asarray([y], dtype=np.float64)
    )
    return (float(out_x[0]), float(out_y[0]))
