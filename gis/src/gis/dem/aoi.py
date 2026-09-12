"""AOI corners and extents — stage 1's geometry, with no shapely and no raster IO.

The algorithm folder states the AOI as four DMS corners and a fractional tolerance. This
module turns that into a bounding box in whatever CRS the raster happens to be in.

★ The AOI is a BOX, not a polygon. The original built a shapely ``Polygon`` and then read
``.bounds`` off it — the min/max of four corners is that same box, so the polygon (and the
dependency) buys nothing. The one thing it did buy, ``buffer(0)`` self-intersection repair,
is irrelevant to a bounding box: a bow-tie quadrilateral and its untwisted twin have
identical bounds.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Final, Sequence

from gis.errors import GisError

__all__ = [
    "MAX_TOLERANCE",
    "AoiCorner",
    "AoiExtent",
    "corners_to_lonlat",
    "dms_to_decimal",
    "parse_dms_string",
]


MAX_TOLERANCE: Final[float] = 5.0
"""Largest accepted padding fraction (500%). A tolerance is a margin, not a search area.

Bounded because the padded box drives the read window: ``tolerance=1e6`` on a 1-degree
tile asks for a window the size of the world, which the clamp then silently reduces to the
whole raster — i.e. "crop" quietly becomes "copy". Refusing is the honest answer.
"""

#: ``34°07'39.16"N`` / ``34 7 39.16 N`` / ``34; 7; 39.16; N`` / ``34.1275`` / ``-34.1275``.
#: Degrees may be signed; a trailing hemisphere letter wins over the sign when both appear.
_DMS_RE: Final[re.Pattern[str]] = re.compile(
    r"""^\s*
    (?P<deg>[+-]?\d+(?:\.\d+)?)      \s*(?:[°d:;]|\s)\s*
    (?:(?P<min>\d+(?:\.\d+)?)        \s*(?:['m:;]|\s)\s*)?
    (?:(?P<sec>\d+(?:\.\d+)?)        \s*(?:["s:;]|\s)?\s*)?
    (?P<hem>[NSEWnsew])?
    \s*$""",
    re.VERBOSE,
)


@dataclass(frozen=True, slots=True)
class AoiCorner:
    """One AOI corner in decimal degrees, EPSG:4326.

    Attributes:
        lon: Longitude, degrees. ★ First, as everywhere in this package.
        lat: Latitude, degrees.
    """

    lon: float
    lat: float

    def __post_init__(self) -> None:
        if not (math.isfinite(self.lon) and math.isfinite(self.lat)):
            raise GisError(f"non-finite AOI corner: lon={self.lon}, lat={self.lat}")
        if not (-180.0 <= self.lon <= 180.0):
            raise GisError(f"AOI corner longitude {self.lon} outside [-180, 180]")
        if not (-90.0 <= self.lat <= 90.0):
            raise GisError(f"AOI corner latitude {self.lat} outside [-90, 90]")


@dataclass(frozen=True, slots=True)
class AoiExtent:
    """An axis-aligned extent in some CRS's own units.

    Attributes:
        left: Minimum x / west.
        bottom: Minimum y / south.
        right: Maximum x / east.
        top: Maximum y / north.
    """

    left: float
    bottom: float
    right: float
    top: float

    def padded(self, fraction: float) -> AoiExtent:
        """Return this extent grown by ``fraction`` of its own span on every side.

        ★ Padding is relative to the SPAN, so a tall thin AOI gets a tall thin margin.
        A degenerate axis (all four corners on one meridian) has zero span and therefore
        gains zero padding — which would make the crop window empty, so callers must
        reject a degenerate AOI rather than rely on the padding to rescue it.

        Args:
            fraction: Padding as a fraction of the extent's width/height. ``0.10`` is 10%.

        Returns:
            The padded extent.

        Raises:
            GisError: If ``fraction`` is negative, non-finite, or above
                :data:`MAX_TOLERANCE`.
        """
        if not math.isfinite(fraction) or fraction < 0.0:
            raise GisError(f"tolerance must be finite and >= 0, got {fraction}")
        if fraction > MAX_TOLERANCE:
            raise GisError(
                f"tolerance {fraction} exceeds the {MAX_TOLERANCE} cap; a tolerance is a "
                "margin around the AOI, not a search radius"
            )
        dx = (self.right - self.left) * fraction
        dy = (self.top - self.bottom) * fraction
        return AoiExtent(
            left=self.left - dx,
            bottom=self.bottom - dy,
            right=self.right + dx,
            top=self.top + dy,
        )

    def as_tuple(self) -> tuple[float, float, float, float]:
        """Return ``(left, bottom, right, top)`` — rasterio's bounds order."""
        return (self.left, self.bottom, self.right, self.top)

    @property
    def is_degenerate(self) -> bool:
        """True when the extent has no area on at least one axis."""
        return self.right <= self.left or self.top <= self.bottom


def dms_to_decimal(
    degrees: float, minutes: float = 0.0, seconds: float = 0.0, hemisphere: str = ""
) -> float:
    """Convert degrees/minutes/seconds to signed decimal degrees.

    Args:
        degrees: Whole degrees. May carry the sign when no hemisphere is given.
        minutes: Arc-minutes, ``0..60``.
        seconds: Arc-seconds, ``0..60``.
        hemisphere: ``N``/``S``/``E``/``W``, or empty. ★ When present it WINS over the
            sign of ``degrees``: ``-34`` with ``"N"`` is +34, because a hemisphere letter
            is an explicit statement and a stray minus is usually a transcription slip.

    Returns:
        Signed decimal degrees.

    Raises:
        GisError: On non-finite input or out-of-range minutes/seconds.
    """
    if not all(math.isfinite(v) for v in (degrees, minutes, seconds)):
        raise GisError(f"non-finite DMS value: {degrees}, {minutes}, {seconds}")
    if not (0.0 <= minutes < 60.0):
        raise GisError(f"minutes must be in [0, 60), got {minutes}")
    if not (0.0 <= seconds < 60.0):
        raise GisError(f"seconds must be in [0, 60), got {seconds}")

    decimal = abs(degrees) + minutes / 60.0 + seconds / 3600.0
    hem = hemisphere.strip().upper()
    if hem in ("S", "W"):
        return -decimal
    if hem in ("N", "E"):
        return decimal
    return -decimal if degrees < 0 else decimal


def parse_dms_string(value: object) -> float:
    """Parse a coordinate in any of the shapes the algorithm's inputs use.

    Accepts, in order of how often they actually appear:

    * a number, or a numeric string — already decimal degrees;
    * ``34°07'39.16"N`` — the form in ``documantation.txt`` and ``aoi_corners.csv``;
    * ``34; 7; 39.16`` and ``34; 7; 39.16; N`` — the Excel form the converter reads;
    * ``34 7 39.16 N`` — whitespace-separated.

    Args:
        value: The raw cell/field value.

    Returns:
        Signed decimal degrees.

    Raises:
        GisError: If the value is empty or cannot be read as a coordinate.
    """
    if value is None:
        raise GisError("empty coordinate")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)

    text = str(value).strip()
    if not text:
        raise GisError("empty coordinate")

    # A bare decimal, with or without a hemisphere suffix.
    try:
        return float(text)
    except ValueError:
        pass

    match = _DMS_RE.match(text.replace("''", '"'))
    if match is None:
        raise GisError(
            f"could not read {text!r} as a coordinate; expected decimal degrees or "
            "DMS such as 34°07'39.16\"N or 34; 7; 39.16; N"
        )
    return dms_to_decimal(
        float(match.group("deg")),
        float(match.group("min") or 0.0),
        float(match.group("sec") or 0.0),
        match.group("hem") or "",
    )


def corners_to_lonlat(corners: Sequence[object]) -> list[AoiCorner]:
    """Normalise assorted corner spellings into :class:`AoiCorner` values.

    Accepts each corner as a mapping with ``lon``/``lat`` (or ``longitude``/``latitude``)
    keys, or as a 2-sequence. Values may be decimal or any DMS form
    :func:`parse_dms_string` reads.

    ★ Order is preserved but irrelevant: the AOI is reduced to a bounding box, so a
    ring wound the "wrong" way, or corners listed NW-SE-NE-SW, yields the same extent.

    Args:
        corners: At least three corners. Three is enough to bound an area; four is what
            the field workflow produces.

    Returns:
        The corners as ``AoiCorner`` values.

    Raises:
        GisError: On fewer than three corners or an unreadable corner.
    """
    if len(corners) < 3:
        raise GisError(
            f"an AOI needs at least 3 corners to bound an area, got {len(corners)}"
        )

    out: list[AoiCorner] = []
    for i, raw in enumerate(corners, start=1):
        try:
            if isinstance(raw, dict):
                lon_raw = raw.get("lon", raw.get("longitude"))
                lat_raw = raw.get("lat", raw.get("latitude"))
                if lon_raw is None or lat_raw is None:
                    raise GisError("corner needs both 'lon' and 'lat'")
            elif isinstance(raw, AoiCorner):
                out.append(raw)
                continue
            elif isinstance(raw, (list, tuple)) and len(raw) == 2:
                lon_raw, lat_raw = raw[0], raw[1]
            else:
                raise GisError(f"unreadable corner shape {type(raw).__name__}")
            out.append(AoiCorner(lon=parse_dms_string(lon_raw), lat=parse_dms_string(lat_raw)))
        except GisError as exc:
            raise GisError(f"AOI corner {i}: {exc}") from exc
    return out


def corners_from_camera(lon: float, lat: float, radius_m: float) -> list[AoiCorner]:
    """Return AOI corners for a disc of ``radius_m`` around a camera station.

    ★ **The camera-position AOI.** A drone or ground camera has one position and a working
    radius — the distance out to which its frames contain usable ground. That is a far more
    natural way to state an area of interest than four transcribed corners, and it is the
    form the field data already takes: ``Table.xlsx`` is a list of camera stations
    (``gps latitude``/``gps longitude``/``gps altitude``), one per photo.

    ★ **The camera position also fixes the UTM zone**, via :func:`gis.crs.utm_epsg_for` —
    which is the reason to capture it here rather than to ask for a zone separately. A zone
    typed by hand can be wrong; a zone derived from where the camera stood cannot be.

    ★ The returned box **over-covers the disc by 4/pi (~27%)**, because a raster crop is
    rectangular and the smallest rectangle containing a circle is not the circle. That is
    deliberate and stated rather than trimmed: cropping inward would exclude ground inside
    the radius the surveyor asked for.

    Args:
        lon: Camera longitude, EPSG:4326 degrees.
        lat: Camera latitude, EPSG:4326 degrees.
        radius_m: Working radius in TRUE ground metres, ``> 0``.

    Returns:
        Four ``AoiCorner`` values, clockwise from north-west.

    Raises:
        GisError: On a non-finite or non-positive radius, or an out-of-range position.
    """
    if not math.isfinite(radius_m) or radius_m <= 0.0:
        raise GisError(f"the camera radius must be finite and > 0 m, got {radius_m}")

    from gis.geometry import disc_to_bbox
    from gis.types import LonLat

    centre = AoiCorner(lon=lon, lat=lat)  # validates the position's range
    box = disc_to_bbox(LonLat(lon=centre.lon, lat=centre.lat), radius_m)
    return [
        AoiCorner(lon=box.west, lat=box.north),
        AoiCorner(lon=box.east, lat=box.north),
        AoiCorner(lon=box.east, lat=box.south),
        AoiCorner(lon=box.west, lat=box.south),
    ]


def utm_zone_for_camera(lon: float, lat: float) -> str:
    """Return the UTM EPSG the camera's position falls in.

    Thin, deliberate wrapper over :func:`gis.crs.utm_epsg_for` so that callers reaching
    for "the zone from the camera" land on the clamped, +/-180-safe implementation rather
    than re-deriving ``floor((lon + 180) / 6) + 1`` — which returns zone 61 at lon 180.
    """
    from gis.crs import utm_epsg_for

    return utm_epsg_for(lon, lat)


def extent_of(corners: Sequence[AoiCorner]) -> AoiExtent:
    """Return the bounding extent of AOI corners, in EPSG:4326 degrees.

    ★ Antimeridian-naive by design, exactly as ``gis.geometry.bbox_from_points`` is: a
    set of corners spanning the Pacific is indistinguishable from one spanning the globe,
    and guessing is how a box silently becomes 359 degrees wide. A survey AOI that
    genuinely crosses +/-180 must be split and processed as two.

    Args:
        corners: The AOI corners.

    Returns:
        The bounding ``AoiExtent`` in degrees.

    Raises:
        GisError: If ``corners`` is empty, or the extent is degenerate (every corner on
            one meridian or one parallel), which would crop to nothing.
    """
    if not corners:
        raise GisError("no AOI corners")
    lons = [c.lon for c in corners]
    lats = [c.lat for c in corners]
    extent = AoiExtent(left=min(lons), bottom=min(lats), right=max(lons), top=max(lats))
    if extent.is_degenerate:
        raise GisError(
            "the AOI corners are collinear (zero width or height), so there is nothing "
            "to crop; check that the corners are not all on one meridian or parallel"
        )
    return extent
