"""Device handover between the preview proxy and a detection run (2026-09-02).

★ THE BUG THESE PIN: a V4L2 device streams for ONE owner, and the app's preview
proxy and its own detection runs raced for it — "turn on the detection and the
app loses the stream", then a reconnect refused with "in use by another
program". The fixes: ``preempt_device`` makes a starting run evict the proxy
SERVER-side (instead of waiting for the browser to drop an <img>), and a
device open now retries briefly while the previous owner's reader thread gets
back from its blocking read and releases.
"""

from __future__ import annotations

import threading
import time

import numpy as np
import pytest

from app.services import live_stream_service as lss
from app.services.live_stream_service import (
    LiveCaptureError,
    mjpeg_stream,
    preempt_device,
)


class FakeCap:
    """A stand-in cv2.VideoCapture: endless tiny frames, release recorded."""

    def __init__(self) -> None:
        """Nothing to configure — the fake is its own state."""
        self.released = False
        self._frame = np.zeros((8, 8, 3), dtype=np.uint8)

    def read(self):
        time.sleep(0.01)
        return True, self._frame

    def release(self) -> None:
        self.released = True

    def get(self, _prop: int) -> float:  # _source_meta probes props
        return 0.0

    def isOpened(self) -> bool:  # noqa: N802 — cv2 spelling
        return True


def test_preempt_evicts_a_live_proxy_and_waits_for_the_release() -> None:
    cap = FakeCap()
    src = "/dev/video9"
    frames = lss._mjpeg_frames(cap, src, fps=60.0, quality=50)
    consumed = threading.Event()
    ended = threading.Event()

    def consume() -> None:
        for i, _part in enumerate(frames):
            consumed.set()
            if ended.is_set():  # safety valve; preemption should end the loop
                break
            if i > 500:
                break
        ended.set()

    t = threading.Thread(target=consume, daemon=True)
    t.start()
    assert consumed.wait(5.0), "the proxy never produced a frame"
    with lss._PROXY_LOCK:
        assert src in lss._PROXY_STOPS  # registered while streaming

    t0 = time.monotonic()
    preempt_device(src)  # ← the run taking over
    assert ended.wait(5.0), "preemption did not end the proxy loop"
    t.join(5.0)
    # The wait returned only once the device was genuinely free:
    assert cap.released
    with lss._PROXY_LOCK:
        assert src not in lss._PROXY_STOPS
    assert time.monotonic() - t0 < 3.0  # ended early, not by timeout


def test_preempt_is_a_noop_for_network_sources_and_idle_devices() -> None:
    # An http stream serves many readers — nothing to evict, nothing to wait for.
    t0 = time.monotonic()
    preempt_device("http://cam/stream")
    preempt_device("/dev/video7")  # no proxy registered
    assert time.monotonic() - t0 < 0.5


def test_device_open_retries_through_the_previous_owners_release(monkeypatch) -> None:
    """The reconnect rides out the previous owner's late release.

    A Stop's reader thread releases the device only after its blocking read
    returns; the reconnecting preview must retry, not refuse on attempt one.
    """
    attempts = {"n": 0}
    cap = FakeCap()

    def flaky_open(_src: str):  # noqa: ANN202
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise LiveCaptureError("could not open capture device — in use")
        return cap

    monkeypatch.setattr(lss, "open_capture", flaky_open)
    monkeypatch.setattr(lss, "_DEVICE_OPEN_RETRY_S", 3.0)
    meta, frames = mjpeg_stream("/dev/video9", fps=60.0)
    assert attempts["n"] == 3  # two busy refusals absorbed
    frames.close()  # release the fake

    # A device that never frees still fails, with the same honest words.
    attempts["n"] = 0

    def always_busy(_src: str):  # noqa: ANN202
        attempts["n"] += 1
        raise LiveCaptureError("could not open capture device — in use")

    monkeypatch.setattr(lss, "open_capture", always_busy)
    monkeypatch.setattr(lss, "_DEVICE_OPEN_RETRY_S", 0.6)
    with pytest.raises(LiveCaptureError):
        mjpeg_stream("/dev/video9", fps=60.0)
    assert attempts["n"] >= 2  # it did retry before giving up

    # Network sources keep single-shot semantics — their errors are not "busy".
    attempts["n"] = 0
    monkeypatch.setattr(
        lss, "open_capture", lambda _src: (_ for _ in ()).throw(LiveCaptureError("unreachable"))
    )
    with pytest.raises(LiveCaptureError):
        mjpeg_stream("http://cam/stream", fps=60.0)


def test_a_fresh_preview_evicts_a_zombie_proxy_of_the_same_device(monkeypatch) -> None:
    """The newest viewer wins the device.

    A removed <img> can keep its MJPEG download alive (a zombie) and hold the
    device forever; a NEW preview of the same device evicts it server-side.
    """
    zombie_cap = FakeCap()
    src = "/dev/video8"
    zombie_frames = lss._mjpeg_frames(zombie_cap, src, fps=60.0, quality=50)
    zombie_ended = threading.Event()

    def consume() -> None:
        for _ in zombie_frames:  # never aborted by any client — the zombie
            pass
        zombie_ended.set()

    threading.Thread(target=consume, daemon=True).start()
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        with lss._PROXY_LOCK:
            if src in lss._PROXY_STOPS:
                break
        time.sleep(0.02)

    fresh_cap = FakeCap()
    monkeypatch.setattr(lss, "open_capture", lambda _src: fresh_cap)
    _meta, frames = mjpeg_stream(src, fps=60.0)
    assert zombie_ended.wait(5.0), "the zombie proxy was not evicted"
    assert zombie_cap.released  # the device was genuinely freed first
    frames.close()
