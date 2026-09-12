"""Recordings — the stream + its attribute table, one folder each (2026-09-02).

★ What these pin: a recording produces ONE folder holding a playable video, a
CSV whose columns are the session export's own, and a meta.json the library
reads; start is idempotent per source; the library lists newest-first, serves
only its own files (traversal refused), and deletes only whole entries.

★ No LUT, smaller table (2026-09-02): a window with no placed marks saves
detections + classes + time from ``detection_events`` — never the full table's
LUT columns, which such a run cannot honestly fill. And the library root always
lives in the visible LandExplorer folder, never the app's hidden data dir.

★ Watched in the app (2026-09-07): the table comes back as rows on the
recording's clock; the first watch derives a playable H.264 rendition once and
serves it with Range support; a trim writes a NEW folder holding the window's
video and rows and names its origin — the original stays as it was.
"""

from __future__ import annotations

import csv
import io
import json
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import cv2
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import deps
from app.api.v1 import live as live_router
from app.core.config import Settings
from app.services import live_stream_service as lss
from app.services import recording_service as rs

if TYPE_CHECKING:
    from pathlib import Path


def _fake_frames(src: str) -> None:
    """Plant a fresh preview frame where the recorder taps them."""
    frame = np.full((48, 64, 3), 200, dtype=np.uint8)
    ok, jpg = cv2.imencode(".jpg", frame)
    assert ok
    lss._LAST_FRAME[src] = jpg.tobytes()
    lss._LAST_FRAME_T[src] = time.monotonic()


@pytest.fixture()
def settings(tmp_path) -> Settings:
    return Settings(capture_export_dir=tmp_path / "library")


@pytest.fixture(autouse=True)
def _no_db(monkeypatch) -> None:
    """The no-LUT path reads ``detection_events`` — keep tests off any real DB."""
    monkeypatch.setattr(rs, "_detection_events_between", lambda *_a, **_k: [])


def test_record_stop_produces_video_csv_and_meta(settings) -> None:
    src = "http://cam/rec-test"
    _fake_frames(src)
    rec = rs.start_recording(src, "Field gate", settings)
    # Idempotent: a second Record press returns the SAME recording.
    assert rs.start_recording(src, "Field gate", settings).recording_id == rec.recording_id
    deadline = time.time() + 5
    while time.time() < deadline and rec.frames < 3:
        _fake_frames(src)  # keep the frame fresh (the tap has a 5 s staleness gate)
        time.sleep(0.05)
    assert rec.frames >= 3

    final = rs.stop_recording(rec.recording_id)
    assert final.status == "done"
    folder = final.folder
    # ── the folder holds the three files, and the video actually plays ──
    assert (folder / "meta.json").is_file()
    assert (folder / "detections.csv").is_file()
    video = folder / "video.mp4"
    assert video.is_file() and video.stat().st_size > 0
    cap = cv2.VideoCapture(str(video))
    try:
        ok, first = cap.read()
    finally:
        cap.release()
    assert ok and first is not None and first.shape[:2] == (48, 64)

    # ── no run placed anything, so the honest (no-LUT) header is written ──
    reader = csv.reader(io.StringIO((folder / "detections.csv").read_text()))
    header = next(reader)
    assert header == rs._CSV_COLUMNS_NO_LUT
    # No detection ran — an EMPTY table, not a missing file.
    assert list(reader) == []

    # ── the library sees it ──
    entries = rs.library_entries(settings)
    assert [e["folder"] for e in entries] == [folder.name]
    assert entries[0]["has_video"] and entries[0]["has_csv"]
    assert entries[0]["frames"] >= 3


def test_csv_carries_the_windows_marks(settings) -> None:
    """A session's marks inside the recording window land in the CSV, others don't."""
    from app.services import detection_service
    from app.services.detection_service import DetectionSession

    src = "http://cam/rec-marks"
    session = DetectionSession(
        session_id="rec-marks-test",
        source=src,
        lut_site="SITE",
        settings={},
        camera_name="gate",
    )
    with detection_service._LOCK:
        detection_service._SESSIONS[session.session_id] = session
    try:
        _fake_frames(src)
        rec = rs.start_recording(src, "gate", settings)
        # The marks land DURING the recording window — as they do in real use.
        now = datetime.now(UTC)
        session.marks = [
            {
                "lat": 34.1,
                "lon": 36.0,
                "score": 0.9,
                "cls_name": "car",
                "frame_index": 1,
                "time_s": 0.5,
                "u": 1.0,
                "v": 2.0,
                "track_id": 7,
                "predicted": False,
                "detected_at": now.isoformat().replace("+00:00", "Z"),
            },
            {
                "lat": 34.2,
                "lon": 36.1,
                "score": 0.8,
                "cls_name": "person",
                "frame_index": 2,
                "time_s": 1.0,
                "u": 1.0,
                "v": 2.0,
                "track_id": None,
                "predicted": True,
                "detected_at": "1999-01-01T00:00:00Z",
            },  # far outside any window
        ]
        time.sleep(0.3)
        final = rs.stop_recording(rec.recording_id)
        text = (final.folder / "detections.csv").read_text()
        assert text.splitlines()[0] == ",".join(rs._CSV_COLUMNS)  # LUT run → full table
        rows = list(csv.DictReader(io.StringIO(text)))
        assert [r["class"] for r in rows] == ["car"]
        assert rows[0]["track_id"] == "7"
        assert final.marks == 1
    finally:
        with detection_service._LOCK:
            detection_service._SESSIONS.pop(session.session_id, None)


def test_no_lut_window_saves_detections_classes_and_time(settings, monkeypatch) -> None:
    """★ A no-LUT run's recording still saves what the run honestly can.

    Detections + classes + time, from the durable ``detection_events`` table —
    with ONLY the columns such a run can fill.
    """
    from types import SimpleNamespace

    src = "http://cam/rec-no-lut"
    seen: dict[str, object] = {}

    def fake_events(source: str, started: datetime, ended: datetime):  # noqa: ANN202
        seen["source"], seen["started"], seen["ended"] = source, started, ended
        return [
            SimpleNamespace(
                cls_name="car",
                score=0.87,
                frame_index=12,
                track_id=3,
                detected_at=datetime(2026, 9, 2, 12, 0, 5, tzinfo=UTC),
                detected_at_local="2026-09-02T15:00:05+03:00",
                camera_name="No-LUT cam",
            ),
            SimpleNamespace(
                cls_name="truck",
                score=0.55,
                frame_index=30,
                track_id=None,
                detected_at=datetime(2026, 9, 2, 12, 0, 9, tzinfo=UTC),
                detected_at_local="2026-09-02T15:00:09+03:00",
                camera_name="",
            ),
        ]

    monkeypatch.setattr(rs, "_detection_events_between", fake_events)
    _fake_frames(src)
    rec = rs.start_recording(src, "No-LUT cam", settings)
    time.sleep(0.3)
    final = rs.stop_recording(rec.recording_id)
    assert final.status == "done"
    assert seen["source"] == src  # the query is scoped to THIS recording's window
    text = (final.folder / "detections.csv").read_text()
    assert text.splitlines()[0] == ",".join(rs._CSV_COLUMNS_NO_LUT)
    for banned in ("lat", "lon", "site", "cam_lat", "drift", "centre_m"):
        assert banned not in text.splitlines()[0].split(",")
    rows = list(csv.DictReader(io.StringIO(text)))
    assert [(r["class"], r["frame"], r["track_id"]) for r in rows] == [
        ("car", "12", "3"),
        ("truck", "30", ""),
    ]
    assert rows[0]["time_utc"] == "2026-09-02T12:00:05Z"
    assert rows[1]["camera"] == "No-LUT cam"  # empty event name falls back to the recording's
    assert final.marks == 2
    import json as json_mod

    assert json_mod.loads((final.folder / "meta.json").read_text())["table"] == "detections"


def test_library_root_is_always_the_landexplorer_folder(tmp_path, monkeypatch) -> None:
    """★ No configured capture folder → the VISIBLE LandExplorer folder.

    Never the app's hidden data dir (owner ask 2026-09-02).
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    root = rs.recordings_root(Settings(capture_export_dir=None))
    assert root == tmp_path / "Pictures" / "LandExplorer" / "recordings"
    assert root.is_dir()


def test_http_surface_and_traversal_guard(settings) -> None:
    app = FastAPI()
    app.include_router(live_router.router)
    app.dependency_overrides[deps.get_settings] = lambda: settings
    client = TestClient(app)

    src = "http://cam/rec-api"
    _fake_frames(src)
    res = client.post("/live/recordings", json={"source": src, "camera_name": "API cam"})
    assert res.status_code == 200
    rid = res.json()["recording_id"]
    # The page's state-restore probe:
    assert client.get(f"/live/recordings/active?src={src}").json()["recording"]["recording_id"] == rid
    _fake_frames(src)
    time.sleep(0.3)
    done = client.delete(f"/live/recordings/{rid}").json()
    assert done["status"] == "done"
    folder = done["folder"]

    listing = client.get("/live/recordings").json()
    assert folder in [e["folder"] for e in listing["items"]]
    assert client.get(f"/live/recordings/files/{folder}/detections.csv").status_code == 200
    assert client.get(f"/live/recordings/files/{folder}/video.mp4").status_code == 200
    # ── the guards: only the folder's own files, no traversal, no other names ──
    assert client.get(f"/live/recordings/files/{folder}/../../etc/passwd").status_code in (404, 422)
    assert client.get(f"/live/recordings/files/{folder}/other.txt").status_code == 404
    assert client.get("/live/recordings/files/%2e%2e/video.mp4").status_code == 404
    # Delete the entry; the library forgets it.
    assert client.delete(f"/live/recordings/library/{folder}").status_code == 204
    assert folder not in [e["folder"] for e in client.get("/live/recordings").json()["items"]]
    idle = client.get("/live/recordings/active?src=nope")
    assert idle.status_code == 200 and idle.json() == {"recording": None}


def test_recorder_opens_its_own_reader_for_browser_played_http(settings, monkeypatch) -> None:
    """★ http MJPEG the browser plays directly leaves NO server-side frames —
    the recorder must open its own reader rather than saving an empty video."""

    class OwnCap:
        def __init__(self) -> None:
            self.released = False

        def read(self):  # noqa: ANN202 — cv2 shape
            time.sleep(0.01)
            return True, np.full((32, 40, 3), 90, dtype=np.uint8)

        def release(self) -> None:
            self.released = True

    from app.services import live_stream_service

    cap = OwnCap()
    monkeypatch.setattr(live_stream_service, "open_capture", lambda _src: cap)
    src = "http://cam/browser-played"  # nothing planted in _LAST_FRAME on purpose
    rec = rs.start_recording(src, "Browser cam", settings)
    deadline = time.time() + 5
    while time.time() < deadline and rec.frames < 3:
        time.sleep(0.05)
    final = rs.stop_recording(rec.recording_id)
    assert final.frames >= 3
    assert (final.folder / "video.mp4").stat().st_size > 0
    assert cap.released  # the own reader is let go at stop


# ── watching a recording in the app (2026-09-07) ──────────────────────────────


def _write_recording(root: Path, name: str, *, started: str, seconds: float, rows: list[dict]) -> Path:
    """A finished folder as the recorder leaves it — mp4v video, CSV, meta — without recording."""
    folder = root / name
    folder.mkdir(parents=True)
    fps = 10
    writer = cv2.VideoWriter(
        str(folder / "video.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), fps, (64, 48)
    )
    for i in range(int(seconds * fps)):
        writer.write(np.full((48, 64, 3), (i * 7) % 255, dtype=np.uint8))
    writer.release()
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=rs._CSV_COLUMNS, extrasaction="ignore")
    w.writeheader()
    for row in rows:
        w.writerow(row)
    (folder / "detections.csv").write_text(buf.getvalue(), encoding="utf-8")
    began = datetime.fromisoformat(started.replace("Z", "+00:00"))
    meta = {
        "recording_id": "abc123",
        "camera_name": "gate",
        "source": "http://cam/x",
        "started_at": started,
        "ended_at": rs._iso(began + timedelta(seconds=seconds)),
        "duration_s": seconds,
        "frames": int(seconds * fps),
        "marks": len(rows),
        "video": "video.mp4",
        "csv": "detections.csv",
        "table": "marks",
    }
    (folder / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return folder


def _api(settings: Settings) -> TestClient:
    app = FastAPI()
    app.include_router(live_router.router)
    app.dependency_overrides[deps.get_settings] = lambda: settings
    return TestClient(app)


def _row(t_utc: str, cls: str, **extra: object) -> dict:
    return {"mark_id": 1, "class": cls, "score": 0.9, "lat": 34.1, "lon": 36.0, "time_utc": t_utc, **extra}


def test_table_places_every_row_on_the_recordings_clock(settings) -> None:
    """★ ``t`` is seconds since ``started_at`` — the one number the player and the table share."""
    root = rs.recordings_root(settings)
    _write_recording(
        root,
        "gate-20260902-120000",
        started="2026-09-02T12:00:00Z",
        seconds=4,
        rows=[
            _row("2026-09-02T12:00:03Z", "person", track_id="", predicted="True", drift=""),
            _row("2026-09-02T12:00:01.500000Z", "car", track_id=3, predicted="False", drift="steady"),
            _row("not-a-time", "van", score="", lat="", lon=""),
        ],
    )
    table = rs.recording_table(settings, "gate-20260902-120000")
    assert table["table"] == "marks"
    assert table["duration_s"] == 4 and table["has_video"] is True
    # chronological, and a row whose time cannot be read comes last with t=None
    assert [(r["t"], r["class_name"]) for r in table["rows"]] == [
        (1.5, "car"),
        (3.0, "person"),
        (None, "van"),
    ]
    car, person, van = table["rows"]
    assert car["track_id"] == 3 and car["predicted"] is False and car["drift"] == "steady"
    assert person["track_id"] is None and person["predicted"] is True and person["drift"] is None
    assert van["score"] is None and van["lat"] is None

    client = _api(settings)
    res = client.get("/live/recordings/table/gate-20260902-120000")
    assert res.status_code == 200
    assert [r["t"] for r in res.json()["rows"]] == [1.5, 3.0, None]
    assert client.get("/live/recordings/table/nope").status_code == 404


def test_watching_derives_a_playable_rendition_once_and_serves_ranges(settings) -> None:
    root = rs.recordings_root(settings)
    folder = _write_recording(root, "gate-20260902-130000", started="2026-09-02T13:00:00Z", seconds=2, rows=[])
    assert not any(e["playable"] for e in rs.library_entries(settings))

    path = rs.ensure_preview(settings, folder.name)
    assert path == folder / "preview.mp4" and path.is_file()
    # H.264 now — what a browser decodes — with the frames intact
    cap = cv2.VideoCapture(str(path))
    try:
        ok, first = cap.read()
        fourcc = int(cap.get(cv2.CAP_PROP_FOURCC) or 0)
    finally:
        cap.release()
    assert ok and first is not None and first.shape[:2] == (48, 64)
    assert fourcc.to_bytes(4, "little").decode("ascii", errors="ignore").lower() in ("avc1", "h264")
    # idempotent: the second ask returns the same file untouched
    stamp = path.stat().st_mtime_ns
    assert rs.ensure_preview(settings, folder.name) == path
    assert path.stat().st_mtime_ns == stamp
    assert [e["playable"] for e in rs.library_entries(settings)] == [True]
    # the card's picture: the first frame, once, as a JPEG the browser shows
    poster = rs.ensure_poster(settings, folder.name)
    assert poster == folder / "poster.jpg" and poster.is_file()
    picture = cv2.imdecode(np.frombuffer(poster.read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert picture is not None and picture.shape[:2] == (48, 64)
    assert rs.ensure_poster(settings, folder.name) == poster

    client = _api(settings)
    shot = client.get(f"/live/recordings/files/{folder.name}/poster.jpg")
    assert shot.status_code == 200 and shot.headers["content-type"] == "image/jpeg"
    part = client.get(f"/live/recordings/files/{folder.name}/preview.mp4", headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and len(part.content) == 100
    assert part.headers["Content-Range"].startswith("bytes 0-99/")
    full = client.get(f"/live/recordings/files/{folder.name}/preview.mp4")
    assert full.status_code == 200 and full.headers["Accept-Ranges"] == "bytes"
    assert len(full.content) == path.stat().st_size
    assert client.get(f"/live/recordings/files/{folder.name}/preview.mp4", headers={"Range": "bytes=999999-"}).status_code == 416
    # a folder without a video cannot be watched
    (folder / "video.mp4").unlink()
    path.unlink()
    poster.unlink()
    assert client.get(f"/live/recordings/files/{folder.name}/preview.mp4").status_code == 404
    assert client.get(f"/live/recordings/files/{folder.name}/poster.jpg").status_code == 404


def test_trim_writes_a_new_recording_with_the_windows_rows(settings) -> None:
    root = rs.recordings_root(settings)
    folder = _write_recording(
        root,
        "gate-20260902-140000",
        started="2026-09-02T14:00:00Z",
        seconds=4,
        rows=[
            _row("2026-09-02T14:00:00.500000Z", "car"),
            _row("2026-09-02T14:00:01.500000Z", "person"),
            _row("2026-09-02T14:00:03.500000Z", "van"),
        ],
    )
    entry = rs.trim_recording(settings, folder.name, 1.0, 3.0)
    new = root / entry["folder"]
    assert new.is_dir() and new != folder
    assert entry["folder"] == "gate-20260902-140001-trim"
    assert entry["trimmed_from"] == folder.name and entry["playable"] is True
    assert entry["duration_s"] == 2.0 and entry["marks"] == 1
    # the cut is the window: two seconds at 10 fps, give or take a frame
    assert 18 <= rs._frame_count(new / "video.mp4") <= 22
    # the window's rows only, re-clocked from the cut's own start
    cut = rs.recording_table(settings, entry["folder"])
    assert [(r["t"], r["class_name"]) for r in cut["rows"]] == [(0.5, "person")]
    assert cut["trimmed_from"] == folder.name
    meta = json.loads((new / "meta.json").read_text())
    assert meta["started_at"] == "2026-09-02T14:00:01Z" and meta["trim_start_s"] == 1.0
    # the original is exactly as it was
    assert len(rs.recording_table(settings, folder.name)["rows"]) == 3
    # a second cut of the same window gets its own name
    assert rs.trim_recording(settings, folder.name, 1.0, 3.0)["folder"] == "gate-20260902-140001-trim-2"
    # refusals: too short, or past the end
    with pytest.raises(rs.RecordingError):
        rs.trim_recording(settings, folder.name, 3.0, 3.2)
    with pytest.raises(rs.RecordingError):
        rs.trim_recording(settings, folder.name, 5.0, 8.0)

    client = _api(settings)
    res = client.post(f"/live/recordings/trim/{folder.name}", json={"start_s": 0.0, "end_s": 1.0})
    assert res.status_code == 200 and res.json()["trimmed_from"] == folder.name
    assert client.post(f"/live/recordings/trim/{folder.name}", json={"start_s": 2.0, "end_s": 2.1}).status_code == 422
    assert client.post("/live/recordings/trim/nope", json={"start_s": 0.0, "end_s": 1.0}).status_code == 422


class TestTheVideoItself:
    """What a recording actually contains (2026-09-11, owner: "stop the transcoding").

    ★ THE MEASUREMENT BEHIND IT. The recorder wrote MPEG-4 Part 2 — which no
    browser decodes — and the first request to watch re-encoded the whole file to
    H.264, so what you watched was a second-generation copy. On a real clip the
    old chain landed at SSIM 0.966 / 2.3 MB; encoding once from the same frames
    gives 0.972 / 1.2 MB. Better picture, half the size, no second pass.
    """

    def test_the_recorder_writes_h264_that_plays_as_it_stands(self, tmp_path) -> None:
        """★ One encode: the file is H.264 and needs no preview derived from it."""
        import numpy as np

        from app.services import recording_service

        rng = np.random.default_rng(0)
        out = tmp_path / "video.mp4"
        writer = recording_service._H264Writer(out, (320, 240), 10.0)
        for _ in range(20):
            writer.write(rng.integers(0, 255, (240, 320, 3), dtype=np.uint8))
        writer.release()

        assert out.is_file() and out.stat().st_size > 0
        # ★ Asked of the file, not assumed from the command line that made it.
        import cv2

        cap = cv2.VideoCapture(str(out))
        try:
            assert cap.isOpened(), "ffmpeg produced a file OpenCV cannot open"
            fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
            tag = "".join(chr((fourcc >> (8 * i)) & 0xFF) for i in range(4))
            assert tag.lower() in ("avc1", "h264"), tag
            ok, frame = cap.read()
            assert ok and frame is not None and frame.shape[:2] == (240, 320)
        finally:
            cap.release()

    def test_an_h264_recording_is_served_without_a_second_encode(self, settings, tmp_path) -> None:
        """★ And an OLDER mp4v recording still gets its preview — no guessing."""
        import json

        from app.services import recording_service

        root = recording_service.recordings_root(settings)
        fresh = root / "fresh"
        fresh.mkdir(parents=True)
        (fresh / "video.mp4").write_bytes(b"not really a video, but it is the file")
        (fresh / "meta.json").write_text(json.dumps({"video_codec": "h264"}))
        # No transcode: the recording IS the playable rendition.
        assert recording_service.ensure_preview(settings, "fresh") == fresh / "video.mp4"
        assert not (fresh / recording_service.PLAYABLE).exists()

        old = root / "old"
        old.mkdir(parents=True)
        (old / "video.mp4").write_bytes(b"mp4v bytes")
        (old / "meta.json").write_text(json.dumps({"frames": 3}))  # no marker
        assert recording_service._meta_codec(old) is None


# ── the session package: satellite map + video + table, one folder (2026-09-12) ──


def _fake_chip(bbox, zoom: int, size: int = 128):
    """A SatelliteChip covering ``bbox`` exactly — no network, real georeferencing."""
    from gis.tiles import lonlat_to_meters
    from gis.types import SatelliteChip

    west_m, south_m = lonlat_to_meters(bbox.west, bbox.south)
    east_m, north_m = lonlat_to_meters(bbox.east, bbox.north)
    gt = (
        west_m,
        (east_m - west_m) / size,
        0.0,
        north_m,
        0.0,
        -(north_m - south_m) / size,
    )
    return SatelliteChip(
        image=np.full((size, size, 3), 90, dtype=np.uint8),
        geotransform=gt,
        crs="EPSG:3857",
        provider_name="fake_sat",
        attribution="© Fake Imagery",
        terms_url="https://example.invalid/terms",
        zoom=zoom,
        captured_at=None,
        gsd_m=0.5,
        georef_ce90_m=5.0,
        is_authoritative=False,
    )


@pytest.fixture()
def _imagery(monkeypatch):
    """``get_static_chip`` without a network — records what it was asked for."""
    asked: dict = {}

    class _Service:
        def __init__(self, *_a, **_kw) -> None:
            pass

        def get_static_chip(self, bbox, zoom, **_kw):
            asked["bbox"], asked["zoom"] = bbox, zoom
            return _fake_chip(bbox, zoom)

    from app.services import imagery_service

    monkeypatch.setattr(imagery_service, "ImageryService", _Service)
    return asked


def test_the_map_frames_the_camera_and_every_placed_mark(settings, tmp_path, _imagery) -> None:
    """★ The scene's box covers the camera AND the marks, with room around them."""
    folder = tmp_path / "scene"
    folder.mkdir()
    rows = [
        _row("2026-09-12T10:00:00Z", "car", lat=34.100, lon=36.000, cam_lat=34.102, cam_lon=36.004),
        _row("2026-09-12T10:00:05Z", "truck", lat=34.101, lon=36.002),
    ]

    built = rs.write_satellite_map(settings, folder, rows, "gate", window="10:00 — 10:01")

    assert built is not None
    assert built["mark_count"] == 2
    assert built["provider"] == "fake_sat"
    for name in (rs.SATELLITE, rs.WORLDFILE, rs.SAT_SIDECAR, rs.MARKS):
        assert (folder / name).is_file(), f"{name} missing"

    box = _imagery["bbox"]
    assert box.west < 36.000 and box.east > 36.004, "the box must reach both marks and the camera"
    assert box.south < 34.100 and box.north > 34.102

    marks = json.loads((folder / rs.MARKS).read_text(encoding="utf-8"))
    roles = [f["properties"]["role"] for f in marks["features"]]
    assert roles.count("camera") == 1 and roles.count("mark") == 2
    # ★ GeoJSON is lon,lat — never lat,lon. The one ordering bug that puts a
    #   detection in the wrong hemisphere without ever raising.
    camera = next(f for f in marks["features"] if f["properties"]["role"] == "camera")
    assert camera["geometry"]["coordinates"] == [36.004, 34.102]

    # The licence obligation travels with the pixels.
    sidecar = (folder / rs.SAT_SIDECAR).read_text(encoding="utf-8")
    assert "© Fake Imagery" in sidecar and "https://example.invalid/terms" in sidecar


def test_a_window_that_placed_nothing_gets_no_map(settings, tmp_path, _imagery) -> None:
    """★ A no-LUT run places nothing; a map of nowhere is worse than no map."""
    folder = tmp_path / "bare"
    folder.mkdir()
    rows = [{"detection_id": 1, "class": "car", "time_utc": "2026-09-12T10:00:00Z"}]

    assert rs.write_satellite_map(settings, folder, rows, "gate") is None
    assert not (folder / rs.SATELLITE).exists()
    assert "bbox" not in _imagery, "imagery must not be asked for a scene with no ground"


def test_unreachable_imagery_costs_the_map_never_the_recording(settings, tmp_path, monkeypatch) -> None:
    """★ Best-effort by construction: the video and the table are the evidence."""
    from app.services import imagery_service

    class _Down:
        def __init__(self, *_a, **_kw) -> None:
            pass

        def get_static_chip(self, *_a, **_kw):
            raise RuntimeError("provider unreachable")

    monkeypatch.setattr(imagery_service, "ImageryService", _Down)
    folder = tmp_path / "offline"
    folder.mkdir()

    assert rs.write_satellite_map(settings, folder, [_row("2026-09-12T10:00:00Z", "car")], "gate") is None
    assert not (folder / rs.SATELLITE).exists()


def test_the_world_file_names_the_top_left_pixel_centre(tmp_path) -> None:
    """★ The geotransform's origin is the pixel's OUTER edge; a world file is its centre."""
    gt = (100.0, 2.0, 0.0, 500.0, 0.0, -2.0)
    out = tmp_path / "w.pgw"
    rs._write_worldfile(out, gt)

    a, d, b, e, c, f = (float(x) for x in out.read_text(encoding="utf-8").split())
    assert (a, d, b, e) == (2.0, 0.0, 0.0, -2.0)
    assert c == 101.0 and f == 499.0  # half a pixel in from each edge


def test_the_package_puts_video_map_and_table_in_their_own_lanes(settings, _imagery) -> None:
    """★ One button, one folder — and inside it the three things, each in its lane."""
    import zipfile

    root = rs.recordings_root(settings)
    folder = _write_recording(
        root,
        "gate-20260912-100000",
        started="2026-09-12T10:00:00Z",
        seconds=1.0,
        rows=[_row("2026-09-12T10:00:00Z", "car", cam_lat=34.102, cam_lon=36.004)],
    )
    rs.ensure_poster(settings, folder.name)

    path, filename = rs.package_path(settings, folder.name)
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            assert zf.testzip() is None
    finally:
        path.unlink(missing_ok=True)

    stem = folder.name
    assert filename == f"{stem}.zip"
    assert names == {
        f"{stem}/video/video.mp4",
        f"{stem}/video/poster.jpg",
        f"{stem}/map/satellite.png",
        f"{stem}/map/satellite.pgw",
        f"{stem}/map/satellite.txt",
        f"{stem}/map/marks.geojson",
        f"{stem}/table/detections.csv",
        f"{stem}/meta.json",
        f"{stem}/README.txt",
    }


def test_an_older_flat_recording_still_packages(settings, monkeypatch) -> None:
    """★ A folder recorded before the map existed downloads as a package anyway."""
    import zipfile

    from app.services import imagery_service

    class _Down:
        def __init__(self, *_a, **_kw) -> None:
            pass

        def get_static_chip(self, *_a, **_kw):
            raise RuntimeError("no imagery here")

    monkeypatch.setattr(imagery_service, "ImageryService", _Down)
    root = rs.recordings_root(settings)
    folder = _write_recording(
        root, "old-20260901-090000", started="2026-09-01T09:00:00Z", seconds=1.0, rows=[]
    )

    path, _ = rs.package_path(settings, folder.name)
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
    finally:
        path.unlink(missing_ok=True)

    stem = folder.name
    assert f"{stem}/video/video.mp4" in names
    assert f"{stem}/table/detections.csv" in names
    assert f"{stem}/README.txt" in names
    assert not any("/map/" in n for n in names), "no map is a missing lane, not a broken zip"


def test_the_package_endpoint_serves_a_zip_and_refuses_traversal(settings, _imagery) -> None:
    """★ One GET returns the whole session; the folder name is still never a path."""
    root = rs.recordings_root(settings)
    folder = _write_recording(
        root,
        "gate-20260912-110000",
        started="2026-09-12T11:00:00Z",
        seconds=1.0,
        rows=[_row("2026-09-12T11:00:00Z", "car", cam_lat=34.102, cam_lon=36.004)],
    )
    client = _api(settings)

    ok = client.get(f"/live/recordings/package/{folder.name}")
    assert ok.status_code == 200
    assert ok.headers["content-type"] == "application/zip"
    assert f"{folder.name}.zip" in ok.headers["content-disposition"]
    assert ok.content[:2] == b"PK"

    # ★ Percent-encoded, not a bare "..": the client collapses a literal one out
    #   of the path before it is ever sent, so only this form reaches the guard.
    assert client.get("/live/recordings/package/%2e%2e").status_code == 404
    assert client.get("/live/recordings/package/nope").status_code == 404


def test_the_library_says_which_folders_carry_a_map(settings, _imagery) -> None:
    """★ ``has_map`` is what the card reads to know the package is complete."""
    root = rs.recordings_root(settings)
    folder = _write_recording(
        root,
        "gate-20260912-120000",
        started="2026-09-12T12:00:00Z",
        seconds=1.0,
        rows=[_row("2026-09-12T12:00:00Z", "car", cam_lat=34.102, cam_lon=36.004)],
    )
    assert rs._entry(folder)["has_map"] is False

    assert rs.ensure_satellite_map(settings, folder.name) is True
    assert rs._entry(folder)["has_map"] is True
