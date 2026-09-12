"""``transcode_video_preview`` — a browser-playable H.264 preview for HEVC uploads.

★ WHY THIS EXISTS. Drones default to HEVC (H.265) in an ``.mp4`` container, and no
mainstream browser will decode it — so the player could neither play nor seek
natively, and every scrub position cost a server round-trip. This task derives a
*second* file (``preview.mp4``: H.264, ≤1080p, faststart) purely for the ``<video>``
element. The ORIGINAL remains the single source of truth: frame capture and every
survey artefact keep reading it at full resolution — the preview is eyes-only.

★ NO JOB ROW, NO STATUS ENDPOINT — deliberately. The client polls
``VideoRead.preview_available``, which is simply "does the preview object exist".
Existence-as-signal means a re-run is naturally idempotent, a crashed worker leaves
nothing half-announced (ffmpeg writes to a temp path; only a finished file is
uploaded), and there is no state machine to reconcile.

★ ffmpeg comes from ``imageio-ffmpeg`` — a static binary inside the wheel — so this
works on the packaged desktop runtime without a system ffmpeg. It is imported inside
the task (§11.3): the API process must never need it.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
import uuid
from pathlib import Path

from celery import shared_task
from sqlalchemy import select

from app.db.session import sync_session
from app.storage import keys

_log = logging.getLogger("app.tasks.transcoding")

TASK_TRANSCODE_PREVIEW = "app.tasks.transcode_video_preview"

#: Codecs the <video> element already plays — uploads in these need no preview.
BROWSER_NATIVE_CODECS = frozenset({"avc1", "h264", "x264"})

#: ★ 1080p ceiling. The preview exists to be WATCHED while choosing a moment; the
#: capture endpoint reads the original, so preview pixels are never measured. 4K
#: H.264 would triple the transcode time and the bytes for zero survey value.
_MAX_WIDTH = 1920


def needs_preview(codec: str | None) -> bool:
    """True when the browser cannot be expected to decode ``codec`` natively."""
    return codec is None or codec.lower() not in BROWSER_NATIVE_CODECS


def _ffmpeg_exe() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


@shared_task(
    name=TASK_TRANSCODE_PREVIEW,
    ignore_result=True,
    # ★ acks_late + one retry: a worker killed mid-transcode re-runs the task once;
    #   idempotence is free because only a completed file is ever uploaded.
    acks_late=True,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 1, "countdown": 30},
)
def transcode_video_preview(video_id: str) -> None:
    """Derive ``preview.mp4`` for one video, if it still needs one."""
    from app.models.video import Video
    from app.storage import get_storage

    storage = get_storage()

    with sync_session() as db:
        row = db.execute(select(Video).where(Video.id == uuid.UUID(video_id))).scalar_one_or_none()
        if row is None or row.deleted_at is not None:
            _log.info("preview skipped: video %s is gone", video_id)
            return
        project_id, source_key, codec = row.project_id, row.storage_path, row.codec

    preview_key = keys.video_preview_key(project_id, uuid.UUID(video_id))
    if not needs_preview(codec):
        _log.info("preview skipped: %s is already browser-native (%s)", video_id, codec)
        return
    if storage.exists(preview_key):
        _log.info("preview skipped: %s already has one", video_id)
        return

    with tempfile.TemporaryDirectory(prefix="le-transcode-") as tmp:
        src = Path(tmp) / "source.mp4"
        dst = Path(tmp) / "preview.mp4"
        with storage.open(source_key) as fh, src.open("wb") as out:
            while chunk := fh.read(1024 * 1024):
                out.write(chunk)

        cmd = [
            _ffmpeg_exe(),
            "-y",
            "-i", str(src),
            # ★ -2, not -1: H.264 requires even dimensions and a 4K→1080p halving of
            #   an odd-height crop would otherwise fail the whole transcode.
            "-vf", f"scale='min({_MAX_WIDTH},iw)':-2",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            # ★ Forced 8-bit 4:2:0: drone HEVC is often 10-bit, and x264 would happily
            #   emit High10 — which browsers reject exactly like HEVC, recreating the
            #   original problem in a new codec.
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-c:a", "aac",
            "-b:a", "128k",
            str(dst),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            tail = proc.stderr.strip().splitlines()[-3:]
            raise RuntimeError(f"ffmpeg failed for video {video_id}: {' | '.join(tail)}")

        preview_bytes = dst.stat().st_size
        with dst.open("rb") as fh:
            storage.put(preview_key, fh, content_type="video/mp4")

    _log.info("preview ready: video %s (%s -> h264, %d bytes)", video_id, codec, preview_bytes)
