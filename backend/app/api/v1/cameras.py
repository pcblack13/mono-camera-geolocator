"""``/cameras/*`` — the server-side camera registry (2026-09-02).

* ``GET    /cameras``                 — Page[CameraRead]
* ``GET    /cameras/all``             — every camera, unpaged (the globe wants all of them)
* ``POST   /cameras``                 — 201 CameraRead
* ``POST   /cameras/import``          — 201 CameraImportResult (browser registry / JSON)
* ``GET    /cameras/{id}``            — CameraRead
* ``GET    /cameras/{id}/export``     — the whole camera as one zip: the registry row,
                                      the frame, the control points, the DEM, the DEM
                                      calibration, the lookup table and the drift reference
* ``PATCH  /cameras/{id}``            — CameraRead
* ``PUT    /cameras/{id}/desired``    — CameraRead (what the camera SHOULD be doing)
* ``POST   /cameras/{id}/drift/freeze`` — CameraDriftRead: freeze the drift reference on
                                      the camera's frame and watch it in the background
* ``DELETE /cameras/{id}``            — 204; stops the camera's watch / run / feed first

★ ``desired`` is normally written by the detection, drift and live routers when a
start or stop carries a ``camera_id`` — the explicit PUT exists for the page's
"forget this setup" and for scripts. Read ``services/camera_service.py`` for the
intent-in / status-out rule before adding anything here that reads a thread.

★ ``/cameras/all`` and ``/cameras/import`` are registered BEFORE ``/cameras/{id}`` so
a literal segment is never parsed as a UUID (``assert_no_duplicate_routes`` proves
the two literals do not collide with anything).
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core.config import Settings
from app.core.exceptions import EmptyPatch
from app.core.pagination import SortKey, SortParams
from app.schemas.camera import (
    CAMERA_SORT_FIELDS,
    CameraCreate,
    CameraDesired,
    CameraDriftRead,
    CameraImportRequest,
    CameraImportResult,
    CameraRead,
    CameraUpdate,
    desired_from_row,
)
from app.schemas.common import Page
from app.services import camera_service, drift_service
from app.services.camera_service import CameraService

router = APIRouter(prefix="/cameras", tags=["cameras"])

_DEFAULT_SORT = (SortKey("name", descending=False),)


def to_camera_read(camera) -> CameraRead:  # noqa: ANN001 — ORM row; the module's one presenter
    return CameraRead(
        id=camera.id,
        name=camera.name,
        lat=camera.lat,
        lon=camera.lon,
        source=camera.source,
        connection=camera.connection,
        provides=camera.provides,
        data_source=camera.data_source,
        heading_deg=camera.heading_deg,
        fov_deg=camera.fov_deg,
        fps=camera.fps,
        tags=list(camera.tags or []),
        lut_site=camera.lut_site,
        project_id=camera.project_id,
        frame_image_id=camera.frame_image_id,
        calibration=camera.calibration,
        desired=desired_from_row(camera.desired),
        created_at=camera.created_at,
        updated_at=camera.updated_at,
    )


@router.get("", response_model=Page[CameraRead], summary="List cameras")
async def list_cameras(
    pagination=Depends(deps.get_pagination),
    sort: str | None = Depends(deps.get_sort),
    q: str | None = Query(None, description="Free-text over name and sources."),
    db: AsyncSession = Depends(deps.get_db),
) -> Page[CameraRead]:
    parsed = SortParams.parse(sort, allowed=CAMERA_SORT_FIELDS, default=_DEFAULT_SORT)
    rows, total = await CameraService(db).list(pagination=pagination, sort=parsed, q=q)
    return Page.of([to_camera_read(c) for c in rows], total, pagination)


@router.get("/all", response_model=list[CameraRead], summary="Every camera, by name")
async def list_all_cameras(db: AsyncSession = Depends(deps.get_db)) -> list[CameraRead]:
    """★ The one unpaged list: the globe draws EVERY camera at once and a site has
    tens of them, not thousands. A registry that grows past that gets a real page."""
    return [to_camera_read(c) for c in await CameraService(db).all()]


@router.post(
    "",
    response_model=CameraRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a camera",
)
async def create_camera(
    body: CameraCreate,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(deps.get_db),
    _: None = Depends(deps.require_writable),
) -> CameraRead:
    camera = await CameraService(db).create(body)
    response.headers["Location"] = f"{request.scope.get('root_path', '')}/api/v1/cameras/{camera.id}"
    return to_camera_read(camera)


@router.post(
    "/import",
    response_model=CameraImportResult,
    status_code=status.HTTP_201_CREATED,
    summary="Import cameras (a browser registry, or a JSON export)",
)
async def import_cameras(
    body: CameraImportRequest,
    db: AsyncSession = Depends(deps.get_db),
    _: None = Depends(deps.require_writable),
) -> CameraImportResult:
    """★ All or nothing, and the result maps every ``client_id`` to its server UUID
    so the browser can re-key its per-camera settings once, on migration."""
    return await CameraService(db).import_many(body)


@router.get("/{camera_id}", response_model=CameraRead, summary="Get a camera")
async def get_camera(camera_id: UUID, db: AsyncSession = Depends(deps.get_db)) -> CameraRead:
    return to_camera_read(await CameraService(db).get(camera_id))


@router.patch("/{camera_id}", response_model=CameraRead, summary="Update a camera")
async def update_camera(
    camera_id: UUID,
    body: CameraUpdate,
    db: AsyncSession = Depends(deps.get_db),
    _: None = Depends(deps.require_writable),
) -> CameraRead:
    if body.is_empty():
        raise EmptyPatch("The PATCH body is empty; send at least one field to change.")
    return to_camera_read(await CameraService(db).update(camera_id, body))


@router.put(
    "/{camera_id}/desired",
    response_model=CameraRead,
    summary="Set what this camera should be doing (restored at boot)",
)
async def set_camera_desired(
    camera_id: UUID,
    body: CameraDesired,
    db: AsyncSession = Depends(deps.get_db),
    _: None = Depends(deps.require_writable),
) -> CameraRead:
    """★ Intent only. Setting ``watch`` here does not start a watch NOW — the drift
    router does that (and records intent as a side effect). This is the explicit
    door: clear a stale intent, or pre-register one for the next boot."""
    return to_camera_read(await CameraService(db).set_desired(camera_id, body))


@router.post(
    "/{camera_id}/drift/freeze",
    response_model=CameraDriftRead,
    status_code=status.HTTP_201_CREATED,
    summary="Freeze the drift reference on the camera's frame and watch it in the background",
)
async def freeze_camera_drift(
    camera_id: UUID,
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    _: None = Depends(deps.require_writable),
) -> CameraDriftRead:
    """★ THE FRAME WITH THE CONTROL POINTS IS THE FROZEN FRAME (2026-09-08). The
    camera settings call this when the lookup table is built and whenever a new
    frame is chosen; the monitoring page only reads the verdict. The watch it
    starts is recorded as the camera's desired state, so it survives a restart.
    """
    from app.api.v1.drift import resolve_image_frame  # noqa: PLC0415 — sibling router's resolver

    service = CameraService(db)
    camera = await service.get(camera_id)
    image_path = image_label = None
    if camera.frame_image_id is not None:
        image_path, image_label = await resolve_image_frame(camera.frame_image_id, db, settings)
    previous = desired_from_row(camera.desired).watch
    try:
        outcome = await run_in_threadpool(
            camera_service.refreeze_drift_watch,
            settings,
            camera_id=str(camera.id),
            name=camera.name,
            source=camera.source or "",
            lut_site=camera.lut_site,
            image_path=image_path,
            image_label=image_label,
            fov_deg=camera.fov_deg,
            previous_ref_id=previous.ref_id if previous is not None else None,
        )
    except drift_service.DriftError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    await service.record_watch(
        camera.id, {"ref_id": outcome["ref_id"], "interval_s": outcome["interval_s"]}
    )
    return CameraDriftRead(**outcome)


@router.get(
    "/{camera_id}/export",
    summary="The whole camera as one zip — settings, frame, GCPs, DEM, calibration, LUT, drift",
)
async def export_camera(
    camera_id: UUID,
    background: BackgroundTasks,
    settings: Settings = Depends(deps.get_settings),
) -> Response:
    """Everything this camera IS, in one downloadable folder.

    ★ A PARTIAL CAMERA STILL EXPORTS. Setup is eight steps and an operator may be
      on step three; every step not done yet is named in the bundle's
      ``camera.json`` under ``missing`` rather than refusing the download. What
      comes back is always a true account of how far this camera got.
    """
    from app.services import camera_export_service

    try:
        path, filename = await run_in_threadpool(
            camera_export_service.export_camera, str(camera_id), settings
        )
    except camera_export_service.CameraExportError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    # The zip is a temporary file; it goes once the response has been sent.
    background.add_task(lambda: Path(path).unlink(missing_ok=True))
    return FileResponse(
        path,
        media_type="application/zip",
        filename=filename,
        background=background,
        headers={"Cache-Control": "no-store"},
    )


@router.delete(
    "/{camera_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a camera (its detection records stay)",
)
async def delete_camera(
    camera_id: UUID,
    db: AsyncSession = Depends(deps.get_db),
    _: None = Depends(deps.require_writable),
) -> Response:
    await CameraService(db).delete(camera_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
