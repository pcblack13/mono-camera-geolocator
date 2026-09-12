"""``video_service`` — validate · store · probe · create; extract · capture frames.

A field VIDEO is a FRAME SOURCE. This service owns the video half of the feature: it
stores the upload, reads its metadata synchronously with the OpenCV/FFMPEG extractor
(``frame_extraction``), and inserts the ``videos`` row. It also serves single frames — a
throwaway JPEG preview (``get_frame_preview``) and the real "capture this frame" path
(``capture_frame``), which builds a normal ``images`` row through :class:`ImageService`.

★ **L5 — frame extraction runs SYNCHRONOUSLY, on the request path, on purpose.** A
single-frame decode is a bounded, fast CV op — the same order of magnitude as the
thumbnail downsample the image API already does inline. The alternative, a job-poll
round-trip per captured frame, would put a spinner between the surveyor's click and the
photo appearing and ruin the one interaction this whole feature exists for. The extractor
is careful to turn a bad timestamp or a corrupt container into a clean 4xx, never a 500,
so "synchronous" does not mean "a decode error takes the request down".

★ **Getting bytes to OpenCV.** ``cv2.VideoCapture`` needs a filesystem PATH, but
``ObjectStorage`` is backend-agnostic. On the default local backend we hand cv2 the real
path (no copy); on any other backend we stream the object to a temp file. Feature-detected
via ``local_path`` — never assumed — so no storage-backend knowledge leaks past here.
"""

from __future__ import annotations

import logging
import os
import threading
from collections import OrderedDict
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterable, Iterator, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import (
    UnsupportedVideoFormat,
    VideoFrameUnavailable,
    VideoNotFound,
    ValidationError,
)
from app.core.pagination import PaginationParams, SortParams
from app.core.queue import JobQueue, NullJobQueue
from app.db.repositories.videos import VideoRepository
from app.models.video import Video
from app.services import frame_extraction
from app.services.image_service import ImageService, UploadResult
from app.storage import keys
from app.storage.base import CHUNK_SIZE, ObjectStorage

__all__ = ["VideoService"]

logger = logging.getLogger(__name__)

#: Rendered scrub-preview JPEGs, ``(video_id, 0.1s bucket) -> bytes``. See
#: ``get_frame_preview`` — bounded, immutable-keyed, shared across requests.
_PREVIEW_CACHE: OrderedDict[tuple[str, int], bytes] = OrderedDict()
_PREVIEW_CACHE_LOCK = threading.Lock()
_PREVIEW_CACHE_MAX = 64


class VideoService:
    """Upload orchestration, reads, lifecycle and frame extraction for field videos.

    Args:
        session: The request's session (transaction boundary).
        settings: Backend settings — upload limits, the video MIME allow-list.
        storage: Where the original bytes live. Injected; synchronous by design.
        queue: Passed through to :class:`ImageService` so a captured frame enqueues the
            same ``ingest`` enrichment a normal upload does.
    """

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        storage: ObjectStorage,
        queue: JobQueue | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._videos = VideoRepository(session)
        self._storage = storage
        self._queue = queue if queue is not None else NullJobQueue()
        self._images = ImageService(session, settings, storage=storage, queue=self._queue)

    # ── reads ──────────────────────────────────────────────────────────────────

    async def get(self, video_id: uuid.UUID, *, include_deleted: bool = False) -> Video:
        video = (
            await self._videos.get(video_id)
            if include_deleted
            else await self._videos.get_active(video_id)
        )
        if video is None:
            raise VideoNotFound(f"No video {video_id}.")
        return video

    async def list(
        self,
        *,
        pagination: PaginationParams,
        sort: SortParams,
        project_id: uuid.UUID | None = None,
        q: str | None = None,
        include_deleted: bool = False,
    ) -> tuple[Sequence[Video], int]:
        return await self._videos.list_videos(
            pagination=pagination,
            sort=sort,
            project_id=project_id,
            q=q,
            include_deleted=include_deleted,
        )

    # ── upload ─────────────────────────────────────────────────────────────────

    async def upload(
        self,
        *,
        project_id: uuid.UUID | None,
        filename: str,
        content_type: str | None,
        data: bytes | BinaryIO | Iterable[bytes],
    ) -> Video:
        """Store the video, read its metadata with OpenCV, and insert the row.

        Args:
            project_id: The project the video belongs to — or ``None`` for a clip that
                lives in the library only (detection / drift work).
            filename: The client's filename (sanitised into the storage key).
            content_type: The client-declared MIME — checked against the video allow-list.
            data: The upload bytes or stream. Streamed to storage, never fully buffered.

        Returns:
            The created :class:`Video`.

        Raises:
            UnsupportedVideoFormat: the declared type is outside the allow-list, or the
                stored file could not be opened/probed by OpenCV.
        """
        self._check_declared_type(content_type)

        video_id = uuid.uuid4()
        safe_name = keys.safe_filename(filename)
        key = keys.video_original_key(project_id, video_id, safe_name)
        stored = self._storage.put(key, data, content_type=content_type)

        # ★ Metadata is read synchronously here (see the module note on L5): the columns
        # are NOT NULL, the browser player needs duration/dimensions the instant the
        # upload returns, and a bad container must fail the upload rather than leave a
        # half-formed row. This decodes no frames — only header/index metadata.
        try:
            with self._local_file(key) as path:
                meta = frame_extraction.read_metadata(path)
        except frame_extraction.FrameExtractionError as exc:
            self._storage.delete(key)
            raise UnsupportedVideoFormat(
                "the uploaded file could not be read as a video; OpenCV's FFMPEG backend "
                "could not open or probe it."
            ) from exc

        video = Video(
            id=video_id,
            project_id=project_id,
            filename=safe_name,
            mime_type=content_type or "application/octet-stream",
            storage_path=key,
            checksum_sha256=stored.checksum_sha256,
            size_bytes=stored.size_bytes,
            duration_s=meta.duration_s,
            fps=meta.fps,
            width=meta.width,
            height=meta.height,
            frame_count=meta.frame_count,
            codec=meta.codec,
        )
        await self._videos.insert(video)

        # ★ HEVC (every recent drone default) cannot play in a browser. Fire the
        #   H.264 preview derivation now — fire-and-forget, no job row: the player
        #   polls `preview_available` and keeps its server-rendered scrub fallback
        #   until the artefact exists. An H.264 upload skips this entirely.
        from app.tasks.transcoding import TASK_TRANSCODE_PREVIEW, needs_preview

        if needs_preview(video.codec):
            self._queue.dispatch(TASK_TRANSCODE_PREVIEW, str(video.id))
        return video

    # ── preview (browser-playable H.264 derivation) ────────────────────────────

    def preview_key(self, video: Video) -> str:
        """The storage key the transcode task writes to."""
        return keys.video_preview_key(video.project_id, video.id)

    def preview_available(self, video: Video) -> bool:
        """Existence IS the signal — see ``app.tasks.transcoding``."""
        return self._storage.exists(self.preview_key(video))

    # ── frames ─────────────────────────────────────────────────────────────────

    def get_frame_preview(self, video: Video, t_seconds: float) -> bytes:
        """Decode the frame at ``t_seconds`` and return JPEG bytes. Creates no image.

        For the scrub-preview fallback and thumbnails. A throwaway render — nothing is
        stored, nothing is inserted.

        ★ SERVED THROUGH A SMALL PROCESS-WIDE LRU, keyed ``(video id, 0.1 s bucket)``.
        Every preview is a full open+seek+decode of the source file — seconds of work
        against a multi-hundred-MB drone video — and the find-the-good-frame workflow is
        BACK-AND-FORTH over the same few seconds of footage. The step back to a frame
        already seen is the single most common request this endpoint gets, and it is the
        one a cache answers for free. The bucket matches the client's own 0.1 s rounding,
        so cache keys and request URLs agree by construction. Bounded (64 frames, a few
        MB of JPEG) and keyed by immutable content: a video's bytes never change under an
        id, so entries cannot go stale, only cold.

        Raises:
            VideoFrameUnavailable: the timestamp is out of range or unreadable (422).
        """
        key = (str(video.id), int(round(t_seconds * 10)))
        with _PREVIEW_CACHE_LOCK:
            cached = _PREVIEW_CACHE.get(key)
            if cached is not None:
                _PREVIEW_CACHE.move_to_end(key)
                return cached

        try:
            with self._local_file(video.storage_path) as path:
                frame = frame_extraction.extract_frame(path, t_seconds)
        except frame_extraction.FrameExtractionError as exc:
            raise VideoFrameUnavailable(
                f"could not extract a frame at t={t_seconds}s from video {video.id}."
            ) from exc

        with _PREVIEW_CACHE_LOCK:
            _PREVIEW_CACHE[key] = frame.jpeg_bytes
            _PREVIEW_CACHE.move_to_end(key)
            while len(_PREVIEW_CACHE) > _PREVIEW_CACHE_MAX:
                _PREVIEW_CACHE.popitem(last=False)
        return frame.jpeg_bytes

    async def capture_frame(
        self,
        video: Video,
        *,
        t_seconds: float,
        code: str | None = None,
        filename: str | None = None,
        owner_id: str | None = None,
        project_id: uuid.UUID | None = None,
    ) -> UploadResult:
        """Extract the frame at ``t_seconds`` and CREATE A REAL ``images`` row from it.

        ★ This is "capture this frame". The decoded JPEG becomes a normal image — with
        ``source_video_id`` / ``source_video_time_s`` set — through
        :meth:`ImageService.create_captured_frame`, so from here it is indistinguishable
        from an uploaded photo to the annotation/GCP/workspace flow. The dimensions come
        from the extractor, not a re-probe.

        Raises:
            VideoFrameUnavailable: the timestamp is out of range or unreadable (422).
            ValidationError: the clip has no project and none was given — a photograph
                must belong to a project.
        """
        # ★ A project-less clip (0018) asks for its project at capture time; an explicit
        #   choice also wins over the clip's own project when both are given.
        target_project = project_id if project_id is not None else video.project_id
        if target_project is None:
            raise ValidationError(
                "this video belongs to no project — choose the project the captured "
                "photograph should go to (`project_id`)."
            )
        try:
            with self._local_file(video.storage_path) as path:
                frame = frame_extraction.extract_frame(path, t_seconds)
        except frame_extraction.FrameExtractionError as exc:
            raise VideoFrameUnavailable(
                f"could not extract a frame at t={t_seconds}s from video {video.id}."
            ) from exc

        # ★ The surveyor's name wins when given; blank/None falls back to the default
        #   ``{video-stem}_t{seconds}.jpg`` (:g trims trailing zeros — 1.5 not 1.500000).
        #   A given name without an extension gains ``.jpg``: the bytes ARE a JPEG, and
        #   an extensionless photo confuses every downstream export.
        given = (filename or "").strip()
        if given:
            capture_name = given if PurePosixPath(given).suffix else f"{given}.jpg"
        else:
            stem = PurePosixPath(video.filename).stem or "frame"
            capture_name = f"{stem}_t{t_seconds:g}.jpg"

        result = await self._images.create_captured_frame(
            project_id=target_project,
            jpeg=frame.jpeg_bytes,
            width=frame.width,
            height=frame.height,
            filename=capture_name,
            source_video_id=video.id,
            source_video_time_s=t_seconds,
            code=code,
            owner_id=owner_id,
        )
        self._export_local_copy(capture_name, frame.jpeg_bytes)
        return result

    def _export_local_copy(self, filename: str, jpeg: bytes) -> None:
        """Also drop the capture into the surveyor's own folder, best-effort.

        ★ WHY: a captured frame often serves SEVERAL projects (the same calibration
        photo pair, the same landmark from one flight), and the only copy used to
        live inside the app's storage tree under a UUID path nobody should have to
        excavate. A plain file in ``~/Pictures/LandExplorer`` can be re-uploaded into
        any project — or opened in anything else.

        ★ BEST-EFFORT, LOUD IN THE LOG, SILENT ON THE WIRE: the image row is the
        work product and is already committed; a full disk or a read-only home
        directory must not turn a successful capture into a 500.
        """
        export_dir = getattr(self._settings, "capture_export_dir", None)
        if not export_dir:
            return
        try:
            root = Path(export_dir).expanduser()
            root.mkdir(parents=True, exist_ok=True)
            target = root / filename
            # Never overwrite: the same name from another project is another photo.
            stem, suffix = target.stem, target.suffix
            counter = 2
            while target.exists():
                target = root / f"{stem}-{counter}{suffix}"
                counter += 1
            target.write_bytes(jpeg)
            logger.info("capture exported to %s", target)
        except OSError:
            logger.warning("could not export capture %r to %s", filename, export_dir, exc_info=True)

    # ── lifecycle ──────────────────────────────────────────────────────────────

    async def soft_delete(self, video_id: uuid.UUID) -> bool:
        await self.get(video_id)  # 404 if absent
        return await self._videos.soft_delete(video_id)

    # ── internals ──────────────────────────────────────────────────────────────

    @contextmanager
    def _local_file(self, key: str) -> Iterator[str]:
        """Yield a filesystem path OpenCV can open for the stored object.

        Fast path: the local backend exposes ``local_path`` — hand cv2 the real file, no
        copy. Any other backend (S3): stream the object to a temp file and clean it up.
        Feature-detected, never assumed — a service must not carry a storage-backend
        ``if``.
        """
        local_path = getattr(self._storage, "local_path", None)
        if callable(local_path):
            yield str(local_path(key))
            return

        fd, tmp_name = tempfile.mkstemp(prefix="le_video_", suffix=".bin")
        try:
            with os.fdopen(fd, "wb") as out, self._storage.open(key) as src:
                shutil.copyfileobj(src, out, length=CHUNK_SIZE)
            yield tmp_name
        finally:
            try:
                os.unlink(tmp_name)
            except OSError:  # pragma: no cover — best-effort temp cleanup
                pass

    def _check_declared_type(self, content_type: str | None) -> None:
        """Reject an obviously-wrong declared MIME early against the video allow-list."""
        if content_type is None:
            return
        allowed = set(self._settings.upload_allowed_video_mime)
        base = content_type.split(";", 1)[0].strip().lower()
        if base and base not in allowed:
            raise UnsupportedVideoFormat(
                f"content type {base!r} is not an accepted video format; allowed: "
                f"{', '.join(sorted(allowed))}."
            )
