"""``/dem-library`` — the surveyor's processed-DEM folder: list, adopt, delete.

Three routes: LIST what the folder holds (with the sidecar metadata a picker
shows), ADOPT one entry as a project's elevation source — which re-runs the real
pipeline (`DemService.process`), so adoption behaves exactly like the setup page's
own upload — and DELETE one entry from the folder, which strands nothing because
adoption always copied the bytes into the project's own storage.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field

from app.api import deps
from app.schemas.dem import DemProcessResponse
from app.services.dem_library_service import DemLibraryService
from app.services.dem_service import DemService

router = APIRouter()


class DemLibraryEntryRead(BaseModel):
    filename: str
    size_bytes: int
    modified_at: str
    source_name: str | None
    output_crs: str | None
    pixel_size_m: float | None


class DemLibraryListRead(BaseModel):
    """★ Not a `Page` — one bounded folder, same shape as the capture library."""

    folder: str | None
    items: list[DemLibraryEntryRead]


class DemAdoptRequest(BaseModel):
    project_id: UUID = Field(description="The project whose elevation source this becomes.")
    image_id: UUID | None = Field(
        default=None,
        description=(
            "Optional — adopt this DEM for ONE image instead of the whole project. That "
            "image overrides the project DEM; every other image keeps the project's."
        ),
    )


@router.get(
    "/dem-library",
    response_model=DemLibraryListRead,
    summary="List the processed-DEM library",
)
async def list_dem_library(
    dem_service: DemService = Depends(deps.get_dem_service),
) -> DemLibraryListRead:
    service = DemLibraryService(dem_service)
    root = service.root()
    return DemLibraryListRead(
        folder=str(root) if root else None,
        items=[
            DemLibraryEntryRead(
                filename=e.filename,
                size_bytes=e.size_bytes,
                modified_at=e.modified_at.isoformat(),
                source_name=e.source_name,
                output_crs=e.output_crs,
                pixel_size_m=e.pixel_size_m,
            )
            for e in service.list()
        ],
    )


@router.post(
    "/dem-library/{filename}/adopt",
    response_model=DemProcessResponse,
    summary="Adopt a library DEM as a project's elevation source",
)
async def adopt_dem_library_file(
    filename: str,
    body: DemAdoptRequest,
    dem_service: DemService = Depends(deps.get_dem_service),
    _: None = Depends(deps.require_writable),
) -> DemProcessResponse:
    return await DemLibraryService(dem_service).adopt_into_project(
        project_id=body.project_id, filename=filename, image_id=body.image_id
    )


@router.delete(
    "/dem-library/{filename}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a DEM from the library",
)
async def delete_dem_library_file(
    filename: str,
    dem_service: DemService = Depends(deps.get_dem_service),
    _: None = Depends(deps.require_writable),
) -> Response:
    # ★ Strands nothing: adoption re-processed the bytes into project storage, so no
    #   project references the library file. Absence and traversal both answer 404 —
    #   the service's containment rule, same as the capture library's.
    DemLibraryService(dem_service).delete(filename)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
