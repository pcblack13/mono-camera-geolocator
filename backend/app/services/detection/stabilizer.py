"""Steady boxes — the YOLO overlay stabilised, honestly (2026-09-03, owner ask).

Raw per-frame YOLO output is jumpy in three distinct ways: boxes BLINK when an
object's score hovers at the confidence floor, box edges JITTER a few pixels on
an object that has not moved, and an object's class FLAPS (car one frame, truck
the next) at the boundary between two labels. Each gets its own habit here, and
none of them invents a detection the model never made:

    DEBOUNCE   a brand-new object is drawn only once it has been seen on
               ``_MIN_HITS`` consecutive frames — a single-frame false positive
               never reaches the screen, the map, or the table.
    SMOOTHING  a matched box is drawn at its exponential moving average, so the
               overlay sits still on a still object instead of vibrating with
               the detector's per-frame noise.
    COASTING   an established object YOLO missed THIS frame keeps its last
               smoothed box for up to ``_MAX_COAST`` frames — marked
               ``predicted`` (the overlay's orange), because that is exactly
               what the flag has always meant: an estimate, not a sighting.
    STICKY     the class shown is the track's, and it changes only after the
    CLASS      detector has insisted on the new label for ``_CLASS_SWITCH``
               consecutive frames — one frame of "truck" cannot rename a car.

★ THE CONFIDENCE FLOOR IS UNTOUCHED. detector.py promises that nothing scoring
below ``conf`` is ever detected — this module only re-arranges what already
passed that door. A coasted frame repeats the last box that DID pass, flagged
as the estimate it is.

★ TRACKER LOCKS PASS THROUGH UNTOUCHED. A detection carrying a ``track_id``
comes from the CSRT/KCF lock, which is already temporally smooth and owns its
identity; smoothing it again would add lag on top of lag. A lock also ABSORBS
any stabiliser track it overlaps, so the handoff never draws the same object
twice.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .models import Box, Detection

#: A detection and a track are the same object from this overlap up.
_MATCH_IOU = 0.3
#: Consecutive sightings before a new object is shown at all.
_MIN_HITS = 2
#: Frames an established object survives unseen (drawn ``predicted``).
_MAX_COAST = 5
#: EMA weight of the NEW box — higher tracks faster, lower sits stiller.
_ALPHA = 0.45
#: Consecutive frames of a different label before the track adopts it.
_CLASS_SWITCH = 3


def _iou(a: Box, b: Box) -> float:
    ix1, iy1 = max(a.x1, b.x1), max(a.y1, b.y1)
    ix2, iy2 = min(a.x2, b.x2), min(a.y2, b.y2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0.0:
        return 0.0
    union = (a.x2 - a.x1) * (a.y2 - a.y1) + (b.x2 - b.x1) * (b.y2 - b.y1) - inter
    return inter / union if union > 0.0 else 0.0


@dataclass
class _Track:
    box: Box
    score: float
    cls_id: int
    cls_name: str
    hits: int = 1
    misses: int = 0
    #: The label the detector is currently insisting on, and for how long.
    other_cls: str = ""
    other_cls_id: int = 0
    other_streak: int = 0

    @property
    def established(self) -> bool:
        return self.hits >= _MIN_HITS


class BoxStabilizer:
    """Frame in, steadier frame out. One instance per run — see detector.py."""

    def __init__(self) -> None:
        """Start with no memory — the first frame is all sighting, no history."""
        self._tracks: list[_Track] = []

    def reset(self) -> None:
        """Forget every track — a new run must not inherit an old run's objects."""
        self._tracks = []

    def _absorb_locks(self, locked: list[Detection]) -> None:
        """A tracker lock owns its object — drop any stabiliser track under it."""
        if locked:
            self._tracks = [
                t for t in self._tracks if all(_iou(t.box, d.box) <= _MATCH_IOU for d in locked)
            ]

    def update(self, dets: list[Detection]) -> list[Detection]:
        """The frame's answer: locks untouched + matched (smoothed) + coasting."""
        locked = [d for d in dets if d.track_id is not None]
        loose = [d for d in dets if d.track_id is None]
        self._absorb_locks(locked)

        # Greedy best-overlap matching, one detection per track.
        pairs = sorted(
            (
                (_iou(t.box, d.box), ti, di)
                for ti, t in enumerate(self._tracks)
                for di, d in enumerate(loose)
            ),
            reverse=True,
        )
        det_of: dict[int, int] = {}
        used: set[int] = set()
        for iou, ti, di in pairs:
            if iou <= _MATCH_IOU or ti in det_of or di in used:
                continue
            det_of[ti] = di
            used.add(di)

        out: list[Detection] = list(locked)
        survivors: list[_Track] = []
        for ti, track in enumerate(self._tracks):
            di = det_of.get(ti)
            if di is None:
                # Unseen this frame: a pending track dies quietly; an
                # established one coasts, drawn as the estimate it is.
                track.misses += 1
                if not track.established or track.misses > _MAX_COAST:
                    continue
                survivors.append(track)
                out.append(
                    Detection(
                        box=replace(track.box),
                        score=track.score,
                        cls_id=track.cls_id,
                        cls_name=track.cls_name,
                        predicted=True,
                    )
                )
                continue
            d = loose[di]
            a = _ALPHA
            track.box = Box(
                x1=track.box.x1 + a * (d.box.x1 - track.box.x1),
                y1=track.box.y1 + a * (d.box.y1 - track.box.y1),
                x2=track.box.x2 + a * (d.box.x2 - track.box.x2),
                y2=track.box.y2 + a * (d.box.y2 - track.box.y2),
            )
            track.score = d.score
            track.hits += 1
            track.misses = 0
            if d.cls_name == track.cls_name:
                track.other_streak = 0
            elif d.cls_name == track.other_cls:
                track.other_streak += 1
                if track.other_streak >= _CLASS_SWITCH:
                    track.cls_name, track.cls_id = d.cls_name, d.cls_id
                    track.other_streak = 0
            else:
                track.other_cls, track.other_cls_id = d.cls_name, d.cls_id
                track.other_streak = 1
            survivors.append(track)
            if track.established:
                out.append(
                    replace(
                        d,
                        box=replace(track.box),
                        cls_id=track.cls_id,
                        cls_name=track.cls_name,
                    )
                )

        # What nothing matched is a NEW object — remembered, not yet shown
        # (unless _MIN_HITS lets first sightings straight through).
        for di, d in enumerate(loose):
            if di in used:
                continue
            track = _Track(box=replace(d.box), score=d.score, cls_id=d.cls_id, cls_name=d.cls_name)
            survivors.append(track)
            if track.established:
                out.append(d)
        self._tracks = survivors
        return out
