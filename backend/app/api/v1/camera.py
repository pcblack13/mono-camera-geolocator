"""The photograph's entered camera — intrinsics, position and tilt, from its setup page.

* ``GET    /images/{image_id}/camera`` — ImageCameraRead. ★ Always 200 on a live
  image: ``configured: false`` with every field null is the honest "not saved yet".
* ``PUT    /images/{image_id}/camera`` — ImageCameraRead. **Upsert, full replace,
  idempotent** — the setup page saves the whole form, and an omitted field *is* a
  cleared field.
* ``DELETE /images/{image_id}/camera`` — 204, **idempotent**.

★ This is the surveyor's ENTERED camera, one per photograph. It is not
``/images/{id}/camera-pose`` — that surface is the deferred matcher's *estimate*
(501 in this build); this one is real CRUD over what a person typed.

★ Why PUT and not PATCH: the camera is one small record typed into one form.
Replace-whole is the truth of the interaction, and it spares the client the
omitted-vs-null distinction PATCH would force on fifteen fields at once.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps, presenters
from app.core.config import Settings
from app.schemas.image_camera import (
    AutoGcpEstimateRead,
    AutoGcpEstimateRequest,
    AutoGcpProjectRead,
    AutoGcpProjectRequest,
    ImageCameraPut,
    ImageCameraRead,
)
from app.services.auto_gcp_service import AutoGcpService
from app.services.image_camera_service import ImageCameraService

router = APIRouter()


@router.get(
    "/images/{image_id}/camera",
    response_model=ImageCameraRead,
    summary="The photograph's entered camera",
)
async def get_image_camera(
    image_id: UUID,
    db: AsyncSession = Depends(deps.get_db),
) -> ImageCameraRead:
    camera = await ImageCameraService(db).get(image_id)
    return presenters.to_image_camera_read(camera, image_id=image_id)


@router.put(
    "/images/{image_id}/camera",
    response_model=ImageCameraRead,
    summary="Create or replace the photograph's entered camera (idempotent)",
)
async def put_image_camera(
    image_id: UUID,
    body: ImageCameraPut,
    db: AsyncSession = Depends(deps.get_db),
    _: None = Depends(deps.require_writable),
) -> ImageCameraRead:
    camera = await ImageCameraService(db).put(image_id, body)
    return presenters.to_image_camera_read(camera, image_id=image_id)


@router.post(
    "/images/{image_id}/camera/estimate",
    response_model=AutoGcpEstimateRead,
    summary="Estimate a pixel's world position from the photo's 4+ located GCPs",
)
async def estimate_from_pixel(
    image_id: UUID,
    body: AutoGcpEstimateRequest,
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
) -> AutoGcpEstimateRead:
    # ★ READ-ONLY computation — solves the pose from the stored correspondences and
    #   intersects the pixel's ray with the project DEM. Creates no row; the client
    #   decides whether the estimate becomes a GCP. Prerequisite failures are 422s
    #   that NAME the missing piece (camera fields, DEM, point count).
    return await AutoGcpService(db, settings).estimate(image_id, body)


@router.post(
    "/images/{image_id}/camera/project",
    response_model=AutoGcpProjectRead,
    summary="Project a world coordinate back into the photograph (the inverse)",
)
async def project_to_pixel(
    image_id: UUID,
    body: AutoGcpProjectRequest,
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
) -> AutoGcpProjectRead:
    # ★ The estimate run BACKWARDS — same solve, same prerequisites, same 422
    #   vocabulary. READ-ONLY: returns the pixel where (lat, lon) appears through
    #   the solved pose; the client decides whether to move anything. A point
    #   behind the camera or off the DEM is a 422 that says so.
    return await AutoGcpService(db, settings).project(image_id, body)


@router.delete(
    "/images/{image_id}/camera",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove the photograph's entered camera (idempotent)",
)
async def delete_image_camera(
    image_id: UUID,
    db: AsyncSession = Depends(deps.get_db),
    _: None = Depends(deps.require_writable),
) -> Response:
    await ImageCameraService(db).delete(image_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
