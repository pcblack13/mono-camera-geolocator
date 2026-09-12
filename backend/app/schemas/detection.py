"""Live object detection — wire types for ``/detection/*``.

★ WHAT A MARK CLAIMS, stated once: a mark's lat/lon comes from a LUT — a frozen
camera pose ray-cast against a DEM. It is only as good as that pose and that
terrain, and it is valid ONLY while the camera has not moved since the LUT was
built. The bundle's own manifest records the pose; the session summary carries it —
and since 2026-09-02 every mark carries ``drift_status``, the drift monitor's
confirmed verdict on that very question at the moment the mark was placed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from .common import ApiModel

#: The drift stamps a mark can carry (``detection_service.DRIFT_STATUSES``).
DriftStamp = Literal["unwatched", "pending", "ok", "moved", "changed", "degraded"]

__all__ = [
    "DetectionAvailability",
    "DetectionBox",
    "DetectionCapability",
    "DetectionLatest",
    "DetectionMark",
    "DetectionMarksRead",
    "DetectionSessionRead",
    "DetectionStartRequest",
]


class DetectionCapability(ApiModel):
    """One optional capability, and — when absent — the words that fix it."""

    available: bool
    reason: str | None = None
    #: ★ For the tracker: which kinds this build can run ("vit" only with its
    #: weights on disk). Empty for capabilities that have no kinds.
    kinds: list[str] = Field(default_factory=list)


class DetectionClass(ApiModel):
    """One subject the pipeline can detect: the COCO id, and its name."""

    id: int
    name: str


class DetectionAvailability(ApiModel):
    """What this machine's detection feature can do. The UI gates on it."""

    detector: DetectionCapability
    tracker: DetectionCapability
    #: The .pt files actually present in the model folder. Empty = nothing to run.
    models: list[str]
    #: Where inference would run (``cpu`` / ``cuda:0`` / ``mps``). ``None`` when the
    #: runtime is absent. The UI defaults its speed controls from this.
    device: str | None = None
    #: The pipeline's fixed subjects — people and road vehicles, nothing else.
    #: The UI's class picker is built from this, so it can never offer a class
    #: the detector would refuse.
    classes: list[DetectionClass]


class DetectionStartRequest(ApiModel):
    """``POST /detection/sessions`` — start detecting a live source."""

    #: A live-panel source: ``device:N`` or an allow-listed stream URL.
    source: str = Field(min_length=1, max_length=1000)
    #: ★ False = a TRACKING-ONLY run (2026-09-11, owner ask): no detector, no
    #: weights loaded — the source is read, the operator's drawn boxes are
    #: followed by the visual tracker, and their marks are placed through the
    #: lookup table like any detection's. Lets an object be tracked when
    #: detection is not running, or cannot run on this machine.
    detect: bool = True
    #: A LUT library site name (this app's own bundles). Omitted = detect without
    #: placing marks — boxes and counts only, honestly unlocated.
    lut_site: str | None = Field(default=None, max_length=64)
    #: Confidence floor — nothing below it is detected, drawn or placed.
    conf: float = Field(default=0.25, ge=0.01, le=0.99)
    #: Which of the fixed classes to detect (COCO ids). Empty = all of them.
    classes: list[int] | None = None
    #: Inference size. The vendored settings snap it to the stride-32 grid.
    imgsz: int = Field(default=640, ge=320, le=1920)
    #: Rotating tile pass for small objects (roughly twice the time per frame).
    tile: bool = False
    #: One weights filename from ``availability.models``. Omitted = the first one.
    model: str | None = Field(default=None, max_length=128)
    #: Stop by itself after this many detected frames. 0 = run until stopped.
    max_frames: int = Field(default=0, ge=0)
    #: The handoff ARMS at this frame count and FIRES on the first armed frame
    #: where YOLO actually found something: "tracker start 60" locks the moment
    #: 60 frames have been detected — or on the first later frame with objects,
    #: if frame 60 happens to be empty. ``0`` = YOLO on every frame (no lock).
    #: After the lock only rescue frames run YOLO; new objects arrive via rescue.
    tracker_start_frame: int = Field(default=0, ge=0, le=100_000)
    #: Which visual tracker takes the handoff. The build's own list — the
    #: service refuses an unknown name rather than silently substituting.
    #: ``vit`` (the learned tracker, default since 2026-09-11 — it measured best on a
    #: real object) falls back to ``csrt`` on a build without its weights.
    tracker_type: str = Field(default="vit", max_length=16)
    #: ★ Past the handoff, YOLO runs again every this-many frames and re-seeds each
    #: lock on its fresh box — the tracker's drift is corrected instead of compounding
    #: (an orange box a car-length behind the car, 2026-08-28). ``0`` = never: the
    #: tracker is only ever re-seeded when a lock is lost outright.
    tracker_refresh_every: int = Field(default=10, ge=0, le=10_000)
    #: ★ How often ONE object may become a mark, per second (2026-09-11). A run
    #: used to place a mark for every detection on every frame — one tracked car
    #: at 25 fps put 605 points on the map in 24 seconds, and the app stuttered
    #: under the weight of them. A ground fix does not change usefully 25 times a
    #: second. 0 = a mark every frame, for anyone who wants the raw stream.
    mark_rate_hz: float = Field(default=1.0, ge=0.0, le=60.0)
    #: FILE sources only: detect every Nth frame; the in-between frames are skipped
    #: without decoding (counted in ``frames_dropped``). Live sources ignore it —
    #: the freshest-frame reader already drops what the detector cannot keep up
    #: with. 1 = every frame.
    every_nth: int = Field(default=1, ge=1, le=10)
    #: ★ Opt-in ground-contact correction: each placed mark is pushed away from the
    #: camera by half its class's typical length (``CLASS_CENTRE_OFFSET_M``) and the
    #: metres applied are recorded on the mark. Off by default — it assumes a length.
    centre_marks: bool = False
    #: ★ Steady boxes (2026-09-03): debounce + smoothing + coasting over the raw
    #: per-frame YOLO output, so the overlay stops flickering. On by default;
    #: off = every frame drawn exactly as the detector saw it.
    steady_boxes: bool = True
    #: The registered camera this run belongs to. When given, the run is recorded as
    #: the camera's DESIRED state and restarted after an API restart; Stop clears it.
    camera_id: UUID | None = None


class DetectionBox(ApiModel):
    """One box on the CURRENT frame, in source-media pixels — the overlay's food."""

    x1: float
    y1: float
    x2: float
    y2: float
    score: float
    cls_name: str
    track_id: int | None = None
    #: The box is the tracker's estimate, not a detector sighting (drawn orange).
    predicted: bool = False
    #: A mark was placed for it (its ground pixel had terrain under it).
    placed: bool = False


class DetectionLatest(ApiModel):
    """The freshest detected frame — what the live overlay draws."""

    seq: int
    frame_index: int
    time_s: float
    width: int
    height: int
    boxes: list[DetectionBox]


class DetectionMark(ApiModel):
    """A detection resolved to a place on the ground, via the LUT."""

    lat: float
    lon: float
    score: float
    cls_name: str
    frame_index: int
    time_s: float
    #: The ground-contact pixel the mark was read from. ``null`` for a mark that
    #: arrived from a data feed — a feed carries no picture, and 0 would be a lie.
    u: float | None = None
    v: float | None = None
    track_id: int | None = None
    predicted: bool = False
    #: When the detection happened — UTC, and the server's local wall clock with
    #: offset, both stamped at detection time (owner request 2026-08-31).
    detected_at: str | None = None
    detected_at_local: str | None = None
    #: ★ The camera's drift verdict when this mark was placed — see the header.
    drift_status: DriftStamp = "unwatched"
    drift_ref_id: str | None = None
    #: ★ Metres this mark may be off on the ground from the camera's measured drift
    #: (rotation × the mark's own range); null when nothing is watched (2026-09-09).
    drift_shift_m: float | None = None
    #: Metres the mark was pushed away from the camera (``centre_marks``); null = none.
    centre_offset_m: float | None = None


class DetectionSessionRead(ApiModel):
    """One live detection session, from start to stop."""

    session_id: str
    source: str
    status: Literal["starting", "running", "stopped", "failed"]
    started_at: datetime
    error: str | None
    device: str
    device_name: str
    media_width: int
    media_height: int
    frames_done: int
    #: Frames the camera produced that the detector never saw — the honest price of
    #: staying live instead of falling minutes behind.
    frames_dropped: int
    fps: float
    phase: str
    counts: dict[str, int]
    #: Ground pixels that fell on sky / outside the DEM — counted, never guessed.
    skipped_no_terrain: int
    marks_total: int
    marks_dropped: int
    #: Detection rows durably written to the ``detection_events`` table (batched).
    db_rows_written: int
    #: Rows the database refused — counted, and the last failure is in ``db_error``.
    db_rows_failed: int
    db_error: str | None
    latest: DetectionLatest | None
    lut_site: str | None
    lut_summary: dict[str, Any] | None
    settings: dict[str, Any]
    #: FILE sessions: True while the run holds between frames (`POST …/pause`).
    paused: bool
    #: What was recording — the video's filename, or the live source string.
    camera_name: str
    #: False = tracking-only: no detector ran; every box is an operator's lock.
    detect: bool = True
    #: The recording camera's (lat, lon) from the LUT manifest; None without one.
    camera_location: tuple[float, float] | None
    #: The registered camera this run belongs to, when the page said so.
    camera_id: UUID | None = None
    #: The drift verdict the LAST detected frame was stamped with, and its watch.
    drift_status: DriftStamp = "unwatched"
    drift_ref_id: str | None = None
    #: Marks placed while the watch read MOVED or CHANGED — placed, never hidden.
    marks_under_alert: int = 0
    #: Detections geolocated but NOT marked, because the same object was marked a
    #: moment ago — the difference between what was seen and what is on the map.
    marks_thinned: int = 0
    #: ★ Manual tracking (2026-09-03): whether the operator has the tracker on, the
    #: ids currently followed, and the one LOCKED primary (the highlighted object).
    tracking_on: bool = False
    tracked_ids: list[int] = Field(default_factory=list)
    primary_track_id: int | None = None
    #: ★ The operator's names for tracks, by id (2026-09-11). JSON keys are
    #: strings on the wire; the client reads ``track_names[String(id)]``.
    track_names: dict[int, str] = Field(default_factory=dict)


class DetectionSessionListRead(ApiModel):
    """``GET /detection/sessions`` — every in-memory session, newest first.

    ★ The camera WALL polls this: one request answers "which cameras are
    detecting right now" for every tile at once (2026-09-02).
    """

    items: list[DetectionSessionRead]


class DetectionPauseRequest(ApiModel):
    """``POST /detection/sessions/{id}/pause`` — hold or release a video-file run."""

    paused: bool


class DetectionOverlayRequest(ApiModel):
    """``POST /detection/sessions/{id}/overlay`` — what the burned-in preview draws.

    The panel's Boxes / Labels / Tracks chips call this mid-run, so the toggles
    keep working while a detection is on. ``None`` leaves a flag unchanged.
    """

    boxes: bool | None = None
    labels: bool | None = None
    tracks: bool | None = None
    #: ★ HUD look (2026-09-03): corner brackets + locked-target crosshair instead
    #: of plain rectangles. Opt-in; ``None`` leaves it unchanged.
    hud: bool | None = None


class DetectionTrackingRequest(ApiModel):
    """``POST /detection/sessions/{id}/tracking`` — the "Start tracking" button.

    ``on`` arms the run to accept click commands; ``off`` releases every lock.
    """

    on: bool


class DetectionTrackRequest(ApiModel):
    """``POST /detection/sessions/{id}/track`` — one click, in MEDIA pixels.

    Toggle semantics: a click on a tracked object releases it, a click on a
    detection tracks it. ``lock`` promotes the object under the click to the
    highlighted primary (double-click) instead. The worker resolves the pixel
    against its freshest frame, so a moving object is hit where it is now.
    """

    u: float = Field(ge=0)
    v: float = Field(ge=0)
    #: True = set/clear the LOCKED primary; False (default) = track/untrack.
    lock: bool = False


class DetectionTrackBoxRequest(ApiModel):
    """``POST /detection/sessions/{id}/track-box`` — a DRAWN box, in MEDIA pixels.

    ★ Tracks what the operator drew, detection or not (2026-09-11). The worker
    seeds the visual tracker on the rectangle itself, so any object in the
    picture can be followed. ``name`` labels the track it becomes.
    """

    x1: float = Field(ge=0)
    y1: float = Field(ge=0)
    x2: float = Field(ge=0)
    y2: float = Field(ge=0)
    name: str | None = Field(default=None, max_length=64)


class DetectionTrackNameRequest(ApiModel):
    """``PUT /detection/sessions/{id}/tracks/{track_id}/name`` — name a track.

    Null or blank clears the name. Allowed on a finished run: the name is about
    the data, and it rides the export.
    """

    name: str | None = Field(default=None, max_length=64)


class DetectionLockRequest(ApiModel):
    """``POST /detection/sessions/{id}/lock`` — set the primary by id.

    ``track_id`` null clears the primary; an id that is already primary toggles
    it off. Used by the inspector's lock control, where the id is already known.
    """

    track_id: int | None = None


class DetectionMarksRead(ApiModel):
    """Marks from ``since`` onward — the map polls incrementally."""

    #: Pass back as the next request's ``since``.
    next_index: int
    marks: list[DetectionMark]
