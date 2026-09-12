"""The export seam (CONTRACT.md §4.21): ABC, context, bundle, format info.

Everything a writer needs arrives in an :class:`ExportContext`, assembled ONCE by
``backend.services.export_service``. Writers never touch the database and never touch the
network, which is what makes each of them trivially unit-testable offline.

★ **The call-time binding rule (CONTRACT.md §11.3).** Four of the eight writers sit on a
dependency that is not in this package's base install (``geopandas``/``fiona``,
``ezdxf``, ``reportlab``). Every one of them binds its dependency **inside the function
that uses it**. Importing ``gis.exports`` — which eagerly imports all eight writers to
build the registry — therefore succeeds with none of them installed, and
:meth:`ExportWriter.is_available` *answers* rather than crashing. :func:`module_available`
below is the shared probe, and it is deliberately ``sys.modules``-aware so that a test
which blocks a module with ``sys.modules["fiona"] = None`` gets ``False`` rather than the
``ValueError`` that ``importlib.util.find_spec`` raises on a ``None`` entry.

★ **Provenance is not decoration.** In this build every GCP is a *direct observation*: the
surveyor marked a landmark in the photograph and clicked the same physical spot on the
map (SCOPE.md §5). Its ``confidence`` is a **surveyor-declared judgement**, not a computed
score. A consumer of an export must be able to tell an observed coordinate from an
inferred one and a declared confidence from a calculated one — so every writer carries
:class:`ExportProvenance`, derived from :attr:`ExportContext.method`, into its output.
"""

from __future__ import annotations

import abc
import hashlib
import importlib.util
import math
import os
import sys
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar, Final, Literal

import numpy as np

from gis.errors import ExportError
from gis.exports.models import GcpRecord
from gis.types import SatelliteChip

__all__ = [
    "ACCURACY_DECIMALS",
    "CONFIDENCE_DECIMALS",
    "ExportBundle",
    "ExportContext",
    "ExportFormatInfo",
    "ExportMethod",
    "ExportProvenance",
    "ExportWriter",
    "LONLAT_DECIMALS",
    "PIXEL_DECIMALS",
    "default_target_srid",
    "enabled_format_ids",
    "format_number",
    "format_timestamp",
    "include_attribution",
    "missing_dependency_reason",
    "module_available",
    "provenance_for",
    "record_provenance",
    "sha256_file",
]


ExportMethod = Literal["direct_georeference", "assisted", "matched"]
"""How the coordinates in an export were produced.

``assisted`` is this build's manual GCP mode: the surveyor's own click. ``matched`` is the
automatic engine, which is DEFERRED (SCOPE.md §1) and therefore produces no rows in this
build — but the value stays legal so that re-enabling the engine later requires no change
here.
"""


#: ★ 6, matching the GCP table's display (~0.11 m of longitude at the equator —
#: an order finer than any CE90 this tool records). The table and the file a
#: client receives must read as the SAME numbers.
LONLAT_DECIMALS: Final[int] = 6
"""~1.1 mm at the equator — finer than ANY provider's accuracy, so rounding is never the
error term. Fixed by CONTRACT.md §4.21 for CSV and applied everywhere for consistency."""

ACCURACY_DECIMALS: Final[int] = 3
"""Millimetres. Reporting more would imply precision the number does not have."""

PIXEL_DECIMALS: Final[int] = 3

CONFIDENCE_DECIMALS: Final[int] = 2


# ─────────────────────────────────────────────────────────────────────────────
# Optional-dependency probing (§11.3)
# ─────────────────────────────────────────────────────────────────────────────


def module_available(name: str) -> bool:
    """Return True iff ``name`` can be imported, WITHOUT importing it.

    ``sys.modules`` is consulted first, deliberately: the §13.1 IU-13 test blocks an
    optional dependency by assigning ``sys.modules["fiona"] = None``, and
    ``importlib.util.find_spec`` raises ``ValueError`` — not ``ImportError`` — on a
    ``None`` entry. A probe that crashed on the very mechanism used to test it would be
    worse than useless.

    Args:
        name: Top-level module name, e.g. ``"geopandas"``.

    Returns:
        True when importable. Never raises.
    """
    if name in sys.modules:
        return sys.modules[name] is not None
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        # ImportError: a parent package is itself absent.
        # ValueError: the module is blocked with a None entry in sys.modules.
        return False


def missing_dependency_reason(*names: str) -> str | None:
    """Return ``"requires x, y"`` naming the absent modules, or None if all are present.

    This string is the tooltip the UI greys an export option with, so it names what to
    install and nothing else.

    Args:
        *names: Top-level module names the caller needs.

    Returns:
        A reason string, or None when every module is importable. Never raises.
    """
    missing = [n for n in names if not module_available(n)]
    if not missing:
        return None
    return "requires " + ", ".join(missing)


# ─────────────────────────────────────────────────────────────────────────────
# Configuration (§9.9). Read at CALL time, defaulted, never raising (L10).
# ─────────────────────────────────────────────────────────────────────────────

_DEFAULT_FORMAT_IDS: Final[tuple[str, ...]] = (
    "csv",
    "geojson",
    "kml",
    "kmz",
    "shapefile",
    "gpkg",
    "dxf",
    "pdf",
)


def _env(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if env is None else env


def include_attribution(env: Mapping[str, str] | None = None) -> bool:
    """Return ``LE_EXPORT_INCLUDE_ATTRIBUTION`` (default True).

    ★ This should not be turned off. Several providers' terms require attribution on
    derived output, so turning it off is a licence decision, not a formatting one — and
    every writer that honours it emits a ``warnings`` entry saying so rather than dropping
    the credit quietly.

    Args:
        env: Environment mapping. Defaults to ``os.environ``.

    Returns:
        Whether imagery attribution travels with the export. Never raises.
    """
    raw = _env(env).get("LE_EXPORT_INCLUDE_ATTRIBUTION", "true").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    return True


def default_target_srid(env: Mapping[str, str] | None = None) -> int:
    """Return ``LE_EXPORT_DEFAULT_SRID`` (default 4326).

    An unparseable value falls back to 4326 rather than taking the process down (L10).

    Args:
        env: Environment mapping. Defaults to ``os.environ``.

    Returns:
        The default EPSG code for new exports. Never raises.
    """
    raw = _env(env).get("LE_EXPORT_DEFAULT_SRID", "").strip()
    try:
        return int(raw)
    except ValueError:
        return 4326


def enabled_format_ids(env: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """Return the operator's ``LE_EXPORT_FORMATS`` allow-list, in registry order.

    Unknown names are ignored rather than raising: a typo in an env var must not remove a
    working system's ability to boot (L10). An empty or absent value means "all formats".

    Args:
        env: Environment mapping. Defaults to ``os.environ``.

    Returns:
        Format ids the operator permits. Never raises.
    """
    raw = _env(env).get("LE_EXPORT_FORMATS", "").strip()
    if not raw:
        return _DEFAULT_FORMAT_IDS
    wanted = {part.strip().lower() for part in raw.split(",") if part.strip()}
    allowed = tuple(fid for fid in _DEFAULT_FORMAT_IDS if fid in wanted)
    return allowed or _DEFAULT_FORMAT_IDS


# ─────────────────────────────────────────────────────────────────────────────
# Formatting helpers — shared so that eight writers cannot drift apart
# ─────────────────────────────────────────────────────────────────────────────


def format_number(value: float | int | None, decimals: int) -> str:
    """Format a number for a text export, or return ``""`` for None.

    ★ ``None`` becomes an EXPLICIT empty string — never ``"None"``, never ``0``, never
    ``"nan"``. The caller is responsible for still emitting the field, so that a missing
    value is *visibly* missing rather than silently absent (CONTRACT.md §13.1, IU-13).

    Negative zero is normalised to ``0``: ``-0.00000000`` in a coordinate column is a
    distraction that costs somebody ten minutes.

    Args:
        value: The number, or None when the producer did not run.
        decimals: Fixed decimal places.

    Returns:
        The formatted number, or ``""``.

    Raises:
        ExportError: If ``value`` is NaN or infinite. A non-finite number in a survey
            deliverable is a wrong answer wearing a number's clothes (L12).
    """
    if value is None:
        return ""
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ExportError(f"refusing to export a non-finite value: {value!r}")
    if numeric == 0.0:
        numeric = 0.0  # collapses -0.0
    return f"{numeric:.{decimals}f}"


def format_timestamp(value: datetime | None) -> str:
    """Format a datetime as ISO 8601 UTC, or ``""`` for None.

    Naive datetimes are assumed UTC rather than rejected — the alternative is failing an
    export over a timezone, and every producer in this system writes UTC.

    Args:
        value: The instant, or None.

    Returns:
        e.g. ``"2026-07-17T09:30:00+00:00"``, or ``""``.
    """
    if value is None:
        return ""
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return aware.isoformat()


def sha256_file(path: Path) -> str:
    """Return the hex sha256 of a file, read in chunks.

    Args:
        path: The file to hash.

    Returns:
        64 lowercase hex characters.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _one_line(value: str) -> str:
    """Flatten a value so it cannot break out of a comment line or an XML attribute."""
    return " ".join(value.split())


# ─────────────────────────────────────────────────────────────────────────────
# Provenance — SCOPE.md §5
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ExportProvenance:
    """Where an export's coordinates came from, and what its confidence means.

    Derived from :attr:`ExportContext.method` — never guessed, never stored twice. The
    three fields answer the three questions a downstream consumer must not have to assume:

    * ``source`` — who produced the coordinate.
    * ``confidence_basis`` — whether the number beside it is a human judgement or a
      calculation.
    * ``is_observation`` — whether the coordinate was **measured** or **inferred**. This
      is the distinction SCOPE.md §2 exists to protect: a confidently-wrong inferred
      coordinate handed to a surveyor is this system's worst failure mode, so an export
      states which kind it is holding.

    Attributes:
        source: ``'manual'`` | ``'direct_georeference'`` | ``'automatic'`` | ``'unknown'``.
        confidence_basis: ``'surveyor_declared'`` | ``'derived_from_georeferencing'`` |
            ``'computed'`` | ``'unknown'``.
        is_observation: True iff the coordinate was measured rather than inferred.
    """

    source: str
    confidence_basis: str
    is_observation: bool


_PROVENANCE_BY_METHOD: Final[Mapping[str, ExportProvenance]] = {
    # SCOPE.md §5 — the surveyor clicked the spot themselves. The coordinate is a direct
    # observation and the confidence is their own declared judgement.
    "assisted": ExportProvenance(
        source="manual",
        confidence_basis="surveyor_declared",
        is_observation=True,
    ),
    # SCOPE.md §3 — a georeferenced upload yields exact GCPs with no matching at all. The
    # coordinate comes from the file's own georeferencing: measured, not inferred.
    "direct_georeference": ExportProvenance(
        source="direct_georeference",
        confidence_basis="derived_from_georeferencing",
        is_observation=True,
    ),
    # The automatic engine. DEFERRED in this build (SCOPE.md §1), so nothing produces this
    # today — but the mapping stays honest so that enabling the engine changes no writer.
    "matched": ExportProvenance(
        source="automatic",
        confidence_basis="computed",
        is_observation=False,
    ),
}

_UNKNOWN_PROVENANCE: Final[ExportProvenance] = ExportProvenance(
    source="unknown",
    confidence_basis="unknown",
    is_observation=False,
)


# ★ SCOPE.md §5 — the PER-ROW twin of ``_PROVENANCE_BY_METHOD``. ``ExportContext.method``
# describes an export's *dominant* method; ``GcpRecord.source`` records who produced THIS
# coordinate. A project export can span a hand-annotated photo (``manual``, observed) and a
# georeferenced upload (``direct_georeference``, observed) at once, and — once the automatic
# engine is re-enabled (SCOPE.md §7) — an inferred (``automatic``) row in an otherwise manual
# export. The row that is measured must never borrow the label of the row that is inferred, so
# a writer derives each row's provenance from the row's own ``source`` and only falls back to
# the export-level method when the row does not know (``source == 'unknown'``).
#
# The three known entries are byte-for-byte the values ``_PROVENANCE_BY_METHOD`` yields for the
# corresponding method, so in this build — where every GCP is written ``source='manual'`` under
# ``method='assisted'`` — per-row and per-export provenance are identical and no output changes.
_PROVENANCE_BY_SOURCE: Final[Mapping[str, ExportProvenance]] = {
    "manual": _PROVENANCE_BY_METHOD["assisted"],
    "direct_georeference": _PROVENANCE_BY_METHOD["direct_georeference"],
    "automatic": _PROVENANCE_BY_METHOD["matched"],
}


def provenance_for(ctx: ExportContext) -> ExportProvenance:
    """Return the provenance implied by ``ctx.method``.

    An unrecognised method resolves to ``unknown`` with ``is_observation=False``. That
    asymmetry is deliberate: claiming "observed" for a method we do not recognise would
    overstate the deliverable, and overstating is the failure this system refuses (L12).

    Args:
        ctx: The export context.

    Returns:
        The provenance. Never raises.
    """
    return _PROVENANCE_BY_METHOD.get(ctx.method, _UNKNOWN_PROVENANCE)


def record_provenance(gcp: GcpRecord, ctx: ExportContext) -> ExportProvenance:
    """Return the provenance of ONE row, preferring the GCP's own ``source`` (SCOPE.md §5).

    This is what a writer uses for a per-row ``source`` / ``coordinate_kind`` /
    ``confidence_basis`` field, and it is the safeguard the ``source`` column exists to
    provide: *"so an automatic GCP can never be confused with an observed one downstream or in
    an export."* Stamping the single export-level :func:`provenance_for` onto every row instead
    would relabel an inferred coordinate as an observed one the moment a project export mixes
    sources — precisely what §7's re-enable guarantee forbids.

    The resolution mirrors :attr:`GcpRecord.source`'s own contract:

    * A **known** source (``manual`` / ``direct_georeference`` / ``automatic``) resolves to its
      own provenance, independent of ``ctx.method``.
    * ``unknown`` (or an empty string) **falls back** to the export-level
      :func:`provenance_for` — the row genuinely does not know, so the export's dominant method
      is the best available answer.
    * Any **other** value is carried verbatim as the ``source`` but claims nothing about it
      (``confidence_basis='unknown'``, ``is_observation=False``). Falling back to the context
      here could silently upgrade an unrecognised label to "observed", which overstates the
      deliverable (L12); relabelling it would lose the value the producer recorded.

    Args:
        gcp: The row being written.
        ctx: The export context, used only as the fallback for an unknown source.

    Returns:
        The row's provenance. Never raises.
    """
    if not gcp.source or gcp.source == "unknown":
        return provenance_for(ctx)
    known = _PROVENANCE_BY_SOURCE.get(gcp.source)
    if known is not None:
        return known
    return ExportProvenance(
        source=gcp.source, confidence_basis="unknown", is_observation=False
    )


# ─────────────────────────────────────────────────────────────────────────────
# The context, the bundle, the format info, the ABC
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ExportContext:
    """Everything a writer needs. Assembled ONCE; writers never touch the DB or the
    network — which makes every writer trivially unit-testable offline.

    Attributes:
        export_id: The export row's id.
        job_id: The originating job, when there was one.
        project_name: For titles and filenames.
        image_filename: The source photograph, when the export is scoped to one.
        gcps: The rows. ★ Only COMMITTED GCPs ever reach here — an uncommitted
            correspondence must never appear in an export (SCOPE.md §5). Enforcing that is
            the service's job; this package trusts the list it is handed.
        chip: The imagery to draw a map figure from, or ``None`` when the provider's terms
            forbid derivative export (§11.5). ``None`` means the PDF omits its figure and
            SAYS SO; it never means "draw something else".
        provider_name: Provenance only, never control flow.
        attribution: The imagery credit. A licence condition, not a nicety.
        terms_url: Where those terms live.
        imagery_captured_at: When the pixels were taken, when the provider says.
        retrieved_at: When we fetched them.
        method: How the coordinates were produced. See :func:`provenance_for`.
        homography: The automatic engine's transform. ``None`` in this build.
        rmse_m: Fit residual in true ground metres, when there was a fit.
        georef_ce90_m: The provider's absolute georeferencing error, CE90 metres.
        target_srid: The requested output EPSG code. Honoured by the writers whose format
            can carry a CRS; the others say in ``warnings`` that they did not.
        generated_at: When this file was produced.
        software_version: What produced it.
    """

    export_id: uuid.UUID
    job_id: uuid.UUID | None
    project_name: str
    image_filename: str | None
    gcps: list[GcpRecord]
    chip: SatelliteChip | None
    provider_name: str
    attribution: str
    terms_url: str
    imagery_captured_at: datetime | None
    retrieved_at: datetime
    method: ExportMethod
    homography: np.ndarray | None
    rmse_m: float | None
    georef_ce90_m: float | None
    target_srid: int = 4326
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    software_version: str = ""
    #: How coordinates are rendered — mirrors the UI's format toggle. ``"ddutmz"`` makes the
    #: CSV writer emit decimal degrees + UTM (easting/northing/zone) + Z (elevation) columns.
    coordinate_format: str = "dd"

    def validate(self) -> None:
        """Check the records are exportable.

        Called at the top of every :meth:`ExportWriter.write`. It rejects the two things a
        writer must never serialise: a non-finite coordinate, and an elevation whose
        source contradicts it (``ck_gcps_elevation_source_consistent``, §4.27) — a
        populated ``elevation_source`` beside a NULL ``elevation_m`` names a producer that
        did not run, which is precisely the lie §4.27 exists to prevent.

        Refusing here is correct: a NaN latitude in a shapefile does not crash anything,
        it just puts a point in the wrong place forever (L12).

        Raises:
            ExportError: On any of the above, naming the offending ``gcp_id``.
        """
        for gcp in self.gcps:
            for name, value in (
                ("lon", gcp.lon),
                ("lat", gcp.lat),
                ("confidence", gcp.confidence),
                ("total_ce90_m", gcp.total_ce90_m),
            ):
                if not math.isfinite(value):
                    raise ExportError(
                        f"gcp {gcp.gcp_id}: {name}={value!r} is not a finite number; "
                        "refusing to write a corrupt survey deliverable"
                    )
            if not (-180.0 <= gcp.lon <= 180.0) or not (-90.0 <= gcp.lat <= 90.0):
                raise ExportError(
                    f"gcp {gcp.gcp_id}: (lon={gcp.lon}, lat={gcp.lat}) is outside the "
                    "EPSG:4326 domain"
                )
            if (gcp.elevation_m is None) != (gcp.elevation_source is None):
                raise ExportError(
                    f"gcp {gcp.gcp_id}: elevation_m={gcp.elevation_m!r} and "
                    f"elevation_source={gcp.elevation_source!r} disagree; the source may "
                    "never name a producer that did not run"
                )

    def metadata_items(self, *, include_attribution_value: bool = True) -> list[tuple[str, str]]:
        """Return the provenance block every export carries, as ordered pairs.

        One definition, eight writers: CSV writes these as ``# `` comments, GeoJSON as a
        foreign member, KML as ``ExtendedData``, the PDF as a page. Keeping the *content*
        in one place is what stops the formats from disagreeing about the same export.

        Args:
            include_attribution_value: When False, the attribution and terms values are
                blanked (``LE_EXPORT_INCLUDE_ATTRIBUTION=false``). The KEYS remain, so the
                omission is visible rather than undetectable.

        Returns:
            ``(key, value)`` pairs, all values already flattened to one line.
        """
        prov = provenance_for(self)
        items: list[tuple[str, str]] = [
            ("software", "LandExplorer"),
            ("software_version", self.software_version),
            ("export_id", str(self.export_id)),
            ("job_id", "" if self.job_id is None else str(self.job_id)),
            ("project_name", self.project_name),
            ("image_filename", self.image_filename or ""),
            ("gcp_count", str(len(self.gcps))),
            ("crs", f"EPSG:{self.target_srid}"),
            ("generated_at", format_timestamp(self.generated_at)),
            ("method", self.method),
            ("source", prov.source),
            ("confidence_basis", prov.confidence_basis),
            ("coordinate_kind", "observed" if prov.is_observation else "inferred"),
            ("imagery_provider", self.provider_name),
            (
                "imagery_attribution",
                self.attribution if include_attribution_value else "",
            ),
            ("imagery_terms_url", self.terms_url if include_attribution_value else ""),
            ("imagery_captured_at", format_timestamp(self.imagery_captured_at)),
            ("imagery_retrieved_at", format_timestamp(self.retrieved_at)),
            ("georef_ce90_m", format_number(self.georef_ce90_m, ACCURACY_DECIMALS)),
            ("rmse_m", format_number(self.rmse_m, ACCURACY_DECIMALS)),
        ]
        return [(key, _one_line(value)) for key, value in items]

    def accuracy_statement(self) -> str:
        """Return the honest, generated accuracy statement for this export.

        Generated from the context, never hand-written per template. ★ A report that
        quietly omits *"this is ±15 m"* is the document that gets forwarded to a client
        and believed.

        Returns:
            One or two sentences, always non-empty.
        """
        prov = provenance_for(self)
        parts: list[str] = []
        if self.method == "direct_georeference":
            parts.append(
                "Coordinates were derived directly from the source file's own "
                "georeferencing. Their accuracy is the source's accuracy."
            )
        elif self.method == "assisted":
            parts.append(
                "Coordinates were placed manually: for each point a surveyor identified a "
                "landmark in the photograph and clicked the same physical location on the "
                "satellite imagery. Each coordinate is a direct observation, not an "
                "inference. Its accuracy is limited by the imagery's ground sample "
                "distance and the precision of the click, both of which are included in "
                "the per-point CE90 figures below."
            )
            parts.append(
                "Each confidence value is a judgement declared by the surveyor who placed "
                "the point. It is NOT a computed score and must not be read as one."
            )
        elif self.method == "matched":
            parts.append(
                "Coordinates were produced by automatic image matching and are inferred, "
                "not observed. The provider's own georeferencing error is reported "
                "separately below and is not included in the fit RMSE."
            )
        else:
            parts.append(
                f"Coordinates were produced by an unrecognised method ({self.method!r}). "
                "Treat their accuracy as unknown."
            )
        if self.rmse_m is not None:
            parts.append(f"Fit RMSE: {format_number(self.rmse_m, ACCURACY_DECIMALS)} m.")
        if self.georef_ce90_m is not None:
            parts.append(
                "Imagery georeferencing error (CE90): "
                f"{format_number(self.georef_ce90_m, ACCURACY_DECIMALS)} m."
            )
        if self.chip is not None:
            gsd = format_number(self.chip.gsd_m, ACCURACY_DECIMALS)
            parts.append(f"Imagery ground sample distance: {gsd} m/pixel.")
            if self.chip.gsd_m >= 5.0:
                parts.append(
                    "★ At this ground sample distance, positional accuracy is limited to "
                    "roughly the tens of metres and is NOT suitable for survey-grade "
                    "control work."
                )
        if not prov.is_observation:
            parts.append(
                "★ These coordinates were inferred rather than measured; verify before "
                "using them as control."
            )
        return " ".join(parts)


@dataclass(frozen=True, slots=True)
class ExportBundle:
    """The result of a write: one file, plus what the writer had to compromise on.

    Attributes:
        path: The file written.
        media_type: Its IANA media type.
        filename: Its basename.
        size_bytes: Its size.
        checksum_sha256: Hex sha256 of the bytes on disk. Served as the download's
            strong ``ETag``, so it must match the file exactly.
        warnings: ★ NOT decoration. When Shapefile truncates ``confidence_basis`` to
            ``CONF_BASIS``, or the PDF omits its map figure because the provider forbids
            derivative export, the user must be TOLD — not left to discover it in their
            GIS at 6pm.
    """

    path: Path
    media_type: str
    filename: str
    size_bytes: int
    checksum_sha256: str
    warnings: list[str]


@dataclass(frozen=True, slots=True)
class ExportFormatInfo:
    """★ The return element of :func:`gis.exports.available_formats`.

    Feeds ``GET /capabilities``' export list and ``ExportCapability`` on the wire.

    Attributes:
        format_id: The registry key.
        label: Human name, e.g. ``"ESRI Shapefile"``.
        media_type: IANA media type of the produced file.
        file_extension: Including the dot.
        available: Whether this format can be written here, right now.
        reason: Why not, e.g. ``"requires fiona"`` — the tooltip the UI greys the option
            with. None iff ``available``.
        is_stdlib_only: True => can NEVER degrade (csv/geojson/kml/kmz).
        supports_target_srid: Whether the format can carry a CRS other than EPSG:4326.
        supports_imagery: Whether the format embeds a map figure (PDF does; CSV does not).
    """

    format_id: str
    label: str
    media_type: str
    file_extension: str
    available: bool
    reason: str | None
    is_stdlib_only: bool
    supports_target_srid: bool
    supports_imagery: bool


class ExportWriter(abc.ABC):
    """Base class for every export writer.

    ★ ``format_id`` is a SINGLE class attribute and the registry is keyed on it, so **one
    class cannot register under two ids**. That is why KML and KMZ are two classes
    (CONTRACT.md §4.21) rather than one class with a flag.
    """

    format_id: ClassVar[str]
    media_type: ClassVar[str]
    file_extension: ClassVar[str]
    label: ClassVar[str]
    is_stdlib_only: ClassVar[bool] = False
    supports_target_srid: ClassVar[bool] = False
    supports_imagery: ClassVar[bool] = False

    @abc.abstractmethod
    def is_available(self) -> tuple[bool, str | None]:
        """(available, reason_if_not). ★ Optional deps are REPORTED, never raised.

        ``GET /capabilities`` returns this so the UI greys out Shapefile with
        ``'requires fiona'`` instead of offering a 500. It MUST be callable with the
        dependency absent, which is why nothing in this package imports an optional
        dependency at module scope (§11.3).

        Returns:
            ``(True, None)`` when usable, else ``(False, reason)``. Never raises.
        """

    @abc.abstractmethod
    def write(self, ctx: ExportContext, out_path: Path) -> ExportBundle:
        """Write the export to ``out_path`` and describe what was written.

        Args:
            ctx: The assembled context.
            out_path: Destination file. Its parent is created if absent.

        Returns:
            The bundle, whose ``checksum_sha256`` matches the bytes on disk.

        Raises:
            ExportError: If the format's dependency is absent, or the context cannot be
                honestly serialised.
        """

    def format_info(self) -> ExportFormatInfo:
        """Return this writer's :class:`ExportFormatInfo`, availability included.

        Returns:
            The info, with ``available``/``reason`` from :meth:`is_available`.
        """
        available, reason = self.is_available()
        return ExportFormatInfo(
            format_id=self.format_id,
            label=self.label,
            media_type=self.media_type,
            file_extension=self.file_extension,
            available=available,
            reason=reason,
            is_stdlib_only=self.is_stdlib_only,
            supports_target_srid=self.supports_target_srid,
            supports_imagery=self.supports_imagery,
        )

    # ── shared machinery ────────────────────────────────────────────────────

    def _require_available(self) -> None:
        """Raise :class:`ExportError` when this writer's dependency is absent.

        Raises:
            ExportError: Naming the missing dependency. Callers are expected to have
                checked :meth:`is_available` first — this is the backstop that turns an
                ``ImportError`` traceback into a typed, explicable failure.
        """
        available, reason = self.is_available()
        if not available:
            raise ExportError(f"{self.format_id} export unavailable: {reason}")

    def _prepare(self, ctx: ExportContext, out_path: Path) -> None:
        """Validate the context and make sure ``out_path``'s directory exists."""
        self._require_available()
        ctx.validate()
        out_path.parent.mkdir(parents=True, exist_ok=True)

    def _srid_warning(self, ctx: ExportContext) -> list[str]:
        """Return a warning when a target SRID was requested that this format cannot carry.

        Silently emitting EPSG:4326 into a file the operator asked to be in UTM is exactly
        the kind of quiet substitution this system does not do.
        """
        if self.supports_target_srid or ctx.target_srid == 4326:
            return []
        return [
            f"{self.label} always stores coordinates in EPSG:4326; the requested "
            f"target_srid={ctx.target_srid} was NOT applied. Use Shapefile, GeoPackage or "
            "DXF for a projected coordinate reference system."
        ]

    def _bundle(self, out_path: Path, warnings: Sequence[str]) -> ExportBundle:
        """Build the bundle for a file already on disk.

        Args:
            out_path: The written file.
            warnings: Everything the writer had to compromise on.

        Returns:
            The bundle, with a checksum computed from the actual bytes.
        """
        return ExportBundle(
            path=out_path,
            media_type=self.media_type,
            filename=out_path.name,
            size_bytes=out_path.stat().st_size,
            checksum_sha256=sha256_file(out_path),
            warnings=list(warnings),
        )

    def _attribution_warnings(self, ctx: ExportContext, *, included: bool) -> list[str]:
        """Warn when attribution was suppressed, or when there is none to carry."""
        if not included:
            return [
                "LE_EXPORT_INCLUDE_ATTRIBUTION=false: the imagery attribution and terms "
                "URL were omitted from this export. Several imagery providers' terms "
                "REQUIRE attribution on derived output; this export may not be "
                "distributable."
            ]
        if not ctx.attribution.strip():
            return [
                f"The imagery provider {ctx.provider_name!r} supplied no attribution "
                "string; this export carries no imagery credit."
            ]
        return []
