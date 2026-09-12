"""``image_service`` — validate · sniff · hash · store · dedupe · create · enqueue ingest.

SCOPE.md §3: image upload (JPG/PNG/TIFF/GeoTIFF), stored metadata and the viewer are BUILT
in full. This service owns the *synchronous* half of an upload — the part that must finish
before the API returns — and hands the *expensive* half (EXIF, thumbnails, overviews,
GeoTIFF georeferencing detection) to ``ingest_image_task`` through the injected
``JobQueue`` (L5 keeps CV/heavy IO off the request path; IU-20 owns the task).

★ **The checksum is computed during the write**, not after (``ObjectStorage.put`` returns
it). ``uq_images_project_checksum`` is a *partial* unique index (``WHERE deleted_at IS
NULL``), and a re-upload of a byte-identical file is a **success that returns the existing
image** (§6.2), never a 409 — so the dedupe pre-check and the storage cleanup on a
duplicate both key on that checksum.
"""

from __future__ import annotations

import io
import logging
import uuid
from typing import BinaryIO, Iterable, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import (
    CannotRescaleGeotiff,
    ImageNotFound,
    UnsupportedImageFormat,
    WorkerUnavailable,
)
from app.core.pagination import PaginationParams, SortParams
from app.core.queue import JobQueue, JobSpec, NullJobQueue
from app.db.repositories.annotations import AnnotationRepository
from app.db.repositories.gcps import GcpRepository
from app.db.repositories.images import ImageRepository
# Router-facing re-export — see the importlinter note in api/deps.py.
from app.db.repositories.images import count_points_per_image  # noqa: F401
from app.models.enums import ImageStatus, JobStatus, JobType
from app.models.image import Image
from app.models.job import AuxJob
from app.services.image_ops import dimensions_of_bytes, resize_image_bytes
from app.storage import keys
from app.storage.base import ObjectStorage, sha256_of

__all__ = ["ImageService", "UploadResult", "count_points_per_image"]

logger = logging.getLogger(__name__)


def _read_all(data: bytes | BinaryIO | Iterable[bytes]) -> bytes:
    """Materialise an upload body — ``bytes``, a file object, or a chunk iterable.

    Only the target-size upload path needs the whole body in memory (a resize cannot be
    streamed); the ordinary upload hands ``data`` straight to storage untouched.
    """
    if isinstance(data, bytes):
        return data
    read = getattr(data, "read", None)
    if callable(read):
        return read()
    return b"".join(data)


class UploadResult:
    """The outcome of an upload: the image, and whether it was a de-duplicated re-upload."""

    __slots__ = ("image", "deduplicated", "ingest_job_id")

    def __init__(self, image: Image, *, deduplicated: bool, ingest_job_id: uuid.UUID | None) -> None:
        self.image = image
        self.deduplicated = deduplicated
        self.ingest_job_id = ingest_job_id


class ImageService:
    """Upload orchestration, reads and lifecycle for photographs and GeoTIFFs.

    Args:
        session: The request's session (transaction boundary).
        settings: Backend settings — upload limits, MIME allow-list, async threshold.
        storage: Where the original bytes live. Injected; synchronous by design.
        queue: Enqueues ``ingest`` for the heavy half. ``NullJobQueue`` refuses loudly
            when no broker is configured, rather than leaving an image stuck ``processing``.
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
        self._images = ImageRepository(session)
        self._annotations = AnnotationRepository(session)
        self._gcps = GcpRepository(session)
        self._storage = storage
        self._queue = queue if queue is not None else NullJobQueue()

    # ── reads ─────────────────────────────────────────────────────────────────

    async def get(self, image_id: uuid.UUID, *, include_deleted: bool = False) -> Image:
        image = (
            await self._images.get(image_id)
            if include_deleted
            else await self._images.get_active(image_id)
        )
        if image is None:
            raise ImageNotFound(f"No image {image_id}.")
        return image

    async def list(
        self,
        *,
        pagination: PaginationParams,
        sort: SortParams,
        project_id: uuid.UUID | None = None,
        status_csv: str | None = None,
        is_geotiff: bool | None = None,
        q: str | None = None,
        include_deleted: bool = False,
    ) -> tuple[Sequence[Image], int]:
        return await self._images.list_images(
            pagination=pagination,
            sort=sort,
            project_id=project_id,
            status_csv=status_csv,
            is_geotiff=is_geotiff,
            q=q,
            include_deleted=include_deleted,
        )

    # ── rescale ───────────────────────────────────────────────────────────────

    async def rescale(self, image_id: uuid.UUID, *, width: int, height: int) -> Image:
        """Resize an already-stored photo, scaling its landmark/GCP photo-pixels with it.

        ★ **This is survey-critical and the scaling rules are exact.** For old
        ``(ow, oh)`` and new ``(nw, nh)``, ``sx = nw/ow`` and ``sy = nh/oh``:

        * the stored image bytes are resampled to ``(nw, nh)`` and the row's
          ``width``/``height``/``checksum_sha256``/``size_bytes`` follow the new bytes;
        * every LIVE annotation on the photo has ``pixel_x *= sx``, ``pixel_y *= sy`` and
          ``pixel_geom = ST_Scale(pixel_geom, sx, sy)`` — one UPDATE, in pixel space;
        * every GCP has ``pixel_x *= sx``, ``pixel_y *= sy`` — and **nothing else**. A
          GCP's ``geom`` (lat/lon) is the surveyor's map click, not a photo measurement,
          so a resize cannot move it; ``satellite_pixel_*`` and ``accuracy_*`` are in
          other spaces and are likewise untouched.

        ★ **All-or-nothing.** The three DB updates run in the request transaction, and
        the storage overwrite is issued **last**, after they have succeeded: a failure in
        any UPDATE aborts before a single byte is written, and a failure of the storage
        write raises and rolls the whole transaction back. There is no interleaving that
        leaves the bytes resized but the coordinates un-scaled, or vice versa — a partial
        rescale is a corrupt survey, and this ordering makes it unreachable.

        Args:
            image_id: The photograph to resize.
            width: Target width in pixels (schema-bounded to ``[1, 20000]``).
            height: Target height in pixels.

        Returns:
            The refreshed :class:`Image`, now at ``(width, height)``.

        Raises:
            ImageNotFound: no such live image (404).
            CannotRescaleGeotiff: the image is a GeoTIFF (422) — a resize drops its
                geotransform, so it is refused rather than silently de-georeferenced.
            ValidationError: the target is out of range or the stored bytes cannot be
                decoded/re-encoded (422, raised by the resize helper).
        """
        image = await self.get(image_id)  # 404 if absent

        # ★ A GeoTIFF's pixels are bound to ground coordinates by its geotransform;
        #   resampling would invalidate that mapping. Refuse before touching anything.
        if image.is_geotiff:
            raise CannotRescaleGeotiff(
                f"Image {image_id} is a GeoTIFF; resizing it would drop its "
                "georeferencing. Rescaling GeoTIFFs is not supported."
            )

        old_w, old_h = int(image.width), int(image.height)
        if (width, height) == (old_w, old_h):
            # Nothing to do — same size in, same image out. No re-encode, no coordinate
            # churn, no needless checksum change.
            return image

        # Resize the stored bytes in memory first. If this raises (bad target, corrupt
        # bytes) it is a clean 422 and nothing has been written or updated yet.
        original = self._storage.get(image.storage_path)
        new_bytes, new_w, new_h = resize_image_bytes(
            original, width, height, mime=image.mime_type
        )

        # ★ THE PRISTINE COPY, written once, before the first overwrite ever lands:
        #   every later rescale is derived, but this key stays the camera's own bytes,
        #   which is what makes `restore_original` a true undo instead of an upsample
        #   pretending to be one. Existence-checked so a second rescale cannot
        #   clobber the pristine copy with an already-degraded generation.
        backup_key = f"{image.storage_path}.pristine"
        if not self._storage.exists(backup_key):
            self._storage.put(backup_key, original, content_type=image.mime_type)
        sx = new_w / old_w
        sy = new_h / old_h

        # ★ DB updates FIRST, storage write LAST — see the method docstring. The checksum
        #   and size are computed from the exact bytes we are about to store, so the row
        #   is written before the storage overwrite yet describes it precisely.
        checksum, size_bytes = sha256_of([new_bytes])
        await self._images.update_dimensions(
            image_id,
            width=new_w,
            height=new_h,
            checksum_sha256=checksum,
            size_bytes=size_bytes,
        )
        await self._annotations.scale_pixels_for_image(image_id, sx, sy)
        await self._gcps.scale_pixels_for_image(image_id, sx, sy)

        # The last mutation, and the only non-transactional one: an atomic overwrite of
        # the same key. If it raises, the transaction above rolls back and the row keeps
        # its original bytes — no partial rescale survives.
        self._storage.put(image.storage_path, new_bytes, content_type=image.mime_type)

        # The Core UPDATE bypassed the ORM identity map; re-read so the returned row
        # carries the new dimensions/checksum/size rather than the cached old ones.
        return await self._images.refresh(image)

    async def restore_original(self, image_id: uuid.UUID) -> Image:
        """Undo every rescale: put the pristine camera bytes back, coordinates scaled.

        The exact inverse of :meth:`rescale`, sourced from the ``.pristine`` copy that
        the first rescale set aside — never an upsample of the degraded bytes. The
        same all-or-nothing ordering applies (DB updates first, storage write last),
        and the pixel coordinates of annotations/GCPs are scaled back by the same
        factors, so a rescale→restore round trip returns them to their original
        positions (within float precision).

        Raises:
            ImageNotFound: no such live image (404).
            ValidationError: the photo has never been rescaled (no pristine copy), or
                it is already at its original size.
        """
        image = await self.get(image_id)
        backup_key = f"{image.storage_path}.pristine"
        if not self._storage.exists(backup_key):
            raise ValidationError(
                "this photo has never been rescaled — it is already at its original "
                "resolution."
            )

        pristine = self._storage.get(backup_key)
        # Probe the pristine dimensions from the bytes themselves — the row's current
        # width/height describe the RESCALED image, and nothing else recorded the
        # original. PIL is imported here, not at module top (§11.3).
        import io

        from PIL import Image as PILImage

        with PILImage.open(io.BytesIO(pristine)) as im:
            orig_w, orig_h = im.size

        old_w, old_h = int(image.width), int(image.height)
        if (orig_w, orig_h) == (old_w, old_h):
            raise ValidationError("this photo is already at its original resolution.")

        sx = orig_w / old_w
        sy = orig_h / old_h

        checksum, size_bytes = sha256_of([pristine])
        await self._images.update_dimensions(
            image_id,
            width=orig_w,
            height=orig_h,
            checksum_sha256=checksum,
            size_bytes=size_bytes,
        )
        await self._annotations.scale_pixels_for_image(image_id, sx, sy)
        await self._gcps.scale_pixels_for_image(image_id, sx, sy)

        self._storage.put(image.storage_path, pristine, content_type=image.mime_type)
        # ★ The pristine copy is now the live copy; keeping the sibling would only
        #   let a future rescale mistake THIS generation for camera-original. Delete;
        #   the next rescale writes a fresh one from these same bytes.
        self._storage.delete(backup_key)

        return await self._images.refresh(image)

    # ── upload ────────────────────────────────────────────────────────────────

    async def upload(
        self,
        *,
        project_id: uuid.UUID,
        filename: str,
        content_type: str | None,
        data: bytes | BinaryIO | Iterable[bytes],
        owner_id: str | None = None,
        target_width: int | None = None,
        target_height: int | None = None,
    ) -> UploadResult:
        """Store, dedupe, create the row, and enqueue ingest.

        Args:
            project_id: The project the image belongs to.
            filename: The client's filename (sanitised into the storage key).
            content_type: The client-declared MIME. ★ Used only as a hint — the true type
                is sniffed by the ingest task, never trusted from the header.
            data: The upload bytes or stream. Streamed to storage, never fully buffered
                — *unless* a target size is requested, which forces a full decode.
            owner_id: The uploading principal.
            target_width: Optional requested stored width. When BOTH ``target_width`` and
                ``target_height`` are given and differ from the source's own dimensions,
                the incoming bytes are resized to that size **before** they are stored, so
                the stored file and ``images.width``/``height`` are the target. A fresh
                upload has no GCPs or annotations, so nothing needs its pixels scaled here.
            target_height: See ``target_width``. Both are required for a resize; one alone
                is ignored (an aspect-free single dimension is ambiguous).

        Returns:
            An :class:`UploadResult`. On a byte-identical re-upload of a live image the
            stored duplicate is deleted and the existing image is returned
            (``deduplicated=True``).

        Raises:
            UnsupportedImageFormat: the declared type is outside the allow-list. (The
                authoritative sniff still happens in ingest.)
        """
        self._check_declared_type(content_type)

        image_id = uuid.uuid4()
        safe_name = keys.safe_filename(filename)
        key = keys.image_original_key(project_id, image_id, safe_name)

        # ★ Target-size upload: resize the incoming bytes BEFORE storing, so the stored
        #   file *is* the target and `_probe_dimensions` reads the target back. This
        #   forces a full buffer (a resize cannot be streamed), which is why it is gated
        #   on the client actually asking for a size — the normal path stays streamed.
        if target_width is not None and target_height is not None:
            raw = _read_all(data)
            src_w, src_h = dimensions_of_bytes(raw)
            if (target_width, target_height) != (src_w, src_h):
                raw, _, _ = resize_image_bytes(
                    raw, target_width, target_height, mime=content_type
                )
            data = raw

        stored = self._storage.put(key, data, content_type=content_type)

        existing = await self._images.find_by_checksum(project_id, stored.checksum_sha256)
        if existing is not None:
            # A re-upload of a file already present. Drop the redundant copy and hand back
            # the original — a success, not a conflict (§6.2).
            self._storage.delete(key)
            return UploadResult(existing, deduplicated=True, ingest_job_id=None)

        # ★ Dimensions are read synchronously here, not deferred to ingest. `images.width`
        # / `height` are NOT NULL (§5, ck_images_dims: width > 0 AND height > 0), the
        # viewer needs them the instant the upload returns, and a manual-GCP build must be
        # usable with no Celery worker running. Reading the header decodes no pixels and is
        # explicitly within L5's EXIF/thumbnail sync budget. The richer EXIF, georeferencing
        # and thumbnail work stays in the ingest task.
        width, height = self._probe_dimensions(key)

        image = Image(
            id=image_id,
            project_id=project_id,
            filename=safe_name,
            mime_type=content_type,
            storage_path=key,
            checksum_sha256=stored.checksum_sha256,
            size_bytes=stored.size_bytes,
            status=ImageStatus.UPLOADED.value,
            width=width,
            height=height,
        )
        await self._images.insert(image)

        ingest_job_id = self._enqueue_ingest(image, owner_id=owner_id)
        return UploadResult(image, deduplicated=False, ingest_job_id=ingest_job_id)

    async def create_captured_frame(
        self,
        *,
        project_id: uuid.UUID,
        jpeg: bytes,
        width: int,
        height: int,
        filename: str,
        source_video_id: uuid.UUID,
        source_video_time_s: float,
        code: str | None = None,
        owner_id: str | None = None,
    ) -> UploadResult:
        """Store a video-captured JPEG frame as a normal ``images`` row and enqueue ingest.

        ★ **This is the "capture this frame" create path**, and it deliberately REUSES the
        upload machinery — store · dedupe-by-checksum · insert · enqueue ingest — rather
        than duplicating it. The one difference from :meth:`upload` is that the dimensions
        are **given by the frame extractor**, not re-probed: the extractor already decoded
        the exact frame and knows its size, so re-opening the JPEG to read ``.size`` would
        be pure waste. The row records ``source_video_id`` + ``source_video_time_s`` so the
        image knows it is a frame and which second it came from (the rest of the system
        neither knows nor cares — it is an ordinary photo from here on).
        """
        image_id = uuid.uuid4()
        safe_name = keys.safe_filename(filename)
        key = keys.image_original_key(project_id, image_id, safe_name)
        stored = self._storage.put(key, jpeg, content_type="image/jpeg")

        existing = await self._images.find_by_checksum(project_id, stored.checksum_sha256)
        if existing is not None:
            # A byte-identical frame already captured (same second, same video): a success
            # that returns the existing image, exactly like a re-upload (§6.2).
            self._storage.delete(key)
            return UploadResult(existing, deduplicated=True, ingest_job_id=None)

        image = Image(
            id=image_id,
            project_id=project_id,
            filename=safe_name,
            mime_type="image/jpeg",
            storage_path=key,
            checksum_sha256=stored.checksum_sha256,
            size_bytes=stored.size_bytes,
            status=ImageStatus.UPLOADED.value,
            width=width,
            height=height,
            source_video_id=source_video_id,
            source_video_time_s=source_video_time_s,
            meta={"capture_code": code} if code else {},
        )
        await self._images.insert(image)

        ingest_job_id = self._enqueue_ingest(image, owner_id=owner_id)
        return UploadResult(image, deduplicated=False, ingest_job_id=ingest_job_id)

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def soft_delete(self, image_id: uuid.UUID) -> bool:
        await self.get(image_id)  # 404 if absent
        return await self._images.soft_delete(image_id)

    async def restore(self, image_id: uuid.UUID) -> bool:
        return await self._images.restore(image_id)

    # ── internals ─────────────────────────────────────────────────────────────

    def _probe_dimensions(self, key: str) -> tuple[int, int]:
        """Read ``(width, height)`` from the stored image header — no pixel decode.

        PIL reports ``.size`` for every accepted format (JPEG/PNG/TIFF/GeoTIFF — a GeoTIFF
        is a TIFF whose geo tags PIL simply ignores) straight from the header. A file PIL
        cannot parse is a real, reportable upload failure, not a silent NULL into a NOT NULL
        column.
        """
        from PIL import Image as PILImage

        raw = self._storage.get(key)
        try:
            with PILImage.open(io.BytesIO(raw)) as im:
                width, height = im.size
        except Exception as exc:  # noqa: BLE001 — any decode failure is a bad upload
            self._storage.delete(key)
            raise UnsupportedImageFormat(
                "the uploaded file could not be read as an image; its dimensions are "
                "required and could not be determined."
            ) from exc
        if width <= 0 or height <= 0:
            self._storage.delete(key)
            raise UnsupportedImageFormat(
                f"the uploaded image reports a non-positive size ({width}x{height})."
            )
        return int(width), int(height)

    def _check_declared_type(self, content_type: str | None) -> None:
        """Reject an obviously-wrong declared MIME early. The authoritative check is the sniff."""
        if content_type is None:
            return
        allowed = set(self._settings.upload_allowed_mime)
        base = content_type.split(";", 1)[0].strip().lower()
        if base and base not in allowed:
            raise UnsupportedImageFormat(
                f"content type {base!r} is not an accepted image format; allowed: "
                f"{', '.join(sorted(allowed))}."
            )

    def _enqueue_ingest(self, image: Image, *, owner_id: str | None) -> uuid.UUID | None:
        """Create the ``ingest`` aux-job row and submit it — the composition of §11's ruling.

        The row is INSERTed first (``celery_task_id`` NULL), then submitted; the returned
        task id is written back by ``JobRepository`` in the worker path. A ``WorkerUnavailable``
        from the queue leaves the row ``pending`` for the stale-job reaper — never a silent
        drop, and — critically — **never a failed upload**.

        ★ Ingest is pure enrichment (thumbnail, EXIF prior, georeferencing detection). The
        image's dimensions — the only upload-blocking metadata — are already read
        synchronously in :meth:`upload`, so a surveyor can upload a photo and place GCPs on
        it with no worker, no broker, and no Docker running. A missing queue is therefore a
        WARNING and a pending row (L11), not a ``503`` that denies the core manual flow. The
        row is picked up whenever a worker next runs.
        """
        # The id is set explicitly (rather than left to the flush-time default) so it can
        # be carried in the JobSpec before the transaction commits — the row exists with a
        # NULL celery_task_id, which the worker path writes back.
        job = AuxJob(
            id=uuid.uuid4(),
            type=JobType.INGEST,
            status=JobStatus.PENDING,
            image_id=image.id,
            params={},
            max_attempts=self._settings.job_max_attempts,
        )
        self._session.add(job)
        spec = JobSpec(
            job_id=job.id,
            job_type=JobType.INGEST,
            payload={"image_id": str(image.id)},
            queue="io",
        )
        spec.validate()
        try:
            self._queue.submit(spec)
        except WorkerUnavailable:
            # The row stays `pending` (never rolled back) for the stale-job reaper or the
            # next worker. The upload itself succeeds — the image and its dimensions are
            # already persisted, and the manual-GCP flow needs nothing from ingest.
            logger.warning(
                "ingest.enqueue_unavailable",
                extra={"image_id": str(image.id), "job_id": str(job.id)},
            )
            return None
        return job.id
