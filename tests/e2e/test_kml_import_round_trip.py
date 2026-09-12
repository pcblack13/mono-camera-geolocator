"""★ THE IMPORT ROUND TRIP: export -> refine elsewhere -> import -> adjusted GCPs.

The inverse of ``test_manual_gcp_offline.py``. That module proves a surveyor can go
photo -> annotate -> correspond -> export; this one proves the loop closes — that the file
they took away and refined in whatever viewer they own comes back and moves the right
points by the right amount, and that everything it *cannot* justify is refused rather than
guessed.

★ **The service is driven against a stub repository, deliberately.** The interesting
behaviour — which placemark claims which GCP, what counts as movement, when an altitude is
honoured — is pure decision-making that a live PostGIS adds nothing to. The two writes the
service performs (``adjust``, ``set_elevation``) are recorded by the stub and asserted, so
the contract with the data layer is pinned without a database. ``tests/integration``
remains the place that proves those two methods do what they say against real SQL.

**What is NOT tested here, on purpose:** which program wrote the file. The service has no
way to ask and no field in which to record an answer — see ``kml_import_service``'s module
docstring. Any test asserting a producer would be asserting a capability that must not
exist.
"""

from __future__ import annotations

import asyncio
import functools
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

pytest.importorskip("pydantic", reason="the import service speaks the pydantic wire types")

from gis.exports.base import ExportContext  # noqa: E402
from gis.exports.kml_writer import KmlExportWriter  # noqa: E402
from gis.exports.models import GcpRecord  # noqa: E402

from app.core.exceptions import ImportFileChanged, ValidationError  # noqa: E402
from app.schemas.imports import KmlImportApplyRequest  # noqa: E402
from app.services.kml_import_service import KmlImportService  # noqa: E402

PROJECT_ID = uuid.UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")

GCP1 = uuid.UUID("00000000-0000-4000-8000-000000000001")
GCP2 = uuid.UUID("00000000-0000-4000-8000-000000000002")


def sync(fn):
    """Drive an ``async def`` test with ``asyncio.run``.

    ★ Deliberately not ``pytest-asyncio``. The suite runs with ``--strict-markers`` and
    installs no async plugin (``tests/conftest.py``), and the service under test needs
    nothing from an event-loop fixture beyond "run this coroutine to completion". A
    four-line decorator buys that without adding a dev dependency that the contract tier
    would then also have to carry.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return asyncio.run(fn(*args, **kwargs))

    return wrapper


# ── stubs ─────────────────────────────────────────────────────────────────────


@dataclass
class _FakeGcp:
    """Only the columns the import service reads."""

    id: uuid.UUID
    code: str | None
    name: str | None = None
    elevation_m: float | None = None
    accuracy_total_ce90_m: float | None = 1.83


@dataclass
class _StubRepo:
    """Records every write so the test can assert the contract with the data layer."""

    rows: list[tuple[_FakeGcp, float, float]]
    adjusted: list[dict[str, Any]] = field(default_factory=list)
    elevations: list[dict[str, Any]] = field(default_factory=list)

    async def list_for_project(self, project_id: uuid.UUID):
        assert project_id == PROJECT_ID
        return self.rows

    async def adjust(self, gcp_id, *, lon, lat, adjustment_note=None, **_):
        self.adjusted.append(
            {"gcp_id": gcp_id, "lon": lon, "lat": lat, "note": adjustment_note}
        )

    async def set_elevation(self, gcp_id, *, elevation_m, elevation_source, elevation_ce90_m):
        self.elevations.append(
            {
                "gcp_id": gcp_id,
                "elevation_m": elevation_m,
                "elevation_source": elevation_source,
                "elevation_ce90_m": elevation_ce90_m,
            }
        )


def _service(*rows: tuple[_FakeGcp, float, float]) -> tuple[KmlImportService, _StubRepo]:
    repo = _StubRepo(rows=list(rows))
    return KmlImportService(repo), repo  # type: ignore[arg-type]


# ── file builders ─────────────────────────────────────────────────────────────


def _our_kml(*gcps: GcpRecord) -> bytes:
    """A file this system exported — carries ``gcp_id`` in ExtendedData."""
    context = ExportContext(
        export_id=uuid.uuid4(),
        job_id=None,
        project_name="Round trip",
        image_filename="DJI_0042.JPG",
        gcps=list(gcps),
        chip=None,
        provider_name="esri_world_imagery",
        attribution="Esri",
        terms_url="https://example.invalid/terms",
        imagery_captured_at=datetime(2025, 4, 11, 9, 12, tzinfo=UTC),
        retrieved_at=datetime(2026, 7, 17, 8, 0, tzinfo=UTC),
        method="manual",
        homography=None,
        rmse_m=None,
        georef_ce90_m=1.78,
        target_srid=4326,
        generated_at=datetime(2026, 7, 17, 8, 5, 30, tzinfo=UTC),
        software_version="1.0.0",
    )
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "gcps.kml"
        KmlExportWriter().write(context, out)
        return out.read_bytes()


def _record(gcp_id: uuid.UUID, code: str, lon: float, lat: float, elevation=None) -> GcpRecord:
    return GcpRecord(
        gcp_id=str(gcp_id),
        code=code,
        label=code,
        lon=lon,
        lat=lat,
        elevation_m=elevation,
        pixel_col=1043.5,
        pixel_row=822.25,
        satellite_pixel_x=None,
        satellite_pixel_y=None,
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
        landmark_kind=None,
        elevation_source="local_dem" if elevation is not None else None,
    )


def _foreign_kml(body: bytes) -> bytes:
    return (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>My Places</name>'
        + body
        + b"</Document></kml>"
    )


# ── the loop closes ───────────────────────────────────────────────────────────


@sync
async def test_reimporting_an_untouched_export_changes_nothing() -> None:
    """★ THE IDEMPOTENCE GUARANTEE. Export then import with no edits must be a no-op.

    If rounding in the writer leaked through as movement, every round trip would stamp
    ``manually_adjusted`` on every GCP and invent an ``adjustment_offset_m`` — destroying
    the only signal that says a human actually intervened.
    """
    lon, lat = 30.802498, 29.318765
    service, repo = _service((_FakeGcp(GCP1, "GCP01"), lon, lat))
    data = _our_kml(_record(GCP1, "GCP01", lon, lat))

    preview = await service.preview(project_id=PROJECT_ID, data=data, filename="gcps.kml")
    assert len(preview.matched) == 1
    assert preview.matched[0].matched_by == "gcp_id"
    assert preview.moved_count == 0

    applied = await service.apply(
        project_id=PROJECT_ID, data=data, body=KmlImportApplyRequest(), filename="gcps.kml"
    )
    assert applied.adjusted_gcp_ids == []
    assert applied.unchanged_count == 1
    assert repo.adjusted == []


@sync
async def test_a_moved_placemark_adjusts_its_gcp() -> None:
    """The whole point: a refined position comes back and moves the right point."""
    service, repo = _service((_FakeGcp(GCP1, "GCP01"), 30.802498, 29.318765))
    data = _our_kml(_record(GCP1, "GCP01", 30.802600, 29.318800))

    preview = await service.preview(project_id=PROJECT_ID, data=data)
    (match,) = preview.matched
    assert match.gcp_id == GCP1
    assert match.offset_m == pytest.approx(10.4, abs=1.5)
    assert preview.moved_count == 1

    await service.apply(project_id=PROJECT_ID, data=data, body=KmlImportApplyRequest())
    (write,) = repo.adjusted
    assert (write["lon"], write["lat"]) == (pytest.approx(30.802600), pytest.approx(29.318800))


@sync
async def test_a_move_beyond_the_error_bar_is_flagged_but_not_blocked() -> None:
    """Refining past the stated CE90 is legitimate — it just has to be deliberate."""
    service, _ = _service((_FakeGcp(GCP1, "GCP01", accuracy_total_ce90_m=1.83), 30.8, 29.3))
    data = _our_kml(_record(GCP1, "GCP01", 30.8010, 29.3))

    preview = await service.preview(project_id=PROJECT_ID, data=data)
    assert preview.matched[0].exceeds_accuracy is True
    assert preview.exceeds_accuracy_count == 1


@sync
async def test_a_foreign_placemark_matches_on_name() -> None:
    """A file with no ExtendedData still works — matched by the operator's own label."""
    service, _ = _service((_FakeGcp(GCP1, "GCP01", name=None), 36.0, 34.0))
    data = _foreign_kml(
        b"<Placemark><name>GCP01</name><Point>"
        b"<coordinates>36.001,34.001</coordinates></Point></Placemark>"
    )
    preview = await service.preview(project_id=PROJECT_ID, data=data)
    assert preview.matched[0].matched_by == "code"


# ── refusing to guess ─────────────────────────────────────────────────────────


@sync
async def test_an_unmatched_placemark_never_becomes_a_new_gcp() -> None:
    """★ A placemark carries no image pixel, and pixel_x/pixel_y are NOT NULL."""
    service, repo = _service((_FakeGcp(GCP1, "GCP01"), 36.0, 34.0))
    data = _foreign_kml(
        b"<Placemark><name>SOMEWHERE ELSE</name><Point>"
        b"<coordinates>10,20</coordinates></Point></Placemark>"
    )
    preview = await service.preview(project_id=PROJECT_ID, data=data)
    assert preview.matched == []
    assert len(preview.unmatched) == 1
    assert preview.untouched_gcp_count == 1

    applied = await service.apply(project_id=PROJECT_ID, data=data, body=KmlImportApplyRequest())
    assert applied.unmatched_count == 1
    assert repo.adjusted == []


@sync
async def test_an_ambiguous_label_matches_nothing() -> None:
    """Two GCPs sharing a name identify neither; picking one would be a coin flip."""
    service, _ = _service(
        (_FakeGcp(GCP1, None, name="corner"), 36.0, 34.0),
        (_FakeGcp(GCP2, None, name="corner"), 36.1, 34.1),
    )
    data = _foreign_kml(
        b"<Placemark><name>corner</name><Point>"
        b"<coordinates>36.05,34.05</coordinates></Point></Placemark>"
    )
    preview = await service.preview(project_id=PROJECT_ID, data=data)
    assert preview.matched == []
    assert "more than one" in preview.unmatched[0].reason


@sync
async def test_two_placemarks_cannot_both_claim_one_gcp() -> None:
    """The second must be reported, not silently applied over the first."""
    service, _ = _service((_FakeGcp(GCP1, "GCP01"), 36.0, 34.0))
    data = _foreign_kml(
        b"<Placemark><name>GCP01</name><Point><coordinates>36.001,34</coordinates></Point>"
        b"</Placemark>"
        b"<Placemark><name>GCP01</name><Point><coordinates>36.002,34</coordinates></Point>"
        b"</Placemark>"
    )
    preview = await service.preview(project_id=PROJECT_ID, data=data)
    assert len(preview.matched) == 1
    assert "already matched" in preview.unmatched[0].reason


@sync
async def test_a_gcp_id_from_another_project_is_reported() -> None:
    """A file from the wrong project must say so, not fall through to a name match."""
    service, _ = _service((_FakeGcp(GCP1, "GCP01"), 36.0, 34.0))
    data = _our_kml(_record(GCP2, "GCP01", 36.001, 34.0))
    preview = await service.preview(project_id=PROJECT_ID, data=data)
    assert preview.matched == []
    assert "not a GCP in this project" in preview.unmatched[0].reason


@sync
async def test_an_unreadable_file_is_a_validation_error() -> None:
    service, _ = _service((_FakeGcp(GCP1, "GCP01"), 36.0, 34.0))
    with pytest.raises(ValidationError):
        await service.preview(project_id=PROJECT_ID, data=b"<not-kml/>")


@sync
async def test_applying_a_file_that_changed_since_the_preview_is_refused() -> None:
    """★ The preview is the operator's consent, and it was to a specific set of moves."""
    service, repo = _service((_FakeGcp(GCP1, "GCP01"), 36.0, 34.0))
    data = _our_kml(_record(GCP1, "GCP01", 36.001, 34.0))

    with pytest.raises(ImportFileChanged):
        await service.apply(
            project_id=PROJECT_ID,
            data=data,
            body=KmlImportApplyRequest(expected_match_count=7),
        )
    assert repo.adjusted == []


# ── elevation: the honest half ────────────────────────────────────────────────


@sync
async def test_an_imported_altitude_is_manual_with_no_error_bar() -> None:
    """★ We record the height the operator asserted, and refuse to invent its accuracy."""
    service, repo = _service((_FakeGcp(GCP1, "GCP01", elevation_m=None), 36.0, 34.0))
    data = _foreign_kml(
        b"<Placemark><name>GCP01</name><Point><altitudeMode>absolute</altitudeMode>"
        b"<coordinates>36.001,34.0,412.5</coordinates></Point></Placemark>"
    )
    await service.apply(project_id=PROJECT_ID, data=data, body=KmlImportApplyRequest())

    (write,) = repo.elevations
    assert write["elevation_m"] == pytest.approx(412.5)
    assert write["elevation_source"] == "manual"
    assert write["elevation_ce90_m"] is None, "an imported height has no derivable CE90"


@sync
async def test_a_clamped_altitude_is_reported_and_never_written() -> None:
    """``clampToGround`` is a display instruction, not a survey elevation."""
    service, repo = _service((_FakeGcp(GCP1, "GCP01"), 36.0, 34.0))
    data = _foreign_kml(
        b"<Placemark><name>GCP01</name><Point><altitudeMode>clampToGround</altitudeMode>"
        b"<coordinates>36.001,34.0,412.5</coordinates></Point></Placemark>"
    )
    preview = await service.preview(project_id=PROJECT_ID, data=data)
    assert "altitude ignored" in (preview.matched[0].elevation_note or "")

    await service.apply(project_id=PROJECT_ID, data=data, body=KmlImportApplyRequest())
    assert repo.elevations == []


@sync
async def test_apply_elevation_false_moves_the_point_and_leaves_z_alone() -> None:
    """Opting out must still perform the horizontal adjustment."""
    service, repo = _service((_FakeGcp(GCP1, "GCP01"), 36.0, 34.0))
    data = _foreign_kml(
        b"<Placemark><name>GCP01</name><Point><altitudeMode>absolute</altitudeMode>"
        b"<coordinates>36.001,34.0,412.5</coordinates></Point></Placemark>"
    )
    await service.apply(
        project_id=PROJECT_ID, data=data, body=KmlImportApplyRequest(apply_elevation=False)
    )
    assert len(repo.adjusted) == 1
    assert repo.elevations == []


@sync
async def test_the_adjustment_note_names_the_source_file() -> None:
    """Provenance of the move has to survive in the record, not just in someone's memory."""
    service, repo = _service((_FakeGcp(GCP1, "GCP01"), 36.0, 34.0))
    data = _our_kml(_record(GCP1, "GCP01", 36.001, 34.0))
    await service.apply(
        project_id=PROJECT_ID,
        data=data,
        body=KmlImportApplyRequest(),
        filename="refined-2026-07-28.kml",
    )
    assert "refined-2026-07-28.kml" in repo.adjusted[0]["note"]
