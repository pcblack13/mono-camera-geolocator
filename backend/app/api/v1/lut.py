"""``/lut/*`` — pixel→lat/lon lookup-table builds (``app.services.lut_service``).

★ THE ROUTER OWNS THE FETCHES, THE SERVICE OWNS THE BUILD. Everything a build
needs is read here through the same deps every other route uses (image, entered
camera, committed GCPs, the project DEM path) and handed over as plain data —
the service stays framework-free and the vendored core stays untouched.

★ 422s NAME THE FIX: "camera has no intrinsics", "only N GCPs carry an
elevation", "project has no DEM". A build that cannot succeed is refused before
the thread starts, not discovered as a stack trace two minutes in.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, Any, BinaryIO
from uuid import UUID  # noqa: TC003 — read at runtime by FastAPI's Query

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.api.presenters import to_image_camera_read
from app.core.config import Settings
from app.api.deps import as_lonlat
from app.core.pagination import PaginationParams, SortKey, SortParams
from app.schemas.gcp import GCP_SORT_FIELDS
from app.schemas.lut import LutBuildRequest, LutBuildStatus, LutLibraryEntry, LutLookupRead
from app.services import lut_service
from app.services.dem_service import DemService
from app.services.elevation_service import ElevationService
from app.services.image_camera_service import ImageCameraService

router = APIRouter(prefix="/lut", tags=["lut"])


def _to_status(build: lut_service.LutBuild) -> LutBuildStatus:
    archive = build.archive_path
    return LutBuildStatus(
        build_id=build.build_id,
        image_id=build.inputs.image_id,
        project_id=build.inputs.project_id,
        site_name=build.inputs.site_name,
        status=build.status,  # type: ignore[arg-type]  # the service emits only the literal states
        progress_done=build.progress_done,
        progress_total=build.progress_total,
        started_at=build.started_at,
        error=build.error,
        report=build.report,
        bundle_dir=build.bundle_dir,
        archive_available=archive is not None and archive.is_file(),
        adopted=build.adopted,
    )


@router.post("/builds", response_model=LutBuildStatus, status_code=status.HTTP_202_ACCEPTED,
             summary="Build a pixel→lat/lon LUT bundle for a photograph")
async def create_build(
    body: LutBuildRequest,
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    dem_service: DemService = Depends(deps.get_dem_service),
    _: None = Depends(deps.require_writable),
) -> LutBuildStatus:
    image = await deps.get_image(body.image_id, db=db)

    try:
        camera_row = await ImageCameraService(db).get(image.id)
    except Exception as exc:  # the service 404s a missing camera — say what to do instead
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="the photograph has no entered camera — fill in its setup page first.",
        ) from exc
    # ★ The WIRE model, not the ORM row: `position` is a PostGIS geometry on the row,
    #   and the presenter is the one place that turns it into lat/lon.
    camera = to_image_camera_read(camera_row, image_id=image.id)

    rows, _total = await deps.list_gcps_for_image(
        db,
        image.id,
        pagination=PaginationParams(limit=200, offset=0),
        sort=SortParams.parse(
            None, allowed=GCP_SORT_FIELDS, default=(SortKey("created_at", descending=True),)
        ),
    )
    # ★ ALL committed GCPs go in — a missing elevation_m is filled by the service
    #   from the project DEM itself, so points placed before the DEM was attached
    #   still count toward the pose.
    points: list[lut_service.GcpPoint] = []
    for g in rows:
        lonlat = as_lonlat(g.geom)
        if lonlat is None:
            continue
        points.append(
            lut_service.GcpPoint(
                u=float(g.pixel_x), v=float(g.pixel_y),
                lat=float(lonlat[1]), lon=float(lonlat[0]),
                elevation_m=None if g.elevation_m is None else float(g.elevation_m),
            )
        )

    site = lut_service.sanitize_site_name(
        body.site_name if body.site_name else image.filename.rsplit(".", 1)[0]
    )

    inputs = lut_service.LutBuildInputs(
        image_id=image.id,
        project_id=image.project_id,
        site_name=site,
        image_width=int(image.width),
        image_height=int(image.height),
        fx=camera.fx, fy=camera.fy, cx=camera.cx, cy=camera.cy,
        k1=camera.k1 or 0.0, k2=camera.k2 or 0.0,
        p1=camera.p1 or 0.0, p2=camera.p2 or 0.0, k3=camera.k3 or 0.0,
        # >>> GEO-DRIFT-UPDATE C2 BEGIN — a calibration is optional >>>
        # ★ The photograph's own answer travels; the build never guesses. With the
        #   flag on, fx..cy above are ignored and K comes from the field of view.
        no_calibration=bool(getattr(camera, "no_calibration", False)),
        fov_h_deg=getattr(camera, "fov_h_deg", None),
        fov_v_deg=getattr(camera, "fov_v_deg", None),
        # <<< GEO-DRIFT-UPDATE C2 END <<<
        cam_lat=camera.lat, cam_lon=camera.lon,
        cam_height_m=camera.mast_offset_m or 0.0,
        gcps=tuple(points),
        # ★ THE ONE DEM RULE (2026-09-04): the surface under THIS photograph — its own
        #   DEM if it has one, else the project's — exactly as the auto-GCP raycast and
        #   every GCP's Z resolve it. The build used to read the project DEM alone and
        #   refused a frame whose DEM was attached per image.
        dem_path=dem_service.elevation_dem_path(image.project_id, image.id),
        output_dir=settings.lut_output_dir,
        # ★ When the photograph has an ADOPTED correction from the accuracy check, the
        #   build stands on that refined pose instead of the one its GCPs alone imply.
        #   The LUT is the only artefact adoption reaches — see `accuracy_service.adopt`.
        accuracy_dir=settings.accuracy_output_dir,
        target_height_m=body.target_height_m,
        coord_dtype=body.coord_dtype,
        validation_samples=body.validation_samples,
    )

    try:
        build = lut_service.start_build(inputs)
    except lut_service.LutBuildError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _to_status(build)


@router.get("/builds", response_model=list[LutBuildStatus],
            summary="Builds started since the API came up (newest first)")
async def list_builds() -> list[LutBuildStatus]:
    return [_to_status(b) for b in lut_service.list_builds()]


@router.get("/builds/{build_id}", response_model=LutBuildStatus, summary="One build's status")
async def get_build(build_id: str) -> LutBuildStatus:
    build = lut_service.get_build(build_id)
    if build is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no such build (builds are tracked in memory — a restart clears the list; "
            "the bundles themselves stay on disk under the LUT output folder).",
        )
    return _to_status(build)


@router.get("/builds/{build_id}/archive", summary="Download the bundle .zip")
async def download_archive(build_id: str) -> FileResponse:
    build = lut_service.get_build(build_id)
    if build is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such build.")
    archive = build.archive_path
    if archive is None or not archive.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="the archive is not ready — wait for the build to succeed.",
        )
    return FileResponse(archive, filename=archive.name, media_type="application/zip")


@router.get("/library", response_model=list[LutLibraryEntry],
            summary="Every LUT bundle on disk (survives restarts)")
async def list_library(settings: Settings = Depends(deps.get_settings)) -> list[LutLibraryEntry]:
    return [LutLibraryEntry(**e) for e in lut_service.scan_library(settings.lut_output_dir)]


@router.get("/library/{site_name}/archive", summary="Download a library bundle's .zip")
async def download_library_archive(
    site_name: str, settings: Settings = Depends(deps.get_settings)
) -> FileResponse:
    archive = lut_service.library_archive_path(settings.lut_output_dir, site_name)
    if archive is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no archive for that site — the bundle folder may exist without its .zip; rebuild to regenerate it.",
        )
    return FileResponse(archive, filename=archive.name, media_type="application/zip")


# ─────────────────────────────────────────────────────────────────────────────
# One pixel, on the ground — the monitoring page's live predict (2026-09-10)
# ─────────────────────────────────────────────────────────────────────────────


@lru_cache(maxsize=8)
def _open_lut(bundle_dir: str, manifest_mtime_ns: int) -> Any:
    """The bundle's reader, kept open: the arrays are memory-mapped, so opening is
    cheap but not free, and a cursor asks several times a second. The manifest's
    mtime is part of the key so a rebuilt bundle is re-read, never served stale."""
    from app.services.detection.lut import GeoLut  # noqa: PLC0415 — numpy stays off the import path

    return GeoLut(bundle_dir)


def _library_bundle(settings: Settings, site_name: str) -> Path:
    # ★ Same traversal-proof resolution as the download route and the detection
    #   start: re-sanitise to the alphabet the writer used, then join.
    safe = lut_service.sanitize_site_name(site_name)
    candidate = settings.lut_output_dir / f"{safe}_lut"
    if not (candidate / "manifest.json").is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no lookup table named '{site_name}' in the library.",
        )
    return candidate


@router.get(
    "/library/{site_name}/lookup",
    response_model=LutLookupRead,
    summary="One pixel of a live picture → its ground coordinates, through a library bundle",
)
async def lookup_pixel(
    site_name: str,
    u: float = Query(..., description="Column, in the media's own pixels"),
    v: float = Query(..., description="Row, in the media's own pixels"),
    w: int | None = Query(None, ge=1, description="The media's width (scales into the table)"),
    h: int | None = Query(None, ge=1, description="The media's height"),
    project_id: UUID | None = Query(
        None, description="The camera's project — its DEM gives the elevation"
    ),
    settings: Settings = Depends(deps.get_settings),
    elevation: ElevationService = Depends(deps.get_elevation_service),
) -> LutLookupRead:
    """★ THE SAME TABLE THE MARKS USE. A detection is placed by reading the bundle's
    arrays at its ground pixel; this reads the same arrays at the cursor, with the
    same media→table scaling, so what the operator points at and what a mark
    would say are one answer. Sky and uncovered ground answer ``placed: false``
    with the reason — a 200, because "nothing there" is the normal case for half
    of every frame, not a failure."""
    bundle = _library_bundle(settings, site_name)
    manifest = bundle / "manifest.json"
    lut = _open_lut(str(bundle), manifest.stat().st_mtime_ns)
    media_size = (w, h) if w and h else None
    sx, sy = lut.scale_from(*media_size) if media_size else (1.0, 1.0)
    lut_u, lut_v = u * sx, v * sy
    base = {"site_name": site_name, "u": u, "v": v, "lut_u": lut_u, "lut_v": lut_v}
    if not (0 <= round(lut_u) < lut.width and 0 <= round(lut_v) < lut.height):
        return LutLookupRead(**base, placed=False, reason="off_table")
    lat, lon = await run_in_threadpool(lut.lookup, u, v, media_size=media_size)
    if lat is None or lon is None:
        return LutLookupRead(**base, placed=False, reason="no_terrain")
    elevation_m: float | None = None
    source: str | None = None
    if project_id is not None:
        results = await run_in_threadpool(
            lambda: elevation.sample_lonlat([(lon, lat)], project_id=project_id)
        )
        if results and results[0].available:
            elevation_m, source = results[0].elevation_m, results[0].source
    return LutLookupRead(
        **base, placed=True, lat=lat, lon=lon, elevation_m=elevation_m, elevation_source=source
    )


# ─────────────────────────────────────────────────────────────────────────────
# Importing a bundle this app did not build
# ─────────────────────────────────────────────────────────────────────────────

#: 1 MB at a time — a full-resolution bundle is ~150 MB and must never be
#: ``read()`` whole into the API's memory. Same contract as the DEM upload.
_CHUNK = 1024 * 1024


def _spool(stream: BinaryIO, destination: Path, limit: int) -> int:
    """Stream the upload to disk, enforcing the ceiling DURING the copy."""
    written = 0
    with destination.open("wb") as out:
        while chunk := stream.read(_CHUNK):
            written += len(chunk)
            if limit and written > limit:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"the bundle exceeds the {limit / 1e6:.0f} MB upload limit.",
                )
            out.write(chunk)
    if written == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="the uploaded file is empty."
        )
    return written


@router.post(
    "/library/import",
    response_model=LutLibraryEntry,
    status_code=status.HTTP_201_CREATED,
    summary="Import an existing LUT bundle into the library",
)
async def import_library_bundle(
    request: Request,
    file: Annotated[UploadFile | None, File(description="A bundle .zip.")] = None,
    source_path: Annotated[
        str | None,
        Form(description="A .zip or a bundle folder on the API's OWN machine (desktop route)."),
    ] = None,
    site_name: Annotated[str | None, Form(max_length=64)] = None,
    overwrite: Annotated[bool, Form()] = False,
    settings: Settings = Depends(deps.get_settings),
    _: None = Depends(deps.require_writable),
) -> LutLibraryEntry:
    """Take a LUT someone else built and file it under ``<site>_lut``.

    ★ WHY THE APP NEEDS THIS. Every page that places a detection on the map —
    live stream, video detection, drift monitor — picks its table by name from this
    one library. Without an import, a surveyor arriving with a bundle on a USB stick
    (built on another machine, or handed over with a camera) had no way in but a
    shell on the API host. The upload is that same copy, with the checks a hand-copy
    never gets: see ``lut_service._validate_payload``.

    ★ TWO ROUTES IN, one behaviour out. ``file`` is the ordinary multipart upload;
    ``source_path`` is the desktop shell's zero-copy route — the API and the UI share
    a machine, so a 150 MB bundle (or a bundle FOLDER, which cannot be uploaded at
    all) is opened in place instead of travelling over HTTP. Exactly as
    ``/dem/process`` does it, including the ``X-Request-ID`` CSRF guard: a
    cross-origin page can post a bare multipart form, but not a custom header.
    """
    if (file is None) == (source_path is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="send exactly one of `file` (the upload) or `source_path` (a bundle "
            "on the API's own machine).",
        )

    limit = int(getattr(settings, "upload_max_bytes", 0) or 0)

    def run(source: Path, origin: str) -> LutLibraryEntry:
        try:
            entry = lut_service.import_bundle(
                output_dir=settings.lut_output_dir,
                source=source,
                origin_name=origin,
                site_name=site_name,
                overwrite=overwrite,
                max_bytes=limit,
            )
        except lut_service.LutImportError as exc:
            # ★ A NAME CLASH is a 409, not a 422: nothing about the bundle is wrong,
            #   the library simply already holds that name, and the client's fix is to
            #   rename or confirm the replacement rather than to pick a different file.
            clash = "already holds a bundle named" in str(exc)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT
                if clash
                else status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
        return LutLibraryEntry(**entry)

    if source_path is not None:
        if request.headers.get("x-request-id") is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="source_path requires the X-Request-ID header.",
            )
        local = Path(source_path).expanduser()
        if not local.exists():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"source_path does not exist: {source_path!r}",
            )
        return await run_in_threadpool(run, local, local.name)

    assert file is not None
    # ★ Spooled to a temp file, not to the library: a refused bundle must leave no
    #   trace in the folder every page reads from. It is spooled BESIDE the library
    #   rather than in the system temp: a full-resolution bundle is ~150 MB, and on
    #   a host whose /tmp is a tmpfs that is 150 MB of RAM — while the LUT folder is
    #   by definition sized for exactly this.
    settings.lut_output_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".lut-import-", dir=settings.lut_output_dir) as tmp:
        staged = Path(tmp) / "upload.zip"
        await run_in_threadpool(_spool, file.file, staged, limit)
        return await run_in_threadpool(run, staged, file.filename or "bundle.zip")
