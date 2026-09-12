"""GeoAlchemy2 wrappers and JSONB helpers for the repository layer (§2.4).

Consumed by ``app.db.repositories`` (IU-18), which is where **all** SQL lives (L6).
Note who is *not* a consumer: ``app.models`` may import ``sqlalchemy``,
``geoalchemy2`` and ``app.{models.base, core.constants}`` and nothing else (§10.2), so
the ORM declares its own columns and this module does not reach into them.

Everything here is about the two type systems the repositories straddle: PostGIS
geography, and JSONB.
"""

from __future__ import annotations

import json
import re
import struct
from typing import Any, Final, Iterable, Mapping, Sequence

from geoalchemy2 import Geography, Geometry
from geoalchemy2.elements import WKBElement, WKTElement
from sqlalchemy import Float, cast, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import ColumnElement

__all__ = [
    "WGS84_SRID",
    "JSONB",
    "GeographyPoint",
    "GeographyPolygon",
    "as_lonlat",
    "geography_point",
    "geography_polygon",
    "jsonb_contains",
    "jsonb_path_exists",
    "point_wkt",
    "st_distance_m",
    "st_dwithin_m",
    "st_x",
    "st_y",
]

#: EPSG:4326. The one SRID the wire ever sees — ``GcpRead.crs`` is
#: ``Literal["EPSG:4326"]`` and says so rather than leaving anyone to assume (§6.2).
WGS84_SRID: Final = 4326


def geography_point(srid: int = WGS84_SRID) -> Geography:
    """A ``geography(Point, 4326)`` column type.

    ★ ``spatial_index=False`` on every spatial column, always (§13.1 asserts it).
    GeoAlchemy2 otherwise creates a GIST index implicitly, at table-creation time,
    with a name it chooses — which means the index exists in the database but not in
    ``0009_indexes_triggers_views.py``, so Alembic's autogenerate proposes dropping it
    on the next migration, and the naming convention in ``models/base.py`` never
    applies to it. §5.5's indexes are declared explicitly, in the migration, where
    they can be reviewed.

    **geography, not geometry.** Its distance and DWithin operate in **metres on the
    spheroid**, with no projection step and no zone selection — which is precisely
    what a GCP query wants ("every GCP within 50 m of this point") and what geometry
    in 4326 cannot give: geometry's ``ST_Distance`` in 4326 returns *degrees*, a unit
    whose ground length varies by a factor of 1/cos(latitude) and is zero at the pole.
    A degree-based radius check silently narrows as you move north.
    """
    return Geography(geometry_type="POINT", srid=srid, spatial_index=False)


def geography_polygon(srid: int = WGS84_SRID) -> Geography:
    """A ``geography(Polygon, 4326)`` column type — image bounds, search AOIs."""
    return Geography(geometry_type="POLYGON", srid=srid, spatial_index=False)


#: Ready-made instances for the common cases. Column types are stateless, so sharing
#: one instance across tables is safe and keeps the declarations short.
GeographyPoint: Final = geography_point()
GeographyPolygon: Final = geography_polygon()


def point_wkt(lon: float, lat: float, srid: int = WGS84_SRID) -> WKTElement:
    """Build a point literal for an INSERT/UPDATE.

    ★ **Longitude first.** ``POINT(lon lat)``, because WKT is X-then-Y and X is
    longitude. Every human says "lat, lon" and every OGC format says the opposite;
    this function exists so the transposition happens in exactly one place. A
    transposed GCP is not a rounding error — it is a coordinate in a different
    hemisphere that will still parse, still store, and still export.
    """
    if not -180.0 <= lon <= 180.0:
        raise ValueError(f"longitude {lon} is outside [-180, 180] — are lon/lat transposed?")
    if not -90.0 <= lat <= 90.0:
        raise ValueError(f"latitude {lat} is outside [-90, 90] — are lon/lat transposed?")
    return WKTElement(f"POINT({lon} {lat})", srid=srid)


_WKT_POINT_RE: Final = re.compile(
    r"POINT\s*[ZM]*\s*\(\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)", re.IGNORECASE
)

# EWKB type-word flag bits (PostGIS).
_EWKB_SRID_FLAG: Final = 0x20000000
_EWKB_Z_FLAG: Final = 0x80000000
_EWKB_M_FLAG: Final = 0x40000000
_EWKB_TYPE_MASK: Final = 0x0FFFFFFF
_WKB_POINT: Final = 1


def _parse_ewkb_point(data: bytes) -> tuple[float, float]:
    """Decode a PostGIS EWKB point into ``(x, y)`` == ``(lon, lat)``.

    ★ Hand-rolled rather than ``geoalchemy2.shape.to_shape``, and this is a
    §11.3 call, not a wheel-reinvention.

    ``geoalchemy2.shape`` imports **shapely at module scope**, and shapely is an
    *optional* dependency here (§9.14 lists it under "Optional (degrade gracefully)";
    it ships only in the ``[exports]`` extra). Importing it at the top of this module
    would make ``app.db.repositories`` — the layer that reads **every GCP's
    coordinate** — fail to import on any deployment without the exports extra. That is
    exactly the failure §11.3 was written about after v1.0 shipped six module-scope
    optional imports.

    Binding it at call time instead would work but is worse: it puts an optional
    dependency on the hot path of the product's primary read, so a missing shapely
    would degrade GCP reads rather than PDF exports. A point is a byte order, a type
    word and two doubles — decoding it needs no geometry library at all.
    """
    endian = "<" if data[0] == 1 else ">"
    (type_word,) = struct.unpack_from(endian + "I", data, 1)
    offset = 5
    if type_word & _EWKB_SRID_FLAG:
        offset += 4  # the embedded SRID; we know it is 4326 from the column type.
    if (type_word & _EWKB_TYPE_MASK) != _WKB_POINT:
        raise ValueError(f"expected a POINT, got WKB type {type_word & _EWKB_TYPE_MASK}")
    # X and Y lead regardless of the Z/M flags, which only add trailing ordinates.
    x, y = struct.unpack_from(endian + "dd", data, offset)
    return float(x), float(y)


def as_lonlat(element: WKBElement | WKTElement | None) -> tuple[float, float] | None:
    """Read a stored point back as ``(lon, lat)``. None passes through.

    Same ordering as ``point_wkt``, for the same reason: one direction of the
    conversion in each function, both spelled lon-first.

    Prefer ``st_x``/``st_y`` when you are writing the query anyway — letting PostGIS
    project the ordinates out is one less format to be wrong about. This exists for
    the case where you already hold a loaded ORM attribute.
    """
    if element is None:
        return None
    if isinstance(element, WKTElement):
        match = _WKT_POINT_RE.search(element.data)
        if not match:
            raise ValueError(f"not a WKT point: {element.data!r}")
        return (float(match.group(1)), float(match.group(2)))

    data = element.data
    if isinstance(data, str):  # geoalchemy2 hands back hex for a hex-encoded EWKB
        data = bytes.fromhex(data)
    return _parse_ewkb_point(data)


def st_x(column: ColumnElement[Any]) -> ColumnElement[float]:
    """``ST_X(column)`` — the **longitude**. X is lon; see ``point_wkt``."""
    return func.ST_X(cast(column, Geometry), type_=Float)


def st_y(column: ColumnElement[Any]) -> ColumnElement[float]:
    """``ST_Y(column)`` — the **latitude**.

    The cast to geometry is required: ``ST_X``/``ST_Y`` have no geography overload,
    and on a ``geography`` column the call fails to resolve without it.
    """
    return func.ST_Y(cast(column, Geometry), type_=Float)


def st_distance_m(
    column: ColumnElement[Any], lon: float, lat: float, srid: int = WGS84_SRID
) -> ColumnElement[float]:
    """Spheroidal distance in **metres** between a geography column and a point.

    Only meaningful against a ``geography`` column — see ``geography_point``.
    """
    return func.ST_Distance(column, point_wkt(lon, lat, srid), type_=Float)


def st_dwithin_m(
    column: ColumnElement[Any], lon: float, lat: float, radius_m: float, srid: int = WGS84_SRID
) -> ColumnElement[bool]:
    """``ST_DWithin`` in metres — the index-using radius predicate.

    ``ST_DWithin(col, pt, r)`` rather than ``ST_Distance(col, pt) < r``: the former
    can use the GIST index, the latter computes a distance for every row in the table
    first. Same answer, different asymptote.
    """
    return func.ST_DWithin(column, point_wkt(lon, lat, srid), radius_m)


def jsonb_contains(column: ColumnElement[Any], value: Mapping[str, Any]) -> ColumnElement[bool]:
    """``column @> value`` — the containment operator the GIN indexes serve.

    §5.5 builds ``jsonb_path_ops`` GIN indexes on ``images.exif``,
    ``match_jobs.params`` and ``exports.options``. ``jsonb_path_ops`` supports ``@>``
    and not much else, which is exactly the trade: a smaller, faster index for the one
    operator these columns are actually queried with.
    """
    # The explicit cast matters: without it the bound parameter arrives as `text`,
    # `@>` does not resolve against (jsonb, text), and the query errors rather than
    # quietly using the wrong plan.
    return column.op("@>")(cast(json.dumps(value), JSONB))


def jsonb_path_exists(column: ColumnElement[Any], path: str) -> ColumnElement[bool]:
    """``jsonb_path_exists(column, path)`` for SQL/JSON path predicates."""
    return func.jsonb_path_exists(column, path)


def coerce_jsonb(value: Any) -> Any:
    """Make a value safe to hand to a JSONB column.

    psycopg serialises with ``json.dumps``, which chokes on UUID, datetime, Path,
    Decimal and numpy scalars — every one of which turns up naturally in a
    ``warnings`` list or a ``params`` blob assembled from real objects. Failing here,
    with the offending value in hand, beats failing in the driver during a flush.
    """
    return json.loads(json.dumps(value, default=str))


def jsonb_array(values: Iterable[Any]) -> list[Any]:
    """Normalise an iterable into a JSONB-safe list.

    For ``warnings`` and other JSONB array columns that default to ``'[]'``.
    """
    return [coerce_jsonb(v) for v in values]


def unwrap_sequence(value: Sequence[Any] | None) -> list[Any]:
    """``None`` -> ``[]``, otherwise a plain list.

    JSONB array columns are NOT NULL DEFAULT '[]' (§5.5), so a None arriving from a
    caller's optional argument must become an empty list rather than a NULL that
    violates the constraint at flush time.
    """
    return list(value) if value else []


# Re-exported for the repositories, so they never import geoalchemy2 directly and
# there is one place to look when the geo stack moves.
__geoalchemy_reexports__ = (Geography, Geometry, WKBElement, WKTElement)
