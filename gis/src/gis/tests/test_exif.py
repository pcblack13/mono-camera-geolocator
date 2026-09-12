"""Tests for ``gis.exif`` (§13.1 IU-09).

Fixtures are built IN MEMORY with PIL — no committed binaries, no network. Every case that
matters here is a *malformed* or *absent* tag, and those are far easier to construct than
to find.

★ The governing rule: **EXIF GPS is a hint, not a truth**, and this module must never
raise because a photograph is odd. A photo with no GPS is the normal case.
"""

from __future__ import annotations

import io
import math
from fractions import Fraction

import pytest
from PIL import Image

from gis.exif import (
    DEFAULT_EXIF_MIN_RADIUS_M,
    DEFAULT_EXIF_RADIUS_INFLATION,
    ExifGps,
    extract_exif_gps,
    inflate_radius_m,
    read_exif_orientation,
)
from gis.types import LonLat


def _dms(value: float) -> tuple[Fraction, Fraction, Fraction]:
    """Encode a decimal degree as an EXIF (deg, min, sec) rational triple."""
    v = abs(value)
    d = int(v)
    m_float = (v - d) * 60.0
    m = int(m_float)
    s = (m_float - m) * 60.0
    return (Fraction(d, 1), Fraction(m, 1), Fraction(s).limit_denominator(10000))


def _image_with_gps(**gps_tags: object) -> io.BytesIO:
    """Build a tiny JPEG carrying the given GPS IFD tags."""
    img = Image.new("RGB", (8, 8), (120, 140, 90))
    exif = img.getexif()
    ifd = exif.get_ifd(0x8825)
    # GPS tag numbers, per the EXIF spec.
    numbers = {
        "GPSLatitudeRef": 1,
        "GPSLatitude": 2,
        "GPSLongitudeRef": 3,
        "GPSLongitude": 4,
        "GPSAltitudeRef": 5,
        "GPSAltitude": 6,
        "GPSTimeStamp": 7,
        "GPSDOP": 11,
        "GPSDateStamp": 29,
        "GPSDifferential": 30,
        "GPSHPositioningError": 31,
    }
    for name, value in gps_tags.items():
        ifd[numbers[name]] = value
    exif[0x8825] = ifd
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    buf.seek(0)
    return buf


def _image_at(lon: float, lat: float, **extra: object) -> io.BytesIO:
    """A JPEG whose EXIF claims it was taken at (lon, lat)."""
    return _image_with_gps(
        GPSLatitude=_dms(lat),
        GPSLatitudeRef="N" if lat >= 0 else "S",
        GPSLongitude=_dms(lon),
        GPSLongitudeRef="E" if lon >= 0 else "W",
        **extra,
    )


class TestExtraction:
    def test_reads_a_northeast_position(self) -> None:
        got = extract_exif_gps(_image_at(15.5, 55.25))
        assert got is not None
        assert got.position.lon == pytest.approx(15.5, abs=1e-4)
        assert got.position.lat == pytest.approx(55.25, abs=1e-4)

    def test_reads_a_southwest_position(self) -> None:
        """★ The hemisphere refs are a SIGN, and dropping them puts you on another continent."""
        got = extract_exif_gps(_image_at(-43.1729, -22.9068))
        assert got is not None
        assert got.position.lon == pytest.approx(-43.1729, abs=1e-3)
        assert got.position.lat == pytest.approx(-22.9068, abs=1e-3)
        assert got.position.lon < 0
        assert got.position.lat < 0

    def test_returns_a_lonlat_lon_first(self) -> None:
        """★ lon FIRST, everywhere in this codebase, in every CRS."""
        got = extract_exif_gps(_image_at(15.0, 55.0))
        assert got is not None
        assert isinstance(got.position, LonLat)
        assert got.position.lon == pytest.approx(15.0, abs=1e-4)

    def test_no_exif_at_all_returns_none(self) -> None:
        """A photo with no GPS is the NORMAL case — the product has a map-click path for it."""
        img = Image.new("RGB", (8, 8))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        buf.seek(0)
        assert extract_exif_gps(buf) is None

    def test_gps_ifd_without_a_position_returns_none(self) -> None:
        assert extract_exif_gps(_image_with_gps(GPSDOP=Fraction(1, 1))) is None

    def test_latitude_without_longitude_returns_none(self) -> None:
        buf = _image_with_gps(GPSLatitude=_dms(55.0), GPSLatitudeRef="N")
        assert extract_exif_gps(buf) is None

    def test_null_island_is_treated_as_an_unset_tag(self) -> None:
        """★ (0, 0) is in the Gulf of Guinea. It is overwhelmingly a zeroed tag, not a site.

        Accepting it sends the search 5000 km into the ocean and reports 'no match',
        which is indistinguishable from an honest 'no match'.
        """
        assert extract_exif_gps(_image_at(0.0, 0.0)) is None

    def test_out_of_range_coordinates_are_rejected(self) -> None:
        buf = _image_with_gps(
            GPSLatitude=(Fraction(200), Fraction(0), Fraction(0)),
            GPSLatitudeRef="N",
            GPSLongitude=_dms(15.0),
            GPSLongitudeRef="E",
        )
        assert extract_exif_gps(buf) is None

    def test_malformed_dms_returns_none_not_a_crash(self) -> None:
        buf = _image_with_gps(
            GPSLatitude=(Fraction(55), Fraction(0)),  # 2 elements, not 3
            GPSLatitudeRef="N",
            GPSLongitude=_dms(15.0),
            GPSLongitudeRef="E",
        )
        assert extract_exif_gps(buf) is None

    def test_a_corrupt_file_returns_none_not_a_crash(self) -> None:
        """★ A corrupt upload is a fact about the upload, not an error in us."""
        assert extract_exif_gps(io.BytesIO(b"not an image at all")) is None

    def test_a_missing_path_returns_none_not_a_crash(self) -> None:
        assert extract_exif_gps("/nonexistent/definitely/not/here.jpg") is None


class TestAltitude:
    def test_above_sea_level(self) -> None:
        got = extract_exif_gps(
            _image_at(15.0, 55.0, GPSAltitude=Fraction(1234, 10), GPSAltitudeRef=0)
        )
        assert got is not None
        assert got.altitude_m == pytest.approx(123.4)
        assert got.altitude_ref == "sea_level"

    def test_below_sea_level_sign_is_applied(self) -> None:
        """★ EXIF stores 'below sea level' as a SEPARATE FLAG. Forgetting it inverts the sign.

        The Dead Sea, the Imperial Valley and the Netherlands are all real agricultural
        places below sea level.
        """
        got = extract_exif_gps(
            _image_at(15.0, 55.0, GPSAltitude=Fraction(50, 1), GPSAltitudeRef=1)
        )
        assert got is not None
        assert got.altitude_m == pytest.approx(-50.0)
        assert got.altitude_ref == "below_sea_level"

    def test_absent_altitude(self) -> None:
        got = extract_exif_gps(_image_at(15.0, 55.0))
        assert got is not None
        assert got.altitude_m is None
        assert got.altitude_ref is None


class TestErrorEstimate:
    def test_explicit_horizontal_error_wins(self) -> None:
        got = extract_exif_gps(
            _image_at(15.0, 55.0, GPSHPositioningError=8.0, GPSDOP=Fraction(1, 1))
        )
        assert got is not None
        assert got.horizontal_error_m == pytest.approx(8.0)
        assert got.estimated_error_m() == pytest.approx(8.0)

    def test_hdop_is_a_factor_not_a_distance(self) -> None:
        """★ HDOP is DIMENSIONLESS. horizontal error ~= HDOP * UERE.

        Treating HDOP as metres makes a mediocre fix (HDOP 2) look like a 2 m one.
        """
        got = ExifGps(position=LonLat(15.0, 55.0), hdop=2.0)
        assert got.estimated_error_m() == pytest.approx(10.0)  # 2 * 5 m UERE
        assert got.estimated_error_m() != 2.0

    def test_no_dop_falls_back_to_an_honest_default(self) -> None:
        got = ExifGps(position=LonLat(15.0, 55.0))
        assert got.estimated_error_m() == pytest.approx(10.0)

    def test_differential_fixes_are_better(self) -> None:
        plain = ExifGps(position=LonLat(15.0, 55.0), horizontal_error_m=5.0)
        dgps = ExifGps(position=LonLat(15.0, 55.0), horizontal_error_m=5.0, is_differential=True)
        assert dgps.estimated_error_m() < plain.estimated_error_m()

    def test_differential_flag_is_read(self) -> None:
        got = extract_exif_gps(_image_at(15.0, 55.0, GPSDifferential=1))
        assert got is not None
        assert got.is_differential is True


class TestRadiusInflation:
    """★ An EXIF hint taken literally excludes the correct answer — the worst failure here."""

    def test_defaults(self) -> None:
        assert DEFAULT_EXIF_RADIUS_INFLATION == 3.0
        assert DEFAULT_EXIF_MIN_RADIUS_M == 250.0

    def test_the_floor_dominates_a_confident_fix(self) -> None:
        """★ A 5 m claimed error still gets a 250 m search radius.

        This is the case that matters: a photo exported through desktop software may carry
        the PROCESSING location with a small, confident, completely wrong error estimate.
        """
        assert inflate_radius_m(5.0) == 250.0

    def test_the_multiplier_dominates_a_poor_fix(self) -> None:
        assert inflate_radius_m(200.0) == 600.0

    def test_the_crossover(self) -> None:
        assert inflate_radius_m(250.0 / 3.0) == pytest.approx(250.0)
        assert inflate_radius_m(100.0) == 300.0

    def test_is_monotonic(self) -> None:
        prev = 0.0
        for e in (0.0, 10.0, 100.0, 500.0, 1000.0):
            r = inflate_radius_m(e)
            assert r >= prev
            prev = r

    def test_never_shrinks_below_the_claim(self) -> None:
        """Inflation must never return a radius SMALLER than the claimed error."""
        for e in (1.0, 50.0, 300.0, 5000.0):
            assert inflate_radius_m(e) >= e

    def test_custom_parameters(self) -> None:
        assert inflate_radius_m(100.0, inflation=2.0, minimum_m=0.0) == 200.0
        assert inflate_radius_m(1.0, inflation=1.0, minimum_m=0.0) == 1.0

    def test_rejects_bad_input(self) -> None:
        with pytest.raises(ValueError, match="claimed_error_m"):
            inflate_radius_m(-1.0)
        with pytest.raises(ValueError, match="inflation"):
            inflate_radius_m(10.0, inflation=0.5)
        with pytest.raises(ValueError, match="minimum_m"):
            inflate_radius_m(10.0, minimum_m=-1.0)

    def test_rejects_nan(self) -> None:
        with pytest.raises(ValueError):
            inflate_radius_m(float("nan"))


class TestOrientation:
    def test_absent_orientation_is_normal(self) -> None:
        img = Image.new("RGB", (8, 8))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        buf.seek(0)
        assert read_exif_orientation(buf) == 1

    def test_orientation_6_is_read(self) -> None:
        """★ Orientation is GEOMETRY, not a display preference.

        A value of 6 means the stored raster is rotated 90 deg CW from how it should be
        shown, so pixel_x/pixel_y and the stored width/height are meaningless unless
        ingest normalises it first.
        """
        img = Image.new("RGB", (8, 4))
        exif = img.getexif()
        exif[0x0112] = 6
        buf = io.BytesIO()
        img.save(buf, format="JPEG", exif=exif)
        buf.seek(0)
        assert read_exif_orientation(buf) == 6

    def test_out_of_range_orientation_is_normalised_to_1(self) -> None:
        img = Image.new("RGB", (8, 8))
        exif = img.getexif()
        exif[0x0112] = 99
        buf = io.BytesIO()
        img.save(buf, format="JPEG", exif=exif)
        buf.seek(0)
        assert read_exif_orientation(buf) == 1

    def test_corrupt_file_is_normal_not_a_crash(self) -> None:
        assert read_exif_orientation(io.BytesIO(b"garbage")) == 1


class TestSampleInvariants:
    def test_estimated_error_is_always_positive_and_finite(self) -> None:
        for hdop in (None, 0.5, 1.0, 20.0):
            for err in (None, 1.0, 100.0):
                sample = ExifGps(position=LonLat(0.0, 0.0), hdop=hdop, horizontal_error_m=err)
                value = sample.estimated_error_m()
                assert math.isfinite(value)
                assert value > 0.0

    def test_zero_hdop_does_not_produce_a_zero_error(self) -> None:
        """★ A claimed HDOP of 0 is impossible. It must not become a 0 m error bar."""
        sample = ExifGps(position=LonLat(0.0, 0.0), hdop=0.0)
        assert sample.estimated_error_m() > 0.0
