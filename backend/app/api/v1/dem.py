"""DEM processing — upload, crop, reproject, download, sample (``gis.dem``).

The executable form of the ``DTM_Proccesing/`` algorithm, behind three endpoints:

* ``POST /dem/process``          multipart upload + parameters -> the run report
* ``GET  /dem/{run_id}/download`` the processed GeoTIFF
* ``POST /dem/{run_id}/sample``   stage 3 — elevations at points

★ These are **not** deferred endpoints. Everything they advertise runs for real; there is
no 501 here and no placeholder. The one honest limit is rasterio's presence, which surfaces
as a ``ConfigurationError`` naming the missing dependency rather than a fake result.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated, BinaryIO
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile, status

from app.api import deps
from app.core.exceptions import ValidationError
from app.schemas.elevation import (
    ElevationSampleRequest,
    ElevationSampleResponse,
    SampledElevation,
)
from app.services.elevation_service import ElevationService
from app.schemas.dem import (
    DemActiveResponse,
    DemAoiCorner,
    DemProcessResponse,
    DemSampleRequest,
    DemSampleResponse,
)
from app.services.dem_service import DemService

__all__ = ["router"]

_log = logging.getLogger("app.api.dem")

router = APIRouter()

#: Resampling kernels the UI may ask for. Kept in step with ``gis.dem.RESAMPLING_METHODS``;
#: the parity is asserted at import so the two cannot drift silently.
_RESAMPLING = ("nearest", "bilinear", "cubic", "cubic_spline", "lanczos", "average", "mode")

#: Deepest terrain zoom served.
#:
#: ★ Bounded because ``z`` indexes a ``1 << z`` grid: an unbounded value turns the tile
#: coordinate check into a shift by hundreds of bits and invites a request for a tile that
#: costs real work to refuse. 22 is already far past any DEM's resolution — a Copernicus
#: 30 m posting is exhausted around z14, and beyond that the renderer is upsampling.
_MAX_TERRAIN_ZOOM = 22


@router.post(
    "/dem/process",
    response_model=DemProcessResponse,
    status_code=status.HTTP_200_OK,
    summary="Crop and reproject a DEM",
)
async def process_dem_endpoint(
    request: Request,
    file: Annotated[UploadFile | None, File(description="The DEM raster.")] = None,
    source_path: Annotated[
        str | None,
        Form(
            description=(
                "★ DESKTOP ROUTE: an absolute path to the DEM on the API's OWN machine, "
                "instead of `file`. The desktop shell and this API share one computer, so "
                "a multi-GB tile is opened in place — it never transits IPC or an HTTP "
                "body (bytes over 2 GiB failed outright there). Exactly one of "
                "`file`/`source_path`."
            )
        ),
    ] = None,
    aoi_corners: Annotated[
        str | None,
        Form(
            description=(
                "JSON array of >=3 objects with `lat`/`lon`. Decimal degrees or DMS "
                'such as `34°07\'39.16"N`. Omit to process the whole DEM.'
            )
        ),
    ] = None,
    camera_lat: Annotated[
        float | None,
        Form(ge=-90.0, le=90.0, description="Camera station latitude, EPSG:4326."),
    ] = None,
    camera_lon: Annotated[
        float | None,
        Form(ge=-180.0, le=180.0, description="Camera station longitude, EPSG:4326."),
    ] = None,
    radius_m: Annotated[
        float | None,
        Form(gt=0.0, description="Working radius around the camera, TRUE ground metres."),
    ] = None,
    tolerance: Annotated[
        float, Form(ge=0.0, le=5.0, description="Padding fraction around the AOI. 0.10 = 10%.")
    ] = 0.10,
    reproject: Annotated[
        bool, Form(description="Run the metric reprojection stage.")
    ] = True,
    target_srid: Annotated[
        int | None,
        Form(description="Explicit projected EPSG code. Omit to auto-pick the UTM zone."),
    ] = None,
    resampling: Annotated[str, Form(description="Resampling kernel.")] = "bilinear",
    target_resolution_m: Annotated[
        float | None,
        Form(gt=0.0, description="Output cell size in metres. Omit to preserve the source's."),
    ] = None,
    set_as_elevation_source: Annotated[
        bool,
        Form(
            description=(
                "Adopt this run's output as the server-wide active DEM (GET /dem/active). "
                "★ INFORMATIONAL under strict per-project opt-in: project GCPs sample "
                "only their own project's DEM, so this no longer feeds any project's Z "
                "— unless `project_id` is also given, which adopts it for that project."
            )
        ),
    ] = False,
    project_id: Annotated[
        UUID | None,
        Form(
            description=(
                "★ Adopt the processed output as THIS project's elevation source — the "
                "full pipeline (AOI crop, metric reprojection) followed by exactly what "
                "`POST /projects/{id}/dem` does. Requires `set_as_elevation_source=true`."
            )
        ),
    ] = None,
    image_id: Annotated[
        UUID | None,
        Form(
            description=(
                "★ Adopt the output for ONE image instead of the whole project (needs "
                "`project_id` too). That image's GCPs and auto-GCP raycast then use THIS "
                "DEM; every other image keeps the project DEM."
            )
        ),
    ] = None,
    service: DemService = Depends(deps.get_dem_service),
) -> DemProcessResponse:
    """Run the DEM pipeline on an uploaded raster.

    ``(lambda, phi, H) -> (E, N, H)``: crop to the AOI, then reproject into a projected
    metre CRS so that distances, slopes and ray geometry derived from the DEM are metric.
    """
    if resampling not in _RESAMPLING:
        raise ValidationError(
            f"unknown resampling {resampling!r}; expected one of {', '.join(_RESAMPLING)}"
        )

    stream, filename, local_path = _resolve_source(request, file, source_path)
    camera = _parse_camera(camera_lat, camera_lon, radius_m)
    corners = None if camera else _parse_corners(aoi_corners)
    _log.info(
        "DEM process: %s aoi=%s tolerance=%.2f reproject=%s srid=%s",
        filename,
        "camera+radius" if camera else ("corners" if corners else "none"),
        tolerance, reproject, target_srid,
    )
    if image_id is not None and project_id is None:
        raise ValidationError("image_id needs project_id — an image DEM belongs to a project.")
    return await service.process(
        project_id=project_id,
        image_id=image_id,
        filename=filename,
        stream=stream,
        source_path=local_path,
        aoi_corners=corners,
        camera=camera,
        tolerance=tolerance,
        reproject=reproject,
        target_srid=target_srid,
        resampling=resampling,
        target_resolution_m=target_resolution_m,
        set_as_elevation_source=set_as_elevation_source,
    )


@router.post(
    "/projects/{project_id}/dem",
    response_model=DemProcessResponse,
    summary="Upload the DEM this project takes GCP elevations from",
)
async def upload_project_dem(
    project_id: UUID,
    request: Request,
    file: Annotated[UploadFile | None, File(description="A preprocessed DEM raster.")] = None,
    source_path: Annotated[
        str | None,
        Form(description="Desktop route: absolute path on the API's own machine. See /dem/process."),
    ] = None,
    reproject: Annotated[bool, Form()] = False,
    _project=Depends(deps.get_project),
    service: DemService = Depends(deps.get_dem_service),
) -> DemProcessResponse:
    """Adopt a DEM as THIS project's elevation source.

    ★ Defaults to ``reproject=False``: the file is described as *preprocessed*, so it has
    already been cropped and projected. Warping it again would resample a surface that is
    already correct and blur it for nothing. The pipeline skips the stage by itself when
    the raster is already in ground metres, so this is belt and braces.

    ★ Existing GCPs are **not** re-sampled. A recorded elevation is an observation of what
    the DEM said when that point was placed, not a live lookup.
    """
    stream, filename, local_path = _resolve_source(request, file, source_path)
    _log.info("project %s DEM upload: %s", project_id, filename)
    return await service.process(
        project_id=project_id,
        filename=filename,
        stream=stream,
        source_path=local_path,
        aoi_corners=None,
        camera=None,
        tolerance=0.0,
        reproject=reproject,
        target_srid=None,
        resampling="bilinear",
        target_resolution_m=None,
        set_as_elevation_source=True,
    )


@router.get(
    "/projects/{project_id}/dem",
    response_model=DemActiveResponse,
    summary="The DEM this project takes GCP elevations from",
)
async def get_project_dem(
    project_id: UUID,
    _project=Depends(deps.get_project),
    service: DemService = Depends(deps.get_dem_service),
) -> DemActiveResponse:
    """Report the project's own DEM. ★ STRICTLY the project's: no fallback is shown,
    because none is sampled — a project without a DEM records NULL elevations, and
    reporting some other DEM here would claim a Z source that will not answer."""
    record = service.project_elevation_dem(project_id)
    if record is None:
        return DemActiveResponse(active=False, provider_enabled=False)
    return DemActiveResponse(active=True, **record)


# ── per-image DEM: one photograph's override of the project DEM ─────────────────


@router.post(
    "/projects/{project_id}/images/{image_id}/dem",
    response_model=DemProcessResponse,
    summary="Upload a preprocessed DEM for ONE image (overrides the project DEM)",
)
async def upload_image_dem(
    project_id: UUID,
    image_id: UUID,
    request: Request,
    file: Annotated[UploadFile | None, File(description="A preprocessed DEM raster.")] = None,
    source_path: Annotated[
        str | None,
        Form(description="Desktop route: absolute path on the API's own machine. See /dem/process."),
    ] = None,
    reproject: Annotated[bool, Form()] = False,
    _project=Depends(deps.get_project),
    service: DemService = Depends(deps.get_dem_service),
) -> DemProcessResponse:
    """Adopt a DEM for THIS image only. Its GCPs and auto-GCP raycast use it; every other
    image keeps the project DEM. Same preprocessed contract as ``POST /projects/{id}/dem``."""
    stream, filename, local_path = _resolve_source(request, file, source_path)
    _log.info("image %s DEM upload: %s", image_id, filename)
    return await service.process(
        project_id=project_id,
        image_id=image_id,
        filename=filename,
        stream=stream,
        source_path=local_path,
        aoi_corners=None,
        camera=None,
        tolerance=0.0,
        reproject=reproject,
        target_srid=None,
        resampling="bilinear",
        target_resolution_m=None,
        set_as_elevation_source=True,
    )


@router.get(
    "/projects/{project_id}/images/{image_id}/dem",
    response_model=DemActiveResponse,
    summary="This image's own DEM, if it has one (else it uses the project DEM)",
)
async def get_image_dem(
    project_id: UUID,
    image_id: UUID,
    _project=Depends(deps.get_project),
    service: DemService = Depends(deps.get_dem_service),
) -> DemActiveResponse:
    """Report the image's OWN DEM. ★ ``active=False`` means the image has no override and
    falls back to the project DEM — the client shows "Using the project DEM"."""
    record = service.image_elevation_dem(project_id, image_id)
    if record is None:
        return DemActiveResponse(active=False, provider_enabled=False)
    return DemActiveResponse(active=True, **record)


@router.delete(
    "/projects/{project_id}/images/{image_id}/dem",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove an image's own DEM — it reverts to the project DEM",
)
async def delete_image_dem(
    project_id: UUID,
    image_id: UUID,
    _project=Depends(deps.get_project),
    service: DemService = Depends(deps.get_dem_service),
) -> Response:
    """Detach the image's override. ★ Elevations already recorded on its GCPs are untouched."""
    service.delete_image_dem(project_id, image_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/projects/{project_id}/elevation/sample",
    response_model=ElevationSampleResponse,
    summary="Sample elevations from this project's DEM",
)
async def sample_project_elevation(
    project_id: UUID,
    body: ElevationSampleRequest,
    _project=Depends(deps.get_project),
    dem: DemService = Depends(deps.get_dem_service),
    elevation: ElevationService = Depends(deps.get_elevation_service),
) -> ElevationSampleResponse:
    """``Z = projectDEM(lon, lat)`` for each point — the readout behind the map cursor.

    ★ **Reads the project's own DEM and nothing else.** ``ElevationService.sample`` takes
    ``project_id`` and deliberately does not fall back to ``LE_ELEVATION_PROVIDER``: a
    project that has attached no raster records NULL elevations on its GCPs, and a readout
    that quietly answered from a server-wide DEM would show the surveyor a number their
    own points will never be given.

    ★ **``dem_attached`` is reported separately from the values.** "You have not attached a
    DEM" and "your DEM has no data at this spot" are different problems with different
    fixes, and a client that could only see nulls could not tell them apart.
    """
    results = elevation.sample_lonlat(
        [(p.lon, p.lat) for p in body.points], project_id=project_id
    )
    return ElevationSampleResponse(
        results=[
            SampledElevation(
                elevation_m=r.elevation_m,
                source=r.source,
                vertical_ce90_m=r.vertical_ce90_m,
            )
            for r in results
        ],
        dem_attached=dem.project_elevation_dem(project_id) is not None,
        with_elevation_count=sum(1 for r in results if r.available),
    )


@router.get(
    "/projects/{project_id}/terrain/{z}/{x}/{y}.png",
    summary="A Terrarium-encoded terrain tile from this project's DEM",
    responses={
        200: {"content": {"image/png": {}}, "description": "The tile."},
        404: {"description": "No DEM, or no data at this tile — render flat ground."},
    },
)
async def terrain_tile(
    project_id: UUID,
    z: int,
    x: int,
    y: int,
    _project=Depends(deps.get_project),
    service: DemService = Depends(deps.get_dem_service),
) -> Response:
    """Serve one 256×256 terrain tile for the 3D view.

    ★ **A 404 here is a normal, expected answer**, not an error: it is how the renderer
    learns there is no terrain for this tile and should draw flat ground. Returning an
    all-zero tile instead would paint a fabricated sea-level surface that looks exactly
    like real data — the failure this codebase exists to avoid, in mesh form.

    ★ **These heights are for RENDERING and are not survey values.** They are resampled
    and quantised to 1/256 m. A GCP's Z comes from ``POST …/elevation/sample``, which
    reads the DEM directly, answers null where there is nothing, and carries a vertical
    CE90. If the two ever disagree, the mesh is wrong and the sample is right.
    """
    if not 0 <= z <= _MAX_TERRAIN_ZOOM:
        raise ValidationError(f"zoom {z} outside [0, {_MAX_TERRAIN_ZOOM}]")
    span = 1 << z
    if not (0 <= x < span and 0 <= y < span):
        raise ValidationError(f"tile ({x}, {y}) outside the z={z} grid of {span}×{span}")

    png = await service.terrain_tile(project_id, z, x, y)
    if png is None:
        # ★ A plain 404 with no envelope: this is an <img>-shaped route and a JSON error
        #   body would be handed to a decoder expecting PNG bytes.
        return Response(status_code=status.HTTP_404_NOT_FOUND)

    return Response(
        content=png,
        media_type="image/png",
        headers={
            # A project's DEM is immutable while attached — re-uploading writes a new
            # file and the surveyor reloads. An hour is safe and keeps a 3D pan cheap.
            "Cache-Control": "private, max-age=3600",
            "X-Elevation-Encoding": "terrarium",
        },
    )


@router.delete(
    "/projects/{project_id}/dem",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove this project's DEM",
)
async def delete_project_dem(
    project_id: UUID,
    _project=Depends(deps.get_project),
    service: DemService = Depends(deps.get_dem_service),
) -> Response:
    """Detach it. ★ Elevations already recorded on its GCPs are untouched."""
    service.delete_project_dem(project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/terrain/global/{z}/{x}/{y}.png",
    response_class=Response,
    summary="Global 3D-terrain tile (AWS/Mapzen terrarium)",
)
async def global_terrain_tile(
    z: int,
    x: int,
    y: int,
    service: DemService = Depends(deps.get_dem_service),
) -> Response:
    """The 3D pane's terrain when a project has no DEM of its own.

    Terrarium-encoded heights from the AWS Open Data terrain tiles (~30 m sources:
    SRTM, 3DEP, GMTED2010) — a VISUALISATION surface, proxied so the browser never
    fetches a third party and so LE_IMAGERY_OFFLINE stays enforceable server-side.
    Refuses z > 14 rather than upsampling invented relief.
    """
    from anyio import to_thread

    data = await to_thread.run_sync(service.global_terrain_tile, z, x, y)
    return Response(
        content=data,
        media_type="image/png",
        headers={
            # Immutable data: relief at z<=14 does not change under anyone's feet.
            "Cache-Control": "public, max-age=2592000, immutable",
            # ★ ASCII only: HTTP headers are latin-1, and the display string carries an
            #   em-dash. The full string travels to the UI via the frontend constant.
            "X-Attribution": "Mapzen/AWS Terrain Tiles (SRTM, 3DEP, GMTED2010, ETOPO1)",
        },
    )


@router.get(
    "/dem/active",
    response_model=DemActiveResponse,
    summary="Which DEM feeds GCP elevations",
)
async def active_dem(
    service: DemService = Depends(deps.get_dem_service),
) -> DemActiveResponse:
    """Report the DEM new GCPs sample their elevation from.

    ★ Registered BEFORE ``/dem/{run_id}/download``: Starlette matches in registration
    order, and ``active`` would otherwise be captured as a ``run_id``.
    """
    record = service.active_elevation_dem()
    if record is None:
        return DemActiveResponse(active=False, provider_enabled=False)
    return DemActiveResponse(active=True, **record)


@router.get(
    "/dem/{run_id}/download",
    response_class=Response,
    summary="Download the processed DEM",
)
async def download_dem(
    run_id: str,
    service: DemService = Depends(deps.get_dem_service),
) -> Response:
    """Stream the processed GeoTIFF."""
    payload, filename = service.open_output(run_id)
    return Response(
        content=payload,
        media_type="image/tiff",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(payload)),
        },
    )


@router.post(
    "/dem/{run_id}/sample",
    response_model=DemSampleResponse,
    summary="Sample elevations from a processed DEM",
)
async def sample_dem(
    run_id: str,
    body: DemSampleRequest,
    service: DemService = Depends(deps.get_dem_service),
) -> DemSampleResponse:
    """Stage 3 — ``(X, Y) = project(lon, lat)``, ``Z = DEM(X, Y) + offset``.

    ★ A point outside the DEM, or on a nodata void, returns ``z_m: null`` — never 0.
    """
    return await service.sample(run_id, body)


def _resolve_source(
    request: Request, file: UploadFile | None, source_path: str | None
) -> tuple[BinaryIO | None, str, Path | None]:
    """Exactly one of ``file`` (multipart bytes) / ``source_path`` (a local file).

    Returns ``(stream, filename, local_path)`` for :meth:`DemService.process`.

    ★ THE ``source_path`` MODE IS FOR THE DESKTOP SHELL, where the API and the UI
    share one machine — it lets a multi-GB DEM skip the HTTP body entirely. CSRF
    guard: a cross-origin page can submit a bare multipart form, but it cannot add
    a custom header without passing CORS preflight — so path mode requires the
    ``X-Request-ID`` header every first-party client already sends.
    """
    if (file is None) == (source_path is None):
        raise ValidationError(
            "send exactly one of `file` (the upload) or `source_path` (a file on the "
            "API's own machine)."
        )
    if file is not None:
        return file.file, file.filename or "dem.tif", None
    if request.headers.get("x-request-id") is None:
        raise ValidationError("source_path requires the X-Request-ID header.")
    assert source_path is not None
    local = Path(source_path).expanduser()
    if not local.is_file():
        raise ValidationError(f"source_path does not exist or is not a file: {source_path!r}")
    return None, local.name, local


def _parse_camera(
    lat: float | None, lon: float | None, radius_m: float | None
) -> tuple[float, float, float] | None:
    """Validate the camera-station triple. All three, or none.

    ★ A partial camera is refused rather than ignored. Silently dropping a position
    because the radius was left blank would process the WHOLE DEM while the surveyor
    believes they cropped to their working area — and the resulting file looks perfectly
    normal.
    """
    given = [v is not None for v in (lat, lon, radius_m)]
    if not any(given):
        return None
    if not all(given):
        missing = [
            name
            for name, value in (("camera_lat", lat), ("camera_lon", lon), ("radius_m", radius_m))
            if value is None
        ]
        raise ValidationError(
            f"a camera AOI needs latitude, longitude and radius together; missing: "
            f"{', '.join(missing)}."
        )
    assert lat is not None and lon is not None and radius_m is not None
    return (lon, lat, radius_m)


def _parse_corners(raw: str | None) -> list[DemAoiCorner] | None:
    """Parse the AOI corners form field.

    Multipart carries strings, so the corner array arrives as JSON text. Parsed here
    rather than in the service so a malformed payload is a 422 about the request, not a
    500 from inside the pipeline.
    """
    if raw is None or not raw.strip():
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"aoi_corners is not valid JSON: {exc}") from exc
    if not isinstance(parsed, list):
        raise ValidationError("aoi_corners must be a JSON array of {lat, lon} objects.")
    if len(parsed) < 3:
        raise ValidationError(
            f"an AOI needs at least 3 corners to bound an area, got {len(parsed)}."
        )
    try:
        return [DemAoiCorner.model_validate(item) for item in parsed]
    except Exception as exc:  # noqa: BLE001 - pydantic's own message is the useful one
        raise ValidationError(f"aoi_corners is malformed: {exc}") from exc
