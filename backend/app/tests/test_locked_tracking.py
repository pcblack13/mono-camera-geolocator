"""``LockedTracker`` — the visual lock, and the two edits that keep it honest.

★ THE BUG THESE PIN (2026-08-28): CSRT follows pixels, and on a small fast object
its box lags the object a little more every frame. Past the handoff YOLO only ran
on a LOSS — and a lag is not a loss — so on the drone clip the orange box sat a
car-length behind the car for the rest of the run. ``correct`` re-seeds each lock
on the detector's fresh box, keeping its id; ``acquire(keep=True)`` lets a rescue
add a lock without clearing the survivors (the original cleared them).

Real CSRT on synthetic frames: a bright square on a dark ground, moved by hand.
"""

from __future__ import annotations

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
pytestmark = pytest.mark.skipif(
    not hasattr(cv2, "TrackerCSRT_create"), reason="opencv-contrib (CSRT) not installed"
)

from app.services.detection.locked_tracking import LockedTracker  # noqa: E402
from app.services.detection.models import Box, Detection  # noqa: E402


def _frame(x: int, y: int, size: int = 40, w: int = 320, h: int = 240) -> np.ndarray:
    """One bright square at (x, y) on a textured dark ground."""
    rng = np.random.default_rng(0)
    img = (rng.integers(20, 60, (h, w, 3))).astype(np.uint8)
    cv2.rectangle(img, (x, y), (x + size, y + size), (230, 230, 230), -1)
    cv2.rectangle(img, (x + 8, y + 8), (x + size - 8, y + size - 8), (40, 120, 220), -1)
    return img


def _det(x: float, y: float, size: float = 40, cls_id: int = 2, score: float = 0.8) -> Detection:
    return Detection(box=Box(x, y, x + size, y + size), score=score, cls_id=cls_id, cls_name="car")


class TestCorrect:
    def test_a_lagging_lock_is_pulled_onto_the_detectors_box_and_keeps_its_id(self) -> None:
        tracker = LockedTracker("csrt")
        locked = tracker.acquire([_det(50, 100)], _frame(50, 100))
        tid = locked[0].track_id
        assert tid is not None

        # The tracker's own estimate has fallen a box-width behind the object.
        stale = [Detection(box=Box(50, 100, 90, 140), score=0.8, cls_id=2, cls_name="car",
                           track_id=tid, predicted=True)]
        frame = _frame(100, 100)
        out = tracker.correct([_det(100, 100)], frame, stale)

        assert len(out) == 1
        assert out[0].track_id == tid          # same object, same id
        assert out[0].predicted is False       # a YOLO sighting, drawn yellow
        assert out[0].box.x1 == 100.0          # where the detector says it is

        # And the RE-SEEDED lock follows from the corrected place, not the stale one.
        moved, lost = tracker.update(_frame(106, 100))
        assert not lost
        assert abs(moved[0].box.cx - (106 + 20)) < 10

    def test_a_fresh_box_no_lock_matches_becomes_a_new_lock(self) -> None:
        tracker = LockedTracker("csrt")
        locked = tracker.acquire([_det(50, 100)], _frame(50, 100))
        tid = locked[0].track_id
        stale = [Detection(box=Box(50, 100, 90, 140), score=0.8, cls_id=2, cls_name="car",
                           track_id=tid, predicted=True)]

        frame = _frame(50, 100)
        cv2.rectangle(frame, (220, 40), (260, 80), (230, 230, 230), -1)
        out = tracker.correct([_det(50, 100), _det(220, 40)], frame, stale)

        ids = sorted(int(d.track_id) for d in out if d.track_id is not None)
        assert len(ids) == 2 and ids[0] == tid and ids[1] != tid

    def test_a_lock_the_detector_missed_carries_on_with_its_tracker_box(self) -> None:
        """A detector miss on one frame is not evidence the object went anywhere."""
        tracker = LockedTracker("csrt")
        locked = tracker.acquire([_det(50, 100)], _frame(50, 100))
        tid = locked[0].track_id
        stale = [Detection(box=Box(52, 100, 92, 140), score=0.8, cls_id=2, cls_name="car",
                           track_id=tid, predicted=True)]

        out = tracker.correct([_det(220, 40)], _frame(52, 100), stale)

        kept = [d for d in out if d.track_id == tid]
        assert len(kept) == 1 and kept[0].predicted is True and kept[0].box.x1 == 52.0
        assert len(tracker._locks) == 2


class TestAcquireKeep:
    def test_a_rescue_no_longer_clears_the_locks_that_survived(self) -> None:
        tracker = LockedTracker("csrt")
        frame = _frame(50, 100)
        cv2.rectangle(frame, (220, 40), (260, 80), (230, 230, 230), -1)
        first = tracker.acquire([_det(50, 100)], frame)
        added = tracker.acquire([_det(220, 40)], frame, keep=True)

        assert first[0].track_id != added[0].track_id
        assert tracker.has_tracks() and len(tracker._locks) == 2

    def test_the_handoff_still_replaces_everything(self) -> None:
        tracker = LockedTracker("csrt")
        frame = _frame(50, 100)
        tracker.acquire([_det(50, 100)], frame)
        tracker.acquire([_det(50, 100)], frame)
        assert len(tracker._locks) == 1


class TestCorrectionClock:
    def test_yolo_runs_on_the_clock_past_the_handoff_and_reseeds_the_lock(self) -> None:
        """YOLO on the clock, the tracker in between, one id throughout.

        Handoff on frame 0, correction every 3 frames: YOLO on 0, 3, 6, 9 — the
        tracker's own (orange) boxes in between — and the id survives throughout.
        """
        from app.services.detection.detector import Detector
        from app.services.detection.models import DetectSettings

        det = Detector.__new__(Detector)  # no weights: _follow never touches the model
        det.device = "cpu"
        det.names = {2: "car"}
        det._model = object()
        det._locked_tracker = None
        det._phase = "detector"
        settings = DetectSettings(tracker_start_frame=1, tracker_refresh_every=3)
        det.start_run(settings)

        yolo_frames: list[int] = []

        def fake_yolo(*args: object) -> list[Detection]:  # (frame, settings, device, index, single)
            index = int(args[3])  # type: ignore[call-overload]
            yolo_frames.append(index)
            x = 50 + 6 * index                     # the car moves 6 px per frame
            return [_det(x, 100)]

        det._detect_yolo = fake_yolo  # type: ignore[method-assign]

        ids, predicted = set(), {}
        for i in range(10):
            out = det._follow(_frame(50 + 6 * i, 100), settings, "cpu")
            assert len(out) == 1, f"frame {i} lost the car"
            ids.add(out[0].track_id)
            predicted[i] = out[0].predicted

        assert yolo_frames == [0, 3, 6, 9]
        assert ids == {1}                           # one object, one id, all the way
        assert {i: predicted[i] for i in (1, 2, 4, 5)} == {1: True, 2: True, 4: True, 5: True}
        assert {predicted[i] for i in (0, 3, 6, 9)} == {False}
        # after the last correction the lock sits on the detector's box, not a lag
        out = det._follow(_frame(50 + 6 * 10, 100), settings, "cpu")
        assert abs(out[0].box.x1 - (50 + 6 * 10)) < 8

    def test_zero_means_the_original_algorithm(self) -> None:
        from app.services.detection.detector import Detector
        from app.services.detection.models import DetectSettings

        det = Detector.__new__(Detector)
        det.device, det.names, det._model, det._locked_tracker, det._phase = "cpu", {2: "car"}, object(), None, "detector"
        settings = DetectSettings(tracker_start_frame=1, tracker_refresh_every=0)
        det.start_run(settings)
        calls: list[int] = []
        det._detect_yolo = lambda _f, _s, _d, i, _single: (calls.append(i), [_det(50, 100)])[1]  # type: ignore[method-assign]
        for _ in range(8):
            det._follow(_frame(50, 100), settings, "cpu")
        assert calls == [0]                         # the handoff, and never again


class TestParallelLocks:
    """★ Several locks are updated side by side (2026-08-30) — same answers, in
    lock order, with the ids the sequential loop gave them."""

    @staticmethod
    def _scene(offset: int, w: int = 640, h: int = 360) -> np.ndarray:
        frame = np.full((h, w, 3), 40, np.uint8)
        for i, (x, y, colour) in enumerate(((60, 80, (250, 250, 250)), (300, 120, (60, 220, 60)), (480, 220, (60, 60, 240)))):
            cv2.rectangle(frame, (x + offset, y + offset // 2), (x + offset + 40, y + offset // 2 + 40), colour, -1)
            cv2.putText(frame, str(i), (x + offset + 8, y + offset // 2 + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
        return frame

    def test_three_locks_come_back_in_order_with_their_ids_and_follow_their_squares(self) -> None:
        tracker = LockedTracker("csrt")
        dets = [
            Detection(box=Box(60, 80, 100, 120), score=0.9, cls_id=2, cls_name="car"),
            Detection(box=Box(300, 120, 340, 160), score=0.8, cls_id=2, cls_name="car"),
            Detection(box=Box(480, 220, 520, 260), score=0.7, cls_id=0, cls_name="person"),
        ]
        seeded = tracker.acquire(dets, self._scene(0))
        assert [d.track_id for d in seeded] == [1, 2, 3]
        out = []
        for step in range(1, 7):
            out, lost = tracker.update(self._scene(3 * step))
            assert not lost
        assert [d.track_id for d in out] == [1, 2, 3]
        assert [d.cls_name for d in out] == ["car", "car", "person"]
        assert all(d.predicted for d in out)
        # every lock moved with its own square (18 px right, 9 px down after six steps)
        for d, x0 in zip(out, (60, 300, 480)):
            assert abs(d.box.x1 - (x0 + 18)) < 6, (d.track_id, d.box.x1)
        # …and the pool exists only once more than one lock has asked for it
        from app.services.detection import locked_tracking

        assert locked_tracking._POOL is not None


class TestStaleLockReaping:
    """★ THE LOOPED-CLIP DUPLICATION (2026-08-31). The simulated stream restarts,
    CSRT keeps "holding" the terrain where the car used to be (a hold is not a
    loss, so no rescue fires), and the next correction locks the re-detected car
    under a NEW id — one car, two boxes, and the frozen one stayed forever.
    Sustained correction misses now reap the lock."""

    @staticmethod
    def _carried(tid: int, x: float, y: float) -> Detection:
        return Detection(box=Box(x, y, x + 40, y + 40), score=0.8, cls_id=2,
                         cls_name="car", track_id=tid, predicted=True)

    def test_a_frozen_lock_is_reaped_after_sustained_misses(self) -> None:
        tracker = LockedTracker("csrt")
        locked = tracker.acquire([_det(50, 100)], _frame(50, 100))
        tid = int(locked[0].track_id)

        # The clip restarted: the car is now at (220, 40); the old lock is frozen.
        frame = _frame(220, 40)
        frozen = self._carried(tid, 50, 100)

        out = tracker.correct([_det(220, 40)], frame, [frozen])       # miss 1
        new_id = next(int(d.track_id) for d in out if int(d.track_id) != tid)
        carried = self._carried(new_id, 220, 40)
        out = tracker.correct([_det(220, 40)], frame, [frozen, carried])  # miss 2
        assert any(int(d.track_id) == tid for d in out if d.track_id is not None), \
            "two misses is still flicker — the lock must carry on"
        out = tracker.correct([_det(220, 40)], frame, [frozen, carried])  # miss 3 — reaped

        ids = {int(d.track_id) for d in out if d.track_id is not None}
        assert tid not in ids, "the frozen box must leave the screen with its lock"
        assert new_id in ids
        assert [int(i["id"]) for i in tracker._locks] == [new_id]

    def test_one_sighting_resets_the_miss_count(self) -> None:
        tracker = LockedTracker("csrt")
        locked = tracker.acquire([_det(50, 100)], _frame(50, 100))
        tid = int(locked[0].track_id)
        frozen = self._carried(tid, 50, 100)

        far = _frame(220, 40)
        tracker.correct([_det(220, 40)], far, [frozen])               # miss 1
        tracker.correct([_det(220, 40)], far, [frozen])               # miss 2
        item = next(i for i in tracker._locks if int(i["id"]) == tid)
        assert item["misses"] == 2

        tracker.correct([_det(50, 100)], _frame(50, 100), [frozen])   # seen again
        assert item["misses"] == 0, "a sighting is a full pardon, not a stay"


class TestBoxSmoothing:
    """★ Jitter damping (2026-08-31): CSRT's scale search makes a held box breathe
    by a pixel or two, which reads as an unstable tracker. Sub-deadband movement
    is eased; anything at or past the deadband passes through untouched — the
    box's bottom edge is the map position, so lag there is metres."""

    def test_jitter_below_the_deadband_is_damped(self) -> None:
        tracker = LockedTracker("csrt")
        item = {"smooth": Box(100, 100, 140, 140)}
        wobbled = tracker._smoothed(item, Box(101.5, 100, 141.5, 140))
        assert 0.0 < wobbled.x1 - 100.0 < 1.5          # eased toward, not adopted
        # the wobble back is damped the same way — the box settles, not oscillates
        settled = tracker._smoothed(item, Box(100, 100, 140, 140))
        assert abs(settled.x1 - wobbled.x1) < 1.5

    def test_real_motion_passes_through_with_zero_lag(self) -> None:
        tracker = LockedTracker("csrt")
        item = {"smooth": Box(100, 100, 140, 140)}
        moved = tracker._smoothed(item, Box(112, 100, 152, 140))
        assert moved.x1 == 112.0 and moved.x2 == 152.0

    def test_the_first_box_is_its_own_reference(self) -> None:
        tracker = LockedTracker("csrt")
        item: dict = {}
        first = tracker._smoothed(item, Box(10, 10, 50, 50))
        assert first.x1 == 10.0 and item["smooth"] is first
