"""Plain data the detection pipeline passes around.

★ OWNED, NOT VENDORED (2026-09-02). This package began as a verbatim copy of the
standalone ``object_geolocator`` core and was then edited in place five dated
times (rescue, correction, reaping, jitter damping, parallel locks). A copy with
five behavioural edits is a fork, and calling it "vendored" kept the header
docstrings describing an algorithm the code no longer ran. It now lives here,
under ``app.services.detection``, with the tests beside it
(``app/tests/test_locked_tracking.py``) — fix bugs HERE.

Nothing in this package imports a web framework, a database or a GUI. The one
runtime dependency, ``ultralytics``/torch, is imported lazily in ``detector``;
``cv2`` is imported by ``locked_tracking`` and ``detector`` only.

What was dropped on the move, because nothing called it: ``Mark``, ``MediaInfo``
and ``RunResult`` (the bridge builds dicts), ``TRACKER_CATALOG`` and
``YOLO_DEFAULTS`` (never read), ``DetectSettings.tracker_confidence`` (stored,
never applied), ``start_frame``/``end_frame``/``pace_realtime`` (accepted and
silently ignored by the run loop — a setting that does nothing is a lie), and
``route.py`` (no endpoint ever exposed it).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Optional

# the weights the app offers; detector.py labels them for the dropdown
MODEL_CHOICES = ("yolo26s.pt",)

# The only classes this app detects — its subjects are people and road
# vehicles, nothing else. COCO ids: person, car, motorcycle, bus, truck.
ALLOWED_CLASSES = (0, 2, 3, 5, 7)

# The visual trackers offered for the handoff; all three construct from the
# opencv-contrib-headless wheel this product ships.
#: ★ "vit" (2026-09-11) is OpenCV's learned VitTrack — the only one of these that
#: SCORES its own confidence, which is what lets a loss be recognised rather
#: than a wrong object silently held. Its model ships in ``resources/``.
LOCKED_TRACKER_TYPES = ("vit", "csrt", "kcf", "mil")

# ★ THE GROUND-CONTACT BIAS, STATED AS NUMBERS (2026-09-02). ``ground.ground_point``
#   reads the bottom-edge midpoint of the box — the object's NEAR edge — so a long
#   vehicle is marked at the end facing the camera, and the bias grows with the
#   vehicle's length. When a session opts in (``centre_marks``), the mark is pushed
#   AWAY from the camera along its bearing by half the class's typical length, and
#   the metres applied are recorded on the mark (``centre_offset_m``) so an export
#   states what was done. Opt-in, because the correction assumes a length: a wrong
#   assumption moves the mark somewhere the object has never been. Half-lengths in
#   metres, by the class name YOLO reports.
CLASS_CENTRE_OFFSET_M = {
    "person": 0.2,
    "car": 2.2,
    "motorcycle": 1.0,
    "bus": 5.5,
    "truck": 4.0,
}


def _num(v, default, lo, hi, integer=False):
    """v forced into [lo, hi]; anything unusable becomes the default."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if math.isnan(x) or math.isinf(x):
        return default
    x = min(max(x, lo), hi)
    return int(round(x)) if integer else x


@dataclass
class Box:
    """Axis-aligned detection box in PIXELS OF THE SOURCE MEDIA."""

    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2.0

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2.0


@dataclass
class Detection:
    """One object found in one frame."""

    box: Box
    score: float
    cls_id: int
    cls_name: str
    frame_index: int = 0
    time_s: float = 0.0
    # where the object meets the ground, in source-media pixels (see ground.py)
    ground_u: Optional[float] = None
    ground_v: Optional[float] = None
    # stable id from the tracker, when tracking is on; None otherwise
    track_id: Optional[int] = None
    # True when the box is the tracker's estimate of where the object is,
    # rather than something the detector actually saw this frame
    predicted: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["box"] = [self.box.x1, self.box.y1, self.box.x2, self.box.y2]
        return d


@dataclass
class DetectSettings:
    """Everything a session can change about the one algorithm.

    YOLO owns the opening frames; from ``tracker_start_frame`` onwards the visual
    tracker owns them, with YOLO returning on a loss (rescue) and on a clock
    (``tracker_refresh_every``) — see ``detector._follow``.

    The YOLO numbers below are ultralytics' own out-of-the-box ones, so a fresh
    session starts from the baseline everything else is judged against.
    """

    model: str = "yolo26s.pt"  # the only weights this build ships
    conf: float = 0.25  # confidence floor — NOTHING below it is ever
    # detected, tracked, drawn or placed
    iou: float = 0.7  # NMS IoU threshold
    imgsz: int = 640  # inference size, single scale
    max_det: int = 300
    # Always a non-empty subset of ALLOWED_CLASSES — the app detects nothing
    # outside that set, and an empty selection falls back to all of it.
    classes: Optional[list[int]] = field(default_factory=lambda: list(ALLOWED_CLASSES))
    device: str = "auto"  # auto = NVIDIA GPU when present, else CPU

    # ---------------------------------------------------------- the algorithm
    # The frame count at which the handoff ARMS (it fires on the first armed
    # frame with detections). ZERO MEANS NEVER — YOLO then works every frame.
    tracker_start_frame: int = 0
    locked_tracker_type: str = "vit"  # visual tracker used after YOLO locks
    # Past the handoff, YOLO runs again every this-many frames and RE-SEEDS each
    # lock on its fresh box — the tracker's drift is corrected instead of
    # accumulating. 0 = never (YOLO only returns on a loss).
    tracker_refresh_every: int = 10

    # One extra detection pass per frame on ONE cell of a grid, rotating
    # through the cells — small objects at higher effective resolution for
    # roughly twice the time. See tiling.py for the measurements.
    tile: bool = False
    tile_imgsz: int = 960  # inference size for the tile pass
    tile_grid: int = 2  # 2 = a 2x2 grid of four cells, 3 = nine
    tile_overlap: float = 0.15

    # Forced to 1 below: the visual tracker follows PIXELS from one frame to
    # the next, and skipping frames destroys the correspondence it works from.
    # (The bridge's file-source ``every_nth`` grab()s frames OUTSIDE this loop
    # and refuses to combine it with a handoff.)
    frame_stride: int = 1
    # How many frames to detect before the run ends itself. 0 = until stopped.
    max_frames: int = 0

    # ★ Opt-in ground-contact correction — see CLASS_CENTRE_OFFSET_M.
    centre_marks: bool = False

    # ★ Steady boxes (2026-09-03): debounce + smoothing + coasting over the raw
    #   per-frame YOLO output — see stabilizer.py. ON by default; off = every
    #   frame drawn exactly as the detector saw it.
    steady_boxes: bool = True

    # ★ HOW OFTEN ONE OBJECT MAY BECOME A MARK (2026-09-11, owner: "the video is
    #   slow"). A run placed a mark for every detection on every frame: one
    #   tracked car at 25 fps produced 605 marks in 24 seconds, and the map draws
    #   every one of them. The picture stutters because the browser is holding
    #   thousands of points, not because the camera or the detector is slow.
    #   A ground fix does not change usefully twenty-five times a second — the
    #   sender path has said so since 2026-09-02 (geo1_service.DEFAULT_FIX_RATE_HZ)
    #   and this is the same rule for our own detections. 0 = mark every frame,
    #   for anyone who wants the raw stream back.
    mark_rate_hz: float = 1.0

    def __post_init__(self):
        """Settings arrive from a form and from a bare HTTP API — force every
        one into a range the pipeline can actually work with, and drop garbage
        back to the default instead of carrying it into a run."""
        if self.model not in MODEL_CHOICES:
            self.model = MODEL_CHOICES[0]
        # device is a request, not a fact — detector.resolve_device checks what
        # actually exists at run time. Here only the shape is enforced.
        d = str(self.device or "auto").strip().lower()
        if not (d in ("auto", "cpu") or d == "cuda" or (d.startswith("cuda:") and d[5:].isdigit())):
            d = "auto"
        self.device = d
        self.conf = _num(self.conf, 0.25, 0.01, 0.99)
        self.iou = _num(self.iou, 0.7, 0.05, 0.95)
        # inference runs on a stride-32 grid; keep the size on it
        self.imgsz = _num(self.imgsz, 640, 320, 1920, integer=True)
        self.imgsz = int(round(self.imgsz / 32) * 32)
        self.max_det = _num(self.max_det, 300, 1, 1000, integer=True)
        # every frame, always — see the field's comment
        self.frame_stride = 1
        self.max_frames = _num(self.max_frames, 0, 0, 10**9, integer=True)
        # 0 is a real, meaningful value here — it means the tracker never takes
        # over — so it is NOT nudged up to 1 the way a count would be.
        self.tracker_start_frame = _num(self.tracker_start_frame, 0, 0, 10**9, integer=True)
        # 0 = never correct; same rule as above
        self.tracker_refresh_every = _num(self.tracker_refresh_every, 10, 0, 10**6, integer=True)
        # 0 = no limit; above that, a sane band — 60/s is already every frame.
        self.mark_rate_hz = _num(self.mark_rate_hz, 1.0, 0.0, 60.0)
        # "false"/"0"/"off" arrive as strings from a bare HTTP client, and
        # bool("false") is True — spell the false-y words out
        for flag in ("tile", "centre_marks", "steady_boxes"):
            v = getattr(self, flag)
            setattr(
                self,
                flag,
                v.strip().lower() in ("1", "true", "yes", "on") if isinstance(v, str) else bool(v),
            )
        self.tile_imgsz = _num(self.tile_imgsz, 960, 320, 1920, integer=True)
        self.tile_imgsz = int(round(self.tile_imgsz / 32) * 32)
        # a 1x1 grid is the whole frame again, which is not a tile pass at all
        self.tile_grid = _num(self.tile_grid, 2, 2, 32, integer=True)
        # above ~45% neighbouring cells overlap each other's centres and the
        # extra pass stops covering new ground
        self.tile_overlap = _num(self.tile_overlap, 0.15, 0.0, 0.45)
        if self.locked_tracker_type not in LOCKED_TRACKER_TYPES:
            self.locked_tracker_type = LOCKED_TRACKER_TYPES[0]
        # only ids from the allowed set survive; anything else — junk, other
        # COCO classes, an emptied selection — falls back to the whole set
        ids = set()
        try:
            items = list(self.classes) if self.classes is not None else []
        except TypeError:
            items = []
        for c in items:
            try:
                if int(c) in ALLOWED_CLASSES:
                    ids.add(int(c))
            except (TypeError, ValueError):
                continue
        self.classes = sorted(ids) or list(ALLOWED_CLASSES)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "DetectSettings":
        """Unknown keys are dropped rather than raising, so a client left over
        from an older build loads without turning anything back on. ``tracker_type``
        is the wire's spelling of ``locked_tracker_type``."""
        d = dict(d or {})
        if "locked_tracker_type" not in d and "tracker_type" in d:
            d["locked_tracker_type"] = d["tracker_type"]
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})
