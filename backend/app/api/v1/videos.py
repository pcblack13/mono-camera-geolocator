"""Videos — a field VIDEO uploaded as a FRAME SOURCE.

* ``POST   /videos``                 — 201 VideoRead. Multipart; streamed to storage.
* ``GET    /videos?project_id=``     — Page[VideoSummary].
* ``GET    /videos/{video_id}``      — VideoRead.
* ``GET    /videos/{video_id}/file`` — ★ byte stream WITH HTTP RANGE (browsers scrub via it).
* ``GET    /videos/{video_id}/frame?t=`` — a JPEG preview of that second. Creates no image.
* ``POST   /videos/{video_id}/frames``   — ★ "capture this frame" → 201 ImageRead.
* ``DELETE /videos/{video_id}``      — 204 soft-delete.

★ **A captured frame is just a photo.** ``POST /videos/{id}/frames`` decodes the frame at
``t_seconds`` server-side (OpenCV) and returns a normal **201 ImageRead** — from there the
existing annotation/GCP/workspace flow owns it, unchanged.

★ ``GET /videos/{id}/file`` **reuses images.py's ``_serve_object``** — the single
Range-capable byte streamer — because scrubbing is broken without ``206 Partial Content``.
The body-size limit is ``LE_UPLOAD_MAX_BYTES`` (4 GB), already the video allowance, so no
per-route override is needed.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile, status
from fastapi.responses import Response as RawResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps, presenters
from app.api.v1.images import _serve_object  # the one Range-capable streamer (reused)
from app.core.config import Settings
from app.core.exceptions import NotFoundError, ValidationError
from app.core.pagination import SortKey, SortParams
from app.schemas.common import Page
from app.schemas.image import ImageRead
from app.schemas.video import (
    VIDEO_SORT_FIELDS,
    VideoFrameCapture,
    VideoRead,
    VideoSummary,
)
from app.services.video_service import VideoService
from app.storage import keys
from app.storage.base import ObjectStorage

router = APIRouter()

_DEFAULT_SORT = (SortKey("created_at", descending=True),)

#: ★ EXTENSION → MIME for the source_path (desktop) route. Python's
#: ``mimetypes.guess_type`` reads the WINDOWS REGISTRY there, which returns
#: unpredictable values ('.mkv'→None, '.mov'→sometimes not 'video/quicktime',
#: '.mp4'→occasionally a registry-custom type) — so a video the surveyor picked
#: was rejected by the allow-list on Windows while the SAME file uploaded fine on
#: Linux (field report). This explicit map removes the OS from the equation; OpenCV
#: probing after storage is still the authoritative "is it really a video" gate.
_VIDEO_EXT_MIME: dict[str, str] = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/quicktime",
    ".qt": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".mpg": "video/mpeg",
    ".mpeg": "video/mpeg",
    ".ts": "video/mp2t",
    ".mts": "video/mp2t",
    ".m2ts": "video/mp2t",
    ".wmv": "video/x-ms-wmv",
    ".flv": "video/x-flv",
    ".3gp": "video/3gpp",
}


def _video_mime_for(name: str) -> str | None:
    """MIME for a video filename from its extension — OS-independent (see the map)."""
    return _VIDEO_EXT_MIME.get(Path(name).suffix.lower())


def _prefix(request: Request) -> str:
    return f"{request.scope.get('root_path', '')}/api/v1"


@router.post(
    "/videos",
    response_model=VideoRead,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a video",
)
async def upload_video(
    request: Request,
    response: Response,
    project_id: UUID | None = Form(
        None,
        description=(
            "The project the clip belongs to. ★ OPTIONAL (0018): omit it for a clip that "
            "only feeds detection or the drift monitor — it lives in the library, and a "
            "frame captured from it asks for its project then."
        ),
    ),
    file: UploadFile | None = File(None),
    source_path: str | None = Form(
        None,
        description=(
            "★ DESKTOP ROUTE: an absolute path to the video on the API's OWN machine, "
            "instead of `file`. A field video is routinely multiple GB; the path is "
            "streamed straight from disk — same contract as /dem/process. Exactly one "
            "of `file`/`source_path`."
        ),
    ),
    filename: str | None = Form(None),
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    storage: ObjectStorage = Depends(deps.get_storage),
    _: None = Depends(deps.require_writable),
) -> VideoRead:
    service = VideoService(db, settings, storage=storage, queue=deps.get_job_queue(request))
    if (file is None) == (source_path is None):
        raise ValidationError(
            "send exactly one of `file` (the upload) or `source_path` (a file on the "
            "API's own machine)."
        )
    if file is not None:
        video = await service.upload(
            project_id=project_id,
            filename=filename or file.filename or "video",
            content_type=file.content_type,
            data=file.file,  # ★ streamed to storage, never buffered whole
        )
    else:
        # ★ LOCAL-PATH MODE (desktop shell). CSRF guard as in dem.py: a cross-origin
        #   form can't add a custom header without passing CORS preflight, so require
        #   the X-Request-ID every first-party client already sends.
        if request.headers.get("x-request-id") is None:
            raise ValidationError("source_path requires the X-Request-ID header.")
        assert source_path is not None
        local = Path(source_path).expanduser()
        if not local.is_file():
            raise ValidationError(
                f"source_path does not exist or is not a file: {source_path!r}"
            )
        # The body-size middleware never sees the real size in path mode — enforce
        # the same ceiling here.
        size = local.stat().st_size
        limit = int(getattr(settings, "upload_max_bytes", 0) or 0)
        if limit and size > limit:
            raise ValidationError(
                f"the video exceeds the {limit / (1024 * 1024):.0f} MB upload limit."
            )
        if size == 0:
            raise ValidationError("the video file is empty.")
        with local.open("rb") as fh:
            video = await service.upload(
                project_id=project_id,
                filename=filename or local.name,
                # ★ Extension-mapped, NOT mimetypes.guess_type — the latter is the
                #   Windows registry and rejected valid videos there. OpenCV probing
                #   after storage is the authoritative check regardless.
                content_type=_video_mime_for(filename or local.name),
                data=fh,  # ★ streamed from disk to storage, never buffered whole
            )
    await db.flush()
    prefix = _prefix(request)
    response.headers["Location"] = f"{prefix}/videos/{video.id}"
    return presenters.to_video_read(video, prefix=prefix)


@router.get("/videos", response_model=Page[VideoSummary], summary="List videos")
async def list_videos(
    pagination=Depends(deps.get_pagination),
    sort: str | None = Depends(deps.get_sort),
    project_id: UUID | None = Query(None),
    q: str | None = Query(None),
    include_deleted: bool = Query(False),
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    storage: ObjectStorage = Depends(deps.get_storage),
) -> Page[VideoSummary]:
    service = VideoService(db, settings, storage=storage)
    parsed = SortParams.parse(sort, allowed=VIDEO_SORT_FIELDS, default=_DEFAULT_SORT)
    rows, total = await service.list(
        pagination=pagination,
        sort=parsed,
        project_id=project_id,
        q=q,
        include_deleted=include_deleted,
    )
    items = [presenters.to_video_summary(v) for v in rows]
    return Page.of(items, total, pagination)


@router.get("/videos/{video_id}", response_model=VideoRead, summary="Get a video")
async def get_video(
    request: Request,
    video=Depends(deps.get_video),
    storage: ObjectStorage = Depends(deps.get_storage),
) -> VideoRead:
    return presenters.to_video_read(
        video,
        prefix=_prefix(request),
        # ★ An existence stat, not a DB column: the transcode task announces
        #   completion by writing the object, so the object IS the status.
        preview_available=storage.exists(
            keys.video_preview_key(video.project_id, video.id)
        ),
    )


@router.get("/videos/{video_id}/file", summary="Stream video bytes (HTTP Range)")
async def get_video_file(
    request: Request,
    download: bool = Query(False),
    video=Depends(deps.get_video),
    storage: ObjectStorage = Depends(deps.get_storage),
) -> Response:
    # ★ Range support is what makes scrubbing work — reused verbatim from images.py.
    return _serve_object(
        request,
        storage,
        key=video.storage_path,
        media_type=video.mime_type,
        download_name=video.filename if download else None,
    )


@router.get("/videos/{video_id}/preview", summary="Stream the H.264 preview (HTTP Range)")
async def get_video_preview(
    request: Request,
    video=Depends(deps.get_video),
    storage: ObjectStorage = Depends(deps.get_storage),
) -> Response:
    """The browser-playable derivation of an HEVC upload — see ``app.tasks.transcoding``.

    404 while the transcode is still running (or for uploads that never needed one):
    ``VideoRead.preview_available`` is the readiness signal, and the player keeps its
    server-rendered scrub fallback until it flips.
    """
    key = keys.video_preview_key(video.project_id, video.id)
    if not storage.exists(key):
        raise NotFoundError(
            "no playable preview exists for this video yet; if it was just uploaded, "
            "the transcode may still be running."
        )
    return _serve_object(request, storage, key=key, media_type="video/mp4", download_name=None)


@router.get("/videos/{video_id}/frame", summary="A JPEG preview of one frame (creates no image)")
async def get_video_frame(
    t: float = Query(..., ge=0.0, description="The second to preview."),
    video=Depends(deps.get_video),
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    storage: ObjectStorage = Depends(deps.get_storage),
) -> RawResponse:
    service = VideoService(db, settings, storage=storage)
    jpeg = service.get_frame_preview(video, t)
    # A short cache: the same (video, t) always decodes to the same bytes.
    return RawResponse(content=jpeg, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


@router.post(
    "/videos/{video_id}/frames",
    response_model=ImageRead,
    status_code=status.HTTP_201_CREATED,
    summary="Capture a frame as a real image",
)
async def capture_video_frame(
    body: VideoFrameCapture,
    request: Request,
    response: Response,
    video=Depends(deps.get_video),
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    storage: ObjectStorage = Depends(deps.get_storage),
    _: None = Depends(deps.require_writable),
) -> ImageRead:
    service = VideoService(db, settings, storage=storage, queue=deps.get_job_queue(request))
    result = await service.capture_frame(
        video,
        t_seconds=body.t_seconds,
        code=body.code,
        filename=body.filename,
        project_id=body.project_id,
    )
    await db.flush()
    prefix = _prefix(request)
    response.headers["Location"] = f"{prefix}/images/{result.image.id}"
    return presenters.to_image_read(result.image, prefix=prefix)


@router.delete(
    "/videos/{video_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a video (never its captured frames)",
)
async def delete_video(
    video_id: UUID,
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    storage: ObjectStorage = Depends(deps.get_storage),
    _: None = Depends(deps.require_writable),
) -> Response:
    # ★ Soft delete. The images already captured from this video keep pointing at it and
    #   are untouched — a video is a source, not an owner of its frames.
    await VideoService(db, settings, storage=storage).soft_delete(video_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
