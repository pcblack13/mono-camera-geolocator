"""The drift watch on a REAL-sized scene (2026-09-09, found on a 1920 px frame).

★ What these pin: the alert threshold is stated at the FAR end of the scene, not
its median; a camera knocked further than the landmark search window reads MOVED
with the angle it implies — never "fog"; fog itself still reads DEGRADED; and the
soak log is capped so a background watch cannot fill the disk.
"""

from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.services import drift_service as ds
from app.tests.test_drift_service import H, K, W, _rotated, _write_bundle


@pytest.fixture()
def bundle(tmp_path: Path) -> Path:
    return _write_bundle(tmp_path)


@pytest.fixture()
def library(tmp_path: Path) -> Path:
    return tmp_path / "drift"


@pytest.fixture(scope="module")
def frame() -> np.ndarray:
    rng = np.random.default_rng(7)
    return cv2.GaussianBlur(rng.integers(0, 255, (H, W), dtype=np.uint8), (5, 5), 0)


class TestFarRangeThreshold:
    def test_the_reference_range_is_the_scenes_far_end(
        self, library: Path, bundle: Path, frame: np.ndarray
    ) -> None:
        rec = ds.freeze_reference(library, bundle, name="x", source="synthetic", frame=frame)
        assert rec["ref_range_m"] > rec["range_median_m"]
        assert rec["ref_range_m"] <= rec["range_max_m"]


class TestLargeMove:
    def test_a_move_beyond_the_search_window_reads_moved_not_fog(
        self, library: Path, bundle: Path, frame: np.ndarray
    ) -> None:
        rec = ds.freeze_reference(library, bundle, name="x", source="synthetic", frame=frame, confirm_n=1)
        mon = ds._monitor_for(library, rec["ref_id"])
        # a rotation that pushes every landmark past ±SEARCH px
        deg = float(np.degrees(np.arctan2(mon.SEARCH * 2.5, K[0, 0])))
        v = ds.check_reference(library, rec["ref_id"], frame=_rotated(frame, deg))
        assert v["state"] == "MOVED", v["why"]
        assert v["status"] == "MOVED" and v["confirmed"] is True
        assert v["large_move_px"] > mon.SEARCH
        assert abs(v["rot_deg"] - deg) / deg < 0.25  # the implied angle is in the right ballpark
        assert "search window" in v["why"]

    def test_a_strong_rotation_seen_by_most_landmarks_reads_moved_even_one_short_of_the_quota(
        self, library: Path, bundle: Path, frame: np.ndarray
    ) -> None:
        # The 0.8° pan on a real 1920 px frame: 9/12 found, 7 agree at SNR 28, the
        # vendor needs 8 → DEGRADED. The service reads the vendor's own numbers.
        rec = ds.freeze_reference(library, bundle, name="x", source="synthetic", frame=frame, confirm_n=1)
        mon = ds._monitor_for(library, rec["ref_id"])
        verdict = {
            "state": "DEGRADED", "n_landmarks": 12, "n_matched": 9, "n_lost": 3,
            "n_inliers": 7, "rot_deg": 0.757, "ground_err_at_ref": 9.76,
            "resid_mean_px": 0.65, "snr": 28.6, "mean_conf": 0.9,
            "why": "only 7 of 12 landmarks agree after culling (need 8)",
        }
        mon._recent.append("DEGRADED")  # what the vendor's _finish just did
        ds._reacquire_large_move(mon, library, rec["ref_id"], frame, verdict)
        assert verdict["state"] == "MOVED" and verdict["status"] == "MOVED"
        assert "7 of 12 landmarks agree" in verdict["why"] and "search window" in verdict["why"]
        assert list(mon._recent) == ["MOVED"]

    def test_a_weak_partial_rotation_stays_degraded(
        self, library: Path, bundle: Path, frame: np.ndarray
    ) -> None:
        rec = ds.freeze_reference(library, bundle, name="x", source="synthetic", frame=frame, confirm_n=1)
        mon = ds._monitor_for(library, rec["ref_id"])
        verdict = {
            "state": "DEGRADED", "n_landmarks": 12, "n_matched": 6, "n_lost": 6,
            "n_inliers": 5, "rot_deg": 0.3, "ground_err_at_ref": 3.0,
            "resid_mean_px": 4.0, "snr": 0.9, "mean_conf": 0.7, "why": "only 5 of 12 agree",
        }
        mon._recent.append("DEGRADED")
        ds._reacquire_large_move(mon, library, rec["ref_id"], frame, verdict)
        assert verdict["state"] == "DEGRADED"

    def test_fog_is_still_degraded(self, library: Path, bundle: Path, frame: np.ndarray) -> None:
        rec = ds.freeze_reference(library, bundle, name="x", source="synthetic", frame=frame, confirm_n=1)
        fog = (cv2.GaussianBlur(frame, (0, 0), 25) * 0.35).astype(np.uint8)
        v = ds.check_reference(library, rec["ref_id"], frame=fog)
        assert v["state"] == "DEGRADED"
        assert "large_move_px" not in v

    def test_the_temporal_window_counts_the_corrected_look_once(
        self, library: Path, bundle: Path, frame: np.ndarray
    ) -> None:
        rec = ds.freeze_reference(library, bundle, name="x", source="synthetic", frame=frame, confirm_n=3)
        mon = ds._monitor_for(library, rec["ref_id"])
        moved = _rotated(frame, float(np.degrees(np.arctan2(mon.SEARCH * 2.5, K[0, 0]))))
        states = [ds.check_reference(library, rec["ref_id"], frame=moved)["status"] for _ in range(3)]
        # two looks: still OK (unconfirmed); the third promotes — exactly confirm_n
        assert states == ["OK", "OK", "MOVED"] or states == [None, None, "MOVED"]
        assert len(mon._recent) == 3 and set(mon._recent) == {"MOVED"}


class TestLogCap:
    def test_an_overfull_log_keeps_its_newest_half(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        ref = "a" * 32
        folder = tmp_path / ref
        folder.mkdir()
        monkeypatch.setattr(ds, "LOG_MAX_BYTES", 2_000)
        for i in range(200):
            ds._append_log(tmp_path, ref, {"kind": "verdict", "i": i, "pad": "x" * 40})
        lines = [json.loads(line) for line in (folder / "log.jsonl").read_text().splitlines()]
        assert (folder / "log.jsonl").stat().st_size <= 2_000
        assert lines[-1]["i"] == 199  # the newest survives
        assert all(b["i"] == a["i"] + 1 for a, b in pairwise(lines))  # whole lines, in order


class TestMoreLandmarksAndTheMeasuredShift:
    def test_a_reference_keeps_more_landmarks_on_a_finer_grid(
        self, library: Path, bundle: Path, frame: np.ndarray
    ) -> None:
        rec = ds.freeze_reference(library, bundle, name="x", source="synthetic", frame=frame)
        assert ds.DRIFT_LANDMARKS == 24
        assert rec["n_landmarks"] >= 16  # the textured synthetic scene offers plenty

    def test_the_status_carries_the_rotation_and_the_range(
        self, library: Path, bundle: Path, frame: np.ndarray
    ) -> None:
        from app.tests.test_drift_service import _rotated

        rec = ds.freeze_reference(library, bundle, name="x", source="shift-src", frame=frame, confirm_n=1)
        run = ds.start_monitor(library, rec["ref_id"], interval_s=60.0, frame_provider=lambda: _rotated(frame, 0.2))
        try:
            import time

            deadline = time.monotonic() + 5.0
            while run.last is None and time.monotonic() < deadline:
                time.sleep(0.05)
            latest = ds.latest_status_for_source("shift-src")
            assert latest is not None
            assert latest["rot_deg"] == pytest.approx(0.2, abs=0.02)
            assert latest["ref_range_m"] == pytest.approx(rec["ref_range_m"])
        finally:
            ds.stop_monitor(rec["ref_id"])

    def test_the_ground_shift_is_rotation_times_the_marks_own_range(self) -> None:
        from app.services.detection_service import ground_shift_m

        camera = (34.10728, 36.01746)
        near = (34.10818, 36.01746)  # ~100 m north
        far = (34.11628, 36.01746)  # ~1000 m north
        assert ground_shift_m(0.1, camera, *near) == pytest.approx(0.17, abs=0.02)
        assert ground_shift_m(0.1, camera, *far) == pytest.approx(1.75, abs=0.05)
        assert ground_shift_m(None, camera, *near) is None
        assert ground_shift_m(0.1, None, *near) is None
