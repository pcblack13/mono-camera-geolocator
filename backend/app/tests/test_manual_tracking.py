"""Manual tracking — operator-chosen visual locks (2026-09-03, owner ask).

★ What these pin: a click tracks the object under it (and only it), a second
click on it releases it, several objects track at once, lock promotes ONE to
the primary and toggles off, turning tracking off clears everything, a tracked
object carries its id into the frame's boxes and is followed through a YOLO
miss, and an untracked object is never given an id.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.detection.manual_tracking import ManualTracker
from app.services.detection.models import Box, Detection

cv2 = pytest.importorskip("cv2")


def _frame() -> np.ndarray:
    # Two bright blocks on black — the trackers need texture to hold.
    f = np.zeros((360, 640, 3), dtype=np.uint8)
    f[80:160, 80:200] = 220  # "car A"
    f[80:160, 400:520] = 180  # "car B"
    return f


A = Detection(box=Box(80, 80, 200, 160), score=0.9, cls_id=2, cls_name="car")
B = Detection(box=Box(400, 80, 520, 160), score=0.8, cls_id=7, cls_name="truck")


def test_a_click_tracks_only_the_object_under_it() -> None:
    mt = ManualTracker("kcf")  # kcf is fast and deterministic enough for a test
    frame, dets = _frame(), [A, B]
    res = mt.toggle_at(frame, dets, 140, 120)  # inside A
    assert res["action"] == "tracked"
    out = mt.step(frame, dets, [])
    by_id = {d.track_id for d in out if d.track_id is not None}
    assert by_id == {res["track_id"]}  # exactly one object got an id
    # ...and it is A, not B: B stays a loose, id-less detection.
    tracked = next(d for d in out if d.track_id is not None)
    assert tracked.cls_name == "car"
    assert all(d.track_id is None for d in out if d.cls_name == "truck")


def test_a_second_click_releases_that_object() -> None:
    mt = ManualTracker("kcf")
    frame, dets = _frame(), [A, B]
    mt.toggle_at(frame, dets, 140, 120)
    mt.step(frame, dets, [])
    assert mt.has_locks()
    res = mt.toggle_at(frame, dets, 140, 120)  # click it again
    assert res["action"] == "released"
    assert not mt.has_locks()


def test_several_objects_track_at_once() -> None:
    mt = ManualTracker("kcf")
    frame, dets = _frame(), [A, B]
    mt.toggle_at(frame, dets, 140, 120)
    mt.toggle_at(frame, dets, 460, 120)
    mt.step(frame, dets, [])
    assert len(mt.ids()) == 2


def test_lock_promotes_one_primary_and_toggles_off() -> None:
    mt = ManualTracker("kcf")
    frame, dets = _frame(), [A, B]
    r = mt.lock_at(frame, dets, 140, 120)  # tracks A AND locks it primary
    assert r["action"] == "locked"
    assert mt.primary_id == r["track_id"]
    # Locking a different object moves the primary; it is still the only one.
    r2 = mt.lock_at(frame, dets, 460, 120)
    assert mt.primary_id == r2["track_id"] != r["track_id"]
    # Locking the current primary again clears it (but leaves it tracked).
    r3 = mt.lock_at(frame, dets, 460, 120)
    assert r3["action"] == "unlocked"
    assert mt.primary_id is None
    assert r2["track_id"] in mt.ids()


def test_clearing_via_step_command_releases_everything() -> None:
    mt = ManualTracker("kcf")
    frame, dets = _frame(), [A, B]
    mt.toggle_at(frame, dets, 140, 120)
    mt.lock_at(frame, dets, 460, 120)
    out = mt.step(frame, dets, [{"op": "clear"}])
    assert not mt.has_locks()
    assert mt.primary_id is None
    assert all(d.track_id is None for d in out)  # nothing marked after a clear


def test_a_tracked_object_is_followed_through_a_yolo_miss() -> None:
    mt = ManualTracker("kcf")
    frame = _frame()
    tid = mt.toggle_at(frame, [A, B], 140, 120)["track_id"]
    mt.step(frame, [A, B], [])
    # Next frame YOLO reports NOTHING — the lock must still carry the object,
    # drawn as the orange estimate (predicted), not vanish.
    out = mt.step(frame, [], [])
    coasted = [d for d in out if d.track_id == tid]
    assert len(coasted) == 1
    assert coasted[0].predicted is True


def test_a_click_on_empty_space_tracks_nothing() -> None:
    mt = ManualTracker("kcf")
    frame, dets = _frame(), [A, B]
    res = mt.toggle_at(frame, dets, 300, 300)  # black gap between the cars
    assert res["action"] == "none"
    assert not mt.has_locks()


# ── a DRAWN box (2026-09-11, owner ask) ─────────────────────────────────────


def test_a_drawn_box_tracks_an_object_yolo_never_reported() -> None:
    """★ The whole point: no detection under it, and it is followed anyway."""
    mt = ManualTracker("kcf")
    frame = _frame()
    tid = mt.acquire_box(frame, Box(400, 80, 520, 160))  # "car B", with NO detections
    assert tid is not None and mt.has_locks()
    out = mt.step(frame, [], [])
    assert [d.track_id for d in out] == [tid]
    assert out[0].cls_name == "object" and out[0].predicted


def test_a_drawn_box_adopts_yolos_class_once_confirmed() -> None:
    mt = ManualTracker("kcf")
    frame = _frame()
    tid = mt.acquire_box(frame, Box(78, 78, 202, 162))  # roughly A
    out = mt.step(frame, [A], [])
    tracked = next(d for d in out if d.track_id == tid)
    assert tracked.cls_name == "car" and not tracked.predicted


def test_a_box_command_carries_its_name_for_the_worker() -> None:
    mt = ManualTracker("kcf")
    frame = _frame()
    out = mt.step(
        frame, [], [{"op": "box", "x1": 400, "y1": 80, "x2": 520, "y2": 160, "name": "white pickup"}]
    )
    assert len(out) == 1 and out[0].track_id is not None
    assert mt.pending_names == {out[0].track_id: "white pickup"}


def test_a_sliver_of_a_box_tracks_nothing() -> None:
    mt = ManualTracker("kcf")
    assert mt.acquire_box(_frame(), Box(10, 10, 12, 40)) is None
    assert not mt.has_locks()


# ── stability: the motion and appearance models (2026-09-11) ────────────────


def _car_frames(
    n: int = 40, speed: int = 6, occlude: tuple[int, int] | None = (12, 24)
) -> list[tuple[np.ndarray, tuple[float, float]]]:
    """A bright object with a dark window crossing textured ground, briefly hidden.

    Returns (frame, true centre) pairs.
    """
    rng = np.random.default_rng(5)
    ground = rng.integers(40, 90, (240, 640, 3), dtype=np.uint8)
    out = []
    for i in range(n):
        f = ground.copy()
        x = 40 + speed * i
        f[100:130, x:x + 50] = 230
        f[106:118, x + 10:x + 40] = 60
        if occlude and occlude[0] <= i < occlude[1]:
            f[90:140, x - 10:x + 60] = 30
        out.append((f, (x + 25.0, 115.0)))
    return out


@pytest.mark.parametrize("kind", ["csrt", "vit"])
def test_an_occluded_object_is_followed_through_and_re_found(kind: str) -> None:
    """★ The lock survives a 12-frame occlusion and lands back within a few pixels.

    This is the whole point of the motion + appearance model.
    """
    if kind == "vit":
        from app.services.detection import locked_tracking as lt

        if not lt.vit_available():
            pytest.skip("ViT weights not on this build")
    seq = _car_frames()
    mt = ManualTracker(kind)
    f0, (cx, cy) = seq[0]
    tid = mt.acquire_box(f0, Box(cx - 25, cy - 15, cx + 25, cy + 15))
    last_err = None
    for f, (cx, cy) in seq[1:]:
        out = mt.step(f, [], [])
        d = next((d for d in out if d.track_id == tid), None)
        assert d is not None, "the lock was reaped during or after the occlusion"
        last_err = float(np.hypot(d.box.cx - cx, d.box.cy - cy))
    assert last_err is not None and last_err < 8.0, last_err


def test_a_teleport_is_refused_and_the_lock_coasts_on_its_velocity() -> None:
    """A box a frame's width from where the motion predicted the object is refused.

    The reported box follows the prediction instead.
    """
    from app.services.detection import manual_tracking as mt_mod

    seq = _car_frames(n=8, occlude=None)
    mt = ManualTracker("kcf")
    f0, (cx, cy) = seq[0]
    tid = mt.acquire_box(f0, Box(cx - 25, cy - 15, cx + 25, cy + 15))
    for f, _ in seq[1:4]:
        mt.step(f, [], [])
    item = mt._locks[tid]
    predicted = mt_mod._predict(item)
    far = Box(predicted.x1 + 400, predicted.y1, predicted.x2 + 400, predicted.y2)
    assert mt_mod._plausible(item, far, predicted) is False
    near = Box(predicted.x1 + 3, predicted.y1, predicted.x2 + 3, predicted.y2)
    assert mt_mod._plausible(item, near, predicted) is True


def test_a_flat_template_stands_the_appearance_check_down() -> None:
    """Dark ground correlates with every other dark ground: no look to check."""
    from app.services.detection import manual_tracking as mt_mod

    flat = np.full((100, 100, 3), 70, dtype=np.uint8)
    assert mt_mod._template(flat, Box(10, 10, 60, 40)) is None
    seq = _car_frames(n=1)
    f0, (cx, cy) = seq[0]
    assert mt_mod._template(f0, Box(cx - 25, cy - 15, cx + 25, cy + 15)) is not None


def test_re_acquisition_finds_the_object_near_where_it_should_be() -> None:
    from app.services.detection import manual_tracking as mt_mod

    seq = _car_frames(n=2, occlude=None)
    f0, (cx, cy) = seq[0]
    tmpl = mt_mod._template(f0, Box(cx - 25, cy - 15, cx + 25, cy + 15))
    f1, (cx1, cy1) = seq[1]
    # the prediction is 20 px off — inside the search window
    guess = Box(cx1 - 25 + 20, cy1 - 15, cx1 + 25 + 20, cy1 + 15)
    found = mt_mod._reacquire(f1, guess, tmpl, 640, 240)
    assert found is not None
    assert abs(found.cx - cx1) < 4 and abs(found.cy - cy1) < 4


def test_vit_falls_back_to_csrt_when_its_weights_are_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.detection import locked_tracking as lt

    monkeypatch.setattr(lt, "vit_available", lambda: False)
    assert ManualTracker("vit").kind == "csrt"


def _small_frames(
    n: int = 40, speed: int = 6, occlude: tuple[int, int] | None = (12, 24)
) -> list[tuple[np.ndarray, tuple[float, float]]]:
    """A 12x8 bright object on textured ground — small in pixels — briefly hidden."""
    rng = np.random.default_rng(9)
    ground = rng.integers(40, 90, (240, 640, 3), dtype=np.uint8)
    out = []
    for i in range(n):
        f = ground.copy()
        x = 40 + speed * i
        f[112:120, x:x + 12] = 235
        f[114:118, x + 3:x + 9] = 70
        if occlude and occlude[0] <= i < occlude[1]:
            f[100:132, x - 8:x + 20] = 30
        out.append((f, (x + 6.0, 116.0)))
    return out


@pytest.mark.parametrize("kind", ["csrt", "vit"])
def test_a_small_target_is_followed_and_reported_at_its_drawn_size(kind: str) -> None:
    """★ Owner report: small targets were missed. A 12x8 box survives an occlusion.

    It is matched by its own template and keeps its size.
    """
    if kind == "vit":
        from app.services.detection import locked_tracking as lt

        if not lt.vit_available():
            pytest.skip("ViT weights not on this build")
    seq = _small_frames()
    mt = ManualTracker(kind)
    f0, (cx, cy) = seq[0]
    tid = mt.acquire_box(f0, Box(cx - 6, cy - 4, cx + 6, cy + 4))
    assert tid is not None
    last = None
    for f, (cx, cy) in seq[1:]:
        out = mt.step(f, [], [])
        d = next((d for d in out if d.track_id == tid), None)
        assert d is not None, "reaped"
        assert 8 <= d.box.width <= 16 and 5 <= d.box.height <= 11   # its own size, ±a scale step
        last = float(np.hypot(d.box.cx - cx, d.box.cy - cy))
    assert last is not None and last < 8.0, last


def test_the_jump_allowance_has_a_floor_and_grows_with_speed() -> None:
    from app.services.detection import manual_tracking as mt_mod

    seq = _small_frames(n=6, speed=10, occlude=None)
    mt = ManualTracker("kcf")
    f0, (cx, cy) = seq[0]
    tid = mt.acquire_box(f0, Box(cx - 6, cy - 4, cx + 6, cy + 4))
    for f, _ in seq[1:5]:
        mt.step(f, [], [])
    item = mt._locks[tid]
    predicted = mt_mod._predict(item)
    # 18 px off a tiny box: more than its diagonal, well inside the floor + speed
    near = Box(predicted.x1 + 18, predicted.y1, predicted.x2 + 18, predicted.y2)
    assert mt_mod._plausible(item, near, predicted) is True
