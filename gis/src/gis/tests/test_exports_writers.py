"""IU-13 — the export writers (CONTRACT.md §13.1).

**Parametrised over every writer.** The properties pinned here are the ones that were
wrong in v1.0 and the ones a future refactor is most likely to break:

* ``is_available()`` NEVER raises with the dependency absent, and importing the FULL
  ``EXPORT_WRITERS`` registry succeeds with ``geopandas``/``fiona``/``reportlab``/``ezdxf``
  blocked in ``sys.modules`` — the collection path that module-scope imports broke.
* CSV/GeoJSON/KML/KMZ are available with ONLY the standard library.
* The CSV column order matches §4.21 EXACTLY; the UTF-8 BOM is present; longitude comes
  before latitude; coordinates are at 8 dp.
* GeoJSON is RFC 7946: ``[lon, lat]``, and **no ``crs`` member**.
* Shapefile field truncation lands in ``ExportBundle.warnings``.
* ``ExportContext.chip = None`` ⇒ the PDF omits the map figure and SAYS SO in ``warnings``.
* ``kml`` and ``kmz`` resolve to DIFFERENT classes with distinct ``format_id``.
* A GCP with ``elevation_m = None`` exports an EXPLICIT empty cell, never a silent blank.
* Every writer's ``ExportBundle.checksum_sha256`` matches the file.
* No writer imports the ORM or touches the DB (an AST assertion), and no writer imports an
  optional dependency at module scope (§11.3, likewise structural).

No network, no database, no weights, no GPU — every one of these runs offline.
"""

from __future__ import annotations

import ast
import csv as csv_module
import json
import os
import subprocess
import sys
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import pytest

from gis.errors import ExportError
from gis.exports import EXPORT_WRITERS, available_formats, get_writer
from gis.exports.base import (
    ExportContext,
    ExportWriter,
    module_available,
    provenance_for,
    record_provenance,
    sha256_file,
)
from gis.exports.csv_writer import CSV_COLUMNS, CsvExportWriter
from gis.exports.fieldmap import (
    DBF_MAX_FIELD_NAME_LEN,
    EXPLICIT_FIELD_NAMES,
    FieldNameMapper,
)
from gis.exports.geojson_writer import GeoJsonExportWriter
from gis.exports.kml_writer import KmlExportWriter, KmzExportWriter
from gis.exports.models import GcpRecord
from gis.exports.pdf_writer import PdfReportWriter
from gis.exports.shapefile_writer import SHAPEFILE_FIELDS, ShapefileExportWriter

KML_NS = {"k": "http://www.opengis.net/kml/2.2"}

OPTIONAL_DEPENDENCIES = ("geopandas", "shapely", "fiona", "pyogrio", "reportlab", "ezdxf")
"""The modules IU-13 blocks. If any of these is importable at module scope in this package,
`cd gis && pytest` dies at COLLECTION rather than merely going red."""

STDLIB_ONLY_FORMATS = ("csv", "geojson", "kml", "kmz")
DEGRADABLE_FORMATS = ("shapefile", "gpkg", "dxf", "pdf")

EXPORTS_DIR = Path(__file__).resolve().parents[1] / "exports"


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


def _gcp(
    *,
    gcp_id: str = "00000000-0000-4000-8000-000000000001",
    code: str | None = "GCP01",
    lon: float = 30.802498,
    lat: float = 29.318765,
    elevation_m: float | None = 21.4,
    elevation_source: str | None = "copernicus_dem",
    confidence: float = 90.0,
    source: str = "manual",
) -> GcpRecord:
    """Build one synthetic record. Defaults are a plausible, fully-populated point."""
    return GcpRecord(
        gcp_id=gcp_id,
        code=code,
        label="Canal junction, NE corner",
        lon=lon,
        lat=lat,
        elevation_m=elevation_m,
        pixel_col=1043.5,
        pixel_row=822.25,
        satellite_pixel_x=311.75,
        satellite_pixel_y=204.5,
        confidence=confidence,
        source=source,
        horizontal_accuracy_m=1.83,
        total_ce90_m=1.83,
        relative_ce90_m=0.42,
        georef_ce90_m=1.78,
        accuracy_dominant_term="georeference",
        residual_px=None,
        manually_adjusted=False,
        adjustment_offset_m=None,
        landmark_kind="canal",
        elevation_source=elevation_source,
    )


@pytest.fixture
def gcps() -> list[GcpRecord]:
    """Three records: fully populated, elevation-absent, and elevation-at-zero.

    The last two are the pair that catches a writer conflating "unknown" with "sea level".
    """
    return [
        _gcp(),
        _gcp(
            gcp_id="00000000-0000-4000-8000-000000000002",
            code="GCP02",
            lon=30.81005,
            lat=29.31002,
            elevation_m=None,
            elevation_source=None,
            confidence=60.0,
        ),
        _gcp(
            gcp_id="00000000-0000-4000-8000-000000000003",
            code="GCP03",
            lon=-0.12776,
            lat=51.50735,
            elevation_m=0.0,
            elevation_source="manual",
            confidence=35.0,
        ),
    ]


@pytest.fixture
def ctx(gcps: list[GcpRecord]) -> ExportContext:
    """A manual-mode export context — this build's only real one (SCOPE.md §5)."""
    return ExportContext(
        export_id=uuid.UUID("11111111-2222-3333-4444-555555555555"),
        job_id=None,
        project_name="Wadi El Natrun — Block 7",
        image_filename="DJI_0042.JPG",
        gcps=gcps,
        chip=None,
        provider_name="esri_world_imagery",
        attribution="Esri, Maxar, Earthstar Geographics",
        terms_url="https://www.esri.com/en-us/legal/terms/full-master-agreement",
        imagery_captured_at=datetime(2025, 4, 11, 9, 12, tzinfo=UTC),
        retrieved_at=datetime(2026, 7, 17, 8, 0, tzinfo=UTC),
        method="assisted",
        homography=None,
        rmse_m=None,
        georef_ce90_m=1.78,
        target_srid=4326,
        generated_at=datetime(2026, 7, 17, 8, 5, 30, tzinfo=UTC),
        software_version="1.0.0",
    )


@pytest.fixture
def blocked_deps(monkeypatch: pytest.MonkeyPatch) -> None:
    """Block every optional dependency in ``sys.modules``.

    ``None`` is the blocking idiom that makes ``importlib.util.find_spec`` raise
    ``ValueError`` — which is exactly why ``base.module_available`` consults ``sys.modules``
    first. A probe that crashed on the mechanism used to test it would be worse than none.
    """
    for name in OPTIONAL_DEPENDENCIES:
        monkeypatch.setitem(sys.modules, name, None)  # type: ignore[arg-type]


def _writer_ids() -> list[str]:
    return list(EXPORT_WRITERS)


# ─────────────────────────────────────────────────────────────────────────────
# The registry and the call-time binding rule (§11.3)
# ─────────────────────────────────────────────────────────────────────────────


_COLLECTION_PROBE = '''
import sys

_BLOCKED = {blocked!r}


class _Blocker:
    """Make the optional dependencies genuinely unimportable, as on a bare machine."""

    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in _BLOCKED:
            raise ImportError(f"blocked by the IU-13 collection probe: {{name}}")
        return None


sys.meta_path.insert(0, _Blocker())

import gis.exports

assert set(gis.exports.EXPORT_WRITERS) == {{
    "csv", "geojson", "kml", "kmz", "shapefile", "gpkg", "dxf", "pdf",
}}, sorted(gis.exports.EXPORT_WRITERS)

for format_id, factory in gis.exports.EXPORT_WRITERS.items():
    available, reason = factory().is_available()
    assert isinstance(available, bool), format_id
    assert (reason is None) == available, (format_id, available, reason)

infos = gis.exports.available_formats()
usable = {{i.format_id for i in infos if i.available}}
assert usable == {{"csv", "geojson", "kml", "kmz"}}, usable

for name in _BLOCKED:
    assert name not in sys.modules, f"{{name}} was imported despite being blocked"

print("OK")
'''


def test_registry_imports_with_every_optional_dependency_blocked() -> None:
    """★ THE COLLECTION TEST. Import the FULL registry in a fresh interpreter with every
    optional dependency genuinely unimportable.

    This is the exact path v1.0's module-scope imports broke: ``exports/__init__.py`` must
    import all eight writers to build ``EXPORT_WRITERS``, four of which sit on a dependency
    that is not installed here. A module-scope ``import geopandas`` makes this an
    ImportError at COLLECTION — before a single assertion runs.

    It runs in a subprocess deliberately. Blocking a module in THIS interpreter and
    re-importing ``gis.exports`` would leave a second copy of every writer class in
    ``sys.modules``, and the ``isinstance`` assertions elsewhere in this file would then be
    comparing classes from two different module objects. A clean interpreter is both a
    stronger claim and a cheaper one to reason about.
    """
    import gis

    src_root = Path(gis.__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(src_root), *([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])]
    )

    result = subprocess.run(
        [sys.executable, "-c", _COLLECTION_PROBE.format(blocked=OPTIONAL_DEPENDENCIES)],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert result.returncode == 0, (
        "importing gis.exports failed with the optional dependencies blocked — some "
        f"writer binds its dependency at module scope (§11.3).\n{result.stderr}"
    )
    assert result.stdout.strip().endswith("OK")


def test_registry_is_complete_and_every_writer_reports_its_availability(
    blocked_deps: None,
) -> None:
    """In-process companion to the collection probe: with the deps blocked in
    ``sys.modules``, every writer still answers."""
    assert set(EXPORT_WRITERS) == {
        "csv",
        "geojson",
        "kml",
        "kmz",
        "shapefile",
        "gpkg",
        "dxf",
        "pdf",
    }
    for factory in EXPORT_WRITERS.values():
        available, reason = factory().is_available()
        assert isinstance(available, bool)
        assert (reason is None) == available, "a reason is required iff unavailable"


@pytest.mark.parametrize("format_id", _writer_ids())
def test_is_available_never_raises_with_dependencies_blocked(
    format_id: str, blocked_deps: None
) -> None:
    """``is_available()`` REPORTS an absent dependency; it never raises."""
    writer = get_writer(format_id)
    available, reason = writer.is_available()
    assert isinstance(available, bool)
    if not available:
        assert reason and reason.startswith("requires ")


@pytest.mark.parametrize("format_id", STDLIB_ONLY_FORMATS)
def test_stdlib_formats_available_with_nothing_installed(
    format_id: str, blocked_deps: None
) -> None:
    """★ CSV/GeoJSON/KML/KMZ are available with ONLY the standard library.

    This is the promise that the surveyor can always get their coordinates out, whatever
    the environment.
    """
    writer = get_writer(format_id)
    assert writer.is_available() == (True, None)
    assert writer.is_stdlib_only is True


@pytest.mark.parametrize("format_id", DEGRADABLE_FORMATS)
def test_degradable_formats_report_a_reason_when_blocked(
    format_id: str, blocked_deps: None
) -> None:
    """A degradable format names what to install rather than crashing."""
    writer = get_writer(format_id)
    available, reason = writer.is_available()
    assert available is False
    assert reason is not None and reason.startswith("requires ")
    assert writer.is_stdlib_only is False


@pytest.mark.parametrize("format_id", DEGRADABLE_FORMATS)
def test_write_on_a_blocked_format_raises_a_typed_error(
    format_id: str, blocked_deps: None, ctx: ExportContext, tmp_path: Path
) -> None:
    """An unavailable writer raises ``ExportError``, not ``ImportError``.

    A caller catching ``GisError`` must not have to also catch the import system.
    """
    writer = get_writer(format_id)
    with pytest.raises(ExportError) as excinfo:
        writer.write(ctx, tmp_path / f"out{writer.file_extension}")
    assert "requires" in str(excinfo.value)


def test_available_formats_is_truthful_and_total() -> None:
    """``available_formats()`` reports every enabled format, available or not."""
    infos = available_formats()
    assert [i.format_id for i in infos] == list(EXPORT_WRITERS)
    for info in infos:
        assert (info.reason is None) == info.available
        writer = get_writer(info.format_id)
        assert info.media_type == writer.media_type
        assert info.file_extension == writer.file_extension
        assert info.available == writer.is_available()[0]
        assert info.is_stdlib_only == (info.format_id in STDLIB_ONLY_FORMATS)


def test_available_formats_honours_the_operator_allow_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``LE_EXPORT_FORMATS`` removes a format entirely — configuration, not degradation."""
    monkeypatch.setenv("LE_EXPORT_FORMATS", "csv,geojson")
    assert [i.format_id for i in available_formats()] == ["csv", "geojson"]


def test_available_formats_ignores_a_typod_allow_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typo in an env var must not remove a working system's exports (L10)."""
    monkeypatch.setenv("LE_EXPORT_FORMATS", "csv,not_a_format")
    assert [i.format_id for i in available_formats()] == ["csv"]
    monkeypatch.setenv("LE_EXPORT_FORMATS", "nonsense_only")
    assert [i.format_id for i in available_formats()] == list(EXPORT_WRITERS)


def test_get_writer_is_case_insensitive_and_returns_fresh_instances() -> None:
    """Writers are cheap and stateless; the registry hands out new ones."""
    assert isinstance(get_writer("CSV"), CsvExportWriter)
    assert get_writer("csv") is not get_writer("csv")


def test_get_writer_rejects_an_unknown_format() -> None:
    """An unknown id is a typed error naming the known ids."""
    with pytest.raises(ExportError) as excinfo:
        get_writer("shapefil")
    assert "shapefile" in str(excinfo.value)


# ─────────────────────────────────────────────────────────────────────────────
# ★ kml and kmz are DIFFERENT classes (§14 F-46)
# ─────────────────────────────────────────────────────────────────────────────


def test_kml_and_kmz_are_distinct_classes_with_distinct_ids() -> None:
    """★ ``format_id`` is a single class attribute, so one class cannot hold two ids."""
    kml = get_writer("kml")
    kmz = get_writer("kmz")

    assert type(kml) is KmlExportWriter
    assert type(kmz) is KmzExportWriter
    assert type(kml) is not type(kmz)
    assert kml.format_id == "kml" != kmz.format_id == "kmz"
    assert kml.media_type != kmz.media_type
    assert kml.file_extension == ".kml"
    assert kmz.file_extension == ".kmz"
    # The subclass relationship is the point: KMZ *is* a zipped KML, and inherits its body.
    assert isinstance(kmz, KmlExportWriter)


def test_every_registry_key_matches_its_writers_format_id() -> None:
    """The registry key and the class attribute are one fact, not two."""
    for key, factory in EXPORT_WRITERS.items():
        assert factory().format_id == key


def test_every_format_id_is_registered_exactly_once() -> None:
    """★ No class registers under two keys — the exact bug that made KMZ its own class.

    ``format_id`` is a single class attribute, so a class registered twice would report the
    wrong id for one of its keys, and ``get_writer("kmz").file_extension`` would hand back
    ``.kml``.
    """
    factories = list(EXPORT_WRITERS.values())
    assert len(set(factories)) == len(factories)


# ─────────────────────────────────────────────────────────────────────────────
# CSV — the normative format
# ─────────────────────────────────────────────────────────────────────────────


def test_csv_columns_mirror_the_ui_table() -> None:
    """★ The CSV columns ARE the on-screen GCP table's, in the same order — the export reads
    like what the surveyor sees."""
    assert CSV_COLUMNS == (
        "Point ID",
        "Name",
        "Image X",
        "Image Y",
        "Latitude",
        "Longitude",
        "Source",
        "Accuracy",
    )


def test_csv_has_a_utf8_bom(ctx: ExportContext, tmp_path: Path) -> None:
    """★ Excel mis-decodes plain UTF-8 CSV. The BOM costs nothing."""
    bundle = CsvExportWriter().write(ctx, tmp_path / "gcps.csv")
    assert bundle.path.read_bytes().startswith(b"\xef\xbb\xbf")


def test_csv_header_matches_the_column_order(ctx: ExportContext, tmp_path: Path) -> None:
    """The file on disk agrees with the constant."""
    CsvExportWriter().write(ctx, tmp_path / "gcps.csv")
    rows = _read_csv(tmp_path / "gcps.csv")
    assert rows[0] == list(CSV_COLUMNS)


def test_csv_latitude_before_longitude_at_six_dp(
    ctx: ExportContext, tmp_path: Path
) -> None:
    """★ Latitude then Longitude, exactly as the table shows them; 6 dp decimal degrees
    (`LONLAT_DECIMALS` — the same fixed count the GCP table displays)."""
    CsvExportWriter().write(ctx, tmp_path / "gcps.csv")
    rows = _read_csv(tmp_path / "gcps.csv")
    header, first = rows[0], rows[1]
    assert header.index("Latitude") < header.index("Longitude")
    assert first[header.index("Latitude")] == "29.318765"
    assert first[header.index("Longitude")] == "30.802498"


def test_csv_first_row_matches_the_table_cells(ctx: ExportContext, tmp_path: Path) -> None:
    """The nine cells are exactly what the on-screen row shows for the same point."""
    CsvExportWriter().write(ctx, tmp_path / "gcps.csv")
    rows = _read_csv(tmp_path / "gcps.csv")
    header, first = rows[0], rows[1]
    cell = lambda name: first[header.index(name)]  # noqa: E731
    assert cell("Point ID") == "GCP01"
    assert cell("Name") == "Canal junction, NE corner"
    assert cell("Image X") == "1043.5"
    assert cell("Source") == "Observed"
    assert cell("Accuracy") == "±1.8 m"  # total_ce90_m 1.83, <5 m -> 1 dp, like the table


def test_csv_is_only_header_and_rows_no_comment_lines(
    ctx: ExportContext, tmp_path: Path
) -> None:
    """★ The file reads EXACTLY like the on-screen table: a header, the data, nothing else —
    no leading metadata block and no trailing attribution/comment line."""
    CsvExportWriter().write(ctx, tmp_path / "gcps.csv")
    text = (tmp_path / "gcps.csv").read_text("utf-8-sig")
    assert "#" not in text, "no comment lines of any kind"
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert lines[0].split(",") == list(CSV_COLUMNS)
    assert len(lines) == 1 + len(ctx.gcps)  # header + one row per GCP


def test_csv_source_column_marks_observations(
    ctx: ExportContext, tmp_path: Path
) -> None:
    """★ SCOPE.md §5 — a consumer can tell an observation from an inference: the Source column
    reads OBSERVED for a manual GCP, exactly as the table's Source chip does."""
    CsvExportWriter().write(ctx, tmp_path / "gcps.csv")
    rows = _read_csv(tmp_path / "gcps.csv")
    src = rows[0].index("Source")
    assert all(row[src] == "Observed" for row in rows[1:])


def test_csv_missing_name_is_an_empty_cell(
    ctx: ExportContext, tmp_path: Path
) -> None:
    """★ A GCP with no linked-landmark label yields an EXPLICIT empty Name cell — never the
    string 'None' — while the column stays present."""
    import dataclasses

    named = _gcp()
    unnamed = dataclasses.replace(_gcp(), label=None)
    context = ExportContext(**{**_ctx_kwargs(ctx), "gcps": [named, unnamed]})
    CsvExportWriter().write(context, tmp_path / "gcps.csv")
    rows = _read_csv(tmp_path / "gcps.csv")
    header = rows[0]
    name = header.index("Name")
    assert rows[1][name] == "Canal junction, NE corner"
    assert rows[2][name] == ""
    assert len(rows[2]) == len(header), "the column must still be present"


def test_csv_refuses_a_non_finite_coordinate(ctx: ExportContext, tmp_path: Path) -> None:
    """L12 — refuse rather than answer wrongly. A NaN latitude crashes nothing; it just
    puts a point in the wrong place forever."""
    broken = ExportContext(**{**_ctx_kwargs(ctx), "gcps": [_gcp(lat=float("nan"))]})
    with pytest.raises(ExportError):
        CsvExportWriter().write(broken, tmp_path / "gcps.csv")


def test_csv_reports_an_unhonoured_target_srid(ctx: ExportContext, tmp_path: Path) -> None:
    """Silently emitting 4326 when UTM was asked for is the quiet substitution we avoid."""
    projected = ExportContext(**{**_ctx_kwargs(ctx), "target_srid": 32636})
    bundle = CsvExportWriter().write(projected, tmp_path / "gcps.csv")
    assert any("32636" in w and "NOT applied" in w for w in bundle.warnings)


def test_csv_attribution_suppression_is_warned_not_silent(
    ctx: ExportContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``LE_EXPORT_INCLUDE_ATTRIBUTION=false`` is a licence decision and is reported."""
    monkeypatch.setenv("LE_EXPORT_INCLUDE_ATTRIBUTION", "false")
    bundle = CsvExportWriter().write(ctx, tmp_path / "gcps.csv")
    assert any("LE_EXPORT_INCLUDE_ATTRIBUTION" in w for w in bundle.warnings)
    text = (tmp_path / "gcps.csv").read_text("utf-8-sig")
    assert "# Imagery:" not in text, "suppressed: no attribution line is written"


def test_csv_of_an_empty_gcp_list_is_a_header_only_file(
    ctx: ExportContext, tmp_path: Path
) -> None:
    """Zero committed GCPs is a legitimate export, not an error."""
    empty = ExportContext(**{**_ctx_kwargs(ctx), "gcps": []})
    CsvExportWriter().write(empty, tmp_path / "gcps.csv")
    rows = _read_csv(tmp_path / "gcps.csv")
    assert rows == [list(CSV_COLUMNS)]


# ─────────────────────────────────────────────────────────────────────────────
# GeoJSON — RFC 7946
# ─────────────────────────────────────────────────────────────────────────────


def test_geojson_is_rfc7946(ctx: ExportContext, tmp_path: Path) -> None:
    """★ ``[lon, lat]`` and NO ``crs`` member. RFC 7946 §4 removed it; emitting one is
    non-conformant AND ignored, which is the worst pair."""
    GeoJsonExportWriter().write(ctx, tmp_path / "gcps.geojson")
    doc = json.loads((tmp_path / "gcps.geojson").read_text("utf-8"))

    assert doc["type"] == "FeatureCollection"
    assert "crs" not in doc
    for feature in doc["features"]:
        assert "crs" not in feature
        assert "crs" not in feature["geometry"]
        assert feature["type"] == "Feature"
        assert feature["geometry"]["type"] == "Point"

    coords = doc["features"][0]["geometry"]["coordinates"]
    assert coords[0] == pytest.approx(30.802498), "longitude first"
    assert coords[1] == pytest.approx(29.318765)


def test_geojson_elevation_none_is_an_explicit_null(
    ctx: ExportContext, tmp_path: Path
) -> None:
    """★ The KEY is always present with an explicit null; the position gains no fake alt."""
    GeoJsonExportWriter().write(ctx, tmp_path / "gcps.geojson")
    doc = json.loads((tmp_path / "gcps.geojson").read_text("utf-8"))

    populated, absent, at_zero = doc["features"]
    assert len(populated["geometry"]["coordinates"]) == 3
    assert populated["properties"]["elevation_m"] == pytest.approx(21.4)

    assert "elevation_m" in absent["properties"], "never drop the key"
    assert absent["properties"]["elevation_m"] is None
    assert absent["properties"]["elevation_source"] is None
    assert len(absent["geometry"]["coordinates"]) == 2, "no fabricated third ordinate"

    # A measured sea-level height is a real 0.0 and keeps its third ordinate.
    assert len(at_zero["geometry"]["coordinates"]) == 3
    assert at_zero["geometry"]["coordinates"][2] == pytest.approx(0.0)
    assert at_zero["properties"]["elevation_m"] == pytest.approx(0.0)


def test_geojson_carries_provenance_and_attribution(
    ctx: ExportContext, tmp_path: Path
) -> None:
    """★ SCOPE.md §5 + the ToS obligation, on every feature and at the top level."""
    GeoJsonExportWriter().write(ctx, tmp_path / "gcps.geojson")
    doc = json.loads((tmp_path / "gcps.geojson").read_text("utf-8"))

    assert doc["metadata"]["source"] == "manual"
    assert doc["metadata"]["confidence_basis"] == "surveyor_declared"
    assert doc["metadata"]["imagery_attribution"] == ctx.attribution
    assert doc["metadata"]["imagery_provider"] == "esri_world_imagery"

    for feature in doc["features"]:
        assert feature["properties"]["source"] == "manual"
        assert feature["properties"]["confidence_basis"] == "surveyor_declared"
        assert feature["properties"]["coordinate_kind"] == "observed"
        assert feature["properties"]["attribution"] == ctx.attribution


# ─────────────────────────────────────────────────────────────────────────────
# KML / KMZ
# ─────────────────────────────────────────────────────────────────────────────


def test_kml_is_well_formed_and_namespaced(ctx: ExportContext, tmp_path: Path) -> None:
    """OGC KML 2.2 in the default namespace."""
    KmlExportWriter().write(ctx, tmp_path / "gcps.kml")
    root = ET.fromstring((tmp_path / "gcps.kml").read_bytes())
    assert root.tag == "{http://www.opengis.net/kml/2.2}kml"
    assert len(root.findall(".//k:Placemark", KML_NS)) == len(ctx.gcps)


def test_kml_coordinates_are_lon_lat_and_never_fabricate_altitude(
    ctx: ExportContext, tmp_path: Path
) -> None:
    """★ KML's own order is lon,lat[,alt]. A missing elevation emits TWO components — not
    ``,0``, which would assert sea level."""
    KmlExportWriter().write(ctx, tmp_path / "gcps.kml")
    root = ET.fromstring((tmp_path / "gcps.kml").read_bytes())
    coords = [
        (element.text or "")
        for element in root.findall(".//k:Placemark/k:Point/k:coordinates", KML_NS)
    ]
    assert coords[0] == "30.802498,29.318765,21.400"
    assert coords[1] == "30.810050,29.310020"
    assert coords[2] == "-0.127760,51.507350,0.000"


def test_kml_elevation_none_is_an_explicit_empty_value(
    ctx: ExportContext, tmp_path: Path
) -> None:
    """★ The ``<Data>`` element is emitted with an empty ``<value/>``, never omitted.

    An omitted element says nothing; an empty one says "we looked and there is nothing".
    """
    KmlExportWriter().write(ctx, tmp_path / "gcps.kml")
    root = ET.fromstring((tmp_path / "gcps.kml").read_bytes())
    placemarks = root.findall(".//k:Placemark", KML_NS)

    absent = _kml_data(placemarks[1])
    assert "elevation_m" in absent, "the Data element must exist"
    assert absent["elevation_m"] == ""
    assert absent["elevation_source"] == ""

    assert _kml_data(placemarks[0])["elevation_m"] == "21.400"
    assert _kml_data(placemarks[2])["elevation_m"] == "0.000"


def test_kml_carries_provenance_per_placemark(ctx: ExportContext, tmp_path: Path) -> None:
    """SCOPE.md §5 — visible on the point a surveyor clicks, not only in a header."""
    KmlExportWriter().write(ctx, tmp_path / "gcps.kml")
    root = ET.fromstring((tmp_path / "gcps.kml").read_bytes())
    for placemark in root.findall(".//k:Placemark", KML_NS):
        data = _kml_data(placemark)
        assert data["source"] == "manual"
        assert data["confidence_basis"] == "surveyor_declared"
        assert data["coordinate_kind"] == "observed"


def test_kml_colour_bands_track_confidence(ctx: ExportContext, tmp_path: Path) -> None:
    """The one export a human eyeballs in a viewer: confidence must be visible."""
    KmlExportWriter().write(ctx, tmp_path / "gcps.kml")
    root = ET.fromstring((tmp_path / "gcps.kml").read_bytes())
    styles = [
        (p.find("k:styleUrl", KML_NS).text or "")  # type: ignore[union-attr]
        for p in root.findall(".//k:Placemark", KML_NS)
    ]
    assert styles == ["#gcp_conf_high", "#gcp_conf_medium", "#gcp_conf_low"]


def test_kml_references_no_network_resource(ctx: ExportContext, tmp_path: Path) -> None:
    """The file must render offline: no icon hrefs pointing at somebody's CDN."""
    KmlExportWriter().write(ctx, tmp_path / "gcps.kml")
    root = ET.fromstring((tmp_path / "gcps.kml").read_bytes())
    assert root.findall(".//k:Icon", KML_NS) == []
    assert root.findall(".//k:href", KML_NS) == []


def test_kmz_contains_byte_identical_kml(ctx: ExportContext, tmp_path: Path) -> None:
    """★ A KMZ is a zipped KML — literally the same bytes, so the two can never disagree."""
    KmlExportWriter().write(ctx, tmp_path / "gcps.kml")
    KmzExportWriter().write(ctx, tmp_path / "gcps.kmz")

    with zipfile.ZipFile(tmp_path / "gcps.kmz") as archive:
        assert archive.namelist() == ["doc.kml"], "doc.kml is the conventional root"
        inner = archive.read("doc.kml")

    assert inner == (tmp_path / "gcps.kml").read_bytes()
    ET.fromstring(inner)


# ─────────────────────────────────────────────────────────────────────────────
# FieldNameMapper — the .dbf 10-char problem
# ─────────────────────────────────────────────────────────────────────────────


def test_explicit_field_names_are_all_dbf_legal() -> None:
    """A typo in the hand-chosen table would silently reintroduce a collision."""
    for original, mapped in EXPLICIT_FIELD_NAMES.items():
        assert len(mapped) <= DBF_MAX_FIELD_NAME_LEN, original
        assert mapped == mapped.upper()
        assert mapped.replace("_", "").isalnum(), original
        assert not mapped[0].isdigit(), original


NAIVELY_COLLIDING_PAIRS = (
    ("elevation_m", "elevation_source"),
    ("satellite_pixel_x", "satellite_pixel_y"),
    ("confidence", "confidence_basis"),
)
"""★ The pairs in our OWN schema that ``name[:10]`` merges into one column. This is not a
hypothetical: these three are why ``FieldNameMapper`` exists rather than a ``[:10]``."""


@pytest.mark.parametrize(("first", "second"), NAIVELY_COLLIDING_PAIRS)
def test_the_naive_truncation_really_does_collide(first: str, second: str) -> None:
    """Pin the premise. If a field is renamed such that these no longer collide, the
    parametrised cases below stop testing anything and this test says so."""
    assert first[:DBF_MAX_FIELD_NAME_LEN] == second[:DBF_MAX_FIELD_NAME_LEN]


def test_the_shapefile_schema_maps_without_a_single_collision() -> None:
    """★ The real schema is the test case."""
    mapping, _ = FieldNameMapper().map(SHAPEFILE_FIELDS)

    assert len(set(mapping.values())) == len(SHAPEFILE_FIELDS), "no two fields share a name"
    for name in mapping.values():
        assert len(name) <= DBF_MAX_FIELD_NAME_LEN

    for first, second in NAIVELY_COLLIDING_PAIRS:
        assert mapping[first] != mapping[second], (
            f"{first} and {second} both truncate to {first[:10]!r}; the mapper must "
            "separate them or the .dbf silently loses a column"
        )


def test_mapper_deduplicates_by_replacing_trailing_characters() -> None:
    """A suffix must never push the name past the limit."""
    mapping, warnings = FieldNameMapper().map(
        ["some_field_alpha", "some_field_bravo", "some_field_charlie"]
    )
    names = list(mapping.values())
    assert len(set(names)) == 3
    for name in names:
        assert len(name) <= DBF_MAX_FIELD_NAME_LEN
    assert len(warnings) == 3


def test_mapper_deduplicates_case_insensitively() -> None:
    """Several .dbf drivers fold case; two names differing only by case collide."""
    mapping, _ = FieldNameMapper().map(["Value", "value_two", "VALUE"])
    upper = [name.upper() for name in mapping.values()]
    assert len(set(upper)) == 3


def test_mapper_sanitizes_illegal_names() -> None:
    """Non-ASCII, punctuation, and a leading digit are all illegal in a .dbf name."""
    mapping, _ = FieldNameMapper().map(["2nd choice", "wh@t?", "", "  "])
    for name in mapping.values():
        assert name
        assert not name[0].isdigit()
        assert name.replace("_", "").isalnum()
        assert len(name) <= DBF_MAX_FIELD_NAME_LEN


def test_mapper_rejects_duplicate_input() -> None:
    """Merging two columns silently is worse than refusing."""
    with pytest.raises(ValueError):
        FieldNameMapper().map(["confidence", "confidence"])


def test_mapper_warns_on_every_rename() -> None:
    """★ Every rename is a warning. The user must be told, not left to discover it."""
    _, warnings = FieldNameMapper().map(["gcp_id", "accuracy_dominant_term"])
    assert not any("gcp_id" in w for w in warnings), "GCP_ID is unchanged"
    assert any("accuracy_dominant_term" in w for w in warnings)


def test_mapper_readme_table_records_every_original_name() -> None:
    """★ The .dbf cannot hold the original names; this table is the only record."""
    table = FieldNameMapper().readme_table(SHAPEFILE_FIELDS)
    for field in SHAPEFILE_FIELDS:
        assert field in table
    mapping, _ = FieldNameMapper().map(SHAPEFILE_FIELDS)
    for mapped in mapping.values():
        assert mapped in table


def test_mapper_rejects_an_unusable_max_length() -> None:
    """Below 2 the suffix has nowhere to live and uniqueness is unguaranteeable."""
    with pytest.raises(ValueError):
        FieldNameMapper(max_length=1)


# ─────────────────────────────────────────────────────────────────────────────
# ★ chip = None ⇒ the PDF omits the map figure AND SAYS SO
# ─────────────────────────────────────────────────────────────────────────────


def test_pdf_omits_the_map_figure_when_the_chip_is_absent(ctx: ExportContext) -> None:
    """★ ``chip = None`` is what a provider forbidding derivative export looks like from
    in here (§11.5). The figure goes; the coordinates stay; the reason is stated.

    This runs WITHOUT reportlab: the omission decision is taken before any rendering, which
    is itself the property worth having.
    """
    assert ctx.chip is None
    figure, note = PdfReportWriter()._map_figure(ctx, image_cls=None, mm=1.0)
    assert figure is None
    assert "omitted" in note.lower()
    assert "coordinates" in note.lower(), "the note must say the coordinates are unaffected"


@pytest.mark.skipif(not module_available("reportlab"), reason="requires reportlab")
def test_pdf_records_the_omitted_figure_in_warnings(
    ctx: ExportContext, tmp_path: Path
) -> None:
    """★ The omission reaches ``ExportBundle.warnings``, hence the API response."""
    bundle = PdfReportWriter().write(ctx, tmp_path / "report.pdf")
    assert any("map figure was omitted" in w.lower() for w in bundle.warnings)
    assert bundle.path.read_bytes().startswith(b"%PDF-")
    assert bundle.checksum_sha256 == sha256_file(bundle.path)


# ─────────────────────────────────────────────────────────────────────────────
# Shapefile — truncation reaches the warnings
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.skipif(
    not (module_available("geopandas") and module_available("shapely")),
    reason="requires geopandas",
)
def test_shapefile_truncation_lands_in_the_bundle_warnings(
    ctx: ExportContext, tmp_path: Path
) -> None:
    """★ When the .dbf renames a field, the user is TOLD."""
    bundle = ShapefileExportWriter().write(ctx, tmp_path / "gcps.zip")
    assert any("accuracy_dominant_term" in w for w in bundle.warnings)
    assert any("README.txt" in w for w in bundle.warnings)


@pytest.mark.skipif(
    not (module_available("geopandas") and module_available("shapely")),
    reason="requires geopandas",
)
def test_shapefile_ships_as_a_zip_with_every_sidecar(
    ctx: ExportContext, tmp_path: Path
) -> None:
    """A single-file "shapefile" download is an unusable shapefile."""
    bundle = ShapefileExportWriter().write(ctx, tmp_path / "gcps.zip")
    assert bundle.media_type == "application/zip"
    with zipfile.ZipFile(bundle.path) as archive:
        names = set(archive.namelist())
        readme = archive.read("README.txt").decode("utf-8")
    assert {"gcps.shp", "gcps.shx", "gcps.dbf", "gcps.prj", "gcps.cpg"} <= names
    assert "README.txt" in names
    assert ctx.attribution in readme, "the ToS credit must survive the format"
    assert "Field-name map" in readme


def test_shapefile_declares_the_zip_contract_without_geopandas() -> None:
    """The identity attributes are readable with the dependency absent."""
    writer = ShapefileExportWriter()
    assert writer.file_extension == ".zip"
    assert writer.media_type == "application/zip"
    assert writer.supports_target_srid is True


# ─────────────────────────────────────────────────────────────────────────────
# Checksums, bundles, provenance
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("format_id", STDLIB_ONLY_FORMATS)
def test_bundle_checksum_matches_the_file(
    format_id: str, ctx: ExportContext, tmp_path: Path
) -> None:
    """★ The checksum is served as the download's strong ETag; it must match the bytes."""
    writer = get_writer(format_id)
    out = tmp_path / f"gcps{writer.file_extension}"
    bundle = writer.write(ctx, out)

    assert bundle.path == out
    assert bundle.filename == out.name
    assert bundle.size_bytes == out.stat().st_size
    assert bundle.checksum_sha256 == sha256_file(out)
    assert len(bundle.checksum_sha256) == 64
    assert bundle.media_type == writer.media_type


@pytest.mark.parametrize("format_id", STDLIB_ONLY_FORMATS)
def test_writers_create_missing_parent_directories(
    format_id: str, ctx: ExportContext, tmp_path: Path
) -> None:
    """The export dir may not exist yet on a fresh deployment."""
    writer = get_writer(format_id)
    out = tmp_path / "a" / "b" / f"gcps{writer.file_extension}"
    assert writer.write(ctx, out).path.exists()


def test_provenance_maps_every_method_honestly(ctx: ExportContext) -> None:
    """★ SCOPE.md §5. ``assisted`` is this build's manual mode: observed, surveyor-declared."""
    assisted = provenance_for(ctx)
    assert assisted.source == "manual"
    assert assisted.confidence_basis == "surveyor_declared"
    assert assisted.is_observation is True

    direct = provenance_for(ExportContext(**{**_ctx_kwargs(ctx), "method": "direct_georeference"}))
    assert direct.source == "direct_georeference"
    assert direct.is_observation is True

    matched = provenance_for(ExportContext(**{**_ctx_kwargs(ctx), "method": "matched"}))
    assert matched.source == "automatic"
    assert matched.confidence_basis == "computed"
    assert matched.is_observation is False


def test_provenance_of_an_unknown_method_never_claims_observation(
    ctx: ExportContext,
) -> None:
    """L12 — claiming "observed" for a method we do not recognise overstates the
    deliverable, so the unknown case fails toward "inferred"."""
    unknown = provenance_for(ExportContext(**{**_ctx_kwargs(ctx), "method": "wat"}))
    assert unknown.source == "unknown"
    assert unknown.is_observation is False


# ─────────────────────────────────────────────────────────────────────────────
# ★ SCOPE.md §5 — PER-ROW provenance: a mixed export must not relabel an inferred
#   coordinate as an observed one. Enforces the ``GcpRecord.source`` contract and the
#   §7 re-enable guarantee ("zero changes outside ai_engine/").
# ─────────────────────────────────────────────────────────────────────────────


def test_record_provenance_prefers_the_rows_own_source(ctx: ExportContext) -> None:
    """★ The writer contract on ``GcpRecord.source``: *"a writer prefers this value and
    falls back to the context provenance only when it is 'unknown'."*

    ``ctx.method='assisted'`` says "manual/observed" at the export level, but a single
    ``automatic`` row inside it is inferred and must say so — otherwise re-enabling the engine
    (SCOPE.md §7) would silently mislabel inferred coordinates as observed in a mixed export.
    """
    manual = record_provenance(_gcp(source="manual"), ctx)
    assert (manual.source, manual.confidence_basis, manual.is_observation) == (
        "manual",
        "surveyor_declared",
        True,
    )
    assert manual == provenance_for(ctx), "manual under 'assisted' is a no-op — this build"

    automatic = record_provenance(_gcp(source="automatic", confidence=95.0), ctx)
    assert (automatic.source, automatic.confidence_basis, automatic.is_observation) == (
        "automatic",
        "computed",
        False,
    ), "★ an inferred row keeps its own inferred label even in an 'assisted' export"

    direct = record_provenance(_gcp(source="direct_georeference"), ctx)
    assert direct.source == "direct_georeference"
    assert direct.is_observation is True

    # 'unknown' is the one case that defers to the export's dominant method.
    unknown = record_provenance(_gcp(source="unknown"), ctx)
    assert unknown == provenance_for(ctx)

    # A source we do not recognise is carried verbatim but claims nothing (never "observed").
    exotic = record_provenance(_gcp(source="lidar_survey"), ctx)
    assert exotic.source == "lidar_survey"
    assert exotic.confidence_basis == "unknown"
    assert exotic.is_observation is False


@pytest.fixture
def mixed_ctx(ctx: ExportContext) -> ExportContext:
    """An ``assisted`` export holding one observed row and one inferred row.

    This is the future SCOPE.md §7 unblocks: the automatic engine re-enabled, an inferred GCP
    landing in a project that also has hand-placed ones. No writer may then serialise the two
    identically.
    """
    observed = _gcp(gcp_id="00000000-0000-4000-8000-00000000000a", code="OBS", source="manual")
    inferred = _gcp(
        gcp_id="00000000-0000-4000-8000-00000000000b",
        code="INF",
        source="automatic",
        confidence=95.0,
    )
    return ExportContext(**{**_ctx_kwargs(ctx), "gcps": [observed, inferred]})


def test_geojson_labels_each_row_by_its_own_source(
    mixed_ctx: ExportContext, tmp_path: Path
) -> None:
    """★ The inferred feature must NOT borrow the observed feature's provenance."""
    GeoJsonExportWriter().write(mixed_ctx, tmp_path / "mixed.geojson")
    doc = json.loads((tmp_path / "mixed.geojson").read_text("utf-8"))
    by_code = {f["properties"]["code"]: f["properties"] for f in doc["features"]}

    assert (
        by_code["OBS"]["source"],
        by_code["OBS"]["coordinate_kind"],
        by_code["OBS"]["confidence_basis"],
    ) == ("manual", "observed", "surveyor_declared")
    assert (
        by_code["INF"]["source"],
        by_code["INF"]["coordinate_kind"],
        by_code["INF"]["confidence_basis"],
    ) == ("automatic", "inferred", "computed"), (
        "★ the automatic (inferred) row must be distinguishable from the manual (observed) "
        "one — the exact safeguard SCOPE.md §5's source column exists to provide"
    )


def test_kml_labels_each_placemark_by_its_own_source(
    mixed_ctx: ExportContext, tmp_path: Path
) -> None:
    """★ Same guarantee in the format a human eyeballs in a viewer."""
    KmlExportWriter().write(mixed_ctx, tmp_path / "mixed.kml")
    root = ET.fromstring((tmp_path / "mixed.kml").read_bytes())
    by_code = {}
    for placemark in root.findall(".//k:Placemark", KML_NS):
        data = _kml_data(placemark)
        by_code[data["code"]] = data

    assert by_code["OBS"]["source"] == "manual"
    assert by_code["OBS"]["coordinate_kind"] == "observed"
    assert by_code["INF"]["source"] == "automatic"
    assert by_code["INF"]["coordinate_kind"] == "inferred"
    assert by_code["INF"]["confidence_basis"] == "computed"


@pytest.mark.skipif(
    not (module_available("geopandas") and module_available("shapely")),
    reason="requires geopandas",
)
def test_shapefile_labels_each_row_by_its_own_source(
    mixed_ctx: ExportContext, tmp_path: Path
) -> None:
    """★ The .dbf attribute table must carry the per-row source too."""
    import geopandas as gpd

    ShapefileExportWriter().write(mixed_ctx, tmp_path / "mixed.zip")
    with zipfile.ZipFile(tmp_path / "mixed.zip") as archive:
        archive.extractall(tmp_path / "shp")
    frame = gpd.read_file(tmp_path / "shp" / "gcps.shp")
    mapping, _ = FieldNameMapper().map(SHAPEFILE_FIELDS)
    src_col = mapping["source"]
    by_code = {row[mapping["code"]]: row[src_col] for _, row in frame.iterrows()}
    assert by_code["OBS"] == "manual"
    assert by_code["INF"] == "automatic"


def test_context_validate_rejects_an_inconsistent_elevation_source(
    ctx: ExportContext,
) -> None:
    """★ §4.27 — the source may never name a producer that did not run."""
    lying = ExportContext(
        **{
            **_ctx_kwargs(ctx),
            "gcps": [_gcp(elevation_m=None, elevation_source="srtm")],
        }
    )
    with pytest.raises(ExportError) as excinfo:
        lying.validate()
    assert "elevation" in str(excinfo.value)


def test_context_validate_rejects_an_out_of_domain_coordinate(ctx: ExportContext) -> None:
    """A longitude of 400 is not a coordinate."""
    with pytest.raises(ExportError):
        ExportContext(**{**_ctx_kwargs(ctx), "gcps": [_gcp(lon=400.0)]}).validate()


def test_accuracy_statement_states_the_confidence_is_declared(ctx: ExportContext) -> None:
    """★ Generated from the context, never hand-written. A report that quietly omits its
    accuracy is the document that gets forwarded and believed."""
    statement = ctx.accuracy_statement()
    assert "direct observation" in statement
    assert "NOT a computed score" in statement
    assert "1.780 m" in statement


def test_accuracy_statement_warns_on_coarse_imagery(ctx: ExportContext) -> None:
    """★ Sentinel-class GSD is stated ON THE ARTIFACT the client keeps."""
    np = pytest.importorskip("numpy")
    from gis.types import SatelliteChip

    chip = SatelliteChip(
        image=np.zeros((4, 4, 3), dtype=np.uint8),
        geotransform=(0.0, 10.0, 0.0, 0.0, 0.0, -10.0),
        crs="EPSG:3857",
        provider_name="sentinel2",
        attribution="Copernicus Sentinel data",
        terms_url="https://example.invalid/terms",
        zoom=None,
        captured_at=None,
        gsd_m=10.0,
        georef_ce90_m=12.0,
        is_authoritative=False,
    )
    statement = ExportContext(**{**_ctx_kwargs(ctx), "chip": chip}).accuracy_statement()
    assert "NOT suitable for survey-grade" in statement


# ─────────────────────────────────────────────────────────────────────────────
# ★ Structural: no ORM, no DB, no module-scope optional imports
# ─────────────────────────────────────────────────────────────────────────────

_FORBIDDEN_IMPORT_ROOTS = frozenset(
    {
        "sqlalchemy",
        "geoalchemy2",
        "alembic",
        "psycopg",
        "psycopg2",
        "asyncpg",
        "fastapi",
        "pydantic",
        "celery",
        "redis",
        "app",
        "backend",
        "httpx",
        "requests",
        "urllib",
        "socket",
    }
)


def _export_modules() -> list[Path]:
    return sorted(EXPORTS_DIR.glob("*.py"))


def _import_roots(node: ast.Import | ast.ImportFrom) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name.split(".")[0] for alias in node.names]
    if node.level:  # a relative import cannot reach another package
        return []
    return [(node.module or "").split(".")[0]]


@pytest.mark.parametrize("path", _export_modules(), ids=lambda p: p.name)
def test_no_writer_imports_the_orm_or_touches_the_db(path: Path) -> None:
    """★ AST assertion. Writers consume ``GcpRecord``; they never open a session.

    That indirection is what makes every writer testable offline — and it only stays true
    if something checks.
    """
    tree = ast.parse(path.read_text("utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for root in _import_roots(node):
                assert root not in _FORBIDDEN_IMPORT_ROOTS, (
                    f"{path.name} imports {root!r}: writers never touch the database, the "
                    "web framework, or the network"
                )


@pytest.mark.parametrize("path", _export_modules(), ids=lambda p: p.name)
def test_no_optional_dependency_is_imported_at_module_scope(path: Path) -> None:
    """★ THE CALL-TIME BINDING RULE (§11.3), asserted structurally.

    A module-scope ``import geopandas`` would make ``import gis.exports`` — which builds the
    registry by importing all eight writers — die at COLLECTION on a machine without the
    geo stack. The blocked-import test above catches it dynamically; this one names the
    offending file and line, which is what a maintainer actually needs.
    """
    tree = ast.parse(path.read_text("utf-8"), filename=str(path))
    for node in tree.body:  # depth 0 ONLY — nested imports are the whole point
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for root in _import_roots(node):
                assert root not in OPTIONAL_DEPENDENCIES, (
                    f"{path.name}:{node.lineno} imports {root!r} at module scope; §11.3 "
                    "requires it be bound inside the function that uses it"
                )
        # `if TYPE_CHECKING:` blocks are erased at runtime and are therefore permitted.


def test_every_writer_subclasses_the_abc_and_declares_its_identity() -> None:
    """The seam is real: the registry only ever holds ``ExportWriter`` subclasses."""
    for format_id, factory in EXPORT_WRITERS.items():
        writer = factory()
        assert isinstance(writer, ExportWriter)
        assert writer.format_id == format_id
        assert writer.media_type and "/" in writer.media_type
        assert writer.file_extension.startswith(".")
        assert writer.label


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _read_csv(path: Path) -> list[list[str]]:
    """Read a CSV, honouring the BOM and dropping the provenance comment lines."""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [row for row in csv_module.reader(handle) if not _is_comment(row)]
    return rows


def _is_comment(row: list[str]) -> bool:
    return bool(row) and row[0].startswith("#")


def _kml_data(placemark: ET.Element) -> dict[str, str]:
    """Flatten a Placemark's ExtendedData into ``{name: value}``.

    A ``<Data>`` with an empty ``<value/>`` yields ``""`` — which is the whole point of the
    explicit-empty-cell rule, so it must not be conflated with a missing key here either.
    """
    out: dict[str, str] = {}
    for data in placemark.findall("k:ExtendedData/k:Data", KML_NS):
        name = data.get("name")
        if name is None:
            continue
        value = data.find("k:value", KML_NS)
        out[name] = (value.text or "") if value is not None else ""
    return out


def _ctx_kwargs(ctx: ExportContext) -> dict[str, Any]:
    """Explode a context so a test can vary one field.

    ``dataclasses.replace`` would be the idiom, but ``ExportContext`` is ``slots=True`` and
    a plain dict of its fields is clearer at the call site than a chain of replaces.
    """
    return {
        "export_id": ctx.export_id,
        "job_id": ctx.job_id,
        "project_name": ctx.project_name,
        "image_filename": ctx.image_filename,
        "gcps": ctx.gcps,
        "chip": ctx.chip,
        "provider_name": ctx.provider_name,
        "attribution": ctx.attribution,
        "terms_url": ctx.terms_url,
        "imagery_captured_at": ctx.imagery_captured_at,
        "retrieved_at": ctx.retrieved_at,
        "method": ctx.method,
        "homography": ctx.homography,
        "rmse_m": ctx.rmse_m,
        "georef_ce90_m": ctx.georef_ce90_m,
        "target_srid": ctx.target_srid,
        "generated_at": ctx.generated_at,
        "software_version": ctx.software_version,
    }
