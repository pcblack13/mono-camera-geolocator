"""``live_stream_service`` — one frame from a network camera, into the capture library.

★ THE INTEGRATION IS THE CAPTURE LIBRARY. A live source (a Raspberry Pi running an
MJPEG streamer, an IP camera, an RTSP encoder) is not a new kind of entity in this
app — it is just another place a FRAME can come from. A captured frame is written
into the same capture-export folder video captures use, so it immediately appears
in the library and imports into any project through the existing "From library"
flow: setup page, GCPs, LUT — the whole pipeline, unchanged.

★ THE SERVER does the grabbing, not the browser. A browser can *display* an MJPEG
stream in an ``<img>``, but cannot save a frame from it cross-origin (canvas
taint), and cannot read RTSP at all. OpenCV's FFMPEG backend reads both.

★ SSRF posture: this is a LAN product feature (the API binds to 127.0.0.1 and the
operator is the only caller), but the URL scheme is still allow-listed — an
attacker-shaped URL (``file://``, ``gopher://``…) is refused by type, not by luck.

Framework-free: no FastAPI imports. The router owns HTTP concerns.
"""

from __future__ import annotations

import logging
import re
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

log = logging.getLogger(__name__)

__all__ = [
    "LiveCaptureError",
    "CapturedFrame",
    "LiveDevice",
    "SourceMeta",
    "is_device_source",
    "list_devices",
    "uncompressed_warning",
    "mjpeg_stream",
    "open_capture",
    "validate_stream_url",
    "capture_frame",
]

#: http(s) covers MJPEG/HTTP snapshot endpoints; rtsp covers IP cameras and
#: ffmpeg/GStreamer pipelines. Nothing else is a camera.
_ALLOWED_SCHEMES = frozenset({"http", "https", "rtsp"})

#: Give a LAN camera a real chance to answer, but never hang a request forever.
_TIMEOUT_MS = 8_000

#: What we ask a local device to run at once it is on its MJPEG pin.
_DEVICE_TARGET_FPS = 30

#: ★ THE RE-STREAM'S CEILING. The loop paces itself to the requested fps; this is the
#: highest it will honour. Raised from 30 to 60 (1.2.6) so a 60 fps capture card is
#: not throttled to half its rate by a constant. The real limit in practice is JPEG
#: encoding cost, which the pacing loop absorbs naturally — it never sleeps negative.
_MAX_RESTREAM_FPS = 60.0

_SAFE = re.compile(r"[^A-Za-z0-9_-]+")


class LiveCaptureError(ValueError):
    """A capture that cannot proceed or failed — the message names the reason."""


@dataclass(frozen=True)
class CapturedFrame:
    filename: str
    path: Path
    width: int
    height: int
    size_bytes: int


@dataclass(frozen=True)
class LiveDevice:
    """One local capture device — a USB/USB-C camera or an HDMI capture card.

    ★ Both present the same way to the OS: a V4L2 node (``/dev/videoN``) on Linux,
    a DirectShow device (an index) on Windows. There is no separate "HDMI" kind —
    an HDMI source arrives through a capture card, which IS a camera to the OS.
    """

    #: ``/dev/video0`` on Linux; ``"0"`` (a DirectShow index) on Windows.
    id: str
    label: str


#: A LOCAL device source: ``/dev/videoN`` (Linux) or a bare index (Windows).
#: ★ Anchored and digit-only — this is the entire set of strings we will ever hand
#: to cv2 as a device, so an arbitrary path can never ride in through this lane.
_DEVICE_ID_RE = re.compile(r"^(?:/dev/video(\d+)|(\d+))$")

#: Windows device probing stops here — DirectShow enumeration by index is the only
#: portable way without extra deps, and absent indices cost real time to probe.
_MAX_WINDOWS_DEVICE_INDEX = 8

#: ★ The last JPEG each ACTIVE stream produced, by source id. This is what lets
#: "Capture frame" work while the same device is being watched: a V4L2/DirectShow
#: device cannot be opened twice, so the capture is served from the live stream's
#: own most recent frame instead of a second open. Entries are removed when the
#: stream ends; the dict never outgrows the number of concurrently-open streams.
_LAST_FRAME: dict[str, bytes] = {}
_LAST_FRAME_T: dict[str, float] = {}

#: ★ DEVICE HANDOVER (2026-09-02). A V4L2/DirectShow device streams for ONE owner;
#: the preview proxy and a detection run must HAND it OVER, not race for it. Every
#: live proxy of a device source registers a stop-event here; ``preempt_device``
#: sets them and waits until the proxies have actually RELEASED the capture. Field
#: report: "when I turn on the detection the app loses the stream" — the browser's
#: img-abort was the only release signal, and it arrives whenever it arrives.
_PROXY_STOPS: dict[str, set[threading.Event]] = {}
_PROXY_LOCK = threading.Lock()

#: How long a fresh open retries while the previous owner lets go. Covers the run
#: thread's release (it happens after its blocking ``cap.read()`` returns) and the
#: proxy's (one loop iteration).
_DEVICE_OPEN_RETRY_S = 5.0


def preempt_device(src: str, wait_s: float = 2.0) -> None:
    """Ask every live proxy re-stream of this DEVICE to release it — and wait.

    A no-op for network sources (an http/rtsp stream serves many readers). The
    wait ends early the moment the last proxy has released; the cap keeps a stuck
    proxy from blocking a start forever.
    """
    if not is_device_source(src):
        return
    with _PROXY_LOCK:
        events = list(_PROXY_STOPS.get(src, ()))
    if not events:
        return
    for e in events:
        e.set()
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        with _PROXY_LOCK:
            if not _PROXY_STOPS.get(src):
                return
        time.sleep(0.05)


def latest_preview_frame(src: str, max_age_s: float = 5.0):  # noqa: ANN201 — ndarray; cv2 stays service-local
    """The re-stream's freshest frame for ``src``, decoded to BGR — or None.

    ★ FOR THE DRIFT MONITOR: while a browser watches this source through
    ``/live/stream``, the SERVER holds the device — a second opener would lose
    the fight it cannot win. This borrows the panel's own picture instead. It is
    a JPEG round-trip (quality ~80), which normalised cross-correlation shrugs
    at; staleness is refused so a stalled source never poses as a fresh look.
    """
    data = _LAST_FRAME.get(src)
    stamped = _LAST_FRAME_T.get(src)
    if data is None or stamped is None or time.monotonic() - stamped > max_age_s:
        return None
    import cv2  # noqa: PLC0415 — heavy import, service-local by design
    import numpy as np  # noqa: PLC0415

    frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    return frame if frame is not None and frame.size > 0 else None


def is_device_source(src: str) -> bool:
    """True when ``src`` names a local capture device rather than a network URL."""
    return bool(_DEVICE_ID_RE.match((src or "").strip()))


def validate_stream_url(url: str) -> str:
    """Return the URL if it names a camera-shaped source; raise otherwise.

    Raises:
        LiveCaptureError: Empty URL, unsupported scheme, or no host.
    """
    parsed = urlparse((url or "").strip())
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise LiveCaptureError(
            "the stream URL must start with http://, https:// or rtsp:// — "
            f"got {parsed.scheme or 'no scheme'!r}."
        )
    if not parsed.netloc:
        raise LiveCaptureError("the stream URL has no host (e.g. http://raspberrypi.local:8080/…).")
    return parsed.geturl()


def _frame_filename(name: str | None, url: str, now: datetime) -> str:
    """``live_<source>_<UTC stamp>.jpg`` — sortable, collision-free enough, honest origin."""
    fallback = urlparse(url).hostname or (Path(url).stem if is_device_source(url) else None)
    source = _SAFE.sub("_", (name or fallback or "camera")).strip("_") or "camera"
    return f"live_{source[:40]}_{now.strftime('%Y%m%d_%H%M%S')}.jpg"


# ── local devices: HDMI capture cards + USB/USB-C cameras ────────────────────────


def list_devices() -> list[LiveDevice]:
    """Enumerate local capture devices. Blocking (device probes) — run in a thread.

    Linux: walk ``/sys/class/video4linux`` for names, then PROBE each node with a
    V4L2 open — a modern UVC device exposes a METADATA node right beside its
    capture node (``video1`` next to ``video0``) and listing those as cameras
    would offer sources that can never produce a frame. A node that fails the
    probe (metadata, or busy in another program) is left out.

    Windows: DirectShow has no portable name enumeration without extra
    dependencies, so indices 0..7 are probed and labeled generically.
    """
    import cv2  # noqa: PLC0415 — heavy import, service-local by design

    devices: list[LiveDevice] = []
    if sys.platform.startswith("linux"):
        base = Path("/sys/class/video4linux")
        nodes = (
            sorted(base.iterdir(), key=lambda p: p.name)
            if base.is_dir()
            else sorted(Path("/dev").glob("video*"), key=lambda p: p.name)
        )
        for node in nodes:
            m = re.fullmatch(r"video(\d+)", node.name)
            if m is None:
                continue
            dev_path = f"/dev/{node.name}"
            name_file = node / "name"
            try:
                label = name_file.read_text().strip() if name_file.exists() else node.name
            except OSError:
                label = node.name
            cap = cv2.VideoCapture(dev_path, cv2.CAP_V4L2)
            ok = cap.isOpened()
            cap.release()
            if ok:
                devices.append(LiveDevice(id=dev_path, label=label))
    elif sys.platform == "win32":
        for index in range(_MAX_WINDOWS_DEVICE_INDEX):
            cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
            ok = cap.isOpened()
            cap.release()
            if ok:
                devices.append(LiveDevice(id=str(index), label=f"Capture device {index}"))
    return devices


@dataclass(frozen=True)
class SourceMeta:
    """What the OPENED source says about itself — honest values or None, never guesses."""

    #: Normalised codec label ("H264", "MJPEG", "YUYV"…), or None when the backend
    #: reports no usable FOURCC (many V4L2/DirectShow paths simply don't).
    codec: str | None
    width: int | None
    height: int | None
    fps: float | None
    #: ★ Set when the device settled on an UNCOMPRESSED format — an explanation for
    #: the operator, never a refusal. See :func:`uncompressed_warning`. ASCII only:
    #: it travels as an HTTP header.
    uncompressed_note: str | None = None


#: ★ UNCOMPRESSED PIXEL FORMATS — REFUSED FOR STREAMING (1.2.6).
#:
#: A UVC camera or capture card offers several "pins": raw (YUYV and friends) and,
#: nearly always, MJPEG. Raw is the default on many V4L2 stacks and it is the reason
#: a 1080p device crawls: uncompressed 1080p is ~50 MB/s, far past USB 2.0's ~35 MB/s
#: ceiling, so the device drops to a few frames per second to fit. The SAME camera on
#: its MJPEG pin runs at full rate over the same cable.
#:
#: So raw is not merely slower — for this app's purpose it is broken, and accepting it
#: silently produced a stream nobody could explain. We ask for MJPEG, verify we got
#: it, and refuse the source by name when we did not.
_RAW_FOURCCS = frozenset(
    {
        "YUYV", "YUY2", "UYVY", "VYUY", "YVYU",  # packed YUV 4:2:2
        "NV12", "NV21", "YV12", "I420", "IYUV",  # planar YUV 4:2:0
        "RGB3", "BGR3", "RGBA", "BGRA", "RGB24", "BGR24",  # packed RGB
        "GREY", "Y800", "Y8  ", "Y16 ",  # greyscale
    }
)

#: FOURCC → the label a human recognises. Unknown codes pass through uppercased.
_FOURCC_LABELS = {
    "MJPG": "MJPEG",
    "AVC1": "H264",
    "H264": "H264",
    "X264": "H264",
    "HEV1": "HEVC",
    "HVC1": "HEVC",
    "HEVC": "HEVC",
    "VP80": "VP8",
    "VP90": "VP9",
    "AV01": "AV1",
}


def _raw_fourcc(cap: Any) -> str | None:  # noqa: ANN401 — cv2.VideoCapture, service-local
    """The capture's CURRENT FOURCC as four raw characters, or None if unreadable.

    ★ Deliberately NOT the pretty label: the raw code is what we compare against
    :data:`_RAW_FOURCCS`, and the mapping to "MJPEG"/"H264" is a display concern.
    """
    import cv2  # noqa: PLC0415 — heavy import, service-local by design

    try:
        value = int(float(cap.get(cv2.CAP_PROP_FOURCC)))
    except Exception:  # noqa: BLE001 — a metadata read must never kill an open
        return None
    if value <= 0:
        return None
    try:
        text = bytes([(value >> shift) & 0xFF for shift in (0, 8, 16, 24)]).decode("ascii")
    except UnicodeDecodeError:
        return None
    return text.upper() if text.isprintable() else None


def uncompressed_warning(cap: Any) -> str | None:  # noqa: ANN401
    """The warning for a device still on an UNCOMPRESSED pin, or None if it is fine.

    ★ WE ASK FOR MJPEG; WE NEVER REFUSE WHAT WE GET (1.2.6). An earlier build made
      this a hard refusal, and it blocked a working greyscale camera — which was the
      wrong trade twice over. First, the problem raw formats cause is a DATA RATE,
      not a format: uncompressed 1080p is ~50 MB/s and does not fit in USB 2.0, so
      the device throttles itself to a few fps — but 640×480 greyscale is ~9 MB/s and
      runs at full rate. Banning the format punishes cameras that were never slow.
      Second, a refusal turns a usable-but-slow stream into no stream at all, which
      is strictly worse for the surveyor holding the only camera they have.

    ★ So the honest design is: request MJPEG, report what actually won, and let the
      operator see a slow device rather than be locked out of it. The stats panel's
      Encoding row already names the format; this sentence explains what it means.

    ★ "Unknown" is not "raw". Plenty of working backends — DirectShow especially —
      report no FOURCC at all, and warning on silence would cry wolf on every
      Windows camera.
    """
    fourcc = _raw_fourcc(cap)
    if fourcc is None or fourcc.strip() not in _RAW_FOURCCS:
        return None
    label = _FOURCC_LABELS.get(fourcc.strip(), fourcc.strip())
    return (
        f"This device is streaming uncompressed {label} - it did not switch to MJPEG. "
        "That is fine at small frame sizes, but a large uncompressed frame does not "
        "fit in USB 2.0 bandwidth and the camera will drop to a few frames per second. "
        "If the video is slow, use a USB 3 port or a device that offers MJPEG."
    )


def _source_meta(cap: Any) -> SourceMeta:  # noqa: ANN401 — cv2.VideoCapture, service-local
    """Read codec/size/fps off an opened capture. Never raises; absent = None."""
    import cv2  # noqa: PLC0415 — heavy import, service-local by design

    def _num(prop: int) -> float | None:
        try:
            value = float(cap.get(prop))
        except Exception:  # noqa: BLE001 — a metadata read must never kill a stream
            return None
        return value if value > 0 else None

    codec: str | None = None
    raw = _num(cv2.CAP_PROP_FOURCC)
    if raw is not None:
        chars = bytes([(int(raw) >> shift) & 0xFF for shift in (0, 8, 16, 24)])
        try:
            text = chars.decode("ascii").strip("\x00 ").strip()
        except UnicodeDecodeError:
            text = ""
        if len(text) >= 2 and text.isprintable():
            codec = _FOURCC_LABELS.get(text.upper(), text.upper())

    width = _num(cv2.CAP_PROP_FRAME_WIDTH)
    height = _num(cv2.CAP_PROP_FRAME_HEIGHT)
    fps = _num(cv2.CAP_PROP_FPS)
    return SourceMeta(
        codec=codec,
        width=int(width) if width else None,
        height=int(height) if height else None,
        fps=round(fps, 2) if fps else None,
        uncompressed_note=uncompressed_warning(cap),
    )


def open_capture(src: str):  # noqa: ANN201 — cv2.VideoCapture; cv2 must stay service-local
    """Open ``src`` — a local device or a validated network URL — or raise.

    Raises:
        LiveCaptureError: Unknown source shape, unreachable stream, or a device
            that is absent/busy. The message names which.
    """
    import cv2  # noqa: PLC0415 — heavy import, service-local by design

    m = _DEVICE_ID_RE.match((src or "").strip())
    if m:
        if sys.platform == "win32":
            index = int(m.group(2) if m.group(2) is not None else m.group(1))
            cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        else:
            number = m.group(1) if m.group(1) is not None else m.group(2)
            cap = cv2.VideoCapture(f"/dev/video{int(number)}", cv2.CAP_V4L2)
        if not cap.isOpened():
            cap.release()
            raise LiveCaptureError(
                f"could not open capture device {src!r} — check that it is connected "
                "and not in use by another program. HDMI sources need their capture "
                "card plugged in AND an active signal on the HDMI input."
            )
        # ★ ASK THE DEVICE FOR MJPEG, NEVER RAW. UVC devices default to raw YUYV on
        #   many stacks, and raw 1080p does not fit USB2 bandwidth — the device then
        #   crawls at a few fps (field report: "YUYV makes the fps too slow"). Nearly
        #   every camera/capture card also exposes an MJPEG pin, which fits easily
        #   at full frame rate. Must be requested BEFORE the first read (V4L2 locks
        #   the format once streaming starts). A device without MJPEG ignores the
        #   request and keeps its native format — the stats panel's Encoding row
        #   reports whichever actually won, so a slow raw device is visible, not
        #   mysterious.
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FPS, float(_DEVICE_TARGET_FPS))
        # ★ NEGOTIATE BEFORE ASKING WHAT WON. V4L2 does not apply a format change
        #   until streaming actually starts, so reading CAP_PROP_FOURCC straight
        #   after `set` reports the format the device had BEFORE the request — a
        #   camera that switches to MJPEG perfectly well still answers "YUYV" here.
        #   Pulling one frame forces the negotiation; only then is the read-back a
        #   fact rather than a stale value. (Field report: an earlier hard refusal
        #   rejected a working webcam because of exactly this.)
        cap.read()
        return cap

    checked = validate_stream_url(src)
    cap = cv2.VideoCapture(
        checked,
        cv2.CAP_FFMPEG,
        [
            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, _TIMEOUT_MS,
            cv2.CAP_PROP_READ_TIMEOUT_MSEC, _TIMEOUT_MS,
        ],
    )
    if not cap.isOpened():
        cap.release()
        raise LiveCaptureError(
            "could not connect to the stream — check that the camera/Pi is on, the "
            "URL is right, and this machine can reach it (same network, port open)."
        )
    return cap


def mjpeg_stream(src: str, *, fps: float = 30.0, quality: int = 80) -> tuple[SourceMeta, Iterator[bytes]]:
    """Open ``src`` and return ``(meta, frames)`` — the source's own metadata plus a
    generator of ``multipart/x-mixed-replace`` parts (boundary ``frame``).

    ★ This is what puts LOCAL devices and RTSP on the app panel: the browser can
    render only http MJPEG, so the server opens the device/stream with OpenCV and
    re-serves it as exactly that. ``meta`` names the SOURCE's codec (H264 from an
    RTSP camera, MJPG/YUYV from a capture card) so the UI can state what is being
    re-encoded, not just what arrives. Blocking — serve through a threadpool
    (FastAPI's ``StreamingResponse`` over a sync generator does this).

    The device is held open for the LIFETIME of the iterator and released when the
    consumer stops (client disconnect → ``GeneratorExit`` → ``finally``) — or when
    :func:`preempt_device` asks for it (a detection run taking over).
    """
    if is_device_source(src):
        # ★ THE NEWEST VIEWER WINS (2026-09-02). A device streams for one owner,
        #   and a browser <img> that was removed from the DOM can keep its MJPEG
        #   download alive as a ZOMBIE — Chromium does not reliably abort it. The
        #   grid tile's zombie held /dev/video0 and the camera page could only
        #   refuse until a hard reload killed every connection. A fresh preview
        #   therefore evicts every other proxy of the SAME device server-side —
        #   zombies included — exactly as a starting detection run does.
        preempt_device(src)
        # ★ The previous owner (a run that just stopped, a proxy being replaced)
        #   releases the device asynchronously — its reader thread must first come
        #   back from a blocking read. Refusing instantly turned every Stop into a
        #   coin-flip "source refused"; retrying for a few seconds is the handover.
        deadline = time.monotonic() + _DEVICE_OPEN_RETRY_S
        while True:
            try:
                cap = open_capture(src)
                break
            except LiveCaptureError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.25)
    else:
        cap = open_capture(src)
    return _source_meta(cap), _mjpeg_frames(cap, src, fps=fps, quality=quality)


def _mjpeg_frames(cap: Any, src: str, *, fps: float, quality: int) -> Iterator[bytes]:  # noqa: ANN401
    """The grab/encode/yield loop behind :func:`mjpeg_stream`. Owns the release."""
    import cv2  # noqa: PLC0415 — heavy import, service-local by design

    interval = 1.0 / max(1.0, min(fps, _MAX_RESTREAM_FPS))
    encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), int(min(max(quality, 30), 95))]
    misses = 0
    # Device sources register for preemption — a starting run must not have to
    # wait for the browser to notice its <img> is gone.
    stop = threading.Event() if is_device_source(src) else None
    if stop is not None:
        with _PROXY_LOCK:
            _PROXY_STOPS.setdefault(src, set()).add(stop)
    try:
        while True:
            if stop is not None and stop.is_set():
                break  # a detection run asked for the device — release NOW
            started = time.monotonic()
            ok, frame = cap.read()
            if not ok or frame is None or frame.size == 0:
                # A single dropped frame is a glitch; a run of them is a dead source.
                misses += 1
                if misses > 25:
                    break
                time.sleep(0.1)
                continue
            misses = 0
            encoded, jpg = cv2.imencode(".jpg", frame, encode_params)
            if not encoded:
                continue
            data = jpg.tobytes()
            _LAST_FRAME[src] = data  # what "Capture frame" saves while we hold the device
            _LAST_FRAME_T[src] = time.monotonic()  # so the drift tap can refuse a stale one
            yield (
                b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                + str(len(data)).encode()
                + b"\r\n\r\n"
                + data
                + b"\r\n"
            )
            # Pace to the fps cap — a 60 fps capture card would otherwise saturate
            # the JPEG encoder and the wire for detail nobody perceives in a panel.
            delay = interval - (time.monotonic() - started)
            if delay > 0:
                time.sleep(delay)
    finally:
        _LAST_FRAME.pop(src, None)
        _LAST_FRAME_T.pop(src, None)
        try:
            cap.release()
        finally:
            # Deregister AFTER the release: preempt_device's wait ends only once
            # the device is genuinely free to open.
            if stop is not None:
                with _PROXY_LOCK:
                    peers = _PROXY_STOPS.get(src)
                    if peers is not None:
                        peers.discard(stop)
                        if not peers:
                            _PROXY_STOPS.pop(src, None)


def capture_frame(url: str, out_dir: Path, *, name: str | None = None) -> CapturedFrame:
    """Grab ONE frame from ``url`` — a network stream OR a local device — as a JPEG.

    Blocking (network/device + decode) — callers on an event loop must run it in
    a thread. (The parameter keeps its historical name ``url``; a local device id
    like ``/dev/video0`` is equally accepted — ``open_capture`` dispatches.)

    ★ A device already being WATCHED cannot be opened a second time — the capture
    is then served from the live stream's own most recent frame (``_LAST_FRAME``),
    which is also exactly what the operator sees on the panel at that moment.

    Raises:
        LiveCaptureError: Bad source, unreachable stream/device, or a source that
            opened but produced no frame. The message states which.
    """
    import cv2  # noqa: PLC0415 — heavy import, service-local by design
    import numpy as np  # noqa: PLC0415 — arrives with cv2; service-local for the same reason

    src = (url or "").strip()
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = _frame_filename(name, src, datetime.now(UTC))
    path = out_dir / filename

    cached = _LAST_FRAME.get(src)
    if cached is not None:
        # The source is live on the panel right now — save what it is showing.
        frame = cv2.imdecode(np.frombuffer(cached, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise LiveCaptureError("the live stream's current frame could not be decoded.")
        path.write_bytes(cached)
    else:
        cap = open_capture(src)
        try:
            ok, frame = cap.read()
        finally:
            cap.release()
        if not ok or frame is None or frame.size == 0:
            raise LiveCaptureError(
                "connected to the source but received no frame — it answered yet sent "
                "no video (wrong endpoint path, camera not streaming, or no signal on "
                "the HDMI input)."
            )
        if not cv2.imwrite(str(path), frame):
            raise LiveCaptureError(f"could not write the frame to {path}.")

    height, width = frame.shape[:2]
    size_bytes = path.stat().st_size
    log.info("live frame captured: %s (%dx%d, %d bytes) from %s", filename, width, height, size_bytes, src)
    return CapturedFrame(filename=filename, path=path, width=width, height=height, size_bytes=size_bytes)
