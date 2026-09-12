"""Session recordings — the live stream AND its attribute table, in one folder.

★ WHY (2026-09-02, owner ask). A detection run is evidence that evaporates: the
stream is watched and gone, the marks ring forgets. Record turns a watch into a
KEEPSAKE — one folder per recording inside a recordings library::

    <capture library>/recordings/<camera>-<YYYYmmdd-HHMMSS>/
        video.mp4         the stream as watched (boxes burned in during a run)
        detections.csv    the run's attribute table for the recorded window
        satellite.png     the scene on satellite imagery, camera + marks drawn on
        satellite.pgw     its world file — the PNG lands itself on a GIS
        satellite.txt     the imagery provider, its attribution and its terms
        marks.geojson     the placed detections as points (WGS84)
        meta.json         camera, source, window, counts — what the folder is

★ ONE BUTTON TAKES THE WHOLE SCENE (2026-09-12, owner ask). ``package_path``
zips the folder into the shape an operator would have built by hand — the video,
the map and the table each in their own lane under one session directory::

    <camera>-<YYYYmmdd-HHMMSS>/
        video/  video.mp4, poster.jpg
        map/    satellite.png, satellite.pgw, satellite.txt, marks.geojson
        table/  detections.csv
        meta.json, README.txt

The folder ON DISK stays flat: every reader here (preview, poster, table, trim)
addresses it that way, and so does every recording made before this. The lanes
are the package's shape, built at download.

★ WHAT THE VIDEO IS. The recorder tails the SAME frames the operator watches:
a running detection session's burned-in preview when one is on, else the live
proxy's re-stream frames. Constant-fps writing (the freshest frame each tick)
keeps wall-clock duration honest without fragile timestamp math.

★ THE CSV IS THE SESSION'S OWN TABLE. Columns come from
``detection_service._export_rows`` — the same attribute table the export
buttons produce — filtered to the recording's window. A recording with no run
still writes the header row: an empty table is an answer, not an error.

★ NO LUT, SMALLER TABLE (2026-09-02, owner ask). A run without a lookup table
places nothing, so the full table's LUT-derived columns (lat/lon, drift,
centre_m, site, camera position) would all be empty lies. Such a recording
saves detections + classes + time only — from ``detection_events``, where the
run already records every box durably, placed or not.

★ WATCHED IN THE APP (2026-09-07, owner ask). The recorder writes MPEG-4 Part 2
(OpenCV's ``mp4v``) — nothing a browser decodes — so the first request to watch
a recording derives ``preview.mp4`` (H.264) beside it with the bundled ffmpeg
(``ensure_preview``). ``recording_table`` hands the CSV over as rows placed on
the recording's own clock (seconds since ``started_at``) so the player and the
table can follow each other, and ``trim_recording`` cuts a window into a NEW
folder — video, the window's rows, meta — never touching the original.
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
import math
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.core.config import Settings

log = get_logger(__name__)

__all__ = [
    "MARKS",
    "PLAYABLE",
    "POSTER",
    "SATELLITE",
    "SAT_SIDECAR",
    "WORLDFILE",
    "Recording",
    "RecordingError",
    "delete_library_entry",
    "ensure_poster",
    "ensure_preview",
    "ensure_satellite_map",
    "get_recording",
    "library_entries",
    "library_file",
    "package_path",
    "recording_for_source",
    "recording_table",
    "recordings_root",
    "start_recording",
    "stop_recording",
    "trim_recording",
    "write_satellite_map",
]

_FPS = 10.0
#: The columns, in order — detection_service._export_rows' own, pinned here so a
#: recording CSV opens identically to a session export.
_CSV_COLUMNS = [
    "mark_id",
    "class",
    "score",
    "lat",
    "lon",
    "time_utc",
    "time_local",
    "frame",
    "track_id",
    "predicted",
    "drift",
    "drift_shift_m",
    "centre_m",
    "camera",
    "cam_lat",
    "cam_lon",
    "site",
]
#: The no-LUT table: what a run without a lookup table can honestly claim —
#: the detection, its class, and when. Nothing LUT-referred.
_CSV_COLUMNS_NO_LUT = [
    "detection_id",
    "class",
    "score",
    "time_utc",
    "time_local",
    "frame",
    "track_id",
    "camera",
]


class RecordingError(Exception):
    """A refusal with a reason — never a bare 500."""


@dataclass
class Recording:
    """One in-progress (or just-finished) recording."""

    recording_id: str
    source: str
    camera_name: str
    folder: Path
    status: str = "recording"  # recording | done | failed
    error: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None
    frames: int = 0
    marks: int = 0
    video_bytes: int = 0
    #: ★ The settings the recording was started with. The recorder thread needs
    #: them at FINALIZE to fetch the scene's satellite chip (2026-09-12); nothing
    #: else in the thread touches configuration.
    settings: Any = field(default=None, repr=False)
    #: What was written into ``video.mp4`` — "h264" once it is encoded directly
    #: (2026-09-11), "mp4v" when the ffmpeg fallback had to be used.
    video_codec: str = "h264"
    _stop: threading.Event = field(default_factory=threading.Event, repr=False)
    _done: threading.Event = field(default_factory=threading.Event, repr=False)


_RECORDINGS: dict[str, Recording] = {}
_LOCK = threading.Lock()


def recordings_root(settings: Settings) -> Path:
    """The library folder — always inside the visible LandExplorer folder.

    ★ Owner ask (2026-09-02): recordings live where the user can FIND them on
    the PC — the LandExplorer capture folder — never the app's hidden data dir.
    """
    base = settings.capture_export_dir
    root = (Path(base) if base else Path("~/Pictures/LandExplorer")).expanduser() / "recordings"
    root.mkdir(parents=True, exist_ok=True)
    return root


class _H264Writer:
    """Frames straight into H.264, with no second pass over the file.

    ★ WHY THIS REPLACED ``cv2.VideoWriter`` (2026-09-11, owner ask: "stop the
    transcoding"). The recorder used to write MPEG-4 Part 2 — a 1999 codec that
    no browser decodes and that OpenCV gives no rate control over — and the first
    request to watch then re-encoded the whole file to H.264. What you watched
    was therefore a SECOND-GENERATION copy of an already lossy file. Measured on
    a real clip: the old chain landed at SSIM 0.966 and 2.3 MB; encoding once,
    from the same frames at CRF 23, gives 0.972 at 1.2 MB — better picture, half
    the size, and the recording is playable the moment it is finished.

    ★ IT NEVER FAILS THE RECORDING. If ffmpeg cannot start, the caller falls back
    to the old writer: a recording that saves something imperfect beats one that
    saves nothing because a codec was missing.
    """

    def __init__(self, path: Path, size: tuple[int, int], fps: float) -> None:
        import subprocess

        width, height = size
        # H.264 4:2:0 refuses an odd dimension; trunc, never round, so a frame is
        # cropped by a pixel rather than stretched.
        cmd = [
            _ffmpeg_exe(), "-y", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "bgr24",
            "-s", f"{width}x{height}", "-r", f"{fps:g}", "-i", "-",
            "-an",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(path),
        ]
        self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    def write(self, frame: Any) -> None:
        stdin = self._proc.stdin
        if stdin is None:
            return
        try:
            stdin.write(frame.tobytes())
        except (BrokenPipeError, ValueError):
            # ffmpeg died mid-run; the frames already written are still a video.
            self._proc.stdin = None  # type: ignore[assignment]

    def release(self) -> None:
        """Close the pipe and let ffmpeg finish the container (moov, faststart)."""
        import contextlib

        if self._proc.stdin is not None:
            with contextlib.suppress(Exception):
                self._proc.stdin.close()
        with contextlib.suppress(Exception):
            self._proc.wait(timeout=30)


def _slug(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
    return cleaned[:48] or "camera"


def _current_jpeg(source: str) -> bytes | None:
    """The freshest frame the operator is seeing for ``source`` — run or preview."""
    from app.services import detection_service, live_stream_service

    for s in detection_service.list_sessions():
        if s.source == source and s.status in ("starting", "running") and s.latest_jpeg:
            return s.latest_jpeg
    ts = live_stream_service._LAST_FRAME_T.get(source, 0.0)
    if time.monotonic() - ts <= 5.0:
        return live_stream_service._LAST_FRAME.get(source)
    return None


def _rows_for_window(source: str, started: datetime, ended: datetime) -> list[dict[str, Any]]:
    """The attribute-table rows every session on ``source`` produced in the window."""
    from app.services import detection_service

    lo = started.isoformat().replace("+00:00", "Z")
    hi = ended.isoformat().replace("+00:00", "Z")
    rows: list[dict[str, Any]] = []
    for s in detection_service.list_sessions():
        if s.source != source:
            continue
        for row in detection_service._export_rows(s):
            t = str(row.get("time_utc") or "")
            if lo <= t <= hi:  # ISO-8601 Z strings sort chronologically
                rows.append(row)
    rows.sort(key=lambda r: str(r.get("time_utc")))
    return rows


def _detection_events_between(source: str, started: datetime, ended: datetime) -> list[Any]:
    """The window's UNPLACED ``detection_events`` rows — a no-LUT run's record."""
    from sqlalchemy import select

    from app.db.session import sync_session
    from app.models import DetectionEvent

    with sync_session() as db:
        return list(
            db.scalars(
                select(DetectionEvent)
                .where(
                    DetectionEvent.source == source,
                    DetectionEvent.kind == "detection",
                    DetectionEvent.lat.is_(None),
                    DetectionEvent.detected_at >= started,
                    DetectionEvent.detected_at <= ended,
                )
                .order_by(DetectionEvent.detected_at, DetectionEvent.frame_index)
            ).all()
        )


def _bare_rows_for_window(rec: Recording) -> list[dict[str, Any]]:
    """Detections + classes + time for a no-LUT window, out of the durable table.

    Best-effort like the run's own flush: a database that is down costs the
    table's rows, never the recording. When the run is still going, its batcher
    is given one flush interval to land the window's tail before the query.
    """
    from app.services import detection_service

    if any(
        s.source == rec.source and s.status in ("starting", "running")
        for s in detection_service.list_sessions()
    ):
        time.sleep(detection_service._DB_FLUSH_S + 0.5)
    try:
        events = _detection_events_between(
            rec.source, rec.started_at, rec.ended_at or rec.started_at
        )
    except Exception as exc:  # a DB failure is a report, not a death
        log.warning("recording.no_lut_rows_unavailable", source=rec.source, error=str(exc))
        return []
    return [
        {
            "detection_id": i + 1,
            "class": e.cls_name,
            "score": e.score,
            "time_utc": e.detected_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "time_local": e.detected_at_local,
            "frame": e.frame_index,
            "track_id": e.track_id,
            "camera": e.camera_name or rec.camera_name,
        }
        for i, e in enumerate(events)
    ]


def _finalize(rec: Recording, writer: Any, video_path: Path) -> None:
    rec.ended_at = datetime.now(UTC)
    if writer is not None:
        with contextlib.suppress(Exception):  # best-effort teardown
            writer.release()
    if video_path.exists():
        rec.video_bytes = video_path.stat().st_size

    rows = _rows_for_window(rec.source, rec.started_at, rec.ended_at)
    columns, table = _CSV_COLUMNS, "marks"
    if not rows:
        # ★ No placed marks in the window = the run had no LUT (or none ran).
        #   The table shrinks to what is honest: detections + classes + time.
        rows = _bare_rows_for_window(rec)
        columns, table = _CSV_COLUMNS_NO_LUT, "detections"
    rec.marks = len(rows)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    w.writeheader()
    for row in rows:
        w.writerow(row)
    (rec.folder / "detections.csv").write_text(buf.getvalue(), encoding="utf-8")

    # ★ THE SCENE ITSELF (2026-09-12). Best-effort by construction — see
    #   ``write_satellite_map``: no imagery, or nothing placed, costs the map and
    #   never the recording.
    window = f"{_iso(rec.started_at)} — {_iso(rec.ended_at)}"
    sat = (
        write_satellite_map(rec.settings, rec.folder, rows, rec.camera_name, window=window)
        if rec.settings is not None
        else None
    )

    meta = {
        "recording_id": rec.recording_id,
        "camera_name": rec.camera_name,
        "source": rec.source,
        "started_at": rec.started_at.isoformat().replace("+00:00", "Z"),
        "ended_at": rec.ended_at.isoformat().replace("+00:00", "Z"),
        "duration_s": round((rec.ended_at - rec.started_at).total_seconds(), 1),
        "frames": rec.frames,
        "marks": rec.marks,
        "video": "video.mp4" if rec.video_bytes > 0 else None,
        #: ★ What is IN video.mp4 (2026-09-11). "h264" plays as it stands; an older
        #: recording has no marker and is transcoded on the first watch as before.
        "video_codec": rec.video_codec,
        "csv": "detections.csv",
        #: ``marks`` = the full LUT-placed table; ``detections`` = the no-LUT one.
        "table": table,
        #: The satellite map of the scene, or None when nothing could be placed on
        #: the ground (no LUT) or imagery was out of reach at stop.
        "map": sat,
        #: True once a map has been TRIED for this folder — so packaging does not
        #: re-fetch imagery for a scene that will never have one.
        "map_attempted": True,
    }
    (rec.folder / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    rec.status = "done"
    log.info(
        "recording.saved",
        folder=str(rec.folder),
        frames=rec.frames,
        marks=rec.marks,
    )


def _record(rec: Recording) -> None:
    """The recorder thread: freshest frame each tick, constant fps, lazy writer."""
    import cv2
    import numpy as np

    video_path = rec.folder / "video.mp4"
    writer: Any = None
    size: tuple[int, int] | None = None
    interval = 1.0 / _FPS
    # ★ THE THIRD FRAME SOURCE (2026-09-02): http MJPEG the BROWSER plays directly
    #   leaves no server-side frames at all — the first UI recording saved a CSV
    #   and no video. The recorder then opens its OWN reader. http-only by
    #   construction: devices and rtsp always flow through the proxy, and an
    #   http stream serves many readers, so this can never contend for a camera.
    own_cap: Any = None
    own_next_try = 0.0

    def _own_frame() -> Any:
        nonlocal own_cap, own_next_try
        if not rec.source.startswith(("http://", "https://")):
            return None
        if own_cap is None:
            if time.monotonic() < own_next_try:
                return None
            from app.services.live_stream_service import open_capture

            try:
                own_cap = open_capture(rec.source)
            except Exception:
                own_next_try = time.monotonic() + 3.0
                return None
        ok, fr = own_cap.read()
        if not ok or fr is None:
            own_cap.release()
            own_cap = None
            own_next_try = time.monotonic() + 3.0
            return None
        return fr

    try:
        while not rec._stop.is_set():
            tick = time.monotonic()
            jpg = _current_jpeg(rec.source)
            if jpg is not None:
                # Server-side frames exist (a run, or the proxy) — prefer them,
                # and let go of any own reader they made redundant.
                if own_cap is not None:
                    own_cap.release()
                    own_cap = None
                frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
            else:
                frame = _own_frame()
            if frame is not None:
                if writer is None:
                    size = (frame.shape[1], frame.shape[0])
                    # ★ H.264 from the first frame — see _H264Writer. The old
                    #   mp4v writer remains the fallback, so a machine whose
                    #   ffmpeg will not start still records something.
                    try:
                        writer = _H264Writer(video_path, size, _FPS)
                        rec.video_codec = "h264"
                    except Exception as exc:  # recording must not die for a codec
                        log.warning("recording.h264_unavailable", error=str(exc))
                        writer = cv2.VideoWriter(
                            str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), _FPS, size
                        )
                        rec.video_codec = "mp4v"
                if (frame.shape[1], frame.shape[0]) != size:
                    frame = cv2.resize(frame, size)
                writer.write(frame)
                rec.frames += 1
            delay = interval - (time.monotonic() - tick)
            if delay > 0:
                rec._stop.wait(delay)
        if own_cap is not None:
            own_cap.release()
            own_cap = None
        _finalize(rec, writer, video_path)
    except Exception as exc:
        rec.status = "failed"
        rec.error = f"{type(exc).__name__}: {exc}"
        log.warning("recording.failed", error=rec.error)
    finally:
        rec._done.set()


def start_recording(source: str, camera_name: str, settings: Settings) -> Recording:
    """Start recording ``source`` — idempotent: an active recording is returned."""
    src = source.strip()
    if src == "":
        raise RecordingError("a source is required.")
    with _LOCK:
        for rec in _RECORDINGS.values():
            if rec.source == src and rec.status == "recording":
                return rec
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        folder = recordings_root(settings) / f"{_slug(camera_name or src)}-{stamp}"
        folder.mkdir(parents=True, exist_ok=True)
        rec = Recording(
            recording_id=uuid.uuid4().hex[:12],
            source=src,
            camera_name=camera_name or src,
            folder=folder,
            settings=settings,
        )
        _RECORDINGS[rec.recording_id] = rec
    threading.Thread(
        target=_record, args=(rec,), name=f"record-{rec.recording_id}", daemon=True
    ).start()
    log.info("recording.started", folder=str(rec.folder), source=src)
    return rec


def get_recording(recording_id: str) -> Recording | None:
    """The recording, or None — the router turns None into a 404."""
    with _LOCK:
        return _RECORDINGS.get(recording_id)


def recording_for_source(source: str) -> Recording | None:
    """The ACTIVE recording of ``source`` — how a re-entered page finds its state."""
    with _LOCK:
        for rec in _RECORDINGS.values():
            if rec.source == source and rec.status == "recording":
                return rec
    return None


def stop_recording(recording_id: str, wait_s: float = 10.0) -> Recording:
    """Stop and FINALIZE — returns only once video + CSV + meta are on disk."""
    rec = get_recording(recording_id)
    if rec is None:
        raise RecordingError("no such recording.")
    rec._stop.set()
    rec._done.wait(wait_s)
    return rec


# ── the library ─────────────────────────────────────────────────────────────────


def _entry(folder: Path) -> dict[str, Any] | None:
    """One library entry from a folder — None when it is not a recording."""
    meta_path = folder / "meta.json"
    if not folder.is_dir() or not meta_path.is_file():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    video = folder / "video.mp4"
    # ★ A WHITELIST, not **meta: the wire schema forbids extras, and meta.json
    #   is user-editable disk content — only the declared fields travel.
    return {
        "folder": folder.name,
        "path": str(folder),
        "camera_name": str(meta.get("camera_name") or ""),
        "source": str(meta.get("source") or ""),
        "started_at": str(meta.get("started_at") or ""),
        "ended_at": meta.get("ended_at"),
        "duration_s": float(meta.get("duration_s") or 0.0),
        "frames": int(meta.get("frames") or 0),
        "marks": int(meta.get("marks") or 0),
        "video_bytes": video.stat().st_size if video.is_file() else 0,
        "has_video": video.is_file(),
        "has_csv": (folder / "detections.csv").is_file(),
        "has_map": (folder / SATELLITE).is_file(),
        "playable": (folder / PLAYABLE).is_file(),
        "trimmed_from": (str(meta["trimmed_from"]) if meta.get("trimmed_from") else None),
    }


def library_entries(settings: Settings) -> list[dict[str, Any]]:
    """Every saved recording folder, newest first — what the library page shows."""
    root = recordings_root(settings)
    entries = [e for e in (_entry(folder) for folder in root.iterdir()) if e is not None]
    entries.sort(key=lambda e: str(e.get("started_at") or ""), reverse=True)
    return entries


def _safe_child(root: Path, folder: str) -> Path:
    """``root/folder`` — refusing separators and traversal, never resolving them."""
    if folder in ("", ".", "..") or "/" in folder or "\\" in folder:
        raise RecordingError("no such recording folder.")
    child = root / folder
    if not child.is_dir():
        raise RecordingError("no such recording folder.")
    return child


def library_file(settings: Settings, folder: str, file: str) -> Path:
    """A downloadable file inside one library folder — video, CSV, meta, or the playable rendition."""
    if file not in (
        "video.mp4",
        "detections.csv",
        "meta.json",
        PLAYABLE,
        POSTER,
        SATELLITE,
        WORLDFILE,
        SAT_SIDECAR,
        MARKS,
    ):
        raise RecordingError("no such file in a recording.")
    path = _safe_child(recordings_root(settings), folder) / file
    if not path.is_file():
        raise RecordingError("no such file in a recording.")
    return path


def delete_library_entry(settings: Settings, folder: str) -> None:
    """Remove one recording folder — the library's own delete, nothing else's."""
    import shutil

    child = _safe_child(recordings_root(settings), folder)
    shutil.rmtree(child)
    log.info("recording.deleted", folder=folder)


# ── watching a recording in the app (2026-09-07) ─────────────────────────────

#: The browser-playable rendition beside the original. The recorder writes
#: MPEG-4 Part 2 (OpenCV's ``mp4v``) — nothing a browser decodes — so the first
#: request to watch a recording derives this H.264 file once, with the bundled
#: ffmpeg, and it stays in the folder. ``video.mp4`` remains the download.
PLAYABLE = "preview.mp4"

#: The recording's first frame as a JPEG — the library card's picture. Derived on
#: the first ask with OpenCV (the recorder's own container reads fine), ≤ 640 px wide.
POSTER = "poster.jpg"

_TRANSCODE_LOCK = threading.Lock()


def _ffmpeg_exe() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def _transcode(
    src: Path, dst: Path, *, start_s: float | None = None, end_s: float | None = None
) -> None:
    """``src`` → H.264 ``dst``, optionally only the window — only a finished file lands."""
    import subprocess

    tmp = dst.with_name(f".{dst.stem}.part.mp4")
    cmd = [_ffmpeg_exe(), "-y", "-loglevel", "error"]
    # ★ ``-ss`` BEFORE ``-i`` seeks fast to the keyframe before the start and, since
    #   the stream is re-encoded, decodes forward to the exact second — an accurate
    #   cut without transcoding what precedes it.
    if start_s is not None and start_s > 0:
        cmd += ["-ss", f"{start_s:.3f}"]
    cmd += ["-i", str(src)]
    if end_s is not None:
        cmd += ["-t", f"{max(0.0, end_s - (start_s or 0.0)):.3f}"]
    cmd += [
        "-an",
        # Even dimensions on both axes: H.264 4:2:0 refuses an odd width or height.
        "-vf",
        "scale='trunc(min(1920,iw)/2)*2':-2",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(tmp),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not tmp.is_file():
        tmp.unlink(missing_ok=True)
        tail = " | ".join(proc.stderr.strip().splitlines()[-3:]) or "no output"
        raise RecordingError(f"ffmpeg could not write the video: {tail}")
    tmp.replace(dst)


def _meta_codec(child: Path) -> str | None:
    """What ``video.mp4`` in this folder holds, per its meta.json — or None."""
    try:
        meta = json.loads((child / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    codec = meta.get("video_codec")
    return str(codec) if codec else None


def _meta_of(child: Path) -> dict[str, Any]:
    try:
        meta = json.loads((child / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RecordingError("this recording has no readable meta.json.") from exc
    return meta if isinstance(meta, dict) else {}


def _parse_utc(text: Any) -> datetime | None:
    """An ISO-8601 instant (``Z`` or offset, with or without fractions) — or None."""
    if not text:
        return None
    try:
        when = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo is not None else when.replace(tzinfo=UTC)


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _float(text: Any) -> float | None:
    try:
        return float(text) if text not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _int(text: Any) -> int | None:
    value = _float(text)
    return int(value) if value is not None else None


def _bool(text: Any) -> bool | None:
    if text in (None, ""):
        return None
    return str(text).strip().lower() in ("1", "true", "yes")


def ensure_preview(settings: Settings, folder: str) -> Path:
    """The playable rendition of a recording's video — derived on the first ask.

    ★ A RECORDING MADE SINCE 2026-09-11 IS ALREADY PLAYABLE: it is H.264 straight
    from the frames, so there is nothing to derive and nothing to lose to a second
    encode. Only the older mp4v files still take the transcode — and they say so
    in their own meta.json, so the answer never depends on guessing from bytes.
    """
    child = _safe_child(recordings_root(settings), folder)
    src = child / "video.mp4"
    if src.is_file() and _meta_codec(child) == "h264":
        return src
    dst = child / PLAYABLE
    if dst.is_file():
        return dst
    if not src.is_file():
        raise RecordingError("this recording has no video.")
    # One transcode at a time: two viewers asking at once must not both encode.
    with _TRANSCODE_LOCK:
        if not dst.is_file():
            _transcode(src, dst)
            log.info("recording.preview_ready", folder=folder)
    return dst


def ensure_poster(settings: Settings, folder: str) -> Path:
    """The recording's first frame as ``poster.jpg`` — derived on the first ask."""
    import cv2

    child = _safe_child(recordings_root(settings), folder)
    dst = child / POSTER
    if dst.is_file():
        return dst
    src = child / "video.mp4"
    if not src.is_file():
        raise RecordingError("this recording has no video.")
    cap = cv2.VideoCapture(str(src))
    try:
        ok, frame = cap.read()
    finally:
        cap.release()
    if not ok or frame is None:
        raise RecordingError("the video's first frame could not be read.")
    height, width = frame.shape[:2]
    if width > 640:
        frame = cv2.resize(frame, (640, max(1, round(height * 640 / width))))
    ok, jpg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
    if not ok:
        raise RecordingError("the poster could not be encoded.")
    tmp = dst.with_name(".poster.part.jpg")
    tmp.write_bytes(jpg.tobytes())
    tmp.replace(dst)
    return dst


def recording_table(settings: Settings, folder: str) -> dict[str, Any]:
    """The attribute table as rows on the recording's clock — ``t`` = seconds since start."""
    child = _safe_child(recordings_root(settings), folder)
    meta = _meta_of(child)
    started = _parse_utc(meta.get("started_at"))
    columns: list[str] = []
    rows: list[dict[str, Any]] = []
    csv_path = child / "detections.csv"
    if csv_path.is_file():
        reader = csv.DictReader(io.StringIO(csv_path.read_text(encoding="utf-8")))
        columns = list(reader.fieldnames or [])
        for index, row in enumerate(reader):
            when = _parse_utc(row.get("time_utc"))
            offset = (
                round(max(0.0, (when - started).total_seconds()), 2)
                if when is not None and started is not None
                else None
            )
            rows.append(
                {
                    "index": index,
                    "t": offset,
                    "time_utc": str(row.get("time_utc") or ""),
                    "class_name": str(row.get("class") or ""),
                    "score": _float(row.get("score")),
                    "lat": _float(row.get("lat")),
                    "lon": _float(row.get("lon")),
                    "frame": _int(row.get("frame")),
                    "track_id": _int(row.get("track_id")),
                    "predicted": _bool(row.get("predicted")),
                    "drift": str(row.get("drift")) if row.get("drift") else None,
                    "drift_shift_m": _float(row.get("drift_shift_m")),
                    "centre_m": _float(row.get("centre_m")),
                    "mark_id": _int(row.get("mark_id") or row.get("detection_id")),
                }
            )
    # Chronological, rows without a time last — the player walks this order.
    rows.sort(key=lambda r: (r["t"] is None, r["t"] or 0.0, r["index"]))
    table = str(meta.get("table") or ("marks" if "lat" in columns else "detections"))
    return {
        "folder": child.name,
        "camera_name": str(meta.get("camera_name") or ""),
        "source": str(meta.get("source") or ""),
        "started_at": str(meta.get("started_at") or ""),
        "ended_at": meta.get("ended_at"),
        "duration_s": float(meta.get("duration_s") or 0.0),
        "table": table,
        "columns": columns,
        "rows": rows,
        "has_video": (child / "video.mp4").is_file(),
        "trimmed_from": (str(meta["trimmed_from"]) if meta.get("trimmed_from") else None),
    }


def _frame_count(video: Path) -> int:
    import cv2

    cap = cv2.VideoCapture(str(video))
    try:
        return max(0, int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0))
    finally:
        cap.release()


def trim_recording(settings: Settings, folder: str, start_s: float, end_s: float) -> dict[str, Any]:
    """Cut ``[start_s, end_s]`` of a recording into a NEW folder — the original is untouched.

    The new folder is a recording like any other: an H.264 ``video.mp4`` (which
    is also its own playable rendition), the window's rows of the attribute
    table with their absolute times kept, and a ``meta.json`` that names where
    it was cut from. Returns the new folder's library entry.
    """
    import os
    import shutil

    root = recordings_root(settings)
    child = _safe_child(root, folder)
    meta = _meta_of(child)
    src = child / "video.mp4"
    if not src.is_file():
        raise RecordingError("this recording has no video to trim.")
    start_s = max(0.0, float(start_s))
    end_s = float(end_s)
    duration = float(meta.get("duration_s") or 0.0)
    if duration > 0:
        end_s = min(end_s, duration)
    if end_s - start_s < 0.5:
        raise RecordingError("the trim needs at least half a second between its start and its end.")
    started = _parse_utc(meta.get("started_at")) or datetime.now(UTC)
    new_started = started + timedelta(seconds=start_s)
    new_ended = started + timedelta(seconds=end_s)
    base = f"{_slug(str(meta.get('camera_name') or folder))}-{new_started.strftime('%Y%m%d-%H%M%S')}-trim"
    new = root / base
    n = 2
    while new.exists():
        new = root / f"{base}-{n}"
        n += 1
    new.mkdir(parents=True)
    try:
        _transcode(src, new / "video.mp4", start_s=start_s, end_s=end_s)
        # The cut is H.264 already: it is its own playable rendition (a hard link
        # where the disk allows one, a copy otherwise).
        try:
            os.link(new / "video.mp4", new / PLAYABLE)
        except OSError:
            shutil.copyfile(new / "video.mp4", new / PLAYABLE)
        header: list[str] = []
        kept: list[dict[str, Any]] = []
        csv_path = child / "detections.csv"
        if csv_path.is_file():
            reader = csv.DictReader(io.StringIO(csv_path.read_text(encoding="utf-8")))
            header = list(reader.fieldnames or [])
            for row in reader:
                when = _parse_utc(row.get("time_utc"))
                if when is not None and new_started <= when <= new_ended:
                    kept.append(row)
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=header or _CSV_COLUMNS_NO_LUT, extrasaction="ignore")
        writer.writeheader()
        for row in kept:
            writer.writerow(row)
        (new / "detections.csv").write_text(buf.getvalue(), encoding="utf-8")
        new_meta = {
            **meta,
            "recording_id": uuid.uuid4().hex[:12],
            "started_at": _iso(new_started),
            "ended_at": _iso(new_ended),
            "duration_s": round(end_s - start_s, 1),
            "frames": _frame_count(new / "video.mp4"),
            "marks": len(kept),
            "video": "video.mp4",
            "csv": "detections.csv",
            "trimmed_from": folder,
            "trim_start_s": round(start_s, 2),
            "trim_end_s": round(end_s, 2),
        }
        (new / "meta.json").write_text(json.dumps(new_meta, indent=2), encoding="utf-8")
    except Exception:
        shutil.rmtree(new, ignore_errors=True)
        raise
    log.info("recording.trimmed", folder=folder, into=new.name, start_s=start_s, end_s=end_s)
    return _entry(new) or {}


# ── the satellite map (2026-09-12, owner ask) ────────────────────────────────────
#
# ★ WHY. A recording was the stream and the table; the ground it happened ON was
#   left behind in the app. An operator who keeps a scene wants the THREE together
#   — what the camera saw, where each detection landed, and the place itself — so
#   the folder now grows a satellite chip of the scene with the camera and every
#   placed mark drawn on it, a world file so the same PNG opens georeferenced in
#   QGIS, the marks as GeoJSON, and the provider's attribution beside the pixels.
#
# ★ BEST-EFFORT, ALWAYS. Imagery is a network call and a licence; a recording is
#   evidence already on disk. Nothing in here may fail a recording — every failure
#   is a log line and a folder without a map, never a lost video.

#: The scene on satellite imagery, the camera and the marks drawn on it.
SATELLITE = "satellite.png"
#: The ESRI world file beside it — the PNG opens georeferenced, no GeoTIFF needed.
WORLDFILE = "satellite.pgw"
#: Provider, attribution, terms. The licence obligation travels WITH the pixels.
SAT_SIDECAR = "satellite.txt"
#: The placed marks and the camera as GeoJSON — the map's own vector layer.
MARKS = "marks.geojson"

#: The stitched chip's longest side. Big enough to read a vehicle on the ground,
#: small enough that stopping a recording is not a tile-fetching expedition.
_MAP_MAX_PX = 1600
#: A scene collapses to a point when one mark landed (or none did and only the
#: camera is known). Give it this much ground anyway, so the map still says where.
_MAP_MIN_SPAN_M = 300.0
#: Breathing room around the marks, as a fraction of their own spread.
_MAP_PAD_FRACTION = 0.25
#: Web Mercator dies at the poles; clamp before asking for tiles.
_MERCATOR_LIMIT = 85.0511


def _scene_points(
    rows: list[dict[str, Any]], camera_name: str
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """The placed marks and the camera, in lon/lat — what the map must cover.

    A no-LUT table places nothing and has no camera columns; both come back empty
    and the caller writes no map. That is the honest answer, not a failure.
    """
    marks: list[dict[str, Any]] = []
    camera: dict[str, Any] | None = None
    for row in rows:
        lat, lon = _float(row.get("lat")), _float(row.get("lon"))
        if lat is not None and lon is not None:
            marks.append(
                {
                    "lon": lon,
                    "lat": lat,
                    "class": str(row.get("class") or ""),
                    "score": _float(row.get("score")),
                    "time_utc": str(row.get("time_utc") or ""),
                    "mark_id": row.get("mark_id"),
                    "track_id": row.get("track_id"),
                }
            )
        if camera is None:
            cam_lat, cam_lon = _float(row.get("cam_lat")), _float(row.get("cam_lon"))
            if cam_lat is not None and cam_lon is not None:
                camera = {
                    "lon": cam_lon,
                    "lat": cam_lat,
                    "name": str(row.get("camera") or camera_name),
                }
    return marks, camera


def _scene_bbox(marks: list[dict[str, Any]], camera: dict[str, Any] | None) -> Any:
    """The EPSG:4326 box to fetch — padded, never degenerate, never wrapped."""
    from gis.types import BBox

    points = [(m["lon"], m["lat"]) for m in marks]
    if camera is not None:
        points.append((camera["lon"], camera["lat"]))
    if not points:
        return None
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    west, east = min(lons), max(lons)
    south, north = min(lats), max(lats)
    mid_lat = (south + north) / 2.0
    per_deg_lat = 111_320.0
    per_deg_lon = max(1.0, 111_320.0 * math.cos(math.radians(mid_lat)))
    pad_lat = max((north - south) * _MAP_PAD_FRACTION, _MAP_MIN_SPAN_M / 2.0 / per_deg_lat)
    pad_lon = max((east - west) * _MAP_PAD_FRACTION, _MAP_MIN_SPAN_M / 2.0 / per_deg_lon)
    west, east = west - pad_lon, east + pad_lon
    south, north = south - pad_lat, north + pad_lat
    # ★ A scene that pads across the antimeridian, or sits past Mercator's edge,
    #   gets no map rather than a wrong one.
    if west < -180.0 or east > 180.0 or west >= east:
        return None
    south = max(south, -_MERCATOR_LIMIT)
    north = min(north, _MERCATOR_LIMIT)
    if south >= north:
        return None
    return BBox(west, south, east, north)


def _pick_zoom(bbox: Any) -> int:
    """The deepest zoom whose stitch stays inside ``_MAP_MAX_PX``."""
    from gis.tiles import lonlat_to_tile_fractional

    for z in range(19, 11, -1):
        x0, y0 = lonlat_to_tile_fractional(bbox.west, bbox.north, z)
        x1, y1 = lonlat_to_tile_fractional(bbox.east, bbox.south, z)
        if max(abs(x1 - x0), abs(y1 - y0)) * 256.0 <= _MAP_MAX_PX:
            return z
    return 12


def _draw_scene(
    image: Any, gt: Any, crs: str, marks: list[dict[str, Any]], camera: dict[str, Any] | None,
    caption: str,
) -> Any:
    """The chip with the camera, the marks and the attribution drawn on — BGR, for cv2.

    ★ Every mark gets a dark ring under its fill. Satellite imagery is every colour
      at once; a bare dot vanishes over a white roof and a black one both.
    """
    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    from gis.crs import lonlat_to_pixel  # noqa: PLC0415

    canvas = np.ascontiguousarray(image[:, :, ::-1])  # RGB in, BGR for cv2
    height, width = canvas.shape[:2]

    def at(lon: float, lat: float) -> tuple[int, int] | None:
        col, row = lonlat_to_pixel(gt, crs, lon, lat)
        if not (math.isfinite(col) and math.isfinite(row)):
            return None
        return int(round(col)), int(round(row))

    ink = (20, 20, 20)
    mark_fill = (0, 165, 255)  # amber
    cam_fill = (255, 220, 40)  # cyan

    for m in marks:
        p = at(m["lon"], m["lat"])
        if p is None or not (0 <= p[0] < width and 0 <= p[1] < height):
            continue
        cv2.circle(canvas, p, 6, ink, -1, cv2.LINE_AA)
        cv2.circle(canvas, p, 4, mark_fill, -1, cv2.LINE_AA)

    if camera is not None:
        p = at(camera["lon"], camera["lat"])
        if p is not None and 0 <= p[0] < width and 0 <= p[1] < height:
            cv2.circle(canvas, p, 11, ink, 3, cv2.LINE_AA)
            cv2.circle(canvas, p, 11, cam_fill, 2, cv2.LINE_AA)
            cv2.drawMarker(canvas, p, ink, cv2.MARKER_CROSS, 22, 3, cv2.LINE_AA)
            cv2.drawMarker(canvas, p, cam_fill, cv2.MARKER_CROSS, 20, 1, cv2.LINE_AA)

    # ★ The caption carries the attribution. The PNG travels on its own once it is
    #   downloaded, and the licence goes with it or the obligation is not met.
    if caption:
        font, scale, thick = cv2.FONT_HERSHEY_SIMPLEX, 0.42, 1
        (tw, th), base = cv2.getTextSize(caption, font, scale, thick)
        bar = th + base + 10
        strip = canvas[height - bar :, :].astype(np.float32) * 0.35
        canvas[height - bar :, :] = strip.astype(np.uint8)
        cv2.putText(
            canvas, caption, (8, height - base - 5), font, scale, (245, 245, 245), thick, cv2.LINE_AA
        )
    return canvas


def _write_worldfile(path: Path, gt: Any) -> None:
    """The six ESRI lines, from the GDAL 6-tuple.

    The geotransform's origin is the OUTER edge of the top-left pixel; a world
    file names its CENTRE, which is the half-pixel added to lines 5 and 6.
    """
    lines = (
        gt[1],  # A — pixel width
        gt[4],  # D — column rotation
        gt[2],  # B — row rotation
        gt[5],  # E — pixel height (negative, north-up)
        gt[0] + gt[1] * 0.5 + gt[2] * 0.5,  # C — x of the top-left pixel's centre
        gt[3] + gt[4] * 0.5 + gt[5] * 0.5,  # F — y of the top-left pixel's centre
    )
    path.write_text("\n".join(f"{v:.12g}" for v in lines) + "\n", encoding="utf-8")


def _marks_geojson(marks: list[dict[str, Any]], camera: dict[str, Any] | None) -> dict[str, Any]:
    """The scene as vectors — WGS84, the one CRS a GeoJSON is allowed to be in."""
    features: list[dict[str, Any]] = []
    if camera is not None:
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [camera["lon"], camera["lat"]]},
                "properties": {"role": "camera", "name": camera["name"]},
            }
        )
    for m in marks:
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [m["lon"], m["lat"]]},
                "properties": {
                    "role": "mark",
                    "class": m["class"],
                    "score": m["score"],
                    "time_utc": m["time_utc"],
                    "mark_id": m["mark_id"],
                    "track_id": m["track_id"],
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def write_satellite_map(
    settings: Settings,
    folder: Path,
    rows: list[dict[str, Any]],
    camera_name: str,
    *,
    window: str = "",
) -> dict[str, Any] | None:
    """Stitch the scene's satellite chip into ``folder``. Never raises.

    Returns what ``meta.json`` should record about the map, or None when there was
    no scene to draw (a no-LUT run places nothing) or imagery was out of reach.
    """
    try:
        marks, camera = _scene_points(rows, camera_name)
        bbox = _scene_bbox(marks, camera)
        if bbox is None:
            log.info("recording.map_skipped", folder=folder.name, reason="nothing placed")
            return None

        from app.services.imagery_service import ImageryService  # noqa: PLC0415

        zoom = _pick_zoom(bbox)
        chip = ImageryService(settings).get_static_chip(bbox, zoom)

        attribution = (chip.attribution or "").strip()
        caption = " · ".join(p for p in (camera_name, window, attribution) if p)
        canvas = _draw_scene(chip.image, chip.geotransform, chip.crs, marks, camera, caption)

        import cv2  # noqa: PLC0415

        if not cv2.imwrite(str(folder / SATELLITE), canvas):
            raise RecordingError("the satellite chip could not be encoded.")
        _write_worldfile(folder / WORLDFILE, chip.geotransform)
        (folder / MARKS).write_text(
            json.dumps(_marks_geojson(marks, camera), indent=2), encoding="utf-8"
        )
        (folder / SAT_SIDECAR).write_text(
            "\n".join(
                (
                    f"provider:      {chip.provider_name}",
                    f"attribution:   {attribution}",
                    f"terms:         {chip.terms_url}",
                    f"captured_at:   {chip.captured_at.isoformat() if chip.captured_at else 'unknown'}",
                    f"zoom:          {chip.zoom}",
                    f"crs:           {chip.crs}   (the world file {WORLDFILE} is in these units)",
                    f"gsd_m:         {chip.gsd_m:.3f}   true ground metres per pixel at centre",
                    f"georef_ce90_m: {chip.georef_ce90_m}",
                    f"bbox_4326:     {bbox.west:.6f},{bbox.south:.6f},{bbox.east:.6f},{bbox.north:.6f}",
                    f"marks:         {len(marks)}",
                    "",
                    "The imagery above is the provider's, under the terms named. Keep this",
                    "file beside the PNG: it is the attribution the licence requires.",
                    "",
                )
            ),
            encoding="utf-8",
        )
        log.info(
            "recording.map_saved", folder=folder.name, zoom=chip.zoom,
            provider=chip.provider_name, marks=len(marks),
        )
        return {
            "image": SATELLITE,
            "worldfile": WORLDFILE,
            "marks": MARKS,
            "provider": chip.provider_name,
            "attribution": attribution,
            "zoom": chip.zoom,
            "crs": chip.crs,
            "bbox_4326": [bbox.west, bbox.south, bbox.east, bbox.north],
            "mark_count": len(marks),
        }
    except Exception as exc:  # imagery is a courtesy; the recording is the evidence
        log.warning("recording.map_unavailable", folder=folder.name, error=f"{type(exc).__name__}: {exc}")
        return None


# ── the download package (2026-09-12, owner ask) ─────────────────────────────────
#
# ★ ONE BUTTON, ONE FOLDER. The library used to offer the video and the CSV as two
#   separate downloads and the map not at all, so keeping a scene meant three trips
#   and a folder the operator had to build themselves. The package is that folder,
#   made here: one directory per session, and inside it the video, the map and the
#   table each in their own, with meta.json and a README naming what everything is.

#: What goes in which lane. Files absent from a folder are simply skipped — an
#: older recording has no map, a data-only one no video, and both still package.
_PACKAGE_LANES: tuple[tuple[str, str], ...] = (
    ("video", "video.mp4"),
    ("video", POSTER),
    ("map", SATELLITE),
    ("map", WORLDFILE),
    ("map", SAT_SIDECAR),
    ("map", MARKS),
    ("table", "detections.csv"),
)

_README = """This folder is one recorded session from LandExplorer.

  video/    video.mp4      the stream as it was watched
            poster.jpg     its first frame
  map/      satellite.png  the scene, with the camera and every placed mark on it
            satellite.pgw  world file — drop the PNG on a GIS and it lands itself
            satellite.txt  the imagery provider, its attribution and its terms
            marks.geojson  the placed detections as points (WGS84)
  table/    detections.csv the run's attribute table for this window
  meta.json                camera, source, window, counts

The CSV, the GeoJSON and the map are the same detections three ways. meta.json
says which table was written: "marks" when the run had a lookup table and could
place them on the ground, "detections" when it could not and the table is honest
about carrying only what was seen and when.
"""


def _rows_from_csv(child: Path) -> list[dict[str, Any]]:
    """A finished recording's own table, back off disk — for a map built late."""
    path = child / "detections.csv"
    if not path.is_file():
        return []
    try:
        with path.open(encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))
    except (OSError, ValueError):
        return []


def ensure_satellite_map(settings: Settings, folder: str) -> bool:
    """The folder's map, stitching it now if it was never made. True when one exists.

    ★ Recordings made before 2026-09-12 have no map, and so does one stopped while
      imagery was unreachable. Packaging asks for the map through here so those
      folders complete themselves on the first download instead of staying poorer
      than the ones recorded after.
    """
    child = _safe_child(recordings_root(settings), folder)
    if (child / SATELLITE).is_file():
        return True
    meta = _meta_of(child)
    if meta.get("map_attempted"):  # a scene with nothing placed: do not re-fetch
        return False
    rows = _rows_from_csv(child)
    window = f"{meta.get('started_at', '')} — {meta.get('ended_at', '') or ''}".strip(" —")
    built = write_satellite_map(
        settings, child, rows, str(meta.get("camera_name") or ""), window=window
    )
    meta["map"] = built
    meta["map_attempted"] = True
    with contextlib.suppress(OSError):
        (child / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return built is not None


def package_path(settings: Settings, folder: str) -> tuple[Path, str]:
    """Build the session's package as a zip on disk; returns ``(path, filename)``.

    The caller owns the file and must delete it — the router does that in a
    background task once the response has been sent.
    """
    import tempfile  # noqa: PLC0415
    import zipfile  # noqa: PLC0415

    child = _safe_child(recordings_root(settings), folder)
    with contextlib.suppress(Exception):  # a missing map must not cost the package
        ensure_satellite_map(settings, folder)

    handle, tmp = tempfile.mkstemp(prefix="recording-", suffix=".zip")
    os.close(handle)
    path = Path(tmp)
    # ★ STORED for the video, DEFLATED for the text. An mp4 is already compressed:
    #   deflating it burns CPU over a long file to save nothing.
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for lane, name in _PACKAGE_LANES:
            member = child / name
            if not member.is_file():
                continue
            zf.write(
                member,
                f"{folder}/{lane}/{name}",
                compress_type=(
                    zipfile.ZIP_STORED if name.endswith((".mp4", ".jpg")) else zipfile.ZIP_DEFLATED
                ),
            )
        if (child / "meta.json").is_file():
            zf.write(child / "meta.json", f"{folder}/meta.json")
        zf.writestr(f"{folder}/README.txt", _README)
    return path, f"{folder}.zip"
