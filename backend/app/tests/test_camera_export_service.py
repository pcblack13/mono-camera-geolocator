"""Camera export — the whole of one camera in one downloadable folder (2026-09-12).

★ What these pin: the bundle carries the registry row AND every artefact the setup
steps produced — the frame and the pose solved on it, the control points, the DEM,
the processed DEM calibration, the lookup table and the frozen drift reference —
each in its own lane under one session folder; a camera that is only half set up
still exports, naming in ``camera.json`` exactly which steps had not happened; and
the drift reference is resolved the way the pages resolve it (the desired watch's
own id, else the reference frozen on the same source).
"""

from __future__ import annotations

import json
import zipfile
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from app.core.config import Settings
from app.services import camera_export_service as ce

CAMERA_ID = "11111111-1111-1111-1111-111111111111"
PROJECT_ID = "22222222-2222-2222-2222-222222222222"
IMAGE_ID = "33333333-3333-3333-3333-333333333333"
REF_ID = "a" * 32


class _Mappings:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def first(self) -> dict | None:
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


class _Row(SimpleNamespace):
    """A SQLAlchemy Row answers to both ``row.name`` and ``row[0]`` — so must this."""

    def __getitem__(self, index: int) -> Any:
        return list(self.__dict__.values())[index]


class _Result:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self) -> _Mappings:
        return _Mappings(self._rows)

    def first(self):
        return _Row(**self._rows[0]) if self._rows else None

    def all(self) -> list[Any]:
        return [_Row(**r) for r in self._rows]


class _FakeDb:
    """Answers the export's queries by what the SQL is asking for."""

    def __init__(self, *, camera: dict, image: dict | None, pose: dict | None, gcps: list[dict]) -> None:
        self.camera, self.image, self.pose, self.gcps = camera, image, pose, gcps

    def execute(self, statement: Any, params: dict) -> _Result:  # noqa: ARG002
        sql = str(statement)
        if "FROM cameras" in sql:
            return _Result([self.camera])
        if "FROM image_cameras" in sql:
            return _Result([self.pose] if self.pose else [])
        if "FROM images WHERE id" in sql:
            return _Result([self.image] if self.image else [])
        if "FROM images WHERE project_id" in sql:
            return _Result(
                [{"id": self.image["id"], "filename": self.image["filename"]}] if self.image else []
            )
        if "FROM gcps" in sql:
            return _Result(self.gcps)
        if "FROM projects" in sql:
            return _Result([{"name": "Gate project"}])
        raise AssertionError(f"unexpected query: {sql}")


def _camera_row(**over: Any) -> dict:
    return {
        "id": UUID(CAMERA_ID),
        "name": "Field gate",
        "lat": 34.1,
        "lon": 36.0,
        "source": "http://cam/stream",
        "connection": "lan",
        "provides": "camera",
        "data_source": None,
        "heading_deg": 120.0,
        "fov_deg": 60.0,
        "fps": 10,
        "tags": ["perimeter"],
        "lut_site": "GATE",
        "desired": {"watch": {"ref_id": REF_ID}},
        "project_id": UUID(PROJECT_ID),
        "frame_image_id": UUID(IMAGE_ID),
        "calibration": {"fx": 1200.0, "fy": 1200.0, "mast_offset_m": 6.0},
        "created_at": None,
        "updated_at": None,
        **over,
    }


@pytest.fixture()
def wired(tmp_path, monkeypatch):
    """A settings object whose every artefact directory is populated on disk."""
    from app.db import session as db_session
    from app import storage as storage_mod

    frame = tmp_path / "store" / "frame.jpg"
    frame.parent.mkdir(parents=True)
    frame.write_bytes(b"\xff\xd8jpeg")

    settings = Settings(
        project_dem_dir=tmp_path / "dem",
        accuracy_output_dir=tmp_path / "accuracy",
        lut_output_dir=tmp_path / "lut",
        drift_output_dir=tmp_path / "drift",
    )
    (tmp_path / "dem").mkdir()
    (tmp_path / "dem" / f"{PROJECT_ID}.tif").write_bytes(b"tif")
    (tmp_path / "dem" / f"{PROJECT_ID}.json").write_text('{"vertical_datum": "unknown"}')
    solve = tmp_path / "accuracy" / IMAGE_ID
    solve.mkdir(parents=True)
    (solve / "correction.json").write_text('{"ce90_m": 0.8}')
    bundle = tmp_path / "lut" / "GATE_lut"
    bundle.mkdir(parents=True)
    (bundle / "manifest.json").write_text('{"dem": {"file": "x.tif"}}')
    ref = tmp_path / "drift" / REF_ID
    ref.mkdir(parents=True)
    (ref / "reference.json").write_text('{"n_landmarks": 40}')
    (ref / "reference.jpg").write_bytes(b"\xff\xd8jpeg")

    state: dict[str, Any] = {
        "camera": _camera_row(),
        "image": {
            "id": UUID(IMAGE_ID),
            "filename": "frame.jpg",
            "storage_path": "store/frame.jpg",
            "project_id": UUID(PROJECT_ID),
            "width": 1920,
            "height": 1080,
        },
        "pose": {"fx": 1210.0, "fy": 1210.0, "img_w": 1920, "img_h": 1080, "lat": 34.1, "lon": 36.0},
        "gcps": [
            {
                "code": "G1",
                "name": "pole",
                "source": "manual",
                "pixel_x": 10.0,
                "pixel_y": 20.0,
                "lat": 34.11,
                "lon": 36.01,
                "elevation_m": 700.0,
                "confidence": 0.9,
                "total_ce90_m": 0.7,
                "included_in_export": True,
                "is_stale": False,
            }
        ],
    }

    @contextmanager
    def _sync_session():
        yield _FakeDb(
            camera=state["camera"],
            image=state["image"],
            pose=state["pose"],
            gcps=state["gcps"],
        )

    monkeypatch.setattr(db_session, "sync_session", _sync_session)
    monkeypatch.setattr(
        storage_mod,
        "get_storage",
        lambda: SimpleNamespace(local_path=lambda p: str(tmp_path / p)),
    )
    return SimpleNamespace(settings=settings, state=state, tmp=tmp_path)


def _names(path) -> set[str]:
    with zipfile.ZipFile(path) as zf:
        assert zf.testzip() is None
        return set(zf.namelist())


def _manifest(path) -> dict:
    with zipfile.ZipFile(path) as zf:
        entry = next(n for n in zf.namelist() if n.endswith("camera.json"))
        return json.loads(zf.read(entry))


def test_a_configured_camera_exports_every_step_in_its_own_lane(wired) -> None:
    """★ The whole camera: settings, frame, GCPs, DEM, calibration, LUT, drift."""
    path, filename = ce.export_camera(CAMERA_ID, wired.settings)
    try:
        names = _names(path)
        manifest = _manifest(path)
    finally:
        path.unlink(missing_ok=True)

    stem = filename[: -len(".zip")]
    assert stem.startswith("Field-gate-")
    assert names == {
        f"{stem}/camera.json",
        f"{stem}/README.txt",
        f"{stem}/frame/frame.jpg",
        f"{stem}/frame/frame.json",
        f"{stem}/gcps/gcps.csv",
        f"{stem}/gcps/gcps.geojson",
        f"{stem}/dem/{PROJECT_ID}.tif",
        f"{stem}/dem/{PROJECT_ID}.json",
        f"{stem}/calibration/correction.json",
        f"{stem}/lut/GATE_lut/manifest.json",
        f"{stem}/drift/{REF_ID}/reference.json",
        f"{stem}/drift/{REF_ID}/reference.jpg",
    }
    assert manifest["has"] == {
        "frame": True,
        "gcps": True,
        "dem": True,
        "dem_calibration": True,
        "lut": True,
        "drift_reference": True,
        "camera_calibration": True,
    }
    assert manifest["missing"] == []


def test_the_manifest_carries_the_settings_an_operator_typed(wired) -> None:
    """★ Name, connection, position and calibration — the registry row, whole."""
    path, _ = ce.export_camera(CAMERA_ID, wired.settings)
    try:
        manifest = _manifest(path)
    finally:
        path.unlink(missing_ok=True)

    camera = manifest["camera"]
    assert camera["name"] == "Field gate"
    assert (camera["lat"], camera["lon"]) == (34.1, 36.0)
    assert camera["connection"] == "lan"
    assert camera["source"] == "http://cam/stream"
    assert camera["tags"] == ["perimeter"]
    assert camera["calibration"]["fx"] == 1200.0
    assert manifest["links"]["project_name"] == "Gate project"
    assert manifest["links"]["drift_ref_id"] == REF_ID


def test_a_half_configured_camera_still_exports_and_says_what_is_missing(wired) -> None:
    """★ Setup is eight steps; an operator on step three still gets their camera."""
    wired.state["camera"] = _camera_row(
        project_id=None, frame_image_id=None, lut_site=None, desired={}, calibration=None
    )
    wired.state["image"] = None
    wired.state["pose"] = None
    wired.state["gcps"] = []

    path, filename = ce.export_camera(CAMERA_ID, wired.settings)
    try:
        names = _names(path)
        manifest = _manifest(path)
    finally:
        path.unlink(missing_ok=True)

    stem = filename[: -len(".zip")]
    assert names == {f"{stem}/camera.json", f"{stem}/README.txt"}
    assert manifest["camera"]["name"] == "Field gate"
    assert not any(manifest["has"].values())
    joined = " | ".join(manifest["missing"])
    for step in ("backing project", "captured frame", "control points", "DEM", "lookup table", "drift"):
        assert step in joined, f"{step!r} not named in {joined!r}"


def test_the_drift_reference_is_found_by_source_when_the_row_names_none(wired) -> None:
    """★ Resolved the way the settings and monitoring pages resolve it, or a camera
    whose watch was started from the drift page would export no drift folder."""
    wired.state["camera"] = _camera_row(desired={})

    def _scan(_root):
        return [{"ref_id": REF_ID, "source": "http://cam/stream"}]

    from app.services import drift_service

    original, drift_service.scan_references = drift_service.scan_references, _scan
    try:
        path, _ = ce.export_camera(CAMERA_ID, wired.settings)
    finally:
        drift_service.scan_references = original
    try:
        manifest = _manifest(path)
    finally:
        path.unlink(missing_ok=True)

    assert manifest["links"]["drift_ref_id"] == REF_ID
    assert manifest["has"]["drift_reference"] is True


def test_a_named_but_absent_lut_is_reported_not_silently_dropped(wired) -> None:
    """★ "the bundle is named but not on disk" is a different fact from "no LUT"."""
    wired.state["camera"] = _camera_row(lut_site="GONE")

    path, _ = ce.export_camera(CAMERA_ID, wired.settings)
    try:
        manifest = _manifest(path)
    finally:
        path.unlink(missing_ok=True)

    assert manifest["has"]["lut"] is False
    assert any("'GONE'" in m and "not on disk" in m for m in manifest["missing"])


def test_an_unknown_camera_is_a_refusal_with_a_reason(wired, monkeypatch) -> None:
    from app.db import session as db_session

    @contextmanager
    def _empty():
        yield _FakeDb(camera=None, image=None, pose=None, gcps=[])

    class _NoCamera(_FakeDb):
        def execute(self, statement, params):  # noqa: ARG002
            return _Result([])

    @contextmanager
    def _none():
        yield _NoCamera(camera=None, image=None, pose=None, gcps=[])

    monkeypatch.setattr(db_session, "sync_session", _none)
    with pytest.raises(ce.CameraExportError, match="no such camera"):
        ce.export_camera(CAMERA_ID, wired.settings)


def test_the_folder_name_can_never_escape_its_directory() -> None:
    assert ce._slug("A/B\\C:*?") == "A-B-C"
    assert ce._slug("...") == "camera"
    assert ce._slug("") == "camera"


def test_gcps_without_a_world_coordinate_stay_out_of_the_vectors() -> None:
    """★ A point picked on the picture but not yet placed has no geometry to write.
    It stays in the CSV, which is the complete record."""
    rows = [
        {"image": "f.jpg", "code": "A", "lon": 36.0, "lat": 34.0},
        {"image": "f.jpg", "code": "B", "lon": None, "lat": None},
    ]
    fc = ce._gcps_geojson(rows)
    assert [f["properties"]["code"] for f in fc["features"]] == ["A"]
    assert fc["features"][0]["geometry"]["coordinates"] == [36.0, 34.0]


# ── the SQL is checked against the real schema, not against a fake (2026-09-12) ──


def _selected_columns(sql: str) -> set[str]:
    """The bare column names a SELECT reads — aliases, functions and params removed."""
    import re

    body = sql[sql.index("SELECT") + 6 : sql.index(" FROM ")]
    names: set[str] = set()
    for part in body.split(","):
        piece = part.strip()
        if not piece or "(" in piece:  # ST_Y(geom::geometry) AS lat — not a bare column
            continue
        names.add(piece.split(" AS ")[0].strip())
    return names


def _sql_literals(fn: Any) -> list[str]:
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    return [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and "SELECT" in n.value
    ]


def test_every_column_the_export_reads_exists_on_the_real_tables() -> None:
    """★ THE FAKE DB CANNOT CATCH A MISSPELLED COLUMN — it answers any query.

    The first version of this export asked ``gcps`` for ``included_in_export``;
    the real column is ``is_included_in_export``, so every configured camera's
    download failed with a 500 while the suite stayed green. This reads the SQL
    out of the service and checks it against the mapped tables themselves.
    """
    from app.models.camera import Camera
    from app.models.gcp import GCP
    from app.models.image import Image
    from app.models.image_camera import ImageCamera

    tables = {
        "cameras": Camera,
        "images": Image,
        "gcps": GCP,
        "image_cameras": ImageCamera,
    }
    checked = 0
    for fn in (ce._read_camera, ce._read_frame, ce._read_gcps):
        for sql in _sql_literals(fn):
            table = sql.split(" FROM ")[1].split()[0]
            if table not in tables:  # projects is read for its name only
                continue
            real = {c.name for c in tables[table].__table__.columns}
            unknown = _selected_columns(sql) - real
            assert not unknown, f"{table} has no column(s) {sorted(unknown)}"
            checked += 1
    assert checked >= 3, "the SQL should have been found and checked"
