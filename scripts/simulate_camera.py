#!/usr/bin/env python3
"""Simulate an IP camera — an MJPEG server the app cannot tell from a real one.

    python scripts/simulate_camera.py                       # synthetic moving scene
    python scripts/simulate_camera.py --file input.mp4      # loop a clip as the camera
    python scripts/simulate_camera.py --file clip.mp4 --fps 15 --port 8090

Then register ``http://127.0.0.1:8090/stream`` as a camera (Monitor → Add camera),
or paste it as a stream URL anywhere the app takes one. The REAL backend opens it
exactly as it would an IP camera: the player measures its FPS, YOLO detects on it,
the LUT places the marks, the drift watch freezes and checks it, capture grabs a
frame from it. Nothing in the app knows it is a file.

★ WHAT IT LETS YOU TEST WITHOUT HARDWARE — the failure modes, on demand:

    GET /stream                  the MJPEG stream (multipart/x-mixed-replace)
    GET /snapshot.jpg            one frame — a "snapshot endpoint" camera
    GET /control/stall?s=8       stop sending frames for 8 s → the app must say LOST
                                 (its watchdog trips at 6 s), then recover by itself
    GET /control/drop            close every open stream → a disconnect mid-run
    GET /control/refuse?on=1     answer 503 to new streams → a REFUSED source
    GET /control/refuse?on=0     …and allow them again
    GET /control/shift?px=40     shift the picture 40 px → the drift watch reports MOVED
    GET /control/status          what the simulator is doing right now

Needs OpenCV + numpy — run it with the backend's Python (the venv, or the desktop
runtime: ``desktop/runtime-build/env/bin/python``). Standard library otherwise.
"""

from __future__ import annotations

import argparse
import contextlib
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np

# ── state the control endpoints flip ─────────────────────────────────────────
_STATE = {
    "stall_until": 0.0,  # monotonic seconds; frames are withheld until then
    "refuse": False,  # new /stream requests get 503
    "shift_px": 0,  # picture shift, to make the drift watch speak
    "generation": 0,  # bumped by /control/drop — open streams see it and close
    "clients": 0,
    "frames": 0,
}
_LOCK = threading.Lock()


class Source:
    """Frames from a looping clip, or a synthetic scene with things that move."""

    def __init__(self, path: str | None, width: int, height: int) -> None:
        """Open the clip, or set up the synthetic scene at ``width`` x ``height``."""
        self.cap = cv2.VideoCapture(path) if path else None
        if self.cap is not None and not self.cap.isOpened():
            raise SystemExit(f"could not open {path}")
        self.w, self.h = width, height
        self.t0 = time.monotonic()
        self.lock = threading.Lock()

    def read(self) -> np.ndarray:
        """The next frame — the clip loops; the scene animates on the wall clock."""
        with self.lock:
            if self.cap is not None:
                ok, frame = self.cap.read()
                if not ok:  # loop
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ok, frame = self.cap.read()
                    if not ok:
                        raise SystemExit("the clip yields no frames")
                return frame
            return self._synthetic()

    def _synthetic(self) -> np.ndarray:
        """A hillside road with a few vehicles driving along it.

        Enough for YOLO to find nothing real, but everything else — FPS, stall,
        drift, capture — to run.
        """
        t = time.monotonic() - self.t0
        h, w = self.h, self.w
        img = np.zeros((h, w, 3), np.uint8)
        ys = np.linspace(0, 1, h)[:, None]
        img[:, :, 0] = (120 - 60 * ys).astype(np.uint8)
        img[:, :, 1] = (70 + 90 * ys).astype(np.uint8)
        img[:, :, 2] = (40 + 60 * ys).astype(np.uint8)
        cv2.rectangle(img, (0, int(h * 0.52)), (w, h), (60, 110, 70), -1)
        road = np.array([[int(w * 0.40), h], [int(w * 0.60), h], [int(w * 0.54), int(h * 0.54)], [int(w * 0.47), int(h * 0.54)]], np.int32)
        cv2.fillPoly(img, [road], (90, 90, 95))
        # three "cars" moving down the road at different speeds
        for k, speed in enumerate((0.05, 0.08, 0.11)):
            p = (t * speed + k * 0.33) % 1.0
            y = int(h * (0.56 + 0.44 * p))
            x = int(w * (0.5 + (p - 0.5) * 0.02 * (k - 1)))
            s = int(14 + 60 * p)
            cv2.rectangle(img, (x - s // 2, y - s // 4), (x + s // 2, y + s // 4), (200, 200, 220), -1)
        # a landmark grid the drift watch can lock onto
        for gx in range(int(w * 0.05), w, int(w * 0.12)):
            for gy in range(int(h * 0.08), int(h * 0.5), int(h * 0.11)):
                cv2.circle(img, (gx, gy), 4, (230, 230, 230), -1)
                cv2.line(img, (gx - 8, gy), (gx + 8, gy), (30, 30, 30), 1)
        cv2.putText(img, time.strftime("SIM %H:%M:%S"), (16, 36), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        return img


SOURCE: Source | None = None
QUALITY = 80


def _frame_jpeg() -> bytes:
    assert SOURCE is not None
    frame = SOURCE.read()
    shift = _STATE["shift_px"]
    if shift:
        frame = np.roll(frame, shift, axis=1)
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, QUALITY])
    if not ok:
        raise RuntimeError("jpeg encode failed")
    return buf.tobytes()


class Handler(BaseHTTPRequestHandler):
    """The camera's HTTP face: the stream, a snapshot, and the control endpoints."""

    server_version = "SimCamera/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        """Log the control calls only — a stream logs nothing, like a camera."""
        if "/control/" in str(args[0] if args else ""):
            super().log_message(fmt, *args)

    def _json(self, status: int, body: str) -> None:
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # http.server's own name
        """Route one request."""
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if url.path == "/stream":
            return self._stream()
        if url.path == "/snapshot.jpg":
            jpg = _frame_jpeg()
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(jpg)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(jpg)
            return None
        if url.path == "/control/stall":
            s = float(q.get("s", ["8"])[0])
            with _LOCK:
                _STATE["stall_until"] = time.monotonic() + s
            return self._json(200, f'{{"stalled_for_s": {s}}}')
        if url.path == "/control/drop":
            with _LOCK:
                _STATE["generation"] += 1
            return self._json(200, '{"dropped": true}')
        if url.path == "/control/refuse":
            on = q.get("on", ["1"])[0] in ("1", "true", "on")
            with _LOCK:
                _STATE["refuse"] = on
            return self._json(200, f'{{"refuse": {str(on).lower()}}}')
        if url.path == "/control/shift":
            px = int(q.get("px", ["0"])[0])
            with _LOCK:
                _STATE["shift_px"] = px
            return self._json(200, f'{{"shift_px": {px}}}')
        if url.path == "/control/status":
            with _LOCK:
                st = dict(_STATE)
            st["stalled"] = time.monotonic() < st["stall_until"]
            return self._json(200, str(st).replace("'", '"').replace("True", "true").replace("False", "false"))
        return self._json(404, '{"error": "try /stream, /snapshot.jpg or /control/status"}')

    def _stream(self) -> None:
        with _LOCK:
            if _STATE["refuse"]:
                return self._json(503, '{"error": "the simulated camera is refusing connections (/control/refuse?on=0 to allow)"}')
            my_gen = _STATE["generation"]
            _STATE["clients"] += 1
        boundary = "simcameraframe"
        self.send_response(200)
        self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={boundary}")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        period = 1.0 / self.server.fps  # type: ignore[attr-defined]
        try:
            while True:
                with _LOCK:
                    if _STATE["generation"] != my_gen:
                        break  # /control/drop — a mid-run disconnect
                    stalled = time.monotonic() < _STATE["stall_until"]
                if stalled:
                    time.sleep(0.1)  # frames withheld: the app's watchdog must notice
                    continue
                jpg = _frame_jpeg()
                self.wfile.write(
                    f"--{boundary}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(jpg)}\r\n\r\n".encode()
                )
                self.wfile.write(jpg)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
                with _LOCK:
                    _STATE["frames"] += 1
                time.sleep(period)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with _LOCK:
                _STATE["clients"] -= 1


def main() -> None:
    """Parse the flags, open the source, serve until Ctrl+C."""
    global SOURCE, QUALITY
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", help="a video file to loop as the camera (default: a synthetic scene)")
    ap.add_argument("--fps", type=float, default=10.0)
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--width", type=int, default=1280, help="synthetic scene width")
    ap.add_argument("--height", type=int, default=720, help="synthetic scene height")
    ap.add_argument("--quality", type=int, default=80)
    a = ap.parse_args()
    QUALITY = a.quality
    SOURCE = Source(a.file, a.width, a.height)
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    srv.fps = a.fps  # type: ignore[attr-defined]
    srv.daemon_threads = True
    print(f"simulated camera: http://{a.host}:{a.port}/stream  ({'clip: ' + a.file if a.file else 'synthetic scene'}, {a.fps:g} fps)")
    print(f"controls:         http://{a.host}:{a.port}/control/status  (stall · drop · refuse · shift)")
    with contextlib.suppress(KeyboardInterrupt):
        srv.serve_forever()


if __name__ == "__main__":
    main()
