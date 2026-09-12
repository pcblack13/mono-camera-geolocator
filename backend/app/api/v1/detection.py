"""``/detection/*`` — live object detection, geolocated through the LUT library.

★ THE ROUTER OWNS THE FETCHES, THE SERVICE OWNS THE RUN — the ``/lut/*`` split.
The LUT site name is resolved HERE against ``settings.lut_output_dir`` through the
same sanitiser the library's own download route uses, so a crafted site name can
no more escape the library here than there.

★ 422s NAME THE FIX: "runtime not installed (pip line)", "no weights in <dir>",
"source already being detected", "handoff needs opencv-contrib". A session that
cannot succeed is refused before its thread starts.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core.config import Settings
from app.schemas.detection import (
    DetectionLockRequest,
    DetectionOverlayRequest,
    DetectionPauseRequest,
    DetectionSessionListRead,
    DetectionAvailability,
    DetectionMarksRead,
    DetectionSessionRead,
    DetectionStartRequest,
    DetectionTrackingRequest,
    DetectionTrackBoxRequest,
    DetectionTrackNameRequest,
    DetectionTrackRequest,
)
from app.services import detection_service, lut_service
from app.services.camera_service import CameraService

router = APIRouter(prefix="/detection", tags=["detection"])


def _to_read(session: detection_service.DetectionSession) -> DetectionSessionRead:
    return DetectionSessionRead(
        session_id=session.session_id,
        source=session.source,
        status=session.status,  # type: ignore[arg-type] — the service emits only these
        started_at=session.started_at,
        error=session.error,
        device=session.device,
        device_name=session.device_name,
        media_width=session.media_width,
        media_height=session.media_height,
        frames_done=session.frames_done,
        frames_dropped=session.frames_dropped,
        fps=session.fps,
        phase=session.phase,
        counts=dict(session.counts),
        skipped_no_terrain=session.skipped_no_terrain,
        marks_total=len(session.marks) + session.marks_dropped,
        marks_dropped=session.marks_dropped,
        db_rows_written=session.db_rows_written,
        db_rows_failed=session.db_rows_failed,
        db_error=session.db_error,
        latest=session.latest or None,  # type: ignore[arg-type] — same shape by construction
        lut_site=session.lut_site,
        lut_summary=session.lut_summary,
        settings=session.settings,
        paused=session.paused,
        camera_name=session.camera_name,
        camera_location=session.camera_location,
        camera_id=UUID(session.camera_id) if session.camera_id else None,
        drift_status=session.drift_status,  # type: ignore[arg-type] — the service emits only these
        drift_ref_id=session.drift_ref_id,
        marks_under_alert=session.marks_under_alert,
        marks_thinned=session.marks_thinned,
        tracking_on=session.tracking_on,
        tracked_ids=list(session.tracked_ids),
        primary_track_id=session.primary_track_id,
        track_names=dict(session.track_names),
        detect=session.detect,
    )


@router.get(
    "/availability",
    response_model=DetectionAvailability,
    summary="What detection can do on this machine — the UI gates on it",
)
async def get_availability(
    settings: Settings = Depends(deps.get_settings),
) -> DetectionAvailability:
    return DetectionAvailability(**detection_service.availability(settings.detection_model_dir))


@router.post(
    "/sessions",
    response_model=DetectionSessionRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start detecting a live source (optionally placing marks through a LUT)",
)
async def start(
    body: DetectionStartRequest,
    db: AsyncSession = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    _: None = Depends(deps.require_writable),
) -> DetectionSessionRead:
    # ── a video from THIS APP'S library as the source ────────────────────────
    # ★ `video:<uuid>` resolves to the stored file HERE, through the video row —
    #   never a free-text path from the wire: a picker that accepts paths is a file
    #   browser with extra steps.
    file_path = None
    source_label = None
    if body.source.startswith("video:"):
        from app.services.video_service import VideoService  # noqa: PLC0415
        from app.storage import get_storage  # noqa: PLC0415

        try:
            video_id = UUID(body.source.removeprefix("video:"))
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
                detail="video-file detection needs local storage (S3 is not supported).",
            )
        try:
            video = await VideoService(db, settings, storage=storage).get(video_id)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"no video {video_id} in the library.",
            ) from exc
        from pathlib import Path as _Path

        file_path = _Path(local_path(video.storage_path))
        # The attribute table's "camera" column: the CLIP is the recording.
        source_label = getattr(video, "filename", None) or f"video:{video_id}"

    lut_dir = None
    if body.lut_site:
        # ★ Same traversal-proof resolution as the LUT library's own download route:
        #   re-sanitise to the alphabet the writer used, then join. A site name that
        #   is not in the library is a 422 naming what IS.
        safe = lut_service.sanitize_site_name(body.lut_site)
        candidate = settings.lut_output_dir / f"{safe}_lut"
        if not (candidate / "manifest.json").is_file():
            known = [e["site_name"] for e in lut_service.scan_library(settings.lut_output_dir)]
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"no LUT bundle named '{body.lut_site}' in the library"
                + (f" (available: {', '.join(known)})" if known else " — build one first"),
            )
        lut_dir = candidate

    values = {
        "conf": body.conf,
        "imgsz": body.imgsz,
        "tile": body.tile,
        "max_frames": body.max_frames,
        "tracker_start_frame": body.tracker_start_frame,
        "locked_tracker_type": body.tracker_type,
        "tracker_refresh_every": body.tracker_refresh_every,
        "model": body.model,
        "classes": body.classes,
        "centre_marks": body.centre_marks,
        "steady_boxes": body.steady_boxes,
        "mark_rate_hz": body.mark_rate_hz,
    }
    # ★ A run that names a camera is checked against the registry FIRST: intent
    #   recorded against a camera that does not exist could never be cleared.
    if body.camera_id is not None:
        camera = await CameraService(db).get(body.camera_id)
        source_label = source_label or camera.name
    try:
        session = detection_service.start_session(
            source=body.source,
            model_dir=settings.detection_model_dir,
            lut_dir=lut_dir,
            settings_values={k: v for k, v in values.items() if v is not None},
            file_path=file_path,
            every_nth=body.every_nth,
            source_label=source_label,
            camera_id=str(body.camera_id) if body.camera_id else None,
            detect=body.detect,
        )
    except detection_service.DetectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except Exception as exc:  # the live-stream validators raise their own ValueError
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    if body.camera_id is not None and file_path is None and body.detect:
        # intent, recorded: this LIVE camera should be detecting with these settings
        # (a tracking-only run is the operator's moment, not the camera's state —
        # its locks cannot be brought back after a restart)
        # (a clip run is a one-off — nothing to bring back after a restart)
        await CameraService(db).record_detect(
            body.camera_id,
            {
                "lut_site": body.lut_site,
                "conf": body.conf,
                "classes": body.classes,
                "imgsz": body.imgsz,
                "tile": body.tile,
                "model": body.model,
                "tracker_start_frame": body.tracker_start_frame,
                "tracker_type": body.tracker_type,
                "tracker_refresh_every": body.tracker_refresh_every,
                "centre_marks": body.centre_marks,
                "steady_boxes": body.steady_boxes,
                "mark_rate_hz": body.mark_rate_hz,
            },
            lut_site=body.lut_site,
        )
    return _to_read(session)


@router.get(
    "/sessions",
    response_model=DetectionSessionListRead,
    summary="Every in-memory session, newest first — the camera wall polls this",
)
async def list_sessions() -> DetectionSessionListRead:
    """One request answers "which cameras are detecting" for every tile at once."""
    return DetectionSessionListRead(items=[_to_read(s) for s in detection_service.list_sessions()])


@router.get(
    "/sessions/{session_id}",
    response_model=DetectionSessionRead,
    summary="One session's live status — the overlay and the counts poll this",
)
async def get_session(session_id: str) -> DetectionSessionRead:
    session = detection_service.get_session(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no such session (sessions are tracked in memory — a restart clears them).",
        )
    return _to_read(session)


@router.get(
    "/sessions/{session_id}/marks",
    response_model=DetectionMarksRead,
    summary="Marks from `since` onward — the map polls incrementally",
)
async def get_marks(
    session_id: str,
    since: int = Query(default=0, ge=0),
) -> DetectionMarksRead:
    session = detection_service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such session.")
    # `since` counts ALL marks ever placed, including any dropped by the cap — so a
    # client that fell far behind never re-receives what no longer exists.
    start_at = max(0, since - session.marks_dropped)
    fresh = session.marks[start_at:]
    return DetectionMarksRead(
        next_index=session.marks_dropped + len(session.marks),
        marks=fresh,  # type: ignore[arg-type] — dicts of the Mark shape by construction
    )


@router.get(
    "/sessions/{session_id}/frame",
    summary="The latest detected frame as JPEG, boxes burned in — every source",
)
async def get_frame(session_id: str) -> Response:
    session = detection_service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such session.")
    if session.latest_jpeg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no preview frame yet — the run has not detected its first frame.",
        )
    return Response(
        content=session.latest_jpeg,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@router.get(
    "/sessions/{session_id}/export",
    summary="The run's marks with their attribute table — csv, geojson, or shp (zipped)",
)
async def export_marks(
    session_id: str,
    fmt: str = Query(default="csv", pattern="^(csv|geojson|shp)$"),
) -> Response:
    try:
        content, media_type, filename = detection_service.export_marks(session_id, fmt)
    except detection_service.DetectionError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.post(
    "/sessions/{session_id}/pause",
    response_model=DetectionSessionRead,
    summary="Pause or resume a video-file run between frames",
)
async def set_paused(
    session_id: str,
    body: DetectionPauseRequest,
    _: None = Depends(deps.require_writable),
) -> DetectionSessionRead:
    try:
        return _to_read(detection_service.set_paused(session_id, body.paused))
    except detection_service.DetectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.post(
    "/sessions/{session_id}/overlay",
    response_model=DetectionSessionRead,
    summary="Steer what the burned-in preview draws — the Boxes/Labels/Tracks chips",
)
async def set_overlay(
    session_id: str,
    body: DetectionOverlayRequest,
    _: None = Depends(deps.require_writable),
) -> DetectionSessionRead:
    """★ Why this exists: the run's MJPEG carries its boxes burned in (frame-synced
    by construction), which made the panel's overlay chips dead for the length of a
    run. This lets them steer the burn instead — a toggle lands on the next frame."""
    try:
        return _to_read(
            detection_service.set_overlay(
                session_id,
                boxes=body.boxes,
                labels=body.labels,
                tracks=body.tracks,
                hud=body.hud,
            )
        )
    except detection_service.DetectionError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/sessions/{session_id}/tracking",
    response_model=DetectionSessionRead,
    summary="Turn manual tracking on/off mid-run — the Start tracking button",
)
async def set_tracking(
    session_id: str,
    body: DetectionTrackingRequest,
    _: None = Depends(deps.require_writable),
) -> DetectionSessionRead:
    """Arm (or disarm) click-to-track. Off releases every lock; on lets the
    operator click detected objects to follow them."""
    try:
        return _to_read(detection_service.set_tracking(session_id, body.on))
    except detection_service.DetectionError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/sessions/{session_id}/track",
    response_model=DetectionSessionRead,
    summary="One click: track/untrack the object at a media pixel (lock=primary)",
)
async def track_at(
    session_id: str,
    body: DetectionTrackRequest,
    _: None = Depends(deps.require_writable),
) -> DetectionSessionRead:
    """Enqueue a click. The worker resolves the pixel against its freshest frame:
    on a tracked object it releases, on a detection it tracks; ``lock`` promotes
    to the highlighted primary instead. The new state shows on the next poll."""
    try:
        return _to_read(
            detection_service.queue_track_command(
                session_id, {"op": "lock" if body.lock else "toggle", "u": body.u, "v": body.v}
            )
        )
    except detection_service.DetectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.post(
    "/sessions/{session_id}/track-box",
    response_model=DetectionSessionRead,
    summary="Track what the operator DREW — a box in media pixels, detection or not",
)
async def track_box(
    session_id: str,
    body: DetectionTrackBoxRequest,
    _: None = Depends(deps.require_writable),
) -> DetectionSessionRead:
    """Enqueue a drawn rectangle. The worker seeds the visual tracker on it, so
    any object in the picture can be followed — one YOLO has no class for, or
    missed. Turns tracking on if it was off. ``name`` labels the new track."""
    x1, x2 = sorted((body.x1, body.x2))
    y1, y2 = sorted((body.y1, body.y2))
    try:
        return _to_read(
            detection_service.queue_track_box(session_id, (x1, y1, x2, y2), body.name)
        )
    except detection_service.DetectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.put(
    "/sessions/{session_id}/tracks/{track_id}/name",
    response_model=DetectionSessionRead,
    summary="Name a track — \"#3\" becomes \"white pickup\" in the table and the export",
)
async def name_track(
    session_id: str,
    track_id: int,
    body: DetectionTrackNameRequest,
    _: None = Depends(deps.require_writable),
) -> DetectionSessionRead:
    """Set or clear (null/blank) the operator's name for a track id. Allowed on
    a finished run: the name is about the data, and it rides the export."""
    try:
        return _to_read(detection_service.set_track_name(session_id, track_id, body.name))
    except detection_service.DetectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post(
    "/sessions/{session_id}/lock",
    response_model=DetectionSessionRead,
    summary="Set/clear the LOCKED primary by track id — the inspector's lock control",
)
async def set_lock(
    session_id: str,
    body: DetectionLockRequest,
    _: None = Depends(deps.require_writable),
) -> DetectionSessionRead:
    """Promote one tracked object to the highlighted primary (null clears it).
    An id that is already primary toggles off."""
    try:
        return _to_read(
            detection_service.queue_track_command(
                session_id, {"op": "lock_id", "track_id": body.track_id}
            )
        )
    except detection_service.DetectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.get(
    "/sessions/{session_id}/stream",
    summary="Every detected frame as MJPEG, boxes burned in — every source",
)
async def stream_frames(session_id: str) -> StreamingResponse:
    """★ The smooth preview. ``/frame`` re-fetches one JPEG at the page's poll rate
    (~2 Hz) — watching that IS "skipping frames" even though every frame was
    detected. This endpoint PUSHES each encoded frame the moment the detector
    finishes it, so the browser shows the run at its true rate with the boxes in
    the picture. The generator is sync — Starlette iterates it in a threadpool,
    so the waits never block the event loop."""
    if detection_service.get_session(session_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such session.")

    boundary = b"detectionframe"

    def gen() -> Iterator[bytes]:
        last = -1
        while True:
            s = detection_service.get_session(session_id)
            if s is None:
                return  # session evicted — stream over
            jpg, seq = s.latest_jpeg, s.jpeg_seq
            if jpg is not None and seq != last:
                last = seq
                yield (
                    b"--" + boundary + b"\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n"
                )
            elif s.status not in ("starting", "running"):
                return  # run over, final frame already sent
            else:
                time.sleep(0.02)

    return StreamingResponse(
        gen(),
        media_type="multipart/x-mixed-replace; boundary=detectionframe",
        headers={"Cache-Control": "no-store"},
    )


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Stop a session",
)
async def stop(
    session_id: str,
    db: AsyncSession = Depends(deps.get_db),
    _: None = Depends(deps.require_writable),
) -> Response:
    session = detection_service.get_session(session_id)
    if session is None or not detection_service.stop_session(session_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such session.")
    if session.camera_id:
        # the operator stopped it: the camera must not be re-started at the next boot
        try:
            await CameraService(db).record_detect(UUID(session.camera_id), None)
        except Exception:  # noqa: BLE001 — a camera removed meanwhile is not an error here
            pass
    return Response(status_code=status.HTTP_204_NO_CONTENT)
