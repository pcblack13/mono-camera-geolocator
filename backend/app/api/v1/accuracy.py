"""``/accuracy/*`` — measure a photograph's real geolocation error, then correct it.

★ THE ROUTER OWNS THE FETCHES, THE SERVICE OWNS THE STAGES — the same split as
``/lut/*``. Everything a run needs is read here through the deps every other route uses
(the image, its entered camera, its committed GCPs, the DEM that answers for it, the
imagery service) and handed over as plain data; ``app.services.accuracy_service`` stays
framework-free and ``app.vendor.geo_accuracy`` stays untouched.

★ 422s NAME THE FIX — "no intrinsics", "fewer than four GCPs", "no DEM", "that provider
may not have its tiles stored". A run that cannot succeed is refused before its thread
starts, not discovered as a stack trace two minutes in.

★ THE DEM IS RESOLVED BY ``DemService.elevation_dem_path``, the one rule that says which
surface answers for a photograph. The accuracy check must measure against exactly the
surface Auto GCP raycasts, or it would be grading a different answer than the one the
surveyor sees.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.api.presenters import to_image_camera_read
from app.core.config import Settings
from app.core.pagination import MAX_LIMIT, PaginationParams, SortKey, SortParams
from app.api.deps import as_lonlat
from app.schemas.accuracy import (
    AccuracyRunStatus,
    AccuracyState,
    AdoptionRead,
    AdoptRequest,
    HeatmapVersion,
    CorrectRequest,
    MeasureRequest,
    PixelQueryRead,
    PixelQueryRequest,
    SolveOptionsRead,
    SolveOptionsRequest,
    SuggestRequest,
)
from app.schemas.gcp import GCP_SORT_FIELDS
from app.services import accuracy_service
from app.services.dem_service import DemService
from app.services.image_camera_service import ImageCameraService
from app.services.imagery_service import ImageryService
from app.storage.base import ObjectStorage

router = APIRouter(prefix="/accuracy", tags=["accuracy"])


def _to_status(run: accuracy_service.AccuracyRun) -> AccuracyRunStatus:
    return AccuracyRunStatus(
        run_id=run.run_id,
        kind=run.kind,
        image_id=run.image_id,
        project_id=run.project_id,
        status=run.status,
        progress_pct=run.progress_pct,
        message=run.message,
        started_at=run.started_at,
        finished_at=run.finished_at,
        error=run.error,
        summary=run.summary,
    )


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


async def _pose_inputs(
    image_id: UUID,
    *,
    db: AsyncSession,
    settings: Settings,
    dem_service: DemService,
    storage: ObjectStorage,
) -> accuracy_service.PoseInputs:
    """Gather one photograph's pose ingredients — the shared front half of every route."""
    image = await deps.get_image(image_id, db=db)

    try:
        camera_row = await ImageCameraService(db).get(image.id)
    except Exception as exc:  # the service 404s a missing camera — say what to do instead
        raise _unprocessable(
            "the photograph has no entered camera — fill in its setup page first "
            "(intrinsics and the camera's position are what the pose is solved from)."
        ) from exc
    # ★ The WIRE model, not the ORM row: `position` is a PostGIS geometry, and the
    #   presenter is the one place that turns it into lat/lon.
    camera = to_image_camera_read(camera_row, image_id=image.id)
    if camera.lat is None or camera.lon is None:
        raise _unprocessable(
            "the photograph's camera has no position — set its latitude/longitude on "
            "the image setup page."
        )
    # ★ NO-CALIBRATION MODE IS A COMPLETE STATION (2026-09-09): fx/fy are absent on
    #   purpose and the focal is solved from the points — the same rule the LUT
    #   build, auto-GCP picking and the drift freeze already follow. Only a
    #   calibrated station with holes in it is refused.
    no_calibration = bool(getattr(camera, "no_calibration", False))
    missing = (
        []
        if no_calibration
        else [n for n in ("fx", "fy", "cx", "cy") if getattr(camera, n) is None]
    )
    if missing:
        raise _unprocessable(
            f"the photograph's camera has no intrinsics ({', '.join(missing)} unset) — "
            "fill them in on its setup page, or switch on no-calibration mode there."
        )

    # ★ MAX_LIMIT, not a number typed here. `PaginationParams` REJECTS anything above
    #   it in __post_init__ — a hand-written 500 raised ValueError before any of this
    #   ran, which the API could only report as "an unexpected error occurred". Reading
    #   the shared bound means this cannot drift from it again.
    rows, total = await deps.list_gcps_for_image(
        db,
        image.id,
        pagination=PaginationParams(limit=MAX_LIMIT, offset=0),
        sort=SortParams.parse(
            None, allowed=GCP_SORT_FIELDS, default=(SortKey("created_at"),)
        ),
    )
    points: list[accuracy_service.GcpPoint] = []
    for g in rows:
        lonlat = as_lonlat(g.geom)
        if lonlat is None:
            continue
        points.append(
            accuracy_service.GcpPoint(
                u=float(g.pixel_x), v=float(g.pixel_y),
                lat=float(lonlat[1]), lon=float(lonlat[0]),
                elevation_m=None if g.elevation_m is None else float(g.elevation_m),
            )
        )

    dem_path = dem_service.elevation_dem_path(image.project_id, image.id)
    photo_path = accuracy_service.materialise_photo(
        storage, image.storage_path, settings.accuracy_output_dir, image.id
    )

    return accuracy_service.PoseInputs(
        image_id=image.id,
        project_id=image.project_id,
        photo_path=photo_path,
        dem_path=dem_path,
        fx=camera.fx, fy=camera.fy, cx=camera.cx, cy=camera.cy,
        k1=camera.k1 or 0.0, k2=camera.k2 or 0.0,
        p1=camera.p1 or 0.0, p2=camera.p2 or 0.0, k3=camera.k3 or 0.0,
        cam_lat=camera.lat, cam_lon=camera.lon,
        cam_height_m=camera.mast_offset_m or 0.0,
        gcps=tuple(points),
        output_dir=settings.accuracy_output_dir,
        gcps_total=int(total),
        no_calibration=no_calibration,
        fov_h_deg=getattr(camera, "fov_h_deg", None),
    )


# ─────────────────────────────────────────────────────────────────────────────
# The three stages
# ─────────────────────────────────────────────────────────────────────────────


@router.post(
    "/measure",
    response_model=AccuracyRunStatus,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Stage D — measure the photograph's real error against satellite imagery",
)
async def measure(
    body: MeasureRequest,
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    dem_service: DemService = Depends(deps.get_dem_service),
    imagery: ImageryService = Depends(deps.get_imagery_service),
    storage: ObjectStorage = Depends(deps.get_storage),
    _: None = Depends(deps.require_writable),
) -> AccuracyRunStatus:
    pose = await _pose_inputs(
        body.image_id, db=db, settings=settings, dem_service=dem_service, storage=storage
    )
    provider = body.provider or imagery.default_provider_name()

    try:
        # ★ Constructing the writer is also the LICENCE CHECK: a provider whose terms
        #   forbid storing tiles is refused here, because the run writes a mosaic to
        #   disk. Same flag the tile cache gates on — not a second, softer rule.
        writer = accuracy_service.make_mosaic_writer(imagery, provider)
    except accuracy_service.AccuracyError as exc:
        raise _unprocessable(str(exc)) from exc
    except Exception as exc:  # unknown / unconfigured provider
        raise _unprocessable(
            f"the imagery provider '{provider}' is not available: {exc}"
        ) from exc

    try:
        run = accuracy_service.start_measure(
            accuracy_service.MeasureInputs(
                pose=pose,
                params=accuracy_service.StageDParams(
                    gsd=body.gsd,
                    max_range=body.max_range,
                    tile=body.tile,
                    stride=body.stride,
                    sat_zoom=body.sat_zoom,
                    mi_rescue=body.mi_rescue,
                    fine_pass=body.fine_pass,
                    max_shift=body.max_shift,
                    ecc_rescue=body.ecc_rescue,
                    tile_auto=body.tile_auto,
                    sigma_dtm=body.sigma_dtm,
                    reliability_max=body.reliability_max,
                    auto_reach=body.auto_reach,
                    cloud_mask=body.cloud_mask,
                ),
                mosaic_writer=writer,
                provider_name=provider,
            )
        )
    except accuracy_service.AccuracyError as exc:
        raise _unprocessable(str(exc)) from exc
    return _to_status(run)


@router.post(
    "/correct",
    response_model=AccuracyRunStatus,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Stages E + F — refine the pose from the measurement, then compare honestly",
)
async def correct(
    body: CorrectRequest,
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    dem_service: DemService = Depends(deps.get_dem_service),
    storage: ObjectStorage = Depends(deps.get_storage),
    _: None = Depends(deps.require_writable),
) -> AccuracyRunStatus:
    pose = await _pose_inputs(
        body.image_id, db=db, settings=settings, dem_service=dem_service, storage=storage
    )
    try:
        run = accuracy_service.start_correct(
            accuracy_service.CorrectInputs(
                pose=pose,
                use_residual_field=body.use_residual_field,
                free_focal=body.free_focal,
            )
        )
    except accuracy_service.AccuracyError as exc:
        raise _unprocessable(str(exc)) from exc
    return _to_status(run)


@router.post(
    "/suggest",
    response_model=AccuracyRunStatus,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Rank regions for the next control point",
)
async def suggest(
    body: SuggestRequest,
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    dem_service: DemService = Depends(deps.get_dem_service),
    storage: ObjectStorage = Depends(deps.get_storage),
    _: None = Depends(deps.require_writable),
) -> AccuracyRunStatus:
    pose = await _pose_inputs(
        body.image_id, db=db, settings=settings, dem_service=dem_service, storage=storage
    )
    try:
        run = accuracy_service.start_suggest(
            accuracy_service.SuggestInputs(
                pose=pose,
                count=body.count,
                criterion=body.criterion,
                box_frac=body.box_frac,
                stop_below_pct=body.stop_below_pct,
            )
        )
    except accuracy_service.AccuracyError as exc:
        raise _unprocessable(str(exc)) from exc
    return _to_status(run)


# ─────────────────────────────────────────────────────────────────────────────
# Runs and results
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/runs/{run_id}", response_model=AccuracyRunStatus, summary="One run's status")
async def get_run(run_id: str) -> AccuracyRunStatus:
    run = accuracy_service.get_run(run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no such run (runs are tracked in memory — a restart clears the "
            "list; the measurement itself stays on disk).",
        )
    return _to_status(run)


@router.get(
    "/images/{image_id}",
    response_model=AccuracyState,
    summary="Everything stored for one photograph",
)
async def get_state(
    image_id: UUID,
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
) -> AccuracyState:
    image = await deps.get_image(image_id, db=db)
    state = accuracy_service.read_state(settings.accuracy_output_dir, image.id)
    running = next(
        (r for r in accuracy_service.list_runs(image.id) if r.status in ("queued", "running")),
        None,
    )
    return AccuracyState(
        **state, active_run=_to_status(running) if running is not None else None
    )


@router.get(
    "/images/{image_id}/layers/{name}",
    summary="One rendered layer: ortho, satellite, or a stage's heat overlay",
    response_class=FileResponse,
)
async def get_layer(
    image_id: UUID,
    name: str,
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
) -> FileResponse:
    image = await deps.get_image(image_id, db=db)
    path = accuracy_service.layer_path(settings.accuracy_output_dir, image.id, name)
    if path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no '{name}' layer for this photograph — measure it first "
            f"(available: {', '.join(sorted(accuracy_service.LAYER_FILES))}).",
        )
    media = "image/png" if path.suffix == ".png" else "image/jpeg"
    return FileResponse(path, media_type=media)


@router.get(
    "/images/{image_id}/correction",
    summary="Download the correction as JSON (the interchange format)",
    response_class=FileResponse,
)
async def download_correction(
    image_id: UUID,
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
) -> FileResponse:
    image = await deps.get_image(image_id, db=db)
    path = accuracy_service.artifact_path(settings.accuracy_output_dir, image.id, "correction")
    if path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="this photograph has no correction yet — run the correction first.",
        )
    # ★ The field tool's own format (`geolocation-correction` v1), byte-for-byte: a
    #   correction written here must load in the desktop tool and vice versa.
    return FileResponse(path, filename=f"{image.id}_correction.json", media_type="application/json")


@router.get(
    "/images/{image_id}/report",
    summary="Download the self-contained interactive error map (offline HTML)",
    response_class=FileResponse,
)
async def download_report(
    image_id: UUID,
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
) -> FileResponse:
    image = await deps.get_image(image_id, db=db)
    path = accuracy_service.artifact_path(settings.accuracy_output_dir, image.id, "report")
    if path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="this photograph has no error map yet — measure it first.",
        )
    return FileResponse(path, filename=f"{image.id}_error_map.html", media_type="text/html")


@router.put(
    "/images/{image_id}/adoption",
    response_model=AdoptionRead,
    summary="Choose which stage this photograph stands on",
)
async def set_adoption(
    image_id: UUID,
    body: AdoptRequest,
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    _: None = Depends(deps.require_writable),
) -> AdoptionRead:
    image = await deps.get_image(image_id, db=db)
    try:
        record = accuracy_service.adopt(settings.accuracy_output_dir, image.id, body.stage)
    except accuracy_service.AccuracyError as exc:
        raise _unprocessable(str(exc)) from exc
    return AdoptionRead(**record)


@router.delete(
    "/images/{image_id}/adoption",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Stop standing on a correction — back to the GCP-solved pose",
)
async def clear_adoption(
    image_id: UUID,
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    _: None = Depends(deps.require_writable),
) -> Response:
    image = await deps.get_image(image_id, db=db)
    accuracy_service.clear_adoption(settings.accuracy_output_dir, image.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/images/{image_id}/history",
    response_model=list[HeatmapVersion],
    summary="Every archived measurement for this photograph, newest first",
)
async def list_history(
    image_id: UUID,
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
) -> list[HeatmapVersion]:
    image = await deps.get_image(image_id, db=db)
    return [
        HeatmapVersion(**v)
        for v in accuracy_service.list_history(settings.accuracy_output_dir, image.id)
    ]


@router.get(
    "/images/{image_id}/history/{version}/layers/{name}",
    summary="One layer as it was in an earlier measurement",
    response_class=FileResponse,
)
async def get_history_layer(
    image_id: UUID,
    version: str,
    name: str,
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
) -> FileResponse:
    image = await deps.get_image(image_id, db=db)
    path = accuracy_service.history_layer_path(
        settings.accuracy_output_dir, image.id, version, name
    )
    if path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"version '{version}' has no '{name}' layer.",
        )
    media = "image/png" if path.suffix == ".png" else "image/jpeg"
    return FileResponse(path, media_type=media)


@router.put(
    "/images/{image_id}/solve-options",
    response_model=SolveOptionsRead,
    summary="How the raw pose is solved from the control points",
)
async def set_solve_options(
    image_id: UUID,
    body: SolveOptionsRequest,
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    _: None = Depends(deps.require_writable),
) -> SolveOptionsRead:
    """★ Changing this CLEARS the stored measurement and everything built on it.

    Those numbers described a pose this flag changes; keeping them on screen beside a
    different solve would be the most quietly misleading thing this feature could do.
    """
    image = await deps.get_image(image_id, db=db)
    options = accuracy_service.set_solve_options(
        settings.accuracy_output_dir, image.id, free_focal=body.free_focal
    )
    return SolveOptionsRead(**options)


@router.post(
    "/images/{image_id}/query",
    response_model=PixelQueryRead,
    summary="One pixel, every stage's answer side by side",
)
async def query(
    image_id: UUID,
    body: PixelQueryRequest,
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    dem_service: DemService = Depends(deps.get_dem_service),
    storage: ObjectStorage = Depends(deps.get_storage),
) -> PixelQueryRead:
    pose = await _pose_inputs(
        image_id, db=db, settings=settings, dem_service=dem_service, storage=storage
    )
    try:
        answer = accuracy_service.query_pixel(
            pose, u=body.u, v=body.v, target_height_m=body.target_height_m
        )
    except accuracy_service.AccuracyError as exc:
        raise _unprocessable(str(exc)) from exc
    return PixelQueryRead(**answer)
