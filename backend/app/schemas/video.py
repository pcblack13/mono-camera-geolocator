"""Videos — a field VIDEO uploaded as a FRAME SOURCE.

Mirrors ``image.py``'s file-half shape: a fat ``VideoRead``, a thin ``VideoSummary`` list
projection, a ``VideoListParams`` query model, plus the one thing images have no analogue
for — ``VideoFrameCapture``, the body of "capture this second as a photo".

★ **A video carries no geometry and no status enum.** It is not ingested, not matched, not
georeferenced. Its whole job is to hand the surveyor a frame, and the frame — once
captured — is a normal ``images`` row that the existing pipeline owns. So there is no
``VideoUpdate``: the container's facts (duration, fps, dimensions) are established by the
decoder at upload and there is nothing on a video a client may edit.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from .common import ApiModel, ListParams

__all__ = [
    "VIDEO_SORT_FIELDS",
    "VideoFrameCapture",
    "VideoListParams",
    "VideoRead",
    "VideoSummary",
    "VideoUrls",
]

VIDEO_SORT_FIELDS = frozenset(
    {"filename", "created_at", "updated_at", "size_bytes", "duration_s"}
)


class VideoUrls(ApiModel):
    """★ ``storage_path`` is **NEVER serialised** — a video is served through ``file``,
    which supports HTTP Range so the browser can seek/scrub. ``frame`` is the preview
    endpoint's base; the client appends ``?t=<seconds>`` to fetch a JPEG of that second.
    """

    file: str = Field(description="Range-capable byte stream. Browsers scrub via this.")
    frame: str = Field(description="Preview base; append ?t=<seconds> for a JPEG frame.")
    preview: str = Field(
        description="Range-capable H.264 preview stream. 404 until preview_available."
    )


class VideoRead(ApiModel):
    """``VideoRead`` — the create and get responses."""

    id: UUID
    #: ``None`` for a clip that lives in the library only (0018).
    project_id: UUID | None
    filename: str
    mime_type: str
    size_bytes: int
    checksum_sha256: str
    duration_s: float = Field(ge=0.0, description="frame_count / fps, 0 when fps unknown.")
    fps: float = Field(ge=0.0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    frame_count: int | None = Field(
        default=None, description="Estimated for some containers, hence nullable."
    )
    codec: str | None = Field(default=None, description="FourCC, e.g. 'avc1' / 'mp4v'.")
    preview_available: bool = Field(
        default=False,
        description=(
            "A browser-playable H.264 preview exists (`urls.preview`). Uploads the "
            "browser can already decode never grow one — play `urls.file` directly. "
            "False for an HEVC upload means the transcode is still running; poll."
        ),
    )
    urls: VideoUrls
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class VideoSummary(ApiModel):
    """List projection — ``GET /videos``. Omits ``checksum``, ``codec``, ``urls``."""

    id: UUID
    project_id: UUID | None
    filename: str
    duration_s: float
    fps: float
    width: int
    height: int
    size_bytes: int
    created_at: datetime
    updated_at: datetime


class VideoListParams(ListParams):
    """``GET /videos``."""

    project_id: UUID | None = None
    q: str | None = Field(default=None, description="Free-text over filename.")
    include_deleted: bool = False


class VideoFrameCapture(ApiModel):
    """``POST /videos/{video_id}/frames`` — "capture this frame as a photo".

    ★ The frame at ``t_seconds`` is decoded server-side (OpenCV) and stored as a normal
    ``images`` row that records ``source_video_id`` + ``source_video_time_s``. The
    response is a **201 ImageRead** — from that point it is an ordinary image the
    annotation/GCP/workspace flow uses unchanged.
    """

    t_seconds: float = Field(
        ge=0.0, description="The second to capture. Clamped to the video's duration."
    )
    code: str | None = Field(
        default=None,
        max_length=120,
        description="Optional surveyor label for the capture, stored on the image's metadata.",
    )
    #: ★ The surveyor's own name for the photograph. Optional: ``null`` keeps the
    #: server's ``{video-stem}_t{seconds}.jpg`` default. Sanitised into the storage
    #: key server-side; a missing extension gains ``.jpg`` (the bytes ARE a JPEG,
    #: and an extensionless photo confuses every downstream export).
    filename: str | None = Field(
        default=None,
        max_length=200,
        description="A name for the captured photo. null → the server's default name.",
    )
    #: ★ The project the photograph goes to. Required when the clip has no project of
    #: its own (0018); when given for a clip that has one, it wins.
    project_id: UUID | None = Field(
        default=None,
        description=(
            "The project the captured photograph goes to. Required for a clip without a "
            "project; otherwise defaults to the clip's own."
        ),
    )
