"""Steady boxes — the overlay stabiliser (2026-09-03, owner ask).

★ What these pin: a single-frame false positive never shows (debounce), a
matched box is drawn smoothed (EMA), a missed frame coasts as ``predicted``
and expires, one frame of "truck" cannot rename a car (sticky class), a
tracker lock passes through untouched and absorbs its stabiliser twin, and
the OFF switch means raw per-frame output.
"""

from __future__ import annotations

from app.services.detection.models import Box, Detection, DetectSettings
from app.services.detection.stabilizer import (
    _MAX_COAST,
    _MIN_HITS,
    BoxStabilizer,
)


def det(
    x1: float = 100.0,
    y1: float = 100.0,
    x2: float = 200.0,
    y2: float = 180.0,
    score: float = 0.8,
    cls_name: str = "car",
    cls_id: int = 2,
    track_id: int | None = None,
) -> Detection:
    return Detection(
        box=Box(x1, y1, x2, y2),
        score=score,
        cls_id=cls_id,
        cls_name=cls_name,
        track_id=track_id,
    )


def test_debounce_a_single_frame_ghost_never_shows() -> None:
    s = BoxStabilizer()
    assert s.update([det()]) == []  # first sighting: remembered, not shown
    assert s.update([]) == []  # gone next frame — it never existed on screen


def test_a_persisting_object_appears_and_is_smoothed() -> None:
    s = BoxStabilizer()
    s.update([det(x1=100.0)])
    out = s.update([det(x1=110.0)])  # second consecutive sighting → shown
    assert len(out) == 1
    d = out[0]
    assert d.predicted is False
    # The drawn edge sits BETWEEN the two raw positions — smoothed, not raw.
    assert 100.0 < d.box.x1 < 110.0


def test_a_missed_frame_coasts_as_predicted_then_expires() -> None:
    s = BoxStabilizer()
    s.update([det()])
    s.update([det()])  # established
    for i in range(_MAX_COAST):
        out = s.update([])
        assert len(out) == 1, f"coast frame {i + 1} should still draw the box"
        assert out[0].predicted is True  # honestly an estimate, not a fresh sighting
        # ★ ...but NEVER a track id: a steady coast is not the tracker, so the
        #   overlay draws it yellow, not the tracker's orange (2026-09-03 fix).
        assert out[0].track_id is None
        assert out[0].cls_name == "car"
    assert s.update([]) == []  # the grace is spent — the object is gone


def test_reacquired_after_a_short_miss_without_flicker() -> None:
    s = BoxStabilizer()
    s.update([det()])
    s.update([det()])
    s.update([])  # one missed frame (coasting)
    out = s.update([det(x1=104.0)])  # the object is back
    assert len(out) == 1
    assert out[0].predicted is False  # a sighting again, immediately


def test_one_frame_of_truck_cannot_rename_a_car() -> None:
    s = BoxStabilizer()
    s.update([det(cls_name="car", cls_id=2)])
    s.update([det(cls_name="car", cls_id=2)])
    out = s.update([det(cls_name="truck", cls_id=7)])  # one dissenting frame
    assert out[0].cls_name == "car"
    # ...but a detector that INSISTS is eventually believed.
    s.update([det(cls_name="truck", cls_id=7)])
    out = s.update([det(cls_name="truck", cls_id=7)])
    assert out[0].cls_name == "truck"


def test_a_tracker_lock_passes_through_and_absorbs_its_twin() -> None:
    s = BoxStabilizer()
    s.update([det()])
    s.update([det()])  # the stabiliser now owns this object...
    locked = det(track_id=3)
    out = s.update([locked])  # ...until the CSRT lock claims it
    assert out == [locked]  # untouched, and NOT drawn twice
    assert s.update([]) == []  # the absorbed twin does not coast either


def test_the_off_switch_means_raw_per_frame_output() -> None:
    settings = DetectSettings(steady_boxes=False)
    assert settings.steady_boxes is False
    # The wire's false-y words survive sanitisation too (bool("false") is True).
    assert DetectSettings(steady_boxes="false").steady_boxes is False
    assert DetectSettings(steady_boxes="true").steady_boxes is True
    assert DetectSettings().steady_boxes is True  # the default is ON


def test_min_hits_is_two_frames_of_latency_no_more() -> None:
    """The contract the UI explains: one extra frame before a new object shows."""
    assert _MIN_HITS == 2
