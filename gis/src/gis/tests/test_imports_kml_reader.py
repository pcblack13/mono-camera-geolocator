"""``gis.imports.kml_reader`` — parsing, and the round trip against ``kml_writer``.

★ **The round-trip tests are the load-bearing ones.** The reader's whole purpose is to
close a loop the writer opens: a surveyor exports GCPs, refines them in whatever viewer
they own, and imports the result. If the two disagree about a field name, an ordinate
order, or what an empty ``<value/>`` means, the loop silently loses data — and a survey
deliverable that quietly lost a point is the failure mode this codebase is built to avoid.
Asserting the loop rather than the parser is what makes that testable in one place.
"""

from __future__ import annotations

import dataclasses
import io
import uuid
import zipfile
from datetime import UTC, datetime

import pytest

from gis.errors import ImportParseError
from gis.exports.base import ExportContext
from gis.exports.kml_writer import KmlExportWriter, KmzExportWriter
from gis.exports.models import GcpRecord
from gis.imports import read_kml_bytes

# ── fixtures ──────────────────────────────────────────────────────────────────


def _gcp(
    *,
    gcp_id: str = "00000000-0000-4000-8000-000000000001",
    code: str | None = "GCP01",
    lon: float = 30.802498,
    lat: float = 29.318765,
    elevation_m: float | None = 21.4,
    elevation_source: str | None = "copernicus_dem",
) -> GcpRecord:
    """One synthetic record, mirroring the export-writer suite's factory."""
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
        confidence=90.0,
        source="manual",
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
def ctx() -> ExportContext:
    """A manual-mode export context — this build's only real one (SCOPE.md §5)."""
    return ExportContext(
        export_id=uuid.UUID("11111111-2222-3333-4444-555555555555"),
        job_id=None,
        project_name="Wadi El Natrun — Block 7",
        image_filename="DJI_0042.JPG",
        gcps=[
            _gcp(),
            _gcp(gcp_id="00000000-0000-4000-8000-000000000002", code="GCP02", elevation_m=None,
                 elevation_source=None),
            _gcp(gcp_id="00000000-0000-4000-8000-000000000003", code="GCP03", elevation_m=0.0,
                 elevation_source="local_dem"),
        ],
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


# ── the round trip ────────────────────────────────────────────────────────────


def test_round_trip_preserves_every_coordinate(ctx: ExportContext, tmp_path) -> None:
    """★ Export then import returns the same points, in order, to full stored precision."""
    out = tmp_path / "gcps.kml"
    KmlExportWriter().write(ctx, out)

    result = read_kml_bytes(out.read_bytes())

    assert not result.skipped
    assert len(result.placemarks) == len(ctx.gcps)
    for original, parsed in zip(ctx.gcps, result.placemarks, strict=True):
        assert parsed.lon == pytest.approx(original.lon, abs=1e-9)
        assert parsed.lat == pytest.approx(original.lat, abs=1e-9)


def test_round_trip_carries_the_gcp_id(ctx: ExportContext, tmp_path) -> None:
    """The id in ExtendedData is what makes an import an exact match rather than a guess.

    If this breaks, imports silently downgrade to matching on a free-text label.
    """
    out = tmp_path / "gcps.kml"
    KmlExportWriter().write(ctx, out)

    parsed = read_kml_bytes(out.read_bytes()).placemarks
    assert [p.extended_data["gcp_id"] for p in parsed] == [g.gcp_id for g in ctx.gcps]
    assert [p.extended_data["code"] for p in parsed] == [g.code for g in ctx.gcps]


def test_round_trip_distinguishes_absent_elevation_from_zero(
    ctx: ExportContext, tmp_path
) -> None:
    """★ THE ONE THAT MATTERS MOST. 'No elevation' and 'sea level' must not converge.

    The writer omits the third ordinate entirely when ``elevation_m is None`` and emits
    ``,0.0`` for a real zero. A reader that defaulted the missing ordinate to 0.0 would
    turn every un-elevated GCP into a sea-level assertion on the way back in.
    """
    out = tmp_path / "gcps.kml"
    KmlExportWriter().write(ctx, out)

    parsed = read_kml_bytes(out.read_bytes()).placemarks
    assert parsed[0].elevation_m == pytest.approx(21.4)
    assert parsed[1].elevation_m is None, "absent elevation must not become 0.0"
    assert parsed[2].elevation_m == pytest.approx(0.0), "a real 0 m must survive as 0.0"


def test_round_trip_marks_emitted_altitude_absolute(ctx: ExportContext, tmp_path) -> None:
    """The writer sets ``absolute`` whenever it emits an altitude; the reader must see it.

    The import service only writes a height whose mode is absolute, so losing this would
    make our own exports round-trip without their Z.
    """
    out = tmp_path / "gcps.kml"
    KmlExportWriter().write(ctx, out)

    parsed = read_kml_bytes(out.read_bytes()).placemarks
    assert parsed[0].altitude_mode == "absolute"
    assert parsed[1].altitude_mode is None, "no altitude emitted, so no mode to report"


def test_round_trip_through_kmz(ctx: ExportContext, tmp_path) -> None:
    """KMZ is the same document zipped, so it must read back identically."""
    kml_path, kmz_path = tmp_path / "gcps.kml", tmp_path / "gcps.kmz"
    KmlExportWriter().write(ctx, kml_path)
    KmzExportWriter().write(ctx, kmz_path)

    from_kml = read_kml_bytes(kml_path.read_bytes())
    from_kmz = read_kml_bytes(kmz_path.read_bytes())
    assert from_kmz.placemarks == from_kml.placemarks


def test_round_trip_preserves_explicitly_empty_values(ctx: ExportContext, tmp_path) -> None:
    """``<value/>`` means 'looked, found nothing' — distinct from an absent key (§13.1)."""
    context = dataclasses.replace(ctx, gcps=[_gcp(elevation_m=None, elevation_source=None)])
    out = tmp_path / "gcps.kml"
    KmlExportWriter().write(context, out)

    extended = read_kml_bytes(out.read_bytes()).placemarks[0].extended_data
    assert extended["elevation_m"] == "", "the key must be present and empty"
    assert "elevation_source" in extended


# ── foreign files: what an external viewer actually saves ─────────────────────

_MINIMAL = b"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>My Places</name>
<Folder><name>Site A</name>
<Placemark><name>GCP01</name>
<Point><altitudeMode>absolute</altitudeMode>
<coordinates>36.1234567,34.7654321,412.5</coordinates></Point></Placemark>
</Folder></Document></kml>"""


def test_reads_a_minimal_foreign_placemark() -> None:
    """A file with no ExtendedData at all is the common case, not an error case."""
    result = read_kml_bytes(_MINIMAL)
    (point,) = result.placemarks
    assert (point.lon, point.lat) == (pytest.approx(36.1234567), pytest.approx(34.7654321))
    assert point.elevation_m == pytest.approx(412.5)
    assert point.name == "GCP01"
    assert point.extended_data == {}
    assert point.folder_path == ("Site A",)
    assert result.document_name == "My Places"


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(
            b"<Document><Placemark><name>N</name><Point>"
            b"<coordinates>10,20</coordinates></Point></Placemark></Document>",
            id="bare-document-root",
        ),
        pytest.param(
            b"<kml><Placemark><name>N</name><Point>"
            b"<coordinates>10,20</coordinates></Point></Placemark></kml>",
            id="no-namespace",
        ),
        pytest.param(
            b'<kml xmlns="http://earth.example/kml/2.0"><Document><Placemark><name>N</name>'
            b"<Point><coordinates>10,20</coordinates></Point></Placemark></Document></kml>",
            id="unfamiliar-namespace",
        ),
    ],
)
def test_accepts_the_namespace_variants_real_tools_emit(payload: bytes) -> None:
    """Rejecting these would fail files every viewer on the operator's machine opens."""
    (point,) = read_kml_bytes(payload).placemarks
    assert (point.lon, point.lat) == (10.0, 20.0)


def test_finds_a_point_wrapped_in_multigeometry() -> None:
    """``<MultiGeometry>`` around a ``<Point>`` is valid KML and real tools write it."""
    payload = (
        b"<kml><Document><Placemark><name>N</name><MultiGeometry><Point>"
        b"<coordinates>1,2,3</coordinates></Point></MultiGeometry></Placemark></Document></kml>"
    )
    (point,) = read_kml_bytes(payload).placemarks
    assert (point.lon, point.lat, point.elevation_m) == (1.0, 2.0, 3.0)


def test_reads_simpledata_as_well_as_data() -> None:
    """``<SimpleData>`` is the schema-typed spelling of the same idea; both must read."""
    payload = (
        b"<kml><Document><Placemark><ExtendedData><SchemaData>"
        b'<SimpleData name="gcp_id">abc-123</SimpleData></SchemaData></ExtendedData>'
        b"<Point><coordinates>1,2</coordinates></Point></Placemark></Document></kml>"
    )
    (point,) = read_kml_bytes(payload).placemarks
    assert point.extended_data == {"gcp_id": "abc-123"}


# ── refusing to guess ─────────────────────────────────────────────────────────


def test_a_non_point_placemark_is_reported_not_dropped() -> None:
    """A surveyor who imports 30 and gets 29 must be told which one went, and why."""
    payload = (
        b"<kml><Document><Placemark><name>A line</name><LineString>"
        b"<coordinates>1,2 3,4</coordinates></LineString></Placemark></Document></kml>"
    )
    result = read_kml_bytes(payload)
    assert result.placemarks == ()
    (skipped,) = result.skipped
    assert skipped.name == "A line"
    assert "no <Point>" in skipped.reason


@pytest.mark.parametrize(
    ("coordinates", "expected"),
    [
        (b"999,0", "longitude"),
        (b"0,91", "latitude"),
        (b"abc,2", "non-numeric"),
        (b"  ", "empty"),
        (b"5", "lon,lat"),
    ],
)
def test_an_unusable_coordinate_is_skipped_with_a_reason(
    coordinates: bytes, expected: str
) -> None:
    """A bad ordinate must never crash the import and never become a plausible point."""
    payload = (
        b"<kml><Document><Placemark><name>bad</name><Point><coordinates>"
        + coordinates
        + b"</coordinates></Point></Placemark></Document></kml>"
    )
    result = read_kml_bytes(payload)
    assert result.placemarks == ()
    assert expected in result.skipped[0].reason


def test_a_network_link_is_reported_and_never_followed() -> None:
    """★ An import must not become an outbound fetch of somebody else's server."""
    payload = (
        b"<kml><Document><NetworkLink><name>remote</name><Link>"
        b"<href>https://example.invalid/points.kml</href></Link></NetworkLink></Document></kml>"
    )
    result = read_kml_bytes(payload)
    assert result.placemarks == ()
    assert "NetworkLink" in result.skipped[0].reason


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        pytest.param(b"", "empty", id="empty-file"),
        pytest.param(b"<kml><unclosed>", "well-formed", id="malformed-xml"),
        pytest.param(b"<svg/>", "root element", id="wrong-root"),
        pytest.param(b"PK\x03\x04not-a-zip", "zip", id="corrupt-archive"),
    ],
)
def test_an_unreadable_file_raises_rather_than_returning_nothing(
    payload: bytes, expected: str
) -> None:
    """'Your file is broken' and 'your file matched nothing' are different answers."""
    with pytest.raises(ImportParseError, match=expected):
        read_kml_bytes(payload)


def test_an_archive_without_a_kml_member_is_an_error() -> None:
    """A zip of something else is not an import that found zero points."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", b"nothing to see")
    with pytest.raises(ImportParseError, match="no .kml"):
        read_kml_bytes(buffer.getvalue())


def test_kmz_prefers_doc_kml_over_archive_order() -> None:
    """``doc.kml`` is the conventional root; picking the first member would be wrong."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("aaa.kml", b"<kml><Document><name>WRONG</name></Document></kml>")
        archive.writestr("doc.kml", _MINIMAL)
    assert read_kml_bytes(buffer.getvalue()).document_name == "My Places"


def test_a_well_formed_file_with_no_placemarks_is_not_an_error() -> None:
    """Zero results is a legitimate answer and must be distinguishable from a failure."""
    result = read_kml_bytes(b"<kml><Document><name>Empty</name></Document></kml>")
    assert result.placemarks == ()
    assert result.skipped == ()
    assert result.document_name == "Empty"
