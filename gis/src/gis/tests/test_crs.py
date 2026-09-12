"""Tests for ``gis.crs`` (§13.1 IU-09).

★ On the verified dev box **pyproj is ABSENT and osgeo IS PRESENT**, so the ``osr`` leg
and the closed-form leg are the ones that actually execute here. That is deliberate: it
means the fallback chain is tested rather than merely written.
"""

from __future__ import annotations

import importlib.util

import numpy as np
import pytest

from gis.crs import (
    backend_name,
    get_transformer,
    is_ground_metric_crs,
    is_metric_crs,
    lonlat_to_pixel,
    normalize_crs,
    pixel_to_lonlat,
    probe,
    transform_point,
    transform_points,
    utm_epsg_for,
)
from gis.errors import CrsError, OutsideUtmError

_HAVE_FULL_BACKEND = backend_name() in ("pyproj", "osr")


class TestUtmZoneSelection:
    """★ The UPS-North off-by-one, and the wrap that must not touch +/-180."""

    def test_antimeridian_goldens(self) -> None:
        """★ §14 C-56's goldens. Note the contract's own FORMULA fails the first one.

        C-56 prescribes ``min(int(floor(((lon + 180) % 360) / 6)) + 1, 60)``. At
        ``lon = 180`` the ``% 360`` yields 0, giving zone 1 / EPSG:32601 — contradicting
        the golden stated in the same row. The goldens carry the correct intent (+180 is
        the EAST limit, zone 60; -180 the west, zone 1), so the goldens win and the
        formula is corrected in ``utm_epsg_for``.
        """
        assert utm_epsg_for(180.0, 45.0) == "EPSG:32660"
        assert utm_epsg_for(-180.0, 45.0) == "EPSG:32601"

    def test_never_returns_ups(self) -> None:
        """★ EPSG:32661 is UPS North — polar stereographic, NOT a UTM zone.

        The naive ``floor((lon + 180) / 6) + 1`` returns 61 at lon = 180, and because §6.1
        routes EVERY metric computation through this function the failure is not an
        exception: it is plausible distances in the wrong system.
        """
        for lon in (179.0, 179.999, 180.0):
            epsg = utm_epsg_for(lon, 45.0)
            assert epsg not in ("EPSG:32661", "EPSG:32761")
            assert epsg == "EPSG:32660"

    @pytest.mark.parametrize(
        ("lon", "lat", "expected"),
        [
            (-177.0, 45.0, "EPSG:32601"),
            (-171.0, 45.0, "EPSG:32602"),
            (-3.0, 51.5, "EPSG:32630"),
            (3.0, 51.5, "EPSG:32631"),
            (9.0, 55.0, "EPSG:32632"),
            (15.0, 55.0, "EPSG:32633"),
            (177.0, 45.0, "EPSG:32660"),
        ],
    )
    def test_northern_zones(self, lon: float, lat: float, expected: str) -> None:
        assert utm_epsg_for(lon, lat) == expected

    def test_southern_hemisphere_uses_327xx(self) -> None:
        assert utm_epsg_for(15.0, -33.0) == "EPSG:32733"
        assert utm_epsg_for(151.2, -33.9) == "EPSG:32756"

    def test_equator_is_northern(self) -> None:
        """lat == 0 resolves north. An arbitrary but FIXED choice; ties must not wobble."""
        assert utm_epsg_for(15.0, 0.0) == "EPSG:32633"

    def test_out_of_range_longitude_wraps(self) -> None:
        assert utm_epsg_for(185.0, 45.0) == utm_epsg_for(-175.0, 45.0)

    def test_rejects_polar(self) -> None:
        with pytest.raises(OutsideUtmError):
            utm_epsg_for(0.0, 85.0)
        with pytest.raises(OutsideUtmError):
            utm_epsg_for(0.0, -85.0)

    def test_rejects_non_finite(self) -> None:
        with pytest.raises(CrsError):
            utm_epsg_for(float("nan"), 45.0)


class TestNormalize:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("EPSG:4326", "EPSG:4326"),
            ("epsg:4326", "EPSG:4326"),
            ("EPSG::4326", "EPSG:4326"),
            ("4326", "EPSG:4326"),
            ("CRS84", "EPSG:4326"),
            ("urn:ogc:def:crs:OGC:1.3:CRS84", "EPSG:4326"),
            ("  EPSG:3857  ", "EPSG:3857"),
            ("EPSG:32633", "EPSG:32633"),
        ],
    )
    def test_normalize(self, raw: str, expected: str) -> None:
        assert normalize_crs(raw) == expected

    def test_rejects_empty(self) -> None:
        with pytest.raises(CrsError):
            normalize_crs("")


class TestMetricGate:
    """``is_metric_crs`` is about UNITS; ``is_ground_metric_crs`` is about TRUTH."""

    def test_geographic_is_not_metric(self) -> None:
        assert is_metric_crs("EPSG:4326") is False
        assert is_ground_metric_crs("EPSG:4326") is False

    def test_web_mercator_has_metre_units_but_is_not_ground_metric(self) -> None:
        """★ THE distinction that stops accuracy.py measuring in 3857.

        EPSG:3857's linear unit genuinely IS the metre, so a units-only gate lets a caller
        measure with it — and get a number that looks like metres and is 74% too large at
        55N. Both predicates are correct; only one is the right gate for a ``_m`` function.
        """
        assert is_metric_crs("EPSG:3857") is True
        assert is_ground_metric_crs("EPSG:3857") is False

    def test_utm_is_ground_metric(self) -> None:
        assert is_metric_crs("EPSG:32633") is True
        assert is_ground_metric_crs("EPSG:32633") is True
        assert is_ground_metric_crs("EPSG:32733") is True


class TestClosedForm:
    """The 4326 <-> 3857 leg works with NO backend at all."""

    def test_closed_form_matches_tiles(self) -> None:
        from gis.tiles import lonlat_to_meters

        x, y = transform_point(15.0, 55.0, "EPSG:4326", "EPSG:3857")
        ex, ey = lonlat_to_meters(15.0, 55.0)
        assert x == pytest.approx(ex, rel=1e-12)
        assert y == pytest.approx(ey, rel=1e-12)

    def test_roundtrip(self) -> None:
        x, y = transform_point(15.0, 55.0, "EPSG:4326", "EPSG:3857")
        lon, lat = transform_point(x, y, "EPSG:3857", "EPSG:4326")
        assert lon == pytest.approx(15.0, abs=1e-9)
        assert lat == pytest.approx(55.0, abs=1e-9)

    def test_identity(self) -> None:
        x, y = transform_point(15.0, 55.0, "EPSG:4326", "EPSG:4326")
        assert (x, y) == (15.0, 55.0)

    def test_batch_is_vectorised(self) -> None:
        lons = np.array([10.0, 15.0, 20.0])
        lats = np.array([50.0, 55.0, 60.0])
        xs, ys = transform_points(lons, lats, "EPSG:4326", "EPSG:3857")
        assert xs.shape == lons.shape
        for i in range(3):
            sx, sy = transform_point(float(lons[i]), float(lats[i]), "EPSG:4326", "EPSG:3857")
            assert xs[i] == pytest.approx(sx, rel=1e-12)
            assert ys[i] == pytest.approx(sy, rel=1e-12)


class TestBackendChain:
    """pyproj -> osr -> closed form, bound at CALL time."""

    def test_import_does_not_bind_a_backend(self) -> None:
        """★ Importing gis.crs must never import pyproj or osgeo (§11.3)."""
        import subprocess
        import sys

        code = (
            "import sys, importlib\n"
            "importlib.import_module('gis.crs')\n"
            "assert 'pyproj' not in sys.modules, 'pyproj imported at module scope'\n"
            "assert 'osgeo' not in sys.modules, 'osgeo imported at module scope'\n"
            "print('clean')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stderr
        assert "clean" in result.stdout

    def test_probe_reports_the_backend(self) -> None:
        text = probe()
        assert "crs backend:" in text
        assert backend_name() in text or "closed-form" in text

    def test_probe_never_raises_and_is_callable_with_no_backend(self) -> None:
        assert isinstance(probe(), str)
        assert backend_name() in ("pyproj", "osr", "closed_form")

    def test_a_full_crs_backend_is_bindable(self) -> None:
        """★ REWRITTEN from two §0.1 machine-snapshot pins (pyproj absent / osgeo
        present). Those described the 2026-07-17 authoring box; the supported install
        now pins pyproj via requirements.txt, and a plain venv legitimately hides the
        system osgeo. What MUST hold on any machine is the posture those pins served:
        a full backend binds, because without one UTM metrics — and therefore
        ``total_ce90_m``, mandatory on every GCP — are uncomputable."""
        assert backend_name() in ("pyproj", "osr"), (
            "no full CRS backend: install pyproj (requirements.txt) or GDAL bindings"
        )


@pytest.mark.skipif(not _HAVE_FULL_BACKEND, reason="needs pyproj or osr")
class TestUtmTransforms:
    """The osr leg — the one that actually runs on this machine."""

    def test_always_xy_ordering(self) -> None:
        """★ THE CLASSIC TRAP. If axis order were authority-defined, this lands in the sea.

        EPSG:4326's authority order is (lat, lon). A transformer without always_xy reads
        our lon as a latitude and returns plausible numbers for the wrong place on Earth.
        Zone 33N's central meridian is 15E, so lon=15 MUST map to easting 500000.
        """
        x, y = transform_point(15.0, 55.0, "EPSG:4326", "EPSG:32633")
        assert x == pytest.approx(500000.0, abs=1.0), "lon/lat were swapped"
        assert 6.0e6 < y < 6.2e6, "northing is implausible for 55N"

    def test_central_meridian_is_500000(self) -> None:
        """A UTM zone's false easting is 500000 at its central meridian, by definition."""
        for lon0, epsg in ((-3.0, "EPSG:32630"), (9.0, "EPSG:32632"), (15.0, "EPSG:32633")):
            x, _ = transform_point(lon0, 50.0, "EPSG:4326", epsg)
            assert x == pytest.approx(500000.0, abs=0.5), epsg

    def test_utm_roundtrip(self) -> None:
        for lon, lat in ((15.0, 55.0), (-0.1278, 51.5074), (151.2, -33.9)):
            epsg = utm_epsg_for(lon, lat)
            x, y = transform_point(lon, lat, "EPSG:4326", epsg)
            lon2, lat2 = transform_point(x, y, epsg, "EPSG:4326")
            assert lon2 == pytest.approx(lon, abs=1e-9)
            assert lat2 == pytest.approx(lat, abs=1e-9)

    def test_utm_metres_are_true_metres(self) -> None:
        """★ THE WHOLE POINT of routing metrics through UTM.

        One degree of latitude is ~111.2 km on the ground. In UTM that is what you
        measure. In EPSG:3857 at 55N you would measure ~74% more.
        """
        epsg = "EPSG:32633"
        _, y0 = transform_point(15.0, 55.0, "EPSG:4326", epsg)
        _, y1 = transform_point(15.0, 56.0, "EPSG:4326", epsg)
        assert abs(y1 - y0) == pytest.approx(111_000.0, rel=0.01)

    def test_3857_metres_are_not(self) -> None:
        """The contrast that justifies the rule, measured rather than asserted."""
        from gis.tiles import lonlat_to_meters

        _, y0 = lonlat_to_meters(15.0, 55.0)
        _, y1 = lonlat_to_meters(15.0, 56.0)
        inflated = abs(y1 - y0)
        assert inflated > 150_000.0, "3857 northing should be inflated by ~1/cos(55)"

    def test_transformer_is_cached(self) -> None:
        a = get_transformer("EPSG:4326", "EPSG:32633")
        b = get_transformer("EPSG:4326", "EPSG:32633")
        assert a is b


class TestPixelRoundTripOnUtm:
    """§13.3's ``test_crs::test_pixel_roundtrip`` — on a UTM raster, < 1e-6 px."""

    # A 64x64 EPSG:32633 ortho at 0.1 m GSD — the shape of gis/tests/fixtures/synthetic_ortho.tif.
    GT = (500000.0, 0.1, 0.0, 6094791.0, 0.0, -0.1)

    @pytest.mark.skipif(not _HAVE_FULL_BACKEND, reason="needs pyproj or osr for UTM")
    @pytest.mark.parametrize(
        ("col", "row"), [(0.0, 0.0), (0.5, 0.5), (31.5, 31.5), (63.0, 63.0), (-0.5, -0.5)]
    )
    def test_pixel_roundtrip(self, col: float, row: float) -> None:
        """★ This is the round trip the closed-form fallback CANNOT do — it needs osr."""
        lon, lat = pixel_to_lonlat(self.GT, "EPSG:32633", col, row)
        col2, row2 = lonlat_to_pixel(self.GT, "EPSG:32633", lon, lat)
        assert col2 == pytest.approx(col, abs=1e-6)
        assert row2 == pytest.approx(row, abs=1e-6)

    def test_tiles_refuses_a_projected_crs_rather_than_guessing(self) -> None:
        """★ gis.tiles may not bind a CRS backend (§10.4 gis-tiles-pure), so it REFUSES.

        The two modules split the job: `tiles` owns the closed form and the +0.5; `crs`
        owns the backend. Both apply the half-pixel through the SAME
        `tiles.apply_geotransform`, so they cannot drift apart.
        """
        from gis.tiles import pixel_to_lonlat as tiles_pixel_to_lonlat

        with pytest.raises(CrsError, match="closed form"):
            tiles_pixel_to_lonlat(self.GT, "EPSG:32633", 0.0, 0.0)

    def test_both_modules_agree_on_the_closed_form_pair(self) -> None:
        """★ The half-pixel is applied at ONE site, so the two paths must agree exactly."""
        from gis.tiles import pixel_to_lonlat as tiles_pixel_to_lonlat

        gt = (1234567.0, 0.6, 0.0, 7361866.0, 0.0, -0.6)
        for col, row in ((0.0, 0.0), (13.25, 91.75)):
            a = tiles_pixel_to_lonlat(gt, "EPSG:3857", col, row)
            b = pixel_to_lonlat(gt, "EPSG:3857", col, row)
            assert a[0] == pytest.approx(b[0], abs=1e-12)
            assert a[1] == pytest.approx(b[1], abs=1e-12)

    @pytest.mark.skipif(not _HAVE_FULL_BACKEND, reason="needs pyproj or osr for UTM")
    def test_geotransform_places_pixels_where_utm_says(self) -> None:
        """A UTM geotransform must land where the CRS says, not where 3857 would."""
        lon, lat = pixel_to_lonlat(self.GT, "EPSG:32633", 0.0, 0.0)
        # 500000 E in zone 33N is the central meridian: 15E.
        assert lon == pytest.approx(15.0, abs=1e-4)
        assert 54.9 < lat < 55.1
