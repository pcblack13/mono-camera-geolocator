"""EXIF GPS extraction, DOP parsing, and honest radius inflation.

★ **EXIF GPS is a hint, not a truth.** Phone GPS is 3-10 m at best and tens of metres
under canopy or beside a barn; the tag may be the *processing* location if the photo was
exported through desktop software; and ``GPSHDOP``/``GPSDifferential`` are frequently
absent altogether.

An EXIF hint taken literally produces a search box that confidently EXCLUDES the correct
answer — the worst failure mode available here, because the result is a plausible wrong
match from a neighbouring field rather than an honest "no match". So the radius is
inflated (default 3x) and floored (default 250 m), and the reasoning is recorded on the
returned value rather than buried in a caller.

This module reads EXIF and nothing else. It never decides where to search; it reports
what the file claims and how much to distrust it.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any, Final

from gis.types import LonLat

__all__ = [
    "DEFAULT_EXIF_MIN_RADIUS_M",
    "DEFAULT_EXIF_RADIUS_INFLATION",
    "ExifGps",
    "extract_exif_gps",
    "inflate_radius_m",
    "read_exif_orientation",
]

_log = logging.getLogger("gis.exif")

DEFAULT_EXIF_RADIUS_INFLATION: Final[float] = 3.0
"""Multiplier applied to a claimed horizontal error. ``LE_EXIF_RADIUS_INFLATION``."""

DEFAULT_EXIF_MIN_RADIUS_M: Final[float] = 250.0
"""Floor for an inflated radius, metres. ``LE_EXIF_MIN_RADIUS_M``."""

_NOMINAL_HDOP_ERROR_M: Final[float] = 5.0
"""Assumed 1-sigma user-equivalent range error, metres, for turning HDOP into metres.

HDOP is a DILUTION factor, not a distance: horizontal error ~= HDOP * UERE. Consumer GNSS
UERE is ~5 m under open sky. This constant is the honest name of an assumption that would
otherwise hide inside an expression.
"""

_NOMINAL_NO_DOP_ERROR_M: Final[float] = 10.0
"""Assumed horizontal error when the file offers no DOP at all, metres."""


@dataclass(frozen=True, slots=True)
class ExifGps:
    """What a photograph's EXIF claims about where it was taken.

    Attributes:
        position: The claimed position, EPSG:4326.
        altitude_m: Claimed altitude in metres above the reference in ``altitude_ref``, or
            None. ★ Sign already applied: EXIF stores "below sea level" as a separate flag,
            which is exactly the kind of thing a caller forgets.
        altitude_ref: ``"sea_level"``, ``"below_sea_level"``, or None.
        hdop: Horizontal dilution of precision, or None. Dimensionless, NOT metres.
        horizontal_error_m: The camera's own claimed horizontal error in metres
            (``GPSHPositioningError``), or None. Preferred over ``hdop`` when present
            because it is already a distance.
        timestamp: The GPS timestamp in UTC, or None. ★ From ``GPSDateStamp`` +
            ``GPSTimeStamp``, which are UTC by specification — unlike ``DateTimeOriginal``,
            which is local time with no zone recorded and is therefore not used here.
        is_differential: True iff the fix was differentially corrected.
        raw: The raw GPS IFD, for debugging and provenance.
    """

    position: LonLat
    altitude_m: float | None = None
    altitude_ref: str | None = None
    hdop: float | None = None
    horizontal_error_m: float | None = None
    timestamp: datetime | None = None
    is_differential: bool = False
    raw: dict[str, Any] | None = None

    def estimated_error_m(self) -> float:
        """Return the best available estimate of this fix's horizontal error, in metres.

        Precedence, most trustworthy first:

        1. ``horizontal_error_m`` — the camera's own claim, already a distance.
        2. ``hdop * 5 m`` — HDOP is a dilution factor and must be multiplied by a
           user-equivalent range error to become a distance. Treating HDOP as metres is a
           units error that makes a good fix look like a 1 m one.
        3. 10 m — the honest "we were told nothing" default.

        A differential fix scales the result by 0.4: DGPS/SBAS typically lands in the
        1-3 m range where autonomous GNSS is 5-10 m.
        """
        if self.horizontal_error_m is not None and self.horizontal_error_m > 0.0:
            base = self.horizontal_error_m
        elif self.hdop is not None and self.hdop > 0.0:
            base = self.hdop * _NOMINAL_HDOP_ERROR_M
        else:
            base = _NOMINAL_NO_DOP_ERROR_M
        return base * 0.4 if self.is_differential else base


def inflate_radius_m(
    claimed_error_m: float,
    *,
    inflation: float = DEFAULT_EXIF_RADIUS_INFLATION,
    minimum_m: float = DEFAULT_EXIF_MIN_RADIUS_M,
) -> float:
    """Inflate a claimed positional error into a search radius we can actually trust.

    ``radius = max(claimed_error_m * inflation, minimum_m)``

    ★ Both terms matter and neither is padding. The multiplier covers the fact that a
    receiver's own error estimate is optimistic under canopy, beside structures and in the
    multipath-rich environments this product is used in. The floor covers the far worse
    case: a photo exported through desktop software carrying the *processing* location, or
    a stale almanac fix, where the claimed error is small and simply wrong. A search box
    that confidently excludes the right answer returns a plausible match from the
    neighbouring field, and the surveyor believes it.

    Args:
        claimed_error_m: The fix's own claimed horizontal error, metres, ``>= 0``.
        inflation: Multiplier, ``>= 1``.
        minimum_m: Floor for the result, metres, ``>= 0``.

    Returns:
        The search radius in metres.

    Raises:
        ValueError: If any argument is out of range or not finite.
    """
    if not math.isfinite(claimed_error_m) or claimed_error_m < 0.0:
        raise ValueError(f"claimed_error_m must be finite and >= 0, got {claimed_error_m}")
    if not math.isfinite(inflation) or inflation < 1.0:
        raise ValueError(f"inflation must be finite and >= 1, got {inflation}")
    if not math.isfinite(minimum_m) or minimum_m < 0.0:
        raise ValueError(f"minimum_m must be finite and >= 0, got {minimum_m}")
    return max(claimed_error_m * inflation, minimum_m)


def _to_float(value: Any) -> float | None:
    """Coerce an EXIF rational/int/float to float, or None if it is unusable."""
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return out if math.isfinite(out) else None


def _dms_to_degrees(dms: Any, ref: Any) -> float | None:
    """Convert an EXIF ``(degrees, minutes, seconds)`` rational triple plus a hemisphere ref.

    Returns None rather than raising: a malformed GPS IFD is a fact about the file, not an
    error in us, and the caller's contract is "no hint" rather than "crash".
    """
    if dms is None:
        return None
    try:
        parts = list(dms)
    except TypeError:
        return None
    if len(parts) != 3:
        return None
    values = [_to_float(p) for p in parts]
    if any(v is None for v in values):
        return None
    degrees, minutes, seconds = values  # type: ignore[misc]
    assert degrees is not None and minutes is not None and seconds is not None
    result = abs(degrees) + minutes / 60.0 + seconds / 3600.0
    ref_s = str(ref).strip().upper() if ref is not None else ""
    if ref_s in ("S", "W"):
        result = -result
    return result


def _gps_timestamp(gps: dict[str, Any]) -> datetime | None:
    """Build a UTC datetime from ``GPSDateStamp`` + ``GPSTimeStamp``, or None."""
    date_s = gps.get("GPSDateStamp")
    time_v = gps.get("GPSTimeStamp")
    if not date_s or time_v is None:
        return None
    try:
        parts = [_to_float(p) for p in list(time_v)]
        if len(parts) != 3 or any(p is None for p in parts):
            return None
        hour, minute, second = (int(p) for p in parts)  # type: ignore[arg-type]
        y, m, d = (int(x) for x in str(date_s).strip().replace("-", ":").split(":")[:3])
        return datetime(y, m, d, hour, minute, min(second, 59), tzinfo=UTC)
    except (ValueError, TypeError, IndexError):
        _log.debug("unparseable GPS timestamp: date=%r time=%r", date_s, time_v)
        return None


def _read_gps_ifd(source: str | Path | IO[bytes]) -> dict[str, Any] | None:
    """Return the GPS IFD as a tag-name-keyed dict, or None if absent/unreadable."""
    # ★ PIL bound at call time. `gis` must import with its optional deps absent, and a
    #   module-scope import here would take the whole package down at collection.
    try:
        from PIL import ExifTags, Image
    except ImportError:  # pragma: no cover - PIL is a base dep, but never crash on it
        _log.warning("Pillow is not installed; EXIF GPS extraction is unavailable")
        return None

    try:
        with Image.open(source) as img:
            exif = img.getexif()
            if not exif:
                return None
            gps_ifd = exif.get_ifd(ExifTags.IFD.GPSInfo)
            if not gps_ifd:
                return None
            return {ExifTags.GPSTAGS.get(tag, str(tag)): value for tag, value in gps_ifd.items()}
    except (OSError, ValueError, KeyError, AttributeError, TypeError) as exc:
        # A corrupt or exotic EXIF block is a fact about the upload, not our failure.
        _log.info("could not read EXIF GPS from %r: %s", source, exc)
        return None


def extract_exif_gps(source: str | Path | IO[bytes]) -> ExifGps | None:
    """Extract the GPS fix a photograph claims, if it has one.

    ★ NEVER RAISES for a missing, malformed or exotic EXIF block. A photo without GPS is
    the normal case (the product has a whole map-click hint path for it), and a corrupt
    IFD is a fact about the upload rather than an error in us. Both return None.

    Args:
        source: A path or an open binary file object holding an image.

    Returns:
        The ``ExifGps``, or None when the file carries no usable position.
    """
    gps = _read_gps_ifd(source)
    if not gps:
        return None

    lat = _dms_to_degrees(gps.get("GPSLatitude"), gps.get("GPSLatitudeRef"))
    lon = _dms_to_degrees(gps.get("GPSLongitude"), gps.get("GPSLongitudeRef"))
    if lat is None or lon is None:
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        _log.info("EXIF GPS out of range (lon=%r, lat=%r); ignoring", lon, lat)
        return None
    # (0, 0) in the Gulf of Guinea is overwhelmingly a zeroed tag, not a survey site.
    if lat == 0.0 and lon == 0.0:
        _log.info("EXIF GPS is exactly (0, 0); treating as an unset tag rather than Null Island")
        return None

    altitude = _to_float(gps.get("GPSAltitude"))
    alt_ref_raw = gps.get("GPSAltitudeRef")
    altitude_ref: str | None = None
    if altitude is not None:
        ref_val = alt_ref_raw
        if isinstance(ref_val, bytes):
            ref_val = ref_val[0] if ref_val else 0
        below = _to_float(ref_val) == 1.0
        altitude_ref = "below_sea_level" if below else "sea_level"
        if below:
            altitude = -altitude

    differential = _to_float(gps.get("GPSDifferential")) == 1.0

    return ExifGps(
        position=LonLat(lon=lon, lat=lat),
        altitude_m=altitude,
        altitude_ref=altitude_ref,
        hdop=_to_float(gps.get("GPSDOP")),
        horizontal_error_m=_to_float(gps.get("GPSHPositioningError")),
        timestamp=_gps_timestamp(gps),
        is_differential=differential,
        raw={k: repr(v) for k, v in gps.items()},
    )


def read_exif_orientation(source: str | Path | IO[bytes]) -> int:
    """Return the EXIF ``Orientation`` tag, or 1 when absent or unreadable.

    ★ Orientation is a GEOMETRIC fact, not a display preference. A value of 6 means the
    stored raster is rotated 90 degrees clockwise from how it should be shown — so an
    annotation's ``pixel_x``/``pixel_y`` and the image's stored ``width``/``height`` are
    meaningless unless ingest normalises it first. Never raises.

    Args:
        source: A path or an open binary file object holding an image.

    Returns:
        The orientation in ``[1, 8]``; 1 (normal) when absent, unreadable or out of range.
    """
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - PIL is a base dep
        return 1
    try:
        with Image.open(source) as img:
            exif = img.getexif()
            if not exif:
                return 1
            value = exif.get(0x0112)  # Orientation
            orientation = int(value) if value is not None else 1
            return orientation if 1 <= orientation <= 8 else 1
    except (OSError, ValueError, TypeError, AttributeError):
        return 1
