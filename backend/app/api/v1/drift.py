"""``/drift/*`` — camera drift references: freeze the trusted state, check it later.

★ THE ROUTER OWNS THE FETCHES, THE SERVICE OWNS THE MONITOR — the ``/detection``
split, reused verbatim: ``video:<id>`` resolves through the video row (never a
free-text path from the wire), the LUT site resolves through the same sanitiser
the library's download route uses, and every refusal names the fix.

★ CAPTURE BLOCKS — a live source pays up to the handover window before the first
frame arrives — so freeze and check run in the threadpool, never on the event
loop.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core.config import Settings
from app.schemas.drift import (
    DriftCheckRequest,
    fit,
    DriftFreezeRequest,
    DriftMonitorList,
    DriftMonitorRead,
    DriftMonitorStartRequest,
    DriftReferenceList,
    DriftReferenceRead,
    DriftSoakReport,
    DriftVerdictRead,
)
from app.services import drift_service, lut_service
from app.services.camera_service import CameraService

router = APIRouter(prefix="/drift", tags=["drift"])


async def _resolve_source(
    source: str, db: AsyncSession, settings: Settings
) -> tuple[Path | None, str | None]:
    """``video:<id>`` → the stored file, through the video row. Everything else
    (a device path, an RTSP/HTTP URL) passes through for the capture layer."""
    if not source.startswith("video:"):
        return None, None
    from app.services.video_service import VideoService  # noqa: PLC0415
    from app.storage import get_storage  # noqa: PLC0415

    try:
        video_id = UUID(source.removeprefix("video:"))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="a video source is 'video:<id>' with the library video's id.",
        ) from exc
    storage = get_storage()
    local_path = getattr(storage, "local_path", None)
    if not callable(local_path):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="video-file drift checks need local storage (S3 is not supported).",
        )
    try:
        video = await VideoService(db, settings, storage=storage).get(video_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"no video {video_id} in the library.",
        ) from exc
    return Path(local_path(video.storage_path)), getattr(video, "filename", None)


# >>> GEO-DRIFT-UPDATE D1 BEGIN — freeze from the photograph the GCPs are on >>>
async def resolve_image_frame(
    image_id: UUID, db: AsyncSession, settings: Settings
) -> tuple[Path, str | None]:
    """A library photograph → the file on disk AND its name, through the image row.

    ★ NEVER A FREE-TEXT PATH FROM THE WIRE — the same rule ``video:<id>`` follows
    next door: the id goes through the row, and the row names the storage key.
    """
    from app.services.image_service import ImageService  # noqa: PLC0415
    from app.storage import get_storage  # noqa: PLC0415

    storage = get_storage()
    local_path = getattr(storage, "local_path", None)
    if not callable(local_path):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="freezing from a photograph needs local storage (S3 is not supported).",
        )
    try:
        image = await ImageService(db, settings, storage=storage).get(image_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"no photograph {image_id} in the library.",
        ) from exc
    # ★ The row's filename, not the storage key's basename — every stored image
    #   is `original.<ext>` on disk, which names nothing a surveyor would recognise.
    return Path(local_path(image.storage_path)), getattr(image, "filename", None)


# <<< GEO-DRIFT-UPDATE D1 END <<<


def _resolve_lut_dir(lut_site: str, settings: Settings) -> Path:
    safe = lut_service.sanitize_site_name(lut_site)
    candidate = settings.lut_output_dir / f"{safe}_lut"
    if not (candidate / "manifest.json").is_file():
        known = [e["site_name"] for e in lut_service.scan_library(settings.lut_output_dir)]
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"no LUT bundle named '{lut_site}' in the library"
            + (f" (available: {', '.join(known)})" if known else " — build one first"),
        )
    return candidate


@router.get(
    "/references",
    response_model=DriftReferenceList,
    summary="Every frozen drift reference, newest first",
)
async def list_references(
    settings: Settings = Depends(deps.get_settings),
) -> DriftReferenceList:
    items = drift_service.scan_references(settings.drift_output_dir)
    return DriftReferenceList(items=[fit(DriftReferenceRead, r) for r in items])


@router.post(
    "/references",
    response_model=DriftReferenceRead,
    status_code=status.HTTP_201_CREATED,
    summary="Freeze the trusted state of a camera view (call while the mapping is good)",
)
async def freeze(
    body: DriftFreezeRequest,
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    _: None = Depends(deps.require_writable),
) -> DriftReferenceRead:
    file_path, source_label = await _resolve_source(body.source, db, settings)
    lut_dir = _resolve_lut_dir(body.lut_site, settings)
    # >>> GEO-DRIFT-UPDATE D1 BEGIN — freeze from the photograph the GCPs are on >>>
    # ★ CHOOSING THE LOOKUP TABLE IS CHOOSING THE PICTURE. The bundle records the
    #   photograph its pose was solved from, so the surveyor does not have to name
    #   it again — picking the table they trusted already says which frame the
    #   reference belongs on. An explicit id still wins, and a bundle that predates
    #   the record (or whose photograph has since been deleted) falls back to the
    #   old behaviour rather than refusing.
    image_id = body.freeze_from_image_id
    if image_id is None and body.use_lut_image:
        import json as _json  # noqa: PLC0415

        try:
            manifest = _json.loads((lut_dir / "manifest.json").read_text(encoding="utf-8"))
            recorded = manifest.get("source_image_id")
            image_id = None if recorded is None else UUID(str(recorded))
        except (OSError, ValueError):
            image_id = None
    image_path = None
    image_label = None
    if image_id is not None:
        try:
            image_path, image_label = await resolve_image_frame(image_id, db, settings)
        except HTTPException:
            # An EXPLICIT id that will not resolve is an error the caller must see;
            # one we inferred from the manifest is not — the photograph may simply
            # have been removed since the table was built.
            if body.freeze_from_image_id is not None:
                raise
            image_path, image_label = None, None
    # <<< GEO-DRIFT-UPDATE D1 END <<<
    try:
        record = await run_in_threadpool(
            drift_service.freeze_reference,
            settings.drift_output_dir,
            lut_dir,
            name=body.name,
            source=body.source,
            source_label=source_label,
            alert_ground_m=body.alert_ground_m,
            ref_range=body.ref_range_m,
            confirm_n=body.confirm_n,
            n_landmarks=body.n_landmarks,
            file_path=file_path,
            at_s=body.at_s,
            image_path=image_path,      # GEO-DRIFT-UPDATE D1
            image_label=image_label,
            # >>> GEO-DRIFT-UPDATE C1 BEGIN — intrinsics without a calibration >>>
            no_calibration=body.no_calibration,
            fov_h_deg=body.fov_h_deg,
            fov_v_deg=body.fov_v_deg,
            square_pixels=body.square_pixels,
            # <<< GEO-DRIFT-UPDATE C1 END <<<
        )
    except drift_service.DriftError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return fit(DriftReferenceRead, record)


@router.post(
    "/references/{ref_id}/check",
    response_model=DriftVerdictRead,
    summary="One monitoring pass: grab a fresh frame and judge it against the reference",
)
async def check(
    ref_id: str,
    body: DriftCheckRequest | None = None,
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
) -> DriftVerdictRead:
    source = body.source if body is not None else None
    file_path = None
    if source is None:
        try:
            source = drift_service.read_reference(settings.drift_output_dir, ref_id)["source"]
        except drift_service.DriftError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
            ) from exc
    file_path, _label = await _resolve_source(source, db, settings)
    try:
        verdict = await run_in_threadpool(
            drift_service.check_reference,
            settings.drift_output_dir,
            ref_id,
            source=source,
            file_path=file_path,
            at_s=body.at_s if body is not None else None,
        )
    except drift_service.DriftError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return fit(DriftVerdictRead, verdict)


#: History entries per monitor on the wire — the loop's ring holds more; a status
#: poll needs the recent shape, not two hours of archaeology.
_WIRE_HISTORY = 50


def _monitor_read(run: drift_service.DriftMonitorRun) -> DriftMonitorRead:
    return DriftMonitorRead(
        ref_id=run.ref_id,
        status=run.status,  # type: ignore[arg-type] — the loop emits only these
        source=run.source,
        interval_s=run.interval_s,
        started_utc=run.started_utc,
        checks_done=run.checks_done,
        capture_failures=run.capture_failures,
        last_error=run.last_error,
        last=fit(DriftVerdictRead, run.last) if run.last else None,
        history=[fit(DriftVerdictRead, v) for v in list(run.history)[-_WIRE_HISTORY:]],
    )


@router.get(
    "/status",
    response_model=DriftMonitorList,
    summary="Every drift monitor's state — the one poll the map and pills need",
)
async def monitors_status() -> DriftMonitorList:
    return DriftMonitorList(items=[_monitor_read(r) for r in drift_service.list_monitors()])


@router.post(
    "/references/{ref_id}/monitor/start",
    response_model=DriftMonitorRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Watch this reference: one check per interval until stopped",
)
async def monitor_start(
    ref_id: str,
    body: DriftMonitorStartRequest | None = None,
    settings: Settings = Depends(deps.get_settings),
    db: AsyncSession = Depends(deps.get_db),
    _: None = Depends(deps.require_writable),
) -> DriftMonitorRead:
    opts = body or DriftMonitorStartRequest()
    # ★ The camera is checked BEFORE the loop starts: a watch recorded against a
    #   camera that does not exist would be intent nobody could ever clear.
    if opts.camera_id is not None:
        await CameraService(db).get(opts.camera_id)
    try:
        run = drift_service.start_monitor(
            settings.drift_output_dir,
            ref_id,
            interval_s=opts.interval_s,
            source=opts.source,
        )
    except drift_service.DriftError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    if opts.camera_id is not None:
        # intent, recorded: this camera should be watched on this reference
        await CameraService(db).record_watch(
            opts.camera_id, {"ref_id": ref_id, "interval_s": float(opts.interval_s)}
        )
    return _monitor_read(run)


@router.post(
    "/references/{ref_id}/monitor/stop",
    response_model=DriftMonitorRead,
    summary="Stop watching this reference",
)
async def monitor_stop(
    ref_id: str,
    camera_id: UUID | None = None,
    db: AsyncSession = Depends(deps.get_db),
) -> DriftMonitorRead:
    """``?camera_id=`` clears the camera's recorded intent too — a watch the
    operator stopped must not come back at the next boot."""
    run = drift_service.stop_monitor(ref_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="this reference is not being monitored.",
        )
    if camera_id is not None:
        await CameraService(db).record_watch(camera_id, None)
    return _monitor_read(run)


@router.get(
    "/references/{ref_id}/status",
    response_model=DriftMonitorRead,
    summary="This reference's monitor state",
)
async def monitor_status(ref_id: str) -> DriftMonitorRead:
    run = drift_service.get_monitor(ref_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="this reference is not being monitored.",
        )
    return _monitor_read(run)


@router.get(
    "/references/{ref_id}/report",
    response_model=DriftSoakReport,
    summary="The soak report: every logged look, summarised for the validation day",
)
async def report(
    ref_id: str,
    settings: Settings = Depends(deps.get_settings),
) -> DriftSoakReport:
    try:
        data = drift_service.soak_report(settings.drift_output_dir, ref_id)
    except drift_service.DriftError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return DriftSoakReport(**data)


# >>> GEO-DRIFT-UPDATE B2 BEGIN — the field-unit export >>>
@router.get(
    "/references/{ref_id}/field-unit",
    summary="Everything an embedded unit needs to watch this reference, as a zip",
    response_class=Response,
)
async def field_unit(
    ref_id: str,
    settings: Settings = Depends(deps.get_settings),
) -> Response:
    """The whole delivery to a field unit — tens of KB, not the LUT's 146 MB.

    ★ WHY THIS IS SO SMALL. ``check()`` needs no terrain model: the landmarks
    carry the world positions baked in at freeze time, so drift detection
    travels as one npz. A unit that must also turn pixels into lat/lon needs the
    LUT bundle as well — that is a separate, much larger delivery.

    ★ IT CARRIES THE WINDOW SIZES, AND THAT IS NOT OPTIONAL. ``PATCH``/``SEARCH``
    are tuning that ``DriftMonitor.load()`` does NOT restore; the vendor's
    defaults were validated at 4032 px wide. A 1920-wide reference judged with
    the defaults reports ~0.74° of rotation that never happened — the unit would
    disagree with this GUI on identical pictures, in the alarming direction. So
    ``field_unit.json`` states them and the daemon reads it.
    """
    import io  # noqa: PLC0415
    import json as _json  # noqa: PLC0415
    import zipfile  # noqa: PLC0415
    from pathlib import Path as _Path  # noqa: PLC0415

    try:
        rec = drift_service.read_reference(settings.drift_output_dir, ref_id)
    except drift_service.DriftError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    ref_dir = settings.drift_output_dir / ref_id
    npz = ref_dir / "landmarks.npz"
    if not npz.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="this reference has no landmarks.npz — re-freeze it.",
        )

    # ★ THE VENDORED COPY IS THE ONE THAT SHIPS. An installed .deb has no repo
    #   checkout beside it, so the app's own `vendor/drift_monitor/` is the only
    #   location guaranteed to exist; the core's standalone home is preferred
    #   when running from a checkout so a fix there needs no re-vendor to test.
    vendor = _Path(drift_service.__file__).resolve().parent.parent / "vendor" / "drift_monitor"
    core = _Path(__file__).resolve().parents[6] / "core" / "drift_monitor"

    alert_mrad = float(rec["alert_ground_m"]) / float(rec["ref_range_m"]) * 1000.0
    sidecar = {
        "ref_id": ref_id,
        "name": rec.get("name", ""),
        "lut_site": rec.get("lut_site", ""),
        "frozen_utc": rec.get("created_utc", ""),
        # ★ the frame profile the unit's stream MUST match
        "frame_width": rec["frame_width"],
        "frame_height": rec["frame_height"],
        # ★ the tuning load() does not restore — see the docstring
        "patch_px": rec.get("patch_px"),
        "search_px": rec.get("search_px"),
        "confirm_n": rec.get("confirm_n"),
        # ★ the threshold as an ANGLE, so no range is baked into the unit
        "alert_mrad": round(alert_mrad, 4),
        "frozen_ref_range_m": rec.get("ref_range_m"),
        "n_landmarks": rec.get("n_landmarks"),
        # ★ GEO-DRIFT-UPDATE C1 — how the intrinsics behind every verdict were
        #   obtained. "fov" means a centred principal point and no distortion
        #   were ASSUMED; the field unit's log should be readable years later
        #   without having to guess which it was.
        "intrinsics_mode": rec.get("intrinsics_mode", "calibration"),
        "lut_intrinsics_mode": rec.get("lut_intrinsics_mode", "calibration"),
        "fov": rec.get("fov"),
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(npz, "landmarks.npz")
        z.writestr("field_unit.json", _json.dumps(sidecar, indent=2))
        # ★ NO SILENT TRUNCATION. A bundle missing the daemon still unzips and
        #   still looks like a delivery — the failure would only surface on the
        #   field unit, offline, by which time it is expensive. Every file is
        #   required; a missing one is a 500 that names it.
        # ★ THE FROZEN FRAME TRAVELS TOO. It costs a few hundred KB — nothing
        #   against the 146 MB this delivery replaces — and it buys the one
        #   check that catches a mis-assembled bundle offline, before it reaches
        #   a mast: judge the reference against ITSELF and the answer must be ~0.
        #   With the wrong matching windows it reads 0.735°. `selftest.py` runs it.
        if (ref_dir / "reference.jpg").is_file():
            z.write(ref_dir / "reference.jpg", "reference.jpg")

        missing: list[str] = []
        for name, where in (
            ("drift_daemon.py", "field_unit"),
            ("selftest.py", "field_unit"),
            ("requirements-embedded.txt", "field_unit"),
            ("README.md", "field_unit"),
            ("GUIDE.md", "field_unit"),
            ("OUTPUT.md", "field_unit"),
            ("BRIEF.md", "field_unit"),
            ("examples/consume.py", "field_unit"),
            ("examples/driftwatch.service", "field_unit"),
            ("drift_monitor.py", ""),
        ):
            src = next(
                (
                    p
                    for p in (core / where / name, vendor / where / name)
                    if p.is_file()
                ),
                None,
            )
            if src is None:
                missing.append(name)
            else:
                z.write(src, name)
        if missing:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    "the field-unit bundle is incomplete — missing "
                    f"{', '.join(missing)}. Looked in {core} and {vendor}."
                ),
            )
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="field-unit-{ref_id[:8]}.zip"'},
    )


# <<< GEO-DRIFT-UPDATE B2 END <<<


@router.delete(
    "/references/{ref_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a drift reference",
)
async def delete(
    ref_id: str,
    settings: Settings = Depends(deps.get_settings),
    _: None = Depends(deps.require_writable),
) -> Response:
    try:
        if not drift_service.delete_reference(settings.drift_output_dir, ref_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="no such drift reference."
            )
    except drift_service.DriftError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
