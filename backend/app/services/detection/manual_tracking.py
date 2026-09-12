"""Operator-chosen visual locks — the manual counterpart to ``locked_tracking``.

★ WHY (2026-09-03, owner ask). The automatic handoff locks EVERY detection at a
frame number; the operator asked instead to choose which objects the tracker
follows: click a detected object to TRACK it, click it again to release, follow
as many as wanted, and promote ONE to the LOCKED primary (highlighted, centred
in the inspector). Detection keeps running every frame underneath — this only
decides which objects also get a persistent visual lock and a stable id.

★ IT NEVER LOCKS ANYTHING ON ITS OWN. ``locked_tracking.LockedTracker`` acquires
new locks by itself (the handoff, the rescue, the correction clock). This class
acquires ONLY where a click lands, and reaps a lock only when its visual tracker
truly loses the object (not merely because YOLO missed it for a frame — the
operator chose this object and expects it followed through the gap).

★ MEASURED, 2026-09-11 (owner: "make the tracker more stable"). The white car
of the Yamouneh 4 frame moved over the frame itself with jitter, a 15-frame
occlusion and a 1.6x growth. Mean centre error in px / held frames:

    tracker           slow 4px    fast 10px   curve 8px   grow 1.6x
    csrt, as it was   lost@51     lost@51     128 (wrong) lost@51
    csrt, motion+look 1.8 / all   2.4 / all   153 (wrong) 2.0 / all
    vit,  motion+look 2.6 / all   2.0 / all   1.8 / all   2.7 / all

So the motion model (jump guard, velocity coasting, re-seed at the predicted
place) and the appearance check (template correlation, re-acquisition search)
carry a correlation tracker through an occlusion; the learned ViT tracker with
them holds everything at ~2 px, in 3.5 ms a frame. ViT is therefore the default.

★ SMALL TARGETS (owner report, same day: "missing the targets ... small in
pixels"). The same car shrunk to 14-28 px wide defeated every visual tracker
(a 14 px car lost at walking pace); padding the box made it worse (the ground
around a car does not move with the car). Matching the target's own template
in a motion-sized window, anchored to the seed crop, every frame:

    width   slow 4px   fast 10px   curve 8px   grow 1.6x   ms/frame
    14 px   0.2        0.0         0.0         0.7         0.4
    20 px   0.2        0.0         0.0         0.6         0.5
    24 px   0.2        0.0         0.0         0.5         0.8
    28 px   0.2        0.0         0.0         0.9         1.1

(mean centre error in px, every run held through the occlusion). Boxes under
32 px a side take this path; larger ones the visual tracker.

★ THE VISUAL MACHINERY IS SHARED. The per-lock tracker, the parallel update
pool, the seed and the jitter smoothing are ``locked_tracking``'s — this module
adds only the "which objects, chosen how" layer on top, so the two behave
identically once a lock exists.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import cv2
import numpy as np

from . import locked_tracking as lt
from .models import LOCKED_TRACKER_TYPES, Box, Detection

#: A tracker box and a YOLO box are the same object from this overlap up, or if
#: the fresh box's centre lies within this many box-widths of the lock's centre
#: (a lagging tracker box may have no overlap left — see LockedTracker.correct).
_MATCH_IOU = 0.1
_MATCH_CENTRE_WIDTHS = 1.5
#: Consecutive frames the visual tracker may LOSE its object before the lock is
#: reaped. A YOLO miss while the tracker still holds does not count — the
#: operator chose this object and expects it followed through detector gaps.
#: 30 is a second and a bit at 25 fps — a car behind a tree, not a car gone.
_MAX_LOST_FRAMES = 30

# ★ THE MOTION MODEL (2026-09-11, owner: "make the tracker more stable").
#   Measured on a real frame: CSRT never admits a loss — through a 15-frame
#   occlusion it latched onto the occluder and "held" it 170-855 px from the
#   object. So a loss has to be RECOGNISED, not reported, and ridden out on the
#   object's own motion. Three habits, each pinned by a test:
#: A tracker box whose centre lands further than this many box diagonals from
#: where the object's velocity predicted it is a TELEPORT — a lock jumping to
#: something else — and is refused; the lock coasts instead. The allowance has
#: a floor in pixels and grows with the object's speed: a 14 px target moving
#: 10 px a frame is not teleporting, it is small and quick.
_JUMP_DIAGONALS = 1.0
_JUMP_FLOOR_PX = 24.0
_JUMP_PER_SPEED = 2.0
# ★ SMALL TARGETS (owner report 2026-09-11: "missing the targets ... small in
#   pixels"). Measured: the white car shrunk to 14 px was lost even at walking
#   pace by every visual tracker — their features have a fixed pixel scale, and
#   a box that small holds a cell or two of them. Padding the box to give them
#   more was measured too, and made it WORSE: the ground around a car does not
#   move with the car, so a padded region is mostly stationary background and
#   the tracker stays with the background. So a small box is followed the way
#   point targets are: by matching its own template in a window around where it
#   should be, every frame, at three scales. Nothing else has anything to hold.
_SMALL_TARGET_PX = 32.0            # both sides under this = a small target
_SMALL_SEARCH_DIAGONALS = 1.5      # the search window's half-size about the prediction ...
_SMALL_SEARCH_FLOOR_PX = 30.0      # ... never under this, and it grows with the speed:
_SMALL_SEARCH_PER_SPEED = 2.0      # a window wider than the motion needs only finds look-alikes
_SMALL_MIN_NCC = 0.60              # the best match must be this convincing ...
_SMALL_SEED_NCC = 0.70             # ... AND still look this much like the SEED crop
_SMALL_REACQ_SEED_NCC = 0.80       # a RE-FIND after a loss has no continuity vouching for
                                   # it, so the seed must vouch harder (traced: distant
                                   # look-alikes scored 0.61-0.71; true re-finds ~1.0)
_SMALL_LEARN_NCC = 0.80            # the live template learns only from matches the seed vouches for
_SMALL_TEMPLATE_BLEND = 0.15       # how fast the template follows the object's look
_SMALL_SCALES = (0.9, 1.0, 1.1)
_SMALL_SCALE_MARGIN = 0.03         # another scale must beat 1.0 by this much to count ...
_SMALL_SCALE_VOTES = 3             # ... and win this many frames running before it is adopted
# ★ WHY THE SEED IS THE ANCHOR (traced 2026-09-11): three frames into an
#   occlusion the search accepted a patch of ground that matched the seed at
#   0.59; the live template then LEARNED that patch, its own score climbed to
#   1.00 on dirt, and the lock walked away for good. A match the seed does not
#   vouch for is refused, and the live template learns only from matches the
#   seed vouches for strongly — so the look can drift with the object, never
#   with the background.
#: Below this the learned tracker's own confidence says "I am not on it". The
#: correlation trackers score nothing, so for them only the jump guard speaks.
_MIN_SCORE = 0.30
#: While coasting, the tracker is re-seeded on the PREDICTED box every this many
#: frames — a search at the place the object should be by now — so an object
#: that walks out from behind a pole is picked up where it emerges, not where it
#: vanished. A re-seed that lands on background fails the score gate next frame.
_RESEED_EVERY = 4
#: Velocity is an exponential average of the centre's motion; it decays while
#: coasting so a long loss drifts to a stop rather than off the frame.
_VEL_ALPHA = 0.4
_VEL_DECAY = 0.97                  # a 15-frame occlusion keeps ~2/3 of the speed
# ★ THE APPEARANCE CHECK. A correlation tracker that stops dead on an occluder
#   reports a still box with no jump to refuse — only the object's LOOK says it
#   is gone. The seed crop is kept as a template; each accepted box is compared
#   with it by normalised cross-correlation, and a sustained mismatch is a loss.
#   Re-acquisition then SEARCHES for the template around the predicted place,
#   at three scales, and re-seeds on the best match if it is convincing.
_TEMPLATE_PX = 48                  # the template's long side, px
#: A template flatter than this (grey std) has no look to check against — a
#: dark patch of ground correlates with every other dark patch of ground — so
#: the appearance check stands down and only the motion model speaks.
_MIN_TEMPLATE_STD = 14.0
_MIN_NCC = 0.35                    # below this the box does not look like the object ...
_NCC_LOST_FRAMES = 3               # ... for this many frames running = lost
_REACQ_NCC = 0.55                  # a search hit must be this convincing to re-seed
_REACQ_DIAGONALS = 1.5             # the search window's half-size, in box diagonals
_REACQ_SCALES = (0.8, 1.0, 1.25)


class ManualTracker:
    """The operator's set of visual locks: acquire by click, release by click."""

    def __init__(self, kind: str = "csrt") -> None:
        """Start empty — nothing is tracked until the operator clicks."""
        self.kind = kind if kind in LOCKED_TRACKER_TYPES else LOCKED_TRACKER_TYPES[0]
        # ★ The learned tracker is the default because it measured best on a real
        #   object (see the module note); a build without its weights or without
        #   OpenCV's dnn falls back to CSRT rather than refusing to track at all.
        if self.kind == "vit" and not lt.vit_available():
            self.kind = "csrt"
        self._factory = lt._constructor(self.kind)
        self._locks: dict[int, dict[str, Any]] = {}
        self._next_id = 1
        #: The one LOCKED object (the highlighted primary), or None.
        self.primary_id: int | None = None
        #: ★ Names given with a drawn box (2026-09-11), keyed by the id the box
        #: got. The worker drains this into the session, where names live.
        self.pending_names: dict[int, str] = {}

    def ids(self) -> list[int]:
        """The track ids currently held, ascending."""
        return sorted(self._locks)

    def has_locks(self) -> bool:
        """True while any object is tracked."""
        return bool(self._locks)

    def clear(self) -> None:
        """Release everything — the operator turned tracking off."""
        self._locks.clear()
        self.primary_id = None
        self._next_id = 1

    # ── choosing objects ─────────────────────────────────────────────────────

    @staticmethod
    def _smallest_covering(boxes: list[tuple[Any, Box]], u: float, v: float) -> Any | None:
        """The key of the smallest box covering ``(u, v)`` — the aimed-at object."""
        best_key, best_area = None, float("inf")
        for key, b in boxes:
            if b.x1 <= u <= b.x2 and b.y1 <= v <= b.y2:
                area = b.width * b.height
                if area < best_area:
                    best_area, best_key = area, key
        return best_key

    def _lock_at(self, u: float, v: float) -> int | None:
        boxes = [(tid, item["box"]) for tid, item in self._locks.items()]
        return self._smallest_covering(boxes, u, v)

    def _det_at(self, dets: list[Detection], u: float, v: float) -> Detection | None:
        idx = self._smallest_covering([(i, d.box) for i, d in enumerate(dets)], u, v)
        return None if idx is None else dets[idx]

    def toggle_at(self, frame: Any, dets: list[Detection], u: float, v: float) -> dict[str, Any]:
        """Click semantics: on a tracked object → release it; on a detection → track it."""
        tid = self._lock_at(u, v)
        if tid is not None:
            self._release(tid)
            return {"action": "released", "track_id": tid}
        det = self._det_at(dets, u, v)
        if det is None:
            return {"action": "none", "track_id": None}
        new_id = self._acquire(frame, det)
        return {"action": "tracked" if new_id else "none", "track_id": new_id}

    def lock_at(self, frame: Any, dets: list[Detection], u: float, v: float) -> dict[str, Any]:
        """Double-click semantics: promote the object under ``(u, v)`` to primary.

        An object not yet tracked is tracked first; clicking the current primary
        again clears the primary (but leaves it tracked).
        """
        tid = self._lock_at(u, v)
        if tid is None:
            det = self._det_at(dets, u, v)
            if det is None:
                return {"action": "none", "track_id": None}
            tid = self._acquire(frame, det)
            if tid is None:
                return {"action": "none", "track_id": None}
        if self.primary_id == tid:
            self.primary_id = None
            return {"action": "unlocked", "track_id": tid}
        self.primary_id = tid
        return {"action": "locked", "track_id": tid}

    def set_primary(self, track_id: int | None) -> dict[str, Any]:
        """Set the primary by id (toggles off if it is already primary)."""
        if track_id is None or track_id not in self._locks:
            self.primary_id = None
            return {"action": "unlocked", "track_id": None}
        self.primary_id = None if self.primary_id == track_id else track_id
        return {"action": "locked" if self.primary_id else "unlocked", "track_id": track_id}

    def release(self, track_id: int) -> bool:
        """Release one track by id."""
        if track_id not in self._locks:
            return False
        self._release(track_id)
        return True

    def acquire_box(self, frame: Any, box: Box, cls_name: str = "object") -> int | None:
        """★ Track what the operator DREW (2026-09-11, owner ask).

        A click can only track what YOLO already found. A drawn box tracks any
        object in the picture — one the detector has no class for, or missed —
        by seeding the visual tracker straight on the operator's rectangle. It
        starts as class ``object`` with full confidence (the operator's word is
        the sighting); the moment YOLO confirms it, ``step`` adopts YOLO's class
        and box like any other lock, so a drawn car becomes a ``car``.
        """
        if box.width < 4 or box.height < 4:
            return None
        return self._acquire(
            frame, Detection(box=box, score=1.0, cls_id=-1, cls_name=cls_name or "object")
        )

    def _acquire(self, frame: Any, det: Detection) -> int | None:
        if det.box.width <= 1 or det.box.height <= 1:
            return None
        tracker = self._factory()
        if not lt.LockedTracker._seed(tracker, frame, det.box):
            return None
        tid = self._next_id
        self._next_id += 1
        self._locks[tid] = {
            "tracker": tracker,
            "cls_id": det.cls_id,
            "cls_name": det.cls_name,
            "score": det.score,
            "box": det.box,
            "smooth": det.box,
            "lost": 0,
            "vel": (0.0, 0.0),
            "template": _template(frame, det.box),
            "unlike": 0,
            # ★ A small target is matched, not tracked: its own crop at its own
            #   size, blended slowly so a changing look is followed.
            "small": _small_template(frame, det.box),
            "small_seed": _small_template(frame, det.box),
        }
        return tid

    def _release(self, track_id: int) -> None:
        self._locks.pop(track_id, None)
        if self.primary_id == track_id:
            self.primary_id = None

    # ── the per-frame advance ────────────────────────────────────────────────

    def _match(self, box: Box, cls_name: str, dets: list[Detection], taken: set[int]) -> int | None:
        """The YOLO det this lock is, preferring same class then overlap/proximity."""
        best_i, best_score = None, 0.0
        for i, d in enumerate(dets):
            if i in taken:
                continue
            iou = lt._iou(box, d.box)
            near = abs(box.cx - d.box.cx) <= _MATCH_CENTRE_WIDTHS * max(box.width, 1.0) and abs(
                box.cy - d.box.cy
            ) <= _MATCH_CENTRE_WIDTHS * max(box.height, 1.0)
            if iou < _MATCH_IOU and not near:
                continue
            # Same-class matches win; among those, most overlap wins.
            score = iou + (1.0 if d.cls_name == cls_name else 0.0)
            if score > best_score:
                best_score, best_i = score, i
        return best_i

    def step(
        self, frame: Any, dets: list[Detection], commands: list[dict[str, Any]]
    ) -> list[Detection]:
        """Apply pending clicks, advance every lock, return the frame's boxes.

        The returned list is: each tracked object once (YOLO's fresh box when it
        was seen this frame, else the tracker's coasting estimate, ``predicted``)
        followed by the untracked detections. A tracked object is never also
        returned as a loose YOLO box.
        """
        for cmd in commands:
            op = cmd.get("op")
            if op == "toggle":
                self.toggle_at(frame, dets, cmd["u"], cmd["v"])
            elif op == "lock":
                self.lock_at(frame, dets, cmd["u"], cmd["v"])
            elif op == "lock_id":
                self.set_primary(cmd.get("track_id"))
            elif op == "release":
                self.release(int(cmd["track_id"]))
            elif op == "clear":
                self.clear()
            elif op == "box":
                tid = self.acquire_box(
                    frame,
                    Box(float(cmd["x1"]), float(cmd["y1"]), float(cmd["x2"]), float(cmd["y2"])),
                    str(cmd.get("label") or "object"),
                )
                if tid is not None and cmd.get("name"):
                    self.pending_names[tid] = str(cmd["name"])

        if not self._locks:
            return dets

        h, w = frame.shape[:2]
        items = list(self._locks.items())
        big = [it for _, it in items if it.get("small") is None]
        big_results = iter(lt._update_all(big, frame))
        tracked: list[Detection] = []
        taken: set[int] = set()
        alive: dict[int, dict[str, Any]] = {}
        for tid, item in items:
            predicted = _predict(item)
            if item.get("small") is not None:
                box = _match_small(frame, item, predicted, w, h)
            else:
                ok, rect = next(big_results)
                box = _valid_box(ok, rect, w, h)
            if box is not None and not _plausible(item, box, predicted):
                box = None  # a teleport, or the tracker's own "not on it"
            if box is not None and item.get("template") is not None and not _scores_itself(item):
                # ★ Does it still LOOK like the object? A correlation tracker parked
                #   on an occluder reports a still box; only the appearance says no.
                #   A tracker that scores itself (ViT) has already answered — its
                #   boxes are loose about the object, and the template check would
                #   second-guess a confident lock into a loss (measured: it did).
                if _ncc(frame, box, item["template"]) < _MIN_NCC:
                    item["unlike"] += 1
                    if item["unlike"] >= _NCC_LOST_FRAMES:
                        box = None
                else:
                    item["unlike"] = 0
            if box is None:
                # ★ A LOSS, recognised: coast on the object's own velocity, search
                #   for it where it should be by now, and reap only after a
                #   sustained loss.
                item["lost"] += 1
                if item["lost"] > _MAX_LOST_FRAMES:
                    continue
                item["vel"] = (item["vel"][0] * _VEL_DECAY, item["vel"][1] * _VEL_DECAY)
                coasted = _clamp(predicted, w, h)
                item["box"] = coasted
                item["smooth"] = coasted
                if item["lost"] % _RESEED_EVERY == 0:
                    # ★ Look for the object where it should be — and, failing
                    #   that, at least point the tracker there. A small target
                    #   searches every frame already; on a loss it only widens.
                    # ★ The longer the loss, the less the coasted place can be trusted,
                    #   so the re-find window grows with it.
                    found = (
                        _match_small(
                            frame, item, coasted, w, h,
                            widen=2.0 + item["lost"] / 4.0, min_seed=_SMALL_REACQ_SEED_NCC,
                        )
                        if item.get("small") is not None
                        else _reacquire(frame, coasted, item.get("template"), w, h)
                    )
                    if item.get("small") is None:
                        seed_box = found if found is not None else coasted
                        reseeded = self._factory()
                        if lt.LockedTracker._seed(reseeded, frame, seed_box):
                            item["tracker"] = reseeded
                    if found is not None:
                        item["box"] = found
                        item["smooth"] = found
                        item["lost"] = 0
                        item["unlike"] = 0
                        alive[tid] = item
                        tracked.append(_coast(item, tid, box=found))
                        continue
                alive[tid] = item
                tracked.append(_coast(item, tid, box=coasted))
                continue
            _advance_velocity(item, box)
            match_i = self._match(box, item["cls_name"], dets, taken)
            if match_i is not None:
                d = dets[match_i]
                taken.add(match_i)
                reseeded = self._factory()
                if lt.LockedTracker._seed(reseeded, frame, d.box):
                    item["tracker"] = reseeded
                item.update(
                    box=d.box,
                    smooth=d.box,
                    score=d.score,
                    cls_id=d.cls_id,
                    cls_name=d.cls_name,
                    lost=0,
                    unlike=0,
                    template=_template(frame, d.box),
                )
                alive[tid] = item
                tracked.append(replace(d, track_id=tid, predicted=False))
            else:
                # Tracker holds but YOLO did not confirm — a chosen object
                # followed through the detector's gap, drawn as the estimate.
                sm = _SMOOTHER._smoothed(item, box)
                item["box"] = sm
                item["lost"] = 0
                alive[tid] = item
                tracked.append(_coast(item, tid, box=sm))
        self._locks = alive
        if self.primary_id not in self._locks:
            self.primary_id = None
        untracked = [d for i, d in enumerate(dets) if i not in taken]
        return tracked + untracked


def _valid_box(ok: Any, rect: Any, w: int, h: int) -> Box | None:
    """A tracker result turned into an in-frame Box, or None if it is a loss."""
    if not ok:
        return None
    x, y, bw, bh = (float(v) for v in rect)
    if bw <= 1 or bh <= 1:
        return None
    cx, cy = x + bw / 2, y + bh / 2
    if not (0 <= cx < w and 0 <= cy < h):
        return None
    return Box(max(0.0, x), max(0.0, y), min(w - 1.0, x + bw), min(h - 1.0, y + bh))


def _coast(item: dict[str, Any], tid: int, box: Box | None = None) -> Detection:
    """A tracked object YOLO did not confirm this frame — the orange estimate."""
    return Detection(
        box=box if box is not None else item["smooth"],
        score=float(item["score"]),
        cls_id=int(item["cls_id"]),
        cls_name=str(item["cls_name"]),
        track_id=tid,
        predicted=True,
    )


#: A throwaway LockedTracker used only for its ``_smoothed`` deadband filter,
#: which is instance state-free (it reads/writes item["smooth"]).
_SMOOTHER = lt.LockedTracker.__new__(lt.LockedTracker)


# ── the motion model ─────────────────────────────────────────────────────────


def _predict(item: dict[str, Any]) -> Box:
    """Where the object should be this frame: the last box moved by its velocity."""
    b, (vx, vy) = item["box"], item["vel"]
    return Box(b.x1 + vx, b.y1 + vy, b.x2 + vx, b.y2 + vy)


def _clamp(box: Box, w: int, h: int) -> Box:
    """Keep a predicted box inside the frame without letting it collapse."""
    bw, bh = box.width, box.height
    x1 = min(max(0.0, box.x1), max(0.0, w - 1.0 - bw))
    y1 = min(max(0.0, box.y1), max(0.0, h - 1.0 - bh))
    return Box(x1, y1, x1 + bw, y1 + bh)


def _advance_velocity(item: dict[str, Any], box: Box) -> None:
    """Fold this frame's centre motion into the velocity estimate."""
    prev = item["box"]
    dx, dy = box.cx - prev.cx, box.cy - prev.cy
    vx, vy = item["vel"]
    item["vel"] = (vx + _VEL_ALPHA * (dx - vx), vy + _VEL_ALPHA * (dy - vy))


def _scores_itself(item: dict[str, Any]) -> bool:
    """True for a tracker that reports its own confidence (ViT); False for CSRT/KCF/MIL."""
    if item.get("small") is not None:
        return True  # matched by its own template: the match score IS the confidence
    return getattr(item["tracker"], "getTrackingScore", None) is not None


def _plausible(item: dict[str, Any], box: Box, predicted: Box) -> bool:
    """Is this tracker box the object, or something else it jumped to?

    Two questions. A tracker that scores itself (ViT) is believed when it says it
    is not on the object. Any tracker's box that lands more than a box diagonal
    from where the motion predicted the object is a teleport — a lock does not
    move a car-length sideways in one frame — and is refused.
    """
    tracker = item["tracker"]
    get_score = None if item.get("small") is not None else getattr(tracker, "getTrackingScore", None)
    if get_score is not None:
        try:
            if float(get_score()) < _MIN_SCORE:
                return False
        except cv2.error:  # a tracker without a score this frame
            pass
    diag = float(np.hypot(predicted.width, predicted.height))
    speed = float(np.hypot(*item["vel"]))
    allowed = max(_JUMP_DIAGONALS * diag, _JUMP_FLOOR_PX) + _JUMP_PER_SPEED * speed
    jump = float(np.hypot(box.cx - predicted.cx, box.cy - predicted.cy))
    return jump <= allowed


# ── the appearance model ─────────────────────────────────────────────────────


def _gray_crop(frame: Any, box: Box) -> Any | None:
    x1, y1 = int(max(0, box.x1)), int(max(0, box.y1))
    x2, y2 = int(min(frame.shape[1], box.x2)), int(min(frame.shape[0], box.y2))
    if x2 - x1 < 4 or y2 - y1 < 4:
        return None
    crop = frame[y1:y2, x1:x2]
    return cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop


def _template(frame: Any, box: Box) -> Any | None:
    """The object's look at seed time: a grey crop, long side ``_TEMPLATE_PX``."""
    g = _gray_crop(frame, box)
    if g is None:
        return None
    h, w = g.shape
    scale = _TEMPLATE_PX / float(max(h, w))
    size = (max(4, int(round(w * scale))), max(4, int(round(h * scale))))
    tmpl = cv2.resize(g, size, interpolation=cv2.INTER_AREA)
    if float(tmpl.std()) < _MIN_TEMPLATE_STD:
        return None
    return tmpl


def _ncc(frame: Any, box: Box, template: Any) -> float:
    """How much the box's content looks like the template, -1..1."""
    g = _gray_crop(frame, box)
    if g is None:
        return -1.0
    th, tw = template.shape
    g = cv2.resize(g, (tw, th), interpolation=cv2.INTER_AREA)
    a = g.astype(np.float32) - float(g.mean())
    b = template.astype(np.float32) - float(template.mean())
    denom = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / denom) if denom > 1e-6 else -1.0


def _reacquire(frame: Any, predicted: Box, template: Any, w: int, h: int) -> Box | None:
    """Search for the template around the predicted box; the best convincing hit.

    Three scales, because an object that went behind something usually comes out
    nearer or farther than it went in. The window is small — a couple of box
    diagonals — so a look-alike across the frame cannot steal the lock.
    """
    if template is None:
        return None
    diag = float(np.hypot(predicted.width, predicted.height))
    half = _REACQ_DIAGONALS * diag
    x1, y1 = int(max(0, predicted.cx - half)), int(max(0, predicted.cy - half))
    x2, y2 = int(min(w, predicted.cx + half)), int(min(h, predicted.cy + half))
    window = _gray_crop(frame, Box(x1, y1, x2, y2))
    if window is None:
        return None
    th, tw = template.shape
    # the template as it would appear at the object's current size
    base_w, base_h = predicted.width, predicted.height
    best: tuple[float, Box] | None = None
    for s in _REACQ_SCALES:
        bw, bh = max(4, int(round(base_w * s))), max(4, int(round(base_h * s)))
        if bw >= window.shape[1] or bh >= window.shape[0]:
            continue
        tmpl = cv2.resize(template, (bw, bh), interpolation=cv2.INTER_LINEAR)
        res = cv2.matchTemplate(window, tmpl, cv2.TM_CCOEFF_NORMED)
        _mn, mx, _mnl, mxl = cv2.minMaxLoc(res)
        if best is None or mx > best[0]:
            best = (float(mx), Box(x1 + mxl[0], y1 + mxl[1], x1 + mxl[0] + bw, y1 + mxl[1] + bh))
    if best is None or best[0] < _REACQ_NCC:
        return None
    return best[1]



# ── small targets: matched, not tracked ──────────────────────────────────────


def _small_template(frame: Any, box: Box) -> Any | None:
    """The small target's own crop, at its own size — None for a big box."""
    if box.width >= _SMALL_TARGET_PX or box.height >= _SMALL_TARGET_PX:
        return None
    g = _gray_crop(frame, box)
    return None if g is None else g.astype(np.float32)


def _match_small(
    frame: Any,
    item: dict[str, Any],
    predicted: Box,
    w: int,
    h: int,
    widen: float = 1.0,
    min_seed: float = _SMALL_SEED_NCC,
) -> Box | None:
    """Find the small target's template around the prediction; None if nothing convinces.

    The window is a few diagonals about where the object should be, so a
    look-alike across the frame cannot steal it; three scales let it grow or
    shrink; a convincing hit refreshes the template a little, so the look the
    tracker holds follows the object instead of freezing on frame one.
    """
    tmpl = item["small"]
    th, tw = tmpl.shape
    diag = float(np.hypot(predicted.width, predicted.height))
    speed = float(np.hypot(*item["vel"]))
    half = (
        max(_SMALL_SEARCH_DIAGONALS * diag, _SMALL_SEARCH_FLOOR_PX) + _SMALL_SEARCH_PER_SPEED * speed
    ) * widen
    x1, y1 = int(max(0, predicted.cx - half)), int(max(0, predicted.cy - half))
    x2, y2 = int(min(w, predicted.cx + half)), int(min(h, predicted.cy + half))
    window = _gray_crop(frame, Box(x1, y1, x2, y2))
    if window is None:
        return None
    window = window.astype(np.float32)
    best: tuple[float, Box, float] | None = None
    for s in _SMALL_SCALES:
        bw, bh = max(4, int(round(tw * s))), max(4, int(round(th * s)))
        if bw >= window.shape[1] or bh >= window.shape[0]:
            continue
        t = tmpl if s == 1.0 else cv2.resize(tmpl, (bw, bh), interpolation=cv2.INTER_LINEAR)
        res = cv2.matchTemplate(window, t, cv2.TM_CCOEFF_NORMED)
        # ★ Among the PEAKS that clear the bar, the one NEAREST the prediction
        #   wins, not the highest: continuity breaks the tie between two
        #   look-alikes. Peaks, not cells — the cells around a peak clear the bar
        #   too, and choosing the nearest of those drags the box toward the
        #   prediction a pixel a frame until the template has learnt the drift.
        peaks = res == cv2.dilate(res, np.ones((bh | 1, bw | 1), np.uint8))
        ys, xs = np.nonzero(peaks & (res >= _SMALL_MIN_NCC))
        if ys.size == 0:
            continue
        ccx, ccy = predicted.cx - x1 - bw / 2.0, predicted.cy - y1 - bh / 2.0
        dist = np.hypot(xs - ccx, ys - ccy)
        k = int(np.argmin(dist))
        # ★ Within a scale the nearest peak; ACROSS scales the best score, and the
        #   object's own scale unless another clearly beats it (traced: a 0.9
        #   peak one pixel nearer won, the template shrank to it, and the seed
        #   never vouched for the shrunken box again).
        score = float(res[ys[k], xs[k]]) - (0.0 if s == 1.0 else _SMALL_SCALE_MARGIN)
        if best is None or score > best[0]:
            best = (score, Box(x1 + xs[k], y1 + ys[k], x1 + xs[k] + bw, y1 + ys[k] + bh), s)
    if best is None:
        return None
    _score, box, scale = best
    # A change of size is adopted only when the same scale keeps winning; until
    # then the box is reported at the size the template has.
    if scale != 1.0:
        item["scale_votes"] = item.get("scale_votes", 0) + 1
        if item["scale_votes"] < _SMALL_SCALE_VOTES:
            box = Box(box.cx - tw / 2.0, box.cy - th / 2.0, box.cx + tw / 2.0, box.cy + th / 2.0)
            scale = 1.0
    else:
        item["scale_votes"] = 0
    fresh = _gray_crop(frame, box)
    if fresh is None:
        return None
    # ★ The seed's word: the accepted patch must still look like what was drawn.
    seed = item["small_seed"]
    vouch = _ncc_of(cv2.resize(fresh, (seed.shape[1], seed.shape[0]), interpolation=cv2.INTER_AREA), seed)
    if vouch < min_seed:
        return None
    if vouch >= _SMALL_LEARN_NCC:
        fresh_t = cv2.resize(fresh, (tw, th), interpolation=cv2.INTER_AREA).astype(np.float32)
        blended = tmpl + _SMALL_TEMPLATE_BLEND * (fresh_t - tmpl)
        if scale != 1.0:
            # The object changed size: the template follows it at the new size.
            new_w, new_h = max(4, int(round(box.width))), max(4, int(round(box.height)))
            blended = cv2.resize(blended, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
            item["scale_votes"] = 0
        item["small"] = blended
    return box


def _ncc_of(a: Any, b: Any) -> float:
    """Normalised cross-correlation of two same-sized grey patches, -1..1."""
    a = np.asarray(a, np.float32) - float(np.mean(a))
    b = np.asarray(b, np.float32) - float(np.mean(b))
    denom = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / denom) if denom > 1e-6 else -1.0
