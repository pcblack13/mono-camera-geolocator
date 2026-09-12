"""``drift_service`` — the bridge in front of the vendored camera drift monitor.

Two kinds of test, the ``test_detection_service`` pattern:

1. **The vendor's verdicts, on OUR terms.** A synthetic scene with a known pose
   and a flat world, nudged by exact warps: a small rotation must come back
   MOVED (the Jira nudge test, automated), a zoom must come back CHANGED, a
   blinded view DEGRADED, and a clean frame OK. The vendored core carries its
   own docstring claims; these pin them against the tuning THIS service applies.
2. **The bridge itself.** A real (synthetic) LUT bundle on disk → freeze →
   library record → check → delete: the manifest-to-monitor translation, the
   ray-reconstructed Z (validated by the freeze-time reprojection self-check),
   the refusals with the fix named, and the traversal-proof ref ids.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from app.services import drift_service
from app.services.drift_service import DriftError, check_reference, freeze_reference
from app.vendor.drift_monitor import CHANGED, DEGRADED, MOVED, OK, DriftMonitor

# ─────────────────────────────────────────────────────────────────────────────
# The synthetic scene: a camera 50 m up, tilted 45° down at flat ground (Z=0)
# ─────────────────────────────────────────────────────────────────────────────

W, H = 640, 360
K = np.array([[800.0, 0.0, 320.0], [0.0, 800.0, 180.0], [0.0, 0.0, 1.0]])
#: EPSG:32637 metres — a real UTM neighbourhood so the lat/lon roundtrip is honest.
C = np.array([500_000.0, 3_777_000.0, 50.0])

_th = np.radians(45.0)
#: rows = camera right / down / forward axes in world coords (det = +1).
R_REF = np.array(
    [
        [1.0, 0.0, 0.0],
        [0.0, -np.sin(_th), -np.cos(_th)],
        [0.0, np.cos(_th), -np.sin(_th)],
    ]
)


def _world_grid() -> tuple[np.ndarray, np.ndarray]:
    """Per-pixel ground XYZ by ray↔plane(Z=0), vectorised. Returns (X, Y)."""
    uu, vv = np.meshgrid(np.arange(W, dtype=float), np.arange(H, dtype=float))
    b = np.stack([(uu - K[0, 2]) / K[0, 0], (vv - K[1, 2]) / K[1, 1], np.ones_like(uu)], axis=-1)
    b /= np.linalg.norm(b, axis=-1, keepdims=True)
    d = b @ R_REF  # row-vector form of R.T @ b
    t = -C[2] / d[..., 2]
    return C[0] + t * d[..., 0], C[1] + t * d[..., 1]


def world_of(u: float, v: float) -> tuple[float, float, float] | None:
    """The host-engine callback, closed form, for the pure-monitor tests."""
    n = np.array([(u - K[0, 2]) / K[0, 0], (v - K[1, 2]) / K[1, 1], 1.0])
    d = R_REF.T @ (n / np.linalg.norm(n))
    if d[2] >= 0:
        return None
    t = -C[2] / d[2]
    p = C + t * d
    return (float(p[0]), float(p[1]), 0.0)


@pytest.fixture(scope="module")
def frame() -> np.ndarray:
    """Reproducible textured ground: blurred noise has corners everywhere."""
    rng = np.random.default_rng(7)
    img = rng.integers(0, 255, (H, W), dtype=np.uint8)
    return cv2.GaussianBlur(img, (5, 5), 0)


def _rotated(img: np.ndarray, deg: float) -> np.ndarray:
    """The nudge: the same scene seen by a camera pitched ``deg`` about its
    right axis — an exact homography, so the ground truth is known."""
    a = np.radians(deg)
    r_delta = np.array(
        [[1, 0, 0], [0, np.cos(a), -np.sin(a)], [0, np.sin(a), np.cos(a)]], dtype=float
    )
    hmat = K @ r_delta @ np.linalg.inv(K)
    return cv2.warpPerspective(img, hmat, (W, H))


def _zoomed(img: np.ndarray, s: float) -> np.ndarray:
    """A focal change about the principal point — no rotation explains it."""
    hmat = np.array(
        [[s, 0, K[0, 2] * (1 - s)], [0, s, K[1, 2] * (1 - s)], [0, 0, 1]], dtype=float
    )
    return cv2.warpPerspective(img, hmat, (W, H))


def _monitor(confirm_n: int = 1, alert_ground_m: float = 0.5) -> DriftMonitor:
    mon = DriftMonitor(K, None, ref_range=200.0, alert_ground_m=alert_ground_m, confirm_n=confirm_n)
    return mon


# ─────────────────────────────────────────────────────────────────────────────
# 1 — the verdicts
# ─────────────────────────────────────────────────────────────────────────────


class TestVerdicts:
    def test_a_clean_frame_is_ok(self, frame: np.ndarray) -> None:
        mon = _monitor()
        assert mon.setup(frame, world_of, C, R_REF) >= mon.MIN_INLIERS
        r = mon.check(frame)
        assert r["state"] == OK
        assert r["rot_deg"] < 0.02

    def test_the_nudge_fires_moved_with_the_right_magnitude(self, frame: np.ndarray) -> None:
        # ★ THE JIRA NUDGE TEST: 0.3° at 200 m = 1.05 m of ground error, over the
        #   0.5 m threshold — and the solved angle must be the injected one.
        mon = _monitor()
        mon.setup(frame, world_of, C, R_REF)
        r = mon.check(_rotated(frame, 0.3))
        assert r["state"] == MOVED
        assert r["rot_deg"] == pytest.approx(0.3, abs=0.05)

    def test_a_zoom_is_changed_not_ok(self, frame: np.ndarray) -> None:
        # ★ The vendor's reason for existing: a zoom produces ≈0° of rotation and
        #   an entirely broken mapping. OK here would be the dangerous lie.
        mon = _monitor()
        mon.setup(frame, world_of, C, R_REF)
        r = mon.check(_zoomed(frame, 1.03))
        assert r["state"] == CHANGED
        assert r["snr"] < mon.MIN_SNR

    def test_a_blinded_view_is_degraded_not_an_alert(self, frame: np.ndarray) -> None:
        mon = _monitor()
        mon.setup(frame, world_of, C, R_REF)
        r = mon.check(np.zeros_like(frame))
        assert r["state"] == DEGRADED

    def test_a_resized_frame_is_refused(self, frame: np.ndarray) -> None:
        mon = _monitor()
        mon.setup(frame, world_of, C, R_REF)
        with pytest.raises(ValueError, match="size must match"):
            mon.check(cv2.resize(frame, (W // 2, H // 2)))

    def test_temporal_confirmation_needs_three_in_a_row(self, frame: np.ndarray) -> None:
        # ★ Alert on `status`, log `state`: one nudged frame must NOT flip the
        #   confirmed status; the third consecutive one must.
        mon = _monitor(confirm_n=3)
        mon.setup(frame, world_of, C, R_REF)
        nudged = _rotated(frame, 0.3)
        assert mon.check(frame)["status"] == OK
        assert mon.check(nudged)["status"] == OK  # raw MOVED, suppressed
        assert mon.check(nudged)["status"] == OK
        third = mon.check(nudged)
        assert third["status"] == MOVED
        assert third["confirmed"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 2 — the bridge: LUT bundle → freeze → library → check
# ─────────────────────────────────────────────────────────────────────────────


def _write_bundle(root: Path, *, drop_pose_keys: tuple[str, ...] = ()) -> Path:
    """A synthetic-but-real LUT bundle: full-resolution lat/lon arrays computed
    from the same pose the monitor will be handed, manifest spelled like the
    generator's."""
    from gis.crs import get_transformer

    folder = root / "synthetic_lut"
    folder.mkdir(parents=True, exist_ok=True)
    x, y = _world_grid()
    lon, lat = get_transformer("EPSG:32637", "EPSG:4326").transform(x.ravel(), y.ravel())
    np.save(folder / "lat.npy", lat.reshape(H, W))
    np.save(folder / "lon.npy", lon.reshape(H, W))
    pose = {
        "R": R_REF.tolist(),
        "C": C.tolist(),
        "K": K.tolist(),
        "dist": [0.0, 0.0, 0.0, 0.0, 0.0],
        "image_width": W,
        "image_height": H,
    }
    for key in drop_pose_keys:
        pose.pop(key, None)
    manifest = {
        "schema_version": "1.0",
        "site_name": "synthetic",
        "image": {"width": W, "height": H},
        "dem": {"file": "synthetic.tif", "epsg": 32637},
        "pose": pose,
    }
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return folder


@pytest.fixture()
def bundle(tmp_path: Path) -> Path:
    return _write_bundle(tmp_path)


@pytest.fixture()
def library(tmp_path: Path) -> Path:
    return tmp_path / "drift"


class TestBridge:
    def test_freeze_writes_the_record_and_the_z_reconstruction_holds(
        self, frame: np.ndarray, bundle: Path, library: Path
    ) -> None:
        rec = freeze_reference(
            library, bundle, name="tower cam", source="synthetic", frame=frame
        )
        folder = library / rec["ref_id"]
        assert (folder / "landmarks.npz").is_file()
        assert (folder / "reference.json").is_file()
        assert (folder / "reference.jpg").is_file()
        assert rec["n_landmarks"] >= 5
        assert rec["lut_site"] == "synthetic"
        # ★ The freeze-time self-check closes the loop on world_of: LUT lat/lon →
        #   metres → ray-reconstructed Z → reprojected through the trusted pose
        #   must land back on the pixel (≤ the LUT's one-cell quantisation).
        assert rec["ref_reproj_mean_px"] < 2.0
        # threshold stated at the scene's actual range — its FAR end (2026-09-09:
        # the 90th percentile of landmark range), never a nominal kilometre
        assert rec["range_median_m"] <= rec["ref_range_m"] <= rec["range_max_m"]
        assert rec["ref_range_m"] != pytest.approx(1000.0)

    def test_check_ok_then_the_nudge_fires_through_the_service(
        self, frame: np.ndarray, bundle: Path, library: Path
    ) -> None:
        rec = freeze_reference(
            library,
            bundle,
            name="",
            source="synthetic",
            alert_ground_m=0.2,
            confirm_n=1,
            frame=frame,
        )
        ok = check_reference(library, rec["ref_id"], frame=frame)
        assert ok["state"] == OK
        moved = check_reference(library, rec["ref_id"], frame=_rotated(frame, 0.5))
        assert moved["state"] == MOVED
        assert moved["status"] == MOVED  # confirm_n=1 promotes immediately
        assert "camera rotated" in moved["why"]
        assert "R_now" not in moved  # internal matrix, not a wire field

    def test_scan_lists_and_delete_removes(
        self, frame: np.ndarray, bundle: Path, library: Path
    ) -> None:
        rec = freeze_reference(library, bundle, name="x", source="synthetic", frame=frame)
        assert [r["ref_id"] for r in drift_service.scan_references(library)] == [rec["ref_id"]]
        assert drift_service.delete_reference(library, rec["ref_id"]) is True
        assert drift_service.scan_references(library) == []
        with pytest.raises(DriftError, match="no such"):
            check_reference(library, rec["ref_id"], frame=frame)

    def test_a_featureless_view_is_refused_with_the_reason(
        self, bundle: Path, library: Path
    ) -> None:
        flat = np.full((H, W), 128, dtype=np.uint8)
        with pytest.raises(DriftError, match="featureless"):
            freeze_reference(library, bundle, name="x", source="s", frame=flat)

    def test_an_aspect_mismatch_is_a_refusal_not_a_bend(
        self, bundle: Path, library: Path
    ) -> None:
        # 4:3 frame against a 16:9 LUT: a crop or another profile — never rescaled.
        wrong = np.zeros((480, 640), dtype=np.uint8)
        with pytest.raises(DriftError, match="aspect ratio"):
            freeze_reference(library, bundle, name="x", source="s", frame=wrong)

    def test_a_poseless_manifest_names_what_is_missing(
        self, frame: np.ndarray, tmp_path: Path, library: Path
    ) -> None:
        bare = _write_bundle(tmp_path / "bare", drop_pose_keys=("R", "K"))
        with pytest.raises(DriftError, match=r"missing: R, K"):
            freeze_reference(library, bare, name="x", source="s", frame=frame)

    def test_ref_ids_are_traversal_proof(self, library: Path) -> None:
        with pytest.raises(DriftError, match="not a drift reference id"):
            drift_service.read_reference(library, "../../etc/passwd")


# ─────────────────────────────────────────────────────────────────────────────
# 3 — the monitor loop: check every interval, without owning the camera
# ─────────────────────────────────────────────────────────────────────────────


def _wait_for(cond, timeout: float = 5.0) -> None:  # noqa: ANN001 — a predicate
    deadline = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached in time")
        time.sleep(0.01)


class TestMonitorLoop:
    @pytest.fixture()
    def ref(self, frame: np.ndarray, bundle: Path, library: Path) -> str:
        rec = freeze_reference(
            library,
            bundle,
            name="loop",
            source="synthetic",
            alert_ground_m=0.2,
            confirm_n=1,
            frame=frame,
        )
        return str(rec["ref_id"])

    def test_the_loop_accumulates_verdicts_and_stops(
        self, frame: np.ndarray, library: Path, ref: str
    ) -> None:
        run = drift_service.start_monitor(
            library, ref, interval_s=0.05, frame_provider=lambda: frame
        )
        try:
            _wait_for(lambda: run.checks_done >= 3)
            assert run.status == "running"
            assert run.last is not None and run.last["state"] == OK
            assert run.last["via"] == "provider"
            assert len(run.history) >= 3
        finally:
            out = drift_service.stop_monitor(ref)
        assert out is not None and out.status == "stopped"

    def test_the_nudge_promotes_through_the_loop(
        self, frame: np.ndarray, library: Path, ref: str
    ) -> None:
        nudged = _rotated(frame, 0.5)
        run = drift_service.start_monitor(
            library, ref, interval_s=0.05, frame_provider=lambda: nudged
        )
        try:
            _wait_for(lambda: run.last is not None and run.last["status"] == MOVED)
        finally:
            drift_service.stop_monitor(ref)

    def test_a_capture_failure_is_a_tick_not_a_death(
        self, frame: np.ndarray, library: Path, ref: str
    ) -> None:
        # ★ The camera being busy (preview holds it, device unplugged for a
        #   moment) must not kill the loop — and recovery must clear the error.
        box = {"fail": True}

        def provider() -> np.ndarray:
            if box["fail"]:
                raise RuntimeError("camera busy")
            return frame

        run = drift_service.start_monitor(library, ref, interval_s=0.05, frame_provider=provider)
        try:
            _wait_for(lambda: run.capture_failures >= 2)
            assert run.status == "running"
            assert run.last_error is not None and "no frame" in run.last_error
            box["fail"] = False
            _wait_for(lambda: run.checks_done >= 1)
            assert run.last_error is None
        finally:
            drift_service.stop_monitor(ref)

    def test_a_profile_change_fails_the_run_with_the_remedy(
        self, frame: np.ndarray, library: Path, ref: str
    ) -> None:
        # ★ Wrong-size frames are terminal, not a tick: repeating the same
        #   failure every interval would be an alarm clock, not a monitor.
        small = cv2.resize(frame, (W // 2, H // 2))
        run = drift_service.start_monitor(
            library, ref, interval_s=0.05, frame_provider=lambda: small
        )
        try:
            _wait_for(lambda: run.status == "failed")
            assert run.last_error is not None and "freeze a new reference" in run.last_error
        finally:
            drift_service.stop_monitor(ref)

    def test_the_detectors_tap_is_preferred_over_opening_the_camera(
        self, frame: np.ndarray, bundle: Path, library: Path
    ) -> None:
        # ★ One camera, one opener: while a detection session runs on the same
        #   source, the loop must borrow its reader's frame, not fight for the
        #   device.
        from app.services import detection_service

        rec = freeze_reference(
            library, bundle, name="tap", source="synthetic-live", confirm_n=1, frame=frame
        )
        session = detection_service.DetectionSession(
            session_id="t-drift-tap", source="synthetic-live", lut_site=None, settings={}
        )
        session.status = "running"
        session.latest_raw, session.latest_raw_t = frame, time.monotonic()
        detection_service._SESSIONS["t-drift-tap"] = session
        try:
            run = drift_service.start_monitor(library, rec["ref_id"], interval_s=0.05)
            _wait_for(lambda: run.checks_done >= 1)
            assert run.last is not None and run.last["via"] == "detector"
        finally:
            drift_service.stop_monitor(rec["ref_id"])
            detection_service._SESSIONS.pop("t-drift-tap", None)

    def test_a_stale_tap_is_refused(self, frame: np.ndarray) -> None:
        # ★ A wedged reader must read as "no frame", not as a fresh look at the
        #   camera — judging drift from a stuck picture reports the past.
        from app.services import detection_service

        session = detection_service.DetectionSession(
            session_id="t-drift-stale", source="stale-live", lut_site=None, settings={}
        )
        session.status = "running"
        session.latest_raw, session.latest_raw_t = frame, time.monotonic()
        detection_service._SESSIONS["t-drift-stale"] = session
        try:
            assert detection_service.latest_raw_frame("stale-live") is not None
            session.latest_raw_t = time.monotonic() - 10.0
            assert detection_service.latest_raw_frame("stale-live") is None
            assert detection_service.latest_raw_frame("never-seen") is None
        finally:
            detection_service._SESSIONS.pop("t-drift-stale", None)

    def test_stored_clips_are_not_monitorable(
        self, frame: np.ndarray, bundle: Path, library: Path
    ) -> None:
        rec = freeze_reference(
            library, bundle, name="clip", source="video:abc", frame=frame
        )
        with pytest.raises(DriftError, match="does not drift"):
            drift_service.start_monitor(library, rec["ref_id"])

    def test_looks_are_logged_durably_for_the_soak_report(
        self, frame: np.ndarray, library: Path, ref: str
    ) -> None:
        # ★ The in-memory ring dies with the process; the validation day's record
        #   must not. Every verdict and every failed look lands in log.jsonl.
        run = drift_service.start_monitor(
            library, ref, interval_s=0.05, frame_provider=lambda: frame
        )
        try:
            _wait_for(lambda: run.checks_done >= 2)
        finally:
            drift_service.stop_monitor(ref)
        log = (library / ref / "log.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(log) >= 2
        assert all('"kind": "verdict"' in line for line in log)

    def test_double_start_is_refused_and_delete_stops_the_run(
        self, frame: np.ndarray, library: Path, ref: str
    ) -> None:
        run = drift_service.start_monitor(
            library, ref, interval_s=0.05, frame_provider=lambda: frame
        )
        try:
            with pytest.raises(DriftError, match="already being monitored"):
                drift_service.start_monitor(library, ref, frame_provider=lambda: frame)
        finally:
            assert drift_service.delete_reference(library, ref) is True
        assert run.status in ("stopped", "failed")
        assert drift_service.get_monitor(ref) is None


# ─────────────────────────────────────────────────────────────────────────────
# 3b — the review fixes: borrow-don't-fight, no orphan watches, honest clip time
# ─────────────────────────────────────────────────────────────────────────────


class TestReviewFixes:
    def test_refreezing_a_source_retires_its_old_watch(
        self, frame: np.ndarray, bundle: Path, library: Path
    ) -> None:
        # ★ The reported bug: re-freeze made the old watch INVISIBLE (the UI
        #   follows the newest reference) while it kept waking the camera.
        old = freeze_reference(library, bundle, name="old", source="synthetic", frame=frame)
        run = drift_service.start_monitor(
            library, old["ref_id"], interval_s=0.05, frame_provider=lambda: frame
        )
        try:
            _wait_for(lambda: run.checks_done >= 1)
            freeze_reference(library, bundle, name="new", source="synthetic", frame=frame)
            _wait_for(lambda: run.status == "stopped")
        finally:
            drift_service.stop_monitor(old["ref_id"])

    def test_freeze_and_check_borrow_a_running_detectors_frame(
        self, frame: np.ndarray, bundle: Path, library: Path
    ) -> None:
        # ★ 'tap-live' is not an openable source — success PROVES the frames were
        #   borrowed from the running session, not fought for at the device.
        from app.services import detection_service

        session = detection_service.DetectionSession(
            session_id="t-drift-freeze-tap", source="tap-live", lut_site=None, settings={}
        )
        session.status = "running"
        session.latest_raw, session.latest_raw_t = frame, time.monotonic()
        detection_service._SESSIONS["t-drift-freeze-tap"] = session
        try:
            rec = freeze_reference(library, bundle, name="tap", source="tap-live", confirm_n=1)
            assert rec["n_landmarks"] >= 5
            assert check_reference(library, rec["ref_id"])["state"] == OK
        finally:
            detection_service._SESSIONS.pop("t-drift-freeze-tap", None)

    def test_freeze_borrows_the_panels_own_preview(
        self, frame: np.ndarray, bundle: Path, library: Path
    ) -> None:
        # ★ The primary flow: the surveyor WATCHES the preview while aiming, then
        #   presses Freeze. The server already holds the device for that preview —
        #   the freeze must borrow its picture, not lose a fight with it.
        from app.services import live_stream_service

        ok, jpg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        assert ok
        live_stream_service._LAST_FRAME["preview-live"] = jpg.tobytes()
        live_stream_service._LAST_FRAME_T["preview-live"] = time.monotonic()
        try:
            rec = freeze_reference(library, bundle, name="pv", source="preview-live")
            assert rec["n_landmarks"] >= 5
        finally:
            live_stream_service._LAST_FRAME.pop("preview-live", None)
            live_stream_service._LAST_FRAME_T.pop("preview-live", None)

    def test_a_clip_is_judged_at_the_chosen_second(
        self, frame: np.ndarray, bundle: Path, library: Path, tmp_path: Path
    ) -> None:
        # ★ The tautology fix: 0–1 s of the clip is the frozen view, 1–2 s is the
        #   same view nudged 0.5°. Judging "at t" must see exactly that.
        clip = tmp_path / "clip.avi"
        writer = cv2.VideoWriter(
            str(clip), cv2.VideoWriter_fourcc(*"MJPG"), 25.0, (W, H), isColor=True
        )
        assert writer.isOpened()
        bgr = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        nudged = cv2.cvtColor(_rotated(frame, 0.5), cv2.COLOR_GRAY2BGR)
        for _ in range(25):
            writer.write(bgr)
        for _ in range(25):
            writer.write(nudged)
        writer.release()

        rec = freeze_reference(
            library,
            bundle,
            name="clip",
            source="video:clip",
            alert_ground_m=0.2,
            confirm_n=1,
            file_path=clip,
            at_s=0,
        )
        # ★ The seconds are RECORDED, so a run of "perfect" verdicts can later be
        #   told apart from a run of self-comparisons (the field-day trap).
        assert rec["frozen_at_s"] == 0.0
        ok_verdict = check_reference(library, rec["ref_id"], file_path=clip, at_s=0.2)
        assert ok_verdict["state"] == OK
        assert ok_verdict["at_s"] == 0.2
        moved = check_reference(library, rec["ref_id"], file_path=clip, at_s=1.5)
        assert moved["state"] == MOVED
        assert moved["rot_deg"] == pytest.approx(0.5, abs=0.08)
        assert moved["at_s"] == 1.5

    def test_verdicts_carry_the_overlay_geometry(
        self, frame: np.ndarray, bundle: Path, library: Path
    ) -> None:
        # ★ The live overlay draws the FROZEN frame's outline inside the current
        #   one: the frame edge at zero drift, sliding off as the camera turns.
        rec = freeze_reference(
            library, bundle, name="ov", source="synthetic", confirm_n=1, frame=frame
        )
        unit = [[0, 0], [1, 0], [1, 1], [0, 1]]
        same = check_reference(library, rec["ref_id"], frame=frame)
        assert (same["frame_w"], same["frame_h"]) == (W, H)
        assert len(same["outline"]) == 4
        for got, want in zip(same["outline"], unit, strict=True):
            assert got == pytest.approx(want, abs=2e-3)
        assert len(same["landmarks"]) == rec["n_landmarks"]
        assert all(p["x"] is not None for p in same["landmarks"])

        moved = check_reference(library, rec["ref_id"], frame=_rotated(frame, 0.5))
        # a pitch slides the whole outline vertically — all corners together
        dy = [c[1] - w[1] for c, w in zip(moved["outline"], unit, strict=True)]
        assert abs(dy[0]) > 0.005
        assert dy[0] == pytest.approx(dy[1], abs=1e-3)

    def test_live_references_record_no_second(
        self, frame: np.ndarray, bundle: Path, library: Path
    ) -> None:
        rec = freeze_reference(library, bundle, name="live", source="synthetic", frame=frame)
        assert rec["frozen_at_s"] is None
        assert check_reference(library, rec["ref_id"], frame=frame)["at_s"] is None


# ─────────────────────────────────────────────────────────────────────────────
# 3c — the wire boundary: every service output must FIT its wire model
# ─────────────────────────────────────────────────────────────────────────────


class TestWireShapes:
    """★ The 2026-08-24 field report: `ApiModel` is extra='forbid', and the freeze
    record's honest bookkeeping keys (patch_px, monitor_version, …) 500'd every
    listing — a gap no test crossed, because none walked service output into the
    wire models. These do, through the same `fit` the router uses."""

    def test_records_verdicts_and_reports_all_fit_the_wire(
        self, frame: np.ndarray, bundle: Path, library: Path
    ) -> None:
        from app.schemas.drift import (
            DriftReferenceRead,
            DriftSoakReport,
            DriftVerdictRead,
            fit,
        )

        rec = freeze_reference(
            library, bundle, name="wire", source="synthetic", confirm_n=1, frame=frame
        )
        read = fit(DriftReferenceRead, rec)
        assert read.ref_id == rec["ref_id"]

        # a solved verdict AND a degraded one — their key sets differ
        solved = check_reference(library, rec["ref_id"], frame=_rotated(frame, 0.5))
        degraded = check_reference(library, rec["ref_id"], frame=np.zeros_like(frame))
        for verdict in (solved, degraded):
            wire = fit(DriftVerdictRead, verdict)
            assert wire.state == verdict["state"]

        report = drift_service.soak_report(library, rec["ref_id"])
        assert DriftSoakReport(**report).checks == 2

    def test_fit_still_rejects_a_genuinely_wrong_record(self) -> None:
        # ★ `fit` ignores EXTRA keys — it must not also paper over a missing or
        #   mistyped required one. Honesty cuts both ways.
        import pytest as _pytest
        from pydantic import ValidationError

        from app.schemas.drift import DriftReferenceRead, fit

        with _pytest.raises(ValidationError):
            fit(DriftReferenceRead, {"ref_id": "x", "unrelated": 1})


# ─────────────────────────────────────────────────────────────────────────────
# 4 — the lighting soak, answered synthetically before the field day
# ─────────────────────────────────────────────────────────────────────────────


def _gamma(img: np.ndarray, g: float) -> np.ndarray:
    return np.clip(255.0 * (img / 255.0) ** g, 0, 255).astype(np.uint8)


def _exposure(img: np.ndarray, gain: float, offset: float) -> np.ndarray:
    return np.clip(img.astype(np.float32) * gain + offset, 0, 255).astype(np.uint8)


def _noisy(img: np.ndarray, sigma: float) -> np.ndarray:
    rng = np.random.default_rng(3)
    return np.clip(img.astype(np.float32) + rng.normal(0, sigma, img.shape), 0, 255).astype(
        np.uint8
    )


class TestLighting:
    """★ README limitation #6: validation to date is synthetic, and a field day is
    Phase 4's whole point. These pin what the soak SHOULD show — normalised
    cross-correlation shrugs at global illumination changes — so a sunrise false
    alarm in the field points at shadows/scene, not at the matcher's arithmetic."""

    def test_global_lighting_changes_do_not_raise_alarms(self, frame: np.ndarray) -> None:
        mon = _monitor()
        mon.setup(frame, world_of, C, R_REF)
        for name, lit in [
            ("dusk gamma", _gamma(frame, 1.6)),
            ("morning gamma", _gamma(frame, 0.6)),
            ("overexposed", _exposure(frame, 1.3, 20)),
            ("underexposed", _exposure(frame, 0.7, -15)),
            ("sensor noise", _noisy(frame, 6)),
        ]:
            r = mon.check(lit)
            assert r["state"] == OK, f"{name}: {r['why']}"

    def test_night_is_degraded_not_an_alarm(self, frame: np.ndarray) -> None:
        # ★ Found while writing this: pure dimming is NOT darkness — NCC
        #   re-normalises, so structure at 5% amplitude still matches (correct!).
        #   Real night is the signal crushed BELOW the sensor's noise floor, so
        #   that is what is modelled: 2% signal under σ=6 noise.
        mon = _monitor()
        mon.setup(frame, world_of, C, R_REF)
        assert mon.check(_noisy(_exposure(frame, 0.02, 0), 6))["state"] == DEGRADED

    def test_a_nudge_is_still_seen_through_a_lighting_change(self, frame: np.ndarray) -> None:
        # ★ The compound case the field will actually produce: the camera drifts
        #   AND the evening light has shifted. The alarm must not hide behind the
        #   lighting change.
        mon = _monitor()
        mon.setup(frame, world_of, C, R_REF)
        r = mon.check(_noisy(_gamma(_rotated(frame, 0.3), 1.4), 4))
        assert r["state"] == MOVED
        assert r["rot_deg"] == pytest.approx(0.3, abs=0.08)


# ─────────────────────────────────────────────────────────────────────────────
# 5 — the soak report
# ─────────────────────────────────────────────────────────────────────────────


class TestSoakReport:
    def test_the_day_is_summarised_faithfully(
        self, frame: np.ndarray, bundle: Path, library: Path
    ) -> None:
        rec = freeze_reference(
            library,
            bundle,
            name="soak",
            source="synthetic",
            alert_ground_m=0.2,
            confirm_n=3,
            frame=frame,
        )
        ref = rec["ref_id"]
        nudged = _rotated(frame, 0.5)
        check_reference(library, ref, frame=frame)  # OK
        for _ in range(3):  # third consecutive MOVED promotes the status
            check_reference(library, ref, frame=nudged)
        check_reference(library, ref, frame=_noisy(_exposure(frame, 0.02, 0), 6))  # DEGRADED
        for _ in range(2):  # two failed looks, as the monitor loop would log them
            drift_service._append_log(
                library,
                ref,
                {"kind": "no_frame", "checked_utc": "2026-08-24T23:59:00Z", "error": "busy"},
            )

        report = drift_service.soak_report(library, ref)
        assert report["checks"] == 5
        assert report["no_frame"] == 2
        assert report["states"] == {"OK": 1, "MOVED": 3, "DEGRADED": 1}
        assert [a["status"] for a in report["confirmed_alerts"]] == ["MOVED"]
        # a sustained alarm is ONE episode, not three rows
        assert [(e["state"], e["checks"]) for e in report["episodes"]] == [
            ("MOVED", 3),
            ("DEGRADED", 1),
        ]
        assert report["episodes"][0]["max_rot_deg"] == pytest.approx(0.5, abs=0.05)
        assert report["rot_ok_max_deg"] is not None
        assert sum(h["ok"] + h["moved"] + h["degraded"] + h["no_frame"] for h in report["hourly"]) == 7

    def test_a_fresh_reference_reports_an_empty_day(
        self, frame: np.ndarray, bundle: Path, library: Path
    ) -> None:
        rec = freeze_reference(library, bundle, name="new", source="synthetic", frame=frame)
        report = drift_service.soak_report(library, rec["ref_id"])
        assert report["checks"] == 0
        assert report["states"] == {}
        assert report["rot_ok_mean_deg"] is None

    def test_an_unknown_reference_is_refused(self, library: Path) -> None:
        with pytest.raises(DriftError, match="no such"):
            drift_service.soak_report(library, "f" * 32)
