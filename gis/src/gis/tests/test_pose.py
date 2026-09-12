"""Tests for ``gis.pose`` (§13.1 IU-09, §4.28).

★ THE BRANCH TEST: *"a north-up EPSG:3857 window yields grid convergence 0; a UTM ortho
window does not."*

That asymmetry is the whole reason this module exists. For the slippy path the conversion
is the identity — **which is why the missing conversion was invisible in every plausible
test** — and for a local orthophoto in its native UTM zone it is not.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pytest

from gis.crs import backend_name
from gis.errors import CrsError
from gis.pose import (
    grid_convergence_deg,
    pose_footprint,
    pose_sigma_to_deg,
    raster_up_grid_bearing_deg,
    window_xy_to_lonlat,
    window_yaw_to_north_deg,
)
from gis.types import LonLat

_HAVE_FULL_BACKEND = backend_name() in ("pyproj", "osr")

# A north-up EPSG:3857 window at z18, ~55N — the slippy path.
GT_3857 = (1234567.0, 0.5971642834779395, 0.0, 7361866.0, 0.0, -0.5971642834779395)

# A north-up EPSG:32633 orthophoto. 500000 E is the zone's CENTRAL MERIDIAN.
GT_UTM_CM = (500000.0, 0.1, 0.0, 6094791.0, 0.0, -0.1)
# The same, near the zone's EASTERN EDGE, where convergence is largest.
GT_UTM_EDGE = (700000.0, 0.1, 0.0, 6094791.0, 0.0, -0.1)


@dataclass
class _Intrinsics:
    focal_px: float
    principal_point: tuple[float, float]


@dataclass
class _Pose:
    """A structural stand-in for ai_engine.types.PoseResult (which gis may not import)."""

    yaw_deg: float
    intrinsics: Any = None
    camera_position_enu: Any = None


class TestRasterUpBearing:
    def test_north_up_raster_is_zero(self) -> None:
        assert raster_up_grid_bearing_deg(GT_3857) == 0.0
        assert raster_up_grid_bearing_deg(GT_UTM_CM) == 0.0

    def test_rotated_raster(self) -> None:
        """A raster whose rows run east-west: "up the raster" is a grid EAST or WEST.

        Moving one row up changes the projected position by ``(-gt[2], -gt[5])``, and the
        grid bearing of that vector is ``atan2(dx, dy)`` — x FIRST, which is what makes it
        a compass bearing rather than a mathematical angle.
        """
        res = 0.5
        # gt[2] = -res, gt[5] = 0  =>  up = (+res, 0)  =>  due grid EAST.
        gt_east = (0.0, 0.0, -res, 0.0, res, 0.0)
        assert raster_up_grid_bearing_deg(gt_east) == pytest.approx(90.0)

        # gt[2] = +res, gt[5] = 0  =>  up = (-res, 0)  =>  due grid WEST.
        gt_west = (0.0, 0.0, res, 0.0, -res, 0.0)
        assert raster_up_grid_bearing_deg(gt_west) == pytest.approx(270.0)

    def test_45_degree_rotation(self) -> None:
        """A clean diagonal, to pin the bearing convention (clockwise from grid north)."""
        res = 0.5
        theta = math.radians(45.0)
        gt = (
            0.0,
            res * math.cos(theta),
            -res * math.sin(theta),
            0.0,
            -res * math.sin(theta),
            -res * math.cos(theta),
        )
        # up = (res*sin45, res*cos45) -> north-east -> bearing 45.
        assert raster_up_grid_bearing_deg(gt) == pytest.approx(45.0)

    def test_south_up_raster_is_180(self) -> None:
        """A positive pixel_height means the raster is stored bottom-up."""
        gt = (0.0, 0.5, 0.0, 0.0, 0.0, 0.5)
        assert raster_up_grid_bearing_deg(gt) == pytest.approx(180.0)

    def test_rejects_degenerate(self) -> None:
        with pytest.raises(ValueError, match="degenerate"):
            raster_up_grid_bearing_deg((0.0, 0.5, 0.0, 0.0, 0.0, 0.0))


class TestGridConvergence:
    """★★ THE BRANCH TEST (§13.1 IU-09)."""

    def test_web_mercator_convergence_is_exactly_zero(self) -> None:
        """★ Mercator is cylindrical: grid north IS true north, everywhere.

        Exactly 0.0, not 1e-12 — it is short-circuited, so the slippy hot path costs
        nothing and the identity is exact.
        """
        for lon in (-179.0, -15.0, 0.0, 15.0, 179.0):
            for lat in (-60.0, 0.0, 55.0, 80.0):
                assert grid_convergence_deg("EPSG:3857", lon, lat) == 0.0

    @pytest.mark.skipif(not _HAVE_FULL_BACKEND, reason="needs pyproj or osr for UTM")
    def test_utm_convergence_is_zero_on_the_central_meridian(self) -> None:
        """On the CM, grid north and true north coincide by construction."""
        assert grid_convergence_deg("EPSG:32633", 15.0, 55.0) == pytest.approx(0.0, abs=1e-6)

    @pytest.mark.skipif(not _HAVE_FULL_BACKEND, reason="needs pyproj or osr for UTM")
    def test_utm_convergence_is_not_zero_off_the_central_meridian(self) -> None:
        """★★ THE OTHER HALF OF THE BRANCH. A UTM ortho does NOT get the identity."""
        gamma = grid_convergence_deg("EPSG:32633", 18.0, 55.0)
        assert gamma != 0.0
        assert abs(gamma) > 0.5, "convergence 3 deg east of the CM at 55N should be ~2.5 deg"

    @pytest.mark.skipif(not _HAVE_FULL_BACKEND, reason="needs pyproj or osr for UTM")
    def test_convergence_matches_the_series_formula(self) -> None:
        """The numeric solve must agree with ``gamma ~= (lon - lon0) * sin(lat)``.

        Checking the general numeric method against the closed form is what makes the
        numeric method trustworthy for the national grids it also has to serve.
        """
        lon0 = 15.0  # zone 33N's central meridian
        for lon, lat in ((16.0, 55.0), (18.0, 55.0), (12.0, 60.0), (17.0, 45.0)):
            got = grid_convergence_deg("EPSG:32633", lon, lat)
            approx = (lon - lon0) * math.sin(math.radians(lat))
            assert got == pytest.approx(approx, abs=0.02), f"at ({lon}, {lat})"

    @pytest.mark.skipif(not _HAVE_FULL_BACKEND, reason="needs pyproj or osr for UTM")
    def test_convergence_sign_flips_across_the_central_meridian(self) -> None:
        east = grid_convergence_deg("EPSG:32633", 18.0, 55.0)
        west = grid_convergence_deg("EPSG:32633", 12.0, 55.0)
        assert east > 0 > west
        assert east == pytest.approx(-west, abs=0.05)

    @pytest.mark.skipif(not _HAVE_FULL_BACKEND, reason="needs pyproj or osr for UTM")
    def test_convergence_grows_away_from_the_central_meridian(self) -> None:
        near = abs(grid_convergence_deg("EPSG:32633", 16.0, 55.0))
        far = abs(grid_convergence_deg("EPSG:32633", 18.0, 55.0))
        assert far > near

    def test_rejects_geographic_crs(self) -> None:
        """Asking for a geographic CRS's grid convergence is a frame confusion."""
        with pytest.raises(CrsError, match="undefined"):
            grid_convergence_deg("EPSG:4326", 15.0, 55.0)


class TestWindowYawToNorth:
    """★ The conversion nobody owned in v1.0."""

    def test_north_up_3857_is_the_identity(self) -> None:
        """★ For a north-up slippy window this is a no-op — which is exactly why the
        missing conversion never showed up in a test."""
        for yaw in (0.0, 45.0, 90.0, 180.0, 271.5):
            got = window_yaw_to_north_deg(yaw, GT_3857, "EPSG:3857", 11.09, 55.0)
            assert got == pytest.approx(yaw % 360.0, abs=1e-9)

    def test_camera_facing_image_north_lands_at_zero_for_3857(self) -> None:
        """★ §13.1's exact assertion for the 3857 branch."""
        assert window_yaw_to_north_deg(0.0, GT_3857, "EPSG:3857", 11.09, 55.0) == 0.0

    @pytest.mark.skipif(not _HAVE_FULL_BACKEND, reason="needs pyproj or osr for UTM")
    def test_camera_facing_image_north_is_nonzero_for_a_utm_ortho(self) -> None:
        """★ §13.1's exact assertion for the UTM branch: NOT the identity."""
        lon, lat = 18.0, 55.0
        got = window_yaw_to_north_deg(0.0, GT_UTM_EDGE, "EPSG:32633", lon, lat)
        assert got != 0.0
        expected = grid_convergence_deg("EPSG:32633", lon, lat) % 360.0
        assert got == pytest.approx(expected, abs=1e-9)

    def test_rotated_geotransform_contributes(self) -> None:
        """A rotated window's raster-up is not grid north, and the yaw must say so."""
        res = 0.5
        theta = math.radians(30.0)
        gt = (
            0.0,
            res * math.cos(theta),
            -res * math.sin(theta),
            0.0,
            -res * math.sin(theta),
            -res * math.cos(theta),
        )
        got = window_yaw_to_north_deg(0.0, gt, "EPSG:3857", 11.0, 55.0)
        assert got == pytest.approx(raster_up_grid_bearing_deg(gt), abs=1e-9)
        assert got != 0.0

    def test_result_is_wrapped_into_0_360(self) -> None:
        for yaw in (-90.0, 0.0, 359.9, 370.0, 720.0):
            got = window_yaw_to_north_deg(yaw, GT_3857, "EPSG:3857", 11.09, 55.0)
            assert 0.0 <= got < 360.0

    def test_rejects_non_finite_yaw(self) -> None:
        with pytest.raises(ValueError, match="finite"):
            window_yaw_to_north_deg(float("nan"), GT_3857, "EPSG:3857", 11.0, 55.0)


class TestWindowXyToLonLat:
    def test_uses_the_pixel_centre_convention(self) -> None:
        """★ Must match gis.tiles exactly, or a pose and a GCP disagree by half a pixel."""
        from gis.tiles import pixel_to_lonlat

        got = window_xy_to_lonlat((13.25, 91.75), GT_3857, "EPSG:3857")
        lon, lat = pixel_to_lonlat(GT_3857, "EPSG:3857", 13.25, 91.75)
        assert got == LonLat(lon=lon, lat=lat)

    def test_returns_a_lonlat_not_a_tuple(self) -> None:
        got = window_xy_to_lonlat((0.0, 0.0), GT_3857, "EPSG:3857")
        assert isinstance(got, LonLat)


class TestPoseFootprint:
    def test_apex_is_first_and_last(self) -> None:
        pose = _Pose(yaw_deg=0.0, intrinsics=_Intrinsics(500.0, (320.0, 240.0)))
        ring = pose_footprint(
            pose, GT_3857, "EPSG:3857", max_range_m=200.0, apex_px=(128.0, 128.0)
        )
        assert ring[0] == ring[-1]
        assert len(ring) >= 4

    def test_cone_points_along_the_yaw(self) -> None:
        """A camera facing north must have its cone to the NORTH of the apex."""
        pose = _Pose(yaw_deg=0.0, intrinsics=_Intrinsics(500.0, (320.0, 240.0)))
        ring = pose_footprint(
            pose, GT_3857, "EPSG:3857", max_range_m=500.0, apex_px=(128.0, 128.0)
        )
        apex = ring[0]
        far = ring[1:-1]
        assert all(p.lat > apex.lat for p in far), "a north-facing cone must extend north"

    def test_cone_facing_east(self) -> None:
        pose = _Pose(yaw_deg=90.0, intrinsics=_Intrinsics(500.0, (320.0, 240.0)))
        ring = pose_footprint(
            pose, GT_3857, "EPSG:3857", max_range_m=500.0, apex_px=(128.0, 128.0)
        )
        apex = ring[0]
        assert all(p.lon > apex.lon for p in ring[1:-1])

    def test_range_is_honoured(self) -> None:
        from gis.geometry import great_circle_distance_m

        pose = _Pose(yaw_deg=0.0, intrinsics=_Intrinsics(500.0, (320.0, 240.0)))
        ring = pose_footprint(
            pose, GT_3857, "EPSG:3857", max_range_m=300.0, apex_px=(128.0, 128.0)
        )
        for p in ring[1:-1]:
            assert great_circle_distance_m(ring[0], p) == pytest.approx(300.0, rel=1e-3)

    def test_apex_from_enu_and_origin(self) -> None:
        """The §4.24(4) frame inversion: X_east = (u-u_ref)*gsd, Y_north = (v_ref-v)*gsd."""
        pose = _Pose(
            yaw_deg=0.0,
            intrinsics=_Intrinsics(500.0, (320.0, 240.0)),
            camera_position_enu=np.array([10.0, -20.0, 1.6]),
        )
        ring = pose_footprint(
            pose,
            GT_3857,
            "EPSG:3857",
            max_range_m=100.0,
            origin_px=(128.0, 128.0),
            gsd_m=0.5,
        )
        # east +10 m at 0.5 m/px => +20 px; north -20 m => v_ref + 40 px (v grows SOUTH).
        expected = window_xy_to_lonlat((148.0, 168.0), GT_3857, "EPSG:3857")
        assert ring[0] == expected

    def test_refuses_without_an_apex(self) -> None:
        """★ L12: refuse rather than draw a confidently wrong picture."""
        pose = _Pose(yaw_deg=0.0, intrinsics=_Intrinsics(500.0, (320.0, 240.0)))
        with pytest.raises(ValueError, match="cannot locate the camera"):
            pose_footprint(pose, GT_3857, "EPSG:3857", max_range_m=100.0)

    def test_hfov_from_intrinsics(self) -> None:
        """2*atan(cx/f): f=320, cx=320 => 90 degrees."""
        pose = _Pose(yaw_deg=0.0, intrinsics=_Intrinsics(320.0, (320.0, 240.0)))
        ring = pose_footprint(
            pose, GT_3857, "EPSG:3857", max_range_m=100.0, apex_px=(128.0, 128.0), arc_steps=2
        )
        # With a 90 deg fov centred on north, the arc spans bearings -45..+45.
        assert ring[1].lon < ring[0].lon  # left edge is west
        assert ring[3].lon > ring[0].lon  # right edge is east

    def test_explicit_hfov_overrides(self) -> None:
        pose = _Pose(yaw_deg=0.0, intrinsics=_Intrinsics(500.0, (320.0, 240.0)))
        narrow = pose_footprint(
            pose, GT_3857, "EPSG:3857", max_range_m=100.0, apex_px=(0.0, 0.0), hfov_deg=10.0
        )
        wide = pose_footprint(
            pose, GT_3857, "EPSG:3857", max_range_m=100.0, apex_px=(0.0, 0.0), hfov_deg=120.0
        )
        narrow_span = max(p.lon for p in narrow) - min(p.lon for p in narrow)
        wide_span = max(p.lon for p in wide) - min(p.lon for p in wide)
        assert wide_span > narrow_span

    def test_rejects_bad_range(self) -> None:
        pose = _Pose(yaw_deg=0.0, intrinsics=_Intrinsics(500.0, (320.0, 240.0)))
        with pytest.raises(ValueError, match="max_range_m"):
            pose_footprint(pose, GT_3857, "EPSG:3857", max_range_m=0.0, apex_px=(0.0, 0.0))


class TestPoseSigma:
    def test_a_rigid_rotation_does_not_change_sigmas(self) -> None:
        """Var(X + c) == Var(X): convergence is a constant offset, not a scaling."""
        got = pose_sigma_to_deg((1.5, 2.0, 3.0), GT_3857, "EPSG:3857", 11.09, 55.0)
        assert got == (1.5, 2.0, 3.0)

    @pytest.mark.skipif(not _HAVE_FULL_BACKEND, reason="needs pyproj or osr for UTM")
    def test_utm_also_passes_sigmas_through(self) -> None:
        got = pose_sigma_to_deg((1.5, 2.0, 3.0), GT_UTM_EDGE, "EPSG:32633", 18.0, 55.0)
        assert got == (1.5, 2.0, 3.0)

    def test_validates_its_inputs(self) -> None:
        with pytest.raises(ValueError, match="sigma_yaw"):
            pose_sigma_to_deg((-1.0, 0.0, 0.0), GT_3857, "EPSG:3857", 11.0, 55.0)
        with pytest.raises(ValueError, match="3-tuple"):
            pose_sigma_to_deg((1.0, 2.0), GT_3857, "EPSG:3857", 11.0, 55.0)  # type: ignore[arg-type]

    def test_validates_the_geotransform(self) -> None:
        with pytest.raises(ValueError, match="degenerate"):
            pose_sigma_to_deg(
                (1.0, 1.0, 1.0), (0.0, 0.5, 0.0, 0.0, 0.0, 0.0), "EPSG:3857", 11.0, 55.0
            )
