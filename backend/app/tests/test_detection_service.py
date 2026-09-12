"""``detection_service`` — the bridge in front of the vendored object geolocator.

Two kinds of test, the ``test_lut_service`` pattern:

1. **The refusals.** A session that cannot succeed is refused before its thread
   starts, with the fix named — including the two refusals specific to THIS
   environment (no ultralytics, no opencv-contrib), which must be statements, not
   crashes.
2. **A stubbed end-to-end run.** The YOLO runtime is optional and absent here, so
   the detector is stubbed — what is under test is the BRIDGE: the freshest-frame
   loop, the ground-point → LUT → mark chain through a real bundle on disk, the
   counts, the caps and the honest counters. The vendored core carries its own
   standalone behaviour; this wiring is ours.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from app.services import detection_service
from app.services.detection_service import (
    DetectionError,
    DetectionSession,
    availability,
    start_session,
)


# ── a real LUT bundle, tiny ──────────────────────────────────────────────────
def _write_lut(root: Path, width: int = 64, height: int = 48) -> Path:
    bundle = root / "test_site_lut"
    bundle.mkdir(parents=True)
    lat = np.full((height, width), 34.11, dtype=np.float64)
    lon = np.full((height, width), 36.02, dtype=np.float64)
    # ★ The top third is SKY (NaN): a ground pixel there must be counted as
    #   skipped, never guessed. Same nodata convention the LUT generator writes.
    lat[: height // 3, :] = np.nan
    np.save(bundle / "lat.npy", lat)
    np.save(bundle / "lon.npy", lon)
    (bundle / "manifest.json").write_text(
        json.dumps({"site_name": "test_site", "image": {"width": width, "height": height}})
    )
    return bundle


class _FakeCapture:
    """A camera that serves N frames then ends — no cv2, no device.

    ★ It PACES itself like a camera. An instant producer would be drained to its
    last frame before the detect loop woke up, and the freshest-frame design would
    (correctly) process one frame — which is the live behaviour, but not a useful
    fixture for counting.
    """

    def __init__(self, frames: int = 40, size: tuple[int, int] = (48, 64)) -> None:
        self._left = frames
        self._size = size

    def read(self):  # noqa: ANN201 — cv2.VideoCapture shape
        if self._left <= 0:
            return False, None
        self._left -= 1
        time.sleep(0.01)  # ~100 fps camera
        h, w = self._size
        return True, np.zeros((h, w, 3), np.uint8)

    def release(self) -> None:
        pass


class _ReleaseAuditCapture(_FakeCapture):
    """A never-ending camera that records WHO released it, and any read after that."""

    def __init__(self) -> None:
        super().__init__(frames=1_000_000)
        self.released_by: str | None = None
        self.read_after_release = False

    def read(self):  # noqa: ANN201 — cv2.VideoCapture shape
        if self.released_by is not None:
            self.read_after_release = True
        return super().read()

    def release(self) -> None:
        self.released_by = threading.current_thread().name


class _FakeDetector:
    """One box per frame, centred low in the frame — its ground pixel has terrain."""

    def __init__(self, model: str, device: str) -> None:
        self.names = {0: "person"}

    def start_run(self, settings) -> None:  # noqa: ANN001
        pass

    def algorithm_status(self) -> dict:
        return {"phase": "detector", "frames_seen": 0}

    def detect(
        self, frame, settings, frame_index=0, time_s=0.0, single_frame=False
    ):  # noqa: ANN001
        from app.services.detection.models import Box, Detection

        h, w = frame.shape[:2]
        # bottom-edge midpoint lands at (w/2, 0.9h) — inside the LUT's terrain
        ground = Detection(
            box=Box(w * 0.4, h * 0.6, w * 0.6, h * 0.9),
            score=0.9,
            cls_id=0,
            cls_name="person",
        )
        # …and one whose feet are in the SKY band (top third): must be skipped
        sky = Detection(
            box=Box(w * 0.4, h * 0.05, w * 0.6, h * 0.2),
            score=0.8,
            cls_id=0,
            cls_name="person",
        )
        return [ground, sky]


@pytest.fixture
def ready(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """The environment pieces the bridge feature-detects, stubbed present.

    The probe is ENVIRONMENT (is ultralytics installed); the logic under test is
    the bridge. The weights file is real so the model-listing path runs for real.
    """
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    (model_dir / "yolo26s.pt").write_bytes(b"weights")
    monkeypatch.setattr(
        detection_service,
        "_detector_probe",
        lambda _d: {"available": True, "reason": None, "models": ["yolo26s.pt"]},
    )
    import app.services.detection.detector as vendor_detector

    monkeypatch.setattr(vendor_detector, "Detector", _FakeDetector)
    monkeypatch.setattr("app.services.live_stream_service.open_capture", lambda src: _FakeCapture())
    return model_dir


def _await_end(session, timeout: float = 10.0):  # noqa: ANN001
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if session.status in ("stopped", "failed"):
            return session
        time.sleep(0.02)
    raise AssertionError(f"session did not finish: {session.status}")


class TestAvailability:
    def test_a_missing_runtime_is_a_statement_with_the_pip_line(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """★ Forced-absent, not assumed-absent: whether THIS machine has ultralytics
        is an accident of its history, and a test that depends on it flips the day
        someone installs the runtime (it did)."""
        import builtins

        real_import = builtins.__import__

        def no_ultralytics(name, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
            if name == "ultralytics":
                raise ImportError("absent")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", no_ultralytics)
        report = availability(tmp_path / "empty")
        assert report["detector"]["available"] is False
        assert "pip install" in report["detector"]["reason"]

    def test_both_availability_states_validate_against_the_wire_schema(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """★ The lesson bought THREE times now (MAX_LIMIT, HeatmapVersion, this):
        validate what the route returns, in EVERY state the payload can take. The
        available state carried a `models` key the capability model forbids — and the
        dev machine, having no runtime, only ever exercised the absent state, so the
        first machine WITH the runtime got the 500."""
        from app.schemas.detection import DetectionAvailability

        # absent state — as this environment naturally reports (or forced)
        absent = DetectionAvailability(**availability(tmp_path / "empty"))
        assert absent.device is None  # no runtime → no device to name

        # available state — the one that shipped broken
        monkeypatch.setattr(
            detection_service,
            "_detector_probe",
            lambda _d: {
                "available": True,
                "reason": None,
                "models": ["yolo26s.pt"],
                "device": "cpu",
            },
        )
        read = DetectionAvailability(**availability(tmp_path))
        assert read.detector.available is True
        assert read.models == ["yolo26s.pt"]
        # ★ The device rides the wire — the UI picks its speed defaults from it.
        assert read.device == "cpu"
        # ★ Classes carry their COCO ids: the picker sends ids back, and a UI that
        #   had to hardcode them would drift from the vendored allow-list.
        assert [c.name for c in read.classes] == [
            "person",
            "car",
            "motorcycle",
            "bus",
            "truck",
        ]
        assert [c.id for c in read.classes] == [0, 2, 3, 5, 7]

    def test_warming_pays_the_import_cost_at_startup_not_on_a_page(
        self, ready: Path, tmp_path: Path
    ) -> None:
        """★ THE TWO-SECOND BAR (2026-08-20). `_detector_probe` imports ultralytics,
        which imports torch — 1.9 s the first time, 0.00 s after. That first call
        landed on whoever opened a detection page, so its settings bar built itself
        in two stages. Warming moves the cost to boot.

        And it DECLINES where there is nothing to detect with: importing torch costs
        real memory, and a machine with no weights cannot run detection anyway."""
        thread = detection_service.warm_probe(ready)
        assert thread is not None
        thread.join(timeout=30)
        assert not thread.is_alive()
        # The page's own call now finds the runtime already imported.
        assert availability(ready)["detector"]["available"] is True

        empty = tmp_path / "no-weights"
        empty.mkdir()
        assert detection_service.warm_probe(empty) is None

    def test_the_tracker_is_available_by_rule(self, tmp_path: Path) -> None:
        # ★ THE RULE FLIPPED 2026-08: the environment ships opencv-contrib-python-
        #   headless (one wheel, no GUI) precisely so the vendored algorithm's full
        #   shape — YOLO finds, CSRT follows — can run. Absence is now the
        #   exception, tested below with the attrs stripped.
        report = availability(tmp_path / "empty")
        assert report["tracker"]["available"] is True

    def test_a_contribless_box_is_told_the_pip_line(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import cv2

        monkeypatch.delattr(cv2, "TrackerCSRT_create", raising=False)
        if getattr(cv2, "legacy", None) is not None:
            monkeypatch.delattr(cv2.legacy, "TrackerCSRT_create", raising=False)
        report = availability(tmp_path / "empty")
        assert report["tracker"]["available"] is False
        assert "opencv-contrib-python-headless" in report["tracker"]["reason"]

    def test_missing_weights_name_the_folder(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(detection_service, "_detector_probe", detection_service._detector_probe)
        # ultralytics absent → that refusal wins; simulate it present to reach weights
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
            if name == "ultralytics":
                import types

                return types.ModuleType("ultralytics")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        report = detection_service._detector_probe(tmp_path / "no_models")
        assert report["available"] is False
        assert "no_models" in report["reason"]
        assert "never downloaded" in report["reason"]


class TestRefusals:
    def test_without_the_runtime_the_start_is_refused_with_the_pip_line(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(
            detection_service,
            "_detector_probe",
            lambda _d: {"available": False, "reason": "… pip install ultralytics …"},
        )
        with pytest.raises(DetectionError, match="pip install"):
            start_session(source="0", model_dir=tmp_path, lut_dir=None)

    def test_a_live_handoff_now_runs(self, ready: Path) -> None:
        """★ FLIPPED 2026-08-20 with the detector-rescue edit: a dropped-frame gap
        that breaks CSRT correspondence fails the lock and the rescue re-acquires
        on that same frame — the silent permanent loss the old refusal guarded
        against cannot happen any more, so live feeds may hand off too."""
        session = start_session(
            source="0",
            model_dir=ready,
            lut_dir=None,
            settings_values={"tracker_start_frame": 3},
        )
        _await_end(session)
        assert session.status == "stopped", session.error
        assert session.settings["tracker_start_frame"] == 3

    def test_a_live_capture_is_released_by_its_reader_never_under_a_read(
        self, ready: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """★ THE CRASH OF 2026-08-30. The run thread released the capture in its
        `finally` while the reader thread was still inside `cap.read()` on it;
        FFmpeg tore the decoder down under the read and the API died with a
        general protection fault in libavutil — on every Stop of a live source.
        The reader owns the release now: it happens on the reader thread, after
        its last read, and never while a read is in flight."""
        cap = _ReleaseAuditCapture()
        monkeypatch.setattr("app.services.live_stream_service.open_capture", lambda src: cap)
        session = detection_service.start_session(
            source="http://cam.local/stream", model_dir=ready, lut_dir=None
        )
        deadline = time.monotonic() + 5
        while session.frames_done < 5 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert session.frames_done >= 5
        assert detection_service.stop_session(session.session_id)
        _await_end(session)
        deadline = time.monotonic() + 3
        while cap.released_by is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert cap.released_by is not None
        assert cap.released_by.startswith("detect-read-"), cap.released_by
        assert cap.read_after_release is False

    def test_a_second_session_on_one_camera_is_refused(self, ready: Path) -> None:
        first = start_session(
            source="7",
            model_dir=ready,
            lut_dir=None,
            settings_values={"max_frames": 1000},
        )
        try:
            with pytest.raises(DetectionError, match="already being detected"):
                start_session(source="7", model_dir=ready, lut_dir=None)
        finally:
            detection_service.stop_session(first.session_id)
            _await_end(first)

    def test_an_unknown_model_names_what_is_available(self, ready: Path) -> None:
        with pytest.raises(DetectionError, match="yolo26s.pt"):
            start_session(
                source="0",
                model_dir=ready,
                lut_dir=None,
                settings_values={"model": "yolo99x.pt"},
            )


class TestQuantizeCompat:
    def test_an_ultralytics_that_rejects_quantize_still_detects(self) -> None:
        """★ The runtime bug that killed the first real click: the vendored detector
        passed `quantize` unconditionally, and the packaged runtime's ultralytics
        rejects the KEY. On CPU the key is now never sent; on CUDA it is retried
        without. This drives the vendored `_predict` with a model that refuses it."""
        from app.services.detection.detector import Detector
        from app.services.detection.models import DetectSettings

        class _RejectingModel:
            names = {0: "person"}

            def predict(self, **kwargs):  # noqa: ANN003, ANN201
                if "quantize" in kwargs:
                    raise SyntaxError("'quantize' is not a valid YOLO argument.")
                return []

        detector = Detector.__new__(Detector)
        detector._model = _RejectingModel()
        detector.names = {0: "person"}
        settings = DetectSettings.from_dict({})
        # CPU: the key is never passed, so this must simply succeed.
        assert detector._predict(None, settings, 640, "cpu") == []
        # CUDA: passed, rejected, retried without — still succeeds.
        assert detector._predict(None, settings, 640, "cuda:0") == []


class TestErrorHygiene:
    def test_ansi_escapes_never_reach_the_wire(self) -> None:
        """ultralytics colours its tracebacks; on a web page that is `[31m` garbage
        that also broke the layout. Errors are for reading."""
        assert (
            detection_service._clean("\x1b[31m\x1b[1mquantize\x1b[0m is not valid")
            == "quantize is not valid"
        )


class TestRun:
    def test_frames_become_marks_through_a_real_bundle(self, ready: Path, tmp_path: Path) -> None:
        """The whole bridge: frames → boxes → ground pixel → LUT → marks + counts.

        ★ ``mark_rate_hz=0`` so this keeps testing THE BRIDGE, one mark per frame.
        The per-object rate limit added on 2026-09-11 is a display concern and has
        its own tests; mixing the two would leave neither stated clearly.
        """
        bundle = _write_lut(tmp_path)
        session = start_session(
            source="0", model_dir=ready, lut_dir=bundle,
            settings_values={"mark_rate_hz": 0},
        )
        _await_end(session)

        assert session.status == "stopped", session.error
        assert session.frames_done > 0
        # One grounded detection per frame became a mark; the sky one never did.
        assert len(session.marks) == session.frames_done
        assert session.skipped_no_terrain == session.frames_done
        mark = session.marks[0]
        assert mark["lat"] == pytest.approx(34.11)
        assert mark["lon"] == pytest.approx(36.02)
        # Counts see BOTH detections — counting is about what was seen, not placed.
        assert session.counts["person"] == 2 * session.frames_done
        # The overlay payload carries the placement truth per box.
        placed = [b["placed"] for b in session.latest["boxes"]]
        assert placed == [True, False]

    def test_a_tracking_only_run_builds_no_detector_and_detects_nothing(
        self, ready: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """★ `detect=False` (2026-09-11): the source is read, the tracker is armed,
        and the detector is never even constructed — no weights, no torch."""
        import app.services.detection.detector as vendor_detector

        def refuse(*_a: object, **_k: object) -> None:
            raise AssertionError("a tracking-only run must not build a detector")

        monkeypatch.setattr(vendor_detector, "Detector", refuse)
        session = start_session(source="0", model_dir=ready, lut_dir=None, detect=False)
        _await_end(session)
        assert session.status == "stopped", session.error
        assert session.detect is False
        assert session.frames_done > 0
        assert session.marks == [] and not session.counts
        assert session.phase == "tracking"
        assert session.tracking_on is True

    def test_a_tracking_only_run_needs_no_weights_at_all(
        self, ready: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A machine that cannot detect can still follow a drawn box.

        `ready` stubs the capture; the model folder used here is a different,
        EMPTY one, and the detector probe is made to say the runtime is missing.
        """
        del ready
        empty = tmp_path / "no-models"
        empty.mkdir()
        monkeypatch.setattr(
            detection_service, "_detector_probe",
            lambda _d: {"available": False, "reason": "no runtime", "models": []},
        )
        with pytest.raises(detection_service.DetectionError):
            start_session(source="0", model_dir=empty, lut_dir=None)
        # ...but the same machine starts a tracking-only run.
        monkeypatch.setattr(
            detection_service, "_tracker_probe", lambda: {"available": True, "reason": None}
        )
        session = start_session(source="0", model_dir=empty, lut_dir=None, detect=False)
        _await_end(session)
        assert session.status == "stopped", session.error
        assert session.detect is False

    def test_without_a_lut_detection_still_runs_but_places_nothing(self, ready: Path) -> None:
        session = start_session(source="0", model_dir=ready, lut_dir=None)
        _await_end(session)
        assert session.status == "stopped", session.error
        assert session.frames_done > 0
        assert session.marks == []
        # ★ NOT counted as skipped: nothing was looked up, so nothing was skipped.
        #   "unlocated because you chose no LUT" and "unlocated because the ground
        #   pixel was sky" are different facts.
        assert session.skipped_no_terrain == 0

    def test_max_frames_stops_the_session_by_itself(self, ready: Path) -> None:
        session = start_session(
            source="0",
            model_dir=ready,
            lut_dir=None,
            settings_values={"max_frames": 3},
        )
        _await_end(session)
        assert session.status == "stopped"
        assert session.frames_done == 3

    def test_a_video_file_reads_every_frame_and_serves_a_preview(
        self, ready: Path, tmp_path: Path
    ) -> None:
        """★ Files are NOT the live loop: no freshest-drop (a file does not go
        stale), the run completes at the clip's end, and — since a file has no
        player under the overlay — the session serves its own JPEG preview."""
        cv2 = pytest.importorskip("cv2")

        clip = tmp_path / "clip.mp4"
        writer = cv2.VideoWriter(str(clip), cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (64, 48))
        for _ in range(8):
            writer.write(np.zeros((48, 64, 3), np.uint8))
        writer.release()

        bundle = _write_lut(tmp_path)
        session = start_session(
            source="video:test", model_dir=ready, lut_dir=bundle, file_path=clip
        )
        _await_end(session)
        assert session.status == "stopped", session.error
        assert session.frames_done == 8  # every frame, none dropped
        assert session.frames_dropped == 0
        assert session.latest_jpeg is not None  # the preview exists
        assert session.latest_jpeg[:2] == b"\xff\xd8"  # and is a JPEG

    def test_every_nth_skips_file_frames_without_detecting_them(
        self, ready: Path, tmp_path: Path
    ) -> None:
        """★ The CPU speed dial. An 8-frame clip at every-2nd detects frames
        1,3,5,7 and grab()s past 2,4,6,8 — 4 detected, 4 skipped, and the skips
        land in `frames_dropped`: the same honesty ledger as the live drop."""
        cv2 = pytest.importorskip("cv2")

        clip = tmp_path / "clip.mp4"
        writer = cv2.VideoWriter(str(clip), cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (64, 48))
        for _ in range(8):
            writer.write(np.zeros((48, 64, 3), np.uint8))
        writer.release()

        session = start_session(
            source="video:test-nth",
            model_dir=ready,
            lut_dir=None,
            file_path=clip,
            every_nth=2,
        )
        _await_end(session)
        assert session.status == "stopped", session.error
        assert session.frames_done == 4
        assert session.frames_dropped == 4

    def test_pause_holds_a_file_run_and_resume_releases_it(
        self, ready: Path, tmp_path: Path
    ) -> None:
        """★ The pause holds BETWEEN frames: frames_done stops advancing while
        paused and the run completes normally after resume. Live sessions refuse
        — a camera has no pause button."""
        cv2 = pytest.importorskip("cv2")
        clip = tmp_path / "pause.mp4"
        writer = cv2.VideoWriter(str(clip), cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (64, 48))
        for _ in range(200):
            writer.write(np.zeros((48, 64, 3), np.uint8))
        writer.release()

        session = start_session(
            source="video:pausable",
            model_dir=ready,
            lut_dir=None,
            file_path=clip,
        )
        detection_service.set_paused(session.session_id, True)
        time.sleep(0.3)
        held_at = session.frames_done
        time.sleep(0.3)
        assert session.frames_done == held_at  # holding, not crawling
        assert session.paused is True
        detection_service.set_paused(session.session_id, False)
        _await_end(session)
        assert session.status == "stopped", session.error
        assert session.frames_done == 200

    def test_live_sessions_refuse_to_pause(self, ready: Path) -> None:
        session = start_session(source="0", model_dir=ready, lut_dir=None)
        try:
            with pytest.raises(DetectionError, match="no pause button"):
                detection_service.set_paused(session.session_id, True)
        finally:
            session._stop.set()
            _await_end(session)

    def test_the_handoff_refuses_frame_skipping(self, ready: Path, tmp_path: Path) -> None:
        cv2 = pytest.importorskip("cv2")
        clip = tmp_path / "skip.mp4"
        writer = cv2.VideoWriter(str(clip), cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (64, 48))
        for _ in range(4):
            writer.write(np.zeros((48, 64, 3), np.uint8))
        writer.release()
        with pytest.raises(DetectionError, match="every Nth frame"):
            start_session(
                source="video:t",
                model_dir=ready,
                lut_dir=None,
                file_path=clip,
                settings_values={"tracker_start_frame": 2},
                every_nth=2,
            )

    def test_a_file_run_carries_the_handoff_into_the_settings(
        self, ready: Path, tmp_path: Path
    ) -> None:
        """The request's tracker_start_frame reaches the vendored settings intact
        (the old code zeroed it) — the Detector builds its LockedTracker from it."""
        cv2 = pytest.importorskip("cv2")
        clip = tmp_path / "handoff.mp4"
        writer = cv2.VideoWriter(str(clip), cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (64, 48))
        for _ in range(4):
            writer.write(np.zeros((48, 64, 3), np.uint8))
        writer.release()
        session = start_session(
            source="video:handoff",
            model_dir=ready,
            lut_dir=None,
            file_path=clip,
            settings_values={"tracker_start_frame": 2},
        )
        _await_end(session)
        assert session.status == "stopped", session.error
        assert session.settings["tracker_start_frame"] == 2


class TestArmedHandoff:
    def test_the_handoff_arms_at_the_frame_and_fires_on_detections(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """★ "Tracker start 60" means: lock when 60 frames have been detected —
        the surveyor's own words (2026-08-20). The handoff ARMS at frame N and
        FIRES on the first armed frame whose YOLO pass found something; an
        armed-but-empty frame keeps YOLO looking instead of locking nothing
        (the empty-opening bug this class originally pinned down)."""
        from app.services.detection.detector import Detector
        from app.services.detection.models import Box, Detection, DetectSettings

        d = Detector.__new__(Detector)  # no ultralytics load
        d._model = object()  # detect() only checks non-None
        d.device = "cpu"
        d.names = {2: "car"}
        settings = DetectSettings.from_dict({"tracker_start_frame": 2, "conf": 0.25})
        d.start_run(settings)

        def frame() -> np.ndarray:
            f = np.zeros((120, 160, 3), np.uint8)
            f[30:60, 30:60] = (60, 180, 240)  # texture where the box will sit
            f[35:55, 35:55] = (200, 90, 30)
            return f

        yolo_calls = {"n": 0}

        # the opening two YOLO passes are EMPTY; every later one sees the car
        # (call 4 is the rescue pass after the simulated loss below)
        def fake_predict(frame, settings, imgsz, device, per_source=False):  # noqa: ANN001, ANN002
            i = yolo_calls["n"]
            yolo_calls["n"] += 1
            if i >= 2:
                return [Detection(box=Box(30, 30, 60, 60), score=0.8, cls_id=2, cls_name="car")]
            return []

        monkeypatch.setattr(d, "_predict", fake_predict)

        assert d.detect(frame(), settings, frame_index=0) == []  # not armed yet
        # frame 1: ARMED (2 frames detected) — but empty, so YOLO keeps looking
        assert d.detect(frame(), settings, frame_index=1) == []
        assert d.algorithm_status()["phase"] == "detector"  # NOT locked
        # frame 2: armed AND detecting — the lock fires HERE
        locked = d.detect(frame(), settings, frame_index=2)
        assert len(locked) == 1 and locked[0].track_id == 1
        after = d.detect(frame(), settings, frame_index=3)  # CSRT owns the run
        assert d.algorithm_status()["phase"] == "tracker"
        assert len(after) == 1 and after[0].track_id == 1
        assert yolo_calls["n"] == 3  # no loss -> no rescue

        # ── the rescue: a lost lock brings YOLO back for that frame ──────────
        # ★ Product requirement 2026-08-20: the box must not silently vanish
        #   while the object is still in the picture. Simulate a total loss and
        #   the next frame must run YOLO and re-acquire — with a FRESH id,
        #   because it is a new lock.
        d._locked_tracker.reset()  # ids restart at 1
        rescued = d.detect(frame(), settings, frame_index=4)
        assert yolo_calls["n"] == 4  # rescue ran YOLO
        assert len(rescued) == 1 and rescued[0].track_id == 1
        followed = d.detect(frame(), settings, frame_index=5)  # lock holds again
        assert len(followed) == 1 and followed[0].track_id == 1
        assert yolo_calls["n"] == 4  # and YOLO rests


class TestCameraHandover:
    """★ THE APP LOSING A FIGHT WITH ITSELF (2026-08-21). Detecting on a live camera
    failed with "could not open capture device '/dev/video0'" while that same camera
    streamed happily in the panel above — because the panel's own re-stream held the
    device, and a V4L2 camera admits exactly ONE opener. The page now switches to the
    run's stream (which drops the preview), and the run waits out the handover."""

    def test_a_camera_the_panel_still_holds_is_waited_for(
        self, ready: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = {"n": 0}

        def flaky(_src):  # noqa: ANN001, ANN202
            calls["n"] += 1
            if calls["n"] < 3:  # the panel has not let go yet
                raise RuntimeError("could not open capture device '/dev/video0'")
            return _FakeCapture()

        monkeypatch.setattr("app.services.live_stream_service.open_capture", flaky)
        session = start_session(source="0", model_dir=ready, lut_dir=None)
        _await_end(session)
        assert session.status == "stopped", session.error
        assert calls["n"] >= 3  # it retried rather than giving up at once
        assert session.frames_done > 0  # and the run really produced frames

    def test_a_camera_nothing_can_open_still_fails_with_the_reason(
        self, ready: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The retry must not turn a REAL failure into a hang: an absent camera, or
        one held by another program, still fails — with the words that name the fix."""
        monkeypatch.setattr(detection_service, "DEVICE_HANDOVER_S", 0.4)

        def never(_src):  # noqa: ANN001, ANN202
            raise RuntimeError(
                "could not open capture device '/dev/video0' — check that it is connected"
            )

        monkeypatch.setattr("app.services.live_stream_service.open_capture", never)
        session = start_session(source="0", model_dir=ready, lut_dir=None)
        _await_end(session)
        assert session.status == "failed"
        assert "could not open capture device" in (session.error or "")

    def test_a_live_run_serves_its_own_picture_too(self, ready: Path) -> None:
        """★ Live sessions encode a preview now, not just files — it is what the panel
        watches while the detector owns the camera, so without it the page would go
        blank the moment detection started."""
        session = start_session(source="0", model_dir=ready, lut_dir=None)
        _await_end(session)
        assert session.status == "stopped", session.error
        assert session.latest_jpeg is not None
        assert session.latest_jpeg[:2] == b"\xff\xd8"
        assert session.jpeg_seq > 0


class TestExportAndIdentity:
    def _session_with_marks(self) -> DetectionSession:
        session = DetectionSession(
            session_id="export-test",
            source="video:x",
            lut_site="siteA",
            settings={},
            camera_name="DJI_0136.MP4",
            camera_location=(34.2, 36.0),
        )
        session.marks = [
            {
                "lat": 34.1,
                "lon": 36.01,
                "score": 0.9,
                "cls_name": "car",
                "frame_index": 3,
                "time_s": 1.5,
                "u": 10.0,
                "v": 20.0,
                "track_id": 1,
                "predicted": False,
            },
            {
                "lat": 34.11,
                "lon": 36.02,
                "score": 0.8,
                "cls_name": "person",
                "frame_index": 7,
                "time_s": 3.0,
                "u": 11.0,
                "v": 21.0,
                "track_id": None,
                "predicted": True,
            },
        ]
        with detection_service._LOCK:
            detection_service._SESSIONS[session.session_id] = session
        return session

    def _cleanup(self) -> None:
        with detection_service._LOCK:
            detection_service._SESSIONS.pop("export-test", None)

    def test_the_three_formats_carry_one_attribute_table(self) -> None:
        """★ CSV, GeoJSON, and zipped Shapefile all carry THE SAME columns —
        date/time, camera name, camera location — because a dataset whose
        attributes depend on the container is two datasets."""
        import io
        import json as json_mod
        import zipfile

        self._session_with_marks()
        try:
            csv_bytes, csv_type, csv_name = detection_service.export_marks("export-test", "csv")
            assert csv_type == "text/csv" and csv_name.endswith(".csv")
            text = csv_bytes.decode("utf-8")
            assert "camera" in text and "DJI_0136.MP4" in text
            assert "34.2" in text and "car" in text  # cam_lat + class
            assert text.count("\n") >= 3  # header + 2 rows

            gj_bytes, gj_type, _ = detection_service.export_marks("export-test", "geojson")
            assert gj_type == "application/geo+json"
            gj = json_mod.loads(gj_bytes)
            assert len(gj["features"]) == 2
            f0 = gj["features"][0]
            assert f0["geometry"]["coordinates"] == [36.01, 34.1]
            assert f0["properties"]["camera"] == "DJI_0136.MP4"
            assert f0["properties"]["time_utc"].endswith("Z")

            shp_bytes, shp_type, shp_name = detection_service.export_marks("export-test", "shp")
            assert shp_type == "application/zip" and shp_name.endswith("_shp.zip")
            names = zipfile.ZipFile(io.BytesIO(shp_bytes)).namelist()
            exts = {n.rsplit(".", 1)[-1] for n in names}
            # .prj included: a shapefile without its CRS is a guessing game
            assert {"shp", "shx", "dbf", "prj"} <= exts
        finally:
            self._cleanup()

    def test_a_named_track_rides_the_export_and_a_blank_name_clears_it(self) -> None:
        """★ "#1" becomes "white pickup" in every format's attribute table."""
        session = self._session_with_marks()
        try:
            detection_service.set_track_name("export-test", 1, "  white   pickup ")
            rows = detection_service._export_rows(session)
            assert rows[0]["track_name"] == "white pickup"
            assert rows[1]["track_name"] is None          # no track, no name
            assert "track_name" in detection_service._EXPORT_COLUMNS
            csv_bytes, _mime, _name = detection_service.export_marks("export-test", "csv")
            assert b"white pickup" in csv_bytes
            detection_service.set_track_name("export-test", 1, "   ")
            assert session.track_names == {}
        finally:
            self._cleanup()

    def test_naming_a_track_on_an_unknown_run_is_refused(self) -> None:
        with pytest.raises(detection_service.DetectionError):
            detection_service.set_track_name("no-such-run", 1, "x")

    def test_an_empty_run_refuses_to_export(self) -> None:
        session = self._session_with_marks()
        session.marks = []
        try:
            with pytest.raises(DetectionError, match="no marks"):
                detection_service.export_marks("export-test", "csv")
        finally:
            self._cleanup()

    def test_camera_location_comes_out_of_the_manifest(self) -> None:
        """pose.C in the DEM's projected CRS + dem.epsg → WGS84. A manifest
        missing either piece answers None, never a guessed point."""
        # UTM 36N easting 700000, northing 3800000 → ~34.32N 35.17E (Lebanon)
        manifest = {"pose": {"C": [700000.0, 3800000.0, 1200.0]}, "dem": {"epsg": 32636}}
        loc = detection_service._camera_location(manifest)
        assert loc is not None
        lat, lon = loc
        assert 34.0 < lat < 34.7 and 34.9 < lon < 35.5
        assert detection_service._camera_location({}) is None
        assert (
            detection_service._camera_location({"pose": {"C": [1.0, 2.0, 3.0]}, "dem": {}}) is None
        )

    def test_an_unknown_tracker_is_refused_with_the_list(self, ready: Path) -> None:
        with pytest.raises(DetectionError, match="csrt, kcf, mil"):
            start_session(
                source="0",
                model_dir=ready,
                lut_dir=None,
                settings_values={"locked_tracker_type": "goturn"},
            )

    def test_restart_waits_for_the_dying_session_instead_of_refusing(self, ready: Path) -> None:
        """★ The Restart button is stop-then-start with no pause between the
        clicks — the start must WAIT for the old thread to release the source,
        not bounce the user for being fast."""
        first = start_session(source="0", model_dir=ready, lut_dir=None)
        detection_service.stop_session(first.session_id)
        second = start_session(source="0", model_dir=ready, lut_dir=None)
        try:
            assert second.session_id != first.session_id
        finally:
            second._stop.set()
            _await_end(second)


class TestMjpegStream:
    def test_the_stream_carries_the_frames_and_ends_with_the_run(self) -> None:
        """★ The smooth preview: the endpoint pushes each encoded frame as a
        multipart part and closes when the run is over. A stopped session with
        one frame yields exactly that frame and terminates — the property that
        keeps the TestClient (and the browser) from hanging forever."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.api.v1 import detection as detection_router

        app = FastAPI()
        app.include_router(detection_router.router)

        session = DetectionSession(
            session_id="stream-test",
            source="video:x",
            lut_site=None,
            settings={},
        )
        session.status = "stopped"
        session.latest_jpeg = b"\xff\xd8streamtestjpegbytes"
        session.jpeg_seq = 1
        with detection_service._LOCK:
            detection_service._SESSIONS["stream-test"] = session
        try:
            client = TestClient(app)
            r = client.get("/detection/sessions/stream-test/stream")
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("multipart/x-mixed-replace")
            assert b"--detectionframe" in r.content
            assert b"\xff\xd8streamtestjpegbytes" in r.content
            assert client.get("/detection/sessions/absent/stream").status_code == 404
        finally:
            with detection_service._LOCK:
                detection_service._SESSIONS.pop("stream-test", None)


class TestLockedTracker:
    def test_csrt_follows_a_moving_object(self) -> None:
        """★ The wheel-swap's proof: REAL CSRT (opencv-contrib-python-headless)
        follows a textured block sliding right — one lock per detection, the id
        stable across frames. If the wheel regresses to contrib-less cv2, this
        fails at construction, not in production."""
        from app.services.detection.locked_tracking import LockedTracker
        from app.services.detection.models import Box, Detection

        def frame(x: int):  # noqa: ANN202
            f = np.zeros((120, 160, 3), np.uint8)
            f[40:70, x : x + 30] = (60, 180, 240)
            f[45:65, x + 5 : x + 25] = (200, 90, 30)
            return f

        tracker = LockedTracker("csrt")
        seed = Detection(box=Box(20, 40, 50, 70), score=0.9, cls_id=2, cls_name="car")
        locked = tracker.acquire([seed], frame(20))
        assert len(locked) == 1
        assert locked[0].track_id == 1

        for x in (25, 30, 35, 40):
            dets, _ = tracker.update(frame(x))
            assert len(dets) == 1
            assert dets[0].track_id == 1
            centre = (dets[0].box.x1 + dets[0].box.x2) / 2
            # the block's true centre is x+15 — CSRT stays within 4 px of it
            assert abs(centre - (x + 15)) <= 4

    def test_wire_schema_round_trip(self, ready: Path, tmp_path: Path) -> None:
        """★ The session IS the response body, and every wire model forbids extras.

        The lesson bought twice already (MAX_LIMIT, HeatmapVersion): validate what
        the route returns, not the dict the service holds.
        """
        from app.api.v1.detection import _to_read

        bundle = _write_lut(tmp_path)
        session = start_session(source="0", model_dir=ready, lut_dir=bundle)
        _await_end(session)
        read = _to_read(session)
        assert read.marks_total == len(session.marks)
        assert read.latest is not None and len(read.latest.boxes) == 2
        assert read.lut_site == "test_site"


class TestDurableDetectionRows:
    """★ OWNER REQUEST (2026-08-31): every detection durably recorded — the UTC
    instant, the local wall clock (with its offset, stamped at detection time),
    and the tracker's id — batched to ``detection_events`` from the run thread."""

    @staticmethod
    def _fake_db(written: list):  # noqa: ANN001, ANN205
        from contextlib import contextmanager

        class _Db:
            def add_all(self, objs) -> None:  # noqa: ANN001
                written.extend(objs)

        @contextmanager
        def fake_sync_session():  # noqa: ANN202
            yield _Db()

        return fake_sync_session

    def test_every_detection_becomes_a_row_with_utc_local_and_track_id(
        self, ready: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from datetime import datetime

        written: list = []
        monkeypatch.setattr("app.db.session.sync_session", self._fake_db(written))
        session = start_session(source="0", model_dir=ready, lut_dir=None)
        _await_end(session)
        assert session.status == "stopped", session.error
        assert session.db_rows_written == len(written) > 0
        assert session.db_rows_failed == 0 and session.db_error is None

        row = written[0]
        assert row.session_id == session.session_id
        assert row.cls_name == "person"
        assert row.detected_at.tzinfo is not None  # timezone-aware UTC
        local = datetime.fromisoformat(row.detected_at_local)
        assert local.utcoffset() is not None, "local time must carry its offset"
        # same instant, two renderings
        assert abs((local - row.detected_at).total_seconds()) < 1.0
        assert row.lat is None and row.lon is None  # this run had no LUT
        assert row.frame_index >= 0

    def test_a_dead_database_costs_the_record_not_the_run(
        self, ready: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from contextlib import contextmanager

        @contextmanager
        def refusing_sync_session():  # noqa: ANN202
            raise RuntimeError("connection refused")
            yield  # pragma: no cover

        monkeypatch.setattr("app.db.session.sync_session", refusing_sync_session)
        session = start_session(source="0", model_dir=ready, lut_dir=None)
        _await_end(session)
        assert session.status == "stopped", session.error  # the run finished anyway
        assert session.db_rows_failed > 0
        assert session.db_error is not None and "RuntimeError" in session.db_error

    def test_marks_carry_the_wall_clock_for_the_export(
        self, ready: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        written: list = []
        monkeypatch.setattr("app.db.session.sync_session", self._fake_db(written))
        session = start_session(source="0", model_dir=ready, lut_dir=_write_lut(tmp_path))
        _await_end(session)
        assert session.status == "stopped", session.error
        assert session.marks, "the grounded detection must have produced marks"
        mark = session.marks[0]
        assert mark["detected_at"].endswith("Z")
        assert "T" in mark["detected_at_local"]
        rows = detection_service._export_rows(session)
        assert rows[0]["time_utc"] == mark["detected_at"]
        assert rows[0]["time_local"] == mark["detected_at_local"]


class TestOverlayToggles:
    """`set_overlay` — the Boxes/Labels/Tracks chips keep working mid-run."""

    def _session(self) -> DetectionSession:
        session = DetectionSession(
            session_id="overlay-test",
            source="http://cam/stream",
            lut_site=None,
            settings={},
        )
        with detection_service._LOCK:
            detection_service._SESSIONS[session.session_id] = session
        return session

    def _cleanup(self) -> None:
        with detection_service._LOCK:
            detection_service._SESSIONS.pop("overlay-test", None)

    def test_defaults_draw_everything(self) -> None:
        session = self._session()
        try:
            assert session.overlay_boxes and session.overlay_labels and session.overlay_tracks
            # ★ HUD is OPT-IN (2026-09-03): plain boxes until the chip turns it on.
            assert session.overlay_hud is False
        finally:
            self._cleanup()

    def test_hud_toggles_on_and_off_independently(self) -> None:
        session = self._session()
        try:
            detection_service.set_overlay(session.session_id, hud=True)
            assert session.overlay_hud is True
            # It is independent — a Boxes toggle leaves HUD alone.
            detection_service.set_overlay(session.session_id, boxes=False)
            assert session.overlay_hud is True
            detection_service.set_overlay(session.session_id, hud=False)
            assert session.overlay_hud is False
        finally:
            self._cleanup()

    def test_set_overlay_writes_only_what_was_sent(self) -> None:
        """★ None leaves a flag untouched — a chip toggles ONE thing, not all three."""
        session = self._session()
        try:
            detection_service.set_overlay(session.session_id, labels=False)
            assert session.overlay_boxes is True
            assert session.overlay_labels is False
            assert session.overlay_tracks is True
            detection_service.set_overlay(session.session_id, boxes=False, tracks=False)
            assert session.overlay_boxes is False
            assert session.overlay_tracks is False
            # And back on — a toggle is a toggle, not a one-way switch.
            detection_service.set_overlay(session.session_id, boxes=True, labels=True, tracks=True)
            assert session.overlay_boxes and session.overlay_labels and session.overlay_tracks
        finally:
            self._cleanup()

    def test_unknown_session_refuses(self) -> None:
        with pytest.raises(detection_service.DetectionError):
            detection_service.set_overlay("no-such-session", boxes=False)


class TestManualTrackingControl:
    """The service side of manual tracking — the button and the click queue."""

    def _session(self, status: str = "running") -> DetectionSession:
        session = DetectionSession(
            session_id="track-test",
            source="http://cam/stream",
            lut_site=None,
            settings={},
        )
        session.status = status
        with detection_service._LOCK:
            detection_service._SESSIONS[session.session_id] = session
        return session

    def _cleanup(self) -> None:
        with detection_service._LOCK:
            detection_service._SESSIONS.pop("track-test", None)

    def test_tracking_is_armed_from_the_start_and_off_releases_everything(self) -> None:
        # ★ 2026-09-08 (owner decision): the tracker runs WITH detection — no
        #   "Start tracking" ritual — but follows nothing until an object is clicked.
        session = self._session()
        try:
            assert session.tracking_on is True
            assert session.tracked_ids == [] and session.primary_track_id is None
            # Off enqueues a clear for the worker to release the locks.
            detection_service.set_tracking(session.session_id, False)
            assert session.tracking_on is False
            assert {"op": "clear"} in session.track_commands
            detection_service.set_tracking(session.session_id, True)
            assert session.tracking_on is True
        finally:
            self._cleanup()

    def test_a_click_is_accepted_at_once_and_refused_only_after_tracking_is_turned_off(
        self,
    ) -> None:
        session = self._session()
        try:
            detection_service.queue_track_command(
                session.session_id, {"op": "toggle", "u": 1.0, "v": 2.0}
            )
            assert {"op": "toggle", "u": 1.0, "v": 2.0} in session.track_commands
            detection_service.set_tracking(session.session_id, False)
            with pytest.raises(detection_service.DetectionError, match="off for this run"):
                detection_service.queue_track_command(
                    session.session_id, {"op": "toggle", "u": 1.0, "v": 2.0}
                )
        finally:
            self._cleanup()

    def test_tracking_refuses_a_finished_run(self) -> None:
        session = self._session(status="stopped")
        try:
            with pytest.raises(detection_service.DetectionError):
                detection_service.set_tracking(session.session_id, True)
        finally:
            self._cleanup()


class TestSessionListEndpoint:
    """`GET /detection/sessions` — what the camera wall polls (2026-09-02)."""

    def test_lists_every_session_newest_first(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.api.v1 import detection as detection_router

        older = DetectionSession(
            session_id="wall-old", source="http://cam/a", lut_site=None, settings={}
        )
        newer = DetectionSession(
            session_id="wall-new", source="http://cam/b", lut_site=None, settings={}
        )
        from datetime import timedelta

        newer.started_at = older.started_at + timedelta(seconds=5)
        with detection_service._LOCK:
            detection_service._SESSIONS["wall-old"] = older
            detection_service._SESSIONS["wall-new"] = newer
        try:
            app = FastAPI()
            app.include_router(detection_router.router)
            body = TestClient(app).get("/detection/sessions").json()
            ids = [s["session_id"] for s in body["items"]]
            assert ids.index("wall-new") < ids.index("wall-old")  # newest first
            mine = next(s for s in body["items"] if s["session_id"] == "wall-new")
            assert mine["source"] == "http://cam/b"
            assert mine["status"] == "starting"
        finally:
            with detection_service._LOCK:
                detection_service._SESSIONS.pop("wall-old", None)
                detection_service._SESSIONS.pop("wall-new", None)


class TestMarkRate:
    """How often one object becomes a mark (2026-09-11, owner: "the video is slow").

    ★ THE MEASUREMENT BEHIND IT. A run placed a mark for every detection on every
    frame: one tracked car at 25 fps put 605 points on the map in 24 seconds. The
    map draws every one, so the browser — which is also drawing the video — was
    holding thousands of points within a minute. The camera and the detector were
    never the problem; the detector runs on the GPU in about 4 ms a frame.
    """

    def test_one_object_marks_once_per_period_and_the_rest_are_counted(
        self, ready: Path, tmp_path: Path
    ) -> None:
        """★ Seen every frame, marked once a second — and the difference is stated."""
        bundle = _write_lut(tmp_path)
        session = start_session(
            source="0", model_dir=ready, lut_dir=bundle,
            settings_values={"mark_rate_hz": 1.0},
        )
        _await_end(session)
        assert session.status == "stopped", session.error
        assert session.frames_done > 1
        # The fixture's detector puts the SAME object in the same place every
        # frame, so at 1 Hz a short run marks it once or twice, never per frame.
        assert len(session.marks) < session.frames_done
        assert session.marks_thinned > 0
        # Nothing was lost: every detection still counted and still drew.
        assert session.counts["person"] == 2 * session.frames_done

    def test_zero_means_every_frame_for_anyone_who_wants_the_raw_stream(
        self, ready: Path, tmp_path: Path
    ) -> None:
        bundle = _write_lut(tmp_path)
        session = start_session(
            source="0", model_dir=ready, lut_dir=bundle,
            settings_values={"mark_rate_hz": 0},
        )
        _await_end(session)
        assert session.status == "stopped", session.error
        assert len(session.marks) == session.frames_done
        assert session.marks_thinned == 0

    def test_a_moving_object_still_draws_a_trail_when_it_is_not_tracked(self) -> None:
        """★ The key that makes thinning safe for untracked sightings.

        With no track id the clock is keyed by class AND ground cell, so a
        standing object is thinned while a moving one keeps entering new cells
        and keeps marking. Thinning a moving object's trail would erase the
        route, which is the thing a run exists to produce.
        """
        from app.services.detection.models import DetectSettings

        settings = DetectSettings.from_dict({"mark_rate_hz": 1.0})
        gap = 1.0 / settings.mark_rate_hz

        def run(keys: list[object]) -> int:
            """Marks placed for this sequence — each case gets its OWN clock."""
            clock: dict[object, float] = {}
            placed = 0
            for frame, key in enumerate(keys):
                now = frame / 25.0
                last = clock.get(key)
                if last is not None and now - last < gap:
                    continue
                clock[key] = now
                placed += 1
            return placed

        # standing still: one cell for a second of frames, one mark
        assert run([("car", 34.10000, 36.01000)] * 25) == 1
        # moving: a new cell each frame, every one marked — the trail survives
        assert run([("car", 34.10000 + t * 0.0001, 36.01000) for t in range(25)]) == 25
