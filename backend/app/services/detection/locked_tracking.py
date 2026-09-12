"""Pixel-based visual locks, seeded by YOLO boxes and updated from frame pixels.

THE SHAPE OF THE ALGORITHM (as it runs today — see ``detector._follow``):

    * the handoff ARMS at ``tracker_start_frame`` and FIRES on the first armed
      frame where YOLO found something; ``acquire`` seeds one lock per box.
    * between YOLO frames each lock follows its object from pixels alone
      (``update``) and reports an orange, ``predicted`` box.
    * YOLO comes back on a LOSS (rescue: un-covered detections become new locks
      via ``acquire(keep=True)``) and on a CLOCK (``correct``: every
      ``tracker_refresh_every`` frames each lock is re-seeded on the detector's
      fresh box, keeping its id), and a lock YOLO keeps not seeing is REAPED.

    So a lock is never without a safety net — which is the opposite of the
    original standalone design ("past the handoff the detector never runs
    again"). This header describes the code below, not that design.

The tracker is given the WHOLE frame every time, which is not the cheapest
thing to do and is deliberate. Feeding it only a window around the object is
roughly twice as fast — these trackers charge for every pixel handed to them —
but a window has to travel with the object, and moving it means re-seeding the
tracker on its own last box. That box LAGS a moving object by about one frame
of its motion, so each re-seed adopts the lag as truth and adds its own.
Measured against whole-frame tracking on the same synthetic runs:

    target speed   windowed                 whole frame
    4 px/frame     held, drifts 12-26 px    held, drifts 12-26 px
    8 px/frame     CSRT LOST at frame 36    held, worst 8.5 px
    14 px/frame    CSRT LOST at frame 32    held, worst 5.5 px

Correcting the seed by the object's own measured velocity recovered some of
that and not enough. Speed is worth having; it is not worth a tracker that
drops a car halfway across the frame with nothing left to pick it up.

What IS free is CSRT's segmentation pass — see _csrt_params.

Tests: ``app/tests/test_locked_tracking.py`` (needs opencv-contrib).
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Sequence

import cv2

from .models import Box, Detection, LOCKED_TRACKER_TYPES


def _csrt_params():
    """CSRT's own defaults, minus the per-frame segmentation pass.

    Measured on this project's 4K clip — three objects, 49, 88 and 190 px
    across, 200 frames each — turning segmentation off makes CSRT 1.5-1.8x
    faster and moves the box NOT AT ALL: the tracked path came out identical
    to the pixel in all three runs. It is the one saving CSRT offers for
    nothing. The others were measured and turned down: cutting the scale
    search from 33 steps to 17 is a further 1.2x but drifts the box up to
    13 px, and a smaller template up to 25 px — and the box's bottom edge is
    the map position, so drift there is metres on the ground.

    None means "this OpenCV cannot be told", and the defaults stand.
    """
    try:
        p = cv2.TrackerCSRT_Params()
    except AttributeError:                  # pragma: no cover — older bindings
        return None
    p.use_segmentation = False
    return p


#: The learned tracker's weights — beside this package, so the packaged app has
#: them without a network. See resources/README.md.
VIT_MODEL_PATH = Path(__file__).with_name("resources") / "vittrack_2023sep.onnx"


def vit_available() -> bool:
    """True when OpenCV has TrackerVit AND its weights are on disk."""
    return hasattr(cv2, "TrackerVit_create") and VIT_MODEL_PATH.is_file()


def _constructor(kind: str):
    if kind == "vit":
        if not vit_available():
            raise RuntimeError(
                "the ViT tracker needs OpenCV 4.9+ with dnn and its weights at "
                f"{VIT_MODEL_PATH}.")
        net = str(VIT_MODEL_PATH)

        def make():
            params = cv2.TrackerVit_Params()
            params.net = net
            return cv2.TrackerVit_create(params)

        return make
    name = f"Tracker{kind.upper()}_create"
    fn = getattr(cv2, name, None)
    if fn is None and hasattr(cv2, "legacy"):
        fn = getattr(cv2.legacy, name, None)
    if fn is None:
        raise RuntimeError(
            f"OpenCV {kind.upper()} tracking is unavailable. Install "
            "opencv-contrib-python-headless (keep exactly ONE cv2 wheel) and "
            "restart the app.")
    if kind == "csrt" and _csrt_params() is not None:
        return lambda: fn(_csrt_params())
    return fn


#: Locks are updated side by side on this pool (see LockedTracker.update).
#: Lazy: a run without a handoff never pays for a thread pool it does not use.
_POOL = None
_POOL_WORKERS = 4


def _update_all(locks, frame):
    """``[(ok, rect), …]`` for every lock, in lock order — pooled past one lock."""
    global _POOL
    if len(locks) <= 1:
        return [item["tracker"].update(frame) for item in locks]
    if _POOL is None:
        from concurrent.futures import ThreadPoolExecutor
        _POOL = ThreadPoolExecutor(max_workers=_POOL_WORKERS, thread_name_prefix="csrt")
    return list(_POOL.map(lambda item: item["tracker"].update(frame), locks))


class LockedTracker:
    """One independent visual lock for every YOLO detection."""

    # ★ EDIT (2026-08-31): output-box jitter damping. CSRT's
    #   scale search makes a held box breathe by a pixel or two every frame, which
    #   the operator reads as an unstable tracker. Movement at or below the
    #   deadband is treated as noise and eased (EMA); anything larger passes
    #   through UNTOUCHED, so a real car is never lagged — lag on the box's bottom
    #   edge is metres on the ground.
    SMOOTH_ALPHA = 0.45          # blend toward the new box, per frame, inside the deadband
    SMOOTH_DEADBAND_FRAC = 0.05  # deadband as a fraction of the box's larger side
    SMOOTH_DEADBAND_MIN_PX = 3.0

    # ★ EDIT (2026-08-31): stale locks are REAPED. One
    #   correction miss is detector flicker; this many CONSECUTIVE corrections in
    #   which YOLO saw the scene and found nothing matching the lock is evidence
    #   the object is gone — the lock is holding background. The looped test
    #   stream made this vivid: the clip restarts, CSRT keeps "holding" the
    #   terrain where the car used to be, the correction locks the re-detected
    #   car under a NEW id, and the frozen box stays on screen forever.
    MAX_CORRECTION_MISSES = 3

    def __init__(self, kind: str = "csrt"):
        self.kind = kind if kind in LOCKED_TRACKER_TYPES else LOCKED_TRACKER_TYPES[0]
        self._factory = _constructor(self.kind)
        self._locks: list[dict] = []
        self._next_id = 1

    def reset(self) -> None:
        self._locks.clear()
        self._next_id = 1

    def has_tracks(self) -> bool:
        return bool(self._locks)

    @staticmethod
    def _seed(tracker, frame, box: Box) -> bool:
        """Point one tracker at one box. True if it took."""
        # OpenCV 5's Python bindings require integer initialization boxes even
        # though update() returns floating-point coordinates.
        rect = (int(round(box.x1)), int(round(box.y1)),
                max(2, int(round(box.width))), max(2, int(round(box.height))))
        ok = tracker.init(frame, rect)
        # OpenCV versions disagree: successful init is either True or None.
        return ok is not False

    def acquire(self, dets: Sequence[Detection], frame,
                keep: bool = False) -> list[Detection]:
        """Lock onto these authoritative YOLO boxes.

        EVERY detection handed in comes back out, whether or not a lock could
        be taken on it: these are YOLO's answer for this frame and the map is
        entitled to all of them. The ones that were locked carry a track id;
        the rest are returned exactly as they arrived.

        ★ EDIT (2026-08-28): `keep`. The handoff REPLACES
        every lock (keep=False, the original). A rescue or a correction ADDS
        to the locks that survive (keep=True) — the original rescue called
        this with the default and so cleared the survivors it had just
        returned, which dropped a second car the frame after the first was
        re-acquired.
        """
        dets = list(dets)
        if not keep:
            self._locks.clear()
        out = []
        for d in dets:
            if d.box.width <= 1 or d.box.height <= 1:
                out.append(replace(d, predicted=False))
                continue
            tracker = self._factory()
            if not self._seed(tracker, frame, d.box):
                out.append(replace(d, predicted=False))
                continue
            tid = self._next_id
            self._next_id += 1
            self._locks.append({"tracker": tracker, "id": tid,
                                "cls_id": d.cls_id, "cls_name": d.cls_name,
                                "score": d.score, "misses": 0, "smooth": d.box})
            out.append(replace(d, track_id=tid, predicted=False))
        return out

    def _smoothed(self, item: dict, box: Box) -> Box:
        """The box to report for this lock: raw when it moved, eased when it jittered.

        The deadband is small (a few px, scaled to the box) so the filter only ever
        sees noise; a real displacement snaps through in one frame with zero lag.
        """
        prev = item.get("smooth")
        if prev is None:
            item["smooth"] = box
            return box
        dead = max(self.SMOOTH_DEADBAND_MIN_PX,
                   self.SMOOTH_DEADBAND_FRAC * max(box.width, box.height))
        step = max(abs(box.x1 - prev.x1), abs(box.y1 - prev.y1),
                   abs(box.x2 - prev.x2), abs(box.y2 - prev.y2))
        if step >= dead:                 # >= : motion AT the deadband is motion
            item["smooth"] = box
            return box
        a = self.SMOOTH_ALPHA
        sm = Box(prev.x1 + a * (box.x1 - prev.x1), prev.y1 + a * (box.y1 - prev.y1),
                 prev.x2 + a * (box.x2 - prev.x2), prev.y2 + a * (box.y2 - prev.y2))
        item["smooth"] = sm
        return sm

    def update(self, frame) -> tuple[list[Detection], bool]:
        """Return orange tracker boxes and whether any lock was lost.

        A lock that fails, collapses or leaves the picture is dropped, and
        ``lost`` tells ``detector._follow`` to run YOLO on this frame (the
        rescue) so whatever is still in the picture is re-acquired under a
        fresh id.
        """
        h, w = frame.shape[:2]
        out, keep = [], []
        lost = False
        # ★ EDIT (parallel locks, 2026-08-30). CSRT costs
        #   ~14 ms per object per frame on this project's machine, and the
        #   objects were updated one after another — four cars meant 56 ms a
        #   frame, under 18 fps, while a 15 fps camera was already dropping
        #   frames at three. OpenCV releases the GIL inside `update`, so the
        #   locks are run side by side on a small pool: measured 2 → 1.8x,
        #   3 → 2.5x, 4 → 3.0x (19 ms for four). One lock stays on this thread —
        #   there is nothing to overlap and the pool would only add a hop. The
        #   results are consumed in lock order, so ids and boxes are exactly
        #   what the sequential loop produced.
        results = _update_all(self._locks, frame)
        for item, (ok, rect) in zip(self._locks, results):
            if not ok:
                lost = True
                continue
            x, y, bw, bh = (float(v) for v in rect)
            if bw <= 1 or bh <= 1:
                lost = True
                continue
            cx, cy = x + bw / 2, y + bh / 2
            if not (0 <= cx < w and 0 <= cy < h):
                lost = True
                continue
            x1, y1 = max(0.0, x), max(0.0, y)
            x2, y2 = min(w - 1.0, x + bw), min(h - 1.0, y + bh)
            keep.append(item)
            out.append(Detection(box=self._smoothed(item, Box(x1, y1, x2, y2)),
                                 score=float(item["score"]),
                                 cls_id=int(item["cls_id"]),
                                 cls_name=str(item["cls_name"]),
                                 track_id=int(item["id"]), predicted=True))
        self._locks = keep
        return out, lost

    def correct(self, dets: Sequence[Detection], frame,
                tracked: Sequence[Detection]) -> list[Detection]:
        """Re-seed every lock on YOLO's fresh box for it; lock anything new.

        ★ EDIT (2026-08-28): the periodic correction. CSRT
        follows pixels, and on a small fast object its box lags the object by
        a little more every frame — on the 4K drone clip the orange box sat a
        car-length behind the car with nothing to pull it back, because past
        the handoff YOLO ran only on a LOSS. A lag is not a loss.

        So every `tracker_refresh_every` frames YOLO runs, and each fresh box
        is matched to the lock it most overlaps (same class first, then any).
        A matched lock keeps its id and score history but is RE-SEEDED on the
        fresh box — the tracker's memory of where the object was is replaced by
        where the detector says it is. Unmatched fresh boxes become new locks;
        locks nothing matched are left to carry on as they were (a detector
        miss on one frame is not evidence the object went anywhere).

        Matching is deliberately lenient: a lagging box may have NO overlap
        with the object any more, so after IoU the fallback is "the fresh box's
        centre lies within 1.5 box-widths of the lock's centre" — further than
        that and it is a different object, or a loss the rescue path owns.

        ★ EDIT (2026-08-31): sustained misses REAP the lock.
        One miss is flicker and the lock carries on; MAX_CORRECTION_MISSES
        consecutive corrections in which YOLO found nothing matching it mean the
        object is gone and the lock is holding background. Without this, a
        looped test clip left the old box frozen on the terrain while the
        re-detected car got a second id — one car, two boxes, forever.

        Returns YOLO's boxes, yellow (predicted=False), carrying the ids.
        """
        dets = list(dets)
        tracked = list(tracked)
        by_id = {int(t.track_id): t for t in tracked if t.track_id is not None}
        taken: set[int] = set()
        out: list[Detection] = []
        fresh: list[Detection] = []

        def _near(a: Box, b: Box) -> bool:
            reach = 1.5 * max(a.width, a.height, b.width, b.height)
            return abs(a.cx - b.cx) <= reach and abs(a.cy - b.cy) <= reach

        for d in dets:
            best_id, best_score = None, -1.0
            for item in self._locks:
                tid = int(item["id"])
                t = by_id.get(tid)
                if t is None or tid in taken:
                    continue
                iou = _iou(d.box, t.box)
                if iou <= 0.0 and not _near(d.box, t.box):
                    continue
                # same class outranks any overlap; within a class, more overlap wins
                score = (2.0 if int(item["cls_id"]) == int(d.cls_id) else 0.0) + iou
                if score > best_score:
                    best_id, best_score = tid, score
            if best_id is None:
                fresh.append(d)
                continue
            item = next(i for i in self._locks if int(i["id"]) == best_id)
            tracker = self._factory()
            if not self._seed(tracker, frame, d.box):
                fresh.append(d)
                continue
            item["tracker"] = tracker
            item["cls_id"], item["cls_name"] = d.cls_id, d.cls_name
            item["score"] = d.score
            item["smooth"] = d.box       # the jitter filter restarts from the fresh box
            taken.add(best_id)
            out.append(replace(d, track_id=best_id, predicted=False))

        # Miss bookkeeping BEFORE any fresh lock is added, so a box locked this
        # very pass cannot be charged with "missing" its own first correction.
        survivors: list[dict] = []
        reaped: set[int] = set()
        for item in self._locks:
            tid = int(item["id"])
            if tid in taken:
                item["misses"] = 0
                survivors.append(item)
                continue
            item["misses"] = int(item.get("misses", 0)) + 1
            if item["misses"] >= self.MAX_CORRECTION_MISSES:
                reaped.add(tid)
                continue
            survivors.append(item)
        self._locks = survivors

        if fresh:
            out.extend(self.acquire(fresh, frame, keep=True))
        # locks YOLO did not see this frame carry on with the tracker's box —
        # unless this miss was the one that reaped them.
        out.extend(t for t in tracked
                   if t.track_id is not None and int(t.track_id) not in taken
                   and int(t.track_id) not in reaped)
        return out


def _iou(a: Box, b: Box) -> float:
    ix = max(0.0, min(a.x2, b.x2) - max(a.x1, b.x1))
    iy = max(0.0, min(a.y2, b.y2) - max(a.y1, b.y1))
    inter = ix * iy
    if inter <= 0.0:
        return 0.0
    return inter / (a.width * a.height + b.width * b.height - inter)
