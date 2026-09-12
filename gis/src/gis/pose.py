"""Window frame to geography: the ONLY sanctioned place pose becomes North (§4.28).

``ai_engine`` emits a **window-local** pose — ``PoseResult.yaw_deg`` is 0 = UP THE RASTER
(the ``-y`` direction of the window frame), because ``ai_engine`` may not know what a CRS
is (L3) and therefore cannot know where north is. The database's ``camera_poses.yaw_deg``
is 0 = **TRUE North**. Converting between them requires two things ``ai_engine`` cannot
have:

1. the geotransform's **rotation terms** — which way is up the raster, in the grid; and
2. **grid convergence** — the angle between projected-grid north and TRUE north at a point.

For a north-up EPSG:3857 window both are exactly zero and the conversion is the identity,
**which is why this bug is invisible in every plausible test**. For a local orthophoto in
its native UTM zone, convergence is NOT zero and grows with distance from the zone's
central meridian — a degree or more at a zone edge, which is a whole field's width at the
end of a 500 m view cone.

Nothing else in the codebase may perform this conversion. ``pose_service`` calls these
functions; it never does frame math itself.

★ Per SCOPE.md, camera pose ESTIMATION is deferred (``ai_engine`` ships the ABC only), so
nothing calls these in this build. They are implemented rather than stubbed because
SCOPE.md §7 requires that enabling the engine later touch **nothing outside**
``ai_engine/`` — a stub here would make that false. The math is pure geodesy and is
correct on its own terms today.
"""

from __future__ import annotations

import math
from typing import Any, Protocol

from gis.crs import transform_point
from gis.errors import CrsError
from gis.tiles import pixel_to_lonlat
from gis.types import GeoTransform, LonLat

__all__ = [
    "grid_convergence_deg",
    "pose_footprint",
    "pose_sigma_to_deg",
    "raster_up_grid_bearing_deg",
    "window_xy_to_lonlat",
    "window_yaw_to_north_deg",
]

_CONVERGENCE_PROBE_M: float = 1.0
"""Northward probe distance, in degrees-equivalent metres, for the numeric convergence solve."""


class _PoseLike(Protocol):
    """The structural shape of ``ai_engine.types.PoseResult`` that this module reads.

    Declared locally and duck-typed: ``gis.pose`` may not import ``ai_engine`` (§10.2
    grants that import to ``gis.candidates`` and ``gis.heatmap`` only). Reading these
    attributes off the real ``PoseResult`` is exactly what §4.28 asks for.
    """

    yaw_deg: float
    intrinsics: Any


def raster_up_grid_bearing_deg(gt: GeoTransform) -> float:
    """Return the GRID bearing of the raster's "up" (``-row``) direction, in degrees.

    0 = grid north, clockwise. For a north-up raster (``gt[2] == 0``, ``gt[5] < 0``) this
    is exactly 0.

    Moving one row UP changes the projected coordinate by ``(-gt[2], -gt[5])``. Its
    bearing from grid north is ``atan2(dx, dy)`` — note ``x`` first, which is what makes
    it a compass bearing rather than a mathematical angle.

    Args:
        gt: The window's geotransform.

    Returns:
        The bearing in ``[0, 360)``.

    Raises:
        ValueError: If the geotransform has no row direction (both terms zero).
    """
    dx = -gt[2]
    dy = -gt[5]
    if dx == 0.0 and dy == 0.0:
        raise ValueError(f"geotransform has a degenerate row direction: {gt}")
    return math.degrees(math.atan2(dx, dy)) % 360.0


def grid_convergence_deg(crs: str, lon: float, lat: float) -> float:
    """Return the grid convergence at a point: the bearing of GRID north from TRUE north.

    Positive means grid north lies clockwise of true north. The relation this defines,
    and the only one that matters downstream::

        true_azimuth = grid_bearing + grid_convergence

    Computed NUMERICALLY rather than from the UTM series formula
    ``gamma ~= (lon - lon0) * sin(lat)``: the numeric solve needs no per-projection
    formula, works for any projected CRS a local orthophoto might declare (UTM, a national
    grid, a Lambert conformal conic), and cannot silently disagree with the transformer
    that produced the coordinates in the first place.

    ★ For EPSG:3857 this returns exactly 0.0 by construction — Mercator is a cylindrical
    projection whose grid north IS true north everywhere. It is short-circuited rather
    than solved so the slippy path costs nothing and is exactly zero rather than 1e-12.

    Args:
        crs: Authority string of the projected grid.
        lon: Longitude in degrees.
        lat: Latitude in degrees.

    Returns:
        Convergence in degrees, in ``(-180, 180]``.

    Raises:
        CrsError: If the CRS is geographic (a geographic "grid" has no convergence to
            speak of and asking is a frame confusion), or if no backend can transform it.
    """
    from gis.crs import is_metric_crs, normalize_crs  # local: keeps the module graph shallow

    key = normalize_crs(crs)
    if key in ("EPSG:3857", "EPSG:900913", "EPSG:102100", "EPSG:102113"):
        return 0.0
    if not is_metric_crs(key):
        raise CrsError(
            f"grid convergence is undefined for the geographic CRS {key}; it is the angle "
            "between a PROJECTED grid's north and true north"
        )

    # Probe a point due TRUE north of (lon, lat) and see which way it lands in the grid.
    dlat = math.degrees(_CONVERGENCE_PROBE_M / 6378137.0)
    lat_n = min(90.0, lat + dlat)
    if lat_n == lat:  # pragma: no cover - only at the pole itself
        raise CrsError(f"cannot probe north of lat={lat}")

    x0, y0 = transform_point(lon, lat, "EPSG:4326", key)
    x1, y1 = transform_point(lon, lat_n, "EPSG:4326", key)
    dx, dy = x1 - x0, y1 - y0
    if dx == 0.0 and dy == 0.0:
        raise CrsError(f"degenerate convergence probe at ({lon}, {lat}) in {key}")

    # (dx, dy) points to TRUE north, expressed in grid axes. Its grid bearing is the
    # bearing of true north FROM grid north; convergence is the negation of that.
    bearing_of_true_north = math.degrees(math.atan2(dx, dy))
    convergence = -bearing_of_true_north
    # Fold into (-180, 180].
    convergence = ((convergence + 180.0) % 360.0) - 180.0
    return convergence


def window_yaw_to_north_deg(
    yaw_deg: float,
    gt: GeoTransform,
    crs: str,
    lon: float,
    lat: float,
) -> float:
    """Convert a window-frame yaw to a TRUE-North yaw for ``camera_poses.yaw_deg``.

    Applies, in order, (a) the geotransform's rotation and (b) grid convergence::

        true_yaw = yaw_window + raster_up_grid_bearing(gt) + grid_convergence(crs, lon, lat)

    Args:
        yaw_deg: ``PoseResult.yaw_deg`` — 0 = up the window raster (``-y``), clockwise.
        gt: The window's geotransform.
        crs: Authority string of ``gt``.
        lon: Longitude of the camera, degrees — convergence is position-dependent.
        lat: Latitude of the camera, degrees.

    Returns:
        Yaw with 0 = TRUE North, clockwise, in ``[0, 360)``.

    Raises:
        ValueError: If ``yaw_deg`` is not finite or ``gt`` is degenerate.
        CrsError: If convergence cannot be computed for ``crs``.
    """
    if not math.isfinite(yaw_deg):
        raise ValueError(f"yaw_deg must be finite, got {yaw_deg}")
    rotation = raster_up_grid_bearing_deg(gt)
    convergence = grid_convergence_deg(crs, lon, lat)
    return (yaw_deg + rotation + convergence) % 360.0


def window_xy_to_lonlat(
    t_px: tuple[float, float], gt: GeoTransform, crs: str
) -> LonLat:
    """Convert a window pixel to a geographic position.

    Uses the PIXEL-CENTRE convention via ``gis.tiles.pixel_to_lonlat`` — the same one
    every GCP goes through, so a pose's position and a GCP's position can never disagree
    by the half pixel that would otherwise creep in here.

    Args:
        t_px: ``(col, row)`` in window pixels.
        gt: The window's geotransform.
        crs: Authority string of ``gt``.

    Returns:
        The position as a ``LonLat``.

    Raises:
        CrsError: If ``crs`` needs a backend that cannot be bound.
    """
    lon, lat = pixel_to_lonlat(gt, crs, float(t_px[0]), float(t_px[1]))
    return LonLat(lon=lon, lat=lat)


def _hfov_deg(pose: _PoseLike) -> float:
    """Derive the horizontal field of view from a pose's intrinsics, in degrees.

    ``hfov = 2 * atan(cx / focal_px)``, taking the principal point's x as the half-width.
    Falls back to 60 degrees — a typical phone camera — when intrinsics are unusable,
    because a footprint is a visual aid and refusing to draw one over a missing focal
    length would be worse than drawing a nominal one.
    """
    intr = getattr(pose, "intrinsics", None)
    focal = float(getattr(intr, "focal_px", 0.0) or 0.0)
    pp = getattr(intr, "principal_point", None)
    half_w = float(pp[0]) if pp is not None else 0.0
    if focal > 0.0 and half_w > 0.0:
        return 2.0 * math.degrees(math.atan(half_w / focal))
    return 60.0


def pose_footprint(
    pose: _PoseLike,
    gt: GeoTransform,
    crs: str,
    *,
    max_range_m: float,
    apex_px: tuple[float, float] | None = None,
    origin_px: tuple[float, float] | None = None,
    gsd_m: float | None = None,
    hfov_deg: float | None = None,
    arc_steps: int = 12,
) -> list[LonLat]:
    """Return the camera's view cone as a closed 4326 ring, for ``camera_poses.footprint``.

    Drives the Leaflet view cone. The ring is apex -> arc across the field of view at
    ``max_range_m`` -> back to apex, in ``[lon, lat]`` order.

    ★ The apex must be supplied in a frame this module can read. ``PoseResult`` carries
    ``camera_position_enu`` in **ENU metres relative to the Zhang-plane reference point**,
    and §4.24(4) defines that frame as ``X_east = (u - u_ref) * gsd_m``,
    ``Y_north = (v_ref - v) * gsd_m``. Recovering window pixels from it therefore needs
    ``u_ref``/``v_ref`` and ``gsd_m`` — which §4.28's signature does not carry and no
    ``ai_engine`` type exposes. So: pass ``apex_px`` directly, or pass ``origin_px`` +
    ``gsd_m`` and this inverts the frame for you. If neither is given this REFUSES rather
    than guessing an apex (L12) — a footprint drawn at a fabricated origin is a confidently
    wrong picture of where someone stood.

    Args:
        pose: The window-frame pose. Read for ``yaw_deg`` and ``intrinsics``.
        gt: The window's geotransform.
        crs: Authority string of ``gt``.
        max_range_m: Cone length in TRUE ground metres, ``> 0``.
        apex_px: Camera position in window pixels ``(col, row)``. Preferred.
        origin_px: The Zhang-plane reference point ``(u_ref, v_ref)`` in window pixels.
            Used with ``gsd_m`` to invert ``pose.camera_position_enu``.
        gsd_m: TRUE ground metres per pixel, required with ``origin_px``.
        hfov_deg: Horizontal field of view. Defaults to a value derived from
            ``pose.intrinsics``.
        arc_steps: Number of segments in the far arc, ``>= 1``.

    Returns:
        A closed ring of ``LonLat``, first point == last point.

    Raises:
        ValueError: If ``max_range_m <= 0``, ``arc_steps < 1``, or no apex can be resolved.
        CrsError: If ``crs`` needs a backend that cannot be bound.
    """
    if not math.isfinite(max_range_m) or max_range_m <= 0.0:
        raise ValueError(f"max_range_m must be finite and > 0, got {max_range_m}")
    if arc_steps < 1:
        raise ValueError(f"arc_steps must be >= 1, got {arc_steps}")

    apex = _resolve_apex_px(pose, apex_px, origin_px, gsd_m)
    apex_ll = window_xy_to_lonlat(apex, gt, crs)

    yaw_true = window_yaw_to_north_deg(pose.yaw_deg, gt, crs, apex_ll.lon, apex_ll.lat)
    fov = _hfov_deg(pose) if hfov_deg is None else float(hfov_deg)
    if not math.isfinite(fov) or not (0.0 < fov < 360.0):
        raise ValueError(f"hfov_deg must be in (0, 360), got {fov}")

    ring: list[LonLat] = [apex_ll]
    start = yaw_true - fov / 2.0
    for i in range(arc_steps + 1):
        bearing = start + fov * (i / arc_steps)
        ring.append(_offset_geodesic(apex_ll, bearing, max_range_m))
    ring.append(apex_ll)
    return ring


def _resolve_apex_px(
    pose: _PoseLike,
    apex_px: tuple[float, float] | None,
    origin_px: tuple[float, float] | None,
    gsd_m: float | None,
) -> tuple[float, float]:
    """Resolve the camera's window-pixel position, or refuse."""
    if apex_px is not None:
        return (float(apex_px[0]), float(apex_px[1]))

    position = getattr(pose, "camera_position_enu", None)
    if position is not None and origin_px is not None and gsd_m:
        if not math.isfinite(gsd_m) or gsd_m <= 0.0:
            raise ValueError(f"gsd_m must be finite and > 0, got {gsd_m}")
        east = float(position[0])
        north = float(position[1])
        # Invert §4.24(4): X_east = (u - u_ref)*gsd_m ; Y_north = (v_ref - v)*gsd_m.
        return (origin_px[0] + east / gsd_m, origin_px[1] - north / gsd_m)

    raise ValueError(
        "pose_footprint cannot locate the camera: pass apex_px, or pass origin_px and "
        "gsd_m so camera_position_enu can be inverted into window pixels. Guessing an "
        "apex would draw a confidently wrong picture of where the photographer stood."
    )


def _offset_geodesic(origin: LonLat, bearing_deg: float, distance_m: float) -> LonLat:
    """Return the point ``distance_m`` from ``origin`` along ``bearing_deg`` (0 = North, CW).

    Spherical direct solution on a sphere of radius ``EARTH_RADIUS_M``. Accurate to ~0.3%
    against WGS84, which is right for a view cone drawn on a map and is never reported as
    a survey number.
    """
    radius = 6378137.0
    ang = distance_m / radius
    brg = math.radians(bearing_deg)
    phi1 = math.radians(origin.lat)
    lam1 = math.radians(origin.lon)

    sin_phi2 = math.sin(phi1) * math.cos(ang) + math.cos(phi1) * math.sin(ang) * math.cos(brg)
    sin_phi2 = max(-1.0, min(1.0, sin_phi2))
    phi2 = math.asin(sin_phi2)
    lam2 = lam1 + math.atan2(
        math.sin(brg) * math.sin(ang) * math.cos(phi1),
        math.cos(ang) - math.sin(phi1) * sin_phi2,
    )
    lon = ((math.degrees(lam2) + 180.0) % 360.0) - 180.0
    return LonLat(lon=lon, lat=math.degrees(phi2))


def pose_sigma_to_deg(
    sigma_deg: tuple[float, float, float],
    gt: GeoTransform,
    crs: str,
    lon: float,
    lat: float,
) -> tuple[float, float, float]:
    """Map a window-frame ``(yaw, pitch, roll)`` 1-sigma triple into the true-North frame.

    The conversion ``window_yaw_to_north_deg`` applies is a **rigid rotation** — it adds
    two position-dependent constants to yaw and touches nothing else. A constant offset
    has zero derivative, so the uncertainties pass through unchanged: ``Var(X + c) ==
    Var(X)``.

    ★ This function therefore exists to be *called* rather than to compute: it makes the
    frame change explicit at the one place it happens, so a reader can see the sigmas were
    considered rather than quietly reused. Its arguments are validated, which is the part
    that has caught real bugs. The one thing that WOULD change the sigmas — a
    scale-varying reprojection — cannot occur here, because grid convergence is an angle,
    not a scale.

    Args:
        sigma_deg: ``(yaw, pitch, roll)`` 1-sigma, degrees, all ``>= 0``.
        gt: The window's geotransform. Validated for degeneracy.
        crs: Authority string of ``gt``. Validated by computing convergence.
        lon: Longitude of the camera, degrees.
        lat: Latitude of the camera, degrees.

    Returns:
        ``(yaw, pitch, roll)`` 1-sigma in degrees, in the true-North frame.

    Raises:
        ValueError: If any sigma is negative or not finite, or ``gt`` is degenerate.
        CrsError: If convergence cannot be computed for ``crs``.
    """
    if len(sigma_deg) != 3:
        raise ValueError(f"sigma_deg must be a 3-tuple, got {len(sigma_deg)} elements")
    for name, value in zip(("yaw", "pitch", "roll"), sigma_deg, strict=True):
        if not math.isfinite(value) or value < 0.0:
            raise ValueError(f"sigma_{name} must be finite and >= 0, got {value}")
    raster_up_grid_bearing_deg(gt)  # validates gt
    grid_convergence_deg(crs, lon, lat)  # validates crs and the position
    return (float(sigma_deg[0]), float(sigma_deg[1]), float(sigma_deg[2]))
