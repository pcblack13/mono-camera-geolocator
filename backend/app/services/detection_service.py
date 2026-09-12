"""``detection_service`` — objects detected in a live stream, placed on the map.

★ THE BRIDGE, NOT THE ALGORITHM. The pipeline is ``app.services.detection`` (our
own package since 2026-09-02 — formerly the vendored ``object_geolocator``, now
owned and tested here). This module only assembles that core's inputs from
LandExplorer's own entities, exactly as ``lut_service`` and ``accuracy_service``
do for theirs:

    frames         ← ``live_stream_service`` (same sources the live panel plays:
                     device:N, MJPEG/RTSP URLs — validated the same way)
    the LUT        ← this app's OWN LUT library (``lut_service`` bundles; the
                     standalone package even ships one of ours)
    the weights    ← ``settings.detection_model_dir`` — LOCAL FILE ONLY, never a
                     download: this is an offline product and ultralytics' silent
                     hub fetch would hang a field laptop with no uplink

    frame ──► YOLO26s ──► box ──► bottom-edge midpoint ──► LUT ──► mark
                                  (+ opt-in centre offset)      (+ drift status)

★ CAPABILITIES ARE FEATURE-DETECTED AND ABSENCE IS A STATEMENT, NOT A CRASH:

* ``ultralytics``/torch are OPTIONAL (they are heavy, and the packaged desktop
  runtime does not carry them by default). ``availability()`` names the pip line
  that turns the feature on; a start without them is refused with the same words.
* The visual trackers live in opencv-contrib. This product ships
  ``opencv-contrib-python-headless`` — ONE cv2 wheel, still no GUI — so the
  algorithm's full shape (YOLO finds, the lock follows from
  ``tracker_start_frame`` on, YOLO returns on a loss and on a clock) can run for
  file AND live sources. A machine whose runtime lacks contrib is refused with
  the pip line that fixes it, never silently downgraded to YOLO-only.

★ A LIVE SOURCE HAS NO PAUSE BUTTON. The camera produces frames at its own rate
and detection is slower, so the reader keeps ONLY THE FRESHEST frame and the
detector always works on "now" — dropping, honestly counted, is what keeps the
marks live instead of minutes behind. A dropped-frame gap can break a lock's
pixel correspondence; that just fails the lock, and the rescue path re-acquires
on the same frame (2026-08-20). On a FILE, ``every_nth > 1`` is refused once the
handoff is on, because there the skip is a choice, not a necessity.

★ A MARK CARRIES ITS DRIFT STATUS (2026-09-02). A mark's lat/lon is valid only
while the camera has not moved since the LUT was built — and the drift monitor
(``drift_service``) is the thing that says whether it has. Every mark and every
``detection_events`` row is stamped with the confirmed verdict of the newest
running watch on the same source at the moment of detection (``ok`` / ``moved``
/ ``changed`` / ``degraded``, ``pending`` while a watch has no verdict yet,
``unwatched`` when nobody is watching). A mark placed under ``moved`` or
``changed`` is counted in ``marks_under_alert`` so the page can say so. The
mark is never suppressed: the detection happened; what is in doubt is where.

★ RUNS IN A THREAD, TRACKED IN MEMORY — the ``lut_service`` reasoning: a live
detection session owns no DB row and its durable products (marks) are handed to
the client as they appear; a restart simply ends the session. The camera's
DESIRED state (``cameras.desired``) is what brings it back — see
``camera_service.reconcile_at_boot``.

Framework-free: no FastAPI, no SQLAlchemy. The router owns HTTP concerns.
"""

from __future__ import annotations

import json
import math
import re
import threading
import time
import uuid as uuid_mod
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.core.logging import get_logger

log = get_logger(__name__)

__all__ = [
    "DRIFT_STATUSES",
    "DetectionError",
    "DetectionSession",
    "availability",
    "drift_status_for_source",
    "drift_rotation_for_source",
    "ground_shift_m",
    "get_session",
    "list_models",
    "list_sessions",
    "queue_track_command",
    "set_tracking",
    "start_session",
    "stop_session",
    "write_detection_rows",
]

#: The drift stamps a mark can carry — the vendor's four verdicts, lower-cased,
#: plus the two honest "nobody said" states. Same set on the wire and in
#: ``detection_events.drift_status``.
DRIFT_STATUSES = ("unwatched", "pending", "ok", "moved", "changed", "degraded")
#: The two stamps that mean "where is in doubt".
DRIFT_ALERT_STATUSES = ("moved", "changed")


class DetectionError(ValueError):
    """A session that cannot proceed — the message names the fix."""


#: ultralytics colours its errors with ANSI escapes; on a web page they render as
#: `[31m[1m…` garbage that also breaks layout. Errors are for READING.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _clean(message: str) -> str:
    return _ANSI_RE.sub("", message)


#: Marks kept per session. A live stream is unbounded; a survey that somehow marks
#: more than this keeps the NEWEST and counts the drop — the map shows the present.
MAX_MARKS = 50_000

#: How long a dead source may stay silent before the session ends itself, seconds.
SOURCE_TIMEOUT_S = 15.0

#: How long a live run waits for the panel to release a camera it is previewing.
#: The handover is a page re-render plus one HTTP disconnect — well under a second
#: in practice; the margin covers a slow machine, not a missing device.
DEVICE_HANDOVER_S = 6.0
#: How long a finished live run waits for its reader to leave `cap.read()` and
#: release the source — one blocked read at most; the capture's own read timeout.
READER_JOIN_S = 12.0


# ─────────────────────────────────────────────────────────────────────────────
# Capability probing — what this machine can actually do, with the fix named
# ─────────────────────────────────────────────────────────────────────────────


def _detector_probe(model_dir: Path) -> dict[str, Any]:
    try:
        import ultralytics  # noqa: F401, PLC0415 — heavy, probe only
    except ImportError:
        return {
            "available": False,
            "reason": (
                "the detection runtime is not installed. Install it into the app's "
                "Python environment: pip install ultralytics  (CPU-only machines: "
                "first  pip install --index-url https://download.pytorch.org/whl/cpu "
                "torch torchvision)."
            ),
        }
    weights = sorted(p.name for p in model_dir.glob("*.pt")) if model_dir.is_dir() else []
    if not weights:
        return {
            "available": False,
            "reason": (
                f"no model weights found in {model_dir} — copy yolo26s.pt there. "
                "Weights are never downloaded: this app works offline."
            ),
        }
    # ★ The DEVICE is part of "what this machine can do": the speed controls in the
    #   UI default to faster settings on a CPU, and they need to know BEFORE the
    #   first session starts. torch is importable here — ultralytics just was.
    from app.services.detection.detector import resolve_device  # noqa: PLC0415

    return {
        "available": True,
        "reason": None,
        "models": weights,
        "device": resolve_device("auto"),
    }


def _tracker_probe() -> dict[str, Any]:
    import cv2  # noqa: PLC0415

    has = hasattr(cv2, "TrackerCSRT_create") or hasattr(
        getattr(cv2, "legacy", None), "TrackerCSRT_create"
    )
    if has:
        from app.services.detection.locked_tracking import vit_available  # noqa: PLC0415
        from app.services.detection.models import LOCKED_TRACKER_TYPES  # noqa: PLC0415

        return {
            "available": True,
            "reason": None,
            # ★ Which kinds this build can run — "vit" only with its weights on disk.
            "kinds": [k for k in LOCKED_TRACKER_TYPES if k != "vit" or vit_available()],
        }
    return {
        "available": False,
        "reason": (
            "the visual tracker needs opencv-contrib. In the app's Python runtime run: "
            "pip uninstall -y opencv-python opencv-python-headless && "
            "pip install --force-reinstall --no-deps opencv-contrib-python-headless  "
            "— keep exactly ONE cv2 wheel installed. Until then detection runs YOLO "
            "on every frame."
        ),
    }


def availability(model_dir: Path) -> dict[str, Any]:
    """What the detection feature can do HERE, and why not where it cannot.

    ★ The capability dicts carry ONLY the wire model's fields. The probe's `models`
    list is hoisted to the top level — leaving it inside cost a 500 on the first
    machine that actually HAD the runtime, because `extra="forbid"` refuses what the
    schema does not declare and the dev machine only ever exercised the absent path.
    """
    det = _detector_probe(model_dir)
    return {
        "detector": {"available": det["available"], "reason": det.get("reason")},
        "tracker": _tracker_probe(),
        "models": det.get("models", []),
        "device": det.get("device"),
        "classes": detectable_classes(),
    }


#: COCO's own names for the ids the pipeline allows. Kept beside the allow-list
#: rather than in the UI so the two cannot drift: the wire carries id AND name,
#: and the class picker is built from what the server actually detects.
_COCO_NAMES = {0: "person", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}


def detectable_classes() -> list[dict[str, Any]]:
    """The pipeline's fixed subjects, as ``{id, name}`` — derived from the
    package's allow-list, so adding one there shows it in the UI."""
    from app.services.detection.models import ALLOWED_CLASSES  # noqa: PLC0415

    return [{"id": int(c), "name": _COCO_NAMES.get(int(c), str(c))} for c in ALLOWED_CLASSES]


def warm_probe(model_dir: Path) -> threading.Thread | None:
    """Pay the runtime's import cost at STARTUP, off the request path.

    ★ THE TWO-SECOND BAR. `_detector_probe` imports ultralytics, which imports torch —
      measured at 1.9 s the first time and 0.00 s every time after, because Python
      caches the module. That first call landed on whoever opened a detection page,
      so the settings bar sat half-built while it finished. Doing it here moves the
      cost to boot, where nothing is waiting on it.

    ★ ONLY WHEN THERE ARE WEIGHTS. Importing torch costs real memory, and a machine
      with no ``.pt`` file cannot detect anything anyway — that user should not pay
      for a feature they have not set up. Returns None when it declines to warm.
    """
    if not list_models(model_dir):
        return None

    def run() -> None:
        try:
            availability(model_dir)
        except Exception as exc:  # noqa: BLE001 — warming must never affect the app
            log.warning("detection.warm_failed", error=f"{type(exc).__name__}: {exc}")

    thread = threading.Thread(target=run, name="detect-warm", daemon=True)
    thread.start()
    return thread


def list_models(model_dir: Path) -> list[str]:
    return sorted(p.name for p in model_dir.glob("*.pt")) if model_dir.is_dir() else []


# ─────────────────────────────────────────────────────────────────────────────
# The session registry
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class DetectionSession:
    """One live detection run. Mutated only under `_LOCK` or by its own thread."""

    session_id: str
    source: str
    lut_site: str | None
    settings: dict[str, Any]
    status: str = "starting"  # starting | running | stopped | failed
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    error: str | None = None
    device: str = ""
    device_name: str = ""
    media_width: int = 0
    media_height: int = 0
    frames_done: int = 0
    frames_dropped: int = 0
    fps: float = 0.0
    phase: str = "detector"
    counts: Counter = field(default_factory=Counter)
    skipped_no_terrain: int = 0
    marks: list[dict[str, Any]] = field(default_factory=list)
    marks_dropped: int = 0
    #: Detection rows durably written to ``detection_events`` (batched; see
    #: `_flush_detection_rows`). `db_error` carries the LAST write failure so a
    #: dead database shows up in the status poll instead of vanishing silently.
    db_rows_written: int = 0
    db_rows_failed: int = 0
    db_error: str | None = None
    #: The registered camera this run belongs to (``cameras.id``), when the page
    #: said so — what the boot reconciliation and ``detection_events`` key on.
    camera_id: str | None = None
    #: ★ False = TRACKING-ONLY (2026-09-11): no detector, no weights; the visual
    #: tracker follows what the operator draws, and nothing else is ever a box.
    detect: bool = True
    #: The drift verdict the LAST detected frame was stamped with (see the module
    #: header), and the watch it came from.
    drift_status: str = "unwatched"
    drift_ref_id: str | None = None
    #: Marks placed while the camera's watch read MOVED or CHANGED — placed,
    #: never hidden, but the count is the page's warning.
    marks_under_alert: int = 0
    #: The freshest frame's boxes, for the panel overlay. Replaced whole per frame.
    latest: dict[str, Any] = field(default_factory=dict)
    #: What the burned-in preview draws — the panel's Boxes / Labels / Tracks chips
    #: steer these MID-RUN (``POST /sessions/{id}/overlay``). The worker reads them
    #: per frame, so a toggle takes effect on the next frame, still frame-synced.
    overlay_boxes: bool = True
    overlay_labels: bool = True
    overlay_tracks: bool = True
    #: ★ HUD look (2026-09-03): corner brackets + a locked-target crosshair instead
    #: of plain rectangles. Opt-in — the chip steers it mid-run like the others.
    overlay_hud: bool = False
    #: ★ Manual tracking (2026-09-03), ARMED FROM THE FIRST FRAME (2026-09-08,
    #: owner decision): the tracker runs with detection, but follows nothing until
    #: the operator clicks a detected object — there is no "Start tracking" ritual.
    #: Steered MID-RUN like the overlay chips: the endpoints write here and the
    #: worker reads them per frame. ``tracked_ids`` and ``primary_track_id`` are
    #: what the worker WROTE back (the truth after each frame), for the poll.
    tracking_on: bool = True
    #: Pending clicks the worker has not applied yet — {op, u, v} / {op, track_id}.
    track_commands: list[dict[str, Any]] = field(default_factory=list)
    #: The ids currently followed, and the one LOCKED primary (the highlight).
    tracked_ids: list[int] = field(default_factory=list)
    primary_track_id: int | None = None
    #: ★ THE OPERATOR'S NAMES FOR TRACKS (2026-09-11, owner ask): "#3" becomes
    #: "white pickup". Kept on the session, not the tracker, because a name is
    #: about the DATA — it must survive the lock being lost, ride the export, and
    #: be settable on a finished run. Marks keep the id; the name is looked up.
    track_names: dict[int, str] = field(default_factory=dict)
    #: ★ When each object last became a mark (2026-09-11) — see
    #: ``DetectSettings.mark_rate_hz``. Keyed by track id where there is one and
    #: by class + ground cell where there is not, so a standing object is thinned
    #: whether or not the operator is tracking it, and a moving one still draws a
    #: trail because it keeps entering new cells.
    mark_clock: dict[Any, float] = field(default_factory=dict)
    #: Detections that were geolocated but not marked, because one was placed for
    #: the same object a moment ago. Reported, never silent: it is the difference
    #: between what was SEEN and what was RECORDED.
    marks_thinned: int = 0
    #: Guards ``track_commands`` between the endpoints and the worker.
    _track_lock: threading.Lock = field(default_factory=threading.Lock)
    #: EVERY source: the latest detected frame as JPEG with the boxes burned in —
    #: what ``/frame`` and ``/stream`` serve (see the burn-in note in ``_run``).
    latest_jpeg: bytes | None = None
    #: LIVE sources: the reader thread's freshest RAW frame (no boxes — the burn-in
    #: path draws into a copy). The drift monitor taps this instead of opening the
    #: device a second time, which a V4L2 camera would refuse. See `latest_raw_frame`.
    latest_raw: Any | None = None
    latest_raw_t: float = 0.0
    #: Bumped once per encoded preview frame — the MJPEG stream endpoint waits on it.
    jpeg_seq: int = 0
    lut_summary: dict[str, Any] | None = None
    #: What was recording: the video's filename, or the live source string.
    camera_name: str = ""
    #: The RECORDING camera's position (lat, lon) — the LUT manifest's solved
    #: camera centre transformed out of the DEM's projected CRS. None when the
    #: run has no LUT or the manifest predates the pose record.
    camera_location: tuple[float, float] | None = None
    #: FILE sources only: True while the run is holding between frames — the clip
    #: has no "stale" to go, so holding is free. Live sources refuse to pause.
    paused: bool = False
    _stop: threading.Event = field(default_factory=threading.Event)
    _pause: threading.Event = field(default_factory=threading.Event)


_LOCK = threading.Lock()
_SESSIONS: dict[str, DetectionSession] = {}


def get_session(session_id: str) -> DetectionSession | None:
    with _LOCK:
        return _SESSIONS.get(session_id)


def set_paused(session_id: str, paused: bool) -> DetectionSession:
    """Pause/resume a FILE run between frames. A live feed has no pause button —
    the camera keeps producing whether anyone listens or not — so live sessions
    refuse rather than silently pretending."""
    session = get_session(session_id)
    if session is None:
        raise DetectionError("no such session.")
    if not session.source.startswith("video:"):
        raise DetectionError(
            "only video-file sessions can pause — a live feed has no pause button; "
            "stop the session instead."
        )
    if session.status not in ("starting", "running"):
        raise DetectionError("the run is already over — nothing to pause.")
    if paused:
        session._pause.set()
    else:
        session._pause.clear()
    session.paused = paused
    return session


def set_overlay(
    session_id: str,
    *,
    boxes: bool | None = None,
    labels: bool | None = None,
    tracks: bool | None = None,
    hud: bool | None = None,
) -> DetectionSession:
    """Steer what the burned-in preview draws, mid-run.

    ★ The panel's Boxes / Labels / Tracks chips call this so they keep working
    WHILE a run is on — the burn-in stays frame-synced (the 2026-08-31 owner
    decision), it just draws only what is asked. ``None`` leaves a flag as it is.
    Plain bool writes; no lock needed against the worker's per-frame reads.
    """
    session = get_session(session_id)
    if session is None:
        raise DetectionError("no such session.")
    if boxes is not None:
        session.overlay_boxes = bool(boxes)
    if labels is not None:
        session.overlay_labels = bool(labels)
    if tracks is not None:
        session.overlay_tracks = bool(tracks)
    if hud is not None:
        session.overlay_hud = bool(hud)
    return session


def set_tracking(session_id: str, on: bool) -> DetectionSession:
    """Turn manual tracking on or off mid-run.

    A run starts ARMED (2026-09-08): clicks are accepted from the first frame.
    Turning it OFF clears every lock: the tracker stops, the ids and the primary
    are dropped, and detection carries on unmarked. Turning it back on re-arms
    the run to accept clicks — nothing is tracked until the operator clicks.
    """
    session = _running_session(session_id)
    session.tracking_on = bool(on)
    if not on:
        with session._track_lock:
            session.track_commands.append({"op": "clear"})
    return session


def queue_track_command(session_id: str, command: dict[str, Any]) -> DetectionSession:
    """Enqueue one click for the worker to apply on its next frame.

    The click carries a pixel in MEDIA coordinates; the worker resolves it
    against THAT frame's detections (the freshest), so a moving object is hit
    where it is now, not where a half-second-old poll last drew it.
    """
    session = _running_session(session_id)
    if not session.tracking_on:
        raise DetectionError("tracking is off for this run — turn it back on first.")
    with session._track_lock:
        session.track_commands.append(command)
    return session


def queue_track_box(
    session_id: str, box: tuple[float, float, float, float], name: str | None
) -> DetectionSession:
    """★ Track what the operator DREW (2026-09-11): enqueue a box, in MEDIA pixels.

    Unlike a click, a box does not need a detection under it — the worker seeds
    the visual tracker on the rectangle itself, so any object in the picture can
    be followed. Drawing one turns tracking on if it was off: the operator has
    just said what to follow, and refusing that with "turn tracking on first"
    would be a ritual for its own sake.
    """
    session = _running_session(session_id)
    x1, y1, x2, y2 = (float(v) for v in box)
    if x2 - x1 < 4 or y2 - y1 < 4:
        raise DetectionError("the box is too small to track — drag a larger rectangle.")
    session.tracking_on = True
    with session._track_lock:
        session.track_commands.append(
            {"op": "box", "x1": x1, "y1": y1, "x2": x2, "y2": y2, "name": name or None}
        )
    return session


def set_track_name(session_id: str, track_id: int, name: str | None) -> DetectionSession:
    """★ Name a track (2026-09-11): "#3" → "white pickup". Empty/null clears it.

    Works on a finished run too — the name is about the data, and an operator
    labelling last night's export is the normal case, not the exception.
    """
    session = get_session(session_id)
    if session is None:
        raise DetectionError("no such detection session.")
    cleaned = " ".join((name or "").split())[:64]
    if cleaned:
        session.track_names[int(track_id)] = cleaned
    else:
        session.track_names.pop(int(track_id), None)
    return session


#: Widest the burned-in preview may be, in pixels. 0 = the camera's own size,
#: which is what an operator asked to see (2026-09-11).
PREVIEW_MAX_WIDTH = 0


def _mark_due(session: DetectionSession, key: Any, now_s: float, gap: float) -> bool:
    """Has this object waited long enough to become a mark again?

    ★ ``gap`` of 0 means every detection marks — see ``DetectSettings.mark_rate_hz``
    for why one a second is the default.
    """
    if gap <= 0.0:
        return True
    last = session.mark_clock.get(key)
    if last is not None and now_s - last < gap:
        return False
    session.mark_clock[key] = now_s
    return True


def _running_session(session_id: str) -> DetectionSession:
    session = get_session(session_id)
    if session is None:
        raise DetectionError("no such session.")
    if session.status not in ("starting", "running"):
        raise DetectionError("the run is over — tracking needs a live session.")
    return session


def list_sessions() -> list[DetectionSession]:
    with _LOCK:
        return sorted(_SESSIONS.values(), key=lambda s: s.started_at, reverse=True)


def stop_session(session_id: str) -> bool:
    session = get_session(session_id)
    if session is None:
        return False
    session._stop.set()
    return True


def _active_for_source(source: str) -> DetectionSession | None:
    with _LOCK:
        for s in _SESSIONS.values():
            if s.source == source and s.status in ("starting", "running"):
                return s
    return None


def latest_raw_frame(source: str, max_age_s: float = 5.0) -> Any | None:
    """The freshest RAW frame a running session holds for ``source``, or None.

    ★ FOR THE DRIFT MONITOR. While a session detects on a camera, the device
    admits no second opener — so the monitor borrows the reader thread's frame
    instead. Staleness is refused: a frame older than ``max_age_s`` means the
    reader is wedged, and judging camera drift from a stuck picture would report
    whatever was true when it stuck.
    """
    session = _active_for_source(source)
    if session is None or session.latest_raw is None:
        return None
    if time.monotonic() - session.latest_raw_t > max_age_s:
        return None
    return session.latest_raw


def drift_rotation_for_source(source: str) -> float | None:
    """The newest running watch's measured rotation for ``source``, in degrees —
    None when nothing is watched or no look has run yet (2026-09-09)."""
    if source.startswith("video:"):
        return None
    from app.services import drift_service  # noqa: PLC0415

    latest = drift_service.latest_status_for_source(source)
    if latest is None:
        return None
    rot = latest.get("rot_deg")
    return None if rot is None else float(rot)


def ground_shift_m(
    rot_deg: float | None,
    camera: tuple[float, float] | None,
    lat: float | None,
    lon: float | None,
) -> float | None:
    """★ THE SHIFT ON THE GROUND AT THIS MARK (2026-09-09, owner ask): the camera's
    measured rotation times the mark's own range from the camera. A far mark moves
    more than a near one for the same rotation — so the figure is per mark, not per
    frame. None when any ingredient is missing."""
    if rot_deg is None or camera is None or lat is None or lon is None:
        return None
    range_m = _haversine_m(camera[0], camera[1], lat, lon)
    return round(math.radians(rot_deg) * range_m, 2)


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Horizontal distance in metres — the same horizontal range the monitor uses."""
    r = 6_371_008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def drift_status_for_source(source: str) -> tuple[str, str | None]:
    """``(status, ref_id)`` — the newest running drift watch's confirmed verdict
    for ``source``, in the stamp vocabulary of ``DRIFT_STATUSES``.

    A stored clip does not drift and cannot be watched, so a ``video:`` source is
    always ``unwatched``. Cheap: one dict scan under the drift registry's lock.
    """
    if source.startswith("video:"):
        return "unwatched", None
    # Call-time import: ``drift_service`` taps this module's frames at call time
    # too; a module-level import either way would close a cycle.
    from app.services import drift_service  # noqa: PLC0415

    latest = drift_service.latest_status_for_source(source)
    if latest is None:
        return "unwatched", None
    status = latest.get("status")
    if not status:
        return "pending", latest.get("ref_id")
    stamp = str(status).lower()
    return (stamp if stamp in DRIFT_STATUSES else "pending"), latest.get("ref_id")


def _camera_location(manifest: dict[str, Any]) -> tuple[float, float] | None:
    """The RECORDING camera's (lat, lon), out of the LUT manifest.

    The manifest stores the solved camera centre ``pose.C`` in the DEM's
    projected CRS and the CRS itself as ``dem.epsg`` — pyproj turns the pair
    into WGS84. Any missing piece returns None rather than a guessed point:
    an attribute table with a wrong camera position is worse than one with
    the column empty.
    """
    # Call-time import: `lut_service` is the LUT bundle's own module and owns this
    # transform; importing it at module level would close a cycle through
    # `accuracy_service`, which the same file already documents.
    from app.services.lut_service import manifest_center  # noqa: PLC0415

    return manifest_center(manifest)


# ─────────────────────────────────────────────────────────────────────────────
# Export — the marks as a dataset with their attribute table
# ─────────────────────────────────────────────────────────────────────────────

#: Attribute-table columns. DBF caps names at 10 chars, so these serve all
#: three formats identically — one table, three containers.
_EXPORT_COLUMNS = (
    "mark_id",
    "class",
    "score",
    "lat",
    "lon",
    "time_utc",
    "time_local",
    "frame",
    "track_id",
    "track_name",
    "predicted",
    "drift",
    "drift_shift_m",
    "centre_m",
    "camera",
    "cam_lat",
    "cam_lon",
    "site",
)


def _export_rows(session: DetectionSession) -> list[dict[str, Any]]:
    cam_lat, cam_lon = session.camera_location or (None, None)
    rows: list[dict[str, Any]] = []
    for i, m in enumerate(session.marks):
        when = session.started_at + timedelta(seconds=float(m.get("time_s", 0.0)))
        rows.append(
            {
                "mark_id": session.marks_dropped + i + 1,
                "class": m["cls_name"],
                "score": m["score"],
                "lat": m["lat"],
                "lon": m["lon"],
                "time_utc": m.get("detected_at") or when.strftime("%Y-%m-%dT%H:%M:%SZ"),
                # ★ The wall-clock the operator lives in — recorded at detection time,
                #   not re-derived at export time with whatever zone the server has then.
                "time_local": m.get("detected_at_local")
                or when.astimezone().isoformat(timespec="seconds"),
                "frame": m["frame_index"],
                "track_id": m.get("track_id"),
                # ★ The operator's name for the track, when one was given.
                "track_name": session.track_names.get(m.get("track_id")),
                "predicted": bool(m.get("predicted", False)),
                # ★ The drift verdict at the moment of detection, and the centre
                #   offset applied (metres, or empty): the file states what it claims.
                "drift": m.get("drift_status", "unwatched"),
                "drift_shift_m": m.get("drift_shift_m"),
                "centre_m": m.get("centre_offset_m"),
                "camera": session.camera_name,
                "cam_lat": cam_lat,
                "cam_lon": cam_lon,
                "site": session.lut_site,
            }
        )
    return rows


def export_marks(session_id: str, fmt: str) -> tuple[bytes, str, str]:
    """The session's marks as (content, media_type, filename).

    Formats: ``csv``, ``geojson``, ``shp`` (a ZIP of the shapefile's sidecars —
    a bare .shp is not a dataset). The attribute table is identical in all
    three; the geometry is WGS84 points.
    """
    session = get_session(session_id)
    if session is None:
        raise DetectionError("no such session.")
    rows = _export_rows(session)
    if not rows:
        raise DetectionError("this run has placed no marks yet — nothing to export.")
    stem = f"detected_marks_{session_id}"

    if fmt == "csv":
        import csv as csv_mod  # noqa: PLC0415
        import io  # noqa: PLC0415

        buf = io.StringIO()
        writer = csv_mod.DictWriter(buf, fieldnames=list(_EXPORT_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
        return buf.getvalue().encode("utf-8"), "text/csv", f"{stem}.csv"

    if fmt == "geojson":
        features = [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
                "properties": {k: r[k] for k in _EXPORT_COLUMNS if k not in ("lat", "lon")},
            }
            for r in rows
        ]
        payload = {"type": "FeatureCollection", "features": features}
        return (
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            "application/geo+json",
            f"{stem}.geojson",
        )

    if fmt == "shp":
        import io  # noqa: PLC0415
        import tempfile  # noqa: PLC0415
        import zipfile  # noqa: PLC0415

        try:
            import geopandas as gpd  # noqa: PLC0415
            from shapely.geometry import Point  # noqa: PLC0415
        except ImportError as exc:
            raise DetectionError(
                "shapefile export needs geopandas — pip install geopandas pyogrio "
                "into the app's Python runtime."
            ) from exc

        gdf = gpd.GeoDataFrame(
            [{k: r[k] for k in _EXPORT_COLUMNS} for r in rows],
            geometry=[Point(r["lon"], r["lat"]) for r in rows],
            crs="EPSG:4326",
        )
        with tempfile.TemporaryDirectory() as tmp:
            shp_path = Path(tmp) / f"{stem}.shp"
            gdf.to_file(shp_path)
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for part in sorted(Path(tmp).iterdir()):
                    zf.write(part, part.name)
        return buf.getvalue(), "application/zip", f"{stem}_shp.zip"

    raise DetectionError(f"unknown export format '{fmt}' — use csv, geojson or shp.")


# ─────────────────────────────────────────────────────────────────────────────
# Start — refusals first, thread second
# ─────────────────────────────────────────────────────────────────────────────


def start_session(
    *,
    source: str,
    model_dir: Path,
    lut_dir: Path | None,
    settings_values: dict[str, Any] | None = None,
    file_path: Path | None = None,
    every_nth: int = 1,
    source_label: str | None = None,
    camera_id: str | None = None,
    detect: bool = True,
) -> DetectionSession:
    """Validate everything that can be validated cheaply, then launch the thread.

    Raises:
        DetectionError: Runtime missing, weights missing, LUT unreadable, a second
            session on a camera already being detected, or a tracker handoff this
            environment cannot honour. Every message names the fix.
    """
    from app.services.live_stream_service import (
        is_device_source,
        validate_stream_url,
    )  # noqa: PLC0415

    if detect:
        probe = _detector_probe(model_dir)
        if not probe["available"]:
            raise DetectionError(probe["reason"])
    else:
        # ★ A tracking-only run needs the tracker, not the detector: no weights,
        #   no torch — a machine that cannot detect can still follow a drawn box.
        tracker = _tracker_probe()
        if not tracker["available"]:
            raise DetectionError(tracker["reason"])

    # ★ A FILE IS A SOURCE TOO — the standalone tool's primary case. The path is
    #   resolved by the ROUTER from a video-library row, never taken from the wire:
    #   free-text paths over HTTP are how a picker becomes a file browser.
    if file_path is not None:
        if not file_path.is_file():
            raise DetectionError("the video file is missing from storage.")
    elif not is_device_source(source):
        source = validate_stream_url(source)

    busy = _active_for_source(source)
    if busy is not None and busy._stop.is_set():
        # ★ RESTART, NOT REFUSAL: the old session is already dying (Stop or
        #   Restart was pressed); give its thread a moment to release the source
        #   instead of bouncing the user for clicking quickly.
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and _active_for_source(source) is not None:
            time.sleep(0.05)
        busy = _active_for_source(source)
    if busy is not None:
        raise DetectionError(
            f"this source is already being detected (session {busy.session_id}) — "
            "stop that session first. Two readers on one camera starve each other."
        )

    from app.services.detection.models import DetectSettings  # noqa: PLC0415

    values = dict(settings_values or {})
    # ★ The model must be one of the local files — DetectSettings would silently fall
    #   back to its own default name, and that default may not exist HERE.
    local = list_models(model_dir)
    model = values.get("model") or (local[0] if local else None)
    if detect and model not in local:
        raise DetectionError(
            f"model '{model}' is not in {model_dir} (available: {', '.join(local)})."
        )

    from app.services.detection.models import LOCKED_TRACKER_TYPES  # noqa: PLC0415

    wanted_tracker = str(values.get("locked_tracker_type", "vit") or "vit").lower()
    if wanted_tracker not in LOCKED_TRACKER_TYPES:
        raise DetectionError(
            f"unknown tracker '{wanted_tracker}' — this build offers: "
            f"{', '.join(LOCKED_TRACKER_TYPES)}."
        )
    values["locked_tracker_type"] = wanted_tracker

    wanted_handoff = int(float(values.get("tracker_start_frame", 0) or 0))
    if wanted_handoff > 0:
        # Refused, never silently zeroed: the surveyor asked for an algorithm this
        # session cannot run, and a run that quietly does something else instead is
        # the failure mode this codebase exists to avoid.
        tracker = _tracker_probe()
        if not tracker["available"]:
            raise DetectionError(tracker["reason"])
        # Live sources may hand off too (2026-08-20): a dropped-frame gap that
        # breaks CSRT's pixel correspondence now just fails the lock, and the
        # detector-rescue edit re-acquires on that same frame — the failure mode
        # the old refusal guarded against (a silent, permanent loss) is gone.
        if every_nth > 1 and file_path is not None:
            raise DetectionError(
                "the CSRT tracker follows pixels from one frame to the NEXT — "
                "skipping frames destroys the correspondence it works from. Set "
                "'every Nth frame' to 1 (every frame) to use the handoff."
            )
    values["tracker_start_frame"] = wanted_handoff
    values["model"] = model

    # The settings dataclass sanitises every field into a range the pipeline can
    # actually run — garbage becomes defaults, not crashes.
    det_settings = DetectSettings.from_dict(values)

    lut = None
    lut_summary = None
    if lut_dir is not None:
        from app.services.detection.lut import GeoLut, LutError  # noqa: PLC0415

        try:
            lut = GeoLut(str(lut_dir))
        except LutError as exc:
            raise DetectionError(str(exc)) from exc
        lut_summary = lut.summary()
        centre = lut.center()
        if centre is not None:
            # ★ So the marks map can open ON THE SITE instead of a world view while
            #   the first mark is still seconds away.
            lut_summary["center"] = [float(centre[0]), float(centre[1])]

    session = DetectionSession(
        session_id=uuid_mod.uuid4().hex[:12],
        source=source,
        lut_site=(lut_summary or {}).get("site"),
        settings=det_settings.to_dict(),
        lut_summary=lut_summary,
        camera_name=source_label or source,
        camera_location=_camera_location(lut.manifest) if lut is not None else None,
        camera_id=camera_id,
        detect=detect,
    )
    with _LOCK:
        _SESSIONS[session.session_id] = session
        # Old finished sessions have no further use — cap the registry.
        done = [s for s in _SESSIONS.values() if s.status in ("stopped", "failed")]
        for stale in sorted(done, key=lambda s: s.started_at)[:-10]:
            _SESSIONS.pop(stale.session_id, None)

    thread = threading.Thread(
        target=_run,
        args=(session, det_settings, model_dir, lut, file_path, max(1, min(10, int(every_nth)))),
        name=f"detect-{session.session_id}",
        daemon=True,
    )
    thread.start()
    return session


# ─────────────────────────────────────────────────────────────────────────────
# The run — reader keeps the freshest frame; this thread detects it
# ─────────────────────────────────────────────────────────────────────────────


#: Detection rows are batched to the database so a 15 fps run costs one INSERT
#: every couple of seconds, not one connection per box (the sync engine is
#: NullPool — every flush is a fresh connection, priced accordingly).
_DB_FLUSH_ROWS = 50
_DB_FLUSH_S = 2.0


def write_detection_rows(rows: list[dict[str, Any]]) -> int:
    """INSERT ``detection_events`` rows over the sync engine; returns the count.

    Shared with ``live_data_service`` — a feed's marks are evidence exactly like
    a run's, and the table is THE record. Raises on failure; callers decide what
    a failure costs (a run: the record, never the run).
    """
    if not rows:
        return 0
    from app.db.session import sync_session  # noqa: PLC0415
    from app.models import DetectionEvent  # noqa: PLC0415

    with sync_session() as db:
        db.add_all([DetectionEvent(**row) for row in rows])
    return len(rows)


def _flush_detection_rows(session: DetectionSession, rows: list[dict[str, Any]]) -> None:
    """Write buffered ``detection_events`` rows. Best-effort BY DESIGN: the run's
    job is to detect, and a database that is down must cost the record, not the
    run — the failure is counted and surfaced in ``db_error``, never raised."""
    if not rows:
        return
    batch, rows[:] = list(rows), []
    try:
        session.db_rows_written += write_detection_rows(batch)
        session.db_error = None
    except Exception as exc:  # noqa: BLE001 — a DB failure is a report, not a death
        session.db_rows_failed += len(batch)
        session.db_error = _clean(f"{type(exc).__name__}: {exc}")


def _run(  # noqa: ANN401 — package types, service-local
    session: DetectionSession,
    det_settings: Any,
    model_dir: Path,
    lut: Any,
    file_path: Path | None = None,
    every_nth: int = 1,
) -> None:
    from app.services.live_stream_service import open_capture  # noqa: PLC0415
    from app.services.detection.detector import (  # noqa: PLC0415
        Detector,
        DetectorError,
        device_label,
        resolve_device,
    )
    from app.services.detection.ground import (  # noqa: PLC0415
        centre_offset_m,
        ground_point,
        push_from_camera,
    )

    cap = None
    reader: threading.Thread | None = None
    pending_rows: list[dict[str, Any]] = []
    try:
        # ── the model, from a LOCAL file only ────────────────────────────────
        # ★ TRACKING-ONLY runs build no detector at all: nothing to load, nothing
        #   to warm, and `detections` below is simply empty every frame.
        detector = None
        if session.detect:
            weights = model_dir / det_settings.model
            detector = Detector(str(weights), det_settings.device)
            detector.start_run(det_settings)
        # ★ Manual tracking (2026-09-03): the operator's chosen locks. Lazy — a run
        #   whose operator never presses "Start tracking" pays nothing for it.
        from app.services.detection.manual_tracking import ManualTracker  # noqa: PLC0415

        manual: ManualTracker | None = None
        device = resolve_device(det_settings.device)
        session.device = device
        session.device_name = device_label(device)

        # ── the source ───────────────────────────────────────────────────────
        # ★ A FILE reads sequentially — every frame, no freshest-drop: a file does
        #   not go stale while you work on it, and dropping its frames would just be
        #   losing data. Only a LIVE feed pays the drop to stay current.
        is_file = file_path is not None
        if is_file:
            import cv2  # noqa: PLC0415

            cap = cv2.VideoCapture(str(file_path))
            if not cap.isOpened():
                raise DetectionError("the video file could not be decoded.")
        else:
            # ★ RETRY, BRIEFLY. The panel is still re-streaming this camera at the
            #   moment Start is pressed, and a V4L2 device admits ONE opener — so the
            #   first attempt loses to the app's own preview. The page switches to
            #   this session's stream as soon as the session exists, which drops the
            #   preview and frees the device; these few seconds are that handover.
            #   A camera that is genuinely absent or held by ANOTHER program still
            #   fails, with the same words as before.
            # ★ AND PREEMPT FIRST (2026-09-02): waiting for the BROWSER to drop its
            #   <img> made the handover a race the run sometimes lost ("turn on the
            #   detection and the app loses the stream"). The run now tells the
            #   proxy re-streams to release the device server-side and waits until
            #   they actually have — the retry below is then the belt, not the plan.
            from app.services.live_stream_service import preempt_device  # noqa: PLC0415

            preempt_device(session.source)
            deadline = time.monotonic() + DEVICE_HANDOVER_S
            while True:
                try:
                    cap = open_capture(session.source)
                    break
                except Exception:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.25)

        # Freshest-frame reader: one slot, always overwritten. `dropped` counts
        # what the detector never saw — the honest price of staying live.
        slot_lock = threading.Lock()
        slot: dict[str, Any] = {"frame": None, "t": 0.0, "seq": 0}
        reader_dead = threading.Event()

        def read() -> None:
            seq = 0
            try:
                while not session._stop.is_set():
                    ok, frame = cap.read()
                    if not ok:
                        break
                    seq += 1
                    with slot_lock:
                        slot["frame"], slot["t"], slot["seq"] = frame, time.monotonic(), seq
                    # ★ The drift monitor's tap: the same pristine frame, shared by
                    #   reference (never mutated — boxes burn into a copy). One
                    #   camera, one opener, two consumers.
                    session.latest_raw, session.latest_raw_t = frame, time.monotonic()
            finally:
                # ★ THE READER RELEASES WHAT IT READS (2026-08-30). The run thread
                #   used to release the capture in ITS `finally` — while this thread
                #   was still blocked inside `cap.read()` on the same object. FFmpeg
                #   then tore the decoder down under a live read and the API died
                #   with a general protection fault in libavutil (kernel log), on
                #   every Stop, every ended run and every error path of a live
                #   source. Whoever is inside `read()` is the only one who can know
                #   the read is over, so the release happens here, after it.
                try:
                    cap.release()
                except Exception:  # noqa: BLE001 — best-effort teardown
                    pass
                reader_dead.set()

        if not is_file:
            reader = threading.Thread(
                target=read, name=f"detect-read-{session.session_id}", daemon=True
            )
            reader.start()

        # ★ One object, one fix per period (2026-09-11) — see
        #   ``DetectSettings.mark_rate_hz``. Fixed for the run, so it is computed
        #   here rather than per frame.
        mark_gap = 0.0 if det_settings.mark_rate_hz <= 0 else 1.0 / det_settings.mark_rate_hz

        session.status = "running"
        started = time.monotonic()
        last_seq = 0
        last_frame_t = time.monotonic()
        fps_ema = 0.0
        last_done_t = time.monotonic()
        last_db_flush = time.monotonic()

        while not session._stop.is_set():
            if is_file:
                # ★ The pause: hold BETWEEN frames, burn nothing. The MJPEG stream
                #   simply stops receiving new parts and the player keeps showing
                #   the frame the run paused on.
                while session._pause.is_set() and not session._stop.is_set():
                    time.sleep(0.05)
                if session._stop.is_set():
                    break
                # ★ THE SPEED DIAL FOR FILES. Frames between detections are grab()bed
                #   — advanced without decoding — so a clip finishes in ~1/N the time.
                #   This loop owns the stride, NOT ``DetectSettings`` (which pins
                #   frame_stride=1 because the tracker needs every frame — so
                #   `start_session` refuses every_nth > 1 once a handoff is on).
                #   Skips are counted in `frames_dropped` — the same honesty as
                #   the live drop.
                if last_seq > 0:
                    for _ in range(every_nth - 1):
                        if not cap.grab():
                            break
                        session.frames_dropped += 1
                ok, frame = cap.read()
                if not ok:
                    break  # end of the clip — the run is complete
                seq = last_seq + 1
            else:
                with slot_lock:
                    frame, seq = slot["frame"], slot["seq"]
                if frame is None or seq == last_seq:
                    if reader_dead.is_set():
                        break
                    if time.monotonic() - last_frame_t > SOURCE_TIMEOUT_S:
                        raise DetectionError(
                            f"the source went silent for {SOURCE_TIMEOUT_S:.0f} s — "
                            "camera unplugged, or the stream ended."
                        )
                    time.sleep(0.01)
                    continue
                session.frames_dropped += max(0, seq - last_seq - 1)
            last_seq = seq
            last_frame_t = time.monotonic()

            if session.media_width == 0:
                session.media_height, session.media_width = frame.shape[:2]
            media_size = (session.media_width, session.media_height)
            t_s = time.monotonic() - started

            detections = (
                detector.detect(
                    frame, det_settings, frame_index=session.frames_done, time_s=t_s
                )
                if detector is not None
                else []
            )

            # ★ MANUAL TRACKING (2026-09-03), armed from the first frame (2026-09-08).
            #   The operator's chosen objects are followed by visual locks and
            #   carry stable ids into the boxes AND the marks (the attribute table
            #   gains the id). Detection above still ran on the whole frame — this
            #   only decides which of those objects also get a lock. The clicks are
            #   resolved against THIS frame's detections, so a moving object is hit
            #   where it is now.
            if session.tracking_on or (manual is not None and manual.has_locks()):
                if manual is None:
                    try:
                        manual = ManualTracker(det_settings.locked_tracker_type)
                    except Exception as exc:  # noqa: BLE001 — a missing tracker wheel
                        # Disable tracking rather than killing a running detection:
                        # the surveyor keeps their detections, the button just fails.
                        session.tracking_on = False
                        session.db_error = _clean(f"tracking unavailable: {exc}")
                        log.warning("manual tracking unavailable: %s", exc)
                if manual is not None:
                    with session._track_lock:
                        commands = session.track_commands
                        session.track_commands = []
                    if not session.tracking_on:
                        commands = [*commands, {"op": "clear"}]
                    detections = manual.step(frame, detections, commands)
                    session.tracked_ids = manual.ids()
                    session.primary_track_id = manual.primary_id
                    if manual.pending_names:
                        session.track_names.update(manual.pending_names)
                        manual.pending_names = {}

            # ★ The detection's WALL CLOCK, stamped once per frame: UTC is the
            #   queryable truth, the local rendering is the operator's answer to
            #   "what time did that happen HERE" — recorded now, with this
            #   machine's zone and offset, because re-deriving it later answers
            #   with whatever zone the server has then (owner request 2026-08-31).
            detected_utc = datetime.now(UTC)
            detected_local_iso = detected_utc.astimezone().isoformat(timespec="seconds")
            detected_utc_iso = detected_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

            # ★ THE DRIFT STAMP, read once per frame: the confirmed verdict of the
            #   newest watch on this camera RIGHT NOW. Stamped on every mark and
            #   row of this frame, so "was the camera trusted when this was seen"
            #   is a column, not a reconstruction from two logs.
            drift_status, drift_ref = drift_status_for_source(session.source)
            session.drift_status, session.drift_ref_id = drift_status, drift_ref
            under_alert = drift_status in DRIFT_ALERT_STATUSES
            drift_rot = drift_rotation_for_source(session.source)

            new_marks: list[dict[str, Any]] = []
            boxes: list[dict[str, Any]] = []
            for d in detections:
                u, v = ground_point(d.box, det_settings, media_size)
                d.ground_u, d.ground_v = u, v
                placed = False
                lat = lon = None
                offset_m: float | None = None
                if lut is not None:
                    lat, lon = lut.lookup(u, v, media_size=media_size)
                    if lat is None:
                        session.skipped_no_terrain += 1
                    else:
                        placed = True
                        if det_settings.centre_marks:
                            # ★ Opt-in: push the near-edge mark to the object's
                            #   centre, and RECORD the metres — see ground.py.
                            lat, lon, offset_m = push_from_camera(
                                lat,
                                lon,
                                session.camera_location,
                                centre_offset_m(d.cls_name),
                            )
                        # ★ One object, one fix per period — the flood this used
                        #   to produce is what made the app stutter, not the
                        #   camera. The detection itself is untouched: it still
                        #   counts, still draws, still writes its row.
                        key: Any = (
                            d.track_id
                            if d.track_id is not None
                            else (d.cls_name, round(lat, 5), round(lon, 5))
                        )
                        if not _mark_due(session, key, t_s, mark_gap):
                            # ★ Not a mark this time — but still a DETECTION: it
                            #   counts, it draws, and its durable row is written
                            #   below. Only the point on the map is thinned, so
                            #   the record stays whole while the display stops
                            #   drowning.
                            session.marks_thinned += 1
                        else:
                            if under_alert:
                                session.marks_under_alert += 1
                            new_marks.append(
                                {
                                    "lat": lat,
                                    "lon": lon,
                                    "score": round(d.score, 3),
                                    "cls_name": d.cls_name,
                                    "frame_index": session.frames_done,
                                    "time_s": round(t_s, 2),
                                    "u": round(u, 1),
                                    "v": round(v, 1),
                                    "track_id": d.track_id,
                                    "predicted": d.predicted,
                                    "detected_at": detected_utc_iso,
                                    "detected_at_local": detected_local_iso,
                                    "drift_status": drift_status,
                                    "drift_ref_id": drift_ref,
                                    "drift_shift_m": ground_shift_m(
                                        drift_rot, session.camera_location, lat, lon
                                    ),
                                    "centre_offset_m": offset_m,
                                }
                            )
                session.counts[d.cls_name] += 1
                boxes.append(
                    {
                        "x1": round(d.box.x1, 1),
                        "y1": round(d.box.y1, 1),
                        "x2": round(d.box.x2, 1),
                        "y2": round(d.box.y2, 1),
                        "score": round(d.score, 3),
                        "cls_name": d.cls_name,
                        "track_id": d.track_id,
                        "predicted": d.predicted,
                        "placed": placed,
                    }
                )
                # ★ EVERY detection becomes a durable row — placed or not, tracked
                #   or not. A run with no LUT still saw the car; the row says when
                #   (UTC + local) and which track (#N) it was.
                pending_rows.append(
                    {
                        "kind": "detection",
                        "session_id": session.session_id,
                        "source": session.source,
                        "camera_id": session.camera_id,
                        "camera_name": session.camera_name,
                        "lut_site": session.lut_site,
                        "track_id": d.track_id,
                        "cls_name": d.cls_name,
                        "score": float(min(max(d.score, 0.0), 1.0)),
                        "predicted": bool(d.predicted),
                        "frame_index": session.frames_done,
                        "time_s": round(t_s, 3),
                        "u": round(u, 1),
                        "v": round(v, 1),
                        "lat": lat,
                        "lon": lon,
                        "detected_at": detected_utc,
                        "detected_at_local": detected_local_iso,
                        "drift_status": drift_status,
                        "drift_ref_id": drift_ref,
                        "centre_offset_m": offset_m,
                    }
                )

            if pending_rows and (
                len(pending_rows) >= _DB_FLUSH_ROWS
                or time.monotonic() - last_db_flush >= _DB_FLUSH_S
            ):
                _flush_detection_rows(session, pending_rows)
                last_db_flush = time.monotonic()

            now = time.monotonic()
            dt = now - last_done_t
            last_done_t = now
            if dt > 0:
                inst = 1.0 / dt
                fps_ema = inst if fps_ema == 0.0 else 0.8 * fps_ema + 0.2 * inst

            session.marks.extend(new_marks)
            if len(session.marks) > MAX_MARKS:
                overflow = len(session.marks) - MAX_MARKS
                del session.marks[:overflow]
                session.marks_dropped += overflow
            session.frames_done += 1
            session.fps = round(fps_ema, 1)
            session.phase = (
                detector.algorithm_status()["phase"] if detector is not None else "tracking"
            )
            # ★ EVERY source serves its own preview now, not just files. A LOCAL
            #   CAMERA CAN ONLY BE OPENED ONCE: while the live panel re-streams
            #   /dev/videoN through `GET /live/stream`, the server already holds it,
            #   and this run's second open failed with "could not open capture
            #   device" — the app losing a fight with itself. The panel therefore
            #   watches THIS stream while a run is on, which releases the device to
            #   the detector and shows the boxes burned into the picture besides.
            import cv2  # noqa: PLC0415

            # ★ THE PREVIEW IS THE CAMERA'S OWN RESOLUTION (2026-09-11, owner ask).
            #   It used to be capped at 1280 wide "because a 4K preview is
            #   bandwidth, not insight" — but the operator watching a 1920 camera
            #   was being shown two thirds of it whenever a run was on, and the
            #   bandwidth it saved is loopback on the same machine. Measured cost
            #   of the full frame: 4.0 ms to encode against 1.8 ms, on a 40 ms
            #   budget at 25 fps. Raise ``PREVIEW_MAX_WIDTH`` above 0 if a camera
            #   ever makes that trade worth taking again.
            scale = 1.0
            small = frame
            if PREVIEW_MAX_WIDTH and frame.shape[1] > PREVIEW_MAX_WIDTH:
                scale = PREVIEW_MAX_WIDTH / frame.shape[1]
                small = cv2.resize(
                    frame, (PREVIEW_MAX_WIDTH, int(frame.shape[0] * scale))
                )
            # ★ THE BOXES ARE BURNED IN. The preview streams at detect rate while
            #   the wire state polls at ~2 Hz — an SVG overlay on top of a stream
            #   would lag its own picture. One JPEG carrying frame AND boxes can
            #   never drift apart. Yellow = YOLO's own sighting, orange = the
            #   tracker's estimate — the same code the on-screen legend uses.
            # ★ AND THE CHIPS STILL WORK (2026-09-01): the panel's Boxes / Labels /
            #   Tracks toggles write session.overlay_* mid-run and this reads them
            #   per frame — same semantics as the client canvas (rectangles gated
            #   by Boxes, the text by Labels, the #id suffix by Tracks).
            draw_text = session.overlay_labels or session.overlay_tracks
            if boxes and (session.overlay_boxes or draw_text):
                if small is frame:
                    small = frame.copy()
                from app.services.detection import hud  # noqa: PLC0415

                for b in boxes:
                    tid = b["track_id"]
                    # ★ THE THREE STATES, EACH ITS OWN COLOUR (2026-09-03, owner ask):
                    #   LOCKED (the primary) is GREEN and says so; TRACKED is CYAN and
                    #   says so; everything else is a plain YELLOW detection. A steady-
                    #   boxes coast is predicted but untracked, so it stays yellow —
                    #   orange (the tracker's own estimate) never shows without an id.
                    is_primary = (
                        session.primary_track_id is not None and tid == session.primary_track_id
                    )
                    is_tracked = tid is not None and not is_primary
                    if is_primary:
                        colour = (94, 197, 34)  # BGR green
                    elif is_tracked:
                        colour = (238, 211, 34)  # BGR cyan
                    else:
                        colour = (21, 204, 250)  # BGR yellow — plain detection
                    x1, y1 = int(b["x1"] * scale), int(b["y1"] * scale)
                    x2, y2 = int(b["x2"] * scale), int(b["y2"] * scale)
                    # ★ HUD LOOK, OPT-IN (2026-09-03): the HUD chip swaps the plain
                    #   rectangle for corner brackets — a sensor reticle framing the
                    #   object, with a centre crosshair on the LOCKED target. Same
                    #   shapes as the client canvas (see hud.py). Off (the default),
                    #   it is the plain box it always was.
                    if is_primary or is_tracked or session.overlay_boxes:
                        if session.overlay_hud:
                            thick = 2 if is_primary else 1
                            arm = hud.corner_len(x2 - x1, y2 - y1)
                            for pa, pb in hud.corner_segments(x1, y1, x2, y2, arm):
                                cv2.line(small, pa, pb, colour, thick, cv2.LINE_AA)
                            if is_primary:
                                for pa, pb in hud.crosshair_segments(
                                    (x1 + x2) // 2, (y1 + y2) // 2
                                ):
                                    cv2.line(small, pa, pb, colour, thick, cv2.LINE_AA)
                        else:
                            cv2.rectangle(small, (x1, y1), (x2, y2), colour, 3 if is_primary else 2)
                    parts: list[str] = []
                    # The state word rides ABOVE the box regardless of the chips —
                    # it is the answer to "is this one locked or tracked".
                    if is_primary:
                        parts.append("LOCKED")
                    elif is_tracked:
                        parts.append("TRACKED")
                    if session.overlay_labels:
                        parts.append(f"{b['cls_name']} {int(b['score'] * 100)}%")
                    if session.overlay_tracks and tid is not None:
                        parts.append(f"#{tid}")
                        name = session.track_names.get(tid)
                        if name:
                            parts.append(name)
                    if parts:
                        text = " ".join(parts)
                        if session.overlay_hud:
                            # A HUD tag: a dark backing bar with a coloured left tick,
                            # so the readout stays legible over a busy scene.
                            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                            ty = max(th + 5, y1 - 5)
                            bx1, by1, bx2, by2 = x1 - 1, ty - th - 4, x1 + tw + 6, ty + 3
                            cv2.rectangle(small, (bx1, by1), (bx2, by2), (18, 18, 18), -1)
                            cv2.line(small, (bx1, by1), (bx1, by2), colour, 2, cv2.LINE_AA)
                            cv2.putText(
                                small,
                                text,
                                (x1 + 4, ty),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.5,
                                colour,
                                1,
                                cv2.LINE_AA,
                            )
                        else:
                            cv2.putText(
                                small,
                                text,
                                (x1, max(14, y1 - 6)),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.5,
                                colour,
                                1,
                                cv2.LINE_AA,
                            )
            ok_enc, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 78])
            if ok_enc:
                session.latest_jpeg = buf.tobytes()
                session.jpeg_seq += 1

            session.latest = {
                "seq": seq,
                "frame_index": session.frames_done - 1,
                "time_s": round(t_s, 2),
                "width": session.media_width,
                "height": session.media_height,
                "boxes": boxes,
            }

            if det_settings.max_frames and session.frames_done >= det_settings.max_frames:
                break

        session.status = "stopped"
    except (DetectionError, DetectorError) as exc:
        session.status = "failed"
        session.error = _clean(str(exc))
    except Exception as exc:  # noqa: BLE001 — the thread must never die silently
        log.exception("detection session %s failed", session.session_id)
        session.status = "failed"
        session.error = _clean(f"{type(exc).__name__}: {exc}")
    finally:
        session._stop.set()
        # The tail of the record: whatever the last interval buffered goes to the
        # database before the run is declared over.
        _flush_detection_rows(session, pending_rows)
        if reader is not None:
            # ★ Live: the reader owns the release (see `read`). Give it the time one
            #   blocked read can take to return, so the source is free before the
            #   next Start — but never touch the capture from this thread.
            reader.join(timeout=READER_JOIN_S)
        elif cap is not None:
            try:
                cap.release()
            except Exception:  # noqa: BLE001 — best-effort teardown
                pass
