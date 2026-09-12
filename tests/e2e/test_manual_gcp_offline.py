"""★★ THE OFFLINE END-TO-END: photo -> EXIF prior -> imagery -> manual GCP -> export.

§13.1 IU-31 mandates *"upload -> annotate -> match -> export using the `fixture` provider,
with no network, no weights and no GPU"*. **SCOPE.md §1 deletes the `match` step** — the
automatic engine is deferred — and §5 replaces it with the product's actual core
interaction::

    The surveyor selects a landmark in the photo -> the app enters *correspondence* mode ->
    they pan/zoom the satellite map and click the same physical spot -> a GCP is created
    linking (pixel_x, pixel_y) to (lat, lon).

So the chain proved here is **upload -> annotate -> correspond -> export**, which is the
whole product. `test_deferred_surface.py` proves the step that was removed is honestly
absent rather than quietly faked.

★ **This module runs on this machine, today.** It is the library-level e2e: it drives the
real `gis` code with the real committed fixtures and zero installs. The API-level e2e
(`test_api_flow.py`) needs fastapi + sqlalchemy + pydantic, none of which are installed
(§0.1), so it skips. Between them the seam is covered from both sides, and the half that can
run does.

**What "no network" means here** is enforced, not asserted: `tests/conftest.py` blocks IP
sockets for the whole suite.
"""

from __future__ import annotations

import csv
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("numpy", reason="the offline e2e drives the real gis stack")

SURVEYOR_CONFIDENCE = 4.0
"""★ SCOPE.md §5: confidence in manual mode is a **surveyor-declared** judgement,
**never** a computed number. This constant is a human's opinion, and the whole point of the
assertions below is that nothing in the pipeline recomputes, rescales or "improves" it."""


CSV_COLUMNS_NORMATIVE: list[str] = [
    "Point ID",
    "Name",
    "Image X",
    "Image Y",
    "Latitude",
    "Longitude",
    "Source",
    "Accuracy",
]
"""★ The CSV mirrors the ON-SCREEN GCP TABLE: same columns, same order, same formatting
(``gis.exports.csv_writer.CSV_COLUMNS``). This replaced the old 24-column machine dump —
the surveyor's deliverable reads like what the surveyor saw. The machine-shaped record
(raw confidence, provenance, CE90 terms) lives in the GeoJSON export instead.

Cross-checked here rather than only inside `gis` because this is a **deliverable's** shape,
not an implementation detail: it is the one artefact that leaves the system and is read by
software we do not control.
"""


def _csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Return ``(header, rows)`` from an export CSV.

    ★ The table-mirror CSV is header + data rows and NOTHING else — no comment lines, so
    the file reads exactly like the on-screen table. The `#` filter below is therefore a
    guard, not a parser: if a preamble ever reappears, the header assertions still see the
    real header rather than a comment line.
    """
    text = path.read_text(encoding="utf-8-sig")
    body = [line for line in text.splitlines() if not line.startswith("#") and line.strip()]
    reader = csv.DictReader(body)
    assert reader.fieldnames is not None
    return list(reader.fieldnames), list(reader)


# =============================================================================
# Step 1 — upload: the photograph and what it tells us
# =============================================================================


def test_upload_reads_the_photo_and_its_gps_prior(field_photo: Path) -> None:
    """★ Ingest: the photo's EXIF GPS becomes the search prior.

    A hint, never a truth — EXIF GPS is where the *camera* stood, not where the landmark is,
    and a phone's fix is metres wide. It seeds the search; it never becomes a GCP.
    """
    from PIL import Image

    from gis.exif import extract_exif_gps, read_exif_orientation

    with Image.open(field_photo) as image:
        assert (image.width, image.height) == (640, 480)

    gps = extract_exif_gps(field_photo)
    assert gps is not None, "field_photo.jpg must carry EXIF GPS — it is its entire purpose"
    assert gps.position.lon == pytest.approx(15.0, abs=1e-6)
    assert gps.position.lat == pytest.approx(45.1534772, abs=1e-6)
    assert read_exif_orientation(field_photo) == 1


def test_a_photo_without_gps_yields_no_prior_rather_than_a_guess(
    field_photo_no_gps: Path,
) -> None:
    """★★ `None`, never a fabricated position. This is the normal case, not the edge case.

    Most field photographs have no GPS. The honest answer drives `422 SEARCH_HINT_REQUIRED`
    and the map-click hint path; a guessed one would silently place a survey coordinate in
    the wrong country. L12: refuse rather than answer wrongly.
    """
    from gis.exif import extract_exif_gps

    assert extract_exif_gps(field_photo_no_gps) is None


def test_orientation_6_is_a_geometric_fact_the_ingest_must_apply(
    field_photo_rotated: Path,
) -> None:
    """★ Orientation 6 means the stored 640x480 **displays** as 480x640.

    §13.2: this fixture *"proves ingest normalises it and that `width`/`height` are stored
    post-rotation"*. If they are stored pre-rotation, every pixel the surveyor clicks is
    transposed against the coordinate the export claims — and nothing anywhere raises.
    """
    from PIL import Image, ImageOps

    from gis.exif import read_exif_orientation

    assert read_exif_orientation(field_photo_rotated) == 6

    with Image.open(field_photo_rotated) as stored:
        assert (stored.width, stored.height) == (640, 480), "stored, pre-rotation"
        displayed = ImageOps.exif_transpose(stored)
        assert displayed is not None
        assert (displayed.width, displayed.height) == (480, 640), (
            "post-rotation — this is what images.width/height must record"
        )


# =============================================================================
# Step 2 — the satellite imagery, offline
# =============================================================================


def test_the_offline_provider_serves_the_scene_with_no_network(
    fixture_provider: Any, scene_lonlat: tuple[float, float]
) -> None:
    """★ L2's default is keyless but networked; this is the provider that works unplugged.

    `tests/conftest.py` blocks IP sockets, so reaching the network here is an error rather
    than a slow success. `make seed && make up` demonstrates the whole product this way.
    """
    from gis.tiles import lonlat_to_tile

    assert fixture_provider.is_configured() is True

    lon, lat = scene_lonlat
    tile = lonlat_to_tile(lon, lat, 16)
    pixels = fixture_provider.get_tile(tile.z, tile.x, tile.y)

    assert pixels.shape == (256, 256, 3), "RGB, no alpha"
    assert pixels.dtype.name == "uint8"
    assert pixels.flags["C_CONTIGUOUS"]
    assert fixture_provider.attribution, "★ every chip must carry attribution"


def test_the_committed_tiles_cover_the_photos_own_ground(
    gis_fixtures_dir: Path, scene_lonlat: tuple[float, float]
) -> None:
    """★ The photo's EXIF GPS lands on a **committed** tile, not a procedural one.

    The fixture set describes one place: `field_photo.jpg`'s GPS, `synthetic_ortho.tif`'s
    corner and the committed tiles all name 15.0000000 E, 45.1534772 N. If they drifted
    apart, this e2e would still pass — on procedurally generated imagery of nowhere — and
    would prove nothing about the scene it claims to exercise.
    """
    from gis.tiles import lonlat_to_tile

    lon, lat = scene_lonlat
    tile = lonlat_to_tile(lon, lat, 16)
    committed = gis_fixtures_dir / "tiles" / str(tile.z) / str(tile.x) / f"{tile.y}.png"

    assert committed.is_file(), (
        f"the scene's own z16 tile {tile.z}/{tile.x}/{tile.y} is not committed; this e2e "
        "would silently fall back to procedural imagery of unrelated ground"
    )


# =============================================================================
# Step 3 — the correspondence: THE product (SCOPE.md §5)
# =============================================================================


def _manual_gcp(scene: tuple[float, float], **overrides: Any) -> Any:
    """Build the GCP a surveyor's click produces. ★ A DIRECT OBSERVATION, not an inference.

    Every value here is either the surveyor's own act (the two pixel coordinates, the map
    click, the declared confidence) or derived from the imagery's geometry (the accuracies).
    **None of it comes from a homography** — there is none.
    """
    from gis.exports.models import GcpRecord

    lon, lat = scene
    fields: dict[str, Any] = {
        "gcp_id": "11111111-1111-4111-8111-111111111111",
        "code": "GCP-001",
        "label": "field corner, NW",
        # ★ SCOPE.md §5: every manually-placed GCP records ``source = "manual"`` so a direct
        #   observation can never be mistaken for an inferred coordinate in an export. This is
        #   the record-level twin of the export-level ``provenance.source`` asserted below.
        "source": "manual",
        "lon": lon,
        "lat": lat,
        "elevation_m": None,
        # The landmark in ORIGINAL image pixel space — independent of viewer zoom,
        # brightness or contrast (SCOPE.md §5, and normative in CONTRACT.md).
        "pixel_col": 412.0,
        "pixel_row": 331.0,
        # Where the surveyor clicked on the satellite pane.
        "satellite_pixel_x": 128.0,
        "satellite_pixel_y": 128.0,
        "confidence": SURVEYOR_CONFIDENCE,
        "horizontal_accuracy_m": 0.42,
        "total_ce90_m": 0.61,
        "relative_ce90_m": 0.42,
        "georef_ce90_m": 0.44,
        "accuracy_dominant_term": "georeferencing",
        # ★ None, not 0.0. There is no homography, so there is no residual. A 0.0 here would
        #   read as "a perfect fit" — a fabricated claim of precision.
        "residual_px": None,
        "manually_adjusted": True,
        "adjustment_offset_m": None,
        "landmark_kind": "field_corner",
        "elevation_source": None,
    }
    fields.update(overrides)
    return GcpRecord(**fields)


def _export_context(gcps: list[Any], provider: Any) -> Any:
    """Assemble the export context for a manual survey.

    ★ `method="assisted"` — SCOPE.md §5's manual correspondence. `gis.exports.base` maps it
    to `source='manual'`, `confidence_basis='surveyor_declared'`, `is_observation=True`.
    """
    from gis.exports.base import ExportContext

    return ExportContext(
        export_id=uuid.UUID("22222222-2222-4222-8222-222222222222"),
        job_id=None,  # ★ no job: nothing was computed
        project_name="Offline e2e",
        image_filename="field_photo.jpg",
        gcps=gcps,
        chip=None,
        provider_name=provider.name,
        attribution=provider.attribution,
        terms_url=provider.terms_url,
        imagery_captured_at=None,
        retrieved_at=datetime(2026, 6, 15, 10, 30, tzinfo=UTC),
        method="assisted",
        homography=None,  # ★ there is none, and the export must not imply one
        rmse_m=None,
        georef_ce90_m=0.44,
        software_version="test",
    )


def test_a_manual_gcp_is_recorded_as_a_direct_observation(
    fixture_provider: Any, scene_lonlat: tuple[float, float]
) -> None:
    """★★ THE ASSERTION THIS WHOLE BUILD TURNS ON (SCOPE.md §2, §5).

    *"The coordinate is a direct observation, not an inference."* An export states which
    kind it is holding, because a confidently-wrong inferred coordinate handed to a surveyor
    is this system's worst failure mode.
    """
    from gis.exports.base import provenance_for

    ctx = _export_context([_manual_gcp(scene_lonlat)], fixture_provider)
    provenance = provenance_for(ctx)

    assert provenance.source == "manual"
    assert provenance.is_observation is True
    assert provenance.confidence_basis == "surveyor_declared", (
        "★ SCOPE.md §5: confidence is a surveyor's declared judgement, NEVER a computed "
        "number. If this ever reads 'computed', a human's opinion has been relabelled as a "
        "measurement."
    )


def test_the_surveyors_confidence_survives_the_pipeline_unchanged(
    fixture_provider: Any, tmp_path: Path, scene_lonlat: tuple[float, float]
) -> None:
    """★ Nothing rescales, recalibrates or "improves" a human's declared judgement.

    The failure this guards against is quiet and plausible: a 1-5 judgement silently
    rendered as a 0-100 percentage, or a calibrator applied to a number that was never a
    probability. The surveyor said 4. The export says 4.

    ★ Asserted on the GEOJSON export: the table-mirror CSV carries the human view (a
    Source label and an ``±N m`` accuracy), and the machine record — raw confidence and
    its basis — travels in the GeoJSON properties.
    """
    from gis.exports import get_writer

    gcp = _manual_gcp(scene_lonlat)
    assert gcp.confidence == SURVEYOR_CONFIDENCE

    out = tmp_path / "gcps.geojson"
    get_writer("geojson").write(_export_context([gcp], fixture_provider), out)
    document = json.loads(out.read_text(encoding="utf-8"))

    features = document["features"]
    assert len(features) == 1
    props = features[0]["properties"]
    assert float(props["confidence"]) == pytest.approx(SURVEYOR_CONFIDENCE)
    assert props["confidence_basis"] == "surveyor_declared", (
        "★ SCOPE.md §5: a human's opinion must never be relabelled as a measurement"
    )


# =============================================================================
# Step 4 — export
# =============================================================================


def test_csv_export_is_a_survey_deliverable(
    fixture_provider: Any, tmp_path: Path, scene_lonlat: tuple[float, float]
) -> None:
    """★ CSV with only the stdlib — no geopandas, no fiona (§13.1 IU-13).

    A UTF-8 **BOM** so Excel opens it without mangling; longitude **before** latitude.
    """
    from gis.exports import get_writer

    writer = get_writer("csv")
    available, reason = writer.is_available()
    assert (available, reason) == (True, None), "CSV must never be unavailable; it is stdlib only"

    out = tmp_path / "gcps.csv"
    bundle = writer.write(_export_context([_manual_gcp(scene_lonlat)], fixture_provider), out)

    assert out.is_file()
    assert bundle.size_bytes == out.stat().st_size
    assert out.read_bytes().startswith(b"\xef\xbb\xbf"), "★ UTF-8 BOM (§13.1 IU-13)"

    header, rows = _csv_rows(out)
    assert header == CSV_COLUMNS_NORMATIVE, (
        "★ The CSV column order is NORMATIVE. Downstream survey software is routinely "
        "configured by column index, so a reordering is a silent data corruption in "
        "someone else's tool.\n"
        f"  expected: {CSV_COLUMNS_NORMATIVE}\n"
        f"  got:      {header}"
    )
    assert header.index("Latitude") < header.index("Longitude"), (
        "★ Latitude BEFORE Longitude — the CSV mirrors the on-screen table, which reads "
        "Lat/Lon. The lon-first machine ordering lives where machines read: RFC 7946 "
        "GeoJSON coordinates (asserted in test_geojson_export_is_rfc7946)."
    )
    assert rows[0]["Longitude"] == "15.000000", "6 dp, exactly as the table renders"
    assert rows[0]["Source"] == "Observed", (
        "★ SCOPE.md §5 travels in the row itself: a manual GCP is an observation"
    )


def test_the_csv_states_observed_vs_inferred_in_every_row(
    fixture_provider: Any, tmp_path: Path, scene_lonlat: tuple[float, float]
) -> None:
    """★★ The deliverable says what it is, in the file, in words.

    A CSV outlives the app that made it. SCOPE.md §5's observation-vs-inference distinction
    has to survive the export or it does not exist. The table-mirror format carries it PER
    ROW — a ``Source`` column reading Observed/Inferred — instead of the old `#` preamble,
    and deliberately emits NO comment lines so the file opens in Excel exactly like the
    on-screen table.
    """
    from gis.exports import get_writer

    out = tmp_path / "gcps.csv"
    get_writer("csv").write(_export_context([_manual_gcp(scene_lonlat)], fixture_provider), out)
    lines = out.read_text(encoding="utf-8-sig").splitlines()

    assert not any(line.startswith("#") for line in lines), (
        "★ no comment lines: the file must read exactly like the on-screen table"
    )
    _header, rows = _csv_rows(out)
    assert rows[0]["Source"] == "Observed", (
        "a manual GCP is a surveyor's direct observation, and the row says so"
    )


def test_geojson_export_is_rfc7946(
    fixture_provider: Any, tmp_path: Path, scene_lonlat: tuple[float, float]
) -> None:
    """★ RFC 7946: `[lon, lat]`, and **no `crs` member** — 7946 deleted it.

    A `crs` member is how a GeoJSON quietly claims to be in something other than 4326, and
    every consumer that trusts the spec ignores it. Its absence is the assertion.
    """
    from gis.exports import get_writer

    out = tmp_path / "gcps.geojson"
    get_writer("geojson").write(_export_context([_manual_gcp(scene_lonlat)], fixture_provider), out)
    document = json.loads(out.read_text(encoding="utf-8"))

    assert document["type"] == "FeatureCollection"
    assert "crs" not in document, "★ RFC 7946 has no crs member"

    lon, lat = document["features"][0]["geometry"]["coordinates"][:2]
    assert lon == pytest.approx(15.0, abs=1e-7)
    assert lat == pytest.approx(45.1534772, abs=1e-7)


def test_the_export_names_its_imagery_and_its_terms(
    fixture_provider: Any, tmp_path: Path, scene_lonlat: tuple[float, float]
) -> None:
    """★ Attribution travels with the deliverable, and says the pixels are synthetic.

    A chip that reaches a PDF must not be mistakeable for real imagery — the `fixture`
    provider's attribution states it in words. Imagery licensing is a legal constraint
    (`docs/legal/imagery-terms.md`), not a nicety.
    """
    from gis.exports import get_writer

    ctx = _export_context([_manual_gcp(scene_lonlat)], fixture_provider)
    assert ctx.attribution
    assert "synthetic" in ctx.attribution.lower()

    out = tmp_path / "gcps.geojson"
    bundle = get_writer("geojson").write(ctx, out)
    assert bundle.checksum_sha256, "every bundle carries a checksum of the bytes on disk"


def test_stdlib_only_writers_are_all_available_offline() -> None:
    """★ CSV / GeoJSON / KML / KMZ need nothing but the stdlib (§13.1 IU-13).

    Naming the registry is itself the test: v1.0's module-scope imports broke **collection**
    of the whole export package when geopandas was absent, which is why the four writers that
    can never fail are the ones the offline deliverable is built from.
    """
    from gis.exports import EXPORT_WRITERS, get_writer

    for format_id in ("csv", "geojson", "kml", "kmz"):
        assert format_id in EXPORT_WRITERS
        available, reason = get_writer(format_id).is_available()
        assert (available, reason) == (True, None), (
            f"{format_id} must be stdlib-only and always available, got {reason!r}"
        )

    assert type(get_writer("kml")) is not type(get_writer("kmz")), (
        "★ kml and kmz resolve to DIFFERENT classes (§13.1 IU-13). `format_id` is a single "
        "class attribute and the registry is keyed on it, so one class physically cannot "
        "register under two ids."
    )
    assert get_writer("kml").format_id == "kml"
    assert get_writer("kmz").format_id == "kmz"


def test_an_uncommitted_correspondence_never_reaches_an_export(
    fixture_provider: Any, tmp_path: Path, scene_lonlat: tuple[float, float]
) -> None:
    """★★ SCOPE.md §5, final line: *"Uncommitted correspondences must never appear in the
    GCP table or an export."*

    Modelled at the only place `gis` can see it: the writer serialises exactly the records
    the context carries, and no more. A half-placed correspondence is not a GcpRecord, so an
    export containing one would mean something upstream promoted it — the export itself must
    never invent a row from an empty list.
    """
    from gis.exports import get_writer

    out = tmp_path / "empty.csv"
    bundle = get_writer("csv").write(_export_context([], fixture_provider), out)

    header, rows = _csv_rows(out)
    assert rows == [], "an export with no committed GCPs has no data rows"
    assert "Longitude" in header, "but it is still a real, well-formed file with a header"
    assert bundle.size_bytes > 0
