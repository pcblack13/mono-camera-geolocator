"""KML and KMZ placemark reading — stdlib ``xml.etree``, the inverse of ``kml_writer``.

★ **THIS MODULE READS A FILE. IT IS NOT AN IMAGERY PROVIDER.**
``docs/legal/imagery-terms.md`` §1 excludes a particular vendor's globe product as an
*imagery source*: we do not fetch its tiles, call its endpoints, or scrape its client.
None of that changes here. This module parses an **OGC KML 2.2 document that the operator
hands us** — a file format maintained by the Open Geospatial Consortium, which QGIS,
ArcGIS, Garmin, and every desktop globe viewer can all write. The parser cannot tell which
program produced its input and deliberately does not try: there is no producer sniffing, no
vendor branch, and no field that records one. What comes back is *the operator's own
assertion about a coordinate*, which is exactly how the accuracy layer must treat it.

★ **WHAT THIS MODULE WILL NOT DO.** It will not invent a coordinate, an altitude, or an
error bar. A placemark with no ``<Point>`` is reported as skipped rather than guessed at; a
2-tuple ``<coordinates>`` yields ``elevation_m = None`` rather than ``0.0``, because a KML
altitude of zero is a real assertion of sea level and an absent one is not. The distinction
survives into ``gcps.elevation_m`` — see ``ck_gcps_elevation_source_consistent``.

★ **PARSED WITHOUT NAMESPACE STRICTNESS.** Real-world KML in the wild appears with the
2.2 namespace, with the older 2.0/2.1 namespaces, with a vendor extension namespace bolted
on, and — from more than one popular tool — with no namespace at all. Matching on the
*local* tag name accepts all of them. A stricter parser would reject files that every
viewer on the operator's machine opens without complaint, and be wrong to.

Read errors are :class:`gis.errors.ImportParseError`. A file that parses but contains no
usable placemark is **not** an error: it returns an empty tuple plus the per-placemark
reasons, because "nothing matched" and "your file is broken" are different answers.
"""

from __future__ import annotations

import io
import math
import zipfile
from dataclasses import dataclass, field
from typing import Final
from xml.etree import ElementTree as ET

from gis.errors import ImportParseError

__all__ = [
    "KmlReadResult",
    "PlacemarkRecord",
    "SkippedPlacemark",
    "read_kml_bytes",
]


_ZIP_MAGIC: Final[bytes] = b"PK\x03\x04"
"""Local file header. A KMZ is an ordinary zip; this is how we tell it from flat KML."""

_ROOT_DOC_NAME: Final[str] = "doc.kml"
"""The conventional root document of a KMZ — what ``KmzExportWriter`` writes."""

_MAX_ARCHIVE_MEMBERS: Final[int] = 4096
"""A KMZ with more members than this is refused unread.

★ A zip bomb is a real input here: this file arrives over an upload endpoint. The cap,
the per-member size cap and the total-size cap below are enforced BEFORE decompression,
against the header-declared sizes, so a malicious archive is rejected without ever being
expanded in memory.
"""

_MAX_MEMBER_BYTES: Final[int] = 256 * 1024 * 1024
"""Largest single decompressed member we will read from a KMZ (256 MiB)."""

_MAX_TOTAL_BYTES: Final[int] = 512 * 1024 * 1024
"""Largest total decompressed size we will accept from a KMZ (512 MiB)."""


@dataclass(frozen=True, slots=True)
class PlacemarkRecord:
    """One KML ``<Placemark>`` carrying a ``<Point>``.

    Attributes:
        name: The ``<name>`` text, stripped; None when absent or blank.
        lon: Longitude in degrees, EPSG:4326. Finite, within [-180, 180].
        lat: Latitude in degrees, EPSG:4326. Finite, within [-90, 90].
        elevation_m: The third coordinate ordinate, metres — or **None** when the
            ``<coordinates>`` tuple had only two ordinates. ★ Never defaulted to 0.
        altitude_mode: The ``<altitudeMode>`` local text if present (``absolute``,
            ``clampToGround``, ``relativeToGround``, …), else None. The caller needs this
            to decide whether ``elevation_m`` means anything: an altitude under
            ``clampToGround`` is decoration, not a measurement.
        extended_data: ``<ExtendedData><Data name=…><value>…`` pairs, flattened. Empty
            when the producer wrote none. This is what lets a file we exported round-trip
            back to the exact GCP it came from — a foreign file simply has none.
        folder_path: The ``<Folder><name>`` chain enclosing the placemark, outermost
            first. Purely informational; used to describe a point in the preview UI.
    """

    lon: float
    lat: float
    name: str | None = None
    elevation_m: float | None = None
    altitude_mode: str | None = None
    extended_data: dict[str, str] = field(default_factory=dict)
    folder_path: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SkippedPlacemark:
    """A ``<Placemark>`` that could not become a :class:`PlacemarkRecord`.

    Surfaced rather than silently dropped: a surveyor who exported 30 points and imported
    28 must be told which two were lost and why, or the import has quietly changed the
    deliverable.

    Attributes:
        name: The placemark's ``<name>`` if it had one, for identification.
        reason: A short human-readable cause, shown verbatim in the preview UI.
    """

    name: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class KmlReadResult:
    """Everything one file yielded.

    Attributes:
        placemarks: The usable point records, document order.
        skipped: Placemarks that were present but unusable, with reasons.
        document_name: The ``<Document><name>`` if present — echoed in the preview so the
            operator can confirm they picked the file they meant.
    """

    placemarks: tuple[PlacemarkRecord, ...]
    skipped: tuple[SkippedPlacemark, ...]
    document_name: str | None = None


def _local(tag: object) -> str:
    """The local part of a possibly namespaced tag, lowercased.

    ``{http://www.opengis.net/kml/2.2}Placemark`` -> ``placemark``. Comment and PI nodes
    carry a callable ``tag`` rather than a string; those become ``""`` and match nothing.
    """
    if not isinstance(tag, str):
        return ""
    _, _, local = tag.rpartition("}")
    return local.lower()


def _find_children(element: ET.Element, name: str) -> list[ET.Element]:
    """Direct children whose local tag equals ``name``."""
    return [child for child in element if _local(child.tag) == name]


def _first_child(element: ET.Element, name: str) -> ET.Element | None:
    """The first direct child whose local tag equals ``name``, else None."""
    for child in element:
        if _local(child.tag) == name:
            return child
    return None


def _first_descendant(element: ET.Element, name: str) -> ET.Element | None:
    """The first descendant (any depth, document order) with local tag ``name``.

    Used for ``<Point>``, which may sit directly under the Placemark or be wrapped in a
    ``<MultiGeometry>`` — both are valid KML and both are written by real tools.
    """
    if _local(element.tag) == name:
        return element
    for child in element:
        found = _first_descendant(child, name)
        if found is not None:
            return found
    return None


def _text_of(element: ET.Element | None) -> str | None:
    """Stripped text content, or None when absent/blank."""
    if element is None or element.text is None:
        return None
    stripped = element.text.strip()
    return stripped or None


def _extended_data_of(placemark: ET.Element) -> dict[str, str]:
    """Flatten ``<ExtendedData><Data name="k"><value>v</value></Data></ExtendedData>``.

    ★ An empty ``<value/>`` maps to ``""``, NOT to a missing key. ``kml_writer._data``
    emits every field even when it has nothing to say, precisely so a reader can tell
    "measured and absent" from "never recorded". Collapsing the two here would throw away
    the distinction the writer went out of its way to preserve.

    ``<SimpleData name=…>`` inside a ``<SchemaData>`` is read the same way: it is the
    typed-schema spelling of the same idea, and several producers emit it instead.
    """
    out: dict[str, str] = {}
    extended = _first_child(placemark, "extendeddata")
    if extended is None:
        return out

    for data in extended.iter():
        local = _local(data.tag)
        if local == "data":
            key = data.get("name")
            if key:
                out[key] = _text_of(_first_child(data, "value")) or ""
        elif local == "simpledata":
            key = data.get("name")
            if key:
                out[key] = (data.text or "").strip()
    return out


def _parse_coordinates(raw: str) -> tuple[float, float, float | None]:
    """Parse the first ``lon,lat[,alt]`` tuple of a ``<coordinates>`` body.

    KML's ordinate order is lon,lat — the same as ours, which is one fewer flip to get
    wrong, and the reason this function returns them in that order rather than "fixing"
    it to lat,lon somewhere a caller cannot see.

    Args:
        raw: The element's text. May carry leading/trailing whitespace and newlines, and
            for a ``<Point>`` should hold exactly one tuple; extra tuples are ignored.

    Returns:
        ``(lon, lat, elevation_m_or_None)``.

    Raises:
        ValueError: The text holds no parseable tuple, an ordinate is not a number or is
            non-finite, or a value is out of range for its axis.
    """
    first = raw.split()[0] if raw.split() else ""
    if not first:
        raise ValueError("empty <coordinates>")

    parts = first.split(",")
    if len(parts) < 2:
        raise ValueError(f"<coordinates> needs at least lon,lat — got {first!r}")

    try:
        lon = float(parts[0])
        lat = float(parts[1])
    except ValueError as exc:
        raise ValueError(f"non-numeric ordinate in {first!r}") from exc

    # ★ A 2-tuple means NO ALTITUDE, not altitude zero. An empty third field
    #   ("12.3,45.6,") is the same statement and is treated identically.
    elevation: float | None = None
    if len(parts) >= 3 and parts[2].strip():
        try:
            elevation = float(parts[2])
        except ValueError as exc:
            raise ValueError(f"non-numeric altitude in {first!r}") from exc

    if not math.isfinite(lon) or not math.isfinite(lat):
        raise ValueError(f"non-finite coordinate in {first!r}")
    if elevation is not None and not math.isfinite(elevation):
        raise ValueError(f"non-finite altitude in {first!r}")
    if not -180.0 <= lon <= 180.0:
        raise ValueError(f"longitude {lon} outside [-180, 180]")
    if not -90.0 <= lat <= 90.0:
        raise ValueError(f"latitude {lat} outside [-90, 90]")

    return lon, lat, elevation


def _read_placemark(
    placemark: ET.Element, folder_path: tuple[str, ...]
) -> PlacemarkRecord | SkippedPlacemark:
    """Turn one ``<Placemark>`` into a record, or explain why it cannot be one."""
    name = _text_of(_first_child(placemark, "name"))

    point = _first_descendant(placemark, "point")
    if point is None:
        return SkippedPlacemark(
            name=name,
            reason="placemark has no <Point> geometry (a GCP is a point)",
        )

    coordinates = _first_child(point, "coordinates")
    raw = coordinates.text if coordinates is not None else None
    if not raw or not raw.strip():
        return SkippedPlacemark(name=name, reason="<Point> has empty <coordinates>")

    try:
        lon, lat, elevation = _parse_coordinates(raw)
    except ValueError as exc:
        return SkippedPlacemark(name=name, reason=str(exc))

    return PlacemarkRecord(
        lon=lon,
        lat=lat,
        name=name,
        elevation_m=elevation,
        altitude_mode=_text_of(_first_descendant(point, "altitudemode")),
        extended_data=_extended_data_of(placemark),
        folder_path=folder_path,
    )


def _walk(
    element: ET.Element,
    folder_path: tuple[str, ...],
    placemarks: list[PlacemarkRecord],
    skipped: list[SkippedPlacemark],
) -> None:
    """Depth-first walk collecting placemarks, tracking the enclosing folder names.

    Recurses through Folders and Documents rather than using a flat ``iter()`` so the
    folder chain stays attached to each point. ``<NetworkLink>`` subtrees are deliberately
    NOT followed: a network link is a URL, and dereferencing one would turn a local file
    read into an outbound fetch of somebody else's server — which is both a surprise to
    the operator and precisely the kind of thing this app does not do behind their back.
    """
    for child in element:
        local = _local(child.tag)
        if local == "placemark":
            result = _read_placemark(child, folder_path)
            if isinstance(result, PlacemarkRecord):
                placemarks.append(result)
            else:
                skipped.append(result)
        elif local == "folder":
            folder_name = _text_of(_first_child(child, "name"))
            next_path = folder_path + (folder_name,) if folder_name else folder_path
            _walk(child, next_path, placemarks, skipped)
        elif local == "networklink":
            skipped.append(
                SkippedPlacemark(
                    name=_text_of(_first_child(child, "name")),
                    reason="<NetworkLink> not followed — imports never fetch remote data",
                )
            )
        elif local in {"document", "kml"}:
            _walk(child, folder_path, placemarks, skipped)


def _kml_from_archive(data: bytes) -> bytes:
    """Extract the root KML document from KMZ bytes.

    Prefers ``doc.kml`` (the conventional root, and what we write), else the first
    ``.kml`` member in archive order — which is what viewers do.

    Raises:
        ImportParseError: Not a readable zip, no ``.kml`` member, or the archive
            declares sizes beyond the decompression caps.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ImportParseError(f"file starts like a zip but cannot be read: {exc}") from exc

    with archive:
        infos = archive.infolist()
        if len(infos) > _MAX_ARCHIVE_MEMBERS:
            raise ImportParseError(
                f"archive declares {len(infos)} members, over the {_MAX_ARCHIVE_MEMBERS} limit"
            )

        # ★ Budget checked against the HEADER-DECLARED sizes, before any read() call.
        total = sum(info.file_size for info in infos)
        if total > _MAX_TOTAL_BYTES:
            raise ImportParseError(
                f"archive declares {total} bytes uncompressed, over the "
                f"{_MAX_TOTAL_BYTES} limit"
            )

        members = [info for info in infos if info.filename.lower().endswith(".kml")]
        if not members:
            raise ImportParseError("archive contains no .kml document")

        chosen = next(
            (i for i in members if i.filename.rsplit("/", 1)[-1].lower() == _ROOT_DOC_NAME),
            members[0],
        )
        if chosen.file_size > _MAX_MEMBER_BYTES:
            raise ImportParseError(
                f"{chosen.filename} declares {chosen.file_size} bytes, over the "
                f"{_MAX_MEMBER_BYTES} limit"
            )

        try:
            return archive.read(chosen)
        except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
            # RuntimeError is what zipfile raises for an encrypted member.
            raise ImportParseError(f"cannot read {chosen.filename} from archive: {exc}") from exc


def read_kml_bytes(data: bytes) -> KmlReadResult:
    """Read placemarks from KML or KMZ bytes.

    The two are distinguished by the zip magic number rather than by filename, so a
    correctly-formed file imports whatever extension the operator's tool gave it.

    Args:
        data: The uploaded file's raw bytes.

    Returns:
        A :class:`KmlReadResult`. A well-formed document containing no point placemarks
        yields empty ``placemarks`` — that is a legitimate answer, not a failure.

    Raises:
        ImportParseError: The bytes are empty, are not well-formed XML, are a zip with no
            readable KML inside, or parse to a root that is not a KML document.
    """
    if not data:
        raise ImportParseError("file is empty")

    payload = _kml_from_archive(data) if data[:4] == _ZIP_MAGIC else data

    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ImportParseError(f"not well-formed XML: {exc}") from exc

    # Accept a <kml> root, or a bare <Document>/<Folder> root — tools emit all three, and
    # rejecting the latter two would fail files that every viewer opens.
    if _local(root.tag) not in {"kml", "document", "folder"}:
        raise ImportParseError(
            f"root element is <{_local(root.tag) or '?'}>, expected <kml> or <Document>"
        )

    document = _first_descendant(root, "document")
    document_name = _text_of(_first_child(document, "name")) if document is not None else None

    placemarks: list[PlacemarkRecord] = []
    skipped: list[SkippedPlacemark] = []
    _walk(root, (), placemarks, skipped)

    return KmlReadResult(
        placemarks=tuple(placemarks),
        skipped=tuple(skipped),
        document_name=document_name,
    )
