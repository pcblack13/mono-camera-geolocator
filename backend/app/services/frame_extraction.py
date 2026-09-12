"""Server-side video frame extraction — the core new CV code of the VIDEO feature.

★ **A pure helper.** No FastAPI, no SQLAlchemy, no ``app.storage`` — it takes a
filesystem path and a timestamp and returns bytes and dimensions. That keeps it unit
testable with a bare ``cv2.VideoWriter`` fixture and importable into a worker, exactly
as a ``gis/`` helper would be (the backend has no ``gis`` package, so it lives beside the
service that uses it, with the same no-framework discipline a ``gis`` module would keep).

★ **Why server-side at all.** Browsers cannot decode AVI/MKV/some MOV, but OpenCV's
FFMPEG backend can, and seeking with ``CAP_PROP_POS_MSEC`` gives the exact frame at the
exact timestamp — which is the whole point of "capture this second as a photo".

★ **L5.** A single-frame decode is a bounded, fast CV op — comparable to the thumbnail
downsample the image API already does synchronously. Callers run it inline; see
``video_service`` for the note on why a job round-trip per frame would ruin the UX.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

__all__ = [
    "ExtractedFrame",
    "FrameExtractionError",
    "VideoMetadata",
    "extract_frame",
    "read_metadata",
]


class FrameExtractionError(Exception):
    """The file could not be opened, probed, or a frame could not be decoded.

    Deliberately a plain exception with no HTTP status: the service maps it onto a clean
    ``415``/``422`` domain error. It is **never** allowed to surface as a 500 — an
    out-of-range timestamp or a corrupt container is the user's input, not our bug.
    """


@dataclass(frozen=True, slots=True)
class VideoMetadata:
    """What OpenCV's FFMPEG backend reports about a video container."""

    duration_s: float
    fps: float
    width: int
    height: int
    #: ``CAP_PROP_FRAME_COUNT`` is an estimate for some containers — nullable on the wire.
    frame_count: int | None
    #: FourCC, decoded to its four characters (``"avc1"``, ``"mp4v"``…), or None.
    codec: str | None


@dataclass(frozen=True, slots=True)
class ExtractedFrame:
    """A single decoded frame, JPEG-encoded, with its pixel dimensions."""

    jpeg_bytes: bytes
    width: int
    height: int


def _fourcc_to_str(fourcc: float) -> str | None:
    """Decode the ``CAP_PROP_FOURCC`` double into its four ASCII characters, or None."""
    code = int(fourcc)
    if code <= 0:
        return None
    chars = bytes((code >> (8 * i)) & 0xFF for i in range(4))
    try:
        text = chars.decode("ascii").strip("\x00 ")
    except UnicodeDecodeError:
        return None
    return text or None


def read_metadata(path: str) -> VideoMetadata:
    """Probe a video's duration, fps, dimensions, frame count and codec.

    ★ Works for every format cv2's FFMPEG backend supports (mp4, mov, avi, mkv). Reads
    only header/index metadata — no pixels are decoded.

    Args:
        path: A filesystem path OpenCV can open.

    Returns:
        The :class:`VideoMetadata`.

    Raises:
        FrameExtractionError: the file could not be opened, or reports no usable frame
            geometry (a zero-sized video is not a video).
    """
    cap = cv2.VideoCapture(path)
    try:
        if not cap.isOpened():
            raise FrameExtractionError(f"OpenCV could not open the video at {path!r}.")
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        raw_count = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        fourcc = float(cap.get(cv2.CAP_PROP_FOURCC) or 0.0)
    finally:
        # ★ ALWAYS release — a leaked VideoCapture pins an FFMPEG demuxer and a file handle.
        cap.release()

    if width <= 0 or height <= 0:
        raise FrameExtractionError(
            f"the video at {path!r} reports a non-positive frame size ({width}x{height})."
        )

    frame_count = int(raw_count) if raw_count > 0 else None
    # duration = frames / fps, guarding fps == 0 (some webcam captures report 0 fps).
    duration_s = (frame_count / fps) if (fps > 0 and frame_count) else 0.0

    return VideoMetadata(
        duration_s=float(duration_s),
        fps=float(fps),
        width=width,
        height=height,
        frame_count=frame_count,
        codec=_fourcc_to_str(fourcc),
    )


def extract_frame(path: str, t_seconds: float, *, jpeg_quality: int = 90) -> ExtractedFrame:
    """Decode the frame at ``t_seconds`` and JPEG-encode it.

    Seeks with ``CAP_PROP_POS_MSEC`` first; if that read fails (some containers ignore a
    millisecond seek), falls back to seeking by frame index ``round(t * fps)``. ``t`` is
    clamped to ``[0, duration]`` so a click one frame past the end still returns the last
    frame rather than erroring.

    Args:
        path: A filesystem path OpenCV can open.
        t_seconds: The timestamp to capture, in seconds.
        jpeg_quality: libjpeg quality, 0–100.

    Returns:
        The :class:`ExtractedFrame` — JPEG bytes plus ``(width, height)`` in pixels.

    Raises:
        FrameExtractionError: the file could not be opened, or no frame could be decoded
            at (or near) the requested time. Callers map this to a 422, never a 500.
    """
    if t_seconds < 0:
        # Clamp rather than reject a small negative: a scrubber at 0 can emit -0.001.
        t_seconds = 0.0

    cap = cv2.VideoCapture(path)
    try:
        if not cap.isOpened():
            raise FrameExtractionError(f"OpenCV could not open the video at {path!r}.")

        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration_s = (frame_count / fps) if (fps > 0 and frame_count > 0) else None

        t = t_seconds
        if duration_s is not None and t > duration_s:
            t = duration_s

        # Primary: seek by presentation time.
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ok, frame = cap.read()

        # Fallback: seek by frame index. A msec seek can land just past the last frame,
        # so clamp the index into range before retrying.
        if not ok or frame is None:
            if fps > 0:
                idx = int(round(t * fps))
                if frame_count > 0:
                    idx = max(0, min(idx, frame_count - 1))
                cap.set(cv2.CAP_PROP_POS_FRAMES, float(idx))
                ok, frame = cap.read()

        if not ok or frame is None:
            raise FrameExtractionError(
                f"no frame could be decoded at t={t_seconds}s in {path!r}."
            )
    finally:
        cap.release()

    # ★ ``frame`` is BGR (OpenCV's native order). ``cv2.imencode`` expects BGR, so encode
    # the ORIGINAL frame — NOT a BGR->RGB converted copy, which would swap the red and
    # blue channels in the stored JPEG. This is the easy bug the brief warns about.
    height, width = frame.shape[:2]
    success, buffer = cv2.imencode(
        ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)]
    )
    if not success:
        raise FrameExtractionError(f"JPEG encoding failed for the frame at t={t_seconds}s.")

    return ExtractedFrame(
        jpeg_bytes=np.asarray(buffer, dtype=np.uint8).tobytes(),
        width=int(width),
        height=int(height),
    )
