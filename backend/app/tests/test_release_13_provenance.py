"""Release 1.3 — the provenance work: drift stamps, centre offsets, feed rows,
the camera registry's rules and the boot reconciliation.

★ WHAT THESE PIN. A mark's coordinate is valid only while the camera has not
moved; since 2026-09-02 that claim is a COLUMN (``drift_status``) rather than a
sentence in a docstring. A feed's marks are evidence too, so they reach
``detection_events``. The registry lives on the server and restarts what the
operator left running. Each of those is one behaviour the product now promises.
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from app.services import detection_service, drift_service, live_data_service  # noqa: E402
from app.services.detection_service import DetectionSession, start_session  # noqa: E402
from app.tests.test_detection_service import (  # noqa: E402
    _await_end,
    _write_lut,
    ready,  # noqa: F401 — the fixture
)


# ── helpers ───────────────────────────────────────────────────────────────────


def _fake_db(written: list):  # noqa: ANN001, ANN205
    class _Db:
        def add_all(self, objs) -> None:  # noqa: ANN001
            written.extend(objs)

    @contextmanager
    def fake_sync_session():  # noqa: ANN202
        yield _Db()

    return fake_sync_session


def _write_lut_with_pose(root: Path) -> Path:
    """A LUT whose manifest names a camera position — the centre offset needs one."""
    bundle = _write_lut(root)
    manifest = json.loads((bundle / "manifest.json").read_text())
    # camera 100 m SOUTH of the constant LUT point (34.11, 36.02): EPSG:32637 is
    # UTM 37N; the exact easting/northing only need to be south of the point.
    from gis.crs import get_transformer

    tr = get_transformer("EPSG:4326", "EPSG:32637")
    x, y = tr.transform(36.02, 34.11 - 0.0009)  # ~100 m south
    manifest["pose"] = {"C": [float(np.ravel(x)[0]), float(np.ravel(y)[0]), 50.0]}
    manifest["dem"] = {"epsg": 32637}
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    return bundle


# ── drift stamps ──────────────────────────────────────────────────────────────


class TestDriftStamp:
    def test_a_clip_is_always_unwatched(self) -> None:
        assert detection_service.drift_status_for_source("video:abc") == ("unwatched", None)

    def test_no_watch_means_unwatched_not_ok(self) -> None:
        """Silence must never read as reassurance."""
        drift_service._RUNS.clear()
        assert detection_service.drift_status_for_source("/dev/video9") == ("unwatched", None)

    def test_a_running_watch_stamps_its_confirmed_status(self) -> None:
        run = drift_service.DriftMonitorRun(ref_id="a" * 32, source="/dev/video9", interval_s=5)
        run.last = {"status": "MOVED", "state": "MOVED", "checked_utc": "2026-09-02T10:00:00Z"}
        drift_service._RUNS[run.ref_id] = run
        try:
            assert detection_service.drift_status_for_source("/dev/video9") == ("moved", run.ref_id)
            # a stopped watch is silence again — not the last thing it said
            run.status = "stopped"
            assert detection_service.drift_status_for_source("/dev/video9") == ("unwatched", None)
        finally:
            drift_service._RUNS.pop(run.ref_id, None)

    def test_a_watch_with_no_verdict_yet_is_pending(self) -> None:
        run = drift_service.DriftMonitorRun(ref_id="b" * 32, source="/dev/video8", interval_s=5)
        drift_service._RUNS[run.ref_id] = run
        try:
            assert detection_service.drift_status_for_source("/dev/video8") == ("pending", run.ref_id)
        finally:
            drift_service._RUNS.pop(run.ref_id, None)

    def test_marks_and_rows_carry_the_stamp_and_alerts_are_counted(
        self, ready: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path  # noqa: F811
    ) -> None:
        run = drift_service.DriftMonitorRun(ref_id="c" * 32, source="0", interval_s=5)
        run.last = {"status": "CHANGED", "state": "CHANGED", "checked_utc": "x"}
        drift_service._RUNS[run.ref_id] = run
        written: list = []
        monkeypatch.setattr("app.db.session.sync_session", _fake_db(written))
        try:
            session = start_session(source="0", model_dir=ready, lut_dir=_write_lut(tmp_path))
            _await_end(session)
        finally:
            drift_service._RUNS.pop(run.ref_id, None)
        assert session.status == "stopped", session.error
        assert session.marks and all(m["drift_status"] == "changed" for m in session.marks)
        assert all(m["drift_ref_id"] == run.ref_id for m in session.marks)
        # placed, never hidden — and counted
        assert session.marks_under_alert == len(session.marks) > 0
        assert session.drift_status == "changed"
        assert written and all(r.drift_status == "changed" for r in written)
        assert all(r.kind == "detection" for r in written)

    def test_the_export_states_the_stamp(self) -> None:
        session = DetectionSession(
            session_id="stamp-export", source="0", lut_site="s", settings={}, camera_name="cam"
        )
        session.marks = [
            {"lat": 34.1, "lon": 36.01, "score": 0.9, "cls_name": "car", "frame_index": 3,
             "time_s": 1.5, "u": 10.0, "v": 20.0, "drift_status": "moved",
             "centre_offset_m": 2.2},
        ]
        with detection_service._LOCK:
            detection_service._SESSIONS[session.session_id] = session
        try:
            csv_bytes, _, _ = detection_service.export_marks("stamp-export", "csv")
        finally:
            with detection_service._LOCK:
                detection_service._SESSIONS.pop(session.session_id, None)
        header, row = csv_bytes.decode().splitlines()[:2]
        assert "drift" in header.split(",") and "centre_m" in header.split(",")
        assert "moved" in row and "2.2" in row


# ── centre offset ─────────────────────────────────────────────────────────────


class TestCentreOffset:
    def test_push_moves_away_from_the_camera_by_the_metres_asked(self) -> None:
        from app.services.detection.ground import push_from_camera

        lat, lon, applied = push_from_camera(34.11, 36.02, (34.10, 36.02), 2.2)
        assert applied == 2.2
        assert lat > 34.11 and lon == pytest.approx(36.02, abs=1e-9)  # straight north
        assert (lat - 34.11) * 111_320 == pytest.approx(2.2, rel=1e-3)

    def test_no_camera_or_no_entry_applies_nothing_and_says_so(self) -> None:
        from app.services.detection.ground import centre_offset_m, push_from_camera

        assert push_from_camera(34.11, 36.02, None, 2.2) == (34.11, 36.02, None)
        assert push_from_camera(34.11, 36.02, (34.1, 36.0), None) == (34.11, 36.02, None)
        assert centre_offset_m("car") == 2.2 and centre_offset_m("unicorn") is None

    def test_off_by_default_and_recorded_when_on(
        self, ready: Path, tmp_path: Path  # noqa: F811
    ) -> None:
        bundle = _write_lut_with_pose(tmp_path)
        off = start_session(source="0", model_dir=ready, lut_dir=bundle)
        _await_end(off)
        assert off.status == "stopped", off.error
        assert off.marks and all(m["centre_offset_m"] is None for m in off.marks)
        assert off.marks[0]["lat"] == pytest.approx(34.11)

        on = start_session(
            source="0", model_dir=ready, lut_dir=bundle, settings_values={"centre_marks": True}
        )
        _await_end(on)
        assert on.status == "stopped", on.error
        assert on.marks and all(m["centre_offset_m"] == 0.2 for m in on.marks)  # person
        # pushed AWAY from a camera to the south: north of the raw LUT point
        assert on.marks[0]["lat"] > 34.11
        assert on.settings["centre_marks"] is True


# ── feeds are evidence ────────────────────────────────────────────────────────


class TestFeedRows:
    def test_a_feed_line_becomes_a_detection_events_row(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        written: list = []
        monkeypatch.setattr("app.db.session.sync_session", _fake_db(written))
        feed = live_data_service.DataFeed(feed_id="f1", source="serial:///dev/ttyTEST",
                                          camera_id="0" * 32, camera_name="pi-1")
        live_data_service._ingest(feed, '{"lat": 34.1, "lon": 36.0, "cls_name": "car", "track_id": 3}', time.monotonic())
        live_data_service._maybe_flush(feed, force=True)
        assert feed.db_rows_written == 1 and written
        row = written[0]
        assert row.kind == "feed" and row.session_id == "f1"
        assert row.camera_id == "0" * 32 and row.camera_name == "pi-1"
        assert row.u is None and row.v is None  # a feed carries no picture
        assert row.lat == 34.1 and row.track_id == 3
        assert row.drift_status == "unwatched"

    def test_a_dead_database_costs_the_record_not_the_feed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        @contextmanager
        def refusing():  # noqa: ANN202
            raise RuntimeError("connection refused")
            yield  # pragma: no cover

        monkeypatch.setattr("app.db.session.sync_session", refusing)
        feed = live_data_service.DataFeed(feed_id="f2", source="serial:///dev/ttyTEST")
        live_data_service._ingest(feed, "34.1,36.0", time.monotonic())
        live_data_service._maybe_flush(feed, force=True)
        assert feed.lines_ok == 1 and feed.marks
        assert feed.db_rows_failed == 1 and "RuntimeError" in (feed.db_error or "")

    def test_serial_urls_on_both_platforms_parse(self) -> None:
        f = live_data_service._serial_path_and_baud
        assert f("serial:///dev/ttyUSB0?baud=9600") == ("/dev/ttyUSB0", 9600)
        assert f("serial://COM3?baud=115200") == ("COM3", 115200)
        assert f("/dev/ttyACM0") == ("/dev/ttyACM0", 115200)
        assert f("serial:///dev/ttyUSB0?baud=nonsense") == ("/dev/ttyUSB0", 115200)


# ── the camera registry ───────────────────────────────────────────────────────


class TestCameraRules:
    def test_the_frontends_rules_hold_on_the_wire(self) -> None:
        from pydantic import ValidationError

        from app.schemas.camera import CameraCreate

        ok = CameraCreate(name="Gate", lat=34.1, lon=36.0, source="rtsp://cam/1")
        assert ok.provides == "camera" and ok.connection == "lan"
        with pytest.raises(ValidationError, match="serial line carries no picture"):
            CameraCreate(name="S", lat=0, lon=0, connection="serial", provides="camera",
                         source="rtsp://x", data_source="serial://COM3")
        with pytest.raises(ValidationError, match="needs a stream source"):
            CameraCreate(name="V", lat=0, lon=0)
        with pytest.raises(ValidationError, match="needs a data source"):
            CameraCreate(name="D", lat=0, lon=0, provides="data", connection="serial")
        with pytest.raises(ValidationError):
            CameraCreate(name="Out", lat=95, lon=0, source="rtsp://x")
        both = CameraCreate(name="Pi", lat=1, lon=2, connection="lan", provides="both",
                            source="http://pi/stream", data_source="http://pi/feed")
        assert both.provides == "both"

    def test_desired_state_tolerates_old_rows(self) -> None:
        from app.schemas.camera import desired_from_row

        assert desired_from_row(None).feed is False
        assert desired_from_row({"garbage": 1, "feed": True}).feed is True
        d = desired_from_row({"watch": {"ref_id": "a" * 32, "interval_s": 10}})
        assert d.watch is not None and d.watch.interval_s == 10
        assert desired_from_row({"watch": {"ref_id": "short"}}).watch is None


class TestReconcileAtBoot:
    def test_restores_feed_detection_and_watch_from_intent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from app.core.config import Settings
        from app.services import camera_service

        calls: dict[str, dict] = {}

        def fake_start_feed(source, camera_id=None, camera_name=None):  # noqa: ANN001, ANN202
            calls["feed"] = {"source": source, "camera_id": camera_id}
            return type("F", (), {"feed_id": "fx"})()

        def fake_start_session(**kw):  # noqa: ANN003, ANN202
            calls["detect"] = kw
            return type("S", (), {"session_id": "sx"})()

        monkeypatch.setattr(live_data_service, "start_feed", fake_start_feed)
        monkeypatch.setattr(detection_service, "_active_for_source", lambda s: None)
        monkeypatch.setattr(detection_service, "start_session", fake_start_session)
        monkeypatch.setattr(drift_service, "get_monitor", lambda ref_id: None)
        monkeypatch.setattr(
            drift_service, "start_monitor",
            lambda out, ref_id, interval_s, source: calls.setdefault(
                "watch", {"ref_id": ref_id, "interval_s": interval_s, "source": source}),
        )
        settings = Settings(lut_output_dir=tmp_path / "lut", drift_output_dir=tmp_path / "drift",
                            detection_model_dir=tmp_path / "models")
        row = {
            "id": "cam-1", "name": "Gate", "source": "rtsp://cam/1",
            "data_source": "http://pi/feed", "lut_site": None,
            "desired": {
                "feed": True,
                "detect": {"conf": 0.4, "tracker_type": "kcf", "centre_marks": True},
                "watch": {"ref_id": "a" * 32, "interval_s": 12},
            },
        }
        out = camera_service._restore_one(settings, row)
        assert out == {"feed": "started fx", "detect": "started sx", "watch": "started aaaaaaaa"}
        assert calls["feed"] == {"source": "http://pi/feed", "camera_id": "cam-1"}
        assert calls["detect"]["source"] == "rtsp://cam/1" and calls["detect"]["camera_id"] == "cam-1"
        assert calls["detect"]["settings_values"]["locked_tracker_type"] == "kcf"
        assert calls["detect"]["settings_values"]["centre_marks"] is True
        assert calls["watch"] == {"ref_id": "a" * 32, "interval_s": 12.0, "source": "rtsp://cam/1"}

    def test_a_missing_lut_is_one_honest_line_not_a_crash(self, tmp_path: Path) -> None:
        from app.core.config import Settings
        from app.services import camera_service

        settings = Settings(lut_output_dir=tmp_path / "lut", drift_output_dir=tmp_path / "drift",
                            detection_model_dir=tmp_path / "models")
        row = {"id": "c", "name": "N", "source": "rtsp://x", "data_source": None,
               "lut_site": "gone", "desired": {"detect": {}}}
        out = camera_service._restore_one(settings, row)
        assert out["detect"].startswith("failed: LUT bundle 'gone'")

    def test_no_database_means_nothing_to_restore_not_an_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from app.core.config import Settings
        from app.services import camera_service

        @contextmanager
        def refusing():  # noqa: ANN202
            raise RuntimeError("connection refused")
            yield  # pragma: no cover

        monkeypatch.setattr("app.db.session.sync_session", refusing)
        assert camera_service.reconcile_at_boot(Settings(lut_output_dir=tmp_path)) == {}
