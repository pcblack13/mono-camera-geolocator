"""The camera's own drift watch (2026-09-08, owner decision).

★ What these pin: the reference is frozen on THE CAMERA'S FRAME (the photograph
the control points sit on) with the camera's lookup table, and a background
watch starts on it at once; a re-freeze retires the previous watch; every
refusal names the missing piece — the table, the frame, or the pose.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from app.services import drift_service
from app.services.camera_service import DRIFT_WATCH_INTERVAL_S, refreeze_drift_watch
from app.tests.test_drift_service import H, W, _write_bundle


@pytest.fixture()
def settings(tmp_path: Path) -> SimpleNamespace:
    lut_root = tmp_path / "lut"
    lut_root.mkdir()
    _write_bundle(lut_root)  # → <lut_root>/synthetic_lut, site "synthetic"
    return SimpleNamespace(lut_output_dir=lut_root, drift_output_dir=tmp_path / "drift")


@pytest.fixture()
def frame_file(tmp_path: Path) -> Path:
    rng = np.random.default_rng(7)
    img = cv2.GaussianBlur(rng.integers(0, 255, (H, W), dtype=np.uint8), (5, 5), 0)
    path = tmp_path / "frame.png"
    cv2.imwrite(str(path), img)
    return path


def _freeze(settings: SimpleNamespace, frame_file: Path | None, **over: object) -> dict:
    kwargs: dict = {
        "camera_id": "cam-1",
        "name": "Gate",
        "source": "synthetic",
        "lut_site": "synthetic",
        "image_path": frame_file,
        "image_label": "frame.png",
        "fov_deg": None,
        "previous_ref_id": None,
    }
    kwargs.update(over)
    return refreeze_drift_watch(settings, **kwargs)


class TestRefusals:
    def test_no_table_yet_says_when_the_watch_starts(
        self, settings: SimpleNamespace, frame_file: Path
    ) -> None:
        with pytest.raises(drift_service.DriftError, match="once the lookup table is built"):
            _freeze(settings, frame_file, lut_site=None)

    def test_an_unknown_table_is_named(self, settings: SimpleNamespace, frame_file: Path) -> None:
        with pytest.raises(drift_service.DriftError, match="no lookup table named 'elsewhere'"):
            _freeze(settings, frame_file, lut_site="elsewhere")

    def test_no_frame_asks_for_one(self, settings: SimpleNamespace) -> None:
        with pytest.raises(drift_service.DriftError, match="capture one and place"):
            _freeze(settings, None)

    def test_a_data_only_camera_has_nothing_to_watch(
        self, settings: SimpleNamespace, frame_file: Path
    ) -> None:
        with pytest.raises(drift_service.DriftError, match="no video source"):
            _freeze(settings, frame_file, source="")

    def test_a_table_without_intrinsics_needs_the_cameras_fov(
        self, tmp_path: Path, frame_file: Path
    ) -> None:
        lut_root = tmp_path / "lut2"
        lut_root.mkdir()
        _write_bundle(lut_root, drop_pose_keys=("K",))
        settings = SimpleNamespace(lut_output_dir=lut_root, drift_output_dir=tmp_path / "d2")
        with pytest.raises(drift_service.DriftError, match="field of view"):
            _freeze(settings, frame_file)


class TestFreezeAndWatch:
    def test_the_frame_is_the_reference_and_the_watch_runs_in_the_background(
        self, settings: SimpleNamespace, frame_file: Path
    ) -> None:
        outcome = _freeze(settings, frame_file)
        try:
            assert outcome["watching"] is True
            assert outcome["n_landmarks"] > 0
            assert outcome["interval_s"] == DRIFT_WATCH_INTERVAL_S
            # the durable record says where it was frozen from — the photograph
            rec = drift_service.read_reference(settings.drift_output_dir, outcome["ref_id"])
            assert rec["frozen_from"] == "image"
            assert rec["frozen_from_label"] == "frame.png"
            assert rec["source"] == "synthetic"  # later checks read the LIVE camera
            run = drift_service.get_monitor(outcome["ref_id"])
            assert run is not None and run.status == "running"
        finally:
            drift_service.stop_monitor(outcome["ref_id"])

    def test_refreezing_retires_the_previous_watch(
        self, settings: SimpleNamespace, frame_file: Path
    ) -> None:
        first = _freeze(settings, frame_file)
        second = _freeze(settings, frame_file, previous_ref_id=first["ref_id"])
        try:
            assert second["ref_id"] != first["ref_id"]
            old = drift_service.get_monitor(first["ref_id"])
            assert old is not None and old.status == "stopped"
            new = drift_service.get_monitor(second["ref_id"])
            assert new is not None and new.status == "running"
        finally:
            drift_service.stop_monitor(first["ref_id"])
            drift_service.stop_monitor(second["ref_id"])
