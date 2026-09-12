"""``/capture-library`` — the surveyor's local capture folder, browsable and importable.

Three routes, one story: LIST what the folder holds, SHOW one photo's bytes (the
picker's thumbnails), IMPORT one into a project — which routes through
:meth:`ImageService.upload`, so an imported photo is a normal upload in every way
(dedupe, ingest job, thumbnail) and importing the same file twice into one project
deduplicates instead of duplicating.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps, presenters
from app.core.config import Settings
from app.schemas.image import ImageRead
from app.services.capture_library_service import CaptureLibraryService
from app.services.image_service import ImageService
from app.storage.base import ObjectStorage

from app.core.security import Principal

router = APIRouter()


class CaptureLibraryEntryRead(BaseModel):
    filename: str
    size_bytes: int
    modified_at: str


class CaptureLibraryListRead(BaseModel):
    """★ Not a `Page`: the library is one bounded folder (500-newest cap in the
    service), and offset pagination over a directory that changes under you would
    skip or repeat files. The `folder` is shown to the user so "where do these come
    from?" answers itself."""

    folder: str | None
    items: list[CaptureLibraryEntryRead]


class CaptureImportRequest(BaseModel):
    project_id: UUID = Field(description="The project to import the photo into.")


def _prefix(request: Request) -> str:
    return f"{request.scope.get('root_path', '')}/api/v1"


@router.get(
    "/capture-library",
    response_model=CaptureLibraryListRead,
    summary="List the local capture library",
)
async def list_capture_library(
    settings: Settings = Depends(deps.get_settings),
) -> CaptureLibraryListRead:
    service = CaptureLibraryService(settings)
    root = service.root()
    return CaptureLibraryListRead(
        folder=str(root) if root else None,
        items=[
            CaptureLibraryEntryRead(
                filename=e.filename,
                size_bytes=e.size_bytes,
                modified_at=e.modified_at.isoformat(),
            )
            for e in service.list()
        ],
    )


@router.get(
    "/capture-library/{filename}",
    summary="One library photo's bytes (the picker's thumbnail/preview source)",
)
async def get_capture_library_file(
    filename: str,
    settings: Settings = Depends(deps.get_settings),
) -> Response:
    service = CaptureLibraryService(settings)
    path = service.resolve(filename)  # 404s on traversal exactly like absence
    media = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return FileResponse(path, media_type=media)


@router.post(
    "/capture-library/{filename}/import",
    response_model=ImageRead,
    status_code=status.HTTP_201_CREATED,
    summary="Import a library photo into a project",
)
async def import_capture_library_file(
    request: Request,
    filename: str,
    body: CaptureImportRequest,
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    storage: ObjectStorage = Depends(deps.get_storage),
    principal: Principal = Depends(deps.get_principal),
    _: None = Depends(deps.require_writable),
) -> ImageRead:
    images = ImageService(db, settings, storage=storage, queue=deps.get_job_queue(request))
    result = await CaptureLibraryService(settings).import_into_project(
        images,
        project_id=body.project_id,
        filename=filename,
        owner_id=None if principal.is_anonymous else principal.subject,
    )
    await db.flush()
    return presenters.to_image_read(result.image, prefix=_prefix(request))
