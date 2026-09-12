"""Images — endpoints 9–15.

★ SCOPE.md §3: upload, stored metadata and the viewer are BUILT in full. Uploads are
**streamed** to storage (the file part is a ``fastapi.UploadFile``, never ``read()`` into
memory), and the expensive half — EXIF, thumbnails, GeoTIFF detection — is an ``ingest`` job.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterator
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps, presenters
from app.api.etag import etag_for, if_none_match_hit
from app.core.config import Settings
from app.core.exceptions import ArtifactReadFailed, ImageNotFound, RangeNotSatisfiable
from app.core.pagination import SortKey, SortParams
from app.core.security import Principal
from app.schemas.common import Page
from app.schemas.image import (
    IMAGE_SORT_FIELDS,
    ImageMetadataRead,
    ImageRead,
    ImageRescaleRequest,
    ImageSummary,
    ImageUploadAccepted,
)
from app.services.image_service import ImageService
from app.storage.base import CHUNK_SIZE, ObjectStorage

router = APIRouter()

_DEFAULT_SORT = (SortKey("uploaded_at", descending=True),)


def _prefix(request: Request) -> str:
    return f"{request.scope.get('root_path', '')}/api/v1"


@router.post(
    "/images",
    # ★ Union, not just ImageUploadAccepted: `response_model` is validated on EVERY return
    # regardless of status code (the `responses=` map is OpenAPI docs only, not runtime
    # coercion). Two returns emit a bare ImageRead at 201 — a de-duplicated re-upload and
    # the degraded no-worker path — so both shapes must be in the declared model or FastAPI
    # raises ResponseValidationError. Their required fields are disjoint, so the smart union
    # discriminates without ambiguity.
    response_model=ImageUploadAccepted | ImageRead,
    status_code=status.HTTP_202_ACCEPTED,
    responses={201: {"model": ImageRead, "description": "De-duplicated re-upload, or ingest deferred (no worker)."}},
    summary="Upload an image",
)
async def upload_image(
    request: Request,
    response: Response,
    project_id: UUID = Form(...),
    file: UploadFile = File(...),
    filename: str | None = Form(None),
    notes: str | None = Form(None),
    captured_at: datetime | None = Form(None),
    target_width: int | None = Form(None),
    target_height: int | None = Form(None),
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    storage: ObjectStorage = Depends(deps.get_storage),
    principal: Principal = Depends(deps.get_principal),
    _: None = Depends(deps.require_writable),
):
    service = ImageService(db, settings, storage=storage, queue=deps.get_job_queue(request))
    result = await service.upload(
        project_id=project_id,
        filename=filename or file.filename or "upload",
        content_type=file.content_type,
        data=file.file,  # ★ streamed to storage, never buffered whole (unless resized)
        owner_id=None if principal.is_anonymous else principal.subject,
        target_width=target_width,
        target_height=target_height,
    )
    prefix = _prefix(request)
    image_read = presenters.to_image_read(result.image, prefix=prefix)
    # 201 + the plain image (no job to track) for a de-duplicated re-upload, AND for the
    # degraded path where no worker/broker was available: the image and its dimensions are
    # already persisted, ingest is enrichment-only, and the declared 201→ImageRead response
    # is exactly this case. Only a genuinely enqueued ingest job returns 202 + a job to poll.
    if result.deduplicated or result.ingest_job_id is None:
        response.status_code = status.HTTP_201_CREATED
        response.headers["Location"] = f"{prefix}/images/{result.image.id}"
        return image_read

    job_view = await deps.fetch_job_view(db, result.ingest_job_id)
    response.status_code = status.HTTP_202_ACCEPTED
    response.headers["Location"] = f"{prefix}/images/{result.image.id}"
    response.headers["Retry-After"] = "1"
    return ImageUploadAccepted(image=image_read, job=presenters.to_job_read(job_view))


@router.get("/images", response_model=Page[ImageSummary], summary="List images")
async def list_images(
    request: Request,
    pagination=Depends(deps.get_pagination),
    sort: str | None = Depends(deps.get_sort),
    project_id: UUID | None = Query(None),
    status_csv: str | None = Query(None, alias="status", description="CSV of ImageStatus."),
    is_geotiff: bool | None = Query(None),
    q: str | None = Query(None),
    include_deleted: bool = Query(False),
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    storage: ObjectStorage = Depends(deps.get_storage),
) -> Page[ImageSummary]:
    service = ImageService(db, settings, storage=storage)
    parsed = SortParams.parse(sort, allowed=IMAGE_SORT_FIELDS, default=_DEFAULT_SORT)
    rows, total = await service.list(
        pagination=pagination,
        sort=parsed,
        project_id=project_id,
        status_csv=status_csv,
        is_geotiff=is_geotiff,
        q=q,
        include_deleted=include_deleted,
    )
    prefix = _prefix(request)
    # ★ REAL counts, one grouped query each. The presenter DEFAULTS these to 0, and
    #   this route shipped without passing them — every image list claimed 0 GCPs and
    #   0 annotations while the editor plainly showed rows. A count that is sometimes
    #   a lie is worse than no count: the LUT page read it and refused valid builds.
    image_ids = [img.id for img in rows]
    # ★ Counted in the REPOSITORY (2026-09-02): the importlinter contract forbids
    #   this router touching app.models, and this query was the one violation.
    from app.services.image_service import count_points_per_image

    gcp_counts, annotation_counts = await count_points_per_image(db, image_ids)
    items = [
        presenters.to_image_summary(
            img,
            prefix=prefix,
            annotation_count=annotation_counts.get(img.id, 0),
            gcp_count=gcp_counts.get(img.id, 0),
        )
        for img in rows
    ]
    return Page.of(items, total, pagination)


@router.get("/images/{image_id}", response_model=ImageRead, summary="Get an image")
async def get_image(
    request: Request,
    response: Response,
    image=Depends(deps.get_image),
):
    tag = etag_for(image.updated_at.timestamp() if image.updated_at else 0, image.updated_at)
    if if_none_match_hit(request, tag):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": tag})
    response.headers["ETag"] = tag
    return presenters.to_image_read(image, prefix=_prefix(request))


@router.post("/images/{image_id}/rescale", response_model=ImageRead, summary="Rescale an image")
async def rescale_image(
    request: Request,
    image_id: UUID,
    body: ImageRescaleRequest,
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    storage: ObjectStorage = Depends(deps.get_storage),
    _: None = Depends(deps.require_writable),
) -> ImageRead:
    """Resize an already-stored photo to ``body.width`` × ``body.height``.

    ★ Landmark and GCP **photo-pixel** positions scale with the image so each marker stays
    on the same feature; every GCP's recorded lat/lon (and its satellite pixels) is left
    exactly as it was — the coordinate came from the map click, not the photo. The whole
    operation is one transaction: coordinates and bytes move together or not at all.
    """
    service = ImageService(db, settings, storage=storage)
    image = await service.rescale(image_id, width=body.width, height=body.height)
    return presenters.to_image_read(image, prefix=_prefix(request))


@router.post(
    "/images/{image_id}/rescale/restore",
    response_model=ImageRead,
    summary="Restore an image's original resolution",
)
async def restore_image_resolution(
    request: Request,
    image_id: UUID,
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    storage: ObjectStorage = Depends(deps.get_storage),
    _: None = Depends(deps.require_writable),
) -> ImageRead:
    """Undo every rescale: the pristine camera bytes come back, coordinates scale back.

    422 when the photo was never rescaled — there is nothing to restore.
    """
    service = ImageService(db, settings, storage=storage)
    image = await service.restore_original(image_id)
    return presenters.to_image_read(image, prefix=_prefix(request))


@router.get("/images/{image_id}/file", summary="Download original bytes")
async def get_image_file(
    request: Request,
    download: bool = Query(False),
    image=Depends(deps.get_image),
    storage: ObjectStorage = Depends(deps.get_storage),
) -> Response:
    return _serve_object(
        request,
        storage,
        key=image.storage_path,
        media_type=image.mime_type,
        download_name=image.filename if download else None,
    )


@router.get("/images/{image_id}/thumbnail", summary="Thumbnail")
async def get_image_thumbnail(
    request: Request,
    image=Depends(deps.get_image),
    storage: ObjectStorage = Depends(deps.get_storage),
) -> Response:
    if not image.thumbnail_path:
        raise ImageNotFound(
            f"Image {image.id} has no thumbnail yet; it may still be processing (ingest)."
        )
    return _serve_object(request, storage, key=image.thumbnail_path, media_type="image/jpeg", download_name=None)


@router.get("/images/{image_id}/metadata", response_model=ImageMetadataRead, summary="Full metadata")
async def get_image_metadata(image=Depends(deps.get_image)) -> ImageMetadataRead:
    return presenters.to_image_metadata(image, metadata_id=image.id)


@router.delete("/images/{image_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete an image")
async def delete_image(
    image_id: UUID,
    request: Request,
    hard: bool = Query(False),
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    storage: ObjectStorage = Depends(deps.get_storage),
    _: None = Depends(deps.require_writable),
) -> Response:
    if hard:
        deps.require_confirm_delete(request)
    await ImageService(db, settings, storage=storage).soft_delete(image_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── binary serving (Range) ─────────────────────────────────────────────────────


def _serve_object(
    request: Request,
    storage: ObjectStorage,
    *,
    key: str,
    media_type: str,
    download_name: str | None,
) -> Response:
    """Stream an object, honouring a single ``Range`` request → 200/206.

    L5 exemption: this is IO, not CV. It streams through ``ObjectStorage.open`` rather than
    reading the whole object into memory.
    """
    stat = storage.stat(key)
    if stat is None:
        raise ArtifactReadFailed(f"The stored object backing this resource is missing.")
    size = stat.size_bytes
    headers: dict[str, str] = {"Accept-Ranges": "bytes", "Content-Length": str(size)}
    if download_name:
        headers["Content-Disposition"] = f'attachment; filename="{download_name}"'

    range_header = request.headers.get("range")
    start, end = 0, size - 1
    status_code = status.HTTP_200_OK
    if range_header and range_header.startswith("bytes="):
        try:
            spec = range_header.split("=", 1)[1].split(",")[0]
            lo, _, hi = spec.partition("-")
            start = int(lo) if lo else 0
            end = int(hi) if hi else size - 1
        except ValueError as exc:
            raise RangeNotSatisfiable(f"Malformed Range header: {range_header!r}") from exc
        if start > end or start >= size:
            raise RangeNotSatisfiable(
                f"Requested range {start}-{end} is outside 0-{size - 1}.",
                headers={"Content-Range": f"bytes */{size}"},
            )
        end = min(end, size - 1)
        status_code = status.HTTP_206_PARTIAL_CONTENT
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        headers["Content-Length"] = str(end - start + 1)

    def body() -> Iterator[bytes]:
        remaining = end - start + 1
        with storage.open(key) as fh:
            fh.seek(start)
            while remaining > 0:
                chunk = fh.read(min(CHUNK_SIZE, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return StreamingResponse(body(), status_code=status_code, media_type=media_type, headers=headers)
