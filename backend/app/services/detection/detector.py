"""YOLO26 detection, kept behind a small interface.

Only this module knows about ultralytics. One frame in, a list of Detections
out — whether that took one pass over the frame or two, and whether a tracker
put ids on them, is this module's business and nobody else's.

THE ALGORITHM, in full — ``_follow`` below is all of it:

    N == 0          YOLO on every frame, no lock is ever built
    frames < N      YOLO; the handoff ARMS once N frames have been seen and
                    FIRES on the first armed frame where YOLO found something
    after the lock  the visual tracker owns the frames in between; YOLO runs
                    again on a LOSS (rescue — un-covered detections become new
                    locks) and on a CLOCK (correction every
                    ``tracker_refresh_every`` frames — each lock is re-seeded on
                    its fresh box and keeps its id; sustained misses reap it)

N is the session's ``tracker_start_frame``. Both halves stay tellable apart on
screen: a YOLO frame's boxes are yellow (``predicted=False``), a tracker frame's
are orange (``predicted=True``). What the tracker earns is the frames in
between; what it can no longer do is walk away from the object unnoticed.

★ THE WEIGHTS ARE NEVER DOWNLOADED. ultralytics would fetch a missing ``.pt``
from its hub on first use; the bridge (``detection_service``) only ever hands
this module a file that exists in ``LE_DETECTION_MODEL_DIR``, because this is
an offline product and a model that downloads itself mid-survey is a hang on a
field laptop with no uplink.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from . import tiling
from .locked_tracking import LockedTracker
from .models import Box, Detection, DetectSettings, MODEL_CHOICES
from .stabilizer import BoxStabilizer

# The one model this build ships (see the header: the file must exist locally).
AVAILABLE_MODELS = {
    "yolo26s.pt": "YOLO26s",
}
# models.py validates settings against MODEL_CHOICES — keep the two lists one
assert set(AVAILABLE_MODELS) == set(MODEL_CHOICES)


class DetectorError(RuntimeError):
    pass


def resolve_device(wanted: str = "auto") -> str:
    """The device inference will actually run on.

    "auto" takes the NVIDIA GPU whenever torch can see one — nobody who has a
    GPU wants CPU inference — and falls back to the CPU otherwise. An explicit
    "cuda:N" is honoured only if it exists, so a settings file copied from a
    GPU machine cannot crash a CPU-only one.
    """
    try:
        import torch

        n_gpus = torch.cuda.device_count() if torch.cuda.is_available() else 0
    except ImportError:
        n_gpus = 0
    w = (wanted or "auto").strip().lower()
    if w == "cpu":
        return "cpu"
    if w.startswith("cuda"):
        if not n_gpus:
            return "cpu"
        idx = int(w[5:]) if w.startswith("cuda:") and w[5:].isdigit() else 0
        return f"cuda:{idx if idx < n_gpus else 0}"
    return "cuda:0" if n_gpus else "cpu"


# ★ EDIT: IoU for the rescue path in Detector._follow — which
#   detections are ALREADY covered by a surviving lock.
def _box_iou(a: Box, b: Box) -> float:
    ix1, iy1 = max(a.x1, b.x1), max(a.y1, b.y1)
    ix2, iy2 = min(a.x2, b.x2), min(a.y2, b.y2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0.0:
        return 0.0
    union = (a.x2 - a.x1) * (a.y2 - a.y1) + (b.x2 - b.x1) * (b.y2 - b.y1) - inter
    return inter / union if union > 0.0 else 0.0


def device_label(device: str) -> str:
    """Human words for the run header: which silicon is doing the work."""
    if device.startswith("cuda"):
        try:
            import torch

            return torch.cuda.get_device_name(int(device.split(":")[1]) if ":" in device else 0)
        except Exception:
            return "CUDA GPU"
    return "CPU"


class Detector:
    """Wraps one loaded YOLO model. Reloads only when the weights change."""

    # ★ Steady boxes (2026-09-03): created lazily in detect() so a Detector built
    #   without __init__ (the tests' __new__ shortcut) still has the attribute.
    _steady: Optional[BoxStabilizer] = None

    def __init__(self, model: str = "yolo26s.pt", device: str = "auto"):
        self.model_name = ""
        self.device = resolve_device(device)
        self._model = None
        self._locked_tracker: Optional[LockedTracker] = None
        # frames of THIS run seen so far — the number the handoff is counted
        # against, so it starts at zero wherever in the clip the run starts
        self._frames_seen = 0
        # ★ EDIT: True once the lock has actually been taken —
        #   the handoff ARMS at a frame number and FIRES on detections (see _follow).
        self._handoff_done = False
        self._handoff_frame = 0
        self._phase = "detector"  # "detector" | "tracker"
        self.names: dict[int, str] = {}
        self.load(model)

    def load(self, model: str) -> None:
        if model == self.model_name and self._model is not None:
            return
        try:
            from ultralytics import YOLO  # imported late: heavy
        except ImportError as exc:  # pragma: no cover
            raise DetectorError(
                "ultralytics is not installed — pip install -r requirements.txt"
            ) from exc
        try:
            self._model = YOLO(model)
        except Exception as exc:
            raise DetectorError(f"could not load {model}: {exc}") from exc
        self.model_name = model
        raw = getattr(self._model, "names", {}) or {}
        self.names = {int(k): str(v) for k, v in raw.items()}

    def class_names(self) -> dict[int, str]:
        return dict(self.names)

    def start_run(self, settings: DetectSettings) -> None:
        """Begin a fresh run.

        Without this a second run continues the first one's tracks, and on a
        different video that means one car inheriting another car's history.
        It also puts the handoff count back to zero, so "start after frame 30"
        means the thirtieth frame of THIS run and not of the app's lifetime.
        (The tile rotation needs no reset — it is derived from the frame index,
        so it starts at the first tile whenever the frames do.)
        """
        self._frames_seen = 0
        self._handoff_done = False  # ★ EDIT (see _follow)
        self._handoff_frame = 0
        self._phase = "detector"
        self._steady = None  # a new run inherits no old tracks
        # A tracker that will never be handed anything is never built: with the
        # handoff at 0 the run is YOLO from end to end.
        self._locked_tracker = (
            LockedTracker(settings.locked_tracker_type)
            if settings.tracker_start_frame > 0
            else None
        )

    # kept for callers that only want the tracks cleared
    def reset_tracker(self) -> None:
        if self._locked_tracker is not None:
            self._locked_tracker.reset()

    def algorithm_status(self) -> dict:
        """Who owns the frames right now, for the run readout."""
        return {"phase": self._phase, "frames_seen": self._frames_seen}

    def _predict_each(
        self, sources: list, settings: DetectSettings, imgsz: int, device: str
    ) -> list[list[Detection]]:
        """Several sources through the GPU in ONE call, answers kept apart.

        Worth doing only when the sources are the same size and want the same
        inference size, which is exactly the tiles of one frame: all four are
        2208x1242 here, and batching them measured 39 ms against 63 ms for four
        separate calls. Batching things that DISAGREE on size is a loss — one
        imgsz has to serve both, so the smaller source is letterboxed up to the
        larger and pays for pixels it does not have.
        """
        if not sources:
            return []
        flat = self._predict(sources, settings, imgsz, device, per_source=True)
        return flat

    def _predict(
        self, source, settings: DetectSettings, imgsz: int, device: str, per_source: bool = False
    ):
        """One inference pass, as plain Detections in `source` pixel space.

        The floor is the user's confidence and nothing else. An earlier version
        ran the detector BELOW it and fed the weak boxes to ByteTrack as
        association fodder — which is why boxes kept appearing on objects
        scoring under the number in the sidebar. There is no second association
        stage to feed any more, so the setting means exactly what it says.
        """
        # ★ EDIT (the only behavioural change in this file).
        #   The original passed `quantize=…` unconditionally; older ultralytics
        #   releases reject the KEY itself — even as None — and the very first
        #   detection died with "'quantize' is not a valid YOLO argument". fp16 is
        #   only meaningful on CUDA anyway, so the key is passed there alone, and
        #   dropped with a retry if the installed release does not know it.
        kwargs = dict(
            source=source,
            conf=settings.conf,
            iou=settings.iou,
            imgsz=imgsz,
            max_det=settings.max_det,
            classes=settings.classes or None,
            device=device,
            verbose=False,
        )
        if device.startswith("cuda"):
            # fp16 on the GPU: ~2x throughput at no meaningful accuracy cost
            kwargs["quantize"] = 16
        try:
            try:
                results = self._model.predict(**kwargs)
            except Exception as exc:
                if "quantize" in kwargs and "quantize" in str(exc):
                    kwargs.pop("quantize")
                    results = self._model.predict(**kwargs)
                else:
                    raise
        except Exception as exc:
            raise DetectorError(f"detection failed: {exc}") from exc

        per: list[list[Detection]] = []
        for res in results:
            here: list[Detection] = []
            boxes = getattr(res, "boxes", None)
            if boxes is not None:
                xyxy = (
                    boxes.xyxy.cpu().numpy()
                    if hasattr(boxes.xyxy, "cpu")
                    else np.asarray(boxes.xyxy)
                )
                conf = (
                    boxes.conf.cpu().numpy()
                    if hasattr(boxes.conf, "cpu")
                    else np.asarray(boxes.conf)
                )
                cls = (
                    boxes.cls.cpu().numpy() if hasattr(boxes.cls, "cpu") else np.asarray(boxes.cls)
                )
                for (x1, y1, x2, y2), sc, ci in zip(xyxy, conf, cls):
                    cid = int(ci)
                    here.append(
                        Detection(
                            box=Box(float(x1), float(y1), float(x2), float(y2)),
                            score=float(sc),
                            cls_id=cid,
                            cls_name=self.names.get(cid, str(cid)),
                        )
                    )
            per.append(here)
        # a batched caller needs to know WHICH source each box came from, to
        # shift it back by that source's offset; a single-source caller does not
        return per if per_source else [d for group in per for d in group]

    def _detect_yolo(
        self, frame, settings: DetectSettings, device: str, frame_index: int, single_frame: bool
    ) -> list[Detection]:
        """Whole-frame YOLO plus the optional rotating tile pass.

        Everything that leaves here scores at least `conf`. The model is
        already asked for that floor; the check is repeated on the way out
        because this is the single door every box in the app comes through,
        and the confidence number is only worth anything if it holds at it.
        """
        dets = self._predict(frame, settings, settings.imgsz, device)
        if settings.tile:
            h, w = frame.shape[:2]
            rects = tiling.tile_rects(w, h, settings.tile_grid, settings.tile_overlap)
            chosen = (
                rects
                if single_frame
                else [rects[tiling.tile_for_frame(frame_index, settings.frame_stride, len(rects))]]
            )
            crops = [np.ascontiguousarray(frame[y0:y1, x0:x1]) for x0, y0, x1, y1 in chosen]
            for rect, found in zip(
                chosen, self._predict_each(crops, settings, settings.tile_imgsz, device)
            ):
                x0, y0 = rect[0], rect[1]
                dets += tiling.drop_clipped(tiling.offset(found, x0, y0), rect, w, h)
        return [d for d in tiling.merge(dets) if d.score >= settings.conf]

    # --------------------------------------------------------- the algorithm
    def detect(
        self,
        frame: np.ndarray,
        settings: DetectSettings,
        frame_index: int = 0,
        time_s: float = 0.0,
        single_frame: bool = False,
    ) -> list[Detection]:
        """Everything found in one frame, in that frame's pixel coordinates.

        One algorithm, in one place (the module header spells it out):

          * the run opens with YOLO. Every box it finds is returned, and
            nothing scoring below `conf` is among them.
          * the handoff ARMS at frame N and FIRES on the first armed frame with
            detections: those boxes both become that frame's answer AND
            initialise the visual tracker. A clip whose opening is still empty
            at N waits instead of locking onto nothing.
          * after the lock the tracker owns the frames in between; YOLO returns
            on a loss (rescue) and on the correction clock.
          * N == 0 means the handoff never happens and YOLO works every frame.

        Boxes are marked `predicted` when the TRACKER produced them, which is
        what the page draws orange; YOLO's own boxes stay yellow.
        """
        if self._model is None:
            raise DetectorError("no model loaded")
        device = resolve_device(settings.device or self.device)

        # A picture has no next frame, so there is nothing for a tracker to do
        # with it: one YOLO pass over the whole of it and that is the answer.
        if single_frame:
            dets = self._detect_yolo(frame, settings, device, frame_index, True)
        else:
            dets = self._follow(frame, settings, device)
            # ★ Steady boxes: debounce/smooth/coast the YOLO half of the answer.
            #   Locked-tracker boxes pass through untouched (see stabilizer.py);
            #   a picture (single_frame) has no next frame to be steady against.
            if settings.steady_boxes:
                if self._steady is None:
                    self._steady = BoxStabilizer()
                dets = self._steady.update(dets)

        for d in dets:
            d.frame_index = frame_index
            d.time_s = time_s
            if not d.cls_name:
                d.cls_name = self.names.get(d.cls_id, str(d.cls_id))
        return dets

    def _follow(self, frame, settings: DetectSettings, device: str) -> list[Detection]:
        """One video frame through the algorithm above."""
        handoff = int(settings.tracker_start_frame)
        seen = self._frames_seen  # 0 for the run's first frame
        self._frames_seen += 1

        if handoff <= 0 or not self._handoff_done:
            self._phase = "detector"
            dets = self._detect_yolo(frame, settings, device, seen, False)
            # ★ EDIT (armed handoff — the third semantics, and
            #   the one the surveyor asked for by name: "tracker start 60" means
            #   the lock happens when 60 frames have been detected).
            #   The ORIGINAL seeded only on raw frame N-1 — a clip with an empty
            #   opening (first car near frame 1500 of a 3000-frame drone clip,
            #   2026-08-20) locked NOTHING and produced empty frames at full
            #   speed for the rest of the run. So: the handoff ARMS once N frames
            #   have been processed, and FIRES on the first armed frame whose
            #   YOLO pass actually found something. On time when objects are
            #   there; a still-empty frame N just keeps YOLO looking.
            if handoff > 0 and seen + 1 >= handoff and dets:
                if self._locked_tracker is None:  # detect() without start_run
                    self._locked_tracker = LockedTracker(settings.locked_tracker_type)
                dets = self._locked_tracker.acquire(dets, frame)
                self._handoff_done = True
                self._handoff_frame = seen
            return dets

        # Past the handoff the tracker owns the run — while its locks hold.
        self._phase = "tracker"
        if self._locked_tracker is None:
            return []
        tracked: list[Detection] = []
        lost = not self._locked_tracker.has_tracks()
        if not lost:
            tracked, lost = self._locked_tracker.update(frame)
        # ★ EDIT (detector rescue on loss).
        #   The original never ran YOLO past the handoff — "not to reacquire, not
        #   to correct" — so a lock that failed ended that object's coverage for
        #   the rest of the run, and a box vanishing mid-video read as a broken
        #   detector (product requirement 2026-08-20: the box must not silently
        #   vanish while the object is still in the picture). Now ANY loss makes
        #   YOLO run on THIS frame, and the tracker re-acquires whatever the
        #   surviving locks do not already cover (IoU ≤ 0.3 — a fresh lock gets a
        #   fresh id, because it IS a new lock). While nothing is locked at all,
        #   every frame is a rescue frame, so an object that leaves and re-enters
        #   the scene is picked up again instead of being gone for the run.
        if lost:
            dets = self._detect_yolo(frame, settings, device, seen, False)
            fresh = [d for d in dets if all(_box_iou(d.box, t.box) <= 0.3 for t in tracked)]
            if fresh:
                tracked = tracked + self._locked_tracker.acquire(fresh, frame, keep=True)
            return tracked
        # ★ EDIT (periodic correction, 2026-08-28).
        #   A tracker that has NOT lost its object can still be wrong about
        #   where it is — CSRT's box lags a fast car and the lag compounds, and
        #   the rescue above never fires because the lock "holds". Every
        #   `tracker_refresh_every` frames YOLO runs and each lock is re-seeded
        #   on the detector's box for it (see LockedTracker.correct). Counted
        #   from the handoff so the first correction lands a full interval in.
        every = int(settings.tracker_refresh_every)
        since = seen - self._handoff_frame
        if every > 0 and since > 0 and since % every == 0:
            dets = self._detect_yolo(frame, settings, device, seen, False)
            if dets:
                tracked = self._locked_tracker.correct(dets, frame, tracked)
        return tracked
